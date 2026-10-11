"""Explicit scripted judgments for isolated replay. No provider, key or broker access."""

import asyncio
from datetime import timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.execution.economics import UsageEvidence
from app.options import entry_judgment, judgment
from app.options.engine import fingerprint
from app.options.entry_reasoning import EntryPlan
from app.options.models import Money, Name, OptionRecord


class ScriptedDecision(OptionRecord):
    cycle_key: Name
    delay_seconds: int = Field(ge=0, le=600, strict=True)
    action: Literal["HOLD", "SELECT", "ENTER", "UNKNOWN"]
    candidate_index: int = Field(default=0, ge=0, le=23, strict=True)
    input_tokens: int = Field(default=1000, gt=0, le=1000000, strict=True)
    output_tokens: int = Field(default=100, ge=0, le=1000000, strict=True)
    condition: Literal["NOW", "ABOVE", "BELOW"] | None = None
    underlying_trigger: Money | None = Field(default=None, gt=0)
    underlying_invalidation: Money | None = Field(default=None, gt=0)
    underlying_target: Money | None = Field(default=None, gt=0)
    horizon_seconds: int | None = Field(default=None, gt=0, le=21600, strict=True)

    @model_validator(mode="after")
    def geometry(self):
        terms = (
            self.condition,
            self.underlying_invalidation,
            self.underlying_target,
            self.horizon_seconds,
        )
        if self.action == "ENTER":
            if any(x is None for x in terms) or (
                (self.condition == "NOW") != (self.underlying_trigger is None)
            ):
                raise ValueError("Complete scripted entry geometry required")
        elif any(x is not None for x in (*terms, self.underlying_trigger)):
            raise ValueError("Only ENTER carries geometry")
        return self


class ReplayScript(OptionRecord):
    version: Literal["scripted-option-judgment-v1"] = "scripted-option-judgment-v1"
    evidence_kind: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    arm: Literal["B", "C"]
    decisions: tuple[ScriptedDecision, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def unique(self):
        if len({d.cycle_key for d in self.decisions}) != len(self.decisions) or any(
            d.action == ("ENTER" if self.arm == "B" else "SELECT") for d in self.decisions
        ):
            raise ValueError("Unique compatible scripted opportunities required")
        return self


class ReplayModel:
    """One-shot scripted responses; scheduler releases a future at virtual completion.

    Only receives model requests. Never receives a venue, engine, tape or credentials.
    Scripted usage is synthetic evidence, not a captured provider receipt.
    """

    def __init__(self, script):
        self.script = ReplayScript.model_validate(script.model_dump(warnings=False))
        self.started = asyncio.Event()
        self.pending = None
        self.used = set()

    def configuration(self):
        return self.script.model_dump(mode="json")

    async def run(self, request):
        key = request.packet.cycle_key
        if key in self.used or self.pending is not None:
            raise ValueError("Scripted judgment cannot replay")
        self.used.add(key)
        decision = next((d for d in self.script.decisions if d.cycle_key == key), None)
        if decision is None:
            raise ValueError("Missing script retains unknown cost")
        ready = asyncio.get_running_loop().create_future()
        self.pending = (request.packet.as_of + timedelta(seconds=decision.delay_seconds), ready)
        self.started.set()
        try:
            await ready
        finally:
            self.pending = None
            self.started.clear()
        if decision.action == "UNKNOWN":
            raise ValueError("Scripted unknown result")
        broad = isinstance(request, entry_judgment.EntryRequest)
        if broad != (self.script.arm == "C"):
            raise ValueError("Scripted model arm mismatch")
        model = request.configuration.costs.model if broad else request.model
        usage = UsageEvidence(
            request_id="fixture-" + fingerprint({"arm": self.script.arm, "cycle": key}),
            model=model,
            input_tokens=decision.input_tokens,
            output_tokens=decision.output_tokens,
        )
        if not broad:
            choice = (
                judgment.hold()
                if decision.action == "HOLD"
                else judgment.CandidateChoice(
                    action="SELECT",
                    candidate_id=request.packet.candidates[decision.candidate_index].candidate_id,
                    thesis="Scripted replay selection; not an authentic model judgment",
                )
            )
            return judgment.result_for(
                request, choice=choice, count=decision.input_tokens, usage=usage
            )
        plan = entry_judgment.hold(request.packet)
        if decision.action == "ENTER":
            opportunity = request.packet.opportunities[decision.candidate_index]
            plan = EntryPlan(
                decision_id=request.packet.decision_id,
                packet_hash=fingerprint(request.packet),
                action="ENTER",
                candidate_id=opportunity.candidate.candidate_id,
                evidence_ids=opportunity.evidence_ids,
                thesis="Scripted replay entry; not an authentic model judgment",
                uncertainty="Synthetic response and usage cannot establish model performance",
                **decision.model_dump(
                    include={
                        "condition",
                        "underlying_trigger",
                        "underlying_invalidation",
                        "underlying_target",
                        "horizon_seconds",
                    }
                ),
            )
        return entry_judgment.result_for(
            request, plan=plan, usage=usage, count=decision.input_tokens
        )
