"""Pinned SignalFlow daily MA rules, recomputed from immutable completed bars."""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.options.degen import _metric
from app.options.engine import exact
from app.options.swing_base import direction
from app.options.swing_ma_models import SwingMAEvidence

D = Decimal


def average_series(bars, period):
    closes = [b.close for b in bars]
    if period == 50:
        # Source substitutes the close until the first complete SMA window.
        return [sum(closes[n - 49 : n + 1]) / 50 if n >= 49 else c for n, c in enumerate(closes)]
    values, weight = [closes[0]], D(2) / (period + 1)
    for close in closes[1:]:
        values.append(close * weight + values[-1] * (1 - weight))
    return values


def confirmations(bars, call):
    previous, current = bars[-2:]
    body = abs(current.close - current.open)
    span = max(current.high - current.low, D(".000000001"))
    bullish = current.close > current.open
    directional = bullish if call else current.close < current.open
    tags = []
    if (
        directional
        and min(current.open, current.close) <= min(previous.open, previous.close)
        and max(current.open, current.close) >= max(previous.open, previous.close)
    ):
        tags.append("ENGULFING")
    wick = (
        min(current.open, current.close) - current.low
        if call
        else current.high - max(current.open, current.close)
    )
    location = (current.close - current.low) / span
    if wick >= max(body * 2, span * D(".45")) and (
        location >= D(".65") if call else location <= D(".35")
    ):
        tags.append("REJECTION")
    if directional and body / span >= D(".65"):
        tags.append("STRONG_CLOSE")
    return tuple(tags)


@exact
def evaluate_ma(seed):
    bars, hourly, period = seed.history.bars, seed.hourly_history, seed.ma_period
    if len(bars) < 56 or hourly is None or period not in (8, 21, 50):
        raise ValueError("Complete daily/hourly evidence and locked MA variant required")
    previous, current = bars[-2:]
    call = seed.instrument.contract.right == "CALL"
    expected, opposed = ("bullish", "bearish") if call else ("bearish", "bullish")
    values = average_series(bars, period)
    ma = values[-1]
    slope = (ma / values[-4] - 1) * 100
    fraction = D(".006") if period == 50 else D(".004")
    touches = [
        b.low <= v * (1 + fraction) and b.high >= v * (1 - fraction)
        for b, v in zip(bars, values, strict=True)
    ]
    hold = 0
    latest = max((n for n, hit in enumerate(touches) if hit), default=len(bars) - 1)
    for n in range(latest, len(bars)):
        held = bars[n].close >= values[n] if call else bars[n].close <= values[n]
        hold = hold + 1 if held else 0
    clusters, active = 0, False
    for hit in touches[-60:]:
        clusters += int(hit and not active)
        active = hit
    ranges = [
        max(
            b.high - b.low,
            abs(b.high - bars[max(0, n - 1)].close),
            abs(b.low - bars[max(0, n - 1)].close),
        )
        for n, b in enumerate(bars)
    ]
    atr = sum(ranges[-14:]) / 14
    if atr <= 0 or any(b.volume <= 0 for b in bars):
        raise ValueError("Observed positive ATR and volume required")
    volume = D(current.volume) * 5 / sum(b.volume for b in bars[-6:-1])
    tags = confirmations(bars, call)
    dd, hd = direction(bars), direction(hourly.bars)
    checks = (
        (dd == expected, "SWING_MA_DAILY_DIRECTION_REQUIRED"),
        (
            (previous.close >= values[-2] and slope >= D(".02"))
            if call
            else (previous.close <= values[-2] and slope <= D("-.02")),
            "SWING_MA_ESTABLISHED_TREND_REQUIRED",
        ),
        (touches[-1], "SWING_MA_TEST_REQUIRED"),
        (current.close >= ma if call else current.close <= ma, "SWING_MA_FAVORABLE_CLOSE_REQUIRED"),
        (hold >= 1, "SWING_MA_HOLD_REQUIRED"),
        (bool(tags), "SWING_MA_DIRECTIONAL_CONFIRMATION_REQUIRED"),
    )
    # The pinned source treats volume, repeat tests and hourly opposition as
    # diagnostics, not CONFIRMED-phase gates. No model score adds authority.
    warnings = tuple(
        reason
        for failed, reason in (
            (volume < 1, "SWING_MA_LOW_CONFIRMATION_VOLUME"),
            (clusters > 2, "SWING_MA_LATE_TEST"),
            (hd == opposed, "SWING_MA_HOURLY_OPPOSED"),
        )
        if failed
    )
    buffer = max(ma * fraction, atr * D(".15"))
    stop = min(current.low, ma - buffer) if call else max(current.high, ma + buffer)
    return SwingMAEvidence(
        period=period,
        reference=current.high if call else current.low,
        invalidation=_metric(stop, ROUND_CEILING if call else ROUND_FLOOR),
        moving_average=_metric(ma),
        slope_pct=_metric(slope),
        atr=_metric(atr),
        volume_ratio=_metric(volume),
        test_number=max(1, clusters),
        hold_bars=hold,
        confirmations=tags,
        daily_direction=dd,
        hourly_direction=hd,
        warnings=warnings,
        reasons=tuple(reason for passed, reason in checks if not passed),
    )
