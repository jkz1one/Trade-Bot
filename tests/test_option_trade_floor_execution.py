"""Enrolled whole-trade floors: native costs, monotone state and executable protection."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_admission import NOW
from test_option_execution import configuration, enter, intent_for, ledger, owned
from test_option_partial_close import fill, prepare
from test_option_premium_trail import quote
from test_option_target_exits import POLICY, at_target, enter_targets, schedule, tick
from test_option_trade_floor import read

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.evaluation import _economic
from app.options.observer import OptionObserver

D = Decimal
ENROLLED = {**POLICY, "trade_floor": "native-target-floor-v1"}


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("stage,expected", [(1, "1.04"), (2, "1.14"), (3, "1.29")])
def test_target_touch_arms_exact_cost_floor_without_inventing_sales(
    tmp_path, right, stage, expected
):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d, plan=schedule(right, quantities=(1, 1, 1)))
        assert buy.trade_floor == ENROLLED["trade_floor"]
        assert e.assess(quote(d, "2"), d["underlying"], now=NOW)["status"] == "HEALTHY"
        assert ledger(e).position.trade_floor.minimum_exit_fill_price is None
        out = e.assess(quote(d, "2"), at_target(d, stage), now=NOW)
        state = ledger(e).position.trade_floor
        assert out["status"] == "HEALTHY" and state.minimum_exit_fill_price == D(expected)
        assert state.reference_stage == stage and not state.reasons
        assert state.evidence_hash == read(e, buy)["evidence_hash"]
        # .01 additional bid rounds down to exactly the fill-price floor after slippage.
        out = e.assess(quote(d, D(expected) + D(".01")), d["underlying"], now=NOW)
        assert out["exit_reason"] == "WHOLE_TRADE_FLOOR"
        assert (
            e.assess(quote(d, "3"), d["underlying"], now=NOW)["exit_reason"] == out["exit_reason"]
        )
        assert ledger(e).position.quantity == 4 and v.submit_count == 1
        assert read(e, buy)["evidence"]["exit_quantity"] == 0


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_profitable_scale_cannot_lower_floor_and_restart_closes_exact_runner(tmp_path, right):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d)
        high = quote(d, "3")
        out = tick(e, d, q=high)
        assert out["status"] == "OPEN", out
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 2
        fill(e, v, sell, high)
        assert D(read(e, buy)["reached_target_floor"]["minimum_exit_fill_price"]) == 0
        e.assess(high, at_target(d), now=NOW)
        assert ledger(e).position.trade_floor.minimum_exit_fill_price == D("1.04")
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        out = tick(e, d, q=quote(d, "1.05"))
        assert out["status"] == "OPEN" and out["exit_reason"] == "WHOLE_TRADE_FLOOR", out
        runner = intent_for(e, out["client_id"])
        assert runner.quantity == 2
        fill(e, v, runner, quote(d, "1.05"))
        result = read(e, buy)["evidence"]
        assert result["status"] == "COMPLETE"
        assert D(result["execution_fees"]) == D("8.20")
        assert D(result["net_after_known_execution_and_model_costs"]) == ledger(e).cash - 1000
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (runner.client_id,)
            ).fetchone()
            assert order_attribution(db, row)["trade_floor"] == ENROLLED["trade_floor"]


@pytest.mark.parametrize("fault", ["stale", "missing", "size", "source", "crossed"])
def test_unusable_bid_preserves_floor_without_triggering(tmp_path, fault):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d)
        e.assess(quote(d, "2"), at_target(d), now=NOW)
        q = quote(d, "1")
        if fault == "stale":
            q = quote(d, "1", NOW - timedelta(minutes=1))
        elif fault == "missing":
            q = None
        elif fault == "size":
            q = q.model_copy(update={"bid_size": 0})
        elif fault == "source":
            q = q.model_copy(update={"source": "foreign"})
        else:
            q = q.model_copy(update={"ask": D(".99")})
        out = e.assess(q, d["underlying"], now=NOW)
        assert out["status"] == "BLOCKED" and out["exit_reason"] is None
        assert ledger(e).position.trade_floor.minimum_exit_fill_price == D("1.04")
        assert v.submit_count == 1


@pytest.mark.parametrize("attempted", [False, True])
def test_full_floor_exit_respects_attempted_scale_reservation(tmp_path, attempted):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d)
        high = quote(d, "2")
        e.assess(high, at_target(d), now=NOW)
        out = prepare(e, buy, d, 2, quote=high)
        scale = intent_for(e, out["client_id"])
        if attempted:
            assert (
                asyncio.run(e.dispatch(scale.client_id, high, d["underlying"], now=NOW)) == "OPEN"
            )
        out = tick(e, d, q=quote(d, "1.05"))
        if attempted:
            assert out["status"] == "EXIT_BLOCKED" and v.submit_count == 2
            v.fill(scale, 1, high, NOW, fill_id="partial-scale")
            assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
            assert tick(e, d, q=quote(d, "1.05"))["status"] == "EXIT_BLOCKED"
            v.fill(scale, 1, high, NOW, fill_id="rest-scale")
            assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
            out = tick(e, d, q=quote(d, "1.05"))
        assert out["status"] == "OPEN" and out["exit_reason"] == "WHOLE_TRADE_FLOOR", out
        assert intent_for(e, out["client_id"]).quantity == (2 if attempted else 4)


def test_partial_dispatch_refreshes_protection_before_attempt(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d)
        high = quote(d, "2")
        out = prepare(e, buy, d, 1, quote=high, underlying=at_target(d))
        assert out["status"] == "PREPARED", out
        result = asyncio.run(
            e.dispatch(out["client_id"], quote(d, "1.05"), d["underlying"], now=NOW)
        )
        assert result == "REJECTED" and v.submit_count == 1
        assert ledger(e).position.exit_reason == "WHOLE_TRADE_FLOOR"


def test_partial_entry_blocks_scales_but_keeps_independent_catastrophe_exit(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d, quantity=2)
        v.record_terminal(buy.client_id, "CANCELED", NOW)
        out = tick(e, d, q=quote(d, "2"))
        assert out["status"] == "TRADE_FLOOR_BLOCKED", out
        state = ledger(e).position.trade_floor
        assert "COMPLETE_ORIGINAL_ENTRY_REQUIRED" in state.reasons
        assert state.minimum_exit_fill_price is None
        out = tick(e, d, q=quote(d, ".2"))
        assert out["status"] == "OPEN" and out["exit_reason"] == "PREMIUM_CATASTROPHE", out


def test_unknown_evidence_preserves_floor_blocks_scale_and_allows_full_protection(
    tmp_path, monkeypatch
):
    from app.options import trade_floor

    with owned(tmp_path, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d)
        e.assess(quote(d, "2"), at_target(d), now=NOW)
        native = trade_floor.native_trade_floor

        def missing(*args):
            value = native(*args)
            return {
                **value,
                "reasons": ["POSITION_MODEL_COST_UNKNOWN"],
                "reached_target_floor": None,
            }

        monkeypatch.setattr(trade_floor, "native_trade_floor", missing)
        out = tick(e, d, q=quote(d, "2"))
        assert out["status"] == "TRADE_FLOOR_BLOCKED"
        out = prepare(e, buy, d, 1, quote=quote(d, "2"))
        assert out["status"] != "PREPARED", out
        assert ledger(e).position.trade_floor.minimum_exit_fill_price == D("1.04")
        out = tick(e, d, q=quote(d, "1.05"))
        assert out["status"] == "OPEN" and out["exit_reason"] == "WHOLE_TRADE_FLOOR", out


def test_audit_rollback_independent_owners_and_stored_observer(tmp_path, monkeypatch):
    with (
        owned(tmp_path / "a", **ENROLLED) as (a, av, ad),
        owned(tmp_path / "b", **ENROLLED) as (b, bv, bd),
    ):
        enter_targets(a, av, ad)
        enter_targets(b, bv, bd)
        before = ledger(a)

        def fail(*args, **kwargs):
            raise RuntimeError("audit unavailable")

        with monkeypatch.context() as m:
            m.setattr(a.journal, "event", fail)
            with pytest.raises(RuntimeError, match="audit unavailable"):
                a.assess(quote(ad, "2"), at_target(ad), now=NOW)
        assert ledger(a) == before
        a.assess(quote(ad, "2"), at_target(ad), now=NOW)
        after = ledger(a)
        assert _economic(after) == _economic(before)
        assert ledger(b).position.trade_floor.minimum_exit_fill_price is None
        data = OptionObserver(a.journal.path, a.limits.population_id, clock=lambda: NOW).report()
        assert D(data["position"]["trade_floor"]["minimum_exit_fill_price"]) == D("1.04")
        assert ledger(a) == after and av.submit_count == bv.submit_count == 1


def test_enrollment_requires_target_policy_and_cannot_change_existing_owner(tmp_path):
    with pytest.raises(ValueError, match="require frozen target"):
        configuration(trade_floor=ENROLLED["trade_floor"])
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter(e, v, d)
        assert "trade_floor" not in buy.model_dump()
        assert "trade_floor" not in ledger(e).position.model_dump()
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(path, limits, policy.model_copy(update=ENROLLED), v, now=NOW),
    ):
        pass


@pytest.mark.parametrize("both", [False, True])
def test_dispatch_rejects_altered_enrollment_before_attempt(tmp_path, both):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = e.prepare("entry", d["proposal"], d["quote"], d["underlying"], now=NOW)
        with e.journal.write() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            intent, approval = json.loads(row["intent_json"]), json.loads(row["approval_json"])
            intent.pop("trade_floor")
            if both:
                approval.pop("trade_floor")
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=? WHERE client_id=?",
                (json.dumps(intent), json.dumps(approval), out["client_id"]),
            )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 0


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_native_open_export_retains_floor_and_costs(tmp_path, monkeypatch, right):
    import test_option_target_export as fixture

    from app.options.evaluation import evaluate

    monkeypatch.setattr(fixture, "POLICY", {**fixture.POLICY, **ENROLLED})
    row, bundle = fixture.exported(
        fixture.native_boundary(tmp_path, right), data_cost=".01", host_cost=".02"
    )
    assert row.closing.position.trade_floor.minimum_exit_fill_price == D("1.04")
    report = evaluate(bundle)["sessions"][0]["arms"]["A"]
    assert report["accounting_verified"], report
    assert report["net_change"] is None and report["status"] == "INCONCLUSIVE"
    assert report["allocated_data_cost"] == "0.01" and report["allocated_host_cost"] == "0.02"


def test_enrolled_abcd_replay_exports_entry_and_management_costs(tmp_path):
    from copy import deepcopy

    from test_option_managed_replay import managed_settings, managed_tape

    from app.options.evaluation import evaluate
    from app.options.evaluation_models import EvaluationBundle
    from app.options.replay import ReplaySettings, run_replay

    tape = managed_tape(tmp_path)
    settings = managed_settings(tape)
    arms = tuple(
        d.model_copy(update={"policy": d.policy.model_copy(update=ENROLLED)})
        for d in settings.manifest.arms
    )
    settings = ReplaySettings.model_validate(
        settings.model_dump() | {"manifest": settings.manifest.model_dump() | {"arms": arms}}
    )
    result = asyncio.run(run_replay(settings, tape, tmp_path / "run"))
    for evidence in result["bundle"]["evidence"]:
        arm = evidence["arm"]
        buys = [o for o in evidence["orders"] if o["intent"]["side"] == "BUY"]
        assert buys and all(o["intent"]["trade_floor"] == ENROLLED["trade_floor"] for o in buys)
        assert evidence["closing"]["position"] is None
        outcome = OptionObserver(
            tmp_path / "run" / arm / "journal.db", f"evaluation-{arm}"
        ).position_outcome(buys[0]["intent"]["client_id"])
        assert outcome["status"] == "COMPLETE"
        assert D(outcome["known_model_cost"]) == D(
            result["report"]["sessions"][0]["arms"][arm]["known_model_cost"]
        )
        if arm == "D":
            assert {c["role"] for c in outcome["model_calls"]} == {"ENTRY", "MANAGEMENT"}
    damaged = deepcopy(result["bundle"])
    buy = next(o for o in damaged["evidence"][0]["orders"] if o["intent"]["side"] == "BUY")
    buy["intent"].pop("trade_floor")
    rejected = evaluate(EvaluationBundle.model_validate(damaged))["sessions"][0]["arms"]["A"]
    assert "TRADE_FLOOR_POLICY_MISMATCH" in rejected["reasons"]
    assert rejected["status"] == "INCONCLUSIVE"
    assert not rejected["accounting_verified"] and rejected["net_change"] is None


@pytest.mark.parametrize("unknown", [False, True])
def test_fresh_cost_evidence_raises_floor_or_withholds_new_activation(
    tmp_path, monkeypatch, unknown
):
    from app.options import trade_floor

    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d)
        native = trade_floor.native_trade_floor

        def charge(*args):
            value = native(*args)
            if unknown:
                return {
                    **value,
                    "reasons": ["POSITION_MODEL_COST_UNKNOWN"],
                    "reached_target_floor": None,
                }
            # Boundary injection isolates the owner refresh from preview arithmetic,
            # which is separately tested against native entry and management receipts.
            return {
                **value,
                "reached_target_floor": {
                    **value["reached_target_floor"],
                    "minimum_exit_fill_price": "1.20",
                },
            }

        monkeypatch.setattr(trade_floor, "native_trade_floor", charge)
        out = e.assess(quote(d, "1.21"), at_target(d), now=NOW)
        state = ledger(e).position.trade_floor
        if unknown:
            assert state.minimum_exit_fill_price is None and out["exit_reason"] is None
            assert state.reasons == ("POSITION_MODEL_COST_UNKNOWN",)
        else:
            assert state.minimum_exit_fill_price == D("1.20")
            assert out["exit_reason"] == "WHOLE_TRADE_FLOOR"
        assert v.submit_count == 1


def test_target_can_latch_without_bid_but_only_fresh_bid_triggers(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d)
        out = e.assess(None, at_target(d), now=NOW)
        assert out["status"] == "BLOCKED" and out["exit_reason"] is None
        assert ledger(e).position.trade_floor.minimum_exit_fill_price == D("1.04")
        out = e.assess(quote(d, "1.05"), None, now=NOW)
        assert out["status"] == "BLOCKED" and out["exit_reason"] == "WHOLE_TRADE_FLOOR"
        assert ledger(e).position.exit_required_at == NOW and v.submit_count == 1


@pytest.mark.parametrize("cost_state", ["known", "unknown", "unallocated"])
def test_native_paid_entry_cost_changes_enforced_floor_and_unknown_is_never_zero(
    tmp_path, cost_state
):
    from app.execution.economics import CostPolicy, UsageEvidence

    costs = CostPolicy(
        total_budget="200", daily_budget="100", max_call_cost="100", input_per_million="10000"
    )
    with owned(tmp_path, **ENROLLED, cost_policy=costs) as (e, v, d):
        key = "unallocated" if cost_state == "unallocated" else "target-entry"
        e.begin_model_attempt(key, "a" * 64, now=NOW)
        e.record_model_usage(
            key,
            UsageEvidence(
                request_id="paid-selection", model=costs.model, input_tokens=1000, output_tokens=100
            ),
            d["proposal"],
            now=NOW,
        )
        buy = enter_targets(e, v, d)
        e.assess(quote(d, "2"), at_target(d), now=NOW)
        if cost_state == "unallocated":
            state = ledger(e).position.trade_floor
            assert state.minimum_exit_fill_price is None
            assert "ACCOUNT_MODEL_COST_LINK_UNPROVEN" in state.reasons
            assert tick(e, d, q=quote(d, "2"))["status"] == "TRADE_FLOOR_BLOCKED"
            return
        state = ledger(e).position.trade_floor
        assert state.minimum_exit_fill_price == D("1.07")  # Without this charge: 1.04.
        assert D(read(e, buy)["evidence"]["known_model_cost"]) == D("10.00005")
        if cost_state == "unknown":
            # Simulate lost usage settlement after prior accepted protection.
            with e.journal.write() as db:
                db.execute("UPDATE execution_model_calls SET cost=NULL WHERE source_key=?", (key,))
            assert tick(e, d, q=quote(d, "2"))["status"] == "TRADE_FLOOR_BLOCKED"
            state = ledger(e).position.trade_floor
            assert state.minimum_exit_fill_price == D("1.07")
            assert "POSITION_MODEL_COST_UNKNOWN" in state.reasons
        out = tick(e, d, q=quote(d, "1.08"))
        assert out["status"] == "OPEN" and out["exit_reason"] == "WHOLE_TRADE_FLOOR", out
        assert v.submit_count == 2
