"""Full typed Scope response fixtures, without enabling native replay authority."""

import asyncio
from datetime import timedelta

import pytest
from test_option_entry_reasoning import plan_for
from test_option_scope_ai import ai_owner
from test_option_scope_position import enter, fake_model

from app.options import entry_judgment, position_judgment
from app.options.engine import fingerprint
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.scope_replay_model import (
    MatchedScopeScripts,
    ScopeReplayModel,
    ScopeReplayScript,
    ScopeScriptedDecision,
)


@pytest.fixture(scope="module", params=["CALL", "PUT"])
def requests(tmp_path_factory, request):
    with (
        pytest.MonkeyPatch.context() as mp,
        ai_owner(
            tmp_path_factory.mktemp("scope-" + request.param),
            mp,
            right=request.param,
            position_policy=PositionReasoningPolicy(
                max_lease_seconds=5, scope_management="scope-fixed-position-v1"
            ),
        ) as (c, v, times, frame, state),
    ):
        _, current = enter(c, v, times, frame)
        entry = state["request"]
        calls = fake_model(mp, "MAINTAIN")
        assert asyncio.run(c.cycle(current))["status"] == "MAINTAIN"
        position = calls[0][0]
    return entry, position


def decision(request, action="ENTER", **changes):
    values = {"cycle_key": request.packet.cycle_key, "action": action, "delay_seconds": 1}
    if action == "ENTER":
        values["scope"] = True
    return ScopeScriptedDecision(**(values | changes))


def model(d, arm="D"):
    return ScopeReplayModel(ScopeReplayScript(arm=arm, decisions=(d,)))


async def release(m, request):
    task = asyncio.create_task(m.run(request))
    waiting = asyncio.create_task(m.started.wait())
    await asyncio.wait((task, waiting), return_when=asyncio.FIRST_COMPLETED)
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    if task.done():
        await task
    assert not task.done()
    at, ready = m.pending
    assert at == request.packet.as_of + timedelta(seconds=m.script.decisions[0].delay_seconds)
    ready.set_result(None)
    result = await task
    assert m.pending is None and not m.started.is_set()
    return result


@pytest.mark.parametrize("arm", ["C", "D"])
def test_fixed_scope_contract_preserves_original_request_and_known_usage(requests, arm):
    request = requests[0]
    original = request.model_dump_json()
    m = model(decision(request), arm)
    result = asyncio.run(release(m, request))
    assert entry_judgment.validate_result(request, result) == result
    assert result.error is None and result.plan.scope
    assert result.plan.candidate_id == fingerprint(request.packet.scope.model_dump(mode="json"))
    assert result.plan.evidence_ids == (result.plan.candidate_id,)
    assert all(
        getattr(result.plan, key) is None
        for key in (
            "condition",
            "underlying_trigger",
            "underlying_invalidation",
            "underlying_target",
            "horizon_seconds",
        )
    )
    assert result.usage.input_tokens == 1000 and result.usage.output_tokens == 100
    assert not result.execution_authority
    assert request.model_dump_json() == original
    with pytest.raises(ValueError, match="replay or overlap"):
        asyncio.run(m.run(request))


@pytest.mark.parametrize("kind", ["ordinary", "hold", "no-scope-hold", "no-scope-enter"])
def test_shared_entry_alternatives_are_typed_and_invalid_selection_retains_charge(requests, kind):
    request = requests[0]
    if kind.startswith("no-scope"):
        request = request.model_copy(
            update={"packet": request.packet.model_copy(update={"scope": None})}
        )
    d = decision(request, "HOLD" if kind.endswith("hold") else "ENTER")
    if kind == "ordinary":
        geometry = plan_for(request.packet).model_dump(
            include={
                "condition",
                "underlying_trigger",
                "underlying_invalidation",
                "underlying_target",
                "horizon_seconds",
            }
        )
        d = decision(request, scope=False, candidate_index=0, **geometry)
    result = asyncio.run(release(model(d), request))
    assert result.usage is not None
    assert entry_judgment.validate_result(request, result) == result
    if kind == "no-scope-enter":
        assert result.error == "ScriptedPlanRejected" and result.plan.action == "HOLD"
    else:
        assert result.error is None and not result.plan.scope
        assert result.plan.action == ("ENTER" if kind == "ordinary" else "HOLD")


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_management_preserves_owned_entry_revision_context_and_deadline(requests, action):
    request = requests[1]
    p = request.packet
    stop = (
        p.position.tightened_underlying_invalidation
        + (p.underlying.bid if p.position.contract.right == "CALL" else p.underlying.ask)
    ) / 2
    d = decision(
        request, action, **({"underlying_invalidation": stop} if action == "TIGHTEN" else {})
    )
    before = request.model_dump_json()
    result = asyncio.run(release(model(d), request))
    assert position_judgment.validate_result(request, result) == result
    assert result.error is None and result.plan.action == action
    assert result.plan.entry_client_id == p.position.entry_client_id
    assert result.plan.position_revision == p.position_revision
    assert result.plan.packet_hash == fingerprint(p)
    assert result.plan.evidence_ids == (p.evidence_ids[0], p.evidence_ids[5])
    assert not result.execution_authority
    assert request.model_dump_json() == before


@pytest.mark.parametrize("role", [0, 1])
@pytest.mark.parametrize("kind", ["unknown", "missing", "late", "cancel"])
def test_virtual_completion_never_refreshes_deadlines_or_invents_unknown_usage(
    requests, role, kind
):
    request = requests[role]
    action = "MAINTAIN" if role else "ENTER"
    d = decision(
        request,
        "UNKNOWN" if kind == "unknown" else action,
        delay_seconds=600 if kind == "late" else 1,
    )
    m = model(d)

    async def run():
        if kind == "missing":
            empty = ScopeReplayModel(ScopeReplayScript(arm="D", decisions=()))
            result = await empty.run(request)
            assert result.error == "ScriptMissing" and result.usage is None
            with pytest.raises(ValueError):
                await empty.run(request)
            return
        if kind == "cancel":
            task = asyncio.create_task(m.run(request))
            await m.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert m.pending is None and not m.started.is_set()
            with pytest.raises(ValueError):
                await m.run(request)
            return
        original = request.model_dump_json()
        result = await release(m, request)
        assert request.model_dump_json() == original
        if kind == "unknown":
            assert result.error == "ScriptedUnknown" and result.usage is None
            assert result.counted_input_tokens is None
        else:
            assert (
                d.delay_seconds
                > (request.packet.valid_until - request.packet.as_of).total_seconds()
            )
            assert result.error is None and result.usage is not None

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["candidate", "geometry", "usage", "widen"])
def test_rejected_proposals_keep_usage_in_safe_full_receipts(requests, damage):
    request = requests[1 if damage == "widen" else 0]
    if damage == "widen":
        p = request.packet
        stop = p.position.tightened_underlying_invalidation + (
            -1 if p.position.contract.right == "CALL" else 1
        )
        d = decision(request, "TIGHTEN", underlying_invalidation=stop)
    elif damage == "usage":
        d = decision(request, input_tokens=1000000)
    else:
        geometry = plan_for(request.packet).model_dump(
            include={
                "condition",
                "underlying_trigger",
                "underlying_invalidation",
                "underlying_target",
                "horizon_seconds",
            }
        )
        if damage == "geometry":
            geometry["underlying_target"] = "100000"
        d = decision(
            request, scope=False, candidate_index=23 if damage == "candidate" else 0, **geometry
        )
    result = asyncio.run(release(model(d), request))
    assert result.error == "ScriptedPlanRejected" and result.usage is not None
    assert result.plan.action == ("MAINTAIN" if damage == "widen" else "HOLD")
    assert result.usage.input_tokens == d.input_tokens


def test_full_request_revalidation_overlap_and_receipt_binding(requests):
    request, position = requests
    d = decision(request)
    m = model(d)

    async def run():
        bad = request.model_copy(
            update={
                "packet": request.packet.model_copy(update={"valid_until": request.packet.as_of})
            }
        )
        with pytest.raises(ValueError):
            await m.run(bad)
        assert not m.used and m.pending is None
        task = asyncio.create_task(m.run(request))
        await m.started.wait()
        with pytest.raises(ValueError, match="overlap"):
            await m.run(position)
        assert position.packet.cycle_key not in m.used
        m.pending[1].set_result(None)
        result = await task
        changed = request.model_copy(update={"request_id": "f" * 32})
        other = await release(model(d), changed)
        assert other.usage.request_id != result.usage.request_id
        with pytest.raises(ValueError):
            entry_judgment.validate_result(changed, result)

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage",
    ["geometry", "index", "scope-hold", "role", "duplicate", "c-management", "b-arm", "extra"],
)
def test_script_contract_rejects_ambiguous_or_authoritative_inputs(damage):
    values = {"cycle_key": "degen:1", "delay_seconds": 0, "action": "ENTER", "scope": True}
    if damage == "geometry":
        values["horizon_seconds"] = 1
    elif damage == "index":
        values["candidate_index"] = 0
    elif damage == "scope-hold":
        values["action"] = "HOLD"
    elif damage == "role":
        values["cycle_key"] = "position:1"
    elif damage == "extra":
        values["quantity"] = 2
    with pytest.raises(ValueError):
        if damage in {"duplicate", "b-arm", "c-management"}:
            d = ScopeScriptedDecision(**values)
            if damage == "c-management":
                d = ScopeScriptedDecision(
                    cycle_key="position:1", delay_seconds=0, action="MAINTAIN"
                )
            ScopeReplayScript(
                arm="B" if damage == "b-arm" else "C",
                decisions=(d, d) if damage == "duplicate" else (d,),
            )
        else:
            ScopeScriptedDecision(**values)


@pytest.mark.parametrize(
    "damage", [None, "delay_seconds", "input_tokens", "output_tokens", "scope", "missing", "arms"]
)
def test_cd_entries_match_all_declared_terms_and_usage(damage):
    d = ScopeScriptedDecision(cycle_key="degen:1", delay_seconds=0, action="ENTER", scope=True)
    c = ScopeReplayScript(arm="C", decisions=(d,))
    position = ScopeScriptedDecision(cycle_key="position:2", delay_seconds=0, action="MAINTAIN")
    other = d
    if damage in {"delay_seconds", "input_tokens", "output_tokens"}:
        other = d.model_copy(update={damage: getattr(d, damage) + 1})
    elif damage == "scope":
        other = ScopeScriptedDecision(cycle_key="degen:1", delay_seconds=0, action="HOLD")
    managed = ScopeReplayScript(
        arm="D", decisions=(position,) if damage == "missing" else (position, other)
    )
    if damage:
        with pytest.raises(ValueError):
            MatchedScopeScripts(entry=managed if damage == "arms" else c, managed=managed)
    else:
        pair = MatchedScopeScripts(entry=c, managed=managed)
        assert MatchedScopeScripts.model_validate_json(pair.model_dump_json()) == pair


def test_legacy_and_unenrolled_requests_remain_rejected():
    from test_option_entry_judgment import request_for
    from test_option_position_judgment import request_for as position_request

    m = ScopeReplayModel(ScopeReplayScript(arm="D", decisions=()))
    for request in (request_for(), position_request(), object()):
        with pytest.raises(ValueError):
            asyncio.run(m.run(request))
    assert not m.used


@pytest.mark.parametrize("arm", ["C", "D"])
def test_new_contract_is_not_execution_enrollment(tmp_path, arm):
    from test_option_entry_reasoning import packet_for
    from test_option_scope_arbitration import shared

    from app.execution.judgment import JudgmentLimits

    async def refresh(_play):
        raise AssertionError("No fresh-input reader before native enrollment")

    with (
        pytest.raises(ValueError, match="Shared Scope AI requires full entry configuration"),
        shared(
            tmp_path,
            costs=True,
            ai=True,
            coordinator_options={
                "entry_policy": packet_for().policy.model_copy(
                    update={"scope_selection": "scope-fixed-plan-v1"}
                ),
                "judgment_limits": JudgmentLimits(),
                "key_file": tmp_path / "unused-private-key",
                "scope_refresh": refresh,
                "replay_model": ScopeReplayModel(ScopeReplayScript(arm=arm, decisions=())),
            },
        ),
    ):
        pytest.fail("Response contract gained native execution enrollment")
