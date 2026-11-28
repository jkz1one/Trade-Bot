from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.models import Candidate, Quote
from app.robinhood.gateway import RobinhoodSafeGateway
from app.robinhood.read import tool_data

ET = ZoneInfo("America/New_York")

# Robinhood MCP responses are delivered as SSE events with a 1 MiB client limit. A week of
# 5-minute OHLCV for several symbols can exceed that limit even though the tool accepts 10 symbols.
# Keep historical requests per-symbol; quote/tradability batching remains unchanged.
HISTORICAL_SYMBOLS_PER_CALL = 1


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("market timestamp must include a timezone")
    return stamp


def _latest_price_and_time(q: dict[str, Any]) -> tuple[Decimal, datetime]:
    choices: list[tuple[datetime, Decimal]] = []
    for price_key, time_key in (
        ("last_trade_price", "venue_last_trade_time"),
        ("last_non_reg_trade_price", "venue_last_non_reg_trade_time"),
    ):
        ts = _dt(q.get(time_key))
        price = q.get(price_key)
        if ts is not None and price not in (None, ""):
            choices.append((ts, _d(price)))
    if not choices:
        raise ValueError("quote has no timestamped trade price")
    ts, price = max(choices, key=lambda item: item[0])
    return price, ts


def _quote_timestamp(q: dict[str, Any], selected_trade_time: datetime, now: datetime) -> datetime:
    # Quote carries one freshness clock. It must conservatively represent every
    # price used by sizing, execution and indicators, not just the newest update.
    stamps = [
        _dt(q.get("venue_bid_time")),
        _dt(q.get("venue_ask_time")),
        selected_trade_time,
    ]
    if any(stamp is None for stamp in stamps):
        raise ValueError("quote requires timestamped bid, ask and selected trade")
    if any(stamp > now for stamp in stamps):
        raise ValueError("quote component timestamp is in the future")
    return min(stamps)


def _clean_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [b for b in bars if b and not b.get("interpolated") and int(b.get("volume") or 0) >= 0]


def _atr_fraction(bars: list[dict[str, Any]], current: Decimal, period: int = 14) -> Decimal | None:
    bars = _clean_bars(bars)
    if len(bars) < period + 1 or current <= 0:
        return None
    trs: list[Decimal] = []
    for prev, cur in zip(bars[-(period + 1) : -1], bars[-period:]):
        high, low = _d(cur["high_price"]), _d(cur["low_price"])
        prev_close = _d(prev["close_price"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = sum(trs, Decimal("0")) / Decimal(len(trs))
    value = atr / current
    return value if value > 0 else None


def _realized_vol_fraction(bars: list[dict[str, Any]], period: int = 20) -> Decimal | None:
    bars = _clean_bars(bars)
    closes = [float(_d(b["close_price"])) for b in bars[-(period + 1) :]]
    if len(closes) < 3 or any(c <= 0 for c in closes):
        return None
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    if len(returns) < 2:
        return None
    value = Decimal(str(statistics.pstdev(returns)))
    return value if value > 0 else None


def _above_vwap(bars: list[dict[str, Any]], current: Decimal) -> bool | None:
    clean = _clean_bars(bars)
    if not clean:
        return None
    latest = _dt(clean[-1].get("begins_at"))
    if latest is None:
        return None
    session_date = latest.astimezone(ET).date()
    session = [
        b
        for b in clean
        if (_dt(b.get("begins_at")) and _dt(b["begins_at"]).astimezone(ET).date() == session_date)
    ]
    weighted = Decimal("0")
    volume = Decimal("0")
    for b in session:
        v = Decimal(int(b.get("volume") or 0))
        if v <= 0:
            continue
        typical = (_d(b["high_price"]) + _d(b["low_price"]) + _d(b["close_price"])) / Decimal("3")
        weighted += typical * v
        volume += v
    if volume <= 0:
        return None
    return current >= weighted / volume


class RobinhoodMarketData:
    def __init__(
        self,
        gateway: RobinhoodSafeGateway,
        *,
        interval: str = "5minute",
        lookback_days: int = 7,
        clock: Callable[[], datetime] | None = None,
    ):
        self.gateway = gateway
        self.interval = interval
        self.lookback_days = lookback_days
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def _quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        data = tool_data(await self.gateway.call_safe("get_equity_quotes", {"symbols": symbols}))
        return {
            item["quote"]["symbol"]: item
            for item in (data.get("results") or [])
            if item and item.get("quote")
        }

    async def _tradability(
        self, account_number: str, symbols: list[str]
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(symbols), 10):
            batch = symbols[i : i + 10]
            data = tool_data(
                await self.gateway.call_safe(
                    "get_equity_tradability",
                    {"account_number": account_number, "symbols": batch},
                )
            )
            out.update({x["symbol"]: x for x in (data.get("results") or []) if x})
        return out

    async def _bars(self, symbols: list[str], now: datetime) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        start = (
            (now - timedelta(days=self.lookback_days))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        end = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for i in range(0, len(symbols), HISTORICAL_SYMBOLS_PER_CALL):
            batch = symbols[i : i + HISTORICAL_SYMBOLS_PER_CALL]
            data = tool_data(
                await self.gateway.call_safe(
                    "get_equity_historicals",
                    {
                        "symbols": batch,
                        "start_time": start,
                        "end_time": end,
                        "interval": self.interval,
                        "bounds": "regular",
                        "adjustment_type": "split",
                    },
                )
            )
            for item in data.get("results") or []:
                if item:
                    out[item["symbol"]] = item.get("bars") or []
        return out

    async def technical_indicator(
        self,
        symbol: str,
        indicator: str,
        *,
        start_time: datetime,
        end_time: datetime | None = None,
        period: int | None = None,
        output: str = "latest",
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "symbol": symbol.upper(),
            "type": indicator,
            "interval": self.interval,
            "start_time": (start_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")),
            "bounds": "regular",
            "adjustment_type": "split",
            "output": output,
        }
        if end_time is not None:
            args["end_time"] = end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if period is not None:
            args["period"] = period
        return tool_data(await self.gateway.call_safe("get_equity_technical_indicators", args))

    async def candidates(
        self,
        account_number: str,
        symbols: list[str],
        now: datetime | None = None,
    ) -> list[Candidate]:
        now = now or self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("market collection clock must include a timezone")
        symbols = [s.upper() for s in symbols][:20]
        quotes = await self._quotes(symbols)
        tradability = await self._tradability(account_number, symbols)
        bars = await self._bars(symbols, now)
        collected_at = self.clock()
        if collected_at.tzinfo is None or collected_at.utcoffset() is None:
            raise ValueError("market collection clock must include a timezone")
        if collected_at < now:
            raise ValueError("market collection clock regressed")
        candidates: list[Candidate] = []
        for symbol in symbols:
            pair = quotes.get(symbol)
            t = tradability.get(symbol)
            if not pair or not t:
                continue
            q = pair["quote"]
            if not q.get("has_traded") or q.get("state") != "active":
                continue
            bid = _d(q.get("bid_price") or "0")
            ask = _d(q.get("ask_price") or "0")
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            last, trade_time = _latest_price_and_time(q)
            quote_time = _quote_timestamp(q, trade_time, collected_at)
            atr = _atr_fraction(bars.get(symbol, []), last)
            rv = _realized_vol_fraction(bars.get(symbol, []))
            if atr is None or rv is None:
                continue
            previous = _d(q.get("adjusted_previous_close") or q.get("previous_close") or "0")
            day_change = last / previous - Decimal("1") if previous > 0 else Decimal("0")
            fractional = (
                t.get("tradeable") is True
                and t.get("state", "active") == "active"
                and t.get("fractional_tradability") == "tradable"
            )
            candidates.append(
                Candidate(
                    quote=Quote(
                        symbol=symbol,
                        timestamp=quote_time,
                        bid=bid,
                        ask=ask,
                        last=last,
                        fractional_tradable=fractional,
                    ),
                    atr_fraction=atr,
                    realized_vol_fraction=rv,
                    day_change_fraction=day_change,
                    above_vwap=_above_vwap(bars.get(symbol, []), last),
                    relative_volume=None,
                )
            )
        return candidates

    @staticmethod
    def regime(candidates: list[Candidate]) -> str:
        by_symbol = {c.quote.symbol: c for c in candidates}
        broad = [by_symbol.get("SPY"), by_symbol.get("QQQ")]
        if all(c is not None and c.day_change_fraction > 0 and c.above_vwap is True for c in broad):
            return "bullish"
        if all(
            c is not None and c.day_change_fraction < 0 and c.above_vwap is False for c in broad
        ):
            return "bearish"
        return "mixed"
