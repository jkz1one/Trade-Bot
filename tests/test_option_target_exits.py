"""Frozen target orders, actual fills, runner conservation and protective precedence."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import intent_for, ledger, owned, quote_at, underlying_at
from test_option_partial_close import close, fill
from test_option_position_outcome import read_owned

from app.options.attribution import decision_attribution, order_attribution
from app.options.engine import OptionExecution
from app.options.lifecycle import TargetExitSchedule, TargetExitStep

D = Decimal
POLICY = {"partial_closes": "whole-contract-v1", "target_exits": "frozen-targets-v1"}


def schedule(right="CALL", quantities=(2, 1), entry_quantity=4):
    sign = 1 if right == "CALL" else -1
    return TargetExitSchedule(
        entry_quantity=entry_quantity,
        steps=tuple(
            TargetExitStep(underlying_price=600 + sign * (i + 1) * 2, quantity=q)
            for i, q in enumerate(quantities)
        ),
    )


def enter_targets(e, v, d, *, plan=None, quantity=None):
    plan = plan or schedule(d["proposal"].contract.right)
    q = quote_at(d, ask_size=plan.entry_quantity)
    out = e.prepare(
        "target-entry", d["proposal"], q, d["underlying"], now=NOW, target_exit_schedule=plan
    )
    assert out["status"] == "PREPARED", out
    buy = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch(buy.client_id, q, d["underlying"], now=NOW)) == "OPEN"
    v.fill(buy, quantity or buy.quantity, q, NOW, fill_id="entry-fill")
    assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
    return buy


def at_target(d, stage=1, at=NOW):
    price = 600 + (1 if d["proposal"].contract.right == "CALL" else -1) * stage * 2
    return underlying_at(d, at, bid=D(price), ask=D(price))


def tick(e, d, *, stage=1, q=None, u=None, at=NOW):
    return asyncio.run(
        e.protective_tick(q or quote_at(d, at), u or at_target(d, stage, at), now=at)
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_two_targets_then_protected_runner_counts_only_fills_and_every_fee(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d)
        before = ledger(e).position
        for stage, qty in ((1, 2), (2, 1)):
            out = tick(e, d, stage=stage)
            assert out["status"] == "OPEN", out
            sell = intent_for(e, out["client_id"])
            assert sell.target_exit_stage == stage and sell.quantity == qty
            assert sell.closing_entry_client_id == buy.client_id
            assert ledger(e).position.quantity == (4 if stage == 1 else 2)
            assert tick(e, d, stage=stage)["status"] == "TARGET_EXIT_BLOCKED"
            fill(e, v, sell, d["quote"])
            assert tick(e, d, stage=stage)["status"] == "HEALTHY"
            assert read_owned(e, buy)["status"] == "INCOMPLETE"
            with e.journal.read() as db:
                row = db.execute(
                    "SELECT * FROM execution_orders WHERE client_id=?", (sell.client_id,)
                ).fetchone()
                attr = order_attribution(db, row)
                assert attr["target_exit_stage"] == stage
                assert attr["requested_close_quantity"] == attr["filled_quantity"] == qty
                decision = decision_attribution(db, sell.source_key, {}, e.policy)
                assert decision.target_exit_stage == stage
                assert decision.filled_quantity == qty
        p = ledger(e).position
        assert p.quantity == 1 and p.target_exit_stage == 2
        assert p.target_exit_schedule == buy.target_exit_schedule
        assert p.original_underlying_invalidation == before.original_underlying_invalidation
        assert p.exit_at == before.exit_at and p.exit_reason is None
        at = p.exit_at
        out = tick(e, d, stage=2, at=at)
        assert out["exit_reason"] == "TIME_EXIT" and out["status"] == "OPEN"
        runner = intent_for(e, out["client_id"])
        assert runner.quantity == 1 and runner.target_exit_stage is None
        fill(e, v, runner, quote_at(d, at), at)
        outcome = read_owned(e, buy)
        assert outcome["status"] == "COMPLETE"
        assert D(outcome["execution_fees"]) == D("9.20")
        assert D(outcome["net_after_known_execution_and_model_costs"]) == D("-25.20")
        assert ledger(e).cash == D("974.80") and v.submit_count == 4


@pytest.mark.parametrize("quantity", [1, 2, 3, 4])
def test_whole_allocation_can_flatten_at_one_target(tmp_path, quantity):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d, plan=schedule(quantities=(quantity,), entry_quantity=quantity))
        out = tick(e, d)
        assert out["status"] == "OPEN", out
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == quantity
        fill(e, v, sell, d["quote"])
        assert ledger(e).position is None
        assert tick(e, d)["status"] == "HEALTHY" and v.submit_count == 2
        assert read_owned(e, buy)["status"] == "COMPLETE"


@pytest.mark.parametrize("quantities", [(2, 1), (1, 1, 1)])
def test_gap_over_targets_aggregates_due_and_low_liquidity_never_claims_fill(tmp_path, quantities):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter_targets(e, v, d, plan=schedule(quantities=quantities))
        for remaining in (3, 2, 1):
            at = NOW + timedelta(seconds=3 - remaining)
            q = quote_at(d, at, bid_size=1)
            out = tick(e, d, stage=len(quantities), q=q, at=at)
            assert out["status"] == "OPEN", out
            sell = intent_for(e, out["client_id"])
            assert sell.quantity == 1 and sell.requested_close_quantity == remaining
            fill(e, v, sell, q, at)
        assert ledger(e).position.quantity == 1
        assert (
            tick(e, d, stage=len(quantities), at=at)["status"] == "HEALTHY" and v.submit_count == 4
        )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_touch_latches_across_rebound_reconciliation_and_restart(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d)
        assert e.assess(d["quote"], at_target(d), now=NOW)["target_exit_stage"] == 1
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        out = tick(e, d, u=d["underlying"])
        assert out["status"] == "OPEN", out
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 2 and sell.closing_entry_client_id == buy.client_id
        fill(e, v, sell, d["quote"])
        assert tick(e, d, u=d["underlying"])["status"] == "HEALTHY"
        assert v.submit_count == 2


def test_discretionary_sales_count_toward_cumulative_allocation(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d)
        out = e.prepare("manual-scale", close(buy, 1), d["quote"], d["underlying"], now=NOW)
        sell = intent_for(e, out["client_id"])
        assert (
            asyncio.run(e.dispatch(sell.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
        )
        fill(e, v, sell, d["quote"])
        out = tick(e, d)
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 1
        fill(e, v, sell, d["quote"])
        assert tick(e, d)["status"] == "HEALTHY"
        assert ledger(e).position.quantity == 2


@pytest.mark.parametrize("cause", ["stop", "premium", "time"])
def test_protection_preempts_touched_target_and_prepared_scale(tmp_path, cause):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d)
        e.assess(d["quote"], at_target(d), now=NOW)
        out = e.prepare(
            "prepared-target", close(buy, 2), d["quote"], at_target(d), now=NOW, target_exit_stage=1
        )
        assert out["status"] == "PREPARED", out
        q = quote_at(d, bid=D(".2"), ask=D(".21")) if cause == "premium" else d["quote"]
        u = underlying_at(d, bid=D(598), ask=D("598.01")) if cause == "stop" else at_target(d)
        at = ledger(e).position.exit_at if cause == "time" else NOW
        if cause == "time":
            q, u = quote_at(d, at), at_target(d, at=at)
        out = tick(e, d, q=q, u=u, at=at)
        assert out["status"] == "OPEN" and "exit_reason" in out, out
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 4 and sell.target_exit_stage is None
        assert v.submit_count == 2


def test_attempted_target_keeps_reservation_then_protection_closes_actual_runner(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter_targets(e, v, d)
        out = tick(e, d)
        sell = intent_for(e, out["client_id"])
        stop = underlying_at(d, bid=D(598), ask=D("598.01"))
        assert tick(e, d, u=stop)["status"] == "EXIT_BLOCKED"
        fill(e, v, sell, d["quote"])
        out = tick(e, d, u=d["underlying"])
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert intent_for(e, out["client_id"]).quantity == 2


@pytest.mark.parametrize("status", ["CANCELED", "REJECTED", "EXPIRED"])
def test_attempted_failed_scale_never_automatically_replays(tmp_path, status):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter_targets(e, v, d)
        out = tick(e, d)
        v.record_terminal(out["client_id"], status, NOW)
        assert tick(e, d)["status"] == "TARGET_EXIT_REVIEW_REQUIRED"
        assert tick(e, d)["status"] == "TARGET_EXIT_REVIEW_REQUIRED" and v.submit_count == 2


def test_partial_entry_cannot_be_reallocated_silently_but_stop_still_exits(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d, quantity=2)
        assert tick(e, d)["status"] == "TARGET_EXIT_BLOCKED"
        v.record_terminal(buy.client_id, "CANCELED", NOW)
        out = tick(e, d)
        assert out["reason"] == "OPTION_TARGET_COMPLETE_ENTRY_REQUIRED"
        stop = underlying_at(d, bid=D(598), ask=D("598.01"))
        out = tick(e, d, u=stop)
        assert out["status"] == "OPEN" and intent_for(e, out["client_id"]).quantity == 2


def test_stale_underlying_cannot_latch_target_or_create_sale(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter_targets(e, v, d)
        stale = at_target(d, at=NOW - timedelta(minutes=1))
        assert tick(e, d, u=stale)["status"] == "BLOCKED"
        assert ledger(e).position.target_exit_stage == 0 and v.submit_count == 1


def test_prepared_target_restart_reuses_same_order(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d)
        e.assess(d["quote"], at_target(d), now=NOW)
        out = e.prepare(
            "resume-target", close(buy, 2), d["quote"], at_target(d), now=NOW, target_exit_stage=1
        )
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        resumed = tick(e, d)
        assert resumed["status"] == "OPEN" and resumed["client_id"] == out["client_id"]
        assert v.submit_count == 2


@pytest.mark.parametrize("bad", [True, "1", 0, 4])
def test_untrusted_target_stage_rejected(tmp_path, bad):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter_targets(e, v, d)
        out = e.prepare(
            "bad-stage", close(buy, 1), d["quote"], d["underlying"], now=NOW, target_exit_stage=bad
        )
        assert out["status"] == "REJECTED" and v.submit_count == 1


@pytest.mark.parametrize("change", ["schedule", "stage"])
def test_changed_target_terms_fail_dispatch_and_stored_attribution(tmp_path, change):
    with owned(tmp_path, **POLICY) as (e, v, d):
        if change == "schedule":
            out = e.prepare(
                "tamper",
                d["proposal"],
                d["quote"],
                d["underlying"],
                now=NOW,
                target_exit_schedule=schedule(),
            )
        else:
            buy = enter_targets(e, v, d)
            e.assess(d["quote"], at_target(d), now=NOW)
            out = e.prepare(
                "tamper", close(buy, 2), d["quote"], at_target(d), now=NOW, target_exit_stage=1
            )
        with e.journal.write() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            approval = json.loads(row["approval_json"])
            approval.pop("target_exit_schedule" if change == "schedule" else "target_exit_stage")
            db.execute(
                "UPDATE execution_orders SET approval_json=? WHERE client_id=?",
                (json.dumps(approval), out["client_id"]),
            )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            with pytest.raises(ValueError, match="TARGET_TERMS_CHANGED"):
                order_attribution(db, row)


def test_schedule_caps_direction_enrollment_and_frozen_reopen(tmp_path):
    with pytest.raises(ValidationError, match="cannot exceed"):
        schedule(quantities=(3, 2))
    with owned(tmp_path / "old", partial_closes="whole-contract-v1") as (e, v, d):
        assert "target_exits" not in e.policy.model_dump()
        out = e.prepare(
            "no-enrollment",
            d["proposal"],
            d["quote"],
            d["underlying"],
            now=NOW,
            target_exit_schedule=schedule(),
        )
        assert out["status"] == "REJECTED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(
            path,
            limits,
            policy.model_copy(update={"target_exits": "frozen-targets-v1"}),
            v,
            now=NOW,
        ),
    ):
        pass
    with owned(tmp_path / "new", **POLICY) as (e, v, d):
        for key, plan in (("quantity", schedule(entry_quantity=5)), ("direction", schedule("PUT"))):
            out = e.prepare(
                key, d["proposal"], d["quote"], d["underlying"], now=NOW, target_exit_schedule=plan
            )
            assert out["status"] == "REJECTED" and v.submit_count == 0


def test_target_consumed_before_entry_dispatch_blocks_buy(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        out = e.prepare(
            "entry",
            d["proposal"],
            d["quote"],
            d["underlying"],
            now=NOW,
            target_exit_schedule=schedule(),
        )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], at_target(d), now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 0


def test_independent_accounts_do_not_share_target_progress_or_cash(tmp_path):
    with (
        owned(tmp_path / "a", **POLICY) as (a, va, da),
        owned(tmp_path / "b", **POLICY) as (b, vb, db),
    ):
        enter_targets(a, va, da)
        enter_targets(b, vb, db)
        original = ledger(b)
        out = tick(a, da, stage=2)
        fill(a, va, intent_for(a, out["client_id"]), da["quote"])
        assert ledger(a).position.quantity == 1
        assert ledger(b) == original and vb.submit_count == 1
        assert tick(b, db, u=db["underlying"])["status"] == "HEALTHY"


def test_unknown_target_attempt_retains_reservation_and_reconciles_without_replay(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter_targets(e, v, d)
        v.fault = "LOST_ACK"
        out = tick(e, d)
        assert out["status"] == "UNKNOWN" and v.submit_count == 2
        v.fault = "NONE"
        assert tick(e, d)["status"] == "TARGET_EXIT_BLOCKED"
        assert v.submit_count == 2 and ledger(e).position.quantity == 4
        fill(e, v, intent_for(e, out["client_id"]), d["quote"])
        assert tick(e, d)["status"] == "HEALTHY" and v.submit_count == 2


def test_target_observation_transaction_failure_cannot_leak_progress(tmp_path, monkeypatch):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter_targets(e, v, d)
        original = ledger(e)
        event = e.journal.event

        def fail(*args, **kwargs):
            event(*args, **kwargs)
            raise RuntimeError("injected target observation failure")

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="injected target"):
            e.assess(d["quote"], at_target(d), now=NOW)
        assert ledger(e) == original and v.submit_count == 1
