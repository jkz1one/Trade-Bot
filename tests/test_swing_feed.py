"""Pinned-schema synthetic histories; no market, credentials or model calls."""

import asyncio
import copy
from datetime import UTC, date, datetime, timedelta

import pytest
from test_portfolio_feed import policy as feed_policy
from test_robinhood_read_mapping import envelope, equity
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
from app.mixed.swing_feed import SwingHistoryPolicy, map_history, planned_history, windows
from app.options.engine import fingerprint
from app.options.read_capture import CaptureResult, policy_digest
from app.options.runtime import read_packet
from app.robinhood.schedule import XNYSCalendar

PREOPEN = datetime(2026, 11, 30, 12, tzinfo=UTC)


def policy(**changes):
    return FeedPolicy.model_validate(
        {**feed_policy().model_dump(), "swing_history": SwingHistoryPolicy(), **changes}
    )


def history_raw(call, at=PREOPEN):
    interval = call.arguments["interval"]
    target, _ = planned_history(SwingHistoryPolicy(), ("SPY", "QQQ"), at)
    pairs = windows(interval, 56 if interval == "day" else 54, target, XNYSCalendar())
    return envelope(
        [
            {
                "symbol": call.arguments["symbols"][0],
                "interval": interval,
                "bounds": "regular",
                "bars": [
                    {
                        "begins_at": start.isoformat(),
                        "open_price": "600.12",
                        "high_price": "602.45",
                        "low_price": "599.33",
                        "close_price": "601.26",
                        "volume": 123456,
                        "session": "reg",
                    }
                    for start, _ in pairs
                ],
            }
        ]
    )


def reader(now, seen, *, bad_history=None, fail_quotes=False):
    async def capture(p, *, schemas, plan):
        seen.append(plan)
        observations, failed = [], False
        for call in plan.calls:
            entry = {"label": call.label, "tool": call.tool, "completed": True}
            if fail_quotes or (bad_history == "transport" and call.label.startswith("swing-")):
                entry["completed"] = False
                observations.append(entry)
                failed = True
                break
            if call.tool == "get_equity_quotes":
                quotes = []
                for symbol in call.arguments["symbols"]:
                    value = equity(symbol)
                    for key in ("venue_bid_time", "venue_ask_time", "venue_last_trade_time"):
                        value[key] = now.isoformat()
                    quotes.append({"quote": value})
                entry["raw"] = envelope(quotes)
            else:
                entry["raw"] = history_raw(call, now)
                if bad_history == "gap":
                    entry["raw"]["structuredContent"]["data"]["results"][0]["bars"].pop()
            observations.append(entry)
        return CaptureResult(
            request_id="b" * 32,
            operation="CAPTURE",
            policy_sha256=policy_digest(p),
            started_at=now,
            collected_at=now + timedelta(seconds=2),
            elapsed_seconds=2,
            status="FAILED" if failed else "COMPLETE",
            error_class="ValueError" if failed else None,
            schemas=schemas,
            plan=plan,
            observations=observations,
        )

    return capture


def test_calendar_bounds_include_holidays_half_days_and_dst():
    cal = XNYSCalendar()
    target, calls = planned_history(SwingHistoryPolicy(), ("SPY", "QQQ"), PREOPEN)
    assert target == date(2026, 11, 30) and len(calls) == 4
    daily = windows("day", 56, target, cal)
    hourly = windows("hour", 54, target, cal)
    assert daily[-1] == (
        datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
        datetime(2026, 11, 27, 18, tzinfo=UTC),
    )
    assert hourly[-1][1] - hourly[-1][0] == timedelta(minutes=30)
    assert date(2026, 11, 26) not in {a.date() for a, _ in daily}
    assert {a.hour for a, _ in daily} == {13, 14}
    assert all(
        c.arguments["bounds"] == "regular" and c.arguments["adjustment_type"] == "split"
        for c in calls
    )
    assert planned_history(
        SwingHistoryPolicy(), ("SPY",), datetime(2026, 11, 30, 15, tzinfo=UTC)
    ) == (None, ())
    tomorrow, _ = planned_history(
        SwingHistoryPolicy(), ("SPY",), datetime(2026, 11, 30, 22, tzinfo=UTC)
    )
    assert tomorrow == date(2026, 12, 1)


@pytest.mark.parametrize("interval,count", [("day", 56), ("hour", 54)])
def test_native_history_preserves_values_and_unknown_entitlement(schemas, interval, count):
    target, calls = planned_history(SwingHistoryPolicy(), ("SPY",), PREOPEN)
    call = next(c for c in calls if c.arguments["interval"] == interval)
    raw = history_raw(call)
    before = copy.deepcopy(raw)
    (history,) = map_history(schemas, call, raw, received_at=PREOPEN, target=target, count=count)
    assert history.complete and history.entitlement == "UNKNOWN"
    assert len(history.bars) == count and str(history.bars[0].open) == "600.12"
    assert history.source_at == datetime(2026, 11, 27, 18, tzinfo=UTC)
    assert history.received_at == PREOPEN and history.bars[-1].closes_at == history.source_at
    assert (
        raw == before
        and "interpolated" not in raw["structuredContent"]["data"]["results"][0]["bars"][0]
    )


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "duplicate",
        "unordered",
        "midnight",
        "session",
        "volume",
        "interpolated",
        "ohlc",
        "interval",
        "open_session",
    ],
)
def test_ambiguous_or_incomplete_history_never_becomes_complete(schemas, bad):
    target, calls = planned_history(SwingHistoryPolicy(), ("SPY",), PREOPEN)
    call = calls[0]
    raw = history_raw(call)
    row = raw["structuredContent"]["data"]["results"][0]
    bars = row["bars"]
    received = PREOPEN
    if bad == "missing":
        bars.pop()
    elif bad == "duplicate":
        bars[1] = dict(bars[0])
    elif bad == "unordered":
        bars.reverse()
    elif bad == "midnight":
        bars[0]["begins_at"] = bars[0]["begins_at"][:10] + "T00:00:00+00:00"
    elif bad == "session":
        bars[0].pop("session")
    elif bad == "volume":
        bars[0]["volume"] = 0
    elif bad == "interpolated":
        bars[0].update(interpolated=True, volume=0)
    elif bad == "ohlc":
        bars[0]["high_price"] = "1"
    elif bad == "interval":
        row["interval"] = "hour"
    else:
        received = datetime(2026, 11, 30, 14, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        map_history(schemas, call, raw, received_at=received, target=target, count=56)


def test_cache_survives_restart_without_rereading_or_restamping(tmp_path, schemas):
    p, seen = policy(), []
    feed = ContinuousFeed(tmp_path / "feed", p, schemas, create=True)
    try:
        result = asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, seen)))
        assert result["status"] == "DELIVERED", result
        original = feed.swing_snapshot(date(2026, 11, 30))
        assert original is not None and len(seen[0].calls) == 5
        assert {h.symbol for h in original.daily} == {"SPY", "QQQ"}
        assert all(h.entitlement == "UNKNOWN" for h in (*original.daily, *original.hourly))
    finally:
        feed.close()
    restarted = ContinuousFeed(tmp_path / "feed", p, schemas)
    try:
        now = PREOPEN + timedelta(seconds=20)
        assert (
            asyncio.run(restarted.tick(now=now, reader=reader(now, seen)))["status"] == "DELIVERED"
        )
        assert len(seen[-1].calls) == 1
        assert restarted.swing_snapshot(date(2026, 11, 30)) == original
        packet = read_packet(tmp_path / "feed/feed.json")
        assert packet.sequence == 2 and len(packet.frame.stocks) == 2
        assert all(s.swing is None and s.catalyst is None for s in packet.frame.stocks)
    finally:
        restarted.close()


@pytest.mark.parametrize("bad_history", ["gap", "transport"])
def test_history_failure_retains_usable_quotes_and_original_failed_capture(
    tmp_path, schemas, bad_history
):
    p, seen = policy(), []
    feed = ContinuousFeed(tmp_path / "feed", p, schemas, create=True)
    try:
        result = asyncio.run(
            feed.tick(now=PREOPEN, reader=reader(PREOPEN, seen, bad_history=bad_history))
        )
        assert result["status"] == "DELIVERED", result
        packet = read_packet(tmp_path / "feed/feed.json")
        assert packet.coverage_issues == ("SWING_HISTORY_UNAVAILABLE",)
        assert len(packet.frame.stocks) == 2 and packet.kind == "MARKET"
        assert feed.swing_snapshot(date(2026, 11, 30)) is None
        raw = CaptureResult.model_validate_json(
            feed.db.execute("SELECT raw_json FROM attempts").fetchone()[0]
        )
        assert raw.status == ("FAILED" if bad_history == "transport" else "COMPLETE")
    finally:
        feed.close()


def test_failed_required_quote_does_not_publish_partial_history_as_market(tmp_path, schemas):
    feed = ContinuousFeed(tmp_path / "feed", policy(), schemas, create=True)
    try:
        result = asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [], fail_quotes=True)))
        assert result["status"] == "FAILED"
        assert not (tmp_path / "feed/feed.json").exists()
    finally:
        feed.close()


def test_history_backfill_cannot_spend_the_quote_budget(tmp_path, schemas):
    seen = []
    feed = ContinuousFeed(tmp_path / "feed", policy(calls_per_minute=2), schemas, create=True)
    try:
        for now in (PREOPEN, PREOPEN + timedelta(seconds=10)):
            assert (
                asyncio.run(feed.tick(now=now, reader=reader(now, seen)))["status"] == "DELIVERED"
            )
        assert [len(p.calls) for p in seen] == [1, 1]
        assert feed.swing_snapshot(date(2026, 11, 30)) is None
    finally:
        feed.close()


def test_failed_backfills_reserve_the_next_quote_polls_across_restart(tmp_path, schemas):
    seen, p = [], policy()
    for index in range(6):
        feed = ContinuousFeed(tmp_path / "feed", p, schemas, create=index == 0)
        try:
            now = PREOPEN + timedelta(seconds=index * 10)
            result = asyncio.run(feed.tick(now=now, reader=reader(now, seen, bad_history="gap")))
            assert result["status"] == "DELIVERED", result
        finally:
            feed.close()
    assert [len(plan.calls) for plan in seen] == [5, 5, 1, 1, 1, 1]


@pytest.mark.parametrize("tamper", ["payload", "raw"])
def test_cached_history_rechecked_against_its_original_capture(tmp_path, schemas, tamper):
    import json

    feed = ContinuousFeed(tmp_path / "feed", policy(), schemas, create=True)
    try:
        assert (
            asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])))["status"] == "DELIVERED"
        )
        if tamper == "payload":
            row = feed.db.execute("SELECT payload_json FROM swing_history").fetchone()
            from app.mixed.swing_feed import SwingHistorySnapshot

            value = json.loads(row[0])
            value["daily"][0]["bars"][0]["volume"] += 1
            changed = SwingHistorySnapshot.model_validate(value)
            feed.db.execute(
                "UPDATE swing_history SET payload_json=?,payload_hash=?",
                (changed.model_dump_json(), fingerprint(changed)),
            )
        else:
            raw = json.loads(feed.db.execute("SELECT raw_json FROM attempts").fetchone()[0])
            raw["observations"][1]["raw"]["structuredContent"]["data"]["results"][0]["bars"][0][
                "volume"
            ] += 1
            feed.db.execute("UPDATE attempts SET raw_json=?", (json.dumps(raw),))
        feed.db.commit()
        with pytest.raises(ValueError, match="binding changed"):
            feed.swing_snapshot(date(2026, 11, 30))
    finally:
        feed.close()


def test_publication_crash_recovers_history_and_quote_sequence_together(
    tmp_path, schemas, monkeypatch
):
    p = policy()
    feed = ContinuousFeed(tmp_path / "feed", p, schemas, create=True)

    def failed(_packet):
        raise OSError("Synthetic file publication interruption")

    monkeypatch.setattr(feed, "publish", failed)
    try:
        assert asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])))["status"] == "FAILED"
        assert feed.db.execute("SELECT status FROM attempts").fetchone()[0] == "NORMALIZED"
    finally:
        feed.close()
    recovered = ContinuousFeed(tmp_path / "feed", p, schemas)
    try:
        assert read_packet(tmp_path / "feed/feed.json").sequence == 1
        assert recovered.swing_snapshot(date(2026, 11, 30)) is not None
    finally:
        recovered.close()


def test_legacy_feed_hash_unchanged_and_no_silent_history_enrollment(tmp_path, schemas):
    old = feed_policy()
    assert "swing_history" not in old.model_dump()
    feed = ContinuousFeed(tmp_path / "feed", old, schemas, create=True)
    assert (
        feed.db.execute("SELECT 1 FROM sqlite_master WHERE name='swing_history'").fetchone() is None
    )
    feed.close()
    with pytest.raises(ValueError, match="Frozen feed configuration changed"):
        ContinuousFeed(tmp_path / "feed", policy(), schemas)


def test_wiring_keeps_catalyst_binding_blockers_and_checks_lookback(tmp_path, schemas):
    from test_connected_check import configuration, report

    from app.mixed.sources import StockSwingPolicy
    from app.options.runtime_models import RuntimeSettings

    settings, feed = configuration(tmp_path)
    value = settings.model_dump()
    value["stock_policy"]["family_priority"] = ("SWING", "DEGEN")
    value["stock_policy"]["swing"] = StockSwingPolicy(
        families=("SWING_DAILY_BASE",),
        history_source="robinhood-mcp",
        daily_lookback=60,
        hourly_source="robinhood-mcp",
        hourly_lookback=54,
        catalyst_source="reviewed-events",
        catalyst_max_age_seconds=30,
        maximum_chase_fraction=".01",
        stop_buffer_fraction=".001",
    )
    settings = RuntimeSettings.model_validate(value)
    feed = FeedPolicy.model_validate({**feed.model_dump(), "swing_history": SwingHistoryPolicy()})
    checked = report(tmp_path, schemas, settings, feed)
    assert "SWING_HISTORY_COVERAGE_TOO_SHORT" in checked["wiring_errors"]
    assert "SWING_CATALYST_FEED_UNAVAILABLE" in checked["entry_blockers"]
    assert "SWING_PREOPEN_HISTORY_AND_SOURCE_BINDING_REQUIRED" in checked["entry_blockers"]
    assert not checked["trading_ready"]


def test_resampled_optional_failure_keeps_required_market_reads(tmp_path, schemas):
    # The original half-hour request must retain the same optional-failure boundary
    # as the old hourly mapping; otherwise a missing Swing history drops peers.
    p = policy(swing_history=SwingHistoryPolicy(bar_mapping='utc-day-halfhour-v1'))
    seen = []
    feed = ContinuousFeed(tmp_path / 'feed', p, schemas, create=True)
    try:
        result = asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, seen, bad_history='transport')))
        assert result['status'] == 'DELIVERED', result
        assert any(c.arguments.get('interval') == '30minute' for c in seen[0].calls)
        packet = read_packet(tmp_path / 'feed/feed.json')
        assert packet.kind == 'MARKET' and len(packet.frame.stocks) == 2
        assert packet.coverage_issues == ('SWING_HISTORY_UNAVAILABLE',)
        assert feed.swing_snapshot(date(2026, 11, 30)) is None
    finally:
        feed.close()
