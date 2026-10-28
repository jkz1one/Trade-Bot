"""Candidate wire mapping: UTC-date daily bars and exact half-hour aggregation.

Proof only. This does not change the frozen collector mapper or install a source.
"""

import importlib.util
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from app.mixed.sources import StockDailyHistory
from app.mixed.swing_feed import SwingHistorySnapshot, windows
from app.options.engine import fingerprint
from app.options.read_capture import CaptureResult
from app.options.read_gateway import CapturePlan
from app.options.read_mapping import exact_rows, instant, response
from app.options.swing import SwingDailyBar, SwingHourlyHistory
from app.robinhood.schedule import XNYSCalendar

spec = importlib.util.spec_from_file_location(
    "history_proof_base", Path(__file__).with_name("swing-history-proof.py")
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def plan_for(policy, now):
    target, old = base.plan_for(policy, now)
    if old is None:
        return None, None
    boundary = datetime.combine(target, time(), UTC)
    # Do not request future boundaries or assume a just-closed daily bar is published.
    if instant(now) < boundary:
        return None, None
    calls = []
    for call in old.calls:
        args = dict(call.arguments)
        if args["interval"] == "day":
            start = instant(args["start_time"])
            args.update(start_time=datetime.combine(start.date(), time(), UTC).isoformat(),
                        end_time=boundary.isoformat())
        else:
            args["interval"] = "30minute"
        calls.append(call.model_copy(update={"arguments": args}))
    return target, CapturePlan(purpose=old.purpose, symbols=old.symbols, calls=tuple(calls))


def map_series(schemas, call, raw, *, received_at, target, count):
    _, data = response(schemas, call, raw, "get_equity_historicals")
    interval = call.arguments["interval"]
    if interval not in ("day", "30minute") or data.get("not_found"):
        raise ValueError("Exact daily/half-hour source required")
    cal = XNYSCalendar()
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
        if (row["interval"] != interval or row["bounds"] != "regular"
                or not isinstance(raw_bars, list) or len(raw_bars) != len(labels)):
            raise ValueError("Exact complete source coverage required")
        source_bars = iter(raw_bars)
        bars = []
        for group in groups:
            pieces = []
            for label, opened, closed in group:
                raw_bar = next(source_bars)
                if (instant(raw_bar["begins_at"]) != label or raw_bar.get("session") != "reg"
                        or raw_bar.get("interpolated", False) is not False
                        or raw_bar["volume"] <= 0):
                    raise ValueError("Missing, shifted or interpolated source bar")
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


def inspect_capture(policy, plan, artifact):
    report, _ = base.inspect_capture(policy, plan, artifact)
    report["version"] = "candidate-swing-bar-mapping-proof-v1"
    report["collector_mapping_changed"] = False
    captured = CaptureResult.model_validate(artifact["result"])
    target, expected_plan = plan_for(policy, captured.started_at)
    if expected_plan != plan or target is None:
        raise ValueError("Exact original candidate plan required")
    report["requested_target_session"] = str(target)
    if captured.status != "COMPLETE" or len(captured.observations) != len(plan.calls):
        return report, None
    daily, hourly = [], []
    try:
        for call, receipt in zip(plan.calls, captured.observations, strict=True):
            if receipt.get("completed") is not True:
                raise ValueError("Incomplete history read")
            is_daily = call.arguments["interval"] == "day"
            values = map_series(
                captured.schemas, call, receipt["raw"], received_at=captured.collected_at,
                target=target, count=(policy.swing_history.daily_bars if is_daily
                                     else policy.swing_history.hourly_bars),
            )
            (daily if is_daily else hourly).extend(values)
    except (ValueError, KeyError, TypeError, ArithmeticError, base.SchemaError):
        report["status"] = "CANDIDATE_HISTORY_MAPPING_UNAVAILABLE"
        return report, None
    history = SwingHistorySnapshot(target_session=target, captured_at=captured.collected_at,
                                   capture_hash=fingerprint(captured), daily=tuple(daily),
                                   hourly=tuple(hourly))
    report.update(status="CANDIDATE_HISTORY_MAPPED", target_session=str(target),
                  daily_bars={h.symbol: len(h.bars) for h in daily},
                  hourly_bars={h.symbol: len(h.bars) for h in hourly})
    return report, history


if __name__ == "__main__":
    raise SystemExit(base.main(planner=plan_for, inspector=inspect_capture))
