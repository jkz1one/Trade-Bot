"""Bounded mixed response fixtures; the native owner alone admits and executes."""

import asyncio
from datetime import timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.execution.economics import UsageEvidence
from app.options import entry_judgment, position_judgment
from app.options.engine import fingerprint
from app.options.entry_reasoning import plan_class
from app.options.models import Money, Name, OptionRecord
from app.options.position_reasoning import PositionPlan


class MixedScriptedDecision(OptionRecord):
    cycle_key: Name = Field(pattern=r"^(degen|position):[0-9]+$")
    delay_seconds: int = Field(ge=0, le=600, strict=True)
    action: Literal["HOLD", "SELECT", "ENTER", "UNKNOWN", "MAINTAIN", "TIGHTEN", "EXIT_ALL"]
    asset: Literal["STOCK", "OPTION", "SCOPE"] | None = None
    candidate_index: int | None = Field(default=None, ge=0, le=63, strict=True)
    input_tokens: int = Field(default=1000, gt=0, le=1000000, strict=True)
    output_tokens: int = Field(default=100, ge=0, le=1000000, strict=True)
    condition: Literal["NOW", "ABOVE", "BELOW"] | None = None
    underlying_trigger: Money | None = Field(default=None, gt=0)
    underlying_invalidation: Money | None = Field(default=None, gt=0)
    underlying_target: Money | None = Field(default=None, gt=0)
    horizon_seconds: int | None = Field(default=None, gt=0, le=5184000, strict=True)

    @model_validator(mode="after")
    def exact_role(self):
        selected = self.action in {"SELECT", "ENTER"}
        if (
            selected != (self.asset is not None)
            or (selected and self.asset != "SCOPE") != (self.candidate_index is not None)
            or (
                self.action != "UNKNOWN"
                and self.cycle_key.startswith("position:")
                != (self.action in {"MAINTAIN", "TIGHTEN", "EXIT_ALL"})
            )
        ):
            raise ValueError("Exact mixed entry/management role and supplied choice required")
        terms = (
            self.condition,
            self.underlying_trigger,
            self.underlying_invalidation,
            self.underlying_target,
            self.horizon_seconds,
        )
        if self.action == "ENTER" and self.asset == "OPTION":
            if any(x is None for x in (terms[0], *terms[2:])) or (
                (self.condition == "NOW") != (self.underlying_trigger is None)
            ):
                raise ValueError("Full C/D ordinary option proposal required")
        elif self.action == "TIGHTEN":
            if self.underlying_invalidation is None or any(
                x is not None for x in (*terms[:2], *terms[3:])
            ):
                raise ValueError("Management can only tighten the current stop")
        elif any(x is not None for x in terms):
            raise ValueError("Original stock/Scope and shortlist terms cannot be replaced")
        return self


class MixedReplayScript(OptionRecord):
    version: Literal["scripted-mixed-judgment-v1"] = "scripted-mixed-judgment-v1"
    evidence_kind: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    arm: Literal["B", "C", "D"]
    decisions: tuple[MixedScriptedDecision, ...] = Field(max_length=1000)

    @model_validator(mode="after")
    def roles(self):
        allowed = (
            {"HOLD", "SELECT", "UNKNOWN"}
            if self.arm == "B"
            else {"HOLD", "ENTER", "UNKNOWN"}
            if self.arm == "C"
            else {"HOLD", "ENTER", "UNKNOWN", "MAINTAIN", "TIGHTEN", "EXIT_ALL"}
        )
        if len({d.cycle_key for d in self.decisions}) != len(self.decisions) or any(
            d.action not in allowed or (self.arm != "D" and d.cycle_key.startswith("position:"))
            for d in self.decisions
        ):
            raise ValueError("Unique mixed script slots and exact B/C/D roles required")
        return self


class MixedReplayModel:
    """Receives full immutable requests only; no venue, account, tape or credentials."""

    def __init__(self, script):
        self.script = MixedReplayScript.model_validate(script.model_dump(warnings=False))
        self.started = asyncio.Event()
        self.pending = None
        self.used = set()

    def configuration(self):
        return self.script.model_dump(mode="json")

    async def run(self, request):
        request, protocol, _managed = _request(self.script, request)
        p, key = request.packet, request.packet.cycle_key
        if key in self.used or self.pending is not None:
            raise ValueError("Mixed response cannot repeat or overlap")
        self.used.add(key)
        decision = next((d for d in self.script.decisions if d.cycle_key == key), None)
        if decision is None:
            return protocol.result_for(request, error="ScriptMissing")
        ready = asyncio.get_running_loop().create_future()
        self.pending = (p.as_of + timedelta(seconds=decision.delay_seconds), ready)
        self.started.set()
        try:
            await ready
        finally:
            self.pending = None
            self.started.clear()
        return response_for(self.script, request)


def _request(script, request):
    if type(request) is entry_judgment.EntryRequest:
        protocol, managed = entry_judgment, False
        request = protocol.EntryRequest.model_validate(request.model_dump(warnings=False))
        if request.packet.policy.mixed_selection != "mixed-paid-entry-v1" or (
            (request.packet.policy.mixed_shortlist is not None) != (script.arm == "B")
        ):
            raise ValueError("Exact mixed full/choice-only entry contract required")
    elif type(request) is position_judgment.PositionRequest:
        protocol, managed = position_judgment, True
        request = protocol.PositionRequest.model_validate(request.model_dump(warnings=False))
        if script.arm != "D" or (
            request.packet.policy.mixed_management != "mixed-stock-position-v1"
        ):
            raise ValueError("Exact mixed D management contract required")
    else:
        raise ValueError("Complete native mixed model request required")
    if len(request.model_dump_json().encode()) > protocol.MAX_REQUEST_BYTES:
        raise ValueError("Mixed replay request capacity exceeded")
    return request, protocol, managed


def response_for(script, request):
    """Pure exact response reconstruction for portable review; no clock or authority."""
    script = MixedReplayScript.model_validate(script.model_dump(warnings=False))
    request, protocol, managed = _request(script, request)
    p = request.packet
    decision = next((d for d in script.decisions if d.cycle_key == p.cycle_key), None)
    if decision is None:
        return protocol.result_for(request, error="ScriptMissing")
    if decision.action == "UNKNOWN":
        return protocol.result_for(request, error="ScriptedUnknown")
    usage = UsageEvidence(
        request_id="mixed-fixture-" + fingerprint({"script": script, "request": request}),
        model=request.configuration.costs.model,
        input_tokens=decision.input_tokens,
        output_tokens=decision.output_tokens,
    )
    try:
        if managed:
            plan = PositionPlan(
                decision_id=p.decision_id,
                packet_hash=fingerprint(p),
                entry_client_id=p.position.entry_client_id,
                position_revision=p.position_revision,
                action=decision.action,
                underlying_invalidation=decision.underlying_invalidation,
                evidence_ids=(p.evidence_ids[0], p.evidence_ids[5]),
                thesis="Scripted mixed management; not authentic model evidence",
                change_since_entry="Review the supplied completed context and original thesis",
                uncertainty="Synthetic usage; native protection remains independent",
            )
        elif decision.action == "HOLD":
            plan = protocol.hold(p)
        else:
            geometry = {}
            if decision.asset == "SCOPE":
                if p.scope is None:
                    raise ValueError("No supplied Scope plan")
                candidate = fingerprint(p.scope.model_dump(mode="json"))
                evidence = (candidate,)
            elif decision.asset == "STOCK":
                o = p.stocks[decision.candidate_index]
                candidate, evidence = o.candidate.candidate_id, (fingerprint(o),)
            else:
                o = p.opportunities[decision.candidate_index]
                candidate, evidence = o.candidate.candidate_id, o.evidence_ids
                if script.arm != "B":
                    geometry = decision.model_dump(
                        include={
                            "condition",
                            "underlying_trigger",
                            "underlying_invalidation",
                            "underlying_target",
                            "horizon_seconds",
                        }
                    )
            plan = plan_class(p.policy)(
                decision_id=p.decision_id,
                packet_hash=fingerprint(p),
                action="ENTER",
                stock=decision.asset == "STOCK",
                scope=decision.asset == "SCOPE",
                candidate_id=candidate,
                evidence_ids=evidence,
                thesis="Scripted mixed entry; not authentic model evidence",
                uncertainty="Synthetic response; paid native reapproval still required",
                **geometry,
            )
        return protocol.validate_result(
            request,
            protocol.result_for(request, plan=plan, usage=usage, count=decision.input_tokens),
        )
    except (ValueError, IndexError):
        return protocol.result_for(
            request, usage=usage, count=decision.input_tokens, error="ScriptedPlanRejected"
        )
