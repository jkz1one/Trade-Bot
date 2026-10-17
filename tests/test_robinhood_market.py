from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.robinhood.market import RobinhoodMarketData


class FakeGateway:
    def __init__(self, now):
        self.now = now
        self.calls = []

    async def call_safe(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_equity_quotes":
            quote = {
                "symbol": "SPY",
                "last_trade_price": "100.00",
                "venue_last_trade_time": self.now.isoformat(),
                "last_non_reg_trade_price": None,
                "venue_last_non_reg_trade_time": None,
                "adjusted_previous_close": "99.00",
                "previous_close": "99.00",
                "previous_close_date": "2026-10-02",
                "bid_price": "99.99",
                "venue_bid_time": self.now.isoformat(),
                "ask_price": "100.01",
                "venue_ask_time": self.now.isoformat(),
                "has_traded": True,
                "state": "active",
            }
            data = {"results": [{
                "quote": quote,
                "close": {
                    "symbol": "SPY",
                    "date": "2026-10-02",
                    "price": "99.00",
                    "interpolated": False,
                    "source": "sip-close",
                },
            }]}
        elif name == "get_equity_tradability":
            data = {"results": [{
                "symbol": "SPY",
                "tradeable": True,
                "state": "active",
                "fractional_tradability": "tradable",
                "extended_hours_fractional_tradability": False,
            }]}
        elif name == "get_equity_historicals":
            bars = []
            for i in range(30):
                px = Decimal("98") + Decimal(i) / Decimal("20")
                ts = self.now - timedelta(minutes=5 * (29 - i))
                bars.append({
                    "begins_at": ts.isoformat(),
                    "open_price": str(px),
                    "close_price": str(px + Decimal("0.05")),
                    "high_price": str(px + Decimal("0.10")),
                    "low_price": str(px - Decimal("0.10")),
                    "volume": 1000 + i,
                    "interpolated": False,
                    "session": "reg",
                })
            data = {"results": [{
                "symbol": "SPY",
                "interval": "5minute",
                "bounds": "regular",
                "bars": bars,
            }]}
        else:
            raise AssertionError(name)
        return {"structuredContent": {"data": data}}


@pytest.mark.anyio
async def test_live_market_shapes_become_candidate():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    gateway = FakeGateway(now)
    market = RobinhoodMarketData(gateway)
    candidates = await market.candidates("RH1", ["SPY"], now=now)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.quote.symbol == "SPY"
    assert candidate.quote.fractional_tradable
    assert candidate.atr_fraction > 0
    assert candidate.realized_vol_fraction > 0
    assert candidate.day_change_fraction > 0


@pytest.mark.anyio
async def test_historical_requests_are_single_symbol_to_stay_under_sse_limit():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    gateway = FakeGateway(now)
    market = RobinhoodMarketData(gateway)
    await market._bars(["SPY", "QQQ", "AAPL"], now)
    historical_calls = [
        args
        for name, args in gateway.calls
        if name == "get_equity_historicals"
    ]
    assert len(historical_calls) == 3
    assert all(len(call["symbols"]) == 1 for call in historical_calls)
