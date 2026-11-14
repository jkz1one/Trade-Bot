"""Exact observed Greek evidence, missing-data semantics and native stored replay."""

import asyncio
import json
import shutil
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from test_option_admission import NOW, inputs
from test_option_execution import enter, ledger, owned, quote_at
from test_option_market_tape import header_for

from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.greek_health import review_greek_pressure
from app.options.market_tape import TapeRecorder, load_tape
from app.options.models import OptionGreekObservation, OptionProposal, OptionQuote
from app.options.observer import OptionObserver

D = Decimal


def observed(quote, **changes):
    values = {
        "instrument": quote.instrument,
        "source": quote.source,
        "source_at": quote.source_at,
        "received_at": quote.received_at,
        "entitlement": "REALTIME",
        "complete": True,
        "provenance": "OBSERVED",
        "theta_unit": "USD_PER_SHARE_PER_DAY",
        "volatility_unit": "DECIMAL_FRACTION",
        "delta": D(".5") if quote.instrument.contract.right == "CALL" else D("-.5"),
        "theta": D("-.1"),
        "implied_volatility": D(".4"),
        **changes,
    }
    return OptionQuote.model_validate(
        quote.model_dump() | {"greeks": OptionGreekObservation(**values)}
    )


def review(entry, current, *, now=NOW, entry_at=NOW):
    return review_greek_pressure(entry, current, inputs()["limits"], entry_at=entry_at, now=now)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "ratio,warning,severe",
    [
        (".80000000001", False, False),
        (".8", True, False),
        (".65000000001", True, False),
        (".65", True, True),
        ("0", True, True),
    ],
)
def test_absolute_delta_boundaries_do_not_round_before_comparing(right, ratio, warning, severe):
    q = inputs(right)["quote"]
    entry = observed(q)
    current = observed(q, delta=entry.greeks.delta * D(ratio))
    r = review(entry, current)
    assert r["status"] == "READY", r
    assert r["signals"]["delta_warning"] is warning
    assert r["signals"]["delta_severe"] is severe
    assert not r["execution_authority"] and not r["live_enabled"]


@pytest.mark.parametrize(
    "ratio,warning,severe",
    [
        (".85000000001", False, False),
        (".85", True, False),
        (".75000000001", True, False),
        (".75", True, True),
        ("0", True, True),
    ],
)
def test_iv_contraction_exact_boundaries(ratio, warning, severe):
    q = inputs()["quote"]
    entry = observed(q)
    r = review(entry, observed(q, implied_volatility=D(".4") * D(ratio)))
    assert r["signals"]["iv_warning"] is warning
    assert r["signals"]["iv_severe"] is severe


@pytest.mark.parametrize(
    "theta,pressure", [("-.389999999999", False), ("-.39", True), (".39", True), ("0", False)]
)
def test_theta_uses_observed_bid_and_explicit_source_heuristic(theta, pressure):
    q = inputs()["quote"].model_copy(update={"bid": D(1), "ask": D("1.01")})
    r = review(observed(q), observed(q, theta=D(theta)))
    assert r["signals"]["theta_pressure"] is pressure
    assert D(r["reference_hourly_theta_pct"]) == (D(0) if theta == "0" else D(6))


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "estimated",
        "unavailable",
        "stale",
        "lag",
        "future",
        "unsynced",
        "source",
        "incomplete",
        "delayed",
        "missing_bid",
        "size",
        "crossed",
    ],
)
def test_bad_current_evidence_never_becomes_healthy_or_zero(fault):
    q = inputs()["quote"]
    entry, current = observed(q), observed(q)
    changes = {
        "estimated": {"provenance": "ESTIMATED"},
        "unavailable": {"provenance": "UNAVAILABLE"},
        "stale": {
            "source_at": NOW - timedelta(minutes=1),
            "received_at": NOW - timedelta(minutes=1),
        },
        "lag": {"source_at": NOW - timedelta(seconds=8)},
        "future": {
            "source_at": NOW + timedelta(seconds=1),
            "received_at": NOW + timedelta(seconds=1),
        },
        "unsynced": {
            "source_at": NOW - timedelta(seconds=4),
            "received_at": NOW - timedelta(seconds=4),
        },
        "source": {"source": "foreign"},
        "incomplete": {"complete": False},
        "delayed": {"entitlement": "DELAYED"},
    }
    if fault == "missing":
        current = q
    elif fault in changes:
        current = observed(q, **changes[fault])
    else:
        current = current.model_copy(
            update={"bid": None}
            if fault == "missing_bid"
            else {"bid_size": 0}
            if fault == "size"
            else {"ask": D(".9")}
        )
    r = review(entry, current)
    assert r["status"] == "INCOMPLETE", r
    assert r["reasons"]
    assert all(x is None for x in r["signals"].values())
    assert r["known_warning_count"] == 0


@pytest.mark.parametrize("field", ["delta", "implied_volatility", "theta"])
def test_individual_missing_greek_retains_other_valid_signals(field):
    q = inputs()["quote"]
    r = review(observed(q), observed(q, **{field: None}))
    assert r["status"] == "INCOMPLETE"
    key = {"delta": "delta_warning", "implied_volatility": "iv_warning", "theta": "theta_pressure"}[
        field
    ]
    assert r["signals"][key] is None
    assert sum(x is None for x in r["signals"].values()) == (1 if field == "theta" else 2)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("baseline", [False, True])
def test_wrong_signed_delta_does_not_hide_valid_theta_and_iv(right, baseline):
    q = inputs(right)["quote"]
    good = observed(q)
    bad = observed(q, delta=-good.greeks.delta)
    r = review(bad if baseline else good, good if baseline else bad)
    assert r["status"] == "INCOMPLETE"
    assert ("ENTRY" if baseline else "CURRENT") + "_DELTA_WRONG_SIGN" in r["reasons"]
    assert r["signals"]["delta_warning"] is None
    assert r["signals"]["theta_pressure"] is False


@pytest.mark.parametrize("field", ["delta", "implied_volatility"])
def test_zero_baseline_is_unknown_not_divided_or_replaced(field):
    q = inputs()["quote"]
    r = review(observed(q, **{field: D(0)}), observed(q))
    assert r["status"] == "INCOMPLETE"
    assert r["signals"]["delta_warning" if field == "delta" else "iv_warning"] is None


def test_entry_is_evaluated_at_original_approval_time_and_decimal_context_is_stable():
    entry = observed(inputs()["quote"])
    now = NOW + timedelta(hours=1)
    q = quote_at(inputs(), now)
    current = observed(q, delta=".325", implied_volatility=".3", theta="-.39")
    expected = review(entry, current, now=now)
    assert expected["status"] == "READY"
    with localcontext() as context:
        context.prec = 4
        assert review(entry, current, now=now) == expected
    assert review(entry, current, now=now + timedelta(minutes=1))["status"] == "INCOMPLETE"


def test_exact_instrument_and_unit_validation_and_optional_legacy_hash():
    q = inputs()["quote"]
    assert "greeks" not in q.model_dump()
    assert fingerprint(q) == fingerprint(OptionQuote.model_validate_json(q.model_dump_json()))
    with pytest.raises(ValueError, match="exact quoted instrument"):
        OptionQuote.model_validate(
            q.model_dump() | {"greeks": observed(inputs("PUT")["quote"]).greeks}
        )
    for field, bad in (
        ("theta_unit", "USD_PER_CONTRACT_PER_DAY"),
        ("volatility_unit", "PERCENT"),
        ("theta", 0.1),
        ("delta", True),
    ):
        with pytest.raises(ValueError):
            observed(q, **{field: bad})
    r = review(observed(q), observed(inputs("PUT")["quote"]))
    assert r["status"] == "INCOMPLETE" and "EXACT_ENTRY_INSTRUMENT_REQUIRED" in r["reasons"]
    assert all(x is None for x in r["signals"].values())


@pytest.mark.parametrize("fault", ["future", "source", "chronology"])
def test_tape_rejects_greeks_not_available_with_quote(tmp_path, fault):
    q = inputs()["quote"]
    changes = (
        {"received_at": NOW + timedelta(seconds=1)}
        if fault == "future"
        else {"source": "foreign"}
        if fault == "source"
        else {"source_at": NOW + timedelta(seconds=1)}
    )
    with (
        TapeRecorder(tmp_path / "bad.tape", header_for()) as recorder,
        pytest.raises(ValueError, match="Greek evidence"),
    ):
        recorder.append(
            DegenFrame(quotes=(observed(q, **changes),)), recorded_at=NOW, kind="MARKET"
        )


def test_seal_retains_greek_evidence_and_detects_tampering(tmp_path):
    q = observed(inputs()["quote"])
    path = tmp_path / "greeks.tape"
    with TapeRecorder(path, header_for()) as recorder:
        recorder.append(DegenFrame(quotes=(q,)), recorded_at=NOW, kind="MARKET")
        recorder.seal()
    assert load_tape(path).events[0].frame.quotes[0] == q
    text = path.read_text()
    assert '"theta": "-0.1"' in text or '"theta":"-0.1"' in text
    path.chmod(0o600)
    path.write_text(text.replace('"-0.1"', '"-0.2"'))
    with pytest.raises(ValueError):
        load_tape(path)


def test_native_observer_binds_original_quote_and_reads_detached_without_mutation(tmp_path):
    with owned(tmp_path) as (e, v, d):
        d["quote"] = observed(d["quote"])
        buy = enter(e, v, d)
        at = NOW + timedelta(seconds=1)
        q = observed(quote_at(d, at), delta=".325", implied_volatility=".3", theta="-.39")
        e.prepare(
            "stored-observation",
            OptionProposal(action="HOLD", thesis="Recorded fixture observation"),
            q,
            None,
            now=at,
        )
        before = ledger(e)
        path, population = e.journal.path, e.limits.population_id
        result = OptionObserver(path, population, clock=lambda: at).report()
        assert result["status"] == "OK", result
        pressure = result["position"]["greek_pressure"]
        assert pressure["status"] == "READY" and pressure["known_warning_count"] == 3
        assert pressure["entry_quote_hash"] == fingerprint(d["quote"])
        assert pressure["current_quote_hash"] == fingerprint(q)
        assert ledger(e) == before and v.submit_count == 1
        assert not result["network_calls"]
        entry_id = buy.client_id
    copy = tmp_path / "detached.db"
    shutil.copy2(path, copy)
    before = copy.read_bytes()
    assert (
        OptionObserver(copy, population, clock=lambda: at).report()["position"]["greek_pressure"]
        == pressure
    )
    assert copy.read_bytes() == before
    import sqlite3

    with sqlite3.connect(copy) as db:
        raw = json.loads(
            db.execute(
                "SELECT approval_json FROM execution_orders WHERE client_id=?", (entry_id,)
            ).fetchone()[0]
        )
        raw["quote"]["greeks"]["delta"] = ".6"
        db.execute(
            "UPDATE execution_orders SET approval_json=? WHERE client_id=?",
            (json.dumps(raw), entry_id),
        )
    assert OptionObserver(copy, population, clock=lambda: at).report()["status"] == "UNAVAILABLE"


def test_abcd_native_replay_exports_observed_greeks_and_every_model_charge(tmp_path, monkeypatch):
    import test_option_managed_replay as fixture

    from app.options.replay import run_replay

    for name in ("frame", "management_frame", "quote_at"):
        original = getattr(fixture, name)
        if name == "quote_at":
            wrapper = lambda *a, _fn=original, **kw: observed(_fn(*a, **kw))
        else:

            def wrapper(*a, _fn=original, **kw):
                f = _fn(*a, **kw)
                return f.model_copy(update={"quotes": tuple(observed(q) for q in f.quotes)})

        monkeypatch.setattr(fixture, name, wrapper)
    tape = fixture.managed_tape(tmp_path)
    result = asyncio.run(run_replay(fixture.managed_settings(tape), tape, tmp_path / "run"))
    rows = result["bundle"]["evidence"]
    assert {r["arm"] for r in rows} == set("ABCD")
    for row in rows:
        assert row["closing"]["position"] is None
        for order in row["orders"]:
            for fill in order["observation"]["fills"] if order["observation"] else ():
                assert fill["quote"]["greeks"]["provenance"] == "OBSERVED"
        buy = next(o for o in row["orders"] if o["intent"]["side"] == "BUY")
        outcome = OptionObserver(
            tmp_path / "run" / row["arm"] / "journal.db", "evaluation-" + row["arm"]
        ).position_outcome(buy["intent"]["client_id"])
        assert outcome["status"] == "COMPLETE"
        assert D(outcome["known_model_cost"]) == D(
            result["report"]["sessions"][0]["arms"][row["arm"]]["known_model_cost"]
        )
        if row["arm"] == "D":
            assert {call["role"] for call in outcome["model_calls"]} == {"ENTRY", "MANAGEMENT"}


@pytest.mark.parametrize("conflict", [False, True])
def test_stored_review_does_not_backfill_missing_baseline_or_choose_conflicting_current(
    tmp_path, conflict
):
    with owned(tmp_path) as (e, v, d):
        if conflict:
            d["quote"] = observed(d["quote"])
        enter(e, v, d)
        at = NOW + timedelta(seconds=1)
        q = observed(quote_at(d, at))
        hold = OptionProposal(action="HOLD", thesis="Stored Greek fixture")
        e.prepare("first-observation", hold, q, None, now=at)
        if conflict:
            e.prepare("conflicting-observation", hold, observed(q, delta=".25"), None, now=at)
        view = OptionObserver(e.journal.path, e.limits.population_id, clock=lambda: at).report()
        assert view["status"] == "OK", view
        pressure = view["position"]["greek_pressure"]
        assert pressure["status"] == "INCOMPLETE"
        assert ("CURRENT_QUOTE_CONFLICT" if conflict else "ENTRY_GREEKS_MISSING") in pressure[
            "reasons"
        ]
        assert pressure["signals"]["delta_warning"] is None
        assert pressure["signals"]["iv_warning"] is None
        assert v.submit_count == 1 and ledger(e).position.exit_reason is None


def test_quote_and_greek_age_boundaries_and_absent_entry_do_not_invent_baseline():
    q = observed(inputs()["quote"])
    assert review(q, q, now=NOW + timedelta(seconds=9))["status"] == "READY"
    r = review(q, q, now=NOW + timedelta(seconds=10))
    assert r["status"] == "INCOMPLETE" and "CURRENT_QUOTE_UNUSABLE" in r["reasons"]
    r = review(None, q)
    assert "ENTRY_QUOTE_MISSING" in r["reasons"] and r["signals"]["delta_warning"] is None
    with pytest.raises(ValueError, match="precede entry"):
        review(q, q, now=NOW - timedelta(seconds=1))
