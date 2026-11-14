"""Source separation, market-only reads and bounded collector cleanup."""

import asyncio
import json
import os
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest

from app.domain.models import AccountState
from app.execution import market_read_worker, market_reads
from app.execution.market_reads import (
    MarketReadPolicy,
    MarketReadRequest,
    MarketReadResult,
    collect_once,
    private_oauth,
    source_hash,
)
from app.execution.quote_feed import DurableQuoteFeed
from app.execution.runtime import runtime_lease
from app.execution.runtime_cli import initialize, load, main
from app.robinhood.gateway import RobinhoodMarketReadGateway, UnsafeRobinhoodToolError
from app.robinhood.market import RobinhoodMarketData
from tests.test_execution_rehearsal import NOW, packet
from tests.test_robinhood_market import FakeGateway


def oauth(tmp_path):
    path = tmp_path / "broker-oauth.json"
    path.write_text(
        json.dumps(
            {
                "tokens": {"access_token": "PRIVATE-BROKER-TOKEN"},
                "client_info": {"client_id": "PRIVATE-CLIENT"},
            }
        )
    )
    path.chmod(0o600)
    return path


def feed_context(tmp_path):
    policy = MarketReadPolicy(oauth_file=str(oauth(tmp_path)))
    feed = DurableQuoteFeed(
        tmp_path / "quotes.db", symbols=["SPY"], source=policy.model_dump(mode="json")
    )
    return feed, policy


def result(request, **changes):
    candidate = packet().candidates[0].model_copy(deep=True)
    candidate.quote.symbol = "SPY"
    data = dict(
        feed_id=request.feed_id,
        request_id=request.request_id,
        source_hash=source_hash(request.policy),
        collected_at=NOW,
        candidates=[candidate],
        regime="mixed",
    )
    data.update(changes)
    return MarketReadResult(**data)


def request(policy):
    return MarketReadRequest(
        policy=policy,
        feed_id="a" * 32,
        request_id="b" * 32,
        symbols=["SPY"],
        started_at=NOW,
        parent_pid=os.getpid(),
        deadline_monotonic=time.monotonic() + 5,
    )


@pytest.mark.anyio
async def test_publication_is_market_only_read_only_to_engine_and_persistent(tmp_path, monkeypatch):
    feed, policy = feed_context(tmp_path)

    async def read(req):
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    published = await collect_once(feed, clock=lambda: NOW)
    assert published["feed_sequence"] == 1 and published["candidate_count"] == 1
    sequence, saved = DurableQuoteFeed(feed.path).latest()
    assert (
        sequence == 1
        and saved.account.equity == saved.account.buying_power == saved.account.cash == 0
    )
    assert saved.account.position is None and saved.account.working_orders == []
    assert "PRIVATE" not in saved.model_dump_json()
    assert "PRIVATE" not in json.dumps(published)
    before = feed.path.read_bytes()
    with pytest.raises(ValueError, match="source"):
        feed.publish("manual", saved)
    assert before == feed.path.read_bytes()
    assert feed.source == policy.model_dump(mode="json")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    (
        "feed",
        "request",
        "source",
        "old-collection",
        "future-collection",
        "missing",
        "duplicate",
        "foreign",
        "stale",
        "future",
        "naive",
        "crossed",
    ),
)
async def test_invalid_evidence_cannot_publish_or_replace(fault, tmp_path, monkeypatch):
    feed, policy = feed_context(tmp_path)

    async def read(req):
        output = result(req)
        if fault in {"feed", "request", "source"}:
            output = output.model_copy(
                update={fault + ("_hash" if fault == "source" else "_id"): "wrong"}
            )
        elif fault in {"old-collection", "future-collection"}:
            output = output.model_copy(
                update={
                    "collected_at": NOW + timedelta(seconds=-1 if fault == "old-collection" else 1)
                }
            )
        elif fault == "missing":
            output = output.model_copy(update={"candidates": []})
        elif fault == "duplicate":
            output = output.model_copy(update={"candidates": output.candidates * 2})
        elif fault == "foreign":
            output.candidates[0].quote.symbol = "QQQ"
        elif fault in {"stale", "future", "naive"}:
            output.candidates[0].quote.timestamp = (
                NOW.replace(tzinfo=None)
                if fault == "naive"
                else NOW + timedelta(seconds=-91 if fault == "stale" else 1)
            )
        else:
            output.candidates[0].quote.ask = output.candidates[0].quote.bid - 1
        return output

    monkeypatch.setattr(market_reads, "_read", read)
    before = feed.path.read_bytes()
    with pytest.raises(ValueError):
        await collect_once(feed, clock=lambda: NOW)
    assert feed.path.read_bytes() == before
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        feed.latest()


@pytest.mark.parametrize(
    "fault", ("missing", "symlink", "fifo", "permissions", "oversized", "malformed", "tokens")
)
def test_private_oauth_requires_preexisting_bounded_owner_credentials(fault, tmp_path):
    path = oauth(tmp_path)
    if fault == "missing":
        path.unlink()
    elif fault == "symlink":
        target = tmp_path / "real.json"
        path.rename(target)
        path.symlink_to(target)
    elif fault == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif fault == "permissions":
        path.chmod(0o644)
    elif fault == "oversized":
        path.write_bytes(b"x" * (64 * 1024 + 1))
    elif fault == "malformed":
        path.write_text("not json")
    else:
        path.write_text('{"client_info": {"client_id":"x"}}')
    with pytest.raises((ValueError, OSError)):
        private_oauth(path)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name",
    (
        "get_portfolio",
        "get_equity_positions",
        "get_equity_orders",
        "review_equity_order",
        "place_equity_order",
        "cancel_equity_order",
    ),
)
async def test_market_gateway_denies_nonmarket_authority_before_client(name):
    class Client:
        async def call_tool(self, *args):
            raise AssertionError("Denied tool reached client")

    with pytest.raises(UnsafeRobinhoodToolError):
        await RobinhoodMarketReadGateway(Client(), "unused").call_safe(name, {})


@pytest.mark.anyio
async def test_worker_reads_four_tools_without_account_authority_output(tmp_path, monkeypatch):
    _, policy = feed_context(tmp_path)
    calls = []

    class Client(FakeGateway):
        async def call_tool(self, name, args):
            calls.append((name, args))
            if name == "get_accounts":
                return {
                    "structuredContent": {
                        "data": {
                            "accounts": [
                                {
                                    "account_number": "PRIVATE-ACCOUNT",
                                    "type": "limited_margin",
                                    "brokerage_account_type": "individual",
                                    "agentic_allowed": True,
                                    "state": "active",
                                    "deactivated": False,
                                    "permanently_deactivated": False,
                                }
                            ]
                        }
                    }
                }
            return await super().call_safe(name, args)

    class Connection:
        @asynccontextmanager
        async def client(self):
            yield Client(NOW)

    monkeypatch.setattr(market_read_worker, "connection", lambda policy: Connection())
    monkeypatch.setattr(market_read_worker, "utc_now", lambda: NOW)
    monkeypatch.setattr(
        market_read_worker,
        "RobinhoodMarketData",
        lambda gateway, **kwargs: RobinhoodMarketData(gateway, clock=lambda: NOW, **kwargs),
    )
    output = await market_read_worker.collect(request(policy))
    assert {name for name, _ in calls} == {
        "get_accounts",
        "get_equity_quotes",
        "get_equity_tradability",
        "get_equity_historicals",
    }
    assert "PRIVATE" not in output.model_dump_json()
    assert output.candidates[0].quote.symbol == "SPY"
    assert output.source_hash == source_hash(policy)
    tradability = next(args for name, args in calls if name == "get_equity_tradability")
    assert tradability["account_number"] == "PRIVATE-ACCOUNT"


def test_source_and_runtime_policy_cannot_change_or_adopt_existing_feed(tmp_path):
    feed, policy = feed_context(tmp_path)
    with pytest.raises(ValueError, match="new feed"):
        DurableQuoteFeed(feed.path, source=policy.model_dump(mode="json"))
    with sqlite3.connect(feed.path) as db:
        meta = json.loads(db.execute("SELECT payload FROM quote_meta").fetchone()[0])
        meta["source"]["max_age_seconds"] = 60
        db.execute("UPDATE quote_meta SET payload=?", (json.dumps(meta),))
    with pytest.raises(ValueError, match="identity"):
        feed.latest()


@pytest.mark.anyio
async def test_sourced_feed_supervision_scheduled_hold_uses_virtual_cash(tmp_path, monkeypatch):
    path = oauth(tmp_path)
    directory = tmp_path / "population"
    initialize(directory, capital=10, symbols=["SPY"], market_oauth_file=path)
    feed = DurableQuoteFeed(directory / "quotes.db")

    async def read(req):
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    journal = directory / "execution.db"
    authority = Path(str(journal) + ".authority.db")
    before = (journal.read_bytes(), authority.read_bytes())
    await collect_once(feed, clock=lambda: NOW)
    assert before == (journal.read_bytes(), authority.read_bytes())
    with runtime_lease(journal):
        runtime = load(directory)
        runtime.clock = runtime.supervisor.clock = lambda: NOW
        runtime._claim()
        runtime.supervisor._claim()
        await runtime.supervisor._tick()
        output = await runtime.cycle_once()
        assert output["status"] == "COMPLETE"
        with runtime.engine.journal.read() as db:
            saved = json.loads(
                db.execute("SELECT packet_json FROM execution_runtime_cycles").fetchone()[0]
            )
            assert saved["account"]["cash"] == "10"
            assert saved["account"]["buying_power"] == "10"
            assert saved["account"]["position"] is None
        assert runtime.supervisor.venue.submit_count == 0
        runtime._publish("STOPPING")
        runtime.supervisor._finish("STOPPED")
        runtime._publish("STOPPED")
    assert runtime.engine.journal.report(now=NOW)["restore_fence"]["status"] == "VERIFIED"


def test_cli_no_source_cannot_collect_and_source_cannot_manually_publish(tmp_path, capsys):
    directory = tmp_path / "fixtures"
    initialize(directory, capital=10, symbols=["SPY"])
    assert main(["collect", "--directory", str(directory)]) == 1
    output = capsys.readouterr().out
    assert "ValueError" in output and "PRIVATE" not in output


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ("timeout", "cancel", "malformed", "oversized", "crash"))
async def test_real_bounded_child_failure_reaped_without_publication(tmp_path, monkeypatch, fault):
    feed, policy = feed_context(tmp_path)
    real_spawn = asyncio.create_subprocess_exec
    processes = []
    environments = []
    scripts = {
        "timeout": "import time;time.sleep(30)",
        "cancel": "import time;time.sleep(30)",
        "malformed": "print('PRIVATE-INVALID-RESPONSE')",
        "oversized": "print('x'*262145)",
        "crash": "import os;os._exit(7)",
    }

    async def spawn(*args, **kwargs):
        environments.append(kwargs["env"])
        process = await real_spawn(sys.executable, "-c", scripts[fault], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setenv("OPENAI_API_KEY", "PRIVATE-MODEL-KEY")
    monkeypatch.setenv("HTTP_PROXY", "http://private-proxy")
    monkeypatch.setattr(market_reads.time, "monotonic", time.monotonic)
    req = request(policy).model_copy(update={"deadline_monotonic": time.monotonic() + 0.2})
    task = asyncio.create_task(market_reads._read(req))
    if fault == "cancel":
        while not processes:
            await asyncio.sleep(0.001)
        task.cancel()
        task.cancel()
    with pytest.raises((ValueError, TimeoutError, asyncio.CancelledError)):
        await task
    assert processes and all(p.returncode is not None for p in processes)
    assert all("OPENAI_API_KEY" not in env and "HTTP_PROXY" not in env for env in environments)
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        feed.latest()


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint", "https://evil.example/mcp"),
        ("redirect_uri", "https://evil.example/callback"),
        ("oauth_file", "relative.json"),
        ("timeout_seconds", 0),
        ("timeout_seconds", 31),
        ("max_age_seconds", 91),
        ("max_age_seconds", float("nan")),
        ("lookback_days", 30),
        ("interval", "day"),
        ("provider", "other-provider"),
    ],
)
def test_read_policy_is_explicit_bounded_and_pinned(tmp_path, field, value):
    with pytest.raises(ValueError):
        MarketReadPolicy(**{"oauth_file": str(tmp_path / "oauth.json"), field: value})


@pytest.mark.anyio
async def test_duplicate_reader_cannot_call_or_publish_while_owner_awaits(tmp_path, monkeypatch):
    feed, _ = feed_context(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def read(req):
        calls.append(req)
        entered.set()
        await release.wait()
        return result(req)

    monkeypatch.setattr(market_reads, "_read", read)
    owner = asyncio.create_task(collect_once(feed, clock=lambda: NOW))
    await entered.wait()
    before = feed.path.read_bytes()
    with pytest.raises(market_reads.MarketReadAlreadyRunning):
        await collect_once(DurableQuoteFeed(feed.path), clock=lambda: NOW)
    assert before == feed.path.read_bytes() and len(calls) == 1
    release.set()
    assert (await owner)["feed_sequence"] == 1
    assert (await collect_once(feed, clock=lambda: NOW))["feed_sequence"] == 2


@pytest.mark.parametrize(
    "field", ("cash", "equity", "buying_power", "high_watermark", "realized_pnl")
)
def test_sourced_packets_cannot_import_account_authority(field, tmp_path):
    feed, policy = feed_context(tmp_path)
    sample = packet()
    sample.account = AccountState(
        **{
            "cash": 0,
            "equity": 0,
            "buying_power": 0,
            "high_watermark": 0,
            "realized_pnl": 0,
            field: 75,
        }
    )
    before = feed.path.read_bytes()
    with pytest.raises(ValueError, match="authority"):
        feed.publish("foreign-account", sample, source=policy.model_dump(mode="json"))
    assert before == feed.path.read_bytes()


@pytest.mark.parametrize("fault", ("symlink", "fifo", "permissions"))
def test_market_read_lock_must_be_private_regular_file(fault, tmp_path):
    feed, _ = feed_context(tmp_path)
    lock = Path(str(feed.path) + ".market-read.lock")
    if fault == "symlink":
        lock.symlink_to(feed.path)
    elif fault == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        lock.touch(mode=0o644)
        lock.chmod(0o644)  # Keep this deliberately unsafe even under umask 077.
    with pytest.raises((ValueError, OSError)):
        with market_reads.market_read_lease(feed.path):
            raise AssertionError("Unsafe lock accepted")


def test_headless_connection_reuses_private_storage_and_never_opens_browser(tmp_path):
    policy = MarketReadPolicy(oauth_file=str(oauth(tmp_path)))
    conn = market_read_worker.connection(policy)
    assert conn.url == policy.endpoint and conn.redirect_uri == policy.redirect_uri
    assert isinstance(conn.storage, market_read_worker.PrivateOAuthStorage)
    with pytest.raises(RuntimeError, match="headless"):
        asyncio.run(conn.redirect_handler("PRIVATE-AUTH-URL"))
    with pytest.raises(RuntimeError, match="headless"):
        asyncio.run(conn.callback_handler())


@pytest.mark.anyio
async def test_repeated_cancel_holds_reader_lease_through_actual_child_cleanup(
    tmp_path, monkeypatch
):
    from app.execution import process as process_tools

    feed, _ = feed_context(tmp_path)
    real_spawn = asyncio.create_subprocess_exec
    real_terminate = process_tools._terminate
    child, cleanup_started, release = [], asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        proc = await real_spawn(sys.executable, "-c", "import time;time.sleep(30)", **kwargs)
        child.append(proc)
        return proc

    async def terminate(proc):
        cleanup_started.set()
        await release.wait()
        await real_terminate(proc)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(process_tools, "_terminate", terminate)
    owner = asyncio.create_task(collect_once(feed, clock=lambda: NOW))
    while not child:
        await asyncio.sleep(0.001)
    owner.cancel()
    await cleanup_started.wait()
    owner.cancel()
    await asyncio.sleep(0.01)
    with pytest.raises(market_reads.MarketReadAlreadyRunning):
        await collect_once(DurableQuoteFeed(feed.path), clock=lambda: NOW)
    assert not owner.done() and child[0].returncode is None
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert child[0].returncode is not None
    with market_reads.market_read_lease(feed.path):
        pass
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        feed.latest()


def test_runtime_load_rejects_reopened_changed_source_policy(tmp_path):
    directory = tmp_path / "population"
    initialize(directory, capital=10, symbols=["SPY"], market_oauth_file=oauth(tmp_path))
    with sqlite3.connect(directory / "quotes.db") as db:
        meta = json.loads(db.execute("SELECT payload FROM quote_meta").fetchone()[0])
        meta["source"]["max_age_seconds"] = 60
        db.execute("UPDATE quote_meta SET payload=?", (json.dumps(meta),))
    with runtime_lease(directory / "execution.db"):
        with pytest.raises(ValueError, match="immutable"):
            load(directory)


def test_private_storage_refresh_preserves_permissions_without_broker_call(tmp_path):
    path = oauth(tmp_path)
    storage = market_read_worker.PrivateOAuthStorage(path)
    refreshed = storage._read()
    refreshed["tokens"]["access_token"] = "REFRESHED-PRIVATE-TOKEN"
    storage._write(refreshed)
    assert storage._read() == refreshed
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    with pytest.raises(ValueError, match="bound"):
        storage._write({"tokens": {"access_token": "x" * 65536}, "client_info": {"client_id": "x"}})
    assert before == path.read_bytes()


@pytest.mark.anyio
async def test_real_child_protocol_success_publishes_without_private_values(tmp_path, monkeypatch):
    feed, policy = feed_context(tmp_path)
    real_spawn = asyncio.create_subprocess_exec
    processes = []
    fixture = result(request(policy)).model_dump_json()
    code = (
        "import sys,json; req=json.load(sys.stdin); out=json.loads(" + repr(fixture) + ");"
        "out['request_id']=req['request_id'];out['feed_id']=req['feed_id'];print(json.dumps(out))"
    )

    async def spawn(*args, **kwargs):
        assert args == (sys.executable, "-I", "-m", "app.execution.market_read_worker")
        proc = await real_spawn(*args[:2], "-c", code, **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    published = await collect_once(feed, clock=lambda: NOW)
    assert published["feed_sequence"] == 1
    assert processes[0].returncode == 0
    assert "PRIVATE" not in feed.latest()[1].model_dump_json()


@pytest.mark.parametrize(
    "field", ("session_context", "recent_lessons", "position", "working_orders")
)
def test_source_feed_cannot_publish_account_or_strategy_metadata(tmp_path, field):
    feed, policy = feed_context(tmp_path)
    sample = packet()
    sample.account = AccountState(equity=0, cash=0, buying_power=0, high_watermark=0)
    if field == "session_context":
        sample.session_context = {"operator": "PRIVATE"}
    elif field == "recent_lessons":
        sample.recent_lessons = ["PRIVATE"]
    elif field == "working_orders":
        sample.account.working_orders = [{"id": "PRIVATE"}]
    else:
        from app.domain.models import Position

        sample.account.position = Position(
            symbol="SPY",
            quantity=1,
            entry_price=10,
            current_price=10,
            original_invalidation=9,
            thesis="PRIVATE",
            opened_at=NOW,
        )
    with pytest.raises(ValueError, match="authority"):
        feed.publish("bad", sample, source=policy.model_dump(mode="json"))
