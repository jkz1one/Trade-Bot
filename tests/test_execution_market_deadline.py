"""Expired collection cannot admit a durable sample or renew source health."""

import asyncio
import json
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

from app.execution import market_reads, quote_feed
from app.execution.market_reads import collect_once, market_read_lease
from tests.test_execution_market_reads import feed_context, request, result
from tests.test_execution_market_service import context
from tests.test_execution_rehearsal import NOW


def monotonic_clock(monkeypatch):
    clock = [100.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0])
    # Do not change the event loop's clock or native child watchdog.
    monkeypatch.setattr(market_reads, "time", timer)
    monkeypatch.setattr(quote_feed, "time", timer)
    return clock


async def warm(feed, monkeypatch):
    async def read(req):
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    await collect_once(feed, clock=lambda: NOW)
    return feed.path.read_bytes(), feed.latest()


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ("read", "parent-clock", "packet", "begin", "binding", "insert"))
async def test_expiry_rolls_back_at_each_publication_boundary(tmp_path, monkeypatch, phase):
    feed, _ = feed_context(tmp_path)
    before, saved = await warm(feed, monkeypatch)
    monotonic = monotonic_clock(monkeypatch)

    def expire():
        monotonic[0] = 130.0

    async def read(req):
        if phase == "read":
            expire()
        return result(req)

    wall_calls = 0

    def wall_clock():
        nonlocal wall_calls
        wall_calls += 1
        if phase == "parent-clock" and wall_calls == 2:
            expire()
        return NOW

    validate, binding = feed._validate_packet, feed._binding

    def validate_packet(packet):
        packet = validate(packet)
        if phase == "packet":
            expire()
        return packet

    def bind(db):
        binding(db)
        if phase == "binding":
            expire()

    connect = sqlite3.connect

    def connection(*args, **kwargs):
        db = connect(*args, **kwargs)

        def trace(sql):
            if (phase == "begin" and sql == "BEGIN IMMEDIATE") or (
                phase == "insert" and sql.startswith("INSERT INTO quote_samples")
            ):
                expire()

        db.set_trace_callback(trace)
        return db

    with monkeypatch.context() as patch:
        patch.setattr(market_reads, "_read", read)
        patch.setattr(feed, "_validate_packet", validate_packet)
        patch.setattr(feed, "_binding", bind)
        patch.setattr(quote_feed.sqlite3, "connect", connection)
        with pytest.raises(TimeoutError, match="publication deadline"):
            await collect_once(feed, clock=wall_clock)
    assert feed.path.read_bytes() == before and feed.latest() == saved
    with market_read_lease(feed.path):
        pass
    # Expiry neither strands the transaction nor consumes a sequence.
    monotonic[0] = 200.0
    assert (await collect_once(feed, clock=lambda: NOW))["feed_sequence"] == 2


@pytest.mark.anyio
async def test_late_native_cleanup_retains_lease_and_cannot_publish(tmp_path, monkeypatch):
    from app.execution import process as process_tools

    real_read = market_reads._read
    feed, policy = feed_context(tmp_path)
    before, saved = await warm(feed, monkeypatch)
    monotonic = monotonic_clock(monkeypatch)
    fixture = result(request(policy)).model_dump_json()
    code = (
        "import sys,json;req=json.load(sys.stdin);out=json.loads(" + repr(fixture) + ");"
        "out['request_id']=req['request_id'];out['feed_id']=req['feed_id'];print(json.dumps(out))"
    )
    real_spawn, terminate = asyncio.create_subprocess_exec, process_tools._terminate
    children = []
    cleanup_started, release = asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        proc = await real_spawn(sys.executable, "-c", code, **kwargs)
        children.append(proc)
        return proc

    async def cleanup(proc):
        cleanup_started.set()
        await release.wait()
        await terminate(proc)
        monotonic[0] = 130.0

    monkeypatch.setattr(market_reads, "_read", real_read)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(process_tools, "_terminate", cleanup)
    owner = asyncio.create_task(collect_once(feed, clock=lambda: NOW))
    try:
        await asyncio.wait_for(cleanup_started.wait(), 10)
        with pytest.raises(market_reads.MarketReadAlreadyRunning):
            await collect_once(feed, clock=lambda: NOW)
        assert not owner.done() and feed.path.read_bytes() == before
    finally:
        release.set()
    with pytest.raises(TimeoutError, match="publication deadline"):
        await owner
    assert len(children) == 1 and children[0].returncode == 0
    assert feed.path.read_bytes() == before and feed.latest() == saved
    with market_read_lease(feed.path):
        pass


@pytest.mark.anyio
async def test_late_refresh_halts_without_renewing_health_or_retry(tmp_path, monkeypatch):
    runtime, engine, feed, _, _ = context(tmp_path)
    monotonic = monotonic_clock(monkeypatch)
    calls, previous = [], []

    async def late(req):
        calls.append(req)
        if len(calls) == 2:
            previous.append((feed.path.read_bytes(), feed.latest(), engine.journal.report(now=NOW)))
            monotonic[0] = req.deadline_monotonic
        return result(req)

    monkeypatch.setattr(market_reads, "_read", late)
    service = runtime.market_service
    assert await service.run(asyncio.Event()) == 1
    report = engine.journal.report(now=NOW)
    before, saved, prior_report = previous[0]
    assert len(calls) == 2 and feed.path.read_bytes() == before and feed.latest() == saved
    state = report["market_service"]
    assert state["status"] == "FAILED" and not state["fresh"]
    assert prior_report["market_service"]["fresh"]
    assert state["last_success_at"] == prior_report["market_service"]["last_success_at"]
    assert state["last_feed_sequence"] == prior_report["market_service"]["last_feed_sequence"] == 1
    assert state["error_class"] == "TimeoutError" and report["halted"]
    assert "PRIVATE" not in json.dumps(report)
    assert runtime.supervisor.venue.submit_count == 0


@pytest.mark.anyio
async def test_before_deadline_publication_and_expired_idempotent_receipt(tmp_path, monkeypatch):
    feed, policy = feed_context(tmp_path)
    monotonic = monotonic_clock(monkeypatch)
    requests = []

    async def read(req):
        requests.append(req)
        monotonic[0] = req.deadline_monotonic - 0.001
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    assert (await collect_once(feed, clock=lambda: NOW))["feed_sequence"] == 1
    sample = feed.latest()[1]
    monotonic[0] = requests[0].deadline_monotonic
    before = feed.path.read_bytes()
    with pytest.raises(TimeoutError):
        feed.publish(
            requests[0].request_id,
            sample,
            source=policy.model_dump(mode="json"),
            deadline_monotonic=requests[0].deadline_monotonic,
        )
    assert feed.path.read_bytes() == before


@pytest.mark.anyio
@pytest.mark.parametrize("lock", ("writer", "reader"))
async def test_sqlite_contention_uses_remaining_budget_and_releases_transaction(
    tmp_path, monkeypatch, lock
):
    feed, policy = feed_context(tmp_path)
    before, saved = await warm(feed, monkeypatch)
    connect, waits, commit_waits = sqlite3.connect, [], []

    def connection(*args, **kwargs):
        waits.append(kwargs["timeout"])
        db = connect(*args, **kwargs)

        def trace(sql):
            if sql.startswith("PRAGMA busy_timeout="):
                commit_waits.append(int(sql.split("=")[1]))

        db.set_trace_callback(trace)
        return db

    with sqlite3.connect(feed.path) as holder:
        holder.execute("BEGIN IMMEDIATE" if lock == "writer" else "BEGIN")
        holder.execute("SELECT * FROM quote_meta").fetchall()
        started = time.monotonic()
        with monkeypatch.context() as patch:
            patch.setattr(quote_feed.sqlite3, "connect", connection)
            with pytest.raises((TimeoutError, sqlite3.OperationalError)):
                feed.publish(
                    "locked",
                    saved[1],
                    source=policy.model_dump(mode="json"),
                    deadline_monotonic=started + 0.025,
                )
        assert len(waits) == 1 and 0 < waits[0] <= 0.025
        assert len(commit_waits) == (0 if lock == "writer" else 1)
        if commit_waits:
            assert 0 <= commit_waits[0] <= int(waits[0] * 1000)
        assert time.monotonic() - started < 0.5
    assert feed.path.read_bytes() == before and feed.latest() == saved
    assert (await collect_once(feed, clock=lambda: NOW))["feed_sequence"] == 2


@pytest.mark.parametrize("deadline", (float("inf"), float("nan"), -1, 0, True))
def test_invalid_deadlines_cannot_disable_publication_bound(tmp_path, deadline):
    feed, policy = feed_context(tmp_path)
    before = feed.path.read_bytes()
    sample = result(request(policy))
    with pytest.raises(ValueError, match="finite positive"):
        feed.publish(
            "bad", sample, source=policy.model_dump(mode="json"), deadline_monotonic=deadline
        )
    assert feed.path.read_bytes() == before
