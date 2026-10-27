"""Documented wire-shape fixtures; no external calls or operational evidence."""

import json
from datetime import timedelta

import pytest
from test_event_assessment import AT, P, request, snapshot

from app.events.adapters import (
    BEA_URL,
    BLS_URL,
    CboeDailyAdapter,
    FinnhubEarningsAdapter,
    ICalendarAdapter,
    SourceSpec,
    TradingEconomicsAdapter,
    local_time,
    native_sample,
    sessions,
)
from app.events.assessment import assess, prepare
from app.events.models import Event


def spec(source="bls", dataset="macro.bls", symbols=()):
    return SourceSpec(
        source, "fixture-wire-v1", dataset, AT - timedelta(days=1), AT + timedelta(days=7), symbols
    )


def ics(start="DTSTART;TZID=America/New_York:20261027T110000", extra="", end=""):
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:release\r\nSEQUENCE:1\r\nSUMMARY:Economic\\, release\r\n{start}\r\nDTSTAMP:20261026T120000Z\r\n{extra}\r\nEND:VEVENT\r\n{end}\r\nEND:VCALENDAR"


@pytest.mark.parametrize("url", [BLS_URL, BEA_URL])
def test_public_ical_normalizes_original_times_folded_text_duration_and_coverage(url):
    raw = ics(extra="DURATION:PT30M").replace("Economic\\, release", "Economic\\,\r\n  release")
    result = ICalendarAdapter(spec(), url).parse(raw, AT)
    e = Event.model_validate(result["events"][0])
    assert e.starts_at == AT and e.ends_at == AT + timedelta(minutes=30)
    assert e.title == "Economic, release"
    assert e.source_at == AT.replace(day=26, hour=12)
    assert result["coverage"][0]["status"] == "PARTIAL"


@pytest.mark.parametrize(
    "start",
    [
        "DTSTART;TZID=America/New_York:20260308T023000",
        "DTSTART;TZID=America/New_York:20261101T013000",
        "DTSTART:20261027T110000",
    ],
)
def test_invalid_dst_and_floating_time_rejected(start):
    with pytest.raises(ValueError):
        ICalendarAdapter(spec(), BLS_URL).parse(ics(start), AT)


def test_valid_dst_offsets_differ():
    assert local_time("20260306T083000", "America/New_York").hour == 13
    assert local_time("20260309T083000", "America/New_York").hour == 12


@pytest.mark.parametrize("extra", ["RRULE:FREQ=DAILY", "SEQUENCE:2"])
def test_unsupported_or_conflicting_ical_schema_not_silently_skipped(extra):
    with pytest.raises(ValueError):
        ICalendarAdapter(spec(), BLS_URL).parse(ics(extra=extra), AT)


def test_all_day_and_cancellation_preserve_uncertainty():
    a = ICalendarAdapter(spec(), BLS_URL)
    e = Event.model_validate(
        a.parse(ics("DTSTART;VALUE=DATE:20261101", "STATUS:CANCELLED"), AT)["events"][0]
    )
    assert e.precision == "DATE" and not e.complete and e.status == "CANCELLED"
    assert (e.ends_at - e.starts_at).total_seconds() == 25 * 3600


def test_te_preserves_distinct_related_events_no_name_whitelist_and_access_failure():
    adapter = TradingEconomicsAdapter(spec("te", "macro.us.high_impact"))
    with pytest.raises(PermissionError):
        adapter.fetch()
    rows = [
        {
            "CalendarId": str(i),
            "Date": f"2026-10-27T{hour}:00",
            "LastUpdate": "2026-10-26T12:00:00",
            "Country": "United States",
            "Category": category,
            "Event": category,
            "DateSpan": "0",
            "Importance": 3,
        }
        for i, hour, category in (
            (1, "18:00", "Interest Rate Decision"),
            (2, "18:30", "Press Conference"),
            (3, "14:00", "New Indicator"),
        )
    ]
    parsed = adapter.parse(json.dumps(rows), AT)
    assert len(parsed["events"]) == 3
    assert len({e["event_id"] for e in parsed["events"]}) == 3
    assert all(e["timezone"] == "UTC" for e in parsed["events"])
    assert parsed["coverage"][0]["status"] == "PARTIAL"
    with pytest.raises(ValueError):
        adapter.parse(json.dumps([rows[0]] * 1000), AT)


def test_company_date_is_not_exact_clearance_or_macro_coverage():
    adapter = FinnhubEarningsAdapter(spec("finnhub", "company.earnings", ("AAPL",)))
    with pytest.raises(PermissionError):
        adapter.fetch()
    raw = json.dumps(
        {
            "earningsCalendar": [
                {"symbol": "AAPL", "year": 2026, "quarter": 4, "date": "2026-10-27", "hour": "amc"}
            ]
        }
    )
    parsed = adapter.parse(raw, AT)
    e = Event.model_validate(parsed["events"][0])
    assert e.source_at is None and e.precision == "DATE" and not e.complete
    assert parsed["coverage"][0]["scope"] == "SYMBOL"
    a = assess(prepare(snapshot(events=(e,)), P), request())
    assert a.market_state == "CLEAR" and a.symbol_state == "BLOCK_NEW_ENTRIES"


def test_daily_vix_retains_date_and_never_becomes_intraday_stress():
    adapter = CboeDailyAdapter(spec("cboe", "volatility.daily"))
    parsed = adapter.parse("DATE,OPEN,HIGH,LOW,CLOSE\n10/26/2026,25,27,24,26\n", AT)
    assert parsed["volatility"][0]["frequency"] == "DAILY_CLOSE"
    assert "source_at" not in parsed["volatility"][0]
    a = assess(prepare(snapshot(volatility=parsed["volatility"]), P), request())
    assert not a.would_block_new_entries
    old = adapter.parse("DATE,CLOSE\n01/01/2026,26\n", AT)
    stale = assess(prepare(snapshot(volatility=old["volatility"]), P), request())
    assert any(f.reason == "VOLATILITY_DAILY_STALE_OR_UNVERIFIED" for f in stale.findings)
    with pytest.raises(ValueError):
        adapter.parse("DATE,CLOSE\n10/27/2026,26\n", AT)


def test_native_quotes_keep_unknown_liquidity_entitlement_and_reference_identity():
    from app.options.models import UnderlyingQuote

    q = UnderlyingQuote(
        symbol="SPY",
        source="native",
        source_at=AT,
        received_at=AT,
        complete=True,
        entitlement="UNKNOWN",
        bid="100",
        ask="100.01",
    )
    s = native_sample(q, evidence_ref="native:1")
    assert s.bid_size is None and s.ask_size is None and s.entitlement == "UNKNOWN"
    assert s.reference_price is None
    prior = q.model_copy(
        update={"source_at": AT - timedelta(seconds=60), "received_at": AT - timedelta(seconds=60)}
    )
    assert native_sample(q, evidence_ref="native:2", reference=prior).reference_price is None
    prior = prior.model_copy(update={"entitlement": "REALTIME"})
    assert native_sample(q, evidence_ref="native:2", reference=prior).reference_price is not None
    with pytest.raises(ValueError):
        native_sample(
            q, evidence_ref="native:2", reference=prior.model_copy(update={"symbol": "QQQ"})
        )


def test_session_materialization_uses_actual_early_close_and_explicit_horizon():
    from datetime import date

    result = sessions(date(2026, 11, 26), date(2026, 11, 27), received_at=AT)
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["closes_at"].startswith("2026-11-27T18:00")
    with pytest.raises(ValueError):
        sessions(date(2026, 1, 1), date(2028, 1, 1), received_at=AT)
