"""Frozen target-triggered stops retain risk, order reservations and native economics."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import configuration, intent_for, ledger, owned, quote_at, underlying_at
from test_option_partial_close import close, fill
from test_option_position_outcome import read_owned
from test_option_target_exits import POLICY, at_target, enter_targets, schedule, tick

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.lifecycle import TargetExitStep

D = Decimal
ENROLLED = {**POLICY, "target_stops": "frozen-target-stops-v1"}


def plan(right="CALL", stops=None):
    base = schedule(right)
    stops = stops if stops is not None else (600, 602 if right == "CALL" else 598)
    return base.model_copy(
        update={
            "steps": tuple(
                s.model_copy(
                    update={"tighten_underlying_to": D(stop) if stop is not None else None}
                )
                for s, stop in zip(base.steps, stops, strict=True)
            )
        }
    )


def price(d, value, at=NOW):
    return underlying_at(d, at, bid=D(value), ask=D(value))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_scales_then_restart_runner_uses_frozen_stops_and_all_fees(tmp_path, right):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d, plan=plan(right))
        assert buy.approved_full_premium_loss == D("414.20")
        original = ledger(e).position
        for stage, stop in ((1, 600), (2, 602 if right == "CALL" else 598)):
            out = tick(e, d, stage=stage)
            sell = intent_for(e, out["client_id"])
            assert sell.quantity == (2 if stage == 1 else 1)
            fill(e, v, sell, d["quote"])
            assert ledger(e).position.tightened_underlying_invalidation == D(stop)
        p = ledger(e).position
        assert p.quantity == 1 and p.exit_reason is None
        assert p.exit_at == original.exit_at
        assert p.original_underlying_invalidation == original.original_underlying_invalidation
        assert read_owned(e, buy)["status"] == "INCOMPLETE"
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (buy.client_id,)
            ).fetchone()
            assert order_attribution(db, row)["target_exit_schedule"] == plan(right).model_dump(
                mode="json"
            )
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        out = tick(e, d, u=price(d, stop))
        assert out["status"] == "OPEN" and out["exit_reason"] == "UNDERLYING_INVALIDATION"
        runner = intent_for(e, out["client_id"])
        assert runner.quantity == 1 and runner.target_exit_stage is None
        fill(e, v, runner, d["quote"])
        outcome = read_owned(e, buy)
        assert outcome["status"] == "COMPLETE"
        assert D(outcome["execution_fees"]) == D("9.20")
        assert D(outcome["net_after_known_execution_and_model_costs"]) == D("-25.20")
        assert ledger(e).cash == D("974.80") and v.submit_count == 4


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_gap_uses_highest_stop_and_existing_tighter_stop_never_widens(tmp_path, right):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d, plan=plan(right))
        u = at_target(d, 2)
        out = e.assess(d["quote"], u, now=NOW)
        assert out["target_exit_stage"] == 2
        assert D(out["target_stop_price"]) == (D(602) if right == "CALL" else D(598))
        tighter = D(603) if right == "CALL" else D(597)
        e.tighten_invalidation(tighter, d["quote"], u, now=NOW)
        out = e.assess(d["quote"], u, now=NOW)
        assert D(out["target_stop_price"]) == tighter and out["status"] == "HEALTHY"
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        assert ledger(e).position.tightened_underlying_invalidation == tighter
        assert e.assess(d["quote"], price(d, tighter), now=NOW)["status"] == "EXIT_REQUIRED"
        assert e.assess(d["quote"], u, now=NOW)["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert v.submit_count == 1


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_target_during_bad_option_quote_tightens_only_on_recovery_and_checks_rebound(
    tmp_path, right
):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d, plan=plan(right))
        original = ledger(e).position.tightened_underlying_invalidation
        out = e.assess(None, at_target(d), now=NOW)
        assert out["status"] == "BLOCKED" and out["target_exit_stage"] == 1
        assert ledger(e).position.tightened_underlying_invalidation == original
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        out = e.assess(d["quote"], price(d, 600), now=NOW)
        assert out["status"] == "EXIT_REQUIRED" and out["target_stop_price"] == "600"
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION" and v.submit_count == 1


@pytest.mark.parametrize("fault", ["stale", "source", "crossed", "incomplete", "missing"])
def test_bad_underlying_never_latches_or_tightens(tmp_path, fault):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d, plan=plan())
        u = at_target(d)
        if fault == "stale":
            u = at_target(d, at=NOW - timedelta(minutes=1))
        elif fault == "source":
            u = u.model_copy(update={"source": "foreign"})
        elif fault == "crossed":
            u = u.model_copy(update={"bid": D(605)})
        elif fault == "incomplete":
            u = u.model_copy(update={"complete": False})
        else:
            u = None
        before = ledger(e).position
        assert e.assess(d["quote"], u, now=NOW)["status"] == "BLOCKED"
        after = ledger(e).position
        assert after.target_exit_stage == 0
        assert after.tightened_underlying_invalidation == before.tightened_underlying_invalidation
        assert v.submit_count == 1


def test_tightened_stop_supersedes_only_unattempted_scale(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d, plan=plan())
        e.assess(d["quote"], at_target(d), now=NOW)
        pending = e.prepare(
            "scale", close(buy, 2), d["quote"], at_target(d), now=NOW, target_exit_stage=1
        )
        assert pending["status"] == "PREPARED"
        out = tick(e, d, u=price(d, 600))
        assert out["status"] == "OPEN" and out["client_id"] != pending["client_id"]
        assert intent_for(e, out["client_id"]).quantity == 4 and v.submit_count == 2


def test_attempted_scale_reservation_survives_then_actual_remaining_position_exits(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d, plan=plan())
        out = tick(e, d)
        scale = intent_for(e, out["client_id"])
        assert tick(e, d, u=price(d, 600))["status"] == "EXIT_BLOCKED"
        assert v.submit_count == 2 and ledger(e).position.quantity == 4
        fill(e, v, scale, d["quote"])
        out = tick(e, d)
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert intent_for(e, out["client_id"]).quantity == 2 and v.submit_count == 3


def test_terminal_partial_entry_retains_stop_without_reallocating_targets(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        buy = enter_targets(e, v, d, plan=plan(), quantity=2)
        v.record_terminal(buy.client_id, "CANCELED", NOW)
        assert tick(e, d)["reason"] == "OPTION_TARGET_COMPLETE_ENTRY_REQUIRED"
        assert ledger(e).position.tightened_underlying_invalidation == D(600)
        out = tick(e, d, u=price(d, 600))
        assert out["status"] == "OPEN" and intent_for(e, out["client_id"]).quantity == 2


@pytest.mark.parametrize(
    "right,stops",
    [
        ("CALL", (598, 602)),
        ("CALL", (602, 603)),
        ("CALL", (600, 599)),
        ("PUT", (602, 598)),
        ("PUT", (598, 597)),
        ("PUT", (600, 601)),
    ],
)
def test_invalid_frozen_stops_rejected_before_entry(tmp_path, right, stops):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        out = e.prepare(
            "invalid",
            d["proposal"],
            d["quote"],
            d["underlying"],
            now=NOW,
            target_exit_schedule=plan(right, stops),
        )
        assert out["status"] == "REJECTED" and v.submit_count == 0


def test_enrollment_and_legacy_encoding_are_frozen(tmp_path):
    with pytest.raises(ValidationError, match="require frozen target exits"):
        configuration(target_stops="frozen-target-stops-v1")
    assert (
        "tighten_underlying_to"
        not in TargetExitStep(underlying_price="602", quantity=1).model_dump()
    )
    with owned(tmp_path, **POLICY) as (e, v, d):
        assert "target_stops" not in e.policy.model_dump()
        out = e.prepare(
            "no-enrollment",
            d["proposal"],
            d["quote"],
            d["underlying"],
            now=NOW,
            target_exit_schedule=plan(),
        )
        assert out["status"] == "REJECTED" and out["reason"] == "OPTION_TARGET_STOPS_NOT_ENROLLED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(
            path,
            limits,
            policy.model_copy(update={"target_stops": "frozen-target-stops-v1"}),
            v,
            now=NOW,
        ),
    ):
        pass


def test_changed_stop_rejected_at_dispatch_and_stored_attribution(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = e.prepare(
            "tamper",
            d["proposal"],
            d["quote"],
            d["underlying"],
            now=NOW,
            target_exit_schedule=plan(),
        )
        with e.journal.write() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            approval = json.loads(row["approval_json"])
            approval["target_exit_schedule"]["steps"][0]["tighten_underlying_to"] = "600.5"
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
        assert v.submit_count == 0


def test_dispatch_rechecks_stop_enrollment_even_when_stored_terms_agree(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        out = e.prepare(
            "entry",
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
                record["target_exit_schedule"] = plan().model_dump(mode="json")
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=? WHERE client_id=?",
                (json.dumps(intent), json.dumps(approval), out["client_id"]),
            )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        with e.journal.read() as db:
            assert (
                db.execute(
                    "SELECT attempted_at FROM execution_orders WHERE client_id=?",
                    (out["client_id"],),
                ).fetchone()[0]
                is None
            )
        assert v.submit_count == 0


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_optional_stop_steps_and_exact_boundary(tmp_path, right):
    stop = D(602) if right == "CALL" else D(598)
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d, plan=plan(right, (None, stop)))
        original = ledger(e).position.tightened_underlying_invalidation
        e.assess(d["quote"], at_target(d), now=NOW)
        assert ledger(e).position.tightened_underlying_invalidation == original
        e.assess(d["quote"], at_target(d, 2), now=NOW)
        above = stop + (D(".000000000001") if right == "CALL" else -D(".000000000001"))
        assert e.assess(d["quote"], price(d, above), now=NOW)["status"] == "HEALTHY"
        assert (
            e.assess(d["quote"], price(d, stop), now=NOW)["exit_reason"]
            == "UNDERLYING_INVALIDATION"
        )


@pytest.mark.parametrize("cause", ["premium", "time"])
def test_existing_mandatory_exit_takes_priority_over_target_stop(tmp_path, cause):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d, plan=plan())
        before = ledger(e).position
        at = before.exit_at if cause == "time" else NOW
        q = quote_at(d, at, bid=D(".2"), ask=D(".21")) if cause == "premium" else quote_at(d, at)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        out = e.assess(q, at_target(d, 2, at), now=at)
        assert out["exit_reason"] == ("TIME_EXIT" if cause == "time" else "PREMIUM_CATASTROPHE")
        assert ledger(e).position.target_exit_stage == 0
        assert (
            ledger(e).position.tightened_underlying_invalidation
            == before.tightened_underlying_invalidation
        )


def test_supervision_audit_failure_rolls_back_stage_and_stop(tmp_path, monkeypatch):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter_targets(e, v, d, plan=plan())
        before = ledger(e).position

        def fail(*args, **kwargs):
            raise RuntimeError("audit unavailable")

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            e.assess(d["quote"], at_target(d, 2), now=NOW)
        assert ledger(e).position == before and v.submit_count == 1


def test_independent_owners_do_not_share_touches_or_stops(tmp_path):
    with (
        owned(tmp_path / "a", **ENROLLED) as (a, av, ad),
        owned(tmp_path / "b", **ENROLLED) as (b, bv, bd),
    ):
        enter_targets(a, av, ad, plan=plan())
        enter_targets(b, bv, bd, plan=plan())
        a.assess(ad["quote"], at_target(ad, 2), now=NOW)
        assert ledger(a).position.tightened_underlying_invalidation == D(602)
        assert ledger(b).position.target_exit_stage == 0
        assert (
            ledger(b).position.tightened_underlying_invalidation
            == bd["proposal"].underlying_invalidation
        )
        assert ledger(a).cash == ledger(b).cash and av.submit_count == bv.submit_count == 1
