"""Coordinated publisher failure/cancellation retains leases until backup drains."""

import asyncio
import json
import os
import sqlite3
import threading
from datetime import timedelta

import pytest
from test_connected_runtime import digest, enrolled
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed import connected_runtime as connected
from app.mixed.dashboard_snapshot import DashboardPublisher


@pytest.mark.parametrize('damage', ['missing_display', 'pending', 'binding', 'reader',
                                  'missing_lock', 'flat', 'unreconciled', 'cash'])
def test_protection_startup_requires_original_enrollment_and_verified_holdings(tmp_path, damage):
    from test_dashboard_snapshot import owner, publisher
    from test_degen_options import AT as original_at
    from app.mixed.observer import MixedObserver

    source, settings = owner(tmp_path, positions=damage != 'flat')
    destination = tmp_path / 'dashboard'
    p = publisher(source, destination)
    try:
        p.publish()
    finally:
        p.close()
    at = original_at + timedelta(seconds=2)
    if damage == 'missing_display':
        (destination / 'options.db').unlink()
    elif damage == 'pending':
        (destination / '.pending.db').write_bytes(b'retained incomplete display')
    elif damage == 'binding':
        path = destination / 'binding.json'
        binding = json.loads(path.read_text())
        binding['population_id'] = 'foreign'
        path.write_text(json.dumps(binding))
    elif damage == 'missing_lock':
        (destination / 'publisher.lock').unlink()
    elif damage == 'unreconciled':
        with sqlite3.connect(source / 'options.db') as db:
            db.execute('UPDATE execution_control SET issues_json=?', ('["UNRESOLVED"]',))
    elif damage == 'cash':
        with sqlite3.connect(source / 'options.db') as db:
            raw = json.loads(db.execute('SELECT snapshot_json FROM execution_portfolio_control').fetchone()[0])
            raw['cash'] = str(int(float(raw['cash'])) + 1)
            db.execute('UPDATE execution_portfolio_control SET snapshot_json=?', (json.dumps(raw),))
    before = digest(tmp_path)
    observer = MixedObserver(source / 'options.db', settings.limits.population_id,
                             clock=lambda: at, native_journal=True)

    def verify():
        connected.protection_startup(source, destination,
            os.getuid() + int(damage == 'reader'), os.getgid(), observer, settings, now=at)

    if damage in {'missing_display', 'pending'}:
        verify()
        reviewed, failure = connected.dashboard_preflight(source, destination, os.getuid(),
            os.getgid(), observer, settings, clock_source=lambda: at)
        assert reviewed['startup_mode'] == 'PROTECTION_ONLY' and reviewed['held_plays'] == 2
        assert failure is not None and not reviewed['publication_available']
        with pytest.raises((OSError, ValueError)):
            connected.dashboard_preflight(source, destination, os.getuid(), os.getgid(),
                observer, settings, clock_source=lambda: at, allow_protection=False)
    else:
        with pytest.raises((OSError, ValueError, RuntimeError)):
            verify()
    assert digest(tmp_path) == before


@pytest.mark.parametrize("raises", [True, False])
def test_publisher_failure_fences_and_drains_runtime_and_collector(raises):
    async def scenario():
        stop = asyncio.Event()
        started, cleaned = set(), set()

        async def component(name, stop):
            started.add(name)
            try:
                while len(started) < 3:
                    await asyncio.sleep(0)
                if name == "PUBLISHER":
                    if raises:
                        raise ValueError("private copy failure")
                    return
                await stop.wait()
            finally:
                cleaned.add(name)

        with pytest.raises(connected.ComponentFailure, match="PUBLISHER") as exc:
            await connected.supervise(
                lambda stop: component("RUNTIME", stop),
                lambda stop: component("COLLECTOR", stop),
                stop,
                publisher_run=lambda stop: component("PUBLISHER", stop),
            )
        assert "private" not in str(exc.value)
        assert started == cleaned == {"RUNTIME", "COLLECTOR", "PUBLISHER"}
        assert stop.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("copy_fails", [False, True])
def test_repeated_cancellation_waits_for_actual_copy_thread(copy_fails):
    entered, release, complete = threading.Event(), threading.Event(), threading.Event()

    class Publisher:
        def publish(self):
            entered.set()
            assert release.wait(3)
            complete.set()
            if copy_fails:
                raise ValueError("retained copy error")
            return {"status": "PUBLISHED"}

    async def scenario():
        task = asyncio.create_task(connected.publish_async(Publisher()))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and not complete.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert complete.is_set()
        finally:
            release.set()

    asyncio.run(scenario())


def test_supervisor_cancellation_drains_copy_before_components_release():
    entered, release, complete = threading.Event(), threading.Event(), threading.Event()

    class Publisher:
        def publish(self):
            entered.set()
            assert release.wait(3)
            complete.set()

    async def scenario():
        stop = asyncio.Event()

        async def worker(stop):
            await stop.wait()

        async def publish(stop):
            await connected.publish_async(Publisher())
            await stop.wait()

        task = asyncio.create_task(
            connected.supervise(worker, worker, stop, publisher_run=publish, shutdown_seconds=0.01)
        )
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0.04)
            assert not task.done() and stop.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert complete.is_set()
        finally:
            release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("damage", ["missing", "reader", "pending"])
def test_invalid_publisher_enrollment_prevents_runtime_or_provider_start(
    tmp_path, schemas, monkeypatch, damage
):
    args, _, _ = enrolled(tmp_path, schemas)
    destination = tmp_path / "dashboard"
    if damage != "missing":
        p = DashboardPublisher(
            args[0], destination, os.getuid(), os.getgid(), create=True, clock_source=lambda: AT
        )
        try:
            p.publish()
        finally:
            p.close()
    if damage == "pending":
        (destination / ".pending.db").write_text("retained failure")
    monkeypatch.setattr(
        connected, "existing_runtime", lambda *_a, **_k: pytest.fail("Owner opened")
    )
    before = digest(args[0])
    with pytest.raises((OSError, ValueError)):
        asyncio.run(
            connected.run(
                *args,
                asyncio.Event(),
                snapshot_directory=destination,
                reader_uid=os.getuid() + 1 if damage == "reader" else os.getuid(),
                reader_gid=os.getgid(),
                clock_source=lambda: AT,
            )
        )
    assert digest(args[0]) == before


def test_pre_stopped_session_does_not_publish_or_open_owner(tmp_path, schemas, monkeypatch):
    args, _, _ = enrolled(tmp_path, schemas)
    destination = tmp_path / "dashboard"
    p = DashboardPublisher(
        args[0], destination, os.getuid(), os.getgid(), create=True, clock_source=lambda: AT
    )
    try:
        p.publish()
    finally:
        p.close()
    before = digest(tmp_path)
    monkeypatch.setattr(
        connected, "existing_runtime", lambda *_a, **_k: pytest.fail("Owner opened")
    )

    async def scenario():
        stop = asyncio.Event()
        stop.set()
        return await connected.run(
            *args,
            stop,
            snapshot_directory=destination,
            reader_uid=os.getuid(),
            reader_gid=os.getgid(),
            clock_source=lambda: AT,
        )

    assert asyncio.run(scenario())["status"] == "NOT_STARTED"
    assert digest(tmp_path) == before


@pytest.mark.parametrize(
    "extra",
    [
        ["--reader-uid", "0"],
        ["--snapshot-directory", "/missing"],
        ["--snapshot-owner", "/source"],
        ["--snapshot-directory", "/missing", "--reader-uid", "0"],
    ],
)
def test_cli_requires_complete_snapshot_binding_before_any_check(monkeypatch, extra):
    monkeypatch.setattr(connected, "check", lambda *_a, **_k: pytest.fail("Preflight opened"))
    with pytest.raises(SystemExit) as exc:
        connected.main(
            [
                "check",
                "--directory",
                "/owner",
                "--feed-directory",
                "/feed",
                "--policy",
                "/policy",
                "--schemas",
                "/schemas",
                *extra,
            ]
        )
    assert exc.value.code == 2


def test_collector_failure_publishes_verified_terminal_records(tmp_path, schemas, monkeypatch):
    from datetime import timedelta
    from app.mixed.dashboard_reader import guard
    from app.mixed.dashboard_snapshot import published

    args, _, _ = enrolled(tmp_path, schemas)
    destination = tmp_path / "dashboard"
    with_publisher = DashboardPublisher(args[0], destination, os.getuid(), os.getgid(),
                                        create=True, clock_source=lambda: AT)
    try:
        with_publisher.publish()
        binding = with_publisher.binding
    finally:
        with_publisher.close()

    async def fail_collector(self, stop, **kwargs):
        raise OSError("private fixture detail")

    monkeypatch.setattr(connected.ContinuousFeed, "run", fail_collector)
    with pytest.raises(connected.ComponentFailure, match="COLLECTOR") as failed:
        asyncio.run(connected.run(*args, asyncio.Event(), snapshot_directory=destination,
                                  reader_uid=os.getuid(), reader_gid=os.getgid(), clock_source=lambda: AT))
    assert [part["component"] for part in failed.value.details] == ["COLLECTOR"]
    receipt = published(destination, binding, include_runtime=True)
    assert receipt["stored_runtime"]["status"] in {"FAILED", "STOPPED"}
    assert receipt["stored_runtime"]["halted"]
    assert guard(destination, binding, clock_source=lambda: AT + timedelta(hours=6))["publication_state"] == "STOPPED_RECORDS"
