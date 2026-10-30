"""Offline original-wire captures; this suite never starts a provider process."""

import asyncio
from datetime import timedelta

import pytest
from test_robinhood_read_mapping import AT, envelope, equity, instrument, option
from test_robinhood_read_mapping import (
    schemas as schemas,  # noqa: PLC0414 -- imported pytest fixture
)

from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy, planned
from app.mixed.stock_models import StockInstrument
from app.options.read_capture import CapturePolicy, CaptureResult, policy_digest
from app.options.runtime import read_packet


def policy():
    return FeedPolicy(
        population_id="offline-feed",
        stocks=tuple(
            StockInstrument(
                provider="robinhood",
                instrument_id="stock-" + s,
                symbol=s,
                kind="ETF",
                tick=".01",
                metadata_complete=False,
                tradable=False,
            )
            for s in ("SPY", "QQQ")
        ),
        capture=CapturePolicy(oauth_file="/unused/offline-fixture", timeout_seconds=5.0),
    )


def reader(at, seen, *, missing=(), source_shift=0):
    async def capture(p, *, schemas, plan):
        seen.append(plan)
        observations = []
        for c in plan.calls:
            values = (
                [{"quote": equity(s)} for s in c.arguments["symbols"] if s not in missing]
                if c.tool == "get_equity_quotes"
                else [{"quote": option()}]
            )
            if c.tool == "get_equity_quotes":
                for row in values:
                    for key in ("venue_bid_time", "venue_ask_time", "venue_last_trade_time"):
                        from datetime import datetime

                        row["quote"][key] = (
                            datetime.fromisoformat(row["quote"][key])
                            + timedelta(seconds=source_shift)
                        ).isoformat()
            observations.append(
                {"label": c.label, "tool": c.tool, "completed": True, "raw": envelope(values)}
            )
        return CaptureResult(
            request_id="a" * 32,
            policy_sha256=policy_digest(p),
            operation="CAPTURE",
            started_at=at,
            collected_at=at + timedelta(seconds=2),
            elapsed_seconds=2,
            status="COMPLETE",
            schemas=schemas,
            plan=plan,
            observations=observations,
        )

    return capture


def test_held_contracts_are_batched_once_and_missing_evidence_stays_missing(tmp_path, schemas):
    p = policy()
    held = (p.stocks[0], instrument())
    plan, catalog = planned(p, held, AT, None, cycle=False)
    assert len(plan.calls) == 2
    assert plan.calls[0].arguments["symbols"] == ["SPY", "QQQ"]
    assert catalog == (instrument(),)
    seen = []
    feed = ContinuousFeed(tmp_path / "feed", p, schemas, create=True)
    try:
        out = asyncio.run(feed.tick(now=AT, held=held, reader=reader(AT, seen)))
        assert out["status"] == "DELIVERED", out
        packet = read_packet(tmp_path / "feed/feed.json")
        assert packet.frame.held_quotes[0].instrument == instrument()
        assert not packet.frame.quotes
        assert all(
            x.quote.entitlement == "UNKNOWN" and x.quote.bid_size is None
            for x in packet.frame.stocks
        )
        assert packet.frame.held_quotes[0].source_at == AT
        assert (
            asyncio.run(feed.tick(now=AT + timedelta(seconds=3), reader=reader(AT, seen)))["status"]
            == "RATE_LIMITED"
        )
        assert len(seen) == 1
    finally:
        feed.close()


def test_missing_peer_does_not_stop_healthy_delivery_or_erase_clock(tmp_path, schemas):
    feed = ContinuousFeed(tmp_path / "feed", policy(), schemas, create=True)
    try:
        assert asyncio.run(feed.tick(now=AT, reader=reader(AT, [])))["status"] == "DELIVERED"
        at = AT + timedelta(seconds=10)
        assert (
            asyncio.run(feed.tick(now=at, reader=reader(at, [], missing=("SPY",))))["status"]
            == "DELIVERED"
        )
        packet = read_packet(tmp_path / "feed/feed.json")
        assert [s.quote.instrument.symbol for s in packet.frame.stocks] == ["QQQ"]
        assert "MISSING_QUOTE:SPY" in packet.coverage_issues
        before = (tmp_path / "feed/feed.json").read_bytes()
        at += timedelta(seconds=10)
        assert (
            asyncio.run(feed.tick(now=at, reader=reader(at, [], source_shift=-10)))["status"]
            == "FAILED"
        )
        assert (tmp_path / "feed/feed.json").read_bytes() == before
    finally:
        feed.close()


def test_unreviewed_held_mapping_is_explicit_while_supported_peers_continue(tmp_path, schemas):
    p = policy()
    held = instrument().model_copy(
        update={
            "contract": instrument().contract.model_copy(
                update={"underlying": "SPX", "root": "SPX"}
            )
        }
    )
    feed = ContinuousFeed(tmp_path / "feed", p, schemas, create=True)
    try:
        assert (
            asyncio.run(feed.tick(now=AT, held=(held,), reader=reader(AT, [])))["status"]
            == "DELIVERED"
        )
        packet = read_packet(tmp_path / "feed/feed.json")
        assert len(packet.frame.stocks) == 2 and not packet.frame.held_quotes
        assert any("UNREVIEWED_HELD_MAPPING" in x for x in packet.coverage_issues)
    finally:
        feed.close()


def test_restart_preserves_source_clocks_sequence_and_failed_reads(tmp_path, schemas):
    p, seen = policy(), []
    directory = tmp_path / "feed"
    feed = ContinuousFeed(directory, p, schemas, create=True)
    assert asyncio.run(feed.tick(now=AT, reader=reader(AT, seen)))["status"] == "DELIVERED"
    before = (directory / "feed.json").read_bytes()
    with pytest.raises(BlockingIOError):
        ContinuousFeed(directory, p, schemas)
    feed.close()
    feed = ContinuousFeed(directory, p, schemas)
    try:
        assert (directory / "feed.json").read_bytes() == before

        async def failed(*a, **kw):
            raise OSError("offline interrupted transport")

        assert (
            asyncio.run(feed.tick(now=AT + timedelta(seconds=10), reader=failed))["status"]
            == "FAILED"
        )
        assert (directory / "feed.json").read_bytes() == before
        at = AT + timedelta(seconds=20)
        assert asyncio.run(feed.tick(now=at, reader=reader(at, seen)))["sequence"] == 3
        packet = read_packet(directory / "feed.json")
        assert packet.frame.stocks[0].quote.source_at == AT
        assert packet.recorded_at == at + timedelta(seconds=2)
    finally:
        feed.close()


def test_collector_budget_survives_restart_and_conflicting_identity_rejected(tmp_path, schemas):
    p = policy().model_copy(update={"calls_per_minute": 1})
    feed = ContinuousFeed(tmp_path / "feed", p, schemas, create=True)
    try:
        assert (
            asyncio.run(feed.tick(now=AT, held=(instrument(),), reader=reader(AT, [])))["status"]
            == "RATE_LIMITED"
        )
        assert feed.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
        altered = p.stocks[0].model_copy(update={"instrument_id": "wrong"})
        with pytest.raises(ValueError, match="Held stock"):
            planned(p, (altered,), AT, None, cycle=False)
    finally:
        feed.close()


def test_eight_candidates_and_two_held_options_have_complete_bounded_delivery(tmp_path, schemas):
    from uuid import NAMESPACE_URL, uuid5
    from app.options.models import OptionInstrument
    catalog = []
    for n in range(10):
        value = instrument().model_dump()
        value['instrument_id'] = str(uuid5(NAMESPACE_URL, f'bounded-option-{n}'))
        value['contract']['strike'] += n
        value['contract'].update(expiration=AT.date(), last_trading_at=AT+timedelta(hours=6),
                                 expires_at=AT+timedelta(hours=7), settles_at=AT+timedelta(days=1))
        catalog.append(OptionInstrument.model_validate(value))
    p = FeedPolicy.model_validate(policy().model_dump() | {'candidates': catalog[:8]})
    seen = []

    async def capture(config, *, schemas, plan):
        seen.append(plan)
        rows = []
        for call in plan.calls:
            if call.tool == 'get_equity_quotes':
                values = [{'quote': equity(s)} for s in call.arguments['symbols']]
            else:
                values = [{'quote': option() | {'instrument_id': identity}}
                          for identity in call.arguments['instrument_ids']]
            rows.append({'label': call.label, 'tool': call.tool, 'completed': True, 'raw': envelope(values)})
        return CaptureResult(request_id='c'*32, operation='CAPTURE', policy_sha256=policy_digest(config),
            started_at=AT, collected_at=AT+timedelta(seconds=1), elapsed_seconds=1,
            status='COMPLETE', schemas=schemas, plan=plan, observations=rows)

    feed = ContinuousFeed(tmp_path / 'feed', p, schemas, create=True)
    try:
        result = asyncio.run(feed.tick(now=AT, held=tuple(catalog[8:]), reader=capture))
        assert result['status'] == 'DELIVERED', result
        calls = [c for c in seen[0].calls if c.tool == 'get_option_quotes']
        assert [len(c.arguments['instrument_ids']) for c in calls] == [8, 2]
        assert len(seen[0].instrument_ids) == 10
        packet = read_packet(tmp_path / 'feed/feed.json')
        assert len(packet.frame.quotes) == 8 and len(packet.frame.held_quotes) == 2
        assert {q.instrument.instrument_id for q in (*packet.frame.quotes, *packet.frame.held_quotes)} == {i.instrument_id for i in catalog}
    finally:
        feed.close()
