"""Executable premium peaks, original entry basis and protected native exits."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_admission import NOW
from test_option_execution import enter, intent_for, ledger, owned, quote_at
from test_option_partial_close import fill, prepare
from test_option_position_outcome import read_owned

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.evaluation import _economic
from app.options.observer import OptionObserver
from app.options.premium_trail import floor_value

D = Decimal
POLICY = {"premium_trail": "executable-premium-v1"}


def quote(d, bid, at=NOW):
    return quote_at(d, at, bid=D(bid), ask=D(bid) + D(".01"))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "peak,floor",
    [
        ("1.211999999999", None),
        ("1.212", ".9797"),
        ("1.363499999999", ".9797"),
        ("1.3635", "1.111"),
        ("1.514999999999", "1.111"),
        ("1.515", "1.28775"),
        ("2.02", "1.5655"),
    ],
)
def test_exact_activation_thresholds_and_bid_floor(tmp_path, right, peak, floor):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = enter(e, v, d)
        assert buy.premium_trail == POLICY["premium_trail"]
        assert buy.approved_full_premium_loss == D("414.20")
        assert e.assess(quote(d, peak), d["underlying"], now=NOW)["status"] == "HEALTHY"
        trail = ledger(e).position.premium_trail
        assert trail.entry_basis == D(404) and trail.entry_quantity == 4
        actual = floor_value(trail, 100)
        assert actual == (D(floor) * 400 if floor else None)
        if floor:
            assert (
                e.assess(quote(d, D(floor) + D(".000000000001")), d["underlying"], now=NOW)[
                    "status"
                ]
                == "HEALTHY"
            )
            out = e.assess(quote(d, floor), d["underlying"], now=NOW)
            assert out["exit_reason"] == "PREMIUM_TRAIL"
            assert ledger(e).position.premium_trail.peak_bid == D(peak)
            assert (
                e.assess(quote(d, "3"), d["underlying"], now=NOW)["exit_reason"] == "PREMIUM_TRAIL"
            )
        assert v.submit_count == 1


def test_weighted_completed_entry_basis_does_not_reset_after_scale_and_restart(tmp_path):
    with owned(tmp_path, partial_closes="whole-contract-v1", **POLICY) as (e, v, d):
        buy = enter(e, v, d, quantity=1)
        assert ledger(e).position.premium_trail.entry_basis is None
        e.assess(quote(d, "2"), d["underlying"], now=NOW)
        assert ledger(e).position.premium_trail.peak_bid is None
        # The native fixture applies slippage and rounds buys up to the tick.
        q = quote_at(d, ask=D(".99"))
        v.fill(buy, 3, q, NOW, fill_id="entry-rest")
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        assert ledger(e).position.premium_trail.entry_basis == D(401)
        peak = quote(d, "1.50375")
        e.assess(peak, d["underlying"], now=NOW)
        out = prepare(e, buy, d, 1, quote=peak)
        sell = intent_for(e, out["client_id"])
        assert asyncio.run(e.dispatch(sell.client_id, peak, d["underlying"], now=NOW)) == "OPEN"
        fill(e, v, sell, peak)
        p = ledger(e).position
        assert p.basis == D(300) and p.premium_trail.entry_basis == D(401)
        assert p.premium_trail.peak_bid == D("1.50375")
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        # 1.0025 * 1.275, using the original complete entry, not remaining FIFO lots.
        q = quote(d, "1.2781875")
        out = asyncio.run(e.protective_tick(q, d["underlying"], now=NOW))
        assert out["exit_reason"] == "PREMIUM_TRAIL" and out["status"] == "OPEN"
        runner = intent_for(e, out["client_id"])
        assert runner.quantity == 3
        fill(e, v, runner, q)
        result = read_owned(e, buy)
        assert result["status"] == "COMPLETE"
        assert D(result["execution_fees"]) == D("8.20")
        assert D(result["net_after_known_execution_and_model_costs"]) == ledger(e).cash - 1000
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (runner.client_id,)
            ).fetchone()
            assert order_attribution(db, row)["premium_trail"] == POLICY["premium_trail"]


@pytest.mark.parametrize("fault", ["stale", "missing", "size", "source", "crossed"])
def test_bad_bid_cannot_invent_peak_or_exit(tmp_path, fault):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter(e, v, d)
        q = quote(d, "3")
        if fault == "stale":
            q = quote(d, "3", NOW - timedelta(minutes=1))
        elif fault == "missing":
            q = None
        elif fault == "size":
            q = q.model_copy(update={"bid_size": 0})
        elif fault == "source":
            q = q.model_copy(update={"source": "foreign"})
        else:
            q = q.model_copy(update={"ask": D("2")})
        out = e.assess(q, d["underlying"], now=NOW)
        assert out["status"] == "BLOCKED" and out["exit_reason"] is None
        assert ledger(e).position.premium_trail.peak_bid is None


def test_stale_bid_does_not_lower_saved_peak_and_fresh_rebound_triggers(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter(e, v, d)
        e.assess(quote(d, "2.02"), d["underlying"], now=NOW)
        assert (
            e.assess(quote(d, "1.5", NOW - timedelta(minutes=1)), d["underlying"], now=NOW)[
                "exit_reason"
            ]
            is None
        )
        assert ledger(e).position.premium_trail.peak_bid == D("2.02")
        assert e.assess(quote(d, "1.5"), d["underlying"], now=NOW)["exit_reason"] == "PREMIUM_TRAIL"


def test_terminal_partial_entry_stays_under_original_protection(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = enter(e, v, d, quantity=1)
        v.record_terminal(buy.client_id, "CANCELED", NOW)
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        e.assess(quote(d, "3"), d["underlying"], now=NOW)
        assert ledger(e).position.premium_trail.entry_basis is None
        assert (
            e.assess(quote(d, ".2"), d["underlying"], now=NOW)["exit_reason"]
            == "PREMIUM_CATASTROPHE"
        )


@pytest.mark.parametrize("attempted", [False, True])
def test_trail_supersedes_only_never_attempted_scale(tmp_path, attempted):
    with owned(tmp_path, partial_closes="whole-contract-v1", **POLICY) as (e, v, d):
        buy = enter(e, v, d)
        peak = quote(d, "2.02")
        e.assess(peak, d["underlying"], now=NOW)
        out = prepare(e, buy, d, 2, quote=peak)
        scale = intent_for(e, out["client_id"])
        if attempted:
            assert (
                asyncio.run(e.dispatch(scale.client_id, peak, d["underlying"], now=NOW)) == "OPEN"
            )
        drop = quote(d, "1.5")
        out = asyncio.run(e.protective_tick(drop, d["underlying"], now=NOW))
        if attempted:
            assert out["status"] == "EXIT_BLOCKED" and v.submit_count == 2
            fill(e, v, scale, peak)
            out = asyncio.run(e.protective_tick(drop, d["underlying"], now=NOW))
        assert out["status"] == "OPEN" and out["exit_reason"] == "PREMIUM_TRAIL"
        assert intent_for(e, out["client_id"]).quantity == (2 if attempted else 4)


def test_legacy_cohort_cannot_adopt_trail_on_reopen(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        assert "premium_trail" not in buy.model_dump()
        assert "premium_trail" not in ledger(e).position.model_dump()
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(path, limits, policy.model_copy(update=POLICY), v, now=NOW),
    ):
        pass


def test_dispatch_rejects_missing_trail_before_attempt(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        out = e.prepare("entry", d["proposal"], d["quote"], d["underlying"], now=NOW)
        with e.journal.write() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            intent, approval = json.loads(row["intent_json"]), json.loads(row["approval_json"])
            intent.pop("premium_trail")
            approval.pop("premium_trail")
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=? WHERE client_id=?",
                (json.dumps(intent), json.dumps(approval), out["client_id"]),
            )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 0


def test_stored_observer_and_economic_projection_retain_basis_without_reassessing(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        enter(e, v, d)
        before = ledger(e)
        e.assess(quote(d, "2.02"), d["underlying"], now=NOW)
        after = ledger(e)
        assert _economic(before) == _economic(after)
        p = after.position
        changed = after.model_copy(
            update={
                "position": p.model_copy(
                    update={
                        "premium_trail": p.premium_trail.model_copy(update={"entry_basis": D(400)})
                    }
                )
            }
        )
        assert _economic(before) != _economic(changed)
        data = OptionObserver(e.journal.path, e.limits.population_id, clock=lambda: NOW).report()
        assert data["position"]["premium_trail"]["peak_bid"] == "2.02"
        assert D(data["position"]["premium_trail"]["floor_original_quantity_premium"]) == D(
            "626.20"
        )
        assert ledger(e) == after and v.submit_count == 1


def test_audit_failure_rolls_back_peak_and_independent_owner_has_no_peak(tmp_path, monkeypatch):
    with (
        owned(tmp_path / "a", **POLICY) as (a, av, ad),
        owned(tmp_path / "b", **POLICY) as (b, bv, bd),
    ):
        enter(a, av, ad)
        enter(b, bv, bd)
        before = ledger(a)

        def fail(*args, **kwargs):
            raise RuntimeError("audit unavailable")

        with monkeypatch.context() as m:
            m.setattr(a.journal, "event", fail)
            with pytest.raises(RuntimeError, match="audit unavailable"):
                a.assess(quote(ad, "2.02"), ad["underlying"], now=NOW)
        assert ledger(a) == before
        a.assess(quote(ad, "2.02"), ad["underlying"], now=NOW)
        assert ledger(b).position.premium_trail.peak_bid is None
        assert ledger(a).cash == ledger(b).cash


def test_enrolled_abcd_replay_exports_entry_and_management_costs(tmp_path):
    from copy import deepcopy

    from test_option_managed_replay import managed_settings, managed_tape

    from app.options.evaluation import evaluate
    from app.options.evaluation_models import EvaluationBundle
    from app.options.replay import ReplaySettings, run_replay

    tape = managed_tape(tmp_path)
    settings = managed_settings(tape)
    arms = tuple(
        d.model_copy(update={"policy": d.policy.model_copy(update=POLICY)})
        for d in settings.manifest.arms
    )
    settings = ReplaySettings.model_validate(
        settings.model_dump() | {"manifest": settings.manifest.model_dump() | {"arms": arms}}
    )
    result = asyncio.run(run_replay(settings, tape, tmp_path / "run"))
    for evidence in result["bundle"]["evidence"]:
        arm = evidence["arm"]
        buys = [o for o in evidence["orders"] if o["intent"]["side"] == "BUY"]
        assert buys and all(o["intent"]["premium_trail"] == POLICY["premium_trail"] for o in buys)
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
    buy["intent"].pop("premium_trail")
    rejected = evaluate(EvaluationBundle.model_validate(damaged))["sessions"][0]["arms"]["A"]
    assert "PREMIUM_TRAIL_POLICY_MISMATCH" in rejected["reasons"]
    assert rejected["status"] == "INCONCLUSIVE"
    assert not rejected["accounting_verified"] and rejected["net_change"] is None
