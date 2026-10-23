"""Source-derived week/month levels and completed break/retest rules; no reads/orders."""

from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from app.options.degen import _metric
from app.options.engine import exact
from app.options.swing_base import direction
from app.options.swing_level_models import SwingLevelEvidence
from app.options.swing_ma import confirmations
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def original_level(seed, calendar):
    bars, key = seed.history.bars, seed.level_key
    local = lambda b: b.begins_at.astimezone(ZoneInfo("America/New_York")).date()
    day = local(bars[-1])
    if key == "weekly_open":
        start, end = day - timedelta(days=day.weekday()), day
    elif key in ("previous_week_high", "previous_week_low"):
        end = day - timedelta(days=day.weekday() + 1)
        start = end - timedelta(days=6)
    elif key in ("previous_month_high", "previous_month_low"):
        end = day.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:
        raise ValueError("Original supported level key required")
    source = [b for b in bars if start <= local(b) <= end]
    expected = calendar.calendar.sessions_in_range(start.isoformat(), end.isoformat())
    if not source or [local(b).isoformat() for b in source] != [
        s.date().isoformat() for s in expected
    ]:
        raise ValueError("Complete actual source period required for original level")
    for b, s in zip(source, expected, strict=True):
        if (
            b.begins_at != calendar.calendar.session_open(s).to_pydatetime()
            or b.closes_at != calendar.calendar.session_close(s).to_pydatetime()
        ):
            raise ValueError("Actual source-period session boundaries required")
    price = (
        source[0].open
        if key == "weekly_open"
        else max(b.high for b in source)
        if key.endswith("high")
        else min(b.low for b in source)
    )
    return price, source[0].begins_at, source[-1].closes_at


@exact
def evaluate_level(seed, *, bullish=None):
    if len(seed.history.bars) < 56:
        raise ValueError("Complete daily regime and source periods required")
    price, start, end = original_level(seed, XNYSCalendar())
    bars, key = seed.history.bars, seed.level_key
    if bullish is not None and type(bullish) is not bool:
        raise ValueError("Explicit source direction must be boolean")
    call = seed.instrument.contract.right == "CALL" if bullish is None else bullish
    expected = "bullish" if call else "bearish"
    dd = direction(bars)
    direction_ok = dd == expected if key == "weekly_open" else key.endswith("high") == call
    recent = bars[-13:]
    breakout = None
    for n in range(1, len(recent)):
        previous, current = recent[n - 1 : n + 1]
        if (
            (previous.close <= price < current.close)
            if call
            else (previous.close >= price > current.close)
        ):
            breakout = n
    tolerance = price * D(".007")
    current = bars[-1]
    touched = current.low <= price + tolerance and current.high >= price - tolerance
    held = current.close >= price * D(".996") if call else current.close <= price * D("1.004")
    after = recent[breakout:] if breakout is not None else recent[-3:]
    count, active = 0, False
    for b in after:
        hit = b.low <= price + tolerance and b.high >= price - tolerance
        count += int(hit and not active)
        active = hit
    tags = confirmations(bars, call)
    checks = (
        (direction_ok, "SWING_LEVEL_DIRECTION_REQUIRED"),
        (breakout is not None, "SWING_LEVEL_COMPLETED_BREAK_REQUIRED"),
        (touched, "SWING_LEVEL_RETEST_REQUIRED"),
        (held, "SWING_LEVEL_ACCEPTANCE_REQUIRED"),
        (bool(tags), "SWING_LEVEL_DIRECTIONAL_CONFIRMATION_REQUIRED"),
    )
    stop = price - tolerance * D("1.5") if call else price + tolerance * D("1.5")
    return SwingLevelEvidence(
        level_key=key,
        level_price=price,
        source_start=start,
        source_end=end,
        breakout_at=recent[breakout].closes_at if breakout is not None else None,
        reference=current.high if call else current.low,
        invalidation=_metric(stop, ROUND_CEILING if call else ROUND_FLOOR),
        test_number=max(1, count),
        daily_direction=dd,
        confirmations=tags,
        warnings=("SWING_LEVEL_LATE_RETEST",) if count > 2 else (),
        reasons=tuple(reason for passed, reason in checks if not passed),
    )
