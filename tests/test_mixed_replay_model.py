"""Full mixed requests, choice-only B and reproducible nonauthoritative responses."""

import asyncio

import pytest
from test_mixed_native_owner import changed
from test_option_entry_reasoning import packet_for, plan_for

from app.execution.economics import CostPolicy
from app.execution.judgment import JudgmentLimits
from app.mixed.replay_model import (
    MixedReplayModel,
    MixedReplayScript,
    MixedScriptedDecision,
    response_for,
)
from app.options import entry_judgment as j
from app.options.engine import fingerprint
from app.options.entry_reasoning import plan_class, review_entry_plan


def request(arm):
    packet = packet_for()
    policy = changed(
        packet.policy,
        mixed_selection="mixed-paid-entry-v1",
        mixed_shortlist="mixed-choice-only-v1" if arm == "B" else None,
    )
    config = j.configuration(
        CostPolicy(total_budget="10", daily_budget="2", max_call_cost=".01"),
        JudgmentLimits(process_timeout_seconds=5, request_timeout_seconds=3),
        policy,
    )
    packet = changed(packet, policy=policy, model_configuration_hash=fingerprint(config))
    return j.create_request(packet, config, request_id="a" * 32, now=packet.as_of)


@pytest.mark.parametrize("arm", ["B", "C", "D"])
def test_complete_response_contract_and_native_option_review(arm):
    r = request(arm)
    values = (
        {}
        if arm == "B"
        else plan_for(r.packet).model_dump(
            include={
                "condition",
                "underlying_trigger",
                "underlying_invalidation",
                "underlying_target",
                "horizon_seconds",
            }
        )
    )
    decision = MixedScriptedDecision(
        cycle_key=r.packet.cycle_key,
        delay_seconds=2,
        action="SELECT" if arm == "B" else "ENTER",
        asset="OPTION",
        candidate_index=0,
        **values,
    )
    script = MixedReplayScript(arm=arm, decisions=(decision,))
    model = MixedReplayModel(script)

    async def exercise():
        task = asyncio.create_task(model.run(r))
        await model.started.wait()
        assert (model.pending[0] - r.packet.as_of).total_seconds() == 2
        model.pending[1].set_result(None)
        result = await task
        assert result == response_for(script, r)
        assert result.usage is not None and result.error is None
        assert not result.execution_authority
        with pytest.raises(ValueError, match="repeat"):
            await model.run(r)
        return result

    result = asyncio.run(exercise())
    o = r.packet.opportunities[0]
    reviewed = review_entry_plan(
        r.packet,
        result.plan,
        quote=o.quote,
        underlying=o.underlying,
        account=r.packet.account,
        now=r.packet.as_of,
    )
    assert reviewed.outcome == "ELIGIBLE"
    if arm == "B":
        assert reviewed.proposal == o.candidate.proposal
        assert reviewed.exit_by is None
        assert result.plan.underlying_target is None and result.plan.horizon_seconds is None


@pytest.mark.parametrize("field", ["underlying_target", "horizon_seconds", "stock"])
def test_choice_only_schema_cannot_smuggle_geometry_or_hold_asset(field):
    r = request("B")
    values = j.hold(r.packet).model_dump()
    values[field] = (
        "605" if field == "underlying_target" else 100 if field == "horizon_seconds" else True
    )
    with pytest.raises(ValueError):
        plan_class(r.packet.policy).model_validate(values)


@pytest.mark.parametrize("mode", ["missing", "unknown", "invalid_choice"])
def test_response_failures_preserve_known_and_unknown_usage(mode):
    r = request("C")
    values = {"cycle_key": r.packet.cycle_key, "delay_seconds": 0, "action": "UNKNOWN"}
    if mode == "invalid_choice":
        values.update(action="ENTER", asset="STOCK", candidate_index=0)
    script = MixedReplayScript(
        arm="C", decisions=() if mode == "missing" else (MixedScriptedDecision(**values),)
    )
    result = response_for(script, r)
    assert result.plan.action == "HOLD" and result.error is not None
    assert (result.usage is not None) == (mode == "invalid_choice")


def test_old_request_cannot_enter_new_mixed_adapter():
    from test_option_entry_judgment import request_for as old_request

    script = MixedReplayScript(arm="C", decisions=())
    with pytest.raises(ValueError, match="mixed"):
        asyncio.run(MixedReplayModel(script).run(old_request()))


@pytest.mark.parametrize("damage", ["legacy", "subclass", "script", "duplicate_tape"])
def test_only_exact_complete_mixed_adapter_can_receive_native_enrollment(damage):
    from app.mixed.replay_enrollment import MixedReplayEnrollment, validate_adapter
    from app.options.replay_model import ReplayModel, ReplayScript

    script = MixedReplayScript(arm="C", decisions=())
    enrollment = {
        "tape_hashes": ("a" * 64,),
        "request_hash": "b" * 64,
        "script_hash": fingerprint(script),
    }
    if damage == "duplicate_tape":
        enrollment["tape_hashes"] *= 2
    elif damage == "script":
        enrollment["script_hash"] = "c" * 64

    class Derived(MixedReplayModel):
        pass

    adapter = (
        ReplayModel(ReplayScript(arm="C", decisions=()))
        if damage == "legacy"
        else Derived(script)
        if damage == "subclass"
        else MixedReplayModel(script)
    )
    with pytest.raises(ValueError):
        validate_adapter(MixedReplayEnrollment(**enrollment), adapter)
