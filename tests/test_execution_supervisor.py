import asyncio
import ctypes
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta
from decimal import Decimal

import pytest

from app.execution import judgment
from app.execution.economics import CostAccounting, CostPolicy, UsageEvidence
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.judgment import JudgmentCoordinator, JudgmentLimits, JudgmentResult
from app.execution.models import Intent
from app.execution.quote_feed import DurableQuoteFeed
from app.execution.supervisor import ExecutionSupervisor, SupervisorAlreadyRunning, SupervisorLimits
from tests.test_execution_process import context as engine_context
from tests.test_execution_rehearsal import NOW, decision, packet


def context(tmp_path, *, fault="NONE", limits=None):
    engine, venue, settings = engine_context(tmp_path, fault)
    feed = DurableQuoteFeed(tmp_path / "quotes.db", symbols=settings.initial_symbols)
    feed.publish("first", packet())
    clock = [NOW]
    supervisor = ExecutionSupervisor(
        engine,
        venue,
        feed,
        limits=limits
        or SupervisorLimits(poll_seconds=0.05, tick_timeout_seconds=3, max_age_seconds=4),
        clock=lambda: clock[0],
    )
    return engine, venue, settings, feed, clock, supervisor


async def wait_until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.01)


async def start(supervisor, engine, clock):
    stop = asyncio.Event()
    task = asyncio.create_task(supervisor.run(stop))
    await wait_until(
        lambda: task.done() or engine.journal.report(now=clock[0])["supervisor"]["fresh"]
    )
    if task.done():
        raise RuntimeError(f"Supervisor failed startup: {task.result()}")
    return stop, task


async def finish(stop, task):
    stop.set()
    return await asyncio.wait_for(task, 10)


async def enter(engine, venue, *, at=NOW, partial=False, proposal=None, p=None, source="entry"):
    p = p or packet(at)
    intent = engine.prepare(source, proposal or decision(), p, now=at)
    assert await engine.dispatch_async(intent.client_id, venue, now=at, packet=p) == "OPEN"
    quantity = (intent.quantity / 2).quantize(Decimal(".00000001")) if partial else intent.quantity
    venue.fill(intent.client_id, quantity, Decimal(10), at, fill_id="entry-fill")
    reconciled = await engine.reconcile_fixture(venue, now=at)
    assert reconciled["reconciled"] and not reconciled["issues"]
    with engine.journal.read() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM execution_fills WHERE fill_id='entry-fill'"
            ).fetchone()[0]
            == 1
        )
        state = json.loads(
            db.execute("SELECT ledger_json FROM execution_control WHERE id=1").fetchone()[0]
        )
        assert Decimal(state["position"]["quantity"]) == quantity
    return intent


def test_quote_feed_stable_samples_private_files_and_read_only_bytes(tmp_path):
    engine, _, _, feed, _, _ = context(tmp_path)
    initial = feed.path.read_bytes()
    assert feed.publish("first", packet()) == 1 and feed.latest()[0] == 1
    assert feed.path.read_bytes() == initial
    assert feed.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="CONFLICT"):
        feed.publish("first", packet(NOW, "9.98", "10"))
    feed.publish("next", packet(NOW + timedelta(seconds=1)))
    assert feed.publish("first", packet()) == 1 and feed.latest()[0] == 2
    with pytest.raises(ValueError, match="REGRESSION"):
        feed.publish("older", packet())
    with pytest.raises(ValueError):
        DurableQuoteFeed(engine.journal.path)
    with pytest.raises(FileExistsError):
        DurableQuoteFeed(feed.path, symbols=feed.symbols)


def test_feed_identity_and_symbol_changes_fail_closed(tmp_path):
    _, _, _, feed, _, _ = context(tmp_path)
    p = packet()
    p.candidates[0].quote.symbol = "FOREIGN"
    with pytest.raises(ValueError):
        feed.publish("foreign", p)
    with sqlite3.connect(feed.path) as db:
        meta = json.loads(db.execute("SELECT payload FROM quote_meta").fetchone()[0])
        meta["feed_id"] = "changed"
        db.execute("UPDATE quote_meta SET payload=?", (json.dumps(meta),))
    with pytest.raises(ValueError, match="identity changed"):
        feed.latest()


@pytest.mark.anyio
async def test_enrolled_but_stopped_or_stale_supervisor_cannot_grant_entry(tmp_path):
    engine, _, _, _, clock, supervisor = context(tmp_path)
    with pytest.raises(ExecutionBlocked, match="SUPERVISOR_NOT_READY"):
        engine.prepare("stopped", decision(), packet(), now=NOW)
    stop, task = await start(supervisor, engine, clock)
    try:
        clock[0] = NOW + timedelta(seconds=5)
        with pytest.raises(ExecutionBlocked, match="SUPERVISOR_NOT_READY"):
            engine.prepare("stale", decision(), packet(clock[0]), now=clock[0])
        assert not engine.journal.report(now=clock[0])["supervisor"]["fresh"]
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_stale_supervisor_rejects_prepared_buy_before_any_venue_call(tmp_path):
    engine, venue, _, _, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        intent = engine.prepare("prepared", decision(), packet(), now=NOW)
        clock[0] = NOW + timedelta(seconds=5)
        assert (
            await engine.dispatch_async(
                intent.client_id, venue, now=clock[0], packet=packet(clock[0])
            )
            == "REJECTED"
        )
        assert venue.submit_count == 0
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_polling_protective_sell_is_idempotent_and_never_buys(tmp_path):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    engine.journal.enable_restore_fence(now=NOW)
    stop, task = await start(supervisor, engine, clock)
    try:
        entry = await enter(engine, venue)
        clock[0] += timedelta(seconds=1)
        feed.publish("stop", packet(clock[0], "9.4", "9.41"))
        await wait_until(lambda: venue.submit_count == 2)
        await wait_until(
            lambda: any(
                o["intent"]["side"] == "SELL" and o["status"] == "OPEN"
                for o in engine.journal.report()["orders"]
            )
        )
        first = engine.journal.report()["orders"][-1]
        await asyncio.sleep(0.3)
        assert venue.submit_count == 2
        assert (
            len([o for o in engine.journal.report()["orders"] if o["intent"]["side"] == "SELL"])
            == 1
        )
        assert Decimal(first["intent"]["quantity"]) == entry.quantity
        assert engine.journal.report()["restore_fence"]["status"] == "VERIFIED"
    finally:
        assert await finish(stop, task) == 0
    report = engine.journal.report(now=clock[0])
    assert report["supervisor"]["status"] == "STOPPED" and not report["supervisor"]["fresh"]
    assert report["halted"]  # Stopping with a live fake position/reservation reduces authority.


@pytest.mark.anyio
async def test_model_busy_unknown_receipt_does_not_delay_protective_exit(tmp_path, monkeypatch):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    costs = CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1))
    coordinator = JudgmentCoordinator(costs, JudgmentLimits())

    async def accepted(request, key):
        return JudgmentResult(
            decision=decision(),
            usage=UsageEvidence(
                request_id="resp-entry", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
            counted_input_tokens=1000,
        )

    monkeypatch.setattr(judgment, "run_judgment_process", accepted)
    stop, task = await start(supervisor, engine, clock)
    model = None
    try:
        out = await coordinator.decide(
            "entry", packet(), api_key="fixture-only", now=NOW, clock=lambda: clock[0]
        )
        await enter(engine, venue, proposal=out.result.decision, p=out.packet)
        real_spawn = asyncio.create_subprocess_exec
        pid_path = tmp_path / "model.pid"
        source = f"import sys,os,time,pathlib\nsys.stdin.read()\npathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))\ntime.sleep(60)"

        async def spawn(*args, **kwargs):
            if args[-1] == "app.execution.judgment_worker":
                return await real_spawn(sys.executable, "-c", source, **kwargs)
            return await real_spawn(*args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        # Restore the real bounded transport after the scripted initial judgment.
        monkeypatch.setattr(judgment, "run_judgment_process", real_transport)
        model = asyncio.create_task(
            coordinator.decide(
                "busy-hold", packet(), api_key="fixture-only", now=NOW, clock=lambda: clock[0]
            )
        )
        await wait_until(pid_path.exists)
        clock[0] += timedelta(seconds=1)
        feed.publish("stop", packet(clock[0], "9.4", "9.41"))
        await wait_until(lambda: venue.submit_count == 2)
        assert not model.done()
        assert engine.journal.report(now=clock[0])["economics"]["unknown_calls"] == 1
        assert engine.journal.report()["orders"][-1]["intent"]["side"] == "SELL"
        pid = int(pid_path.read_text())
        model.cancel()
        with pytest.raises(asyncio.CancelledError):
            await model
        model = None
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if model is not None:
            model.cancel()
            await asyncio.gather(model, return_exceptions=True)
        await finish(stop, task)


# Preserve the original function before per-test monkeypatches replace it.
real_transport = judgment.run_judgment_process


@pytest.mark.anyio
async def test_unresolved_partial_buy_halts_without_sale_or_cancel(tmp_path):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        await enter(engine, venue, partial=True)
        clock[0] += timedelta(seconds=1)
        feed.publish("stop", packet(clock[0], "9.4", "9.41"))
        await wait_until(lambda: engine.journal.report()["halted"])
        assert venue.submit_count == 1
        assert len(engine.journal.report()["orders"]) == 1
        assert engine.journal.report()["orders"][0]["active"]
    finally:
        await finish(stop, task)


@pytest.mark.anyio
@pytest.mark.parametrize("bad", ["stale", "future", "missing", "insane"])
async def test_bad_market_evidence_halts_without_heartbeat_or_dispatch(tmp_path, bad):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    if bad == "stale":
        clock[0] = NOW + timedelta(seconds=91)
    elif bad == "future":
        feed.publish("future", packet(NOW + timedelta(seconds=1)))
    elif bad == "missing":
        with sqlite3.connect(feed.path) as db:
            db.execute("DELETE FROM quote_samples")
    else:
        feed.publish("insane", packet(NOW, "11", "10"))
    assert await supervisor.run(asyncio.Event()) == 1
    report = engine.journal.report(now=clock[0])
    assert report["halted"] and report["supervisor"]["status"] == "FAILED"
    assert not report["supervisor"]["fresh"] and venue.submit_count == 0


@pytest.mark.anyio
async def test_quote_history_rollback_blocks_healthy_lease(tmp_path):
    engine, _, _, feed, clock, supervisor = context(tmp_path)
    feed.publish("second", packet(NOW + timedelta(seconds=1)))
    clock[0] += timedelta(seconds=1)
    stop, task = await start(supervisor, engine, clock)
    try:
        with sqlite3.connect(feed.path) as db:
            db.execute("DELETE FROM quote_samples WHERE sequence=2")
        assert await asyncio.wait_for(task, 10) == 1
        assert engine.journal.report()["supervisor"]["status"] == "FAILED"
        assert engine.journal.report()["halted"]
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_duplicate_supervisor_cannot_replace_active_owner(tmp_path):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        second = ExecutionSupervisor(
            engine, venue, feed, limits=supervisor.limits, clock=lambda: clock[0]
        )
        generation = engine.journal.report()["supervisor"]["generation"]
        with pytest.raises(SupervisorAlreadyRunning):
            await second.run(asyncio.Event())
        assert engine.journal.report()["supervisor"]["generation"] == generation
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_closed_market_flat_is_idle_and_uses_no_venue_read(tmp_path, monkeypatch):
    engine, _, _, _, clock, supervisor = context(tmp_path)
    clock[0] = NOW.replace(hour=22)

    async def forbidden(*args, **kwargs):
        pytest.fail("No fixture read needed during flat closed sessions")

    monkeypatch.setattr(engine, "reconcile_fixture", forbidden)
    stop = asyncio.Event()
    task = asyncio.create_task(supervisor.run(stop))
    await wait_until(lambda: engine.journal.report()["supervisor"]["status"] == "IDLE")
    assert not engine.journal.report(now=clock[0])["supervisor"]["fresh"]
    assert await finish(stop, task) == 0


@pytest.mark.anyio
async def test_stale_supervisor_prevents_new_model_receipt(tmp_path):
    engine, _, _, _, _, _ = context(tmp_path)
    costs = CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1))
    with pytest.raises(ExecutionBlocked, match="SUPERVISOR_NOT_READY"):
        costs.begin("no-health", packet(), now=NOW)
    assert engine.journal.report()["economics"]["unknown_calls"] == 0


def test_policy_is_frozen_and_requires_enrollment_before_any_order(tmp_path):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        ExecutionSupervisor(engine, venue, feed, limits=SupervisorLimits(), clock=lambda: clock[0])
    with pytest.raises(ValueError):
        SupervisorLimits(poll_seconds=5, tick_timeout_seconds=10, max_age_seconds=10)
    with pytest.raises(ValueError):
        ExecutionSupervisor(engine, object(), feed)
    with pytest.raises(ValueError):
        ExecutionSupervisor(engine, venue, feed, limits=SupervisorLimits(max_age_seconds=91))
    assert supervisor.limits.max_age_seconds == 4


@pytest.mark.anyio
async def test_fixture_read_timeout_never_publishes_healthy_heartbeat(tmp_path, monkeypatch):
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    engine, _, _, _, _, supervisor = context(
        tmp_path,
        fault="STALL_READ",
        limits=SupervisorLimits(poll_seconds=0.01, tick_timeout_seconds=0.2, max_age_seconds=1),
    )
    assert await supervisor.run(asyncio.Event()) == 1
    report = engine.journal.report(now=NOW)
    assert report["halted"] and not report["supervisor"]["fresh"]
    assert report["supervisor"]["last_result"]["error_class"] == "TimeoutError"


@pytest.mark.anyio
async def test_changed_runtime_configuration_fails_and_revokes_entry_health(tmp_path):
    engine, _, _, _, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        supervisor.limits = SupervisorLimits()
        assert await asyncio.wait_for(task, 10) == 1
        report = engine.journal.report(now=clock[0])
        assert report["halted"] and report["supervisor"]["status"] == "FAILED"
        assert not report["supervisor"]["fresh"]
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_tick_storage_failure_cannot_grant_entry_health(tmp_path):
    engine, _, _, _, _, supervisor = context(tmp_path)
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER execution_fail_health BEFORE UPDATE ON execution_supervisor WHEN NEW.status='RUNNING' BEGIN SELECT RAISE(ABORT,'failure'); END"
        )
    assert await supervisor.run(asyncio.Event()) == 1
    report = engine.journal.report(now=NOW)
    assert report["supervisor"]["heartbeat_at"] is None
    assert report["supervisor"]["status"] == "FAILED" and report["halted"]


@pytest.mark.anyio
async def test_manual_halt_is_not_cleared_by_valid_ticks_or_stop_exit(tmp_path):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        await enter(engine, venue)
        engine.halt("Operator review required", now=NOW)
        clock[0] += timedelta(seconds=1)
        feed.publish("stop", packet(clock[0], "9.4", "9.41"))
        await wait_until(
            lambda: (
                engine.journal.report(now=clock[0])["supervisor"]["last_result"]["status"]
                == "BLOCKED"
            )
        )
        alert_count = len(engine.journal.alerts())
        await asyncio.sleep(0.3)
        assert engine.journal.report()["halted"] and venue.submit_count == 1
        assert len(engine.journal.alerts()) == alert_count
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_definitively_canceled_partial_sell_allows_only_residual_quantity(tmp_path):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        entry = await enter(engine, venue)
        clock[0] += timedelta(seconds=1)
        feed.publish("stop", packet(clock[0], "9.4", "9.41"))
        await wait_until(lambda: venue.submit_count == 2)
        row = engine.journal.report()["orders"][-1]
        first = Intent.model_validate(row["intent"])
        partial = (first.quantity / 2).quantize(Decimal(".00000001"))
        venue.fill(first.client_id, partial, first.limit_price, clock[0], fill_id="partial-sell")
        venue.terminal(
            first.client_id, "CANCELED", clock[0]
        )  # Local fake terminal evidence, never a broker call.
        clock[0] += timedelta(seconds=1)
        feed.publish("after-cancel", packet(clock[0], "9.39", "9.40"))
        await wait_until(lambda: venue.submit_count == 3)
        row = engine.journal.report()["orders"][-1]
        second = Intent.model_validate(row["intent"])
        assert second.side == "SELL" and second.quantity == entry.quantity - partial
        assert second.client_id != first.client_id
        assert second.original_invalidation == entry.original_invalidation
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_foreign_feed_or_oversized_packet_cannot_renew_authority(tmp_path):
    engine, _, _, feed, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        with sqlite3.connect(feed.path) as db:
            db.execute("UPDATE quote_samples SET payload=?", ("x" * 262145,))
        assert await asyncio.wait_for(task, 10) == 1
        assert not engine.journal.report(now=clock[0])["supervisor"]["fresh"]
        assert engine.journal.report()["halted"]
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_repeated_cancellation_reaps_read_child_and_retains_stop_gate(tmp_path, monkeypatch):
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    engine, _, _, _, _, supervisor = context(tmp_path, fault="STALL_READ")
    children = []
    real_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        child = await real_spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(supervisor.run(asyncio.Event()))
    await wait_until(lambda: bool(children))
    task.cancel()
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(c.returncode is not None for c in children)
    for child in children:
        with pytest.raises(ProcessLookupError):
            os.kill(child.pid, 0)
    report = engine.journal.report(now=NOW)
    assert report["supervisor"]["status"] == "STOPPED" and not report["supervisor"]["fresh"]
    assert report["halted"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper owns orphan cleanup")
def test_actual_supervisor_parent_crash_keeps_halt_and_requires_explicit_review(tmp_path):
    engine, venue, settings, feed, clock, supervisor = context(tmp_path)
    engine.journal.enable_restore_fence(now=NOW)
    marker = tmp_path / "read-child.pid"
    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(original), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        pytest.skip("Subreaper unavailable")
    child_pid = None
    script = '''
import asyncio,os,sys
from pathlib import Path
from datetime import datetime
from app.config import Settings
from app.execution.engine import ExecutionEngine
from app.execution.models import ExecutionLimits
from app.execution.durable_fixture import DurableFixtureVenue
from app.execution.quote_feed import DurableQuoteFeed
from app.execution.supervisor import ExecutionSupervisor,SupervisorLimits
at=datetime.fromisoformat(sys.argv[6])
engine=ExecutionEngine(sys.argv[1],Settings(_env_file=None,mode="PAPER",live_enabled=False,starting_capital=10),limits=ExecutionLimits.model_validate_json(sys.argv[4]))
venue=DurableFixtureVenue(sys.argv[2])
feed=DurableQuoteFeed(sys.argv[3])
supervisor=ExecutionSupervisor(engine,venue,feed,limits=SupervisorLimits.model_validate_json(sys.argv[5]),clock=lambda:at)
source="""
import os
from pathlib import Path
from app.execution import worker
original=worker._stall
def stalled(parent):
    Path(MARKER).write_text(str(os.getpid()))
    original(parent)
worker._stall=stalled
raise SystemExit(worker.main())
""".replace("MARKER",repr(sys.argv[7]))
real_spawn=asyncio.create_subprocess_exec
async def spawn(*args,**kwargs):
    return await real_spawn(sys.executable,"-c",source,**kwargs)
asyncio.create_subprocess_exec=spawn
async def run():
    asyncio.create_task(supervisor.run(asyncio.Event()))
    async with asyncio.timeout(10):
        while not engine.journal.report(now=at)["supervisor"]["fresh"]: await asyncio.sleep(.01)
        venue.fault="STALL_READ"
        while not Path(sys.argv[7]).exists(): await asyncio.sleep(.01)
    os._exit(93)
asyncio.run(run())
'''
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(engine.journal.path),
                str(venue.path),
                str(feed.path),
                engine.limits.model_dump_json(),
                supervisor.limits.model_dump_json(),
                NOW.isoformat(),
                str(marker),
            ],
            capture_output=True,
            check=False,
            timeout=15,
        )
        assert result.returncode == 93, result.stderr
        child_pid = int(marker.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(child_pid, os.WNOHANG)
            if pid:
                child_pid = None
                assert os.waitstatus_to_exitcode(status) == 96
                break
            time.sleep(0.01)
        assert child_pid is None
        restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
        resumed = ExecutionSupervisor(
            restarted, venue, feed, limits=supervisor.limits, clock=lambda: clock[0]
        )

        async def review():
            stop = asyncio.Event()
            task = asyncio.create_task(resumed.run(stop))
            try:
                await wait_until(
                    lambda: (
                        restarted.journal.report(now=NOW)["supervisor"]["status"] == "RUNNING"
                        and restarted.journal.report(now=NOW)["supervisor"]["generation"] == 2
                    )
                )
                report = restarted.journal.report(now=NOW)
                assert report["halted"] and report["halt_reason"] == "INTERRUPTED_SUPERVISOR"
                assert not report["supervisor"]["fresh"]
                restarted.resume("Reviewed complete fixture truth after interruption", now=NOW)
                await wait_until(lambda: restarted.journal.report(now=NOW)["supervisor"]["fresh"])
                assert restarted.journal.report()["restore_fence"]["status"] == "VERIFIED"
                assert venue.submit_count == 0
            finally:
                await finish(stop, task)

        asyncio.run(review())
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child_pid, 0)
        libc.prctl(36, original.value, 0, 0, 0)


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["prepare", "fill"])
async def test_inflight_older_read_cannot_replace_new_account_evidence(
    tmp_path, monkeypatch, change
):
    from types import SimpleNamespace

    from app.execution import process

    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    supervisor._claim()
    await supervisor._tick()
    first_health = engine.journal.report(now=NOW)["supervisor"]
    intent = None
    if change == "fill":
        intent = engine.prepare("entry", decision(), packet(), now=NOW)
        assert (
            await engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet()) == "OPEN"
        )
    older = venue.snapshot(NOW)
    entered, release = asyncio.Event(), asyncio.Event()
    real = process.run_fixture_process

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(snapshot=older)

    monkeypatch.setattr(process, "run_fixture_process", delayed)
    clock[0] += timedelta(seconds=1)
    feed.publish("next", packet(clock[0]))
    tick = asyncio.create_task(supervisor._tick())
    await entered.wait()
    if change == "prepare":
        intent = engine.prepare("entry", decision(), packet(clock[0]), now=clock[0])
    else:
        venue.fill(intent.client_id, intent.quantity, Decimal(10), clock[0], fill_id="new-fill")
        assert engine.reconcile(venue.snapshot(clock[0]), now=clock[0])["new_fills"] == 1
    before = engine.journal.report(now=clock[0])
    release.set()
    await tick
    after = engine.journal.report(now=clock[0])
    assert not after["halted"] and after["orders"] == before["orders"]
    assert after["ledger"] == before["ledger"]
    assert after["supervisor"]["heartbeat_at"] == first_health["heartbeat_at"]
    assert after["supervisor"]["last_feed_sequence"] == 1
    assert after["events"][0]["kind"] == "FIXTURE_READ_SUPERSEDED"
    monkeypatch.setattr(process, "run_fixture_process", real)
    await supervisor._tick()
    assert engine.journal.report(now=clock[0])["supervisor"]["last_feed_sequence"] == 2
    supervisor._finish("STOPPED")


@pytest.mark.anyio
async def test_unchanged_epoch_account_mismatch_still_fails_closed(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.execution import process

    engine, venue, _, _, _, supervisor = context(tmp_path)
    bad = venue.snapshot(NOW).model_copy(
        update={"cash": Decimal(9), "safe_buying_power": Decimal(9)}
    )

    async def mismatch(*args, **kwargs):
        return SimpleNamespace(snapshot=bad)

    monkeypatch.setattr(process, "run_fixture_process", mismatch)
    assert await supervisor.run(asyncio.Event()) == 1
    report = engine.journal.report(now=NOW)
    assert report["halted"] and report["issues"]
    assert not report["supervisor"]["fresh"] and venue.submit_count == 0


@pytest.mark.anyio
async def test_read_completion_cannot_renew_health_with_expired_quote(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.execution import process

    engine, venue, _, _, clock, supervisor = context(tmp_path)
    clock[0] += timedelta(seconds=89)

    async def completing(*args, **kwargs):
        snapshot = venue.snapshot(clock[0])
        clock[0] += timedelta(seconds=2)
        return SimpleNamespace(snapshot=snapshot)

    monkeypatch.setattr(process, "run_fixture_process", completing)
    assert await supervisor.run(asyncio.Event()) == 1
    report = engine.journal.report(now=clock[0])
    assert report["halted"] and report["supervisor"]["heartbeat_at"] is None
    assert venue.submit_count == 0


@pytest.mark.anyio
async def test_corrupted_quote_universe_cannot_grant_flat_health(tmp_path):
    engine, venue, _, feed, _, supervisor = context(tmp_path)
    bad = packet().model_dump(mode="json")
    bad["candidates"][0]["quote"]["symbol"] = "FOREIGN"
    with sqlite3.connect(feed.path) as db:
        db.execute("UPDATE quote_samples SET payload=?", (json.dumps(bad),))
    assert await supervisor.run(asyncio.Event()) == 1
    assert engine.journal.report()["halted"] and venue.submit_count == 0


@pytest.mark.anyio
async def test_intraday_session_exit_runs_without_model(tmp_path):
    engine, venue, _, feed, clock, supervisor = context(tmp_path)
    stop, task = await start(supervisor, engine, clock)
    try:
        await enter(engine, venue)
        clock[0] = NOW.replace(hour=19, minute=46)
        feed.publish("session-exit", packet(clock[0], "10.1", "10.11"))
        await wait_until(lambda: venue.submit_count == 2)
        report = engine.journal.report(now=clock[0])
        assert report["orders"][-1]["intent"]["side"] == "SELL"
        assert report["ledger"]["management"]["exit_reason"] == "SESSION_EXIT"
    finally:
        await finish(stop, task)


@pytest.mark.anyio
async def test_stop_revokes_entry_health_before_read_cleanup_finishes(tmp_path, monkeypatch):
    from app.execution import process

    engine, _, _, _, clock, supervisor = context(tmp_path)
    costs = CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1))
    stop, task = await start(supervisor, engine, clock)
    costs.begin("entry-before-stop", packet(), now=NOW)
    costs.settle(
        "entry-before-stop",
        UsageEvidence(
            request_id="resp-before-stop", model="gpt-6-luna", input_tokens=1000, output_tokens=100
        ),
        decision(),
        now=NOW,
    )
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def delayed(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            raise

    monkeypatch.setattr(process, "run_fixture_process", delayed)
    try:
        await entered.wait()
        stop.set()
        await cleaning.wait()
        report = engine.journal.report(now=NOW)
        assert report["supervisor"]["status"] == "STOPPING"
        assert not report["supervisor"]["fresh"] and not task.done()
        with pytest.raises(ExecutionBlocked, match="EXECUTION_SUPERVISOR_NOT_READY"):
            engine.prepare("entry-before-stop", decision(), packet(), now=NOW)
        with pytest.raises(ExecutionBlocked, match="EXECUTION_SUPERVISOR_NOT_READY"):
            costs.begin("during-stop", packet(), now=NOW)
        assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 0
    finally:
        release.set()
        await finish(stop, task)
