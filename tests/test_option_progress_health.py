"""Durable risk geometry, sampled progress and conservative missing-data semantics."""

import asyncio
import json
import shutil
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from test_option_admission import NOW
from test_option_execution import enter, intent_for, ledger, owned, quote_at, underlying_at
from test_option_partial_close import fill, prepare

from app.options.engine import OptionExecution
from app.options.observer import OptionObserver
from app.options.progress_health import record, stored

D = Decimal


def read(e, entry, at=NOW):
    with e.journal.read() as db:
        return stored(db, entry.client_id, e.limits, at)


def observe(e, v, d, seconds=0, *, bid=".98", distance="0", missing=False):
    at = NOW + timedelta(seconds=seconds)
    direction = 1 if d["quote"].instrument.contract.right == "CALL" else -1
    original = d["underlying"].ask if direction == 1 else d["underlying"].bid
    mark = original + direction * D(distance)
    u = underlying_at(
        d,
        at,
        bid=mark if direction == 1 else mark - D(".01"),
        ask=mark + D(".01") if direction == 1 else mark,
    )
    q = quote_at(d, at, bid=D(bid), ask=D(bid) + D(".01"))
    assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
    e.assess(None if missing else q, u, now=at)
    return q, u, at


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_original_geometry_actual_fills_and_directional_progress(tmp_path, right):
    with owned(tmp_path, right) as (e, v, d):
        buy = enter(e, v, d)
        before = ledger(e)
        observe(e, v, d, distance=".8", bid="1.515")
        r = read(e, buy)
        b = r["state"]["baseline"]
        ref = d["underlying"].ask if right == "CALL" else d["underlying"].bid
        assert D(b["underlying_reference"]) == ref
        assert D(b["risk_distance"]) == abs(ref - buy.original_underlying_invalidation)
        assert b["entry_basis"] == "404.00" and b["entry_quantity"] == 4
        assert r["metrics"]["premium_return_pct"] == "50.000000"
        assert D(r["metrics"]["current_underlying_r"]) > 0
        assert r["status"] == "READY" and not r["execution_authority"]
        assert ledger(e) == before and v.submit_count == 1


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_exact_divergence_and_giveback_thresholds(tmp_path, right):
    with owned(tmp_path, right) as (e, v, d):
        buy = enter(e, v, d)
        observe(e, v, d)
        risk = D(read(e, buy)["state"]["baseline"]["risk_distance"])
        observe(e, v, d, 1, distance=risk * D(".75"), bid="1.515")
        q, u, at = observe(e, v, d, 2, distance=risk * D(".25"), bid=".9595")
        with localcontext() as ctx:
            ctx.prec = 6
            with e.journal.write() as db:
                record(e, db, ledger(e).position, q, u, at)
        r = read(e, buy, NOW + timedelta(seconds=2))
        assert r["signals"] == {
            "stalled": False,
            "premium_divergence": True,
            "premium_giveback": True,
            "underlying_giveback": True,
        }
        assert r["metrics"]["premium_return_pct"] == "-5.000000"
        assert r["metrics"]["underlying_giveback_r"] == "0.500000"
        observe(e, v, d, 3, distance=risk * D(".25000001"), bid=".959500000001")
        r = read(e, buy, NOW + timedelta(seconds=3))
        assert r["signals"]["premium_divergence"] is False
        assert r["signals"]["underlying_giveback"] is False


def test_stall_needs_twenty_minutes_observed_coverage_then_new_peak_resets(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        for seconds in range(0, 1201, 8):
            observe(e, v, d, seconds)
        r = read(e, buy, NOW + timedelta(minutes=20))
        assert r["signals"]["stalled"] is True
        assert r["metrics"]["coverage_seconds"] == 1200
        assert r["state"]["last_progress_at"] == NOW.isoformat()
        observe(e, v, d, 1208, bid=".99")
        r = read(e, buy, NOW + timedelta(seconds=1208))
        assert r["signals"]["stalled"] is False
        assert r["metrics"]["minutes_since_observed_progress"] == 0
        assert ledger(e).position.exit_reason is None


def test_gap_missing_quote_and_restart_do_not_invent_stall_or_reset_original_state(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        observe(e, v, d)
        initial = read(e, buy)["state"]
        observe(e, v, d, 1200)
        r = read(e, buy, NOW + timedelta(minutes=20))
        assert r["signals"]["stalled"] is None
        assert r["reasons"] == ["PROGRESS_COVERAGE_GAP"]
        assert r["state"]["last_progress_at"] == initial["last_progress_at"]
        observe(e, v, d, 1201, missing=True)
        r = read(e, buy, NOW + timedelta(seconds=1201))
        assert all(value is None for value in r["signals"].values())
        assert r["state"]["coverage_interrupted"]
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW + timedelta(seconds=1202)) as e:
        observe(e, v, d, 1202)
        r = read(e, buy, NOW + timedelta(seconds=1202))
        assert r["state"]["baseline"] == initial["baseline"]
        assert r["state"]["last_progress_at"] == initial["last_progress_at"]
        assert r["state"]["coverage_since"] == (NOW + timedelta(seconds=1202)).isoformat()
        assert r["signals"]["stalled"] is None


@pytest.mark.parametrize(
    "fault",
    ["stale", "future", "foreign", "size", "mapping", "crossed", "sync", "regression", "conflict"],
)
def test_unusable_or_conflicting_evidence_cannot_raise_peaks(tmp_path, fault):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        q, u, _ = observe(e, v, d, 1)
        original = read(e, buy, NOW + timedelta(seconds=1))["state"]
        at = NOW + timedelta(seconds=2)
        q = q.model_copy(update={"bid": D("3"), "ask": D("3.01")})
        if fault == "stale":
            q = q.model_copy(update={"source_at": NOW - timedelta(seconds=20)})
        elif fault == "future":
            q = q.model_copy(update={"source_at": at + timedelta(seconds=1)})
        elif fault == "foreign":
            q = q.model_copy(update={"source": "foreign"})
        elif fault == "size":
            q = q.model_copy(update={"bid_size": 1})
        elif fault == "mapping":
            q = q.model_copy(
                update={"instrument": q.instrument.model_copy(update={"instrument_id": "foreign"})}
            )
        elif fault == "crossed":
            q = q.model_copy(update={"ask": D("2")})
        elif fault == "sync":
            at = NOW + timedelta(seconds=5)
            q = q.model_copy(update={"source_at": at, "received_at": at})
        elif fault == "regression":
            q = q.model_copy(update={"source_at": NOW, "received_at": NOW})
        with e.journal.write() as db:
            r = record(e, db, ledger(e).position, q, u, at)
        assert r["status"] == "INCOMPLETE"
        assert r["state"]["peak_bid"] == original["peak_bid"]
        assert r["state"]["last_progress_at"] == original["last_progress_at"]
        assert all(v is None for v in r["signals"].values())


def test_duplicate_and_clock_regression_do_not_create_progress_events(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        q, u, at = observe(e, v, d, 1)
        original = read(e, buy, at)
        with e.journal.read() as db:
            count = db.execute(
                "SELECT count(*) FROM execution_events WHERE kind='OPTION_PROGRESS_OBSERVED'"
            ).fetchone()[0]
        with e.journal.write() as db:
            record(e, db, ledger(e).position, q, u, at)
            record(e, db, ledger(e).position, d["quote"], d["underlying"], NOW)
        assert read(e, buy, at) == original
        with e.journal.read() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM execution_events WHERE kind='OPTION_PROGRESS_OBSERVED'"
                ).fetchone()[0]
                == count
            )


def test_partial_entry_stays_unknown_until_complete(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d, quantity=1)
        observe(e, v, d)
        r = read(e, buy)
        assert r["state"] is None and r["reasons"] == ["ORIGINAL_ENTRY_INCOMPLETE"]
        v.fill(buy, 3, d["quote"], NOW, fill_id="rest")
        observe(e, v, d, 1)
        r = read(e, buy, NOW + timedelta(seconds=1))
        assert r["state"]["baseline"]["entry_quantity"] == 4
        assert D(r["state"]["baseline"]["entry_basis"]) == 404


def test_scale_retains_original_basis_peak_and_progress(tmp_path):
    with owned(tmp_path, partial_closes="whole-contract-v1") as (e, v, d):
        buy = enter(e, v, d)
        q, u, at = observe(e, v, d, 1, bid="1.515", distance=".8")
        before = read(e, buy, at)["state"]
        out = prepare(e, buy, d, 2, at=at, quote=q, underlying=u)
        sell = intent_for(e, out["client_id"])
        assert asyncio.run(e.dispatch(sell.client_id, q, u, now=at)) == "OPEN"
        fill(e, v, sell, q, at)
        observe(e, v, d, 2, bid="1.01")
        r = read(e, buy, NOW + timedelta(seconds=2))
        assert r["state"]["baseline"] == before["baseline"]
        assert r["state"]["peak_bid"] == before["peak_bid"]
        assert r["state"]["last_progress_at"] == before["last_progress_at"]
        assert r["metrics"]["premium_return_pct"] == "0.000000"
        assert ledger(e).position.quantity == 2 and ledger(e).fees_paid > D("3.60")


def test_atomic_audit_failure_rolls_back_progress_and_supervision(tmp_path, monkeypatch):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        observe(e, v, d)
        old = read(e, buy)
        before = ledger(e)
        event = e.journal.event

        def fail(db, at, kind, payload, client_id=None):
            if kind == "OPTION_PROGRESS_OBSERVED":
                raise RuntimeError("audit unavailable")
            return event(db, at, kind, payload, client_id)

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            observe(e, v, d, 1, bid="2")
        assert read(e, buy) == old and ledger(e) == before


def test_stored_observer_detached_staleness_and_legacy_table_compatibility(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        observe(e, v, d)
        path, population = e.journal.path, e.limits.population_id
        r = OptionObserver(path, population, clock=lambda: NOW).report()
        assert r["position"]["progress_health"] == read(e, buy)
    copy = tmp_path / "detached.db"
    shutil.copy2(path, copy)
    before = copy.read_bytes()
    r = OptionObserver(copy, population, clock=lambda: NOW + timedelta(minutes=30)).report()
    assert not r["position"]["progress_health"]["observations_fresh"]
    assert r["position"]["progress_health"]["stored_only"]
    assert copy.read_bytes() == before
    import sqlite3

    with sqlite3.connect(copy) as db:
        db.execute("DROP TABLE execution_option_progress")
    r = OptionObserver(copy, population, clock=lambda: NOW).report()
    assert r["status"] == "OK" and "progress_health" not in r["position"]


def test_changed_approved_geometry_cannot_replace_saved_baseline(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        observe(e, v, d)
        with e.journal.write() as db:
            row = db.execute(
                "SELECT approval_json FROM execution_orders WHERE client_id=?", (buy.client_id,)
            ).fetchone()
            approval = json.loads(row[0])
            approval["underlying"]["ask"] = "600.10"
            db.execute(
                "UPDATE execution_orders SET approval_json=? WHERE client_id=?",
                (json.dumps(approval), buy.client_id),
            )
        with pytest.raises(ValueError, match="original entry binding"):
            e.assess(d["quote"], d["underlying"], now=NOW)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_native_target_progress_is_retained_separately_from_actual_sales(tmp_path, right):
    from test_option_target_exits import POLICY, at_target, enter_targets

    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d)
        observe(e, v, d)
        at = NOW + timedelta(seconds=1)
        e.assess(quote_at(d, at), at_target(d, 1, at), now=at)
        r = read(e, buy, at)
        assert r["state"]["highest_target_stage"] == 1
        assert r["state"]["last_progress_at"] == at.isoformat()
        observe(e, v, d, 1202)
        r = read(e, buy, NOW + timedelta(seconds=1202))
        assert r["signals"]["stalled"] is False
        assert r["state"]["highest_target_stage"] == 1
        assert ledger(e).position.quantity == 4 and v.submit_count == 1


def test_stored_progress_requires_matching_audit_event(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        observe(e, v, d)
        with e.journal.write() as db:
            db.execute(
                "UPDATE execution_option_progress SET payload=json_set(payload,'$.state.peak_bid','999') WHERE entry_client_id=?",
                (buy.client_id,),
            )
        with pytest.raises(ValueError, match="audited entry binding"):
            read(e, buy)
        assert (
            OptionObserver(e.journal.path, e.limits.population_id, clock=lambda: NOW).report()[
                "status"
            ]
            == "UNAVAILABLE"
        )


def test_native_abcd_replay_keeps_independent_progress_and_all_model_costs(tmp_path, monkeypatch):
    from test_option_greek_health import (
        test_abcd_native_replay_exports_observed_greeks_and_every_model_charge,
    )

    test_abcd_native_replay_exports_observed_greeks_and_every_model_charge(tmp_path, monkeypatch)
    import sqlite3

    entries = set()
    for arm in "ABCD":
        with sqlite3.connect(tmp_path / "run" / arm / "journal.db") as db:
            rows = db.execute(
                "SELECT entry_client_id,payload FROM execution_option_progress"
            ).fetchall()
            assert rows
            for entry_id, raw in rows:
                assert entry_id not in entries
                entries.add(entry_id)
                r = stored(
                    db, entry_id, __import__("test_option_execution").configuration()[1], NOW
                )
                assert r["state"]["baseline"]["entry_client_id"] == entry_id
                assert json.loads(raw)["execution_authority"] is False
