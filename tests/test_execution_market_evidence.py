"""Measured collector evidence is observational, never authenticated acceptance."""

import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.execution import market_read_worker, market_reads, quote_feed
from app.execution.market_reads import MarketReadDiagnostics, MarketToolObservation, collect_once
from app.robinhood.gateway import UnsafeRobinhoodToolError
from tests.test_execution_market_reads import feed_context, result
from tests.test_execution_rehearsal import NOW
from tests.test_robinhood_market import FakeGateway


def diagnostics(**changes):
    data = {
        "collection_seconds": 4.0,
        **{
            name: {"attempted": 1, "completed": 1, "elapsed_seconds": 0.5}
            for name in (
                "get_accounts",
                "get_equity_quotes",
                "get_equity_tradability",
                "get_equity_historicals",
            )
        },
    }
    data.update(changes)
    return MarketReadDiagnostics.model_validate(data)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "observation", ["valid", "missing", "wrong-count", "call-time", "child-time"]
)
async def test_parent_report_binds_sample_and_measured_intervals_without_changing_authority(
    tmp_path, monkeypatch, observation
):
    feed, policy = feed_context(tmp_path)
    source = dict(feed.source)
    timer = [100.0]
    fake_time = SimpleNamespace(monotonic=lambda: timer[0])
    monkeypatch.setattr(market_reads, "time", fake_time)
    monkeypatch.setattr(quote_feed, "time", fake_time)
    requests = []
    child = diagnostics()
    if observation == "missing":
        child = None
    elif observation == "wrong-count":
        child = diagnostics(get_accounts={"attempted": 2, "completed": 2, "elapsed_seconds": 0.5})
    elif observation == "call-time":
        child = diagnostics(collection_seconds=1.0)
    elif observation == "child-time":
        child = diagnostics(collection_seconds=20.0)

    async def read(req):
        requests.append(req)
        timer[0] = 108.125
        return result(req, diagnostics=child)

    original = feed.publish

    def publish(*args, **kwargs):
        value = original(*args, **kwargs)
        timer[0] = 110.625
        return value

    monkeypatch.setattr(market_reads, "_read", read)
    monkeypatch.setattr(feed, "publish", publish)
    report = await collect_once(feed, clock=lambda: NOW)
    evidence = report["evidence"]
    assert report["status"] == "PUBLISHED" and report["feed_sequence"] == 1
    assert evidence["request_id"] == requests[0].request_id
    assert evidence["feed_id"] == feed.feed_id and evidence[
        "source_hash"
    ] == market_reads.source_hash(policy)
    sequence, packet = feed.latest()
    assert (
        sequence == 1
        and evidence["packet_sha256"]
        == hashlib.sha256(packet.model_dump_json().encode()).hexdigest()
    )
    with sqlite3.connect(feed.path) as db:
        assert (
            db.execute("SELECT sample_id FROM quote_samples WHERE sequence=1").fetchone()[0]
            == evidence["request_id"]
        )
    assert evidence["read_and_reap_seconds"] == 8.125
    assert evidence["validation_and_publication_seconds"] == 2.5
    assert evidence["total_seconds"] == 10.625 and evidence["timeout_seconds"] == 30
    assert (
        evidence["started_at"]
        == evidence["collected_at"]
        == evidence["checked_at"]
        == NOW.isoformat()
    )
    assert evidence["oldest_quote_at"] == packet.candidates[0].quote.timestamp.isoformat()
    assert evidence["symbols"] == ["SPY"] and evidence["expected_tool_calls"] == dict.fromkeys(
        ("get_accounts", "get_equity_quotes", "get_equity_tradability", "get_equity_historicals"), 1
    )
    assert evidence["tool_observations_status"] == (
        "OBSERVED" if observation == "valid" else "UNVERIFIED"
    )
    assert evidence["provider_acceptance"] == "UNVERIFIED" and not evidence["execution_authority"]
    assert feed.source == source and not report["live_enabled"]
    assert "PRIVATE" not in json.dumps(report) and str(tmp_path) not in json.dumps(report)
    assert packet.account.equity == packet.account.cash == packet.account.buying_power == 0


@pytest.mark.parametrize(
    "field,bad",
    [
        ("attempted", True),
        ("attempted", "1"),
        ("completed", -1),
        ("completed", 25),
        ("elapsed_seconds", -1.0),
        ("elapsed_seconds", float("nan")),
        ("elapsed_seconds", float("inf")),
        ("elapsed_seconds", True),
    ],
)
def test_invalid_observations_cannot_masquerade_as_measurements(field, bad):
    data = {"attempted": 1, "completed": 1, "elapsed_seconds": 0.5}
    data[field] = bad
    with pytest.raises(ValidationError):
        MarketToolObservation.model_validate(data)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [False, True])
async def test_observer_counts_validated_completion_and_elapsed_time_only(monkeypatch, failure):
    timer = [100.0]
    monkeypatch.setattr(market_read_worker, "time", SimpleNamespace(monotonic=lambda: timer[0]))

    class Client:
        async def call_tool(self, name, arguments):
            timer[0] = 102.5
            output = await FakeGateway(NOW).call_safe(name, arguments)
            if failure:
                output["structuredContent"]["data"]["results"].append(None)
            return output

    gateway = market_read_worker.ObservedGateway(Client(), "fixture")
    if failure:
        with pytest.raises(ValueError):
            await gateway.call_safe("get_equity_quotes", {"symbols": ["SPY"]})
    else:
        await gateway.call_safe("get_equity_quotes", {"symbols": ["SPY"]})
    assert gateway.observations["get_equity_quotes"] == {
        "attempted": 1,
        "completed": 0 if failure else 1,
        "elapsed_seconds": 2.5,
    }
    assert all(
        v["attempted"] == 0 for k, v in gateway.observations.items() if k != "get_equity_quotes"
    )
    assert "PRIVATE" not in json.dumps(gateway.observations)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name",
    [
        "get_portfolio",
        "get_equity_positions",
        "get_equity_orders",
        "review_equity_order",
        "place_equity_order",
        "cancel_equity_order",
    ],
)
async def test_observer_preserves_market_only_firewall(name):
    class Client:
        async def call_tool(self, *args):
            pytest.fail("forbidden capability reached client")

    gateway = market_read_worker.ObservedGateway(Client(), "fixture")
    with pytest.raises(UnsafeRobinhoodToolError):
        await gateway.call_safe(name, {"private_account": "PRIVATE"})
    assert name not in gateway.observations and all(
        v["attempted"] == 0 for v in gateway.observations.values()
    )


@pytest.mark.anyio
async def test_cancelled_observation_retains_attempt_without_claiming_completion(monkeypatch):
    timer = [100.0]
    entered = asyncio.Event()
    monkeypatch.setattr(market_read_worker, "time", SimpleNamespace(monotonic=lambda: timer[0]))

    class Client:
        async def call_tool(self, *args):
            entered.set()
            await asyncio.Future()

    gateway = market_read_worker.ObservedGateway(Client(), "fixture")
    work = asyncio.create_task(gateway.call_safe("get_equity_quotes", {"symbols": ["SPY"]}))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        timer[0] = 100.25
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert gateway.observations["get_equity_quotes"] == {
            "attempted": 1,
            "completed": 0,
            "elapsed_seconds": 0.25,
        }
    finally:
        if not work.done():
            work.cancel()
            with pytest.raises(asyncio.CancelledError):
                await work
