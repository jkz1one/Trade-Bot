"""Executable price components must not borrow a newer component's freshness."""

from datetime import datetime, timedelta, timezone

import pytest
from test_robinhood_market import FakeGateway

from app.domain.models import AccountState, MarketPacket, Position, TradeDecision
from app.risk.governor import govern
from app.robinhood.market import RobinhoodMarketData

NOW = datetime(2026, 10, 7, 15, tzinfo=timezone.utc)
COMPONENTS = ("venue_bid_time", "venue_ask_time", "venue_last_trade_time")


class QuoteGateway(FakeGateway):
    def __init__(self, changes):
        super().__init__(NOW)
        self.changes = changes

    async def call_safe(self, name, arguments):
        result = await super().call_safe(name, arguments)
        if name == "get_equity_quotes":
            result["structuredContent"]["data"]["results"][0]["quote"].update(self.changes)
        return result


async def collect(changes, *, clock=lambda: NOW, now=NOW):
    gateway = QuoteGateway(changes)
    candidates = await RobinhoodMarketData(gateway, clock=clock).candidates("RH1", ["SPY"], now)
    assert {name for name, _ in gateway.calls} == {
        "get_equity_quotes",
        "get_equity_tradability",
        "get_equity_historicals",
    }
    return candidates


@pytest.mark.anyio
@pytest.mark.parametrize("component", COMPONENTS)
@pytest.mark.parametrize("action", ("OPEN_LONG", "CLOSE"))
async def test_stale_component_is_retained_and_governor_rejects(component, action, settings):
    stale = NOW - timedelta(seconds=settings.quote_max_age_seconds + 1)
    candidates = await collect({component: stale.isoformat()})
    assert candidates[0].quote.timestamp == stale
    position = (
        Position(
            symbol="SPY",
            quantity="0.01",
            entry_price="100",
            current_price="100",
            original_invalidation="99",
            thesis="test",
            opened_at=NOW,
        )
        if action == "CLOSE"
        else None
    )
    packet = MarketPacket(
        as_of=NOW,
        candidates=candidates,
        account=AccountState(
            equity="10", cash="10", buying_power="10", high_watermark="10", position=position
        ),
    )
    decision = TradeDecision(
        action=action,
        symbol="SPY",
        confidence=0.9,
        setup_quality=0.9,
        desired_exposure_fraction=0.9,
        invalidation_price="99",
        thesis="test",
        invalidation_reason="test",
        why_now="test",
    )
    result = govern(decision, packet, settings, now=NOW)
    assert not result.approved
    assert "STALE_QUOTE" in result.rejection_reasons
    assert result.approved_notional == 0


@pytest.mark.anyio
@pytest.mark.parametrize("component", COMPONENTS)
@pytest.mark.parametrize("bad", (None, "", "not-a-time", "2026-10-07T15:00:00"))
async def test_missing_malformed_or_naive_component_fails_closed(component, bad):
    with pytest.raises(ValueError):
        await collect({component: bad})


@pytest.mark.anyio
@pytest.mark.parametrize("component", COMPONENTS)
async def test_future_component_cannot_hide_behind_older_component(component):
    with pytest.raises(ValueError, match="future"):
        await collect({component: (NOW + timedelta(microseconds=1)).isoformat()})


@pytest.mark.anyio
async def test_selected_newer_trade_has_matching_clock_and_price():
    candidates = await collect(
        {
            "venue_last_trade_time": (NOW - timedelta(days=1)).isoformat(),
            "venue_last_non_reg_trade_time": NOW.isoformat(),
            "last_non_reg_trade_price": "101",
        }
    )
    assert candidates[0].quote.timestamp == NOW
    assert candidates[0].quote.last == 101


@pytest.mark.anyio
async def test_unpriced_unused_trade_clock_cannot_refresh_stale_selected_trade():
    old = NOW - timedelta(minutes=5)
    candidates = await collect(
        {
            "venue_last_trade_time": old.isoformat(),
            "venue_last_non_reg_trade_time": NOW.isoformat(),
            "last_non_reg_trade_price": None,
        }
    )
    assert candidates[0].quote.timestamp == old
    assert candidates[0].quote.last == 100


@pytest.mark.anyio
async def test_component_timezone_offsets_compare_as_instants():
    candidates = await collect(
        {
            "venue_bid_time": "2026-10-07T10:59:59-04:00",
            "venue_ask_time": "2026-10-07T15:00:00Z",
        }
    )
    assert candidates[0].quote.timestamp == NOW - timedelta(seconds=1)


@pytest.mark.anyio
async def test_quotes_received_after_request_start_use_completion_clock():
    completed = NOW + timedelta(seconds=2)
    candidates = await collect(
        {k: completed.isoformat() for k in COMPONENTS}, clock=lambda: completed
    )
    assert candidates[0].quote.timestamp == completed


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ("request", "completion", "regression"))
async def test_collection_clock_must_be_aware_and_nonregressing(phase):
    naive = NOW.replace(tzinfo=None)
    clock = (
        (lambda: naive)
        if phase == "completion"
        else ((lambda: NOW - timedelta(seconds=1)) if phase == "regression" else (lambda: NOW))
    )
    with pytest.raises(ValueError, match="clock"):
        await collect({}, now=naive if phase == "request" else NOW, clock=clock)
