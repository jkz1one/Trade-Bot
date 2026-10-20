"""Tool-less C/D response fixtures; execution requires separate frozen tape enrollment."""

import asyncio
from datetime import timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.execution.economics import UsageEvidence
from app.options import entry_judgment, position_judgment
from app.options.engine import fingerprint
from app.options.entry_reasoning import SharedScopeEntryPlan
from app.options.models import Money, Name, OptionRecord
from app.options.position_reasoning import PositionPlan
from app.options.replay_model import ScriptedDecision


class ScopeScriptedDecision(OptionRecord):
    cycle_key: Name = Field(pattern=r"^(degen|position):[0-9]+$")
    delay_seconds: int = Field(ge=0, le=600, strict=True)
    action: Literal["HOLD", "ENTER", "UNKNOWN", "MAINTAIN", "EXIT_ALL", "TIGHTEN"]
    scope: bool = Field(default=False, strict=True)
    candidate_index: int | None = Field(default=None, ge=0, le=23, strict=True)
    input_tokens: int = Field(default=1000, gt=0, le=1000000, strict=True)
    output_tokens: int = Field(default=100, ge=0, le=1000000, strict=True)
    condition: Literal["NOW", "ABOVE", "BELOW"] | None = None
    underlying_trigger: Money | None = Field(default=None, gt=0)
    underlying_invalidation: Money | None = Field(default=None, gt=0)
    underlying_target: Money | None = Field(default=None, gt=0)
    horizon_seconds: int | None = Field(default=None, gt=0, le=21600, strict=True)

    @model_validator(mode="after")
    def contract(self):
        managed = self.cycle_key.startswith("position:")
        if self.action != "UNKNOWN" and managed != (
            self.action in {"MAINTAIN", "EXIT_ALL", "TIGHTEN"}
        ):
            raise ValueError("Script action must match its original entry/position slot")
        if self.scope:
            if (
                self.action != "ENTER"
                or self.candidate_index is not None
                or any(
                    x is not None
                    for x in (
                        self.condition,
                        self.underlying_trigger,
                        self.underlying_invalidation,
                        self.underlying_target,
                        self.horizon_seconds,
                    )
                )
            ):
                raise ValueError("Scope selects only the supplied fixed plan")
        else:
            if (self.action == "ENTER") != (self.candidate_index is not None):
                raise ValueError("Only ordinary ENTER selects an indexed opportunity")
            ScriptedDecision.model_validate(
                self.model_dump(exclude={"scope", "candidate_index"})
                | {"candidate_index": self.candidate_index or 0}
            )
        return self


class ScopeReplayScript(OptionRecord):
    version: Literal["scripted-scope-judgment-v1"] = "scripted-scope-judgment-v1"
    evidence_kind: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    arm: Literal["C", "D"]
    decisions: tuple[ScopeScriptedDecision, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def slots(self):
        if len({d.cycle_key for d in self.decisions}) != len(self.decisions) or (
            self.arm == "C" and any(d.cycle_key.startswith("position:") for d in self.decisions)
        ):
            raise ValueError("Unique slots and D-only management required")
        return self


class MatchedScopeScripts(OptionRecord):
    """Declaration only: matching scripts never copy one owner's reached decisions."""

    version: Literal["matched-scope-scripts-v1"] = "matched-scope-scripts-v1"
    entry: ScopeReplayScript
    managed: ScopeReplayScript

    @model_validator(mode="after")
    def matched(self):
        if (
            self.entry.arm != "C"
            or self.managed.arm != "D"
            or {d.cycle_key: d for d in self.entry.decisions}
            != {d.cycle_key: d for d in self.managed.decisions if d.cycle_key.startswith("degen:")}
        ):
            raise ValueError("C/D entry choices, timing, geometry and usage must match")
        return self


class ScopeReplayModel:
    """Only full typed requests enter; only nonauthoritative model receipts leave.

    The enrolled tape scheduler delivers market receipts before releasing `pending`.
    This class owns no clock, tape, account, venue, credentials or cost settlement.
    Coordinators reject this adapter without explicit full Scope tape enrollment.
    """

    def __init__(self, script):
        self.script = ScopeReplayScript.model_validate(script.model_dump(warnings=False))
        self.started = asyncio.Event()
        self.pending = None
        self.used = set()

    def configuration(self):
        return self.script.model_dump(mode="json")

    async def run(self, request):
        if type(request) is entry_judgment.EntryRequest:
            protocol = entry_judgment
            request = protocol.EntryRequest.model_validate(request.model_dump(warnings=False))
            if request.packet.policy.scope_selection != "scope-fixed-plan-v1":
                raise ValueError("Explicit shared Scope entry request required")
            managed = False
        elif type(request) is position_judgment.PositionRequest:
            protocol = position_judgment
            request = protocol.PositionRequest.model_validate(request.model_dump(warnings=False))
            if (
                self.script.arm != "D"
                or request.packet.policy.scope_management != "scope-fixed-position-v1"
            ):
                raise ValueError("Explicit D shared Scope management request required")
            managed = True
        else:
            raise ValueError("Full shared Scope request required")
        if len(request.model_dump_json().encode()) > protocol.MAX_REQUEST_BYTES:
            raise ValueError("Bounded shared Scope request required")
        p = request.packet
        key = p.cycle_key
        if key in self.used or self.pending is not None:
            raise ValueError("Scripted opportunity cannot replay or overlap")
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
        if decision.action == "UNKNOWN":
            return protocol.result_for(request, error="ScriptedUnknown")
        usage = UsageEvidence(
            request_id="scope-fixture-"
            + fingerprint({"script": self.script, "request_id": request.request_id, "packet": p}),
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
                    thesis="Scripted management; not authentic model evidence",
                    change_since_entry="Review only the supplied completed context",
                    uncertainty="Synthetic usage and response; native protection remains required",
                )
            elif decision.action == "HOLD":
                plan = protocol.hold(p)
            else:
                if decision.scope:
                    if p.scope is None:
                        raise ValueError("No supplied Scope plan")
                    candidate = fingerprint(p.scope.model_dump(mode="json"))
                    evidence = (candidate,)
                    geometry = {}
                else:
                    opportunity = p.opportunities[decision.candidate_index]
                    candidate, evidence = (
                        opportunity.candidate.candidate_id,
                        opportunity.evidence_ids,
                    )
                    geometry = decision.model_dump(
                        include={
                            "condition",
                            "underlying_trigger",
                            "underlying_invalidation",
                            "underlying_target",
                            "horizon_seconds",
                        }
                    )
                plan = SharedScopeEntryPlan(
                    decision_id=p.decision_id,
                    packet_hash=fingerprint(p),
                    action="ENTER",
                    scope=decision.scope,
                    candidate_id=candidate,
                    evidence_ids=evidence,
                    thesis="Scripted entry; not authentic model evidence",
                    uncertainty="Synthetic usage and response; fresh native approval remains required",
                    **geometry,
                )
            result = protocol.result_for(
                request, plan=plan, usage=usage, count=decision.input_tokens
            )
            return protocol.validate_result(request, result)
        except (ValueError, IndexError):
            # A supplied but invalid proposal is still a known synthetic charge.
            # Missing/UNKNOWN scripts above never invent a zero or estimated receipt.
            return protocol.result_for(
                request, usage=usage, count=decision.input_tokens, error="ScriptedPlanRejected"
            )
