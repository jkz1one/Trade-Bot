"""Synthetic evidence proves semantics only, never provider acceptance."""

from datetime import UTC, datetime, timedelta

import pytest

from app.events.adapters import sessions
from app.events.assessment import assess, prepare
from app.events.models import Coverage, Event, MarketSample, Policy, Request, Snapshot
from app.options.engine import fingerprint

AT = datetime(2026, 10, 27, 15, tzinfo=UTC)
P = Policy()


def changed(value, **updates):
    return type(value).model_validate(value.model_dump() | updates)


def request(at=AT, **kwargs):
    return Request(
        **(
            {
                "population_id": "fixture-owner",
                "decision_id": "actual-source-key",
                "family": "DEGEN",
                "symbol": "AAPL",
                "instrument_id": "aapl-id",
                "underlying_kind": "EQUITY",
                "evaluated_at": at,
                "holding_until": at + timedelta(minutes=10),
            }
            | kwargs
        )
    )


def coverage(dataset="macro.us.high_impact", at=AT, **kwargs):
    return Coverage(
        **(
            {
                "source": "fixture",
                "source_version": "fixture-v1",
                "dataset": dataset,
                "scope": "SYMBOL" if dataset == "company.earnings" else "MARKET",
                "symbols": ("AAPL",) if dataset == "company.earnings" else (),
                "starts_at": at - timedelta(days=1),
                "ends_at": at + timedelta(days=2),
                "checked_at": at - timedelta(hours=1),
                "fresh_until": at + timedelta(hours=6),
                "status": "COMPLETE",
            }
            | kwargs
        )
    )


def sample(symbol="AAPL", at=AT, **kwargs):
    return MarketSample(
        **(
            {
                "source": "fixture",
                "source_version": "fixture-v1",
                "evidence_ref": "quote:" + symbol,
                "instrument_id": "aapl-id" if symbol == "AAPL" else symbol,
                "symbol": symbol,
                "asset": "STOCK",
                "source_at": at,
                "received_at": at,
                "bid": "100",
                "ask": "100.01",
                "bid_size": "100",
                "ask_size": "100",
                "reference_price": "100",
                "reference_at": at - timedelta(seconds=60),
                "entitlement": "REALTIME",
                "complete": True,
            }
            | kwargs
        )
    )


def event(at=AT, **kwargs):
    return Event(
        **(
            {
                "source": "fixture",
                "source_version": "fixture-v1",
                "event_id": "decision",
                "revision": "1",
                "category": "macro.policy_decision",
                "title": "Test release",
                "scope": "MARKET",
                "source_at": at - timedelta(days=1),
                "received_at": at - timedelta(hours=1),
                "starts_at": at,
                "ends_at": at,
                "timezone": "America/New_York",
                "precision": "EXACT",
                "importance": "HIGH",
                "complete": True,
                "evidence_ref": "fixture:decision",
            }
            | kwargs
        )
    )


def snapshot(at=AT, **kwargs):
    cal = sessions(at.date(), (at + timedelta(days=3)).date(), received_at=at)
    return Snapshot(
        **(
            {
                "sequence": 1,
                "published_at": at,
                "policy_hash": fingerprint(P),
                "coverage": (
                    coverage(at=at),
                    coverage("company.earnings", at),
                    Coverage.model_validate(cal["coverage"][0]),
                ),
                "samples": tuple(sample(s, at) for s in ("AAPL", "SPY", "QQQ")),
                "sessions": cal["sessions"],
            }
            | kwargs
        )
    )


def reasons(a):
    return {f.reason for f in a.findings}


@pytest.mark.parametrize("family", ["DEGEN", "SWING", "SCOPE"])
def test_shared_clear_is_not_approval_and_never_enables_carry(family):
    a = assess(prepare(snapshot(), P), request(family=family))
    assert a.state == "CLEAR"
    assert not a.authority and not a.trade_approval and not a.live_enabled
    assert a.would_restrict_carry and a.mode == "OBSERVATION_ONLY"


@pytest.mark.parametrize(
    "offset,blocked", [(-901, False), (-900, True), (1799, True), (1800, False)]
)
def test_scheduled_window_half_open_boundaries_without_provider_refresh(offset, blocked):
    now = AT + timedelta(seconds=offset)
    s = snapshot(now, events=(event(),))
    a = assess(prepare(s, P), request(now))
    assert a.would_block_new_entries is blocked


def test_validity_ends_at_next_window_activation_and_calendar_not_quote_clock():
    now = AT - timedelta(seconds=905)
    s = snapshot(now, events=(event(),))
    a = assess(prepare(s, P), request(now))
    assert a.valid_until == AT - timedelta(seconds=900)
    assert "CALENDAR_STALE_OR_FUTURE" not in reasons(a)
    later = assess(prepare(s, P), request(AT - timedelta(seconds=890)))
    assert later.would_block_new_entries
    assert "QUOTE_STALE_OR_INVALID_CLOCK" in reasons(later)


def test_decision_and_press_conference_have_distinct_windows():
    press = event(
        event_id="press",
        category="macro.press_conference",
        starts_at=AT + timedelta(minutes=30),
        ends_at=AT + timedelta(minutes=30),
        evidence_ref="fixture:press",
    )
    now = AT + timedelta(minutes=35)
    a = assess(prepare(snapshot(now, events=(event(), press)), P), request(now))
    refs = {ref for f in a.findings if f.reason == "SCHEDULED_EVENT_WINDOW" for ref in f.evidence}
    assert refs == {"fixture:press"}


def test_symbol_uncertainty_does_not_become_market_restriction():
    s = snapshot(coverage=(coverage(), coverage("session.xnys")))
    a = assess(prepare(s, P), request())
    assert a.market_state == "CLEAR" and a.symbol_state == "UNKNOWN"
    assert not a.would_block_new_entries and a.would_restrict_exposure


@pytest.mark.parametrize("damage", ["missing", "partial", "stale", "short_horizon", "future"])
def test_missing_or_stale_calendar_is_not_clear(damage):
    c = coverage()
    if damage == "partial":
        c = changed(c, status="PARTIAL")
    if damage == "stale":
        c = changed(c, fresh_until=AT)
    if damage == "short_horizon":
        c = changed(c, ends_at=AT + timedelta(minutes=1))
    if damage == "future":
        c = changed(c, checked_at=AT + timedelta(seconds=1))
    s = snapshot(
        coverage=(() if damage == "missing" else (c,)),
        published_at=AT + timedelta(seconds=1) if damage == "future" else AT,
    )
    assert assess(prepare(s, P), request()).state == "UNKNOWN"


def test_cancelled_and_conflicting_sources_are_not_silently_cleared():
    cancel = changed(event(), status="CANCELLED")
    a = assess(prepare(snapshot(events=(cancel,)), P), request())
    assert a.state == "CLEAR"
    e = changed(event(), canonical_key="fomc-decision")
    other = changed(cancel, source="other", canonical_key="fomc-decision")
    a = assess(prepare(snapshot(events=(e, other)), P), request())
    assert a.would_block_new_entries and "CONFLICTING_EVENT_REVISIONS" in reasons(a)
    assert "CONFLICTING_EVENT_REVISIONS" not in reasons(
        assess(prepare(snapshot(events=(e, e)), P), request())
    )


@pytest.mark.parametrize(
    "updates,reason,state",
    [
        ({"bid_size": None}, "DISPLAYED_LIQUIDITY_MISSING", "UNKNOWN"),
        ({"ask_size": "0"}, "LOW_DISPLAYED_LIQUIDITY", "BLOCK_NEW_ENTRIES"),
        ({"ask": "102"}, "WIDE_SPREAD", "BLOCK_NEW_ENTRIES"),
        ({"ask": "100.6"}, "ELEVATED_SPREAD", "CAUTION"),
        ({"reference_price": "95"}, "RAPID_PRICE_CHANGE", "BLOCK_NEW_ENTRIES"),
        (
            {"reference_at": AT - timedelta(hours=1)},
            "PRICE_CHANGE_REFERENCE_MISSING_OR_STALE",
            "UNKNOWN",
        ),
        ({"source_at": AT - timedelta(seconds=11)}, "QUOTE_STALE_OR_INVALID_CLOCK", "UNKNOWN"),
        ({"entitlement": "UNKNOWN"}, "QUOTE_ENTITLEMENT_UNCONFIRMED", "UNKNOWN"),
        ({"bid": "101"}, "QUOTE_BOOK_UNUSABLE", "UNKNOWN"),
    ],
)
def test_stress_uses_available_original_evidence(updates, reason, state):
    s = snapshot(samples=(sample(**updates), sample("SPY"), sample("QQQ")))
    a = assess(prepare(s, P), request())
    assert a.state == state and reason in reasons(a)
    assert a.market_state == "CLEAR"


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2026, 11, 26, 16, tzinfo=UTC), "OUTSIDE_REGULAR_SESSION"),
        (datetime(2026, 11, 27, 17, 30, tzinfo=UTC), "SESSION_CLOSE_WINDOW"),
        (datetime(2026, 11, 27, 18, tzinfo=UTC), "OUTSIDE_REGULAR_SESSION"),
        (datetime(2026, 11, 2, 14, 31, tzinfo=UTC), "SESSION_OPEN_WINDOW"),
    ],
)
def test_holiday_early_close_and_dst_session_windows(now, expected):
    a = assess(prepare(snapshot(now), P), request(now))
    assert expected in reasons(a)


def test_holding_period_crosses_close_and_future_coverage():
    now = datetime(2026, 11, 27, 16, tzinfo=UTC)
    a = assess(prepare(snapshot(now), P), request(now, holding_until=now + timedelta(days=4)))
    assert {"HOLDING_PERIOD_NOT_COVERED", "HORIZON_CROSSES_SESSION_CLOSE"} <= reasons(a)
    assert a.would_restrict_carry


def test_empty_snapshot_policy_drift_naive_times_and_enforcement_rejected():
    assert assess(prepare(None, P), request()).state == "UNKNOWN"
    assert (
        assess(prepare(changed(snapshot(), policy_hash="wrong"), P), request()).state == "UNKNOWN"
    )
    with pytest.raises(ValueError):
        request(AT.replace(tzinfo=None))
    with pytest.raises(ValueError):
        Policy(mode="ENFORCE")
    with pytest.raises(ValueError):
        Policy(overnight_carry=True)


def test_dense_calendar_is_explicitly_incomplete_and_assessment_is_bounded():
    events = tuple(event(event_id=f"crowded-{i}") for i in range(1000))
    a = assess(prepare(snapshot(events=events), P), request())
    assert "ASSESSMENT_EVENT_CAPACITY" in reasons(a)
    assert len(a.findings) <= P.max_local_events + 1
    assert a.would_block_new_entries


def test_native_incomplete_quote_and_foreign_symbol_are_not_clear():
    for damaged, reason in (
        (sample(complete=False), "QUOTE_INCOMPLETE"),
        (sample(symbol="MSFT", instrument_id="aapl-id"), "QUOTE_SYMBOL_MISMATCH"),
    ):
        a = assess(prepare(snapshot(samples=(damaged, sample("SPY"), sample("QQQ"))), P), request())
        assert a.state == "UNKNOWN" and reason in reasons(a)


def test_decimal_context_cannot_change_assessment():
    from decimal import localcontext

    view, r = prepare(snapshot(), P), request()
    expected = assess(view, r)
    with localcontext() as ctx:
        ctx.prec = 2
        assert assess(view, r) == expected
