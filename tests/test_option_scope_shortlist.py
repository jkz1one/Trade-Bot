"""Choice-only B retains original proposals and full native paid Scope approval."""

import asyncio
import json
from decimal import Decimal

import pytest
from test_option_entry_reasoning import packet_for
from test_option_scope_model_replay import request as model_request
from test_option_scope_model_replay import rows
from test_option_scope_replay_model import release

from app.execution.economics import CostPolicy
from app.execution.judgment import JudgmentLimits
from app.options import entry_judgment
from app.options.engine import fingerprint
from app.options.entry_reasoning import ScopeShortlistPlan, review_entry_plan
from app.options.scope_execution_export import verify_scope_execution_export
from app.options.scope_model_replay import ScopeModelReplay, run_scope_model_replay
from app.options.scope_shortlist_replay import (
    ScopeShortlistDecision,
    ScopeShortlistModel,
    ScopeShortlistScript,
)


def request(tmp_path, **kwargs):
    old = model_request(tmp_path, **kwargs)
    d = old.script.decisions[0]
    script = ScopeShortlistScript(
        decisions=(
            ScopeShortlistDecision(
                cycle_key=d.cycle_key,
                delay_seconds=d.delay_seconds,
                action="SELECT" if d.action == "ENTER" else d.action,
                scope=d.scope,
            ),
        )
    )
    return ScopeModelReplay.model_validate(
        old.model_dump()
        | {
            "script": script.model_dump(),
            "entry_policy": old.entry_policy.model_dump()
            | {"scope_selection": "scope-fixed-shortlist-v1"},
        }
    )


def original_request(right="CALL"):
    p = packet_for(right)
    policy = p.policy.model_copy(update={"scope_selection": "scope-fixed-shortlist-v1"})
    config = entry_judgment.configuration(
        CostPolicy(total_budget="1", daily_budget=".1"),
        JudgmentLimits(process_timeout_seconds=5, request_timeout_seconds=3),
        policy,
    )
    p = p.model_copy(update={"policy": policy, "model_configuration_hash": fingerprint(config)})
    return entry_judgment.create_request(p, config, request_id="b" * 32, now=p.as_of)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("action", ["SELECT", "HOLD", "UNKNOWN", "invalid"])
def test_shortlist_receipt_and_original_ordinary_terms(right, action):
    req = original_request(right)
    d = ScopeShortlistDecision(
        cycle_key=req.packet.cycle_key,
        delay_seconds=1,
        action="SELECT" if action == "invalid" else action,
        candidate_index=23 if action == "invalid" else 0 if action == "SELECT" else None,
    )
    m = ScopeShortlistModel(ScopeShortlistScript(decisions=(d,)))
    original = req.model_dump_json()
    result = asyncio.run(release(m, req))
    assert req.model_dump_json() == original
    assert entry_judgment.validate_result(req, result) == result
    if action == "UNKNOWN":
        assert result.usage is None and result.error
    else:
        assert result.usage.input_tokens == 1000
    if action == "SELECT":
        o = req.packet.opportunities[0]
        reviewed = review_entry_plan(
            req.packet,
            result.plan,
            quote=o.quote,
            underlying=o.underlying,
            account=req.packet.account,
            now=req.packet.as_of,
        )
        assert reviewed.outcome == "ELIGIBLE"
        assert reviewed.proposal == o.candidate.proposal
        assert reviewed.admission.quantity <= o.candidate.admission.quantity
        assert reviewed.admission.valid_until <= o.candidate.admission.valid_until
        assert reviewed.exit_by is None
        assert result.plan.underlying_target is None and result.plan.horizon_seconds is None
    else:
        assert result.plan.action == "HOLD"


@pytest.mark.parametrize(
    "change",
    [
        {"underlying_target": "602"},
        {"horizon_seconds": 30},
        {"condition": "NOW"},
        {"underlying_invalidation": "600"},
        {"scope": True, "candidate_index": 0},
        {"scope": False, "candidate_index": None},
        {"cycle_key": "position:123"},
        {"action": "ENTER"},
    ],
)
def test_shortlist_scripts_reject_replacement_terms(change):
    with pytest.raises(ValueError):
        ScopeShortlistDecision.model_validate(
            {"cycle_key": "degen:123", "delay_seconds": 1, "action": "SELECT", "candidate_index": 0}
            | change
        )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_shortlist_plan_rejects_full_geometry_and_post_cost_caps(right):
    req = original_request(right)
    p = req.packet
    o = p.opportunities[0]
    plan = ScopeShortlistPlan(
        decision_id=p.decision_id,
        packet_hash=fingerprint(p),
        action="ENTER",
        scope=False,
        candidate_id=o.candidate.candidate_id,
        evidence_ids=o.evidence_ids,
        thesis="Selection",
        uncertainty="Fixture",
    )
    with pytest.raises(ValueError):
        ScopeShortlistPlan.model_validate(plan.model_dump() | {"underlying_target": "602"})
    for now, account in [
        (p.valid_until, p.account),
        (p.as_of, p.account.model_copy(update={"cash": Decimal(0), "settled_cash": Decimal(0)})),
    ]:
        result = review_entry_plan(
            p, plan, quote=o.quote, underlying=o.underlying, account=account, now=now
        )
        assert result.outcome == "REJECTED"


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_native_b_paid_scope_fill_export(tmp_path, right):
    req = request(tmp_path, right=right)
    home = tmp_path / "run"
    report = asyncio.run(run_scope_model_replay(req, home))
    a = report["accounting"]
    assert report["arm"] == "B" and a["status"] == "COMPLETE_FLAT_ACCOUNTING"
    assert len(a["orders"]) == 2
    assert len(rows(home, "execution_fills")) == 2
    calls = rows(home, "execution_model_calls")
    assert len(calls) == 1 and Decimal(calls[0]["cost"]) > 0
    cycles = [json.loads(r["result_json"]) for r in rows(home, "execution_option_opportunities")]
    selected = next(c for c in cycles if "scope_paid_review" in c)
    assert selected["status"] == "OPEN" and selected["entry_timely"]
    assert selected["entry_result"]["plan"]["version"] == "shared-scope-shortlist-plan-v1"
    assert (
        selected["scope_fresh_candidate"]["binding"]["revision"]
        > selected["scope_candidate"]["binding"]["revision"]
    )
    assert rows(home, "execution_control")[0]["halted"] == 0
    export = json.loads((home / "native.json").read_text())
    assert (
        verify_scope_execution_export(export, report["export_hash"])["status"]
        == "VERIFIED_NATIVE_ACCOUNTING"
    )
    assert Decimal(a["net_after_all_costs"]) == Decimal(
        a["ledger"]["cash"]
    ) - req.execution.capital - Decimal(calls[0]["cost"]) - Decimal(".03")


@pytest.mark.parametrize("damage", ["none", "missing-receipt", "changed-receipt"])
def test_native_b_ordinary_choice_retains_proposal_and_native_exit(
    tmp_path, monkeypatch, damage, *, family="DEGEN"
):
    from datetime import timedelta

    from test_option_scope import AT
    from test_option_scope_arbitration import shared

    from app.options.scope_replay_enrollment import ScopeReplayEnrollment

    key = "degen:" + str(int((AT + timedelta(seconds=60)).timestamp()) // 300)
    script = ScopeShortlistScript(
        decisions=(
            ScopeShortlistDecision(
                cycle_key=key,
                delay_seconds=1,
                action="SELECT",
                candidate_index=0,
            ),
        )
    )
    model = ScopeShortlistModel(script)

    async def unused(play):
        raise AssertionError("Ordinary selection cannot refresh or substitute Scope")

    options = {
        "entry_policy": packet_for().policy.model_copy(
            update={"scope_selection": "scope-fixed-shortlist-v1"}
        ),
        "judgment_limits": JudgmentLimits(process_timeout_seconds=5, request_timeout_seconds=3),
        "scope_refresh": unused,
        "replay_model": model,
        "scope_replay": ScopeReplayEnrollment(
            tape_hash="a" * 64, request_hash="b" * 64, script_hash=fingerprint(script)
        ),
    }
    with shared(
        tmp_path,
        priority=("SCOPE", "SWING", "DEGEN") if family == "SWING" else ("SCOPE", "DEGEN"),
        costs=True,
        ai=True,
        coordinator_options=options,
    ) as (
        c,
        _v,
        times,
        frame,
    ):
        if damage != "none":
            dispatch = c.engine.dispatch

            async def altered(client_id, quote, underlying, *, now):
                with c.engine.journal.write() as db:
                    a = json.loads(
                        db.execute(
                            "SELECT approval_json FROM execution_orders WHERE client_id=?",
                            (client_id,),
                        ).fetchone()[0]
                    )
                    if damage == "missing-receipt":
                        del a["entry_request"]
                        del a["entry_result"]
                    else:
                        a["entry_result"]["plan"]["thesis"] = "changed"
                    db.execute(
                        "UPDATE execution_orders SET approval_json=? WHERE client_id=?",
                        (json.dumps(a), client_id),
                    )
                return await dispatch(client_id, quote, underlying, now=now)

            monkeypatch.setattr(c.engine, "dispatch", altered)

        async def cycle():
            task = asyncio.create_task(c.cycle(frame))
            waiter = asyncio.create_task(model.started.wait())
            await asyncio.wait((task, waiter), return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            assert not task.done(), task.result()
            times[0] = model.pending[0]
            model.pending[1].set_result(None)
            return await task

        result = asyncio.run(cycle())
        if damage != "none":
            assert result["status"] == "REJECTED", result
            with c.engine.journal.read() as db:
                assert db.execute("SELECT attempted_at FROM execution_orders").fetchone()[0] is None
                assert (
                    Decimal(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) > 0
                )
            return
        assert result["status"] == "OPEN", result
        original = next(
            o["candidate"]
            for o in result["entry_request"]["packet"]["opportunities"]
            if o["candidate"]["candidate_id"] == result["candidate_id"]
        )
        assert result["entry_review"]["proposal"] == original["proposal"]
        assert result["entry_review"]["exit_by"] is None
        assert result["scope_arbitration"]["selected"]["family"] == family
        with c.engine.journal.read() as db:
            order = dict(db.execute("SELECT * FROM execution_orders").fetchone())
        intent = json.loads(order["intent_json"])
        assert intent.get("entry_protection") is None
        assert (
            intent["original_underlying_invalidation"]
            == original["proposal"]["underlying_invalidation"]
        )
        assert intent["approval_expires_at"] <= original["admission"]["valid_until"]
        assert intent["quantity"] <= original["admission"]["quantity"]
        assert order["attempted_at"] is not None


@pytest.mark.parametrize("variant", ["late", "hold", "unknown", "missing", "stale"])
def test_native_b_rejected_entry_keeps_charge_and_deadline(tmp_path, monkeypatch, variant):
    import test_option_scope_model_replay as original

    monkeypatch.setattr(original, "request", request)
    original.test_rejected_entry_never_erases_charges_or_creates_fills(tmp_path, variant)


def test_native_b_swing_preserves_locked_terms(tmp_path, monkeypatch):
    test_native_b_ordinary_choice_retains_proposal_and_native_exit(
        tmp_path, monkeypatch, "none", family="SWING"
    )
