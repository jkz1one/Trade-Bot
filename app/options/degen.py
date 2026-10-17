"""Versioned completed-bar Degen evidence. No model, broker or sizing authority."""

from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from typing import Literal

from pydantic import Field, model_validator

from app.options.governor import _fresh
from app.options.models import Count, Evidence, Money, Name, OptionRecord, PositiveCount, Symbol

Family = Literal["ORB_CONTINUATION", "VWAP_PULLBACK", "FAILED_BREAK_REVERSAL"]
FAMILIES = ("ORB_CONTINUATION", "VWAP_PULLBACK", "FAILED_BREAK_REVERSAL")
ZERO = Decimal(0)


class DegenPolicy(OptionRecord):
    version: Literal["degen-completed-bars-v1"] = "degen-completed-bars-v1"
    symbols: tuple[Literal["SPY", "QQQ"], ...] = Field(min_length=1, max_length=2)
    history_source: Name
    max_bar_age_seconds: PositiveCount = Field(le=600)
    max_receive_lag_seconds: Count = Field(le=30)
    volume_lookback: PositiveCount = Field(ge=3, le=20)
    minimum_volume_ratio: Money = Field(gt=0, le=10)
    opening_range_minutes: Literal[15] = 15
    stop_buffer_fraction: Money = Field(gt=0, le=Decimal(".01"))
    maximum_extension_fraction: Money = Field(gt=0, le=Decimal(".1"))
    vwap_separation_fraction: Money = Field(gt=0, le=Decimal(".1"))
    vwap_touch_fraction: Money = Field(gt=0, le=Decimal(".01"))
    setup_priority: tuple[Family, ...] = FAMILIES

    @model_validator(mode="after")
    def distinct(self):
        if (
            len(set(self.symbols)) != len(self.symbols)
            or set(self.setup_priority) != set(FAMILIES)
            or len(self.setup_priority) != 3
        ):
            raise ValueError("Unique frozen symbols and a complete setup priority required")
        return self


class DegenBar(OptionRecord):
    begins_at: datetime
    open: Money = Field(gt=0)
    high: Money = Field(gt=0)
    low: Money = Field(gt=0)
    close: Money = Field(gt=0)
    volume: int = Field(ge=0, le=1_000_000_000_000, strict=True)
    interpolated: bool = Field(strict=True)

    @model_validator(mode="after")
    def ohlc(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Consistent OHLC range required")
        return self

    @property
    def ends_at(self):
        return self.begins_at + timedelta(minutes=5)


class DegenHistory(Evidence):
    symbol: Symbol
    interval_seconds: Literal[300] = 300
    bounds: Literal["regular"] = "regular"
    adjustment: Literal["split"] = "split"
    bars: tuple[DegenBar, ...] = Field(max_length=96)


class SetupObservation(OptionRecord):
    family: Family
    right: Literal["CALL", "PUT"]
    status: Literal["BLOCKED", "WATCHING", "CONFIRMED"]
    reasons: tuple[Name, ...]
    invalidation: Money | None = Field(default=None, gt=0)
    reference: Money | None = Field(default=None, gt=0)


class DegenScan(OptionRecord):
    version: Literal["degen-completed-bars-v1"] = "degen-completed-bars-v1"
    symbol: Symbol
    evaluated_at: datetime
    completed_through: datetime | None = None
    higher_timeframe_through: datetime | None = None
    last_close: Money | None = None
    opening_high: Money | None = None
    opening_low: Money | None = None
    vwap: Money | None = None
    volume_ratio: Money | None = None
    observations: tuple[SetupObservation, ...]
    issues: tuple[Name, ...] = ()


def _ema(values, period):
    alpha = Decimal(2) / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def _metric(value, rounding=ROUND_FLOOR):
    return (
        value.quantize(Decimal(".000000000001"), rounding=rounding) if value is not None else None
    )


def scan_degen(history, policy, window, *, now):
    """Window comes from the owner's actual calendar. Never guess a weekday/open."""
    history = DegenHistory.model_validate(history.model_dump(warnings=False))
    policy = DegenPolicy.model_validate(policy.model_dump(warnings=False))
    with localcontext(Context(prec=192)):
        return _scan(history, policy, window, now)


def _scan(h, p, w, now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware Degen evaluation clock required")
    issues = []
    if w is None or not w.opens_at <= now < w.closes_at:
        issues.append("MARKET_CLOSED")
    if h.symbol not in p.symbols or h.source != p.history_source:
        issues.append("HISTORY_BINDING_MISMATCH")
    if (
        not h.complete
        or h.entitlement != "REALTIME"
        or not _fresh(
            h.source_at, h.received_at, now, p.max_bar_age_seconds, p.max_receive_lag_seconds
        )
    ):
        issues.append("HISTORY_UNAVAILABLE_DELAYED_OR_STALE")
    bars = list(h.bars)
    if w is not None and any(
        b.begins_at < w.opens_at or b.ends_at > w.closes_at or b.begins_at > now or b.interpolated
        for b in bars
    ):
        issues.append("HISTORY_FOREIGN_FUTURE_OR_INTERPOLATED")
    if w is not None and (
        not bars
        or bars[0].begins_at != w.opens_at
        or any(b.begins_at != w.opens_at + timedelta(minutes=5 * n) for n, b in enumerate(bars))
    ):
        issues.append("HISTORY_DUPLICATE_GAP_OR_UNORDERED")
    complete = [b for b in bars if b.ends_at <= min(now, h.source_at, h.received_at)]
    if len(complete) < max(6, p.volume_lookback + 1):
        issues.append("COMPLETED_STRUCTURE_INSUFFICIENT")
    if complete and not timedelta(0) <= now - complete[-1].ends_at < timedelta(
        seconds=p.max_bar_age_seconds
    ):
        issues.append("COMPLETED_BARS_STALE")
    if issues:
        return DegenScan(
            symbol=h.symbol,
            evaluated_at=now,
            observations=tuple(
                SetupObservation(family=f, right=r, status="BLOCKED", reasons=tuple(issues))
                for f in p.setup_priority
                for r in ("CALL", "PUT")
            ),
            issues=tuple(issues),
        )
    latest, previous = complete[-1], complete[-2]
    high = max(b.high for b in complete[:3])
    low = min(b.low for b in complete[:3])
    weighted = volume = ZERO
    vwaps = []
    for bar in complete:
        volume += bar.volume
        weighted += (bar.high + bar.low + bar.close) * bar.volume / 3
        vwaps.append(weighted / volume if volume > 0 else None)
    vwap = vwaps[-1]
    prior_volume = sum(b.volume for b in complete[-p.volume_lookback - 1 : -1]) / Decimal(
        p.volume_lookback
    )
    ratio = Decimal(latest.volume) / prior_volume if prior_volume > 0 else None
    # Three complete five-minute bars make one fifteen-minute close. Forming
    # five/ fifteen-minute bars cannot vote, even if their extreme prices look good.
    fifteen = [complete[i + 2] for i in range(0, len(complete) - 2, 3)]
    bullish = fifteen[-1].close > fifteen[-2].close
    bearish = fifteen[-1].close < fifteen[-2].close
    observations = []
    for family in p.setup_priority:
        for right in ("CALL", "PUT"):
            sign = 1 if right == "CALL" else -1
            boundary = high if sign == 1 else low
            directional = lambda a, b, sign=sign: a > b if sign == 1 else a < b
            stop = boundary - sign * boundary * p.stop_buffer_fraction
            reference = boundary
            gates = {
                "VOLUME_CONFIRMATION_REQUIRED": ratio is not None
                and ratio >= p.minimum_volume_ratio,
                "FIFTEEN_MINUTE_CONFIRMATION_REQUIRED": bullish if sign == 1 else bearish,
                "VWAP_CONFIRMATION_REQUIRED": vwap is not None and directional(latest.close, vwap),
            }
            if family == "ORB_CONTINUATION":
                gates.update(
                    {
                        "OPENING_BREAK_AND_HOLD_REQUIRED": directional(previous.close, boundary)
                        and directional(latest.close, boundary),
                        "BREAKOUT_TOO_EXTENDED": abs(latest.close / boundary - 1)
                        <= p.maximum_extension_fraction,
                    }
                )
            elif family == "FAILED_BREAK_REVERSAL":
                failed_level = low if sign == 1 else high
                failed = previous.close < low if sign == 1 else previous.close > high
                reference = failed_level
                stop = (
                    previous.low - previous.low * p.stop_buffer_fraction
                    if sign == 1
                    else previous.high + previous.high * p.stop_buffer_fraction
                )
                gates.update(
                    {
                        "OBSERVED_FAILED_BREAK_REQUIRED": failed,
                        "REVERSAL_CONTINUATION_REQUIRED": directional(latest.close, failed_level)
                        and directional(latest.close, previous.high if sign == 1 else previous.low),
                        "REVERSAL_TOO_EXTENDED": abs(latest.close / failed_level - 1)
                        <= p.maximum_extension_fraction,
                    }
                )
            else:
                reference = vwap
                stop = (
                    min(latest.low, vwap * (1 - p.stop_buffer_fraction))
                    if sign == 1 and vwap
                    else max(latest.high, vwap * (1 + p.stop_buffer_fraction))
                    if vwap
                    else None
                )
                gates["VWAP_TREND_STRUCTURE_INSUFFICIENT"] = len(complete) >= 25
                fast, slow = (
                    _ema([b.close for b in complete], 8),
                    _ema([b.close for b in complete], 21),
                )
                gates["EMA_TREND_ALIGNMENT_REQUIRED"] = (
                    directional(fast[-1], slow[-1])
                    and directional(fast[-1], fast[-4])
                    and (slow[-1] >= slow[-4] if sign == 1 else slow[-1] <= slow[-4])
                )
                gates["PRIOR_VWAP_SEPARATION_REQUIRED"] = any(
                    v is not None
                    and directional(b.close, v * (1 + sign * p.vwap_separation_fraction))
                    for b, v in zip(complete[-7:-1], vwaps[-7:-1], strict=True)
                )
                gates["VWAP_RETEST_REQUIRED"] = (
                    vwap is not None
                    and latest.low <= vwap * (1 + p.vwap_touch_fraction)
                    and latest.high >= vwap * (1 - p.vwap_touch_fraction)
                )
                gates["DIRECTIONAL_CANDLE_CONFIRMATION_REQUIRED"] = directional(
                    latest.close, latest.open
                ) and directional(latest.close, previous.close)
                gates["VWAP_TOO_EXTENDED"] = (
                    vwap is not None
                    and abs(latest.close / vwap - 1) <= p.maximum_extension_fraction
                )
            reasons = tuple(key for key, value in gates.items() if not value)
            observations.append(
                SetupObservation(
                    family=family,
                    right=right,
                    status="WATCHING" if reasons else "CONFIRMED",
                    reasons=reasons,
                    invalidation=_metric(stop, ROUND_CEILING if sign == 1 else ROUND_FLOOR),
                    reference=_metric(reference),
                )
            )
    return DegenScan(
        symbol=h.symbol,
        evaluated_at=now,
        completed_through=latest.ends_at,
        higher_timeframe_through=fifteen[-1].ends_at,
        last_close=latest.close,
        opening_high=high,
        opening_low=low,
        vwap=_metric(vwap),
        volume_ratio=_metric(ratio),
        observations=tuple(observations),
    )
