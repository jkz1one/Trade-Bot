import asyncio
import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.execution import judgment
from app.execution.economics import CostAccounting, CostPolicy, UsageEvidence
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.journal import ExecutionJournal
from app.execution.judgment import JudgmentCoordinator, JudgmentLimits, JudgmentResult
from app.execution.runtime import (
    PaperRuntime,
    RuntimeAlreadyRunning,
    RuntimeLimits,
    model_key,
    runtime_lease,
)
from app.execution.runtime_cli import initialize, load, main
from tests.test_execution_rehearsal import NOW, decision, packet
from tests.test_execution_supervisor import context as supervisor_context
from tests.test_execution_supervisor import wait_until


def context(tmp_path, *, model=False, fault="NONE"):
    engine, venue, settings, feed, clock, supervisor = supervisor_context(tmp_path, fault=fault)
    engine.journal.enable_restore_fence(now=NOW)
    coordinator, key_file = None, None
    if model:
        coordinator = JudgmentCoordinator(
            CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1)),
            JudgmentLimits(process_timeout_seconds=3, request_timeout_seconds=2),
        )
        key_file = tmp_path / "model.key"
        key_file.write_text("fixture-only\n")
        key_file.chmod(0o600)
    runtime = PaperRuntime(
        supervisor,
        limits=RuntimeLimits(poll_seconds=0.05, max_age_seconds=1, cycle_timeout_seconds=6),
        judgment=coordinator,
        key_file=key_file,
        clock=lambda: clock[0],
    )
    runtime.enroll()
    return runtime, engine, venue, settings, feed, clock


async def start(runtime):
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    await wait_until(
        lambda: (
            task.done() or runtime.engine.journal.report(now=runtime.clock())["runtime"]["cycles"]
        )
    )
    if task.done():
        raise RuntimeError(f"Runtime startup failed: {task.result()}")
    return stop, task


@pytest.mark.anyio
async def test_stub_hold_is_durable_once_per_slot_across_restart(tmp_path):
    runtime, engine, venue, settings, _, clock = context(tmp_path)
    stop, task = await start(runtime)
    assert await runtime.cycle_once() == {"status": "SKIPPED", "reason": "SLOT_ALREADY_ATTEMPTED"}
    stop.set()
    assert await task == 0
    report = engine.journal.report(now=NOW)
    assert report["runtime"]["status"] == "STOPPED" and report["runtime"]["cycles"] == {
        "COMPLETE": 1
    }
    assert not report["halted"] and venue.submit_count == 0
    assert sum(e["kind"] == "HOLD" for e in report["events"]) == 1
    reopened = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    runtime.engine = reopened
    runtime.supervisor.engine = reopened
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    await wait_until(
        lambda: (
            engine.journal.report(now=clock[0])["runtime"]["generation"] == 2
            and engine.journal.report(now=clock[0])["supervisor"]["fresh"]
        )
    )
    stop.set()
    assert await task == 0
    assert engine.journal.report(now=NOW)["runtime"]["cycles"] == {"COMPLETE": 1}
    assert not engine.journal.report()["halted"]


@pytest.mark.anyio
async def test_duplicate_runner_cannot_mutate_live_owner(tmp_path):
    runtime, engine, _, _, _, _ = context(tmp_path)
    stop, task = await start(runtime)
    try:
        with pytest.raises(RuntimeAlreadyRunning):
            await runtime.run(asyncio.Event())
        assert engine.journal.report(now=NOW)["runtime"]["generation"] == 1
    finally:
        stop.set()
        await task


@pytest.mark.anyio
async def test_closed_session_does_not_read_quotes_or_call_model(tmp_path, monkeypatch):
    runtime, engine, venue, _, _, clock = context(tmp_path, model=True)
    clock[0] = NOW.replace(hour=22)

    def unavailable():
        raise AssertionError("Closed flat service must not read quotes")

    monkeypatch.setattr(runtime.supervisor.feed, "latest", unavailable)
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    await wait_until(lambda: engine.journal.report(now=clock[0])["supervisor"]["status"] == "IDLE")
    stop.set()
    assert await task == 0
    assert engine.journal.report()["runtime"]["cycles"] == {}
    assert engine.journal.report()["economics"]["unknown_calls"] == 0 and venue.submit_count == 0


@pytest.mark.anyio
async def test_known_model_receipt_governed_fake_order_once(tmp_path, monkeypatch):
    runtime, engine, venue, _, _, _ = context(tmp_path, model=True)
    calls = []

    async def propose(request, api_key):
        calls.append((request, api_key))
        return JudgmentResult(
            decision=decision(),
            counted_input_tokens=1000,
            usage=UsageEvidence(
                request_id="fixture-runtime",
                model="gpt-6-luna",
                input_tokens=1000,
                output_tokens=100,
            ),
        )

    monkeypatch.setattr(judgment, "run_judgment_process", propose)
    stop, task = await start(runtime)
    try:
        await wait_until(
            lambda: engine.journal.report(now=NOW)["runtime"]["cycles"] == {"COMPLETE": 1}
        )
        report = engine.journal.report(now=NOW)
        assert len(calls) == 1 and calls[0][1] == "fixture-only"
        assert report["orders"][0]["status"] == "OPEN" and venue.submit_count == 1
        assert report["economics"]["known_cost"] == "0.00015"
        assert Decimal(report["orders"][0]["intent"]["approved_notional"]) <= 10
        assert calls[0][0].packet.session_context["calendar"] == "XNYS"
        assert await runtime.cycle_once() == {
            "status": "SKIPPED",
            "reason": "SLOT_ALREADY_ATTEMPTED",
        }
    finally:
        stop.set()
        await task
    assert engine.journal.report()["halted"]  # stopping with an unresolved fake order


@pytest.mark.anyio
async def test_risk_rejection_records_decision_without_venue_attempt(tmp_path, monkeypatch):
    runtime, engine, venue, _, _, _ = context(tmp_path, model=True)

    async def propose(request, api_key):
        return JudgmentResult(
            decision=decision().model_copy(update={"invalidation_price": Decimal("10.2")}),
            counted_input_tokens=1000,
            usage=UsageEvidence(
                request_id="risk-rejected", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
        )

    monkeypatch.setattr(judgment, "run_judgment_process", propose)
    stop, task = await start(runtime)
    await wait_until(lambda: engine.journal.report(now=NOW)["runtime"]["cycles"] == {"BLOCKED": 1})
    stop.set()
    assert await task == 0 and venue.submit_count == 0
    with engine.journal.read() as db:
        row = db.execute("SELECT * FROM execution_runtime_cycles").fetchone()
        assert json.loads(row["decision_json"])["action"] == "OPEN_LONG"
        assert "INVALIDATION" in json.loads(row["result_json"])["reason"]


@pytest.mark.anyio
async def test_unknown_model_usage_is_auditable_hold_and_never_retried(tmp_path, monkeypatch):
    runtime, engine, venue, _, feed, clock = context(tmp_path, model=True)
    calls = []

    async def fail(request, api_key):
        calls.append(request)
        raise RuntimeError("private-model-message")

    monkeypatch.setattr(judgment, "run_judgment_process", fail)
    stop, task = await start(runtime)
    await wait_until(lambda: engine.journal.report(now=NOW)["runtime"]["cycles"] == {"COMPLETE": 1})
    clock[0] += timedelta(minutes=15)
    feed.publish("later", packet(clock[0]))
    await wait_until(
        lambda: sum(engine.journal.report(now=clock[0])["runtime"]["cycles"].values()) == 2
    )
    stop.set()
    assert await task == 0 and venue.submit_count == 0 and len(calls) == 1
    report = engine.journal.report(now=clock[0])
    assert report["economics"]["unknown_calls"] == 1 and report["economics"]["net_equity"] is None
    assert "private-model-message" not in json.dumps(report)


@pytest.mark.anyio
async def test_stop_during_model_leaves_interrupted_slot_and_cleans_up_before_lease_release(
    tmp_path, monkeypatch
):
    runtime, engine, venue, _, _, _ = context(tmp_path, model=True)
    entered, cleaned, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def block(request, api_key):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert engine.journal.report(now=NOW)["runtime"]["status"] == "STOPPING"
            await release.wait()
            cleaned.set()

    monkeypatch.setattr(judgment, "run_judgment_process", block)
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    await asyncio.wait_for(entered.wait(), 10)
    stop.set()
    await wait_until(lambda: engine.journal.report(now=NOW)["runtime"]["status"] == "STOPPING")
    task.cancel()
    task.cancel()
    await asyncio.sleep(0.02)
    with pytest.raises(RuntimeAlreadyRunning), runtime_lease(engine.journal.path):
        pass
    assert not cleaned.is_set() and not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set() and engine.journal.report()["runtime"]["cycles"] == {"INTERRUPTED": 1}
    assert (
        engine.journal.report()["halted"]
        and engine.journal.report()["economics"]["unknown_calls"] == 1
    )
    assert venue.submit_count == 0
    with runtime_lease(engine.journal.path):
        pass


@pytest.mark.anyio
async def test_supervision_failure_revokes_runtime_and_halts(tmp_path):
    runtime, engine, _, _, _, clock = context(tmp_path)
    clock[0] += timedelta(seconds=91)
    assert await runtime.run(asyncio.Event()) == 1
    report = engine.journal.report(now=clock[0])
    assert (
        report["runtime"]["status"] == "FAILED"
        and not report["runtime"]["fresh"]
        and report["halted"]
    )
    assert report["runtime"]["cycles"] == {}


@pytest.mark.anyio
async def test_interrupted_restart_retains_cycle_and_denies_new_slot(tmp_path):
    runtime, engine, _, _, feed, clock = context(tmp_path)
    runtime._claim()
    with engine.journal.write() as db:
        db.execute(
            "INSERT INTO execution_runtime_cycles VALUES(? ,?,'CLAIMED',?,NULL,1,? ,?,NULL,NULL)",
            (
                "PAPER:XNYS:" + NOW.isoformat(),
                runtime.owner,
                NOW.isoformat(),
                "a" * 64,
                packet().model_dump_json(),
            ),
        )
    runtime.owner = None  # simulate an owner that died, without graceful stop
    clock[0] += timedelta(minutes=15)
    feed.publish("new", packet(clock[0]))
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    await wait_until(lambda: engine.journal.report(now=clock[0])["runtime"]["generation"] == 2)
    assert await runtime.cycle_once() != {"status": "COMPLETE"}
    stop.set()
    await task
    report = engine.journal.report(now=clock[0])
    assert report["halted"] and report["runtime"]["cycles"] == {"INTERRUPTED": 1}
    assert report["runtime"]["generation"] == 2


@pytest.mark.anyio
async def test_runtime_health_gates_entries_and_costs_but_audits_hold(tmp_path):
    runtime, engine, _, _, _, _ = context(tmp_path)
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    with pytest.raises(ExecutionBlocked, match="RUNTIME_NOT_READY"):
        engine.prepare("stopped-entry", decision(), packet(), now=NOW)
    assert engine.prepare("hold", decision("HOLD", None), packet(), now=NOW) is None
    runtime._claim()
    with pytest.raises(ExecutionBlocked, match="RUNTIME_NOT_READY"):
        engine.prepare(
            "stale-entry",
            decision(),
            packet(NOW + timedelta(seconds=2)),
            now=NOW + timedelta(seconds=2),
        )
    runtime._publish("STOPPED")
    costs = CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1))
    with pytest.raises(ExecutionBlocked, match="RUNTIME_NOT_READY"):
        costs.begin("stopped-model", packet(), now=NOW)


def test_policy_change_and_late_enrollment_fail_closed(tmp_path):
    runtime, engine, _, _, _, _ = context(tmp_path)
    different = PaperRuntime(runtime.supervisor, limits=RuntimeLimits(), clock=lambda: NOW)
    with pytest.raises(ValueError, match="immutable"):
        different.enroll()
    runtime.limits = RuntimeLimits(poll_seconds=0.1)
    with pytest.raises(ExecutionBlocked, match="CONFIGURATION_CHANGED"):
        runtime._claim()
    assert engine.journal.report()["runtime"]["generation"] == 0


def test_runtime_requires_verified_pair_before_enrollment(tmp_path):
    engine, _, _, _, _, supervisor = supervisor_context(tmp_path)
    with pytest.raises(ValueError, match="Verified paired"):
        PaperRuntime(supervisor).enroll()
    with engine.journal.read() as db:
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_runtime'"
        ).fetchone()


@pytest.mark.parametrize(
    "mode,data",
    [
        (0o644, b"secret"),
        (0o600, b"bad key"),
        (0o600, b""),
        (0o600, b"x" * 514),
        (0o600, b"key\n\n"),
        (0o600, b"\xff"),
    ],
)
def test_private_key_rejects_broad_invalid_input(tmp_path, mode, data):
    path = tmp_path / "key"
    path.write_bytes(data)
    path.chmod(mode)
    with pytest.raises((ValueError, UnicodeError)):
        model_key(path)


def test_private_key_and_lease_reject_symlink_fifo(tmp_path):
    key = tmp_path / "key"
    key.write_text("fixture-only\n")
    key.chmod(0o600)
    assert model_key(key) == "fixture-only"
    alias = tmp_path / "alias"
    alias.symlink_to(key)
    with pytest.raises(OSError):
        model_key(alias)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError):
        model_key(fifo)
    path = tmp_path / "engine"
    Path(str(path) + ".runtime.lock").symlink_to(key)
    with pytest.raises(OSError), runtime_lease(path):
        pass


def test_cli_exclusive_init_ignores_live_env_and_report_is_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADER_MODE", "LIVE")
    monkeypatch.setenv("TRADER_LIVE_ENABLED", "true")
    directory = tmp_path / "fixture"
    assert main(["init", "--directory", str(directory), "--capital", "10", "--symbols", "SPY"]) == 0
    assert json.loads(capsys.readouterr().out)["agent"] == "stub-hold"
    before = {p.name: p.read_bytes() for p in directory.iterdir() if p.suffix == ".db"}
    assert main(["report", "--directory", str(directory)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["restore_fence"]["status"] == "VERIFIED" and report["config"]["capital"] == "10"
    assert before == {p.name: p.read_bytes() for p in directory.iterdir() if p.suffix == ".db"}
    assert main(["init", "--directory", str(directory), "--capital", "10", "--symbols", "SPY"]) == 1
    assert json.loads(capsys.readouterr().out)["error_class"] == "FileExistsError"
    with runtime_lease(directory / "execution.db"):
        runtime = load(directory)
    assert runtime.engine.settings.mode == "PAPER" and not runtime.engine.settings.live_enabled
    assert directory.stat().st_mode & 0o777 == 0o700


def test_cli_publishes_bounded_packet_without_model_or_venue_calls(tmp_path, capsys):
    directory = tmp_path / "fixture"
    initialize(directory, capital=Decimal(10), symbols=["SPY"])
    source = tmp_path / "packet.json"
    source.write_text(packet().model_dump_json())
    args = [
        "publish",
        "--directory",
        str(directory),
        "--packet-file",
        str(source),
        "--sample-id",
        "sample",
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["feed_sequence"] == 1
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["feed_sequence"] == 1
    source.write_bytes(b"x" * (256 * 1024 + 1))
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)["error_class"] == "ValueError"
    assert ExecutionJournal(directory / "execution.db").report()["runtime"]["cycles"] == {}


@pytest.mark.anyio
async def test_fenced_supervisor_read_defers_active_submission_without_renewing_truth(
    tmp_path, monkeypatch
):
    runtime, engine, venue, _, _, _ = context(tmp_path)
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    intent = engine.prepare("in-flight", decision(), packet(), now=NOW)
    engine._bind_fixture(venue, now=NOW)
    assert (
        engine._begin_attempt(
            intent.client_id,
            venue.account_id,
            now=NOW,
            packet=packet(),
            process_context={
                "adapter": "DURABLE_FIXTURE_PROCESS",
                "venue_id": venue.venue_id,
                "timeout_seconds": 2,
            },
        ).client_id
        == intent.client_id
    )
    before = engine.journal.report(now=NOW)

    async def no_read(*args, **kwargs):
        raise AssertionError("Must defer before starting a read child")

    import app.execution.process as processes

    monkeypatch.setattr(processes, "run_fixture_process", no_read)
    await runtime.supervisor._tick()
    after = engine.journal.report(now=NOW)
    assert after["revision"] == before["revision"] and after["supervisor"] == before["supervisor"]
    assert after["orders"][0]["status"] == "SUBMITTING" and not after["halted"]
    # Uncertain receipt is not indefinitely ignored; normal evidence checks remain.
    engine._uncertain(intent.client_id, RuntimeError(), now=NOW)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["issues"] == ["ATTEMPTED_ORDER_MISSING"]


@pytest.mark.anyio
async def test_slot_crossing_after_judgment_records_usage_but_never_dispatches(
    tmp_path, monkeypatch
):
    runtime, engine, venue, _, _, clock = context(tmp_path, model=True)

    async def late(request, api_key):
        clock[0] += timedelta(minutes=15)
        return JudgmentResult(
            decision=decision(),
            counted_input_tokens=1000,
            usage=UsageEvidence(
                request_id="late", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
        )

    monkeypatch.setattr(judgment, "run_judgment_process", late)
    # Isolate the one scheduled tick from the intentionally stale next-session feed.
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    assert await runtime.cycle_once() == {
        "status": "BLOCKED",
        "reason": "DECISION_SESSION_SLOT_EXPIRED",
    }
    report = engine.journal.report(now=clock[0])
    assert venue.submit_count == 0 and report["orders"] == []
    assert report["economics"]["known_cost"] == "0.00015" and report["runtime"]["cycles"] == {
        "BLOCKED": 1
    }


@pytest.mark.anyio
async def test_protective_sell_continues_while_scheduled_model_waits(tmp_path, monkeypatch):
    runtime, engine, venue, _, feed, clock = context(tmp_path, model=True)
    calls, waiting = [], asyncio.Event()

    async def propose(request, api_key):
        calls.append(request)
        if len(calls) == 2:
            waiting.set()
            await asyncio.Event().wait()
        return JudgmentResult(
            decision=decision(),
            counted_input_tokens=1000,
            usage=UsageEvidence(
                request_id="entry", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
        )

    monkeypatch.setattr(judgment, "run_judgment_process", propose)
    stop, task = await start(runtime)
    try:
        await wait_until(
            lambda: engine.journal.report(now=NOW)["runtime"]["cycles"] == {"COMPLETE": 1}
        )
        intent = engine.journal.report()["orders"][0]["intent"]
        venue.fill(
            intent["client_id"], Decimal(intent["quantity"]), Decimal(10), NOW, fill_id="buy"
        )
        await wait_until(lambda: engine.journal.report()["ledger"]["position"] is not None)
        clock[0] += timedelta(minutes=15)
        feed.publish("next-slot", packet(clock[0]))
        await asyncio.wait_for(waiting.wait(), 10)
        clock[0] += timedelta(seconds=1)
        feed.publish("stop-crossed", packet(clock[0], "9.4", "9.41"))
        await wait_until(lambda: venue.submit_count == 2)
        order = engine.journal.report()["orders"][-1]
        assert order["intent"]["side"] == "SELL" and not task.done()
        venue.fill(
            order["intent"]["client_id"],
            Decimal(order["intent"]["quantity"]),
            Decimal("9.4"),
            clock[0],
            fill_id="sell",
        )
        await wait_until(lambda: engine.journal.report()["ledger"]["position"] is None)
        assert len(calls) == 2 and not task.done()
    finally:
        stop.set()
        await task
    report = engine.journal.report(now=clock[0])
    assert report["runtime"]["cycles"] == {"COMPLETE": 1, "INTERRUPTED": 1}
    assert report["halted"] and report["economics"]["unknown_calls"] == 1


@pytest.mark.anyio
async def test_already_stopped_run_drains_without_claiming_a_cycle(tmp_path):
    runtime, engine, venue, _, _, _ = context(tmp_path)
    stop = asyncio.Event()
    stop.set()
    assert await runtime.run(stop) == 0
    report = engine.journal.report(now=NOW)
    assert report["runtime"]["status"] == "STOPPED" and report["runtime"]["cycles"] == {}
    assert not report["halted"] and venue.submit_count == 0


def test_cli_duplicate_lease_precedes_writable_startup_recovery(tmp_path):
    directory = tmp_path / "service"
    initialize(directory, capital=Decimal(10), symbols=["SPY"])
    with runtime_lease(directory / "execution.db"):
        before = {p.name: p.read_bytes() for p in directory.iterdir() if p.suffix == ".db"}
        assert main(["run", "--directory", str(directory)]) == 1
        assert before == {p.name: p.read_bytes() for p in directory.iterdir() if p.suffix == ".db"}


@pytest.mark.anyio
async def test_draining_tick_cannot_renew_stopping_supervisor_authority(tmp_path):
    runtime, engine, _, _, _, _ = context(tmp_path)
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    runtime.supervisor._finish("STOPPING")
    await runtime.supervisor._tick()
    report = engine.journal.report(now=NOW)
    assert report["supervisor"]["status"] == "STOPPING" and not report["supervisor"]["fresh"]
    with pytest.raises(ExecutionBlocked, match="SUPERVISOR_NOT_READY"):
        engine.prepare("stopping", decision(), packet(), now=NOW)
