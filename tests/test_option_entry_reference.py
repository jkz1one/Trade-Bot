"""Native entry-reference stops bind complete fills, not setup or approval prices."""

import asyncio
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import configuration, intent_for, ledger, owned, quote_at, underlying_at
from test_option_partial_close import close, fill
from test_option_position_outcome import read_owned
from test_option_target_exits import at_target, tick
from test_option_target_milestones import POLICY as MILESTONES
from test_option_target_stops import price

from app.options.engine import OptionExecution
from app.options.entry_reference import review_reference, stored_reference
from app.options.lifecycle import TargetExitSchedule, TargetExitStep
from app.options.observer import OptionObserver

D = Decimal
VERSION = "fill-weighted-underlying-v1"
POLICY = {**MILESTONES, "target_entry_reference": VERSION}


def plan(right="CALL", quantity=3):
    sign = 1 if right == "CALL" else -1
    first, second = {1: (0, 1), 2: (1, 0), 3: (1, 1), 4: (2, 1)}[quantity]
    return TargetExitSchedule(
        version="frozen-target-milestones-v2",
        entry_quantity=quantity,
        steps=(
            TargetExitStep(
                underlying_price=600 + sign * 2, quantity=first, tighten_to_entry=VERSION
            ),
            TargetExitStep(
                underlying_price=600 + sign * 4,
                quantity=second,
                tighten_underlying_to=600 + sign * 2,
            ),
        ),
    )


def prepare(e, d, quantity=3):
    q = quote_at(d, ask_size=quantity)
    out = e.prepare(
        "entry",
        d["proposal"],
        q,
        d["underlying"],
        now=NOW,
        target_exit_schedule=plan(d["proposal"].contract.right, quantity),
    )
    assert out["status"] == "PREPARED", out
    buy = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch(buy.client_id, q, d["underlying"], now=NOW)) == "OPEN"
    return buy


def entry_fill(e, v, d, buy, quantity, second, offset=".5", *, missing=False):
    at = NOW + timedelta(seconds=second)
    sign = 1 if buy.instrument.contract.right == "CALL" else -1
    reference = D(600) + sign * D(offset)
    u = underlying_at(
        d,
        at,
        bid=reference - (D(".1") if sign == 1 else 0),
        ask=reference + (D(".1") if sign == -1 else 0),
    )
    receipt = v.fill(
        buy,
        quantity,
        quote_at(d, at),
        at,
        fill_id="entry-" + str(second),
        underlying=None if missing else u,
    )
    assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
    return receipt


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("quantity", [1, 2, 3])
def test_entry_stop_then_next_target_preserve_allocation_costs_and_restart(
    tmp_path, right, quantity
):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = prepare(e, d, quantity)
        entry_fill(e, v, d, buy, quantity, 1)
        original = ledger(e)
        at = NOW + timedelta(seconds=2)
        out = tick(e, d, at=at)
        reference = D("600.5") if right == "CALL" else D("599.5")
        p = ledger(e).position
        assert p.tightened_underlying_invalidation == reference
        assert p.target_exit_stage == 1
        if quantity == 1:
            assert out["status"] == "HEALTHY" and v.submit_count == 1
            assert ledger(e).cash == original.cash
        else:
            assert out["status"] == "OPEN", out
            sell = intent_for(e, out["client_id"])
            assert sell.quantity == 1
            fill(e, v, sell, quote_at(d, at), at)
        saved_reference = ledger(e).position.entry_underlying_reference
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=at) as e:
        assert ledger(e).position.entry_underlying_reference == saved_reference
        at += timedelta(seconds=1)
        out = tick(e, d, stage=2, at=at)
        if quantity == 2:
            assert out["status"] == "HEALTHY" and v.submit_count == 2
        else:
            assert out["status"] == "OPEN", out
            sell = intent_for(e, out["client_id"])
            assert sell.quantity == 1
            fill(e, v, sell, quote_at(d, at), at)
        if quantity > 1:
            stop = D(602 if right == "CALL" else 598)
            assert ledger(e).position.tightened_underlying_invalidation == stop
            assert ledger(e).position.entry_underlying_reference == saved_reference
            at += timedelta(seconds=1)
            out = tick(e, d, u=price(d, stop, at), at=at)
            assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
            sell = intent_for(e, out["client_id"])
            assert sell.quantity == 1
            fill(e, v, sell, quote_at(d, at), at)
        outcome = read_owned(e, buy)
        assert outcome["status"] == "COMPLETE"
        assert D(outcome["execution_fees"]) == {1: D("3.30"), 2: D("5.60"), 3: D("7.90")}[quantity]
        assert ledger(e).position is None


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_partial_fills_use_quantity_weighting_and_latched_target_rebounds(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = prepare(e, d)
        first = entry_fill(e, v, d, buy, 1, 1, "1")
        at = NOW + timedelta(seconds=1)
        e.assess(quote_at(d, at), at_target(d, at=at), now=at)
        p = ledger(e).position
        assert p.target_exit_stage == 1
        assert review_reference(p)["reasons"] == ["ENTRY_FILL_INCOMPLETE"]
        assert p.tightened_underlying_invalidation == buy.original_underlying_invalidation
        with e.journal.read() as db:
            assert not e._control(db)["halted"]
        second = entry_fill(e, v, d, buy, 2, 2, ".25")
        reference = D("600.5") if right == "CALL" else D("599.5")
        with localcontext() as ctx:
            ctx.prec = 3
            result = review_reference(ledger(e).position)
        assert D(result["reference"]) == reference
        assert result["observed_quantity"] == 3
        assert len(ledger(e).position.entry_underlying_reference.samples) == 2
        at += timedelta(seconds=2)
        out = tick(e, d, u=price(d, reference, at), at=at)
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert intent_for(e, out["client_id"]).quantity == 3
        assert v.submit_count == 2
        assert first.underlying != second.underlying


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_fractional_reference_rounds_toward_tighter_stop_at_fixed_precision(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = prepare(e, d)
        entry_fill(e, v, d, buy, 1, 1, "1")
        entry_fill(e, v, d, buy, 2, 2, "0")
        expected = D("600.333333333334" if right == "CALL" else "599.666666666666")
        assert D(review_reference(ledger(e).position)["reference"]) == expected
        at = NOW + timedelta(seconds=3)
        e.assess(quote_at(d, at), at_target(d, at=at), now=at)
        assert ledger(e).position.tightened_underlying_invalidation == expected


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("fault", ["missing", "original_stop", "first_target", "partial_terminal"])
def test_unusable_entry_reference_blocks_scales_without_suppressing_original_exit(
    tmp_path, right, fault
):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = prepare(e, d)
        if fault == "partial_terminal":
            entry_fill(e, v, d, buy, 2, 1)
            v.record_terminal(buy.client_id, "CANCELED", NOW + timedelta(seconds=1))
            assert e.reconcile(
                v.snapshot(NOW + timedelta(seconds=1)), now=NOW + timedelta(seconds=1)
            )["reconciled"]
        else:
            offset = "2" if fault == "first_target" else ".5"
            if fault == "original_stop":
                offset = str(
                    (buy.original_underlying_invalidation - D(600)) * (1 if right == "CALL" else -1)
                )
            entry_fill(e, v, d, buy, 3, 1, offset, missing=fault == "missing")
        at = NOW + timedelta(seconds=2)
        out = tick(e, d, at=at)
        assert out["status"] == "TARGET_EXIT_BLOCKED", out
        assert out["reason"] == "OPTION_TARGET_ENTRY_REFERENCE_REQUIRED"
        p = ledger(e).position
        assert p.tightened_underlying_invalidation == buy.original_underlying_invalidation
        out = e.prepare("scale", close(buy, 1), quote_at(d, at), at_target(d, at=at), now=at)
        assert (
            out["status"] == "REJECTED"
            and out["reason"] == "OPTION_TARGET_ENTRY_REFERENCE_REQUIRED"
        )
        with e.journal.read() as db:
            assert not e._control(db)["halted"]
        at += timedelta(seconds=1)
        out = tick(e, d, at=at, u=price(d, buy.original_underlying_invalidation, at))
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert intent_for(e, out["client_id"]).quantity == p.quantity


def test_legacy_cohort_cannot_adopt_reference_at_prepare_or_reopen(tmp_path):
    with pytest.raises(ValidationError, match="v2 milestones"):
        configuration(target_entry_reference=VERSION)
    with owned(tmp_path, **MILESTONES) as (e, v, d):
        out = e.prepare(
            "new",
            d["proposal"],
            quote_at(d, ask_size=3),
            d["underlying"],
            now=NOW,
            target_exit_schedule=plan(),
        )
        assert out["reason"] == "OPTION_TARGET_ENTRY_REFERENCE_NOT_ENROLLED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(
            path, limits, policy.model_copy(update={"target_entry_reference": VERSION}), v, now=NOW
        ),
    ):
        pass


def test_reference_is_first_only_and_cannot_coexist_with_a_fixed_stop():
    p = plan()
    with pytest.raises(ValidationError, match="fixed price"):
        TargetExitStep(
            underlying_price=602, quantity=0, tighten_to_entry=VERSION, tighten_underlying_to=600
        )
    for changes in ({"version": "frozen-targets-v1"}, {"steps": (p.steps[1], p.steps[0])}):
        with pytest.raises(ValidationError, match="first v2"):
            TargetExitSchedule.model_validate(p.model_dump() | changes)
    for right in ("CALL", "PUT"):
        p = plan(right)
        bad = p.model_copy(
            update={
                "steps": (
                    p.steps[0],
                    p.steps[1].model_copy(update={"tighten_underlying_to": D(600)}),
                )
            }
        )
        with pytest.raises(ValueError, match="tighten strictly"):
            bad.check_stops(right, D(599 if right == "CALL" else 601))


def test_readonly_reference_verifies_fill_hashes_and_reconciliation_rejects_forged_basis(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = prepare(e, d)
        entry_fill(e, v, d, buy, 3, 1)
        at = NOW + timedelta(seconds=2)
        before = e.journal.path.read_bytes()
        report = OptionObserver(e.journal.path, e.limits.population_id, clock=lambda: at).report()
        assert report["status"] == "OK", report
        assert report["position"]["entry_underlying_reference"]["reference"] == "600.5"
        assert e.journal.path.read_bytes() == before
        p = ledger(e).position
        state = p.entry_underlying_reference
        bad = state.model_copy(
            update={"samples": (state.samples[0].model_copy(update={"reference": D("600.9")}),)}
        )
        with e.journal.read() as db, pytest.raises(ValueError, match="BASIS_CHANGED"):
            stored_reference(db, p.model_copy(update={"entry_underlying_reference": bad}), e.limits)
        snap = v.snapshot(at)
        result = e.reconcile(
            snap.model_copy(
                update={
                    "position": snap.position.model_copy(update={"entry_underlying_reference": bad})
                }
            ),
            now=at,
        )
        assert result["issues"] == ["OPTION_POSITION_TERMS_MISMATCH"]
        assert ledger(e).position == p


def test_stop_update_rolls_back_and_other_owner_reference_is_independent(tmp_path, monkeypatch):
    with (
        owned(tmp_path / "a", **POLICY) as (a, av, ad),
        owned(tmp_path / "b", **POLICY) as (b, bv, bd),
    ):
        ai, bi = prepare(a, ad), prepare(b, bd)
        entry_fill(a, av, ad, ai, 3, 1, ".25")
        entry_fill(b, bv, bd, bi, 3, 1, ".75")
        before_a, before_b = ledger(a), ledger(b)
        at = NOW + timedelta(seconds=2)
        with monkeypatch.context() as patch:

            def fail(*args, **kwargs):
                raise RuntimeError("audit unavailable")

            patch.setattr(a.journal, "event", fail)
            with pytest.raises(RuntimeError, match="audit unavailable"):
                a.assess(quote_at(ad, at), at_target(ad, at=at), now=at)
        assert ledger(a) == before_a and ledger(b) == before_b
        a.assess(quote_at(ad, at), at_target(ad, at=at), now=at)
        assert ledger(a).position.tightened_underlying_invalidation == D("600.25")
        assert ledger(b) == before_b


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("sold", [0, 2])
def test_native_export_replays_original_reference_through_open_runner(
    tmp_path, monkeypatch, right, sold
):
    import test_option_target_export as export

    from app.options.evaluation import evaluate

    monkeypatch.setattr(export, "POLICY", {**POLICY, "premium_trail": "executable-premium-v1"})
    monkeypatch.setattr(export, "plan", lambda direction: plan(direction, 4))
    row, bundle = export.exported(
        export.native_boundary(tmp_path, right, sold=sold, observed_entry=True),
        data_cost=".01",
        host_cost=".02",
    )
    p = row.closing.position
    assert p.quantity == 4 - sold
    assert p.entry_underlying_reference.entry_quantity == 4
    assert review_reference(p)["status"] == "READY"
    result = evaluate(bundle)["sessions"][0]["arms"]["A"]
    assert result["accounting_verified"], result
    assert result["net_change"] is None
    state = p.entry_underlying_reference
    changed = state.model_copy(
        update={"samples": (state.samples[0].model_copy(update={"reference": D("600.5")}),)}
    )
    rows = list(bundle.evidence)
    rows[0] = row.model_copy(
        update={
            "closing": row.closing.model_copy(
                update={"position": p.model_copy(update={"entry_underlying_reference": changed})}
            )
        }
    )
    result = evaluate(bundle.model_copy(update={"evidence": tuple(rows)}))["sessions"][0]["arms"][
        "A"
    ]
    assert not result["accounting_verified"]
    assert "CASH_OR_OWNERSHIP_REPLAY_MISMATCH" in result["reasons"]


def test_dispatch_rechecks_reference_enrollment_before_any_attempt(tmp_path):
    import json

    from test_option_target_milestones import milestones

    with owned(tmp_path, **MILESTONES) as (e, v, d):
        out = e.prepare(
            "old",
            d["proposal"],
            quote_at(d, ask_size=3),
            d["underlying"],
            now=NOW,
            target_exit_schedule=milestones(quantity=3),
        )
        assert out["status"] == "PREPARED"
        with e.journal.write() as db:
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            intent, approval = json.loads(row["intent_json"]), json.loads(row["approval_json"])
            for obj in (intent, approval):
                obj["target_exit_schedule"] = plan().model_dump(mode="json")
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=?",
                (json.dumps(intent), json.dumps(approval)),
            )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        with e.journal.read() as db:
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            assert row["attempted_at"] is None
            event = db.execute(
                "SELECT payload FROM execution_events WHERE kind='OPTION_DISPATCH_REJECTED'"
            ).fetchone()
            assert json.loads(event[0])["reason"] == "OPTION_TARGET_ENTRY_REFERENCE_NOT_ENROLLED"
        assert v.submit_count == 0


@pytest.mark.parametrize("missing", [False, True])
def test_independent_cost_floor_protects_even_when_entry_reference_is_missing(tmp_path, missing):
    from test_option_premium_trail import quote

    with owned(tmp_path, **POLICY, trade_floor="native-target-floor-v1") as (e, v, d):
        buy = prepare(e, d, 1)
        entry_fill(e, v, d, buy, 1, 1, missing=missing)
        at = NOW + timedelta(seconds=2)
        rich = quote(d, "2").model_copy(update={"source_at": at, "received_at": at})
        out = tick(e, d, q=rich, at=at)
        assert out["status"] == ("TARGET_EXIT_BLOCKED" if missing else "HEALTHY"), out
        assert ledger(e).position.trade_floor.minimum_exit_fill_price == D("1.05")
        assert ledger(e).position.quantity == 1 and v.submit_count == 1
        at += timedelta(seconds=1)
        rebound = quote(d, "1.06").model_copy(update={"source_at": at, "received_at": at})
        out = tick(e, d, q=rebound, at=at)
        assert out["exit_reason"] == "WHOLE_TRADE_FLOOR", out
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 1
        fill(e, v, sell, rebound, at)
        assert read_owned(e, buy)["status"] == "COMPLETE"
