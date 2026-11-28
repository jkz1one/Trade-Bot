"""New carry adapters cannot broaden old scripts or native shortlist owners."""

import pytest
from test_option_entry_reasoning import packet_for

from app.options import entry_judgment
from app.options.engine import fingerprint
from app.options.entry_reasoning import EntryReasoningPolicy, plan_class
from app.options.scope_carry_replay_model import (
    ScopeCarryDecision,
    ScopeCarryReplayModel,
    ScopeCarryScript,
    ScopeCarryShortlistModel,
    ScopeCarryShortlistScript,
)
from app.options.scope_replay_enrollment import (
    ScopeCarrySeriesEnrollment,
    ScopeSeriesEnrollment,
    validate_adapter,
)
from app.options.scope_replay_model import (
    ScopeReplayModel,
    ScopeReplayScript,
    ScopeScriptedDecision,
)
from app.options.scope_shortlist_replay import ScopeShortlistDecision


def test_b_carry_requires_new_marker_and_rejects_all_geometry():
    p = packet_for().policy.model_dump() | {
        "scope_selection": "scope-fixed-shortlist-v1",
        "scope_carry": "shared-scope-carry-v1",
        "max_carry_horizon_seconds": 600000,
    }
    with pytest.raises(ValueError):
        EntryReasoningPolicy.model_validate(p)
    policy = EntryReasoningPolicy.model_validate(
        p | {"scope_carry_shortlist": "scope-carry-shortlist-v1"}
    )
    assert entry_judgment.prompt_version(policy) == "shared-scope-carry-shortlist-v1"
    assert "without a replacement horizon" in entry_judgment.instructions(policy)
    value = {
        "decision_id": "a" * 64,
        "packet_hash": "b" * 64,
        "candidate_id": "c" * 64,
        "evidence_ids": ("c" * 64,),
        "action": "ENTER",
        "scope": False,
        "thesis": "Choice only",
        "uncertainty": "Unknown overnight path",
    }
    plan = plan_class(policy)(**value)
    assert plan.version == "shared-scope-carry-shortlist-plan-v1"
    for field in (
        "underlying_trigger",
        "underlying_target",
        "underlying_invalidation",
        "horizon_seconds",
    ):
        with pytest.raises(ValueError):
            plan_class(policy)(**value, **{field: 1})
    with pytest.raises(ValueError):
        EntryReasoningPolicy.model_validate(
            policy.model_dump() | {"scope_selection": "scope-fixed-plan-v1"}
        )


def test_full_script_long_horizon_is_new_but_scope_terms_stay_fixed():
    raw = {
        "cycle_key": "degen:123",
        "delay_seconds": 1,
        "action": "ENTER",
        "candidate_index": 0,
        "condition": "NOW",
        "underlying_invalidation": "600",
        "underlying_target": "605",
        "horizon_seconds": 279600,
    }
    assert ScopeCarryDecision(**raw).horizon_seconds == 279600
    with pytest.raises(ValueError):
        ScopeScriptedDecision(**raw)
    with pytest.raises(ValueError):
        ScopeCarryDecision(**(raw | {"scope": True, "candidate_index": None}))
    with pytest.raises(ValueError):
        ScopeShortlistDecision(
            cycle_key="degen:123",
            delay_seconds=1,
            action="SELECT",
            candidate_index=0,
            horizon_seconds=279600,
        )


@pytest.mark.parametrize("arm", ["B", "C", "D"])
def test_exact_adapter_and_script_enrollment_cannot_cross_cohorts(arm):
    script = (
        ScopeCarryShortlistScript(decisions=())
        if arm == "B"
        else ScopeCarryScript(arm=arm, decisions=())
    )
    adapter = (ScopeCarryShortlistModel if arm == "B" else ScopeCarryReplayModel)(script)
    args = {
        "tape_hashes": ("a" * 64, "b" * 64),
        "request_hash": "c" * 64,
        "script_hash": fingerprint(script),
    }
    enrolled = ScopeCarrySeriesEnrollment(**args)
    assert validate_adapter(enrolled, adapter) == enrolled
    with pytest.raises(ValueError):
        validate_adapter(ScopeSeriesEnrollment(**args), adapter)
    old = ScopeReplayModel(ScopeReplayScript(arm="C", decisions=()))
    with pytest.raises(ValueError):
        validate_adapter(enrolled.model_copy(update={"script_hash": fingerprint(old.script)}), old)
    with pytest.raises(ValueError):
        validate_adapter(enrolled.model_copy(update={"script_hash": "d" * 64}), adapter)
