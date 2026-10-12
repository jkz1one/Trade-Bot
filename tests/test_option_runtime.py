"""Continuous native PAPER, independent protection and truthful stored runtime state."""

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_degen_options import AT, frame, owned_strategy, policies
from test_option_execution import configuration, intent_for, ledger
from test_option_position_coordination import (
    MANAGE_AT,
    enter_position,
    management_frame,
    model,
    owned_manager,
)

from app.options.coordinator import DegenFrame
from app.options.engine import OptionExecution
from app.options.observer import OptionObserver
from app.options.runtime import MAX_PACKET_BYTES, OptionRuntime, read_packet
from app.options.runtime_cli import initialize
from app.options.runtime_models import RuntimePacket, RuntimePolicy, RuntimeSettings
from app.options.runtime_state import report
from app.options.venue import DurableOptionVenue


def policy(path, **changes):
    return RuntimePolicy.model_validate(
        {
            "feed_file": str(path / "feed.json"),
            "tick_seconds": 0.2,
            "heartbeat_max_age_seconds": 10,
            "feed_max_age_seconds": 10,
        }
        | changes
    )


def settings(path):
    _, limits, execution = configuration()
    setup, selection = policies()
    return RuntimeSettings(
        limits=limits, execution=execution, setup=setup, selection=selection, runtime=policy(path)
    )


def packet(r, at=AT, *, sequence=1, value=None, population=None):
    p = RuntimePacket(
        population_id=population or r.c.engine.limits.population_id,
        sequence=sequence,
        recorded_at=at,
        frame=value or DegenFrame(),
    )
    path = r.policy.feed_file
    with open(path, "w") as stream:
        stream.write(p.model_dump_json())
    os.chmod(path, 0o600)
    return p


def enable(r):
    r.running = True
    with r.c.engine.journal.write() as db:
        db.execute(
            "UPDATE execution_option_runtime SET status='RUNNING',heartbeat_at=? WHERE id=1",
            (r.c.now().isoformat(),),
        )


async def step(r):
    await r.tick()
    if r.task:
        await r.task


def state(c):
    with c.engine.journal.read() as db:
        return report(db, c.now())


@pytest.mark.parametrize(
    "changes",
    [
        {"feed_file": "relative"},
        {"tick_seconds": 0.1},
        {"tick_seconds": 6.0},
        {"tick_seconds": True},
        {"feed_max_age_seconds": 31},
        {"heartbeat_max_age_seconds": 1},
        {"version": "other"},
    ],
)
def test_invalid_policy(tmp_path, changes):
    with pytest.raises(ValidationError):
        policy(tmp_path, **changes)


@pytest.mark.parametrize("kind", ["costs", "model_limits", "management", "freshness"])
def test_unpaired_or_impossible_settings(tmp_path, kind):
    s = settings(tmp_path).model_dump()
    if kind == "costs":
        from app.execution.economics import CostPolicy

        s["execution"]["cost_policy"] = CostPolicy(total_budget="1", daily_budget=".1")
    elif kind == "model_limits":
        from app.execution.judgment import JudgmentLimits

        s["judgment_limits"] = JudgmentLimits()
    elif kind == "management":
        from app.options.position_reasoning import PositionReasoningPolicy

        s["position_policy"] = PositionReasoningPolicy(max_lease_seconds=5)
    else:
        s["runtime"]["heartbeat_max_age_seconds"] = 5
    with pytest.raises(ValidationError):
        RuntimeSettings.model_validate(s)


@pytest.mark.parametrize("damage", ["symlink", "permissions", "huge", "fifo", "invalid"])
def test_packet_read_is_bounded_private_and_regular(tmp_path, damage):
    path = tmp_path / "feed.json"
    if damage == "fifo":
        os.mkfifo(path, 0o600)
    else:
        path.write_text("x" * (MAX_PACKET_BYTES + 1) if damage == "huge" else "{}")
        path.chmod(0o644 if damage == "permissions" else 0o600)
        if damage == "symlink":
            target = tmp_path / "target"
            path.rename(target)
            path.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        read_packet(path)


def test_enrollment_one_owner_slot_claim_and_legacy_read_only_observer(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        assert state(c)["status"] == "NOT_ENROLLED"
        r = OptionRuntime(c, policy(tmp_path), create=True)
        with pytest.raises(ValueError):
            OptionRuntime(c, policy(tmp_path))
        packet(r)
        enable(r)
        asyncio.run(step(r))
        asyncio.run(step(r))
        s = state(c)
        assert s["status"] == "RUNNING" and s["freshness"] == "FRESH"
        assert s["cycles"] == {"COMPLETE": 1, "SKIPPED": 6}
        assert s["session"]["date"] == "2026-10-09"
        before = hashlib.sha256(c.engine.journal.path.read_bytes()).hexdigest()
        for _ in range(2):
            observed = OptionObserver(
                c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
            ).report()
            assert observed["status"] == "OK"
            assert observed["runtime"] == s and observed["worker_status"] == "RUNNING"
            assert observed["session_status"] == "OPEN" and not observed["execution_authority"]
        assert hashlib.sha256(c.engine.journal.path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "damage", ["missing", "stale", "future", "foreign", "regression", "conflict", "older_time"]
)
def test_feed_fault_halts_entry_retains_prior_sequence_and_still_supervises(tmp_path, damage):
    with owned_strategy(tmp_path) as (c, _, _, times, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        packet(r, sequence=2)
        asyncio.run(step(r))
        times[0] += timedelta(seconds=1)
        if damage == "missing":
            os.unlink(r.policy.feed_file)
        else:
            packet(
                r,
                at=times[0] + timedelta(seconds=1)
                if damage == "future"
                else (
                    AT - timedelta(seconds=20)
                    if damage == "stale"
                    else AT - timedelta(seconds=1)
                    if damage == "older_time"
                    else times[0]
                ),
                sequence=1 if damage == "regression" else 2 if damage == "conflict" else 3,
                population="other" if damage == "foreign" else None,
            )
        asyncio.run(step(r))
        s = state(c)
        assert s["status"] == "BLOCKED" and s["feed_sequence"] == 2
        with c.engine.journal.read() as db:
            assert c.engine._control(db)["halted"]
            assert c.engine._account(db, c.now()).entry_halted
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM execution_events WHERE kind='POSITION_SUPERVISED'"
                ).fetchone()[0]
                >= 3
            )
        packet(r, at=times[0], sequence=4)
        asyncio.run(step(r))
        assert state(c)["status"] == "RUNNING"
        assert c.engine.journal.report(now=c.now())["halted"]


def test_pending_cycle_skips_later_slot_and_cannot_queue_old_decision(tmp_path, monkeypatch):
    with owned_strategy(tmp_path) as (c, _, _, times, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        packet(r)
        enable(r)

        async def exercise():
            started, release = asyncio.Event(), asyncio.Event()

            async def waiting(_):
                started.set()
                await release.wait()
                return {"status": "HOLD"}

            monkeypatch.setattr(c, "cycle", waiting)
            await r.tick()
            await started.wait()
            times[0] += timedelta(minutes=10)
            packet(r, at=times[0], sequence=2)
            await r.tick()
            assert state(c)["latest_slots"][0]["reason"] == "MODEL_OR_CYCLE_IN_PROGRESS"
            release.set()
            await r.task
            await r.tick()
            assert state(c)["cycles"] == {"COMPLETE": 1, "SKIPPED": 8}

        asyncio.run(exercise())


def test_protection_runs_during_paid_management_wait_and_cost_is_retained(tmp_path, monkeypatch):
    with owned_manager(tmp_path) as (c, venue, times):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        enter_position(c, venue, times, monkeypatch)

        async def exercise():
            started, release = asyncio.Event(), asyncio.Event()

            async def wait(*_):
                started.set()
                await release.wait()

            model(monkeypatch, c, "MAINTAIN", after=wait)
            packet(r, at=MANAGE_AT, value=management_frame())
            await r.tick()
            await asyncio.wait_for(started.wait(), 10)
            times[0] += timedelta(seconds=1)
            f = management_frame(at=times[0])
            f = f.model_copy(
                update={
                    "underlyings": (
                        f.underlyings[0].model_copy(
                            update={"bid": Decimal(599), "ask": Decimal("599.01")}
                        ),
                    )
                }
            )
            packet(r, at=times[0], sequence=2, value=f)
            await r.tick()
            assert ledger(c.engine).position.exit_reason == "UNDERLYING_INVALIDATION"
            with c.engine.journal.read() as db:
                sells = db.execute(
                    "SELECT client_id FROM execution_orders WHERE json_extract(intent_json,'$.side')='SELL'"
                ).fetchall()
                assert len(sells) == 1
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NULL"
                    ).fetchone()[0]
                    == 1
                )
            assert intent_for(c.engine, sells[0][0]).side == "SELL"
            release.set()
            await r.task
            with c.engine.journal.read() as db:
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NULL"
                    ).fetchone()[0]
                    == 0
                )
                assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 2

        asyncio.run(exercise())


def test_stop_cancels_pending_cycle_before_owner_release_and_restart_never_resumes(
    tmp_path, monkeypatch
):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        packet(r)

        async def exercise():
            started, cancelled, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()

            async def waiting(_):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            monkeypatch.setattr(c, "cycle", waiting)
            task = asyncio.create_task(r.run(stop))
            await asyncio.wait_for(started.wait(), 10)
            stop.set()
            await task
            assert cancelled.is_set() and r.task is None and not r.running
            assert state(c)["status"] == "STOPPED"
            assert state(c)["cycles"]["INTERRUPTED"] == 1
            assert c.engine.journal.report(now=c.now())["halted"]
            stop = asyncio.Event()
            stop.set()
            await r.run(stop)
            assert c.engine.journal.report(now=c.now())["halted"]

        asyncio.run(exercise())


def test_clock_rollback_fails_and_cleans_pending_task(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, times, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        packet(r)
        enable(r)
        asyncio.run(step(r))
        times[0] -= timedelta(seconds=1)
        with pytest.raises(ValueError):
            asyncio.run(r.tick())


def test_runtime_heartbeat_gates_entry_and_is_truthful_when_stale(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, times, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        packet(r)
        enable(r)
        asyncio.run(step(r))
        times[0] += timedelta(seconds=10)
        assert state(c)["freshness"] == "STALE"
        with c.engine.journal.read() as db:
            assert "OPTION_RUNTIME_NOT_READY" in c.engine._account(db, c.now()).entry_blockers
        report_ = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
        assert report_["runtime"]["freshness"] == "STALE"
        assert report_["runtime"]["worker_liveness"] == "NOT_VERIFIED_BY_STORED_HEARTBEAT"


def test_native_runtime_entry_fill_and_subsequent_stop_without_extra_cycle(tmp_path):
    with owned_strategy(tmp_path) as (c, venue, _, times, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        f = frame()
        packet(r, value=f)
        asyncio.run(step(r))
        with c.engine.journal.read() as db:
            client = db.execute("SELECT client_id FROM execution_orders").fetchone()[0]
        intent = intent_for(c.engine, client)
        venue.fill(intent, intent.quantity, f.quotes[0], AT, fill_id="runtime-entry")
        times[0] += timedelta(seconds=1)
        f = f.model_copy(
            update={
                "quotes": tuple(
                    q.model_copy(update={"source_at": times[0], "received_at": times[0]})
                    for q in f.quotes
                ),
                "underlyings": (
                    f.underlyings[0].model_copy(
                        update={
                            "source_at": times[0],
                            "received_at": times[0],
                            "bid": Decimal(599),
                            "ask": Decimal("599.01"),
                        }
                    ),
                ),
            }
        )
        packet(r, at=times[0], sequence=2, value=f)
        asyncio.run(step(r))
        assert ledger(c.engine).position.exit_reason == "UNDERLYING_INVALIDATION"
        with c.engine.journal.read() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM execution_option_opportunities").fetchone()[0] == 1
            )
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 2
        observed = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
        assert observed["status"] == "OK" and observed["position"]["quantity"] == intent.quantity


def test_actual_management_attempt_remains_unknown_after_runtime_shutdown(tmp_path, monkeypatch):
    with owned_manager(tmp_path) as (c, venue, times):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        enter_position(c, venue, times, monkeypatch)
        r.running = False
        packet(r, at=MANAGE_AT, value=management_frame())

        async def exercise():
            started, stop = asyncio.Event(), asyncio.Event()

            async def wait(*_):
                started.set()
                await asyncio.Event().wait()

            model(monkeypatch, c, "MAINTAIN", after=wait)
            main = asyncio.create_task(r.run(stop))
            await asyncio.wait_for(started.wait(), 10)
            stop.set()
            await main
            assert state(c)["status"] == "STOPPED"
            assert state(c)["cycles"]["INTERRUPTED"] == 1
            with c.engine.journal.read() as db:
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NULL"
                    ).fetchone()[0]
                    == 1
                )
                assert c.engine._control(db)["halted"]
            assert r.task is None and not r.running

        asyncio.run(exercise())


def test_bad_feed_fences_pending_entry_before_snapshot_wait(tmp_path, monkeypatch):
    from test_option_entry_coordination import fake_model, owned_entry

    from app.options import entry_judgment

    with owned_entry(tmp_path) as (c, _, _, times):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        packet(r, value=frame())
        fake_model(monkeypatch, c)
        original_model = entry_judgment.run_entry_process
        original_supervise = c.supervise

        async def exercise():
            started, release = asyncio.Event(), asyncio.Event()

            async def waiting(request, secret):
                started.set()
                await release.wait()
                return await original_model(request, secret)

            monkeypatch.setattr(entry_judgment, "run_entry_process", waiting)
            await r.tick()
            await asyncio.wait_for(started.wait(), 10)
            times[0] += timedelta(seconds=1)
            os.unlink(r.policy.feed_file)

            async def supervise(*args):
                with c.engine.journal.read() as db:
                    assert c.engine._control(db)["halted"]
                release.set()
                await asyncio.sleep(0)
                return await original_supervise(*args)

            monkeypatch.setattr(c, "supervise", supervise)
            await r.tick()
            await r.task
            with c.engine.journal.read() as db:
                assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 0
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NOT NULL"
                    ).fetchone()[0]
                    == 1
                )

        asyncio.run(exercise())


def test_changed_runtime_policy_cannot_adopt_existing_enrollment(tmp_path):
    s = settings(tmp_path)
    directory = tmp_path / "run"
    initialize(directory, s, clock=lambda: AT)
    venue = DurableOptionVenue(directory / "venue.db")
    with OptionExecution.open(directory / "options.db", s.limits, s.execution, venue, now=AT) as e:
        from app.execution.engine import ExecutionBlocked
        from app.options.coordinator import DegenCoordinator

        c = DegenCoordinator(e, s.setup, s.selection, clock=lambda: AT)
        with pytest.raises(ExecutionBlocked):
            OptionRuntime(c, policy(tmp_path, feed_file=str(tmp_path / "other-feed.json")))
        assert not hasattr(e, "_option_runtime")


def test_native_supervisor_timeout_fails_runtime_and_releases_pending_work(tmp_path):
    from app.execution.process import FixtureProcessTimeout

    with owned_strategy(tmp_path) as (c, venue, _, _, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        packet(r)
        venue.fault = "STALL_READ"
        with pytest.raises(FixtureProcessTimeout):
            asyncio.run(r.run(asyncio.Event()))
        assert state(c)["status"] == "FAILED"
        assert c.engine.journal.report(now=c.now())["halted"]
        assert r.task is None and not r.running


def test_shutdown_request_immediately_fences_entry_during_a_snapshot_wait(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        packet(r)
        enable(r)
        r.stop = asyncio.Event()
        r.stop.set()
        with c.engine.journal.read() as db:
            assert not c.engine._control(db)["halted"]
            assert "OPTION_RUNTIME_STOP_REQUESTED" in c.engine._account(db, c.now()).entry_blockers


def test_runtime_html_reads_only_stored_state(tmp_path, monkeypatch):
    from test_option_observer import app_for

    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        packet(r)
        asyncio.run(step(r))
        client, _ = app_for(c, tmp_path)

        def forbidden(*_, **__):
            raise AssertionError("Observer attempted runtime work")

        monkeypatch.setattr("app.options.runtime.read_packet", forbidden)
        monkeypatch.setattr(c, "supervise", forbidden)
        html = client.get("/")
        assert html.status_code == 200 and "Runtime evidence" in html.text
        assert "RUNNING / FRESH" in html.text and "2026-10-09" in html.text


def test_create_only_settings_and_interrupted_restart(tmp_path):
    s = settings(tmp_path)
    directory = tmp_path / "run"
    initialize(directory, s, clock=lambda: AT)
    with pytest.raises(FileExistsError):
        initialize(directory, s, clock=lambda: AT)
    venue = DurableOptionVenue(directory / "venue.db")
    with (
        OptionExecution.open(directory / "options.db", s.limits, s.execution, venue, now=AT) as e,
        e.journal.write() as db,
    ):
        db.execute("UPDATE execution_option_runtime SET status='RUNNING'")
        db.execute(
            "INSERT INTO execution_option_runtime_slots VALUES(1,'2026-10-09','STARTED',NULL,?,NULL)",
            (AT.isoformat(),),
        )
    venue = DurableOptionVenue(directory / "venue.db")
    with OptionExecution.open(
        directory / "options.db", s.limits, s.execution, venue, now=AT
    ) as engine:
        from app.options.coordinator import DegenCoordinator

        c = DegenCoordinator(engine, s.setup, s.selection, clock=lambda: AT)
        OptionRuntime(c, s.runtime)
        assert state(c)["status"] == "FAILED"
        assert state(c)["cycles"]["INTERRUPTED"] == 1
        assert engine.journal.report(now=AT)["halted"]


def test_installed_cli_init_run_shutdown_and_reuse_rejection(tmp_path):
    path = tmp_path / "settings.json"
    s = settings(tmp_path)
    path.write_text(s.model_dump_json())
    path.chmod(0o600)
    directory = tmp_path / "runner"
    command = [sys.executable, "-I", "-m", "app.options.runtime_cli"]
    initialized = subprocess.run(
        command + ["init", "--settings", str(path), "--directory", str(directory)],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert initialized.returncode == 0, initialized.stderr
    stopped = subprocess.run(
        command + ["run", "--directory", str(directory), "--seconds", "1"],
        capture_output=True,
        check=False,
        text=True,
        timeout=25,
    )
    assert stopped.returncode == 0, stopped.stderr
    assert json.loads(stopped.stdout)["status"] == "STOPPED"
    assert not json.loads(stopped.stdout)["live_enabled"]
    with sqlite3.connect(directory / "options.db") as db:
        assert db.execute("SELECT halted FROM execution_control").fetchone()[0] == 1
        assert db.execute("SELECT status FROM execution_option_runtime").fetchone()[0] == "STOPPED"
        assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 0
    reused = subprocess.run(
        command + ["init", "--settings", str(path), "--directory", str(directory)],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert reused.returncode == 2 and json.loads(reused.stdout)["status"] == "UNAVAILABLE"
