"""Continuous source composition keeps quote provenance and risk authority separate."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from app.execution import market_reads, market_state
from app.execution.economics import CostAccounting, CostPolicy
from app.execution.engine import ExecutionBlocked
from app.execution.market_reads import (
    MarketReadAlreadyRunning,
    market_read_lease,
)
from app.execution.market_service import MarketServiceLimits, PaperMarketService
from app.execution.quote_feed import DurableQuoteFeed
from app.execution.runtime import PaperRuntime, RuntimeLimits, runtime_lease
from app.execution.runtime_cli import initialize, load, main
from app.execution.supervisor import ExecutionSupervisor, SupervisorLimits
from tests.test_execution_market_reads import oauth, result
from tests.test_execution_rehearsal import NOW, decision, packet
from tests.test_execution_supervisor import wait_until


def context(tmp_path, *, model=False, read_timeout=0.5, source_max_age=4):
    directory = tmp_path / "population"
    initialize(directory, capital=10, symbols=["SPY"], market_oauth_file=oauth(tmp_path))
    with runtime_lease(directory / "execution.db"):
        base = load(directory)
    feed = base.supervisor.feed
    # A new explicit test population, before any attempts, with bounded fast-source policy.
    with sqlite3.connect(feed.path) as db:
        meta = json.loads(db.execute("SELECT payload FROM quote_meta").fetchone()[0])
        meta["source"]["timeout_seconds"] = read_timeout
        db.execute("UPDATE quote_meta SET payload=?", (json.dumps(meta),))
    feed = DurableQuoteFeed(feed.path)
    # Remove only provisioning enrollments in this disposable setup, never an existing service.
    with base.engine.journal.write() as db:
        db.execute("DELETE FROM execution_runtime")
        db.execute("DELETE FROM execution_supervisor")
    clock = [NOW]
    supervisor = ExecutionSupervisor(
        base.engine,
        base.supervisor.venue,
        feed,
        limits=SupervisorLimits(poll_seconds=0.05, tick_timeout_seconds=3, max_age_seconds=4),
        clock=lambda: clock[0],
    )
    service = PaperMarketService(
        base.engine,
        feed,
        limits=MarketServiceLimits(poll_seconds=0.05, max_age_seconds=source_max_age),
        clock=lambda: clock[0],
    )
    service.enroll()
    costs = (
        CostAccounting(base.engine, CostPolicy(total_budget=1, daily_budget=1)) if model else None
    )
    runtime = PaperRuntime(
        supervisor,
        market_service=service,
        limits=RuntimeLimits(poll_seconds=0.05, max_age_seconds=4, cycle_timeout_seconds=6),
        clock=lambda: clock[0],
    )
    runtime.enroll()
    return runtime, base.engine, feed, clock, costs


async def begin(runtime):
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(stop))
    await wait_until(lambda: runtime.owner is not None or task.done())
    return stop, task


def install_success(monkeypatch, calls, clock):
    async def read(req):
        calls.append(req)
        output = result(req).model_copy(update={"collected_at": clock[0]})
        output.candidates[0].quote.timestamp = clock[0]
        return output

    monkeypatch.setattr(market_reads, "_read", read)


@pytest.mark.anyio
@pytest.mark.parametrize("account_delay", (0, 0.75))
async def test_cold_session_warms_with_no_entry_and_runs_scheduled_hold(
    tmp_path, monkeypatch, account_delay
):
    # The fixture deliberately holds a source read across a native account read.
    # Its source budget must cover that synchronization, not race a 0.5s deadline.
    runtime, engine, feed, clock, _ = context(tmp_path, read_timeout=5, source_max_age=8)
    reconcile = type(engine).reconcile_fixture

    async def delayed_account(self, *args, **kwargs):
        await asyncio.sleep(account_delay)
        return await reconcile(self, *args, **kwargs)

    monkeypatch.setattr(type(engine), "reconcile_fixture", delayed_account)
    entered, release, advance = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def read(req):
        calls.append(req)
        entered.set()
        if len(calls) == 1:
            await release.wait()
        elif len(calls) == 2:
            # Keep a stable exact sample while the native account read completes.
            await advance.wait()
        else:
            await asyncio.Event().wait()
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    stop, task = await begin(runtime)
    await entered.wait()
    await wait_until(lambda: engine.journal.report(now=NOW)["supervisor"]["status"] == "WAITING")
    report = engine.journal.report(now=NOW)
    assert not report["market_service"]["fresh"] and not report["supervisor"]["fresh"]
    assert report["runtime"]["cycles"] == {} and not report["halted"]
    with pytest.raises(ExecutionBlocked):
        engine.prepare("cold", decision(), packet(), now=NOW)
    with pytest.raises(MarketReadAlreadyRunning):
        await market_reads.collect_once(DurableQuoteFeed(feed.path), clock=lambda: NOW)
    release.set()
    await wait_until(lambda: engine.journal.report(now=NOW)["runtime"]["cycles"] == {"COMPLETE": 1})
    advance.set()
    await wait_until(lambda: feed.latest()[0] == 2)
    stop.set()
    assert await task == 0
    report = engine.journal.report(now=NOW)
    assert report["runtime"]["status"] == report["market_service"]["status"] == "STOPPED"
    assert report["restore_fence"]["status"] == "VERIFIED"
    assert runtime.supervisor.venue.submit_count == 0
    assert feed.latest()[0] >= 2 and not report["halted"]


@pytest.mark.anyio
async def test_closed_flat_service_waits_without_credentials_or_child_calls(tmp_path, monkeypatch):
    runtime, engine, feed, clock, _ = context(tmp_path)
    clock[0] = NOW.replace(hour=23)
    Path(feed.source["oauth_file"]).unlink()

    async def forbidden(*args, **kwargs):
        raise AssertionError("Closed flat source made a read")

    monkeypatch.setattr(market_reads, "_collect_owned", forbidden)
    stop, task = await begin(runtime)
    await wait_until(
        lambda: engine.journal.report(now=clock[0])["market_service"]["status"] == "IDLE"
    )
    assert engine.journal.report(now=clock[0])["runtime"]["cycles"] == {}
    stop.set()
    assert await task == 0
    assert not engine.journal.report(now=clock[0])["halted"]


@pytest.mark.anyio
async def test_closed_to_open_waits_for_fresh_source_without_misreporting_health(
    tmp_path, monkeypatch
):
    runtime, engine, _, clock, _ = context(tmp_path, read_timeout=5, source_max_age=8)
    clock[0] = NOW.replace(hour=13, minute=29, second=59)
    entered, release = asyncio.Event(), asyncio.Event()
    attempts = []

    async def read(req):
        attempts.append(req)
        if len(attempts) > 1:
            # Keep the first exact sample stable while native reconciliation
            # completes; the next bounded refresh is cancelled on runtime stop.
            await asyncio.Event().wait()
        entered.set()
        await release.wait()
        output = result(req).model_copy(update={"collected_at": clock[0]})
        output.candidates[0].quote.timestamp = clock[0]
        return output

    monkeypatch.setattr(market_reads, "_read", read)
    stop, task = await begin(runtime)
    try:
        await wait_until(
            lambda: engine.journal.report(now=clock[0])["market_service"]["status"] == "IDLE"
        )
        clock[0] += timedelta(seconds=1)
        await asyncio.wait_for(entered.wait(), 10)
        await wait_until(
            lambda: engine.journal.report(now=clock[0])["supervisor"]["status"] == "WAITING"
        )
        release.set()
        await wait_until(
            lambda: (
                task.done()
                or engine.journal.report(now=clock[0])["runtime"]["cycles"] == {"COMPLETE": 1}
            )
        )
        assert engine.journal.report(now=clock[0])["runtime"]["cycles"] == {"COMPLETE": 1}
    finally:
        release.set()
        stop.set()
        assert await asyncio.wait_for(task, 10) == 0


@pytest.mark.anyio
@pytest.mark.parametrize("error", (TimeoutError, ValueError, RuntimeError))
async def test_refresh_failure_halts_without_retries_or_replacing_sample(
    tmp_path, monkeypatch, error
):
    runtime, engine, feed, clock, _ = context(tmp_path)
    calls = []
    failed = asyncio.Event()

    async def read(req):
        calls.append(req)
        if len(calls) > 1:
            failed.set()
            raise error("PRIVATE-RAW-MCP")
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    stop, task = await begin(runtime)
    await failed.wait()
    assert await task == 1
    report = engine.journal.report(now=NOW)
    assert report["halted"] and report["runtime"]["status"] == "FAILED"
    assert report["market_service"]["status"] == "FAILED" and not report["market_service"]["fresh"]
    assert len(calls) == 2 and feed.latest()[0] == 1
    assert report["market_service"]["error_class"] == error.__name__
    assert "PRIVATE" not in json.dumps(report)
    assert report["restore_fence"]["status"] == "VERIFIED"


@pytest.mark.anyio
async def test_source_health_gates_entries_and_model_receipts_without_blocking_hold(
    tmp_path, monkeypatch
):
    runtime, engine, feed, clock, _ = context(tmp_path)
    calls = []
    install_success(monkeypatch, calls, clock)
    stop, task = await begin(runtime)
    await wait_until(lambda: engine.journal.report(now=NOW)["supervisor"]["fresh"])
    runtime.market_service.revoke()
    with pytest.raises(ExecutionBlocked, match="MARKET_SERVICE"):
        engine.prepare("denied", decision(), packet(), now=NOW)
    costs = CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1))
    with pytest.raises(ExecutionBlocked, match="MARKET_SERVICE"):
        costs.begin("denied-model", packet(), now=NOW)
    assert engine.prepare("cash-hold", decision("HOLD"), packet(), now=NOW) is None
    stop.set()
    await task


@pytest.mark.parametrize("fault", ("source", "limits", "universe", "engine", "authority"))
def test_explicit_enrollment_bindings_and_freshness_bounds(fault, tmp_path):
    runtime, engine, feed, clock, _ = context(tmp_path)
    if fault == "source":
        feed.source = None
    elif fault == "limits":
        with pytest.raises(ValueError):
            PaperMarketService(
                engine, feed, limits=MarketServiceLimits(poll_seconds=30, max_age_seconds=20)
            )
        return
    elif fault == "universe":
        feed.symbols = ["QQQ"]
    elif fault == "engine":
        engine = object()
    else:
        Path(str(engine.journal.path) + ".authority.db").unlink()
    with pytest.raises((ValueError, ExecutionBlocked)):
        service = PaperMarketService(engine, feed)
        service.enroll()


def test_cli_continuous_opt_in_preserves_old_populations_and_read_only_report(tmp_path, capsys):
    auth = oauth(tmp_path)
    old = tmp_path / "old"
    new = tmp_path / "new"
    initialize(old, capital=10, symbols=["SPY"], market_oauth_file=auth)
    with runtime_lease(old / "execution.db"):
        assert load(old).market_service is None
    assert (
        main(
            [
                "init",
                "--directory",
                str(new),
                "--capital",
                "10",
                "--symbols",
                "SPY",
                "--market-oauth-file",
                str(auth),
                "--continuous-market",
            ]
        )
        == 0
    )
    capsys.readouterr()
    with runtime_lease(new / "execution.db"):
        assert load(new).market_service is not None
    before = {p.name: p.read_bytes() for p in new.iterdir() if p.suffix == ".db"}
    assert main(["report", "--directory", str(new)]) == 0
    assert json.loads(capsys.readouterr().out)["market_service"]["status"] == "STOPPED"
    assert before == {p.name: p.read_bytes() for p in new.iterdir() if p.suffix == ".db"}
    with pytest.raises(ValueError, match="OAuth"):
        initialize(tmp_path / "bad", capital=10, symbols=["SPY"], continuous_market=True)
    assert not (tmp_path / "bad").exists()


@pytest.mark.anyio
async def test_runtime_stop_holds_both_leases_until_source_cleanup_finishes(tmp_path, monkeypatch):
    runtime, engine, feed, clock, _ = context(tmp_path)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def read(req):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await asyncio.shield(release.wait())

    monkeypatch.setattr(market_reads, "_read", read)
    stop, task = await begin(runtime)
    await entered.wait()
    stop.set()
    await cleaning.wait()
    task.cancel()
    task.cancel()
    await asyncio.sleep(0.01)
    with pytest.raises(MarketReadAlreadyRunning):
        with market_read_lease(feed.path):
            pass
    from app.execution.runtime import RuntimeAlreadyRunning

    with pytest.raises(RuntimeAlreadyRunning):
        with runtime_lease(engine.journal.path):
            pass
    assert not engine.journal.report(now=NOW)["market_service"]["fresh"]
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    with market_read_lease(feed.path):
        pass
    with runtime_lease(engine.journal.path):
        pass
    assert engine.journal.report(now=NOW)["runtime"]["status"] == "STOPPED"


@pytest.mark.anyio
async def test_protective_sell_continues_while_market_refresh_waits(tmp_path, monkeypatch):
    from decimal import Decimal

    from tests.test_execution_supervisor import enter

    # Deliberately pause a source read across native entry/fill/reconciliation.
    # Keep the test policy bounded without coupling it to subsecond child startup.
    runtime, engine, feed, clock, _ = context(tmp_path, read_timeout=5, source_max_age=8)
    second, release, blocked = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def read(req):
        calls.append(req)
        output = result(req)
        if len(calls) == 2:
            second.set()
            await release.wait()
            output.candidates[0].quote.bid = Decimal("9.4")
            output.candidates[0].quote.ask = Decimal("9.41")
            output.candidates[0].quote.last = Decimal("9.41")
        elif len(calls) >= 3:
            blocked.set()
            await asyncio.Event().wait()
        return output

    monkeypatch.setattr(market_reads, "_read", read)
    stop, task = await begin(runtime)
    try:
        await wait_until(lambda: second.is_set() or task.done())
        assert second.is_set() and not task.done()
        await wait_until(lambda: engine.journal.report(now=NOW)["supervisor"]["fresh"])
        venue = runtime.supervisor.venue
        await enter(engine, venue, p=feed.latest()[1])
        release.set()
        await wait_until(lambda: blocked.is_set() or task.done())
        assert blocked.is_set() and not task.done()
        await wait_until(lambda: venue.submit_count == 2)
        order = engine.journal.report(now=NOW)["orders"][-1]["intent"]
        assert order["side"] == "SELL" and not task.done()
        venue.fill(
            order["client_id"],
            Decimal(order["quantity"]),
            Decimal("9.4"),
            NOW,
            fill_id="protective",
        )
        await wait_until(lambda: engine.journal.report(now=NOW)["ledger"]["position"] is None)
        stop.set()
        assert await asyncio.wait_for(task, 10) == 0
        assert not engine.journal.report(now=NOW)["halted"]
    finally:
        stop.set()
        await asyncio.wait_for(task, 10)


@pytest.mark.anyio
async def test_owned_risk_cannot_use_flat_warmup_to_ignore_missing_quotes(tmp_path, monkeypatch):
    from tests.test_execution_supervisor import enter

    runtime, engine, feed, clock, _ = context(tmp_path)
    calls = []
    install_success(monkeypatch, calls, clock)
    stop, task = await begin(runtime)
    await wait_until(lambda: engine.journal.report(now=NOW)["supervisor"]["fresh"])
    await enter(engine, runtime.supervisor.venue, p=feed.latest()[1])
    with feed._db(write=True) as db:
        db.execute("DELETE FROM quote_samples")

    async def blocked(req):
        await asyncio.Event().wait()

    monkeypatch.setattr(market_reads, "_read", blocked)
    assert await task == 1
    report = engine.journal.report(now=NOW)
    assert report["halted"] and report["ledger"]["position"] is not None
    # Any owner task can detect the missing feed first; all other tasks must drain.
    assert report["runtime"]["status"] == "FAILED"
    assert report["supervisor"]["status"] in {"FAILED", "STOPPED"}
    assert report["market_service"]["status"] in {"FAILED", "STOPPED"}
    assert runtime.supervisor.venue.submit_count == 1


@pytest.mark.anyio
async def test_supervisor_with_owned_position_never_waits_for_empty_warming_feed(tmp_path):
    from tests.test_execution_supervisor import enter

    runtime, engine, feed, _, _ = context(tmp_path)
    from app.domain.models import AccountState

    sample = packet()
    sample.account = AccountState(equity=0, cash=0, buying_power=0, high_watermark=0)
    feed.publish("initial", sample, source=feed.source)
    service = runtime.market_service
    service._claim()
    service._publish("RUNNING", sample=feed.latest())
    runtime._claim()
    runtime.supervisor._claim()
    await runtime.supervisor._tick()
    await enter(engine, runtime.supervisor.venue, p=feed.latest()[1])
    service._publish("COLLECTING")
    with feed._db(write=True) as db:
        db.execute("DELETE FROM quote_samples")
    with pytest.raises(ValueError, match="FIXTURE_QUOTES_UNAVAILABLE"):
        await runtime.supervisor._tick()
    assert engine.journal.report(now=NOW)["supervisor"]["status"] != "WAITING"
    assert runtime.supervisor.venue.submit_count == 1


@pytest.mark.anyio
async def test_interrupted_market_owner_restart_retains_halt_and_discards_old_health(
    tmp_path, monkeypatch
):
    runtime, engine, feed, clock, _ = context(tmp_path)
    with engine.journal.write() as db:
        db.execute(
            "UPDATE execution_market_service SET status='COLLECTING',owner='lost',last_success_at=?,oldest_quote_at=?,heartbeat_at=? WHERE id=1",
            (NOW.isoformat(), NOW.isoformat(), NOW.isoformat()),
        )
    entered, release = asyncio.Event(), asyncio.Event()

    async def read(req):
        entered.set()
        await release.wait()
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    stop, task = await begin(runtime)
    await entered.wait()
    report = engine.journal.report(now=NOW)
    assert report["halted"] and not report["market_service"]["fresh"]
    assert report["market_service"]["generation"] == 1
    release.set()
    await wait_until(lambda: engine.journal.report(now=NOW)["market_service"]["fresh"])
    assert engine.journal.report(now=NOW)["runtime"]["cycles"] == {}
    stop.set()
    assert await task == 0
    assert engine.journal.report(now=NOW)["halted"]


@pytest.mark.parametrize("status", ("STOPPED", "STOPPING", "FAILED", "IDLE"))
def test_stopped_or_idle_source_cannot_grant_admission_with_old_healthy_quote(status, tmp_path):
    runtime, engine, feed, clock, _ = context(tmp_path)
    service = runtime.market_service
    service._claim()
    sample = packet()
    sample.account = sample.account.model_copy(update={})
    # Publish a trusted test source result with zero account authority.
    from app.domain.models import AccountState

    sample.account = AccountState(equity=0, cash=0, buying_power=0, high_watermark=0)
    feed.publish("test", sample, source=feed.source)
    service._publish("RUNNING", sample=feed.latest())
    with engine.journal.read() as db:
        assert market_state.report(db, NOW)["fresh"]
    service._publish(status)
    with engine.journal.read() as db:
        assert not market_state.report(db, NOW)["fresh"]
        assert market_state.entry_reasons(db, NOW) == ["EXECUTION_MARKET_SERVICE_NOT_READY"]


@pytest.mark.parametrize("offset", (-1, 46))
def test_source_freshness_requires_nonfuture_recent_success(offset, tmp_path):
    runtime, engine, feed, clock, _ = context(tmp_path)
    service = runtime.market_service
    service._claim()
    with engine.journal.write() as db:
        db.execute(
            "UPDATE execution_market_service SET status='RUNNING',last_success_at=?,oldest_quote_at=? WHERE id=1",
            ((NOW - timedelta(seconds=offset)).isoformat(), NOW.isoformat()),
        )
    with engine.journal.read() as db:
        assert not market_state.report(db, NOW)["fresh"]


def test_failed_service_state_can_reduce_authority_after_configuration_changed(tmp_path):
    runtime, engine, feed, clock, _ = context(tmp_path)
    service = runtime.market_service
    service._claim()
    service.limits = MarketServiceLimits(poll_seconds=0.05, max_age_seconds=5)
    with pytest.raises(ExecutionBlocked, match="CONFIGURATION"):
        service._publish("RUNNING")
    service._publish("FAILED", error="ValueError")
    report = engine.journal.report(now=NOW)
    assert report["halted"] and report["market_service"]["status"] == "FAILED"


def test_source_waiting_grace_is_bounded_and_has_no_future_clock(tmp_path):
    runtime, engine, feed, clock, _ = context(tmp_path)
    service = runtime.market_service
    service._claim()
    service._publish("COLLECTING")
    with engine.journal.read() as db:
        assert market_state.report(db, NOW)["waiting_flat"]
        assert not market_state.report(db, NOW - timedelta(seconds=1))["waiting_flat"]
        assert not market_state.report(db, NOW + timedelta(seconds=3))["waiting_flat"]
