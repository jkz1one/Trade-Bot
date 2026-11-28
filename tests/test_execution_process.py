import asyncio
import os
import sqlite3
import sys
import time
from datetime import timedelta
from decimal import Decimal

import pytest

import app.execution.process as process_module
from app.config import Settings
from app.execution.durable_fixture import DurableFixtureVenue
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.models import ExecutionLimits
from app.execution.process import FixtureProcessTimeout
from tests.test_execution_rehearsal import NOW, decision, packet

D = Decimal


def context(tmp_path, fault="NONE"):
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    limits = ExecutionLimits(
        max_entry_notional=10,
        max_position_notional=10,
        total_loss_limit=10,
        daily_loss_limit=10,
        process_timeout_seconds=2,
    )
    engine = ExecutionEngine(tmp_path / "engine.db", settings, limits=limits)
    venue = DurableFixtureVenue(tmp_path / "venue.db", capital=D(10), fault=fault)
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    return engine, venue, settings


@pytest.fixture
def children(monkeypatch):
    captured = []
    spawn = asyncio.create_subprocess_exec

    async def observe(*args, **kwargs):
        child = await spawn(*args, **kwargs)
        captured.append((child, kwargs))
        return child

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", observe)
    return captured


def reaped(children):
    assert children
    for child, _ in children:
        assert child.returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(child.pid, 0)


async def wait_until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.01)


def test_process_success_commits_receipt_before_child_and_strips_credentials(
    tmp_path, children, monkeypatch
):
    engine, venue, _ = context(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "private-key-never-to-child")
    monkeypatch.setenv("TRADER_LIVE_ENABLED", "true")
    monkeypatch.setenv("ROBINHOOD_TOKEN", "private-token-never-to-child")
    original = process_module.asyncio.create_subprocess_exec

    async def check(*args, **kwargs):
        order = engine.journal.report()["orders"][0]
        assert order["status"] == "SUBMITTING" and order["attempted_at"] is not None
        assert (
            not {"OPENAI_API_KEY", "TRADER_LIVE_ENABLED", "ROBINHOOD_TOKEN"} & kwargs["env"].keys()
        )
        return await original(*args, **kwargs)

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", check)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    assert (
        asyncio.run(engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet()))
        == "OPEN"
    )
    assert venue.submit_count == 1
    event = next(e for e in engine.journal.report()["events"] if e["kind"] == "ATTEMPT_STARTED")
    assert event["payload"] == {
        "adapter": "DURABLE_FIXTURE_PROCESS",
        "venue_id": venue.venue_id,
        "timeout_seconds": 2.0,
        "effective_timeout_seconds": 2.0,
        "deadline_monotonic": event["payload"]["deadline_monotonic"],
    }
    reaped(children)


@pytest.mark.parametrize(
    "fault,accepted,error",
    [
        ("STALL_BEFORE_ACCEPT", 0, "FixtureProcessTimeout"),
        ("STALL_AFTER_ACCEPT", 1, "FixtureProcessTimeout"),
        ("IGNORE_TERM_AFTER_ACCEPT", 1, "FixtureProcessTimeout"),
        ("CRASH_AFTER_ACCEPT", 1, "FixtureProcessFailed"),
        ("LOST_ACK", 1, "FixtureProcessFailed"),
        ("INVALID_ACK", 1, "FixtureProcessProtocolError"),
        ("OVERSIZED_ACK", 1, "FixtureProcessProtocolError"),
    ],
)
def test_failure_reaps_child_retains_attempt_and_never_replays(
    tmp_path, children, fault, accepted, error
):
    engine, venue, settings = context(tmp_path, fault)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    start = time.monotonic()
    assert (
        asyncio.run(engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet()))
        == "UNKNOWN"
    )
    assert time.monotonic() - start < 8
    assert venue.submit_count == accepted
    report = engine.journal.report()
    assert report["halted"] and report["orders"][0]["active"]
    assert report["orders"][0]["status"] == "UNKNOWN"
    assert report["events"][0]["payload"]["error_class"] == error
    reaped(children)
    restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    reopened = DurableFixtureVenue(venue.path)
    assert reopened.venue_id == venue.venue_id and reopened.submit_count == accepted
    assert asyncio.run(restarted.dispatch_async(intent.client_id, reopened, now=NOW)) == "UNKNOWN"
    assert len(children) == 1 and reopened.submit_count == accepted
    with pytest.raises(ExecutionBlocked):
        restarted.abandon_prepared(intent.client_id, "time passed", now=NOW + timedelta(hours=1))
    with pytest.raises(ExecutionBlocked):
        restarted.resume("cannot prove a terminal outcome", now=NOW)


def test_timeout_before_accept_missing_history_cannot_release_reservation(tmp_path):
    engine, venue, _ = context(tmp_path, "STALL_BEFORE_ACCEPT")
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    asyncio.run(engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet()))
    venue.fault = "NONE"
    result = asyncio.run(engine.reconcile_fixture(venue, now=NOW))
    assert not result["reconciled"] and "ATTEMPTED_ORDER_MISSING" in result["issues"]
    assert engine.journal.report()["orders"][0]["active"]


def test_crash_recovery_partial_entry_then_protective_exit_is_durable(tmp_path, children):
    engine, venue, settings = context(tmp_path, "CRASH_AFTER_ACCEPT")
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    assert (
        asyncio.run(engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet()))
        == "UNKNOWN"
    )
    reopened = DurableFixtureVenue(venue.path)
    restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    assert asyncio.run(restarted.reconcile_fixture(reopened, now=NOW))["reconciled"]
    assert restarted.journal.report()["orders"][0]["status"] == "OPEN"
    half = (intent.quantity / 2).quantize(D(".00000001"))
    at = NOW + timedelta(seconds=1)
    reopened.fill(intent.client_id, half, D(10), at, fill_id="partial")
    reopened.terminal(intent.client_id, "CANCELED", at)
    assert asyncio.run(restarted.reconcile_fixture(reopened, now=at))["new_fills"] == 1
    assert asyncio.run(restarted.reconcile_fixture(reopened, now=at))["new_fills"] == 0
    p = packet(at, "9.4", "9.41")
    assert restarted.supervise(p, now=at)["exit_reason"] == "INVALIDATION"
    restarted.resume("verified canceled remainder and current risk", now=at)
    sell = restarted.prepare_protective_exit(p, now=at)
    assert sell.quantity == half
    assert (
        asyncio.run(restarted.dispatch_async(sell.client_id, reopened, now=at, packet=p)) == "OPEN"
    )
    reopened.fill(sell.client_id, half, sell.limit_price, at, fill_id="sell")
    assert asyncio.run(restarted.reconcile_fixture(reopened, now=at))["new_fills"] == 1
    report = restarted.journal.report()
    assert report["ledger"]["position"] is None and len(report["fills"]) == 2
    assert reopened.submit_count == 2 and not report["halted"]
    reaped(children)


def test_repeated_cancellation_after_accept_waits_for_kill_and_preserves_uncertainty(
    tmp_path, children
):
    engine, venue, _ = context(tmp_path, "IGNORE_TERM_AFTER_ACCEPT")
    intent = engine.prepare("entry", decision(), packet(), now=NOW)

    async def scenario():
        task = asyncio.create_task(
            engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet())
        )
        await wait_until(lambda: venue.submit_count == 1)
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)

    asyncio.run(scenario())
    assert engine.journal.report()["orders"][0]["status"] == "UNKNOWN"
    assert engine.journal.report()["halted"] and venue.submit_count == 1
    reaped(children)


def test_cancellation_during_spawn_still_reaps_eventual_child(tmp_path, children, monkeypatch):
    engine, venue, _ = context(tmp_path, "STALL_BEFORE_ACCEPT")
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    original = process_module.asyncio.create_subprocess_exec

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", delayed)
        task = asyncio.create_task(
            engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet())
        )
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert engine.journal.report()["orders"][0]["status"] == "UNKNOWN"
    reaped(children)


def test_failed_read_keeps_last_snapshot_and_requires_explicit_recovery(tmp_path, children):
    engine, venue, _ = context(tmp_path, "STALL_READ")
    before = engine.journal.report()["ledger"]
    with pytest.raises(FixtureProcessTimeout):
        asyncio.run(engine.reconcile_fixture(venue, now=NOW))
    report = engine.journal.report()
    assert report["ledger"] == before and report["halted"] and report["orders"] == []
    venue.fault = "NONE"
    assert asyncio.run(engine.reconcile_fixture(venue, now=NOW))["reconciled"]
    assert engine.journal.report()["halted"]
    engine.resume("complete fresh fixture evidence", now=NOW)
    assert not engine.journal.report()["halted"]
    reaped(children)


def test_spawn_failure_remains_uncertain_without_releasing_attempt(tmp_path, monkeypatch):
    engine, venue, _ = context(tmp_path)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)

    async def fail(*args, **kwargs):
        raise OSError("injected")

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", fail)
    assert (
        asyncio.run(engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet()))
        == "UNKNOWN"
    )
    assert engine.journal.report()["orders"][0]["active"] and venue.submit_count == 0


def test_no_arbitrary_adapter_and_no_sync_bypass_after_binding(tmp_path):
    engine, venue, _ = context(tmp_path)
    asyncio.run(engine.reconcile_fixture(venue, now=NOW))
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    with pytest.raises(ValueError):
        asyncio.run(engine.dispatch_async(intent.client_id, object(), now=NOW, packet=packet()))
    local = LocalFixtureVenue(D(10))
    with pytest.raises(ExecutionBlocked, match="PROCESS_REQUIRED"):
        engine.dispatch(intent.client_id, local, now=NOW, packet=packet())
    assert venue.submit_count == local.submit_count == 0


def test_binding_cannot_switch_to_same_account_new_venue_on_restart(tmp_path):
    engine, venue, settings = context(tmp_path)
    asyncio.run(engine.reconcile_fixture(venue, now=NOW))
    new = DurableFixtureVenue(tmp_path / "other.db", capital=D(10))
    restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
    with pytest.raises(ExecutionBlocked, match="BINDING_MISMATCH"):
        asyncio.run(restarted.reconcile_fixture(new, now=NOW))
    assert restarted.journal.report()["halted"]
    assert restarted.journal.report()["fixture_binding"]["venue_id"] == venue.venue_id


def test_durable_venue_refuses_application_db_and_never_overwrites_or_recreates(tmp_path):
    engine, venue, _ = context(tmp_path)
    with pytest.raises(ValueError, match="dedicated"):
        DurableFixtureVenue(engine.journal.path)
    before = venue.path.read_bytes()
    with pytest.raises(FileExistsError):
        DurableFixtureVenue(venue.path, capital=D(99))
    assert venue.path.read_bytes() == before
    venue.path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        venue.snapshot(NOW)
    assert not venue.path.exists()


def test_bound_venue_replacement_is_rejected_in_child_before_acceptance(tmp_path):
    engine, venue, _ = context(tmp_path)
    asyncio.run(engine.reconcile_fixture(venue, now=NOW))
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    venue.path.unlink()
    replacement = DurableFixtureVenue(venue.path, capital=D(10))
    assert (
        asyncio.run(engine.dispatch_async(intent.client_id, venue, now=NOW, packet=packet()))
        == "UNKNOWN"
    )
    assert replacement.submit_count == 0 and engine.journal.report()["halted"]


def test_short_admission_lease_caps_child_deadline(tmp_path, children):
    engine, venue, _ = context(tmp_path)
    at = NOW + timedelta(seconds=89.5)
    entry = engine.prepare("short-lease", decision(), packet(at), now=at)
    with sqlite3.connect(venue.path) as locked:
        locked.execute("BEGIN EXCLUSIVE")
        assert (
            asyncio.run(engine.dispatch_async(entry.client_id, venue, now=at, packet=packet(at)))
            == "UNKNOWN"
        )
    event = next(e for e in engine.journal.report()["events"] if e["kind"] == "ATTEMPT_STARTED")
    assert event["payload"]["effective_timeout_seconds"] == 0.5
    assert venue.submit_count == 0
    reaped(children)


def test_deadline_cli_rehearsal_is_saved_and_network_free(tmp_path, capsys, monkeypatch):
    import json
    import socket

    from app.execution.cli import main

    def deny(*args, **kwargs):
        raise AssertionError("Network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", deny)
    db = tmp_path / "demo.db"
    assert main(["deadline-run", "--db", str(db)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "OK" and not report["network_calls"] and not report["live_enabled"]
    assert len(report["fills"]) == 2 and report["fixture_binding"] is not None
    assert [o["status"] for o in report["orders"]] == ["CANCELED", "FILLED"]
    before = db.read_bytes()
    assert main(["report", "--db", str(db)]) == 0
    capsys.readouterr()
    assert db.read_bytes() == before

    assert main(["deadline-run", "--db", str(db)]) == 1
    capsys.readouterr()
    assert db.read_bytes() == before


def test_durable_transport_cannot_adopt_previous_in_memory_attempts(tmp_path):
    engine, venue, _ = context(tmp_path)
    entry = engine.prepare("local", decision(), packet(), now=NOW)
    engine.dispatch(entry.client_id, LocalFixtureVenue(D(10)), now=NOW, packet=packet())
    with pytest.raises(ExecutionBlocked, match="TRANSPORT_ALREADY_USED"):
        asyncio.run(engine.reconcile_fixture(venue, now=NOW))
    assert engine.journal.report()["halted"] and venue.submit_count == 0


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="Linux subreaper owns orphan cleanup in this crash test",
)
def test_abrupt_parent_exit_preserves_accepted_order_and_child_exits(tmp_path):
    import ctypes
    import signal
    import subprocess
    import sys

    engine, venue, settings = context(tmp_path, "IGNORE_TERM_AFTER_ACCEPT")
    intent = engine.prepare("crash-parent", decision(), packet(), now=NOW)
    pid_path = tmp_path / "child.pid"
    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    # Only this test process changes its own subreaper flag, so it can reap its orphan.
    if libc.prctl(37, ctypes.byref(original), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        pytest.skip("Subreaper unavailable")
    child_pid = None
    script = """
import asyncio, os, sys
from pathlib import Path
from datetime import datetime
from app.config import Settings
from app.execution.models import ExecutionLimits
from app.execution.engine import ExecutionEngine
from app.execution.durable_fixture import DurableFixtureVenue
from tests.test_execution_rehearsal import packet
engine=ExecutionEngine(sys.argv[1], Settings(_env_file=None, mode='PAPER', live_enabled=False, starting_capital=10), limits=ExecutionLimits.model_validate_json(sys.argv[4]))
venue=DurableFixtureVenue(sys.argv[2], fault='IGNORE_TERM_AFTER_ACCEPT')
spawn=asyncio.create_subprocess_exec
async def capture(*args, **kwargs):
    child=await spawn(*args, **kwargs)
    Path(sys.argv[5]).write_text(str(child.pid))
    return child
asyncio.create_subprocess_exec=capture
async def run():
    at=datetime.fromisoformat(sys.argv[6])
    asyncio.create_task(engine.dispatch_async(sys.argv[3], venue, now=at, packet=packet(at)))
    async with asyncio.timeout(10):
        while venue.submit_count!=1:
            await asyncio.sleep(.01)
    os._exit(95)
asyncio.run(run())
"""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(engine.journal.path),
                str(venue.path),
                intent.client_id,
                engine.limits.model_dump_json(),
                str(pid_path),
                NOW.isoformat(),
            ],
            timeout=15,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 95, result.stderr
        child_pid = int(pid_path.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            reaped_pid, status = os.waitpid(child_pid, os.WNOHANG)
            if reaped_pid:
                child_pid = None
                assert os.waitstatus_to_exitcode(status) == 96
                break
            time.sleep(0.01)
        assert child_pid is None, "Fake child did not exit after parent death"
        reopened = DurableFixtureVenue(venue.path)
        restarted = ExecutionEngine(engine.journal.path, settings, limits=engine.limits)
        report = restarted.journal.report()
        assert report["orders"][0]["status"] == "UNKNOWN" and report["halted"]
        assert report["orders"][0]["active"] and reopened.submit_count == 1
        assert (
            asyncio.run(restarted.dispatch_async(intent.client_id, reopened, now=NOW)) == "UNKNOWN"
        )
        assert asyncio.run(restarted.reconcile_fixture(reopened, now=NOW))["reconciled"]
        assert reopened.submit_count == 1
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child_pid, 0)
        libc.prctl(36, original.value, 0, 0, 0)
