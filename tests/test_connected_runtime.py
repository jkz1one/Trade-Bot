"""Offline coordinated ownership, failure cleanup and durable feed restart."""

import asyncio
import hashlib
import os
import sqlite3
from datetime import timedelta

import pytest
from test_connected_check import configuration
from test_portfolio_feed import reader
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.execution.runtime import RuntimeAlreadyRunning
from app.mixed.connected_runtime import ComponentFailure, check, run, supervise
from app.mixed.continuous_feed import ContinuousFeed
from app.options.runtime_cli import initialize


def enrolled(tmp_path, schemas):
    settings, policy = configuration(tmp_path)
    owner, feed = tmp_path / "owner", tmp_path / "feed"
    initialize(owner, settings, clock=lambda: AT)
    ContinuousFeed(feed, policy, schemas, create=True).close()
    paths = tmp_path / "policy.json", tmp_path / "schemas.json"
    for path, value in zip(paths, (policy, schemas)):
        path.write_text(value.model_dump_json())
        path.chmod(0o600)
    return (owner, feed, *paths), settings, policy


def digest(directory):
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }


def state(owner):
    with sqlite3.connect(owner / "options.db") as db:
        db.row_factory = sqlite3.Row
        runtime = dict(db.execute("SELECT * FROM execution_option_runtime WHERE id=1").fetchone())
        control = dict(db.execute("SELECT * FROM execution_control WHERE id=1").fetchone())
    return runtime, control


def test_check_is_read_only_and_does_not_open_credentials(tmp_path, schemas, monkeypatch):
    args, settings, _ = enrolled(tmp_path, schemas)
    before = digest(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Check opened writable execution or collector")

    monkeypatch.setattr("app.mixed.connected_runtime.existing_runtime", forbidden)
    monkeypatch.setattr("app.mixed.connected_runtime.ContinuousFeed", forbidden)
    result = check(*args, clock_source=lambda: AT)[0]
    assert result["dashboard_journal"] == str(args[0] / "options.db")
    assert result["dashboard_population_id"] == settings.limits.population_id
    assert not result["trading_ready"] and not result["workers_started"]
    assert not result["state_modified"] and not result["credentials_opened"]
    assert digest(tmp_path) == before


@pytest.mark.parametrize("frozen_by", ["reason", "event"])
def test_frozen_review_rejected_before_state_changes(tmp_path, schemas, frozen_by):
    args, _, _ = enrolled(tmp_path, schemas)
    with sqlite3.connect(args[0] / "options.db") as db:
        if frozen_by == "reason":
            db.execute("UPDATE execution_control SET halt_reason='FROZEN_OFFLINE_REPLAY'")
        else:
            db.execute(
                "INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)",
                (AT.isoformat(), "PORTFOLIO_REPLAY_STARTED", "{}"),
            )
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="Frozen offline replay"):
        asyncio.run(run(*args, asyncio.Event(), clock_source=lambda: AT))
    assert digest(tmp_path) == before


def test_missing_enrollment_never_creates_population(tmp_path, schemas):
    args, _, _ = enrolled(tmp_path, schemas)
    missing = tmp_path / "missing"
    with pytest.raises(OSError):
        check(missing, *args[1:], clock_source=lambda: AT)
    assert not missing.exists()
    (args[1] / "collector.db").unlink()
    before = digest(tmp_path)
    with pytest.raises(OSError):
        asyncio.run(run(*args, asyncio.Event(), clock_source=lambda: AT))
    assert digest(tmp_path) == before


@pytest.mark.parametrize("changed", ["runtime", "collector"])
def test_changed_enrollment_rejected_before_owner_open(tmp_path, schemas, changed):
    args, settings, policy = enrolled(tmp_path, schemas)
    if changed == "runtime":
        value = settings.model_copy(
            update={"runtime": settings.runtime.model_copy(update={"tick_seconds": 0.3})}
        )
        (args[0] / "runtime.json").write_text(value.model_dump_json())
    else:
        args[2].write_text(policy.model_copy(update={"poll_seconds": 21}).model_dump_json())
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="differ"):
        asyncio.run(run(*args, asyncio.Event(), clock_source=lambda: AT))
    assert digest(tmp_path) == before


@pytest.mark.parametrize("failed_role", ["RUNTIME", "COLLECTOR"])
@pytest.mark.parametrize("raises", [False, True])
def test_component_failure_or_early_return_drains_sibling(failed_role, raises):
    async def scenario():
        stop = asyncio.Event()
        started, cleaned = set(), set()

        async def worker(role, stop):
            started.add(role)
            try:
                while len(started) < 2:
                    await asyncio.sleep(0)
                if role == failed_role:
                    if raises:
                        raise ValueError("private provider error must not escape")
                    return
                await stop.wait()
                await asyncio.sleep(0)
            finally:
                cleaned.add(role)

        with pytest.raises(ComponentFailure, match=failed_role) as error:
            await supervise(
                lambda stop: worker("RUNTIME", stop),
                lambda stop: worker("COLLECTOR", stop),
                stop,
            )
        assert "private" not in str(error.value)
        assert error.value.details[0]["component"] == failed_role
        assert error.value.details[0]["error_class"] == (
            "ValueError" if raises else "UNEXPECTED_RETURN"
        )
        assert stop.is_set() and cleaned == started == {"RUNTIME", "COLLECTOR"}

    asyncio.run(scenario())


def test_shutdown_deadline_cancels_and_awaits_stuck_collector():
    async def scenario():
        stop, cleaned, started = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def runtime(stop):
            await started.wait()
            stop.set()

        async def collector(stop):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        with pytest.raises(ComponentFailure, match="COLLECTOR"):
            await supervise(runtime, collector, stop, shutdown_seconds=0.01)
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_supervisor_cancellation_drains_components_and_propagates():
    async def scenario():
        stop = asyncio.Event()
        started, cleaned = set(), set()

        async def worker(role, stop):
            started.add(role)
            try:
                await stop.wait()
            finally:
                cleaned.add(role)

        task = asyncio.create_task(
            supervise(
                lambda stop: worker("runtime", stop), lambda stop: worker("collector", stop), stop
            )
        )
        while len(started) < 2:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == started and stop.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "with_positions,unreconciled", [(False, False), (True, False), (True, True)]
)
@pytest.mark.parametrize("with_dashboard", [False, True])
def test_native_restart_consumes_next_delivery_without_reset_or_duplicate_owner(
    tmp_path, schemas, monkeypatch, with_positions, unreconciled, with_dashboard
):
    args, settings, _ = enrolled(tmp_path, schemas)
    times = [AT]
    observed = []
    calls = []
    entries = {}
    if with_positions:
        from datetime import date, datetime

        from test_degen_options import AT as seed_at
        from test_mixed_accounting import changed
        from test_portfolio_controls import get_intent
        from test_portfolio_selection import two_symbols

        from app.options.coordinator import DegenFrame
        from app.options.runtime_cli import existing_runtime

        times[0] = AT + timedelta(minutes=30)
        shift = times[0] - seed_at

        def adapt(value):
            # Synthetic fixture only: rebase the complete original selection
            # packet, preserving all relative clocks and native admission rules.
            if isinstance(value, (datetime, date)):
                return value + shift
            if isinstance(value, dict):
                return {
                    k: "robinhood"
                    if k == "provider"
                    else "robinhood-mcp"
                    if k == "source"
                    else adapt(v)
                    for k, v in value.items()
                }
            if isinstance(value, (list, tuple)):
                return [adapt(v) for v in value]
            return value

        frame = DegenFrame.model_validate(adapt(two_symbols().model_dump()))
        with existing_runtime(args[0], clock=lambda: times[0]) as (runtime, _):
            engine = runtime.c.engine
            outcome = asyncio.run(runtime.c.cycle(frame))
            assert [e["status"] for e in outcome["entries"]] == ["OPEN", "OPEN"], outcome
            later = times[0] + timedelta(seconds=1)
            for entry in outcome["entries"]:
                intent = get_intent(engine, entry["client_id"])
                quote = next(
                    x.quote for x in frame.stocks if x.quote.instrument == intent.instrument
                )
                engine.venue.fill_stock(
                    intent,
                    intent.quantity,
                    changed(quote, source_at=later, received_at=later),
                    later,
                    fill_id=intent.client_id,
                )
                entries[intent.client_id] = intent.model_dump(mode="json")
            if not unreconciled:
                assert engine.reconcile(engine.venue.snapshot(later), now=later)["reconciled"]
        times[0] += timedelta(seconds=2)

    async def offline_capture(
        self, stop, *, clock_source, held_source, calendar, source_settings=None
    ):
        assert source_settings == settings
        assert state(args[0])[0]["heartbeat_at"] is not None
        calls.append(held_source())
        # The first runner holds both real leases before any provider task starts.
        with pytest.raises(RuntimeAlreadyRunning):
            await run(*args, asyncio.Event(), clock_source=clock_source)
        elapsed = int((times[0] - AT).total_seconds())
        result = await self.tick(
            now=times[0],
            held=held_source(),
            reader=reader(times[0], observed, source_shift=elapsed),
        )
        assert result["status"] == "DELIVERED", result
        times[0] += timedelta(seconds=2)
        for _ in range(150):
            if state(args[0])[0]["feed_sequence"] == result["sequence"]:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("Native runtime did not consume collector delivery")
        stop.set()

    monkeypatch.setattr(ContinuousFeed, "run", offline_capture)
    snapshot_args = {}
    if with_dashboard:
        from app.mixed.dashboard_snapshot import DashboardPublisher

        destination = tmp_path / "dashboard"
        publisher = DashboardPublisher(
            args[0],
            destination,
            os.getuid(),
            os.getgid(),
            create=True,
            clock_source=lambda: times[0],
        )
        try:
            publisher.publish()
        finally:
            publisher.close()
        snapshot_args = {
            "snapshot_directory": destination,
            "reader_uid": os.getuid(),
            "reader_gid": os.getgid(),
        }
    before_cash = None
    for generation in (1, 2):
        result = asyncio.run(
            run(*args, asyncio.Event(), clock_source=lambda: times[0], **snapshot_args)
        )
        assert result["status"] == "STOPPED" and not result["automatic_resume"]
        runtime, control = state(args[0])
        assert runtime["generation"] == generation and runtime["feed_sequence"] == generation
        assert runtime["status"] == "STOPPED" and control["halted"]
        from app.mixed.observer import MixedObserver

        report = MixedObserver(
            args[0] / "options.db", settings.limits.population_id, clock=lambda: times[0]
        ).report()
        assert report["status"] == "OK", report
        if with_dashboard:
            snapshot = MixedObserver(
                destination / "options.db", settings.limits.population_id, clock=lambda: times[0]
            ).report()
            assert snapshot == report
            assert result["dashboard_published"]
        assert {p["play_id"]: p["entry"] for p in report["positions"]} == entries
        assert len(report["fills"]) == len(entries)
        assert all(
            o["intent"]["side"] != "BUY" or o["play_id"] in entries for o in report["orders"]
        )
        if before_cash is None:
            before_cash = report["cash"]
        assert report["cash"] == before_cash
        times[0] += timedelta(seconds=20)
    assert len(calls) == len(observed) == 2
    assert all(len(held) == len(entries) for held in calls)
    # Reopen after shutdown proves the collector lease was actually released.
    from app.mixed.continuous_feed import FeedPolicy

    feed = ContinuousFeed(args[1], FeedPolicy.model_validate_json(args[2].read_bytes()), schemas)
    feed.close()


def test_failed_first_tick_never_starts_collector_and_releases_lease(
    tmp_path, schemas, monkeypatch
):
    args, _, _ = enrolled(tmp_path, schemas)
    calls = []

    async def failed(self):
        raise ValueError("fixture first tick failed")

    async def forbidden(self, *args, **kwargs):
        calls.append("collector")
        raise AssertionError("Collector started before native first tick completed")

    monkeypatch.setattr("app.options.runtime.OptionRuntime.tick", failed)
    monkeypatch.setattr(ContinuousFeed, "run", forbidden)
    with pytest.raises(ComponentFailure, match="RUNTIME"):
        asyncio.run(run(*args, asyncio.Event(), clock_source=lambda: AT))
    assert not calls
    runtime, control = state(args[0])
    assert runtime["status"] == "FAILED" and control["halted"]
    from app.options.runtime_cli import existing_runtime

    with existing_runtime(args[0], clock=lambda: AT):
        pass
