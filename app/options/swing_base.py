"""Pinned daily-base rules on supplied completed evidence; no provider or order authority."""

from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.options.degen import _metric
from app.options.engine import exact
from app.options.swing_base_models import SwingBaseEvidence

D = Decimal


def input_issues(seed, policy, calendar):
    daily, hourly = seed.history, seed.hourly_history
    if policy.higher_levels is not None:
        if seed.level_key not in policy.higher_levels.keys:
            return ("SWING_LEVEL_KEY_ENROLLMENT_REQUIRED",)
        if (
            getattr(daily, "version", None) != "swing-level-daily-v1"
            or hourly is not None
            or seed.ma_period is not None
        ):
            return ("SWING_LEVEL_ORIGINAL_DAILY_REQUIRED",)
        from app.options.swing_levels import original_level

        try:
            original_level(seed, calendar)
        except (ValueError, ArithmeticError):
            return ("SWING_LEVEL_COMPLETE_SOURCE_PERIOD_REQUIRED",)
        return ()
    if seed.level_key is not None or getattr(daily, "version", None) == "swing-level-daily-v1":
        return ("SWING_LEVEL_ENROLLMENT_REQUIRED",)
    family = policy.ma_pullback or policy.daily_base
    if policy.ma_pullback is not None:
        if seed.ma_period not in policy.ma_pullback.periods:
            return ("SWING_MA_VARIANT_ENROLLMENT_REQUIRED",)
    elif seed.ma_period is not None or getattr(daily, "version", None) == "swing-ma-daily-v1":
        return ("SWING_MA_ENROLLMENT_REQUIRED",)
    enrolled = family is not None
    if not enrolled:
        return (
            ("SWING_BASE_ENROLLMENT_REQUIRED",)
            if (hourly is not None or getattr(daily, "version", None) is not None)
            else ()
        )
    version = "swing-ma-daily-v1" if policy.ma_pullback is not None else "swing-base-daily-v1"
    if getattr(daily, "version", None) != version or hourly is None:
        return ("SWING_BASE_COMPLETED_DAILY_AND_HOURLY_REQUIRED",)
    if (
        hourly.symbol != daily.symbol
        or hourly.source != family.hourly_source
        or not hourly.complete
        or hourly.entitlement != "REALTIME"
        or len(hourly.bars) != family.hourly_lookback
        or not daily.bars[-1].closes_at <= hourly.source_at <= hourly.received_at <= seed.created_at
    ):
        return ("SWING_BASE_HOURLY_BINDING_OR_COVERAGE",)
    cal = calendar.calendar
    if not cal.is_session(seed.target_session.isoformat()):
        return ("SWING_TARGET_NOT_EXCHANGE_SESSION",)
    session = cal.previous_session(seed.target_session.isoformat())
    end = cal.session_close(session).to_pydatetime()
    for bar in reversed(hourly.bars):
        opened = cal.session_open(session).to_pydatetime()
        # Exchange-open anchored hours include the actual final short interval.
        hours = int((end - opened).total_seconds() - 1) // 3600
        begins = opened + timedelta(hours=hours)
        if (
            bar.begins_at != begins
            or bar.closes_at != end
            or bar.closes_at > hourly.source_at
            or bar.interpolated
            or bar.volume <= 0
        ):
            return ("SWING_BASE_HOURLY_GAPPED_UNFINISHED_OR_INTERPOLATED",)
        end = begins
        if begins == opened:
            session = cal.previous_session(session)
            end = cal.session_close(session).to_pydatetime()
    return ()


def direction(bars):
    """Source 10/50 SMA direction with three-bar slopes; unavailable never means neutral."""
    if len(bars) < 54:
        raise ValueError("Complete 54-bar trend context required")
    closes = [b.close for b in bars]
    fast, slow = (sum(closes[-n:]) / n for n in (10, 50))
    prior_fast, prior_slow = (sum(closes[-n - 3 : -3]) / n for n in (10, 50))
    if fast > slow and fast > prior_fast and slow >= prior_slow:
        return "bullish"
    if fast < slow and fast < prior_fast and slow <= prior_slow:
        return "bearish"
    return "neutral"


@exact
def evaluate_base(seed):
    """SignalFlow f9eaf2c: 15-session base, SMA ATR14, prior-volume20 and regime gates."""
    daily, hourly = seed.history.bars, seed.hourly_history
    if len(daily) < 55 or hourly is None:
        raise ValueError("Available prior daily and hourly trend evidence required")
    current, base = daily[-1], daily[-16:-1]
    high, low = max(b.high for b in base), min(b.low for b in base)
    ranges = [
        max(
            b.high - b.low,
            abs(b.high - daily[max(0, n - 1)].close),
            abs(b.low - daily[max(0, n - 1)].close),
        )
        for n, b in enumerate(daily)
    ]
    atrs = [sum(ranges[n - 13 : n + 1]) / 14 for n in range(13, len(ranges))]
    atr, average_atr = atrs[-2], sum(atrs[-16:-1]) / 15
    if atr <= 0 or average_atr <= 0 or any(b.volume <= 0 for b in daily[-21:]):
        raise ValueError("Observed positive ATR and volume required")
    call = seed.instrument.contract.right == "CALL"
    boundary = high if call else low
    width = (high - low) / ((high + low) / 2)
    compression = (high - low) / average_atr
    location = (current.close - current.low) / max(current.high - current.low, D(".000000001"))
    volume = D(current.volume) * 20 / sum(b.volume for b in daily[-21:-1])
    extension = abs(current.close - boundary) / atr
    dd, hd = direction(daily[:-1]), direction(hourly.bars)
    opposed = "bearish" if call else "bullish"
    checks = (
        (width <= D(".12") and compression <= D("6.5"), "SWING_BASE_COMPRESSION_REQUIRED"),
        (
            current.close > boundary if call else current.close < boundary,
            "SWING_BASE_BOUNDARY_CLOSE_REQUIRED",
        ),
        (
            location >= D(".70") if call else location <= D(".30"),
            "SWING_BASE_STRONG_CLOSE_REQUIRED",
        ),
        (volume >= D("1.20"), "SWING_BASE_VOLUME_EXPANSION_REQUIRED"),
        (dd != opposed and hd != opposed, "SWING_BASE_REGIME_OPPOSED"),
        (extension <= D("1.25"), "SWING_BASE_ATR_EXTENSION_EXCEEDED"),
    )
    buffer = max(atr * D(".18"), boundary * D(".0015"))
    stop = _metric(
        boundary - buffer if call else boundary + buffer, ROUND_CEILING if call else ROUND_FLOOR
    )
    return SwingBaseEvidence(
        reference=current.high if call else current.low,
        invalidation=stop,
        base_high=high,
        base_low=low,
        prior_atr=_metric(atr),
        width_fraction=_metric(width),
        compression_ratio=_metric(compression),
        volume_ratio=_metric(volume),
        close_location=_metric(location),
        extension_atr=_metric(extension),
        daily_direction=dd,
        hourly_direction=hd,
        reasons=tuple(reason for passed, reason in checks if not passed),
    )
