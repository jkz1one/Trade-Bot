"""Pre-open Swing history capture, with original bars and no eligibility upgrade.

This stores native daily/hourly evidence for later source binding. It does not
invent catalysts, entitlement, targets or an executable Swing seed.
"""

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from app.mixed.sources import StockDailyHistory
from app.options.engine import fingerprint
from app.options.models import OptionRecord
from app.options.read_gateway import ReadSample, same_schema_contract
from app.options.read_mapping import SOURCE, exact_rows, instant, response
from app.options.swing import SwingDailyBar, SwingHourlyHistory
from app.robinhood.schedule import XNYSCalendar


class SwingHistoryPolicy(OptionRecord):
    version: Literal["preopen-swing-history-v1"] = "preopen-swing-history-v1"
    bar_mapping: Literal["session-aligned-v1", "utc-day-halfhour-v1"] = Field(
        default="session-aligned-v1", exclude_if=lambda v: v == "session-aligned-v1"
    )
    daily_bars: int = Field(default=56, strict=True, ge=56, le=260)
    hourly_bars: int = Field(default=54, strict=True, ge=54, le=260)


class SwingHistorySnapshot(OptionRecord):
    version: Literal["preopen-swing-history-snapshot-v1"] = "preopen-swing-history-snapshot-v1"
    target_session: date
    captured_at: datetime
    capture_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    daily: tuple[StockDailyHistory, ...] = Field(min_length=1, max_length=2)
    hourly: tuple[SwingHourlyHistory, ...] = Field(min_length=1, max_length=2)


def target_session(now, calendar):
    """Prepare only after the previous close and before the target session opens."""
    now = instant(now)
    cal = calendar.calendar
    day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    target = cal.date_to_session(day, direction="next")
    if now >= cal.session_open(target).to_pydatetime():
        target = cal.next_session(target)
    previous = cal.previous_session(target)
    if now < cal.session_close(previous).to_pydatetime():
        return None
    return target.date()


def windows(interval, count, target, calendar):
    """Calendar-derived session bars, including the final short hourly segment."""
    if interval not in {"day", "hour"} or type(count) is not int or not 1 <= count <= 260:
        raise ValueError("Bounded explicit daily/hourly interval required")
    cal = calendar.calendar
    session = cal.previous_session(target.isoformat())
    result = []
    while len(result) < count:
        start = cal.session_open(session).to_pydatetime()
        close = cal.session_close(session).to_pydatetime()
        if interval == "day":
            result.append((start, close))
        else:
            segments = []
            while start < close:
                end = min(start + timedelta(hours=1), close)
                segments.append((start, end))
                start = end
            result.extend(reversed(segments))
        session = cal.previous_session(session)
    return tuple(reversed(result[:count]))


def planned_history(policy, symbols, now, *, calendar=None):
    policy = SwingHistoryPolicy.model_validate(policy.model_dump())
    if not symbols or len(set(symbols)) != len(symbols) or not set(symbols) <= {"SPY", "QQQ"}:
        raise ValueError("Exact supported Swing history subjects required")
    if policy.bar_mapping == "utc-day-halfhour-v1":
        from app.mixed.swing_bar_mapping import planned

        return planned(policy, symbols, now, calendar=calendar)
    calendar = calendar or XNYSCalendar()
    target = target_session(now, calendar)
    if target is None:
        return None, ()
    calls = []
    for symbol in symbols:
        # One symbol per call keeps the largest allowed histories within the
        # existing per-response bound. No schema or capture budget is widened.
        for interval, count in (("day", policy.daily_bars), ("hour", policy.hourly_bars)):
            expected = windows(interval, count, target, calendar)
            calls.append(
                ReadSample(
                    label=f"swing-{symbol}-{interval}",
                    tool="get_equity_historicals",
                    arguments={
                        "symbols": [symbol],
                        "interval": interval,
                        "bounds": "regular",
                        "adjustment_type": "split",
                        "start_time": expected[0][0].isoformat(),
                        "end_time": expected[-1][1].isoformat(),
                    },
                )
            )
    return target, tuple(calls)


def map_history(schemas, call, raw, *, received_at, target, count, calendar=None):
    calendar = calendar or XNYSCalendar()
    call, data = response(schemas, call, raw, "get_equity_historicals")
    args, received = call.arguments, instant(received_at)
    interval = args.get("interval")
    expected = windows(interval, count, target, calendar)
    if (
        args.get("bounds") != "regular"
        or args.get("adjustment_type") != "split"
        or instant(args["start_time"]) != expected[0][0]
        or instant(args["end_time"]) != expected[-1][1]
        or not expected[-1][1]
        <= received
        < calendar.calendar.session_open(target.isoformat()).to_pydatetime()
        or data.get("not_found")
    ):
        raise ValueError("Exact completed pre-open history request required")
    histories = []
    for row in exact_rows(data["results"], args["symbols"], lambda row: row["symbol"]):
        if (
            row["interval"] != interval
            or row["bounds"] != "regular"
            or not isinstance(row["bars"], list)
            or len(row["bars"]) != len(expected)
        ):
            raise ValueError("Exact complete session history coverage required")
        bars = []
        for raw_bar, (begins, closes) in zip(row["bars"], expected, strict=True):
            if (
                not isinstance(raw_bar, dict)
                or raw_bar.get("session") != "reg"
                or instant(raw_bar["begins_at"]) != begins
                or raw_bar["volume"] <= 0
                or raw_bar.get("interpolated", False) is not False
            ):
                raise ValueError("Original positive-volume noninterpolated session bar required")
            # The schema's left edge and the pinned local exchange calendar bind
            # closes_at. Never assume 24h daily bars or invent OHLC/volume/gap bars.
            bars.append(
                SwingDailyBar(
                    begins_at=begins,
                    closes_at=closes,
                    open=raw_bar["open_price"],
                    high=raw_bar["high_price"],
                    low=raw_bar["low_price"],
                    close=raw_bar["close_price"],
                    volume=raw_bar["volume"],
                    interpolated=False,
                )
            )
        cls = StockDailyHistory if interval == "day" else SwingHourlyHistory
        histories.append(
            cls(
                symbol=row["symbol"],
                source=SOURCE,
                source_at=expected[-1][1],
                received_at=received,
                entitlement="UNKNOWN",
                complete=True,
                bars=tuple(bars),
            )
        )
    return tuple(histories)


def snapshot(policy, symbols, schemas, captured):
    """Bind one complete original capture to one immutable target-session source."""
    if (
        captured.plan is None
        or not same_schema_contract(captured.schemas, schemas)
        or captured.started_at > captured.collected_at
    ):
        raise ValueError("Original history capture clocks and schemas required")
    target, calls = planned_history(policy, symbols, captured.started_at)
    actual = tuple(c for c in captured.plan.calls if c.label.startswith("swing-"))
    if target is None or actual != calls or captured.status != "COMPLETE":
        raise ValueError("Exact original pre-open Swing capture required")
    daily, hourly = [], []
    for call, receipt in zip(captured.plan.calls, captured.observations, strict=True):
        if call not in calls:
            continue
        if (
            receipt.get("label") != call.label
            or receipt.get("tool") != call.tool
            or receipt.get("completed") is not True
        ):
            raise ValueError("Swing read receipt identity changed")
        interval = call.arguments["interval"]
        mapper = map_history
        if policy.bar_mapping == "utc-day-halfhour-v1":
            from app.mixed.swing_bar_mapping import map_history as mapper
        result = mapper(
            schemas,
            call,
            receipt["raw"],
            received_at=captured.collected_at,
            target=target,
            count=policy.daily_bars if interval == "day" else policy.hourly_bars,
        )
        (daily if interval == "day" else hourly).extend(result)
    return SwingHistorySnapshot(
        target_session=target,
        captured_at=captured.collected_at,
        capture_hash=fingerprint(captured),
        daily=tuple(daily),
        hourly=tuple(hourly),
    )
