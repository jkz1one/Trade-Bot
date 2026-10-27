"""Synthetic earnings and retained native option evidence, never provider acceptance."""

import json
from datetime import timedelta

import pytest
from test_event_assessment import P, changed, coverage, event, request, snapshot
from test_option_admission import NOW, inputs
from test_option_greek_health import observed

from app.events.assessment import prepare
from app.events.models import Volatility
from app.events.observation import observation_payload
from app.events.option_volatility import (
    OptionVolatilityPolicy,
    prepare_option_volatility,
    review_option_volatility,
)
from app.events.store import EventStore
from app.options.engine import fingerprint


def quote():
    q = inputs()["quote"]
    original = q.instrument.contract
    contract = changed(
        original,
        underlying="AAPL",
        underlying_kind="EQUITY",
        expiration=original.expiration + timedelta(days=7),
        last_trading_at=original.last_trading_at + timedelta(days=7),
        expires_at=original.expires_at + timedelta(days=7),
        settles_at=original.settles_at + timedelta(days=7),
    )
    return observed(changed(q, instrument=changed(q.instrument, contract=contract)))


def req(**updates):
    return request(NOW, instrument_id=quote().instrument.instrument_id, **updates)


def earnings(**updates):
    return event(
        NOW, **({"category": "company.earnings", "scope": "SYMBOL", "symbols": ("AAPL",)} | updates)
    )


def snap(**updates):
    return snapshot(
        NOW,
        **(
            {"coverage": (coverage("company.earnings", NOW, ends_at=NOW + timedelta(days=8)),)}
            | updates
        ),
    )


def review(s=None, r=None, q=None, p=None):
    return review_option_volatility(
        prepare_option_volatility(prepare(s or snap(), P), p), r or req(), q or quote()
    )


def reasons(result):
    return {f["reason"] for f in result["findings"]}


@pytest.mark.parametrize("family", ["DEGEN", "SWING", "SCOPE"])
def test_clear_is_limited_evidence_not_crush_prediction(family):
    result = review(r=req(family=family))
    assert result["state"] == "CLEAR" and result["current_iv_decimal_fraction"] == "0.4"
    assert result["crush_forecast_state"] == "UNKNOWN"
    assert result["expected_iv_drop"] is result["expected_option_value_change"] is None
    assert not result["authority"] and not result["trade_approval"] and not result["live_enabled"]
    assert result["would_restrict_carry"] and not result["would_block_new_entries"]


@pytest.mark.parametrize(
    "offset,warning", [(-259201, False), (-259200, True), (86399, True), (86400, False)]
)
def test_exact_watch_boundaries_from_stored_times(offset, warning):
    at = NOW - timedelta(seconds=offset)
    # Receipt must precede the decision even for an event now in the future.
    e = earnings(starts_at=at, ends_at=at)
    result = review(snap(events=(e,)), req(holding_until=NOW))
    assert ("EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE" in reasons(result)) is warning


def test_clock_activates_without_another_snapshot_or_provider():
    e = earnings(
        starts_at=NOW + timedelta(days=3, seconds=5), ends_at=NOW + timedelta(days=3, seconds=5)
    )
    v = prepare_option_volatility(prepare(snap(events=(e,)), P))
    first = review_option_volatility(v, req(holding_until=NOW), quote())
    assert first["valid_until"] == (NOW + timedelta(seconds=5)).isoformat()
    later = review_option_volatility(
        v,
        req(evaluated_at=NOW + timedelta(seconds=5), holding_until=NOW + timedelta(seconds=5)),
        quote(),
    )
    assert "EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE" in reasons(later)


@pytest.mark.parametrize("damage", ["missing", "partial", "stale", "short", "conflict"])
def test_missing_earnings_watch_coverage_never_clear(damage):
    c = coverage("company.earnings", NOW, ends_at=NOW + timedelta(days=8))
    updates = {
        "partial": {"status": "PARTIAL"},
        "stale": {"fresh_until": NOW},
        "short": {"ends_at": NOW + timedelta(days=1)},
        "conflict": {"status": "CONFLICT"},
    }
    result = review(snap(coverage=() if damage == "missing" else (changed(c, **updates[damage]),)))
    assert result["state"] == "UNKNOWN" and "MISSING_COMPLETE_EARNINGS_COVERAGE" in reasons(result)


@pytest.mark.parametrize(
    "damage",
    ["missing", "stale", "estimated", "zero", "future", "source", "unsynced", "entitlement"],
)
def test_missing_or_unusable_iv_is_not_replaced_by_daily_vix(damage):
    q = quote()
    updates = {
        "stale": {"source_at": NOW - timedelta(seconds=10)},
        "estimated": {"provenance": "ESTIMATED"},
        "zero": {"implied_volatility": "0"},
        "future": {"received_at": NOW + timedelta(seconds=1)},
        "source": {"source": "other"},
        "unsynced": {
            "source_at": NOW - timedelta(seconds=3),
            "received_at": NOW - timedelta(seconds=3),
        },
        "entitlement": {"entitlement": "UNKNOWN"},
    }
    q = changed(q, greeks=None if damage == "missing" else changed(q.greeks, **updates[damage]))
    vix = Volatility(
        source="cboe",
        source_version="fixture",
        symbol="VIX",
        observed_date=(NOW - timedelta(days=1)).date(),
        value="30",
        received_at=NOW,
        evidence_ref="fixture:daily-vix",
    )
    result = review(snap(volatility=(vix,)), q=q)
    assert result["state"] == "UNKNOWN" and result["current_iv_decimal_fraction"] is None


def test_cancel_reschedule_duplicate_conflict_and_foreign_symbol():
    e = earnings(canonical_key="aapl-earnings")
    assert review(snap(events=(changed(e, status="CANCELLED"),)))["state"] == "CLEAR"
    assert (
        review(
            snap(
                events=(
                    changed(e, starts_at=NOW + timedelta(days=7), ends_at=NOW + timedelta(days=7)),
                )
            )
        )["state"]
        == "CLEAR"
    )
    assert "CONFLICTING_EARNINGS_REVISIONS" not in reasons(review(snap(events=(e, e))))
    conflict = changed(e, source="second", status="CANCELLED")
    result = review(snap(events=(e, conflict)))
    assert result["state"] == "UNKNOWN"
    assert {"CONFLICTING_EARNINGS_REVISIONS", "EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE"} <= reasons(
        result
    )
    assert review(snap(events=(changed(e, symbols=("MSFT",)),)))["state"] == "CLEAR"


def test_date_precision_uncertainty_and_future_holding_overlap():
    e = earnings(
        starts_at=NOW + timedelta(hours=3),
        ends_at=NOW + timedelta(days=1),
        precision="DATE",
        complete=False,
        source_at=None,
        status="TENTATIVE",
    )
    result = review(snap(events=(e,)), req(holding_until=NOW + timedelta(hours=4)))
    assert result["state"] == "UNKNOWN"
    assert {
        "EARNINGS_DETAILS_INCOMPLETE",
        "EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE",
        "EARNINGS_INTERVAL_OVERLAPS_HOLDING_PERIOD",
    } <= reasons(result)


def test_earnings_after_contract_expiry_is_not_crush_exposure_but_ambiguous_day_is():
    q = quote()
    original = inputs()["quote"].instrument.contract
    contract = changed(original, underlying="AAPL", underlying_kind="EQUITY")
    q = observed(changed(q, instrument=changed(q.instrument, contract=contract), greeks=None))
    later = contract.expires_at + timedelta(seconds=1)
    assert review(snap(events=(earnings(starts_at=later, ends_at=later),)), q=q)["state"] == "CLEAR"
    uncertain = earnings(
        starts_at=NOW, ends_at=NOW + timedelta(days=1), precision="DATE", complete=False
    )
    result = review(snap(events=(uncertain,)), q=q)
    assert result["state"] == "UNKNOWN"
    assert "EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE" in reasons(result)


def test_policy_is_versioned_bounded_observation_only_and_capacity_is_unknown():
    p = OptionVolatilityPolicy(max_events=1)
    s = snap(events=(earnings(), earnings(event_id="second")))
    result = review(s, p=p)
    assert result["policy_hash"] == fingerprint(p)
    assert "EARNINGS_ASSESSMENT_CAPACITY" in reasons(result)
    with pytest.raises(ValueError):
        OptionVolatilityPolicy(mode="ENFORCE")


def test_snapshot_future_policy_mismatch_and_quote_identity():
    for s in (snap(published_at=NOW + timedelta(seconds=1)), snap(policy_hash="wrong")):
        assert review(s)["state"] == "UNKNOWN"
    assert (
        review(
            q=changed(
                quote(), instrument=changed(quote().instrument, instrument_id="wrong"), greeks=None
            )
        )["state"]
        == "UNKNOWN"
    )
    view = prepare_option_volatility(prepare(None, P))
    assert review_option_volatility(view, req(), None)["state"] == "UNKNOWN"


def test_native_payload_retains_policy_quote_and_decision_without_changing_assessment(tmp_path):
    q, r = quote(), req()
    native = {
        "source_key": r.decision_id,
        "result_json": '{"status":"BLOCKED","reasons":["EXISTING_BLOCKER"]}',
    }
    native_event = {"occurred_at": NOW.isoformat(), "sequence": 1}
    evidence = (native, native_event, {"quote": q.model_dump(mode="json")}, {})
    store = EventStore(tmp_path / "events", r.population_id, P, create=True)
    store.retain({"events": [earnings().model_dump(mode="json")]})
    store.publish(now=NOW)
    before = json.dumps(evidence, sort_keys=True)
    payload, assessment = observation_payload(
        store, "OPTION", r, evidence, {}, recorded_at=NOW, context_origin="OFFLINE_FIXTURE"
    )
    assert json.dumps(evidence, sort_keys=True) == before
    assert payload["native_result"]["reasons"] == ["EXISTING_BLOCKER"]
    assert payload["assessment"] == assessment.model_dump(mode="json")
    diagnostic = payload["option_event_volatility"]
    assert diagnostic["decision_id"] == r.decision_id
    assert diagnostic["native_quote"] == q.model_dump(mode="json")
    assert diagnostic["policy_hash"] == fingerprint(diagnostic["policy"])
    assert "EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE" in reasons(diagnostic)
    store.observe(payload)
    restarted = EventStore(store.directory, r.population_id, P)
    assert restarted.export()["observations"][0]["option_event_volatility"] == diagnostic


def test_actual_native_option_decision_and_account_unchanged(tmp_path):
    from test_event_native import native_dump
    from test_option_execution import owned

    from app.events.observation import decision_evidence

    with owned(tmp_path / "owner") as (engine, _venue, data):
        outcome = engine.prepare(
            "real-option-decision", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        assert outcome["status"] == "PREPARED"
        before = native_dump(engine)
        with engine.journal.read() as db:
            evidence = decision_evidence(db, "OPTION", "real-option-decision")
        r = request(
            NOW,
            population_id=engine.limits.population_id,
            decision_id="real-option-decision",
            instrument_id=data["quote"].instrument.instrument_id,
            symbol="SPY",
            underlying_kind="ETF",
            holding_until=evidence[3]["exit_at"],
        )
        store = EventStore(tmp_path / "events", r.population_id, P, create=True)
        payload, _ = observation_payload(
            store,
            "OPTION",
            r,
            evidence,
            {},
            recorded_at=NOW,
            context_origin="ACTUAL_NATIVE_OFFLINE_FIXTURE",
        )
        store.observe(payload)
        assert payload["native_result"]["status"] == "PREPARED"
        assert payload["option_event_volatility"]["state"] == "UNKNOWN"
        assert "CONTRACT_IV_MISSING" in reasons(payload["option_event_volatility"])
        assert native_dump(engine) == before


def test_stock_native_payload_does_not_get_option_diagnostic(tmp_path):
    from test_event_native import published_fixture

    from app.events.observation import observe_decision

    _, settings, path, binding, requests, at = published_fixture(tmp_path)
    store = EventStore(tmp_path / "events", settings.limits.population_id, P, create=True)
    observe_decision(
        store, path, "PORTFOLIO", requests[0], recorded_at=at, snapshot_binding=binding
    )
    assert "option_event_volatility" not in store.export()["observations"][0]
