"""Versioned UTC-day/half-hour wire mapping; no fabricated or restamped source bars."""

from datetime import UTC, datetime, time, timedelta

from app.mixed.sources import StockDailyHistory
from app.options.read_mapping import exact_rows, instant, response
from app.options.swing import SwingDailyBar, SwingHourlyHistory
from app.robinhood.schedule import XNYSCalendar


def planned(policy, symbols, now, *, calendar=None):
    from app.mixed.swing_feed import planned_history

    legacy = policy.model_copy(update={"bar_mapping": "session-aligned-v1"})
    target, calls = planned_history(legacy, symbols, now, calendar=calendar)
    if target is None:
        return None, ()
    # The last completed UTC date is enough for date-keyed daily bars. Waiting
    # for the target date unnecessarily prevents weekend/holiday preparation.
    boundary = min(datetime.combine(target, time(), UTC),
                   datetime.combine(instant(now).date(), time(), UTC))
    from app.mixed.swing_feed import windows
    previous_open = windows("day", 1, target, calendar or XNYSCalendar())[0][0]
    if boundary <= datetime.combine(previous_open.date(), time(), UTC):
        return None, ()
    result = []
    for call in calls:
        args = dict(call.arguments)
        if args["interval"] == "day":
            start = instant(args["start_time"])
            args.update(start_time=datetime.combine(start.date(), time(), UTC).isoformat(),
                        end_time=boundary.isoformat())
        else:
            args["interval"] = "30minute"
        result.append(call.model_copy(update={"arguments": args}))
    return target, tuple(result)


class HistoryMappingError(ValueError):
    """Only fixed codes and bounded numeric/clock evidence leave the mapper."""

    def __init__(self, reason, **detail):
        super().__init__(reason)
        self.detail = {"reason": reason, **detail}


class HistoryBarError(HistoryMappingError):
    """Bounded, public bar diagnostics; never exception text or transport payloads."""

    def __init__(self, reason, label, expected, observed):
        super().__init__(reason, label=label, expected_begins_at=expected.isoformat(),
                         observed_begins_at=observed.isoformat())


def map_history(schemas, call, raw, *, received_at, target, count, calendar=None):
    _, data = response(schemas, call, raw, "get_equity_historicals")
    interval = call.arguments["interval"]
    if interval not in ("day", "30minute") or data.get("not_found"):
        raise ValueError("Exact daily/half-hour source required")
    cal = calendar or XNYSCalendar()
    from app.mixed.swing_feed import windows

    expected = windows("day" if interval == "day" else "hour", count, target, cal)
    received = instant(received_at)
    if not expected[-1][1] <= received < cal.calendar.session_open(target.isoformat()).to_pydatetime():
        raise ValueError("Completed pre-open source required")
    groups = []
    for opened, closed in expected:
        if interval == "day":
            groups.append([(datetime.combine(opened.date(), time(), UTC), opened, closed)])
        else:
            pieces = []
            at = opened
            while at < closed:
                end = min(at + timedelta(minutes=30), closed)
                pieces.append((at, at, end))
                at = end
            groups.append(pieces)
    labels = [label for group in groups for label, _, _ in group]
    histories = []
    for row in exact_rows(data["results"], call.arguments["symbols"], lambda r: r["symbol"]):
        raw_bars = row["bars"]
        if row["interval"] != interval or row["bounds"] != "regular":
            raise HistoryMappingError("SOURCE_INTERVAL_OR_BOUNDS_MISMATCH", label=call.label)
        if not isinstance(raw_bars, list):
            raise HistoryMappingError("SOURCE_BARS_UNAVAILABLE", label=call.label)
        if len(raw_bars) != len(labels):
            observed = [instant(b["begins_at"]) for b in raw_bars]
            missing = sorted(set(labels) - set(observed))
            unexpected = sorted(set(observed) - set(labels))
            raise HistoryMappingError(
                "SOURCE_COVERAGE_MISMATCH", label=call.label,
                expected_bars=len(labels), observed_bars=len(observed),
                missing_bars=len(missing), unexpected_bars=len(unexpected),
                duplicate_bars=len(observed) - len(set(observed)),
                first_expected=labels[0].isoformat(), last_expected=labels[-1].isoformat(),
                first_observed=min(observed).isoformat() if observed else None,
                last_observed=max(observed).isoformat() if observed else None,
                missing_begins_at=[x.isoformat() for x in missing[:8]],
                unexpected_begins_at=[x.isoformat() for x in unexpected[:8]],
            )
        source_bars = iter(raw_bars)
        bars = []
        for group in groups:
            pieces = []
            for label, opened, closed in group:
                raw_bar = next(source_bars)
                observed = instant(raw_bar["begins_at"])
                reason = (
                    "SOURCE_LABEL_MISMATCH" if observed != label else
                    "NONREGULAR_BAR" if raw_bar.get("session") != "reg" else
                    "INTERPOLATED_BAR" if raw_bar.get("interpolated", False) is not False else
                    "NONPOSITIVE_VOLUME" if raw_bar["volume"] <= 0 else None
                )
                if reason:
                    raise HistoryBarError(reason, call.label, label, observed)
                pieces.append(SwingDailyBar(
                    begins_at=opened, closes_at=closed, open=raw_bar["open_price"],
                    high=raw_bar["high_price"], low=raw_bar["low_price"],
                    close=raw_bar["close_price"], volume=raw_bar["volume"], interpolated=False,
                ))
            bars.append(SwingDailyBar(
                begins_at=pieces[0].begins_at, closes_at=pieces[-1].closes_at,
                open=pieces[0].open, high=max(b.high for b in pieces),
                low=min(b.low for b in pieces), close=pieces[-1].close,
                volume=sum(b.volume for b in pieces), interpolated=False,
            ))
        cls = StockDailyHistory if interval == "day" else SwingHourlyHistory
        histories.append(cls(symbol=row["symbol"], source="robinhood-mcp",
                             source_at=expected[-1][1], received_at=received,
                             entitlement="UNKNOWN", complete=True, bars=tuple(bars)))
    return tuple(histories)
