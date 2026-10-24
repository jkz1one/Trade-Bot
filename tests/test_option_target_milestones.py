"""Target protection progresses without manufacturing a sale or changing allocation."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import configuration, intent_for, ledger, owned, quote_at
from test_option_partial_close import close, fill
from test_option_position_outcome import read_owned
from test_option_target_exits import at_target, enter_targets, schedule, tick
from test_option_target_stops import ENROLLED, price

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.lifecycle import TargetExitSchedule, TargetExitStep

D = Decimal
VERSION = "frozen-target-milestones-v2"
POLICY = {**ENROLLED, "target_exits": VERSION}


def milestones(right="CALL", quantity=1, *, all_stops=False):
    sign = 1 if right == "CALL" else -1
    return TargetExitSchedule(
        version=VERSION,
        entry_quantity=quantity,
        steps=(
            TargetExitStep(underlying_price=600 + sign * 2, quantity=0, tighten_underlying_to=600),
            TargetExitStep(
                underlying_price=600 + sign * 4,
                quantity=0 if all_stops else quantity,
                tighten_underlying_to=600 + sign * 2,
            ),
        ),
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_one_contract_tightens_without_sale_then_exits_at_second_target(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d, plan=milestones(right))
        before = ledger(e)
        for _ in range(2):
            assert tick(e, d)["status"] == "HEALTHY"
            current = ledger(e)
            assert current.position.quantity == 1 and current.position.target_exit_stage == 1
            assert current.position.tightened_underlying_invalidation == D(600)
            assert current.cash == before.cash and current.fees_paid == before.fees_paid
            assert v.submit_count == 1
        with e.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 1
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            assert order_attribution(db, row)["target_exit_schedule"] == milestones(
                right
            ).model_dump(mode="json")
        assert read_owned(e, buy)["status"] == "INCOMPLETE"
        out = tick(e, d, stage=2)
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 1 and sell.target_exit_stage == 2
        fill(e, v, sell, d["quote"])
        outcome = read_owned(e, buy)
        assert outcome["status"] == "COMPLETE"
        assert D(outcome["execution_fees"]) == D("3.30")
        assert D(outcome["net_after_known_execution_and_model_costs"]) == D("-7.30")
        assert v.submit_count == 2 and ledger(e).position is None


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_stop_only_runner_survives_restart_then_rebound_exits_actual_holdings(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d, plan=milestones(right, 2, all_stops=True))
        assert tick(e, d, stage=2)["status"] == "HEALTHY"
        saved = ledger(e)
        assert saved.position.quantity == 2 and saved.position.target_exit_stage == 2
        assert v.submit_count == 1
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        assert ledger(e) == saved
        stop = 602 if right == "CALL" else 598
        out = tick(e, d, u=price(d, stop))
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 2 and sell.target_exit_stage is None
        fill(e, v, sell, d["quote"])
        assert read_owned(e, buy)["status"] == "COMPLETE"
        assert v.submit_count == 2


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_gap_requests_only_cumulative_sales_and_never_repeats_after_fill(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        p = milestones(right, 3)
        p = p.model_copy(
            update={"steps": (p.steps[0], p.steps[1].model_copy(update={"quantity": 2}))}
        )
        enter_targets(e, v, d, plan=p)
        out = tick(e, d, stage=2)
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 2
        assert tick(e, d, stage=2)["status"] == "TARGET_EXIT_BLOCKED"
        fill(e, v, sell, d["quote"])
        assert tick(e, d, stage=2)["status"] == "HEALTHY"
        assert ledger(e).position.quantity == 1 and v.submit_count == 2


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_unavailable_option_latches_milestone_then_recovery_applies_stop_before_sale(
    tmp_path, right
):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        enter_targets(e, v, d, plan=milestones(right))
        stale = quote_at(d, NOW - timedelta(minutes=1))
        original = ledger(e).position.tightened_underlying_invalidation
        assert e.assess(stale, at_target(d), now=NOW)["status"] == "BLOCKED"
        assert ledger(e).position.target_exit_stage == 1
        assert ledger(e).position.tightened_underlying_invalidation == original
        out = tick(e, d, u=price(d, 600))
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert intent_for(e, out["client_id"]).quantity == 1
        assert v.submit_count == 2


def test_zero_allocation_cannot_be_used_to_request_a_sale(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d, plan=milestones())
        assert tick(e, d)["status"] == "HEALTHY"
        out = e.prepare(
            "invent-sale", close(buy, 1), d["quote"], at_target(d), now=NOW, target_exit_stage=1
        )
        assert out["status"] == "REJECTED" and out["reason"] == "OPTION_TARGET_QUANTITY_CHANGED"
        assert ledger(e).position.quantity == 1 and v.submit_count == 1


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_terminal_partial_entry_retains_stop_but_never_resizes_allocation(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d, plan=milestones(right, 3), quantity=1)
        v.record_terminal(buy.client_id, "CANCELED", NOW)
        assert tick(e, d)["reason"] == "OPTION_TARGET_COMPLETE_ENTRY_REQUIRED"
        assert ledger(e).position.tightened_underlying_invalidation == D(600)
        out = tick(e, d, u=price(d, 600))
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert intent_for(e, out["client_id"]).quantity == 1


def test_enrollment_is_required_and_old_cohort_cannot_upgrade(tmp_path):
    with pytest.raises(ValidationError, match="require frozen target stops"):
        configuration(partial_closes="whole-contract-v1", target_exits=VERSION)
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = e.prepare(
            "v2",
            d["proposal"],
            d["quote"],
            d["underlying"],
            now=NOW,
            target_exit_schedule=milestones(quantity=4),
        )
        assert out["status"] == "REJECTED" and out["reason"] == "OPTION_TARGET_VERSION_NOT_ENROLLED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(
            path, limits, policy.model_copy(update={"target_exits": VERSION}), v, now=NOW
        ),
    ):
        pass


def test_dispatch_rechecks_schedule_version_even_if_intent_and_approval_agree(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = e.prepare(
            "old",
            d["proposal"],
            d["quote"],
            d["underlying"],
            now=NOW,
            target_exit_schedule=schedule(),
        )
        assert out["status"] == "PREPARED"
        with e.journal.write() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            intent, approval = json.loads(row["intent_json"]), json.loads(row["approval_json"])
            for record in (intent, approval):
                record["target_exit_schedule"] = milestones(quantity=4).model_dump(mode="json")
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=? WHERE client_id=?",
                (json.dumps(intent), json.dumps(approval), out["client_id"]),
            )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            assert row["attempted_at"] is None
            rejected = db.execute(
                "SELECT payload FROM execution_events WHERE kind='OPTION_DISPATCH_REJECTED' "
                "AND client_id=?",
                (out["client_id"],),
            ).fetchone()
            assert json.loads(rejected[0])["reason"] == "OPTION_TARGET_VERSION_NOT_ENROLLED"
        assert v.submit_count == 0


def test_legacy_encoding_and_noop_negative_or_fractional_steps_stay_invalid():
    p = schedule()
    assert p.version == "frozen-targets-v1"
    assert "tighten_underlying_to" not in p.model_dump()["steps"][0]
    with pytest.raises(ValidationError, match="v2 schedule"):
        TargetExitSchedule.model_validate(
            {**milestones().model_dump(), "version": "frozen-targets-v1"}
        )
    for quantity in (-1, True, "0", D(".5")):
        with pytest.raises(ValidationError):
            TargetExitStep(underlying_price=602, quantity=quantity, tighten_underlying_to=600)
    with pytest.raises(ValidationError, match="explicit tighter stop"):
        TargetExitStep(underlying_price=602, quantity=0)


def test_later_stop_only_stage_does_not_repeat_an_earlier_scale(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        p = milestones(quantity=2, all_stops=True)
        p = p.model_copy(
            update={"steps": (p.steps[0].model_copy(update={"quantity": 1}), p.steps[1])}
        )
        enter_targets(e, v, d, plan=p)
        out = tick(e, d)
        fill(e, v, intent_for(e, out["client_id"]), d["quote"])
        assert tick(e, d, stage=2)["status"] == "HEALTHY"
        assert ledger(e).position.quantity == 1
        assert ledger(e).position.tightened_underlying_invalidation == D(602)
        assert v.submit_count == 2


def test_stop_only_milestone_activates_cost_floor_without_claiming_proceeds(tmp_path):
    from test_option_premium_trail import quote
    from test_option_trade_floor import read

    with owned(tmp_path, **POLICY, trade_floor="native-target-floor-v1") as (e, v, d):
        buy = enter_targets(e, v, d, plan=milestones())
        assert tick(e, d, q=quote(d, "2"))["status"] == "HEALTHY"
        state = ledger(e).position.trade_floor
        assert state.reference_stage == 1 and state.minimum_exit_fill_price == D("1.05")
        evidence = read(e, buy)
        assert evidence["evidence"]["exit_quantity"] == 0
        assert D(evidence["evidence"]["exit_premium"]) == 0
        assert evidence["remaining_quantity"] == 1 and v.submit_count == 1
        out = tick(e, d, q=quote(d, "1.06"))
        assert out["exit_reason"] == "WHOLE_TRADE_FLOOR"
        assert intent_for(e, out["client_id"]).quantity == 1


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_stop_only_progress_survives_native_export_and_portable_accounting(
    tmp_path, monkeypatch, right
):
    import test_option_target_export as export

    from app.options.evaluation import evaluate

    monkeypatch.setattr(export, "POLICY", {**POLICY, "premium_trail": "executable-premium-v1"})
    monkeypatch.setattr(export, "plan", lambda direction: milestones(direction, 4))
    row, bundle = export.exported(
        export.native_boundary(tmp_path, right, sold=0), data_cost=".01", host_cost=".02"
    )
    assert row.closing.position.target_exit_schedule == milestones(right, 4)
    assert row.closing.position.quantity == 4 and row.closing.position.target_exit_stage == 1
    result = evaluate(bundle)["sessions"][0]["arms"]["A"]
    assert result["accounting_verified"], result
    assert result["net_change"] is None and result["status"] == "INCONCLUSIVE"
    assert D(result["venue_fees"]) == D("3.60")
    assert result["allocated_data_cost"] == "0.01" and result["allocated_host_cost"] == "0.02"


def test_milestone_write_failure_rolls_back_and_independent_owner_stays_unchanged(
    tmp_path, monkeypatch
):
    with (
        owned(tmp_path / "a", **POLICY) as (a, av, ad),
        owned(tmp_path / "b", **POLICY) as (b, bv, bd),
    ):
        enter_targets(a, av, ad, plan=milestones())
        enter_targets(b, bv, bd, plan=milestones())
        before_a, before_b = ledger(a), ledger(b)
        with monkeypatch.context() as patch:

            def fail(*args, **kwargs):
                raise RuntimeError("audit unavailable")

            patch.setattr(a.journal, "event", fail)
            with pytest.raises(RuntimeError, match="audit unavailable"):
                a.assess(ad["quote"], at_target(ad), now=NOW)
        assert ledger(a) == before_a and ledger(b) == before_b
        assert tick(a, ad)["status"] == "HEALTHY"
        assert ledger(a).position.target_exit_stage == 1
        assert ledger(b) == before_b and av.submit_count == bv.submit_count == 1
