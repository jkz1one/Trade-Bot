"""Opt-in model judgments for the fixture engine; no execution or broker capability."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from decimal import Decimal

from agents import AgentOutputSchema
from pydantic import Field, model_validator

from app.agent.prompts import TRADER_INSTRUCTIONS, TRADER_PROMPT_VERSION
from app.agent.trader import fail_closed_agent_run
from app.domain.models import Action, MarketPacket, TradeDecision
from app.execution.economics import CostAccounting, UsageEvidence
from app.execution.engine import ExecutionBlocked, _clock
from app.execution.models import Contract, Ledger, Snapshot
from app.execution.process import _cleanup

MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 128 * 1024


class JudgmentLimits(Contract):
    max_input_tokens: int = Field(default=16000, ge=1, le=100000, strict=True)
    max_output_tokens: int = Field(default=1024, ge=16, le=4096, strict=True)
    process_timeout_seconds: float = Field(default=30, gt=0, le=120)
    request_timeout_seconds: float = Field(default=20, gt=0, le=60)

    @model_validator(mode="after")
    def paired(self):
        if self.request_timeout_seconds > self.process_timeout_seconds:
            raise ValueError("Request timeout cannot exceed the whole-process timeout")
        return self


def request_content(model, packet):
    return {
        "model": model,
        "instructions": TRADER_INSTRUCTIONS,
        "input": "MARKET_PACKET_JSON\n"
        + json.dumps(packet.model_dump(mode="json"), separators=(",", ":")),
        "tools": [],
        "tool_choice": "none",
        "truncation": "disabled",
        "text": {
            "format": {
                "type": "json_schema",
                "name": "TradeDecision",
                "strict": True,
                "schema": AgentOutputSchema(TradeDecision).json_schema(),
            }
        },
    }


def configuration(costs, limits):
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    return {
        "policy": "bounded-responses-v1",
        "limits": limits.model_dump(mode="json"),
        "cost_policy_hash": digest(costs.policy.model_dump(mode="json")),
        "prompt_version": TRADER_PROMPT_VERSION,
        "prompt_hash": digest(TRADER_INSTRUCTIONS),
        "schema_hash": digest(AgentOutputSchema(TradeDecision).json_schema()),
    }


class JudgmentRequest(Contract):
    model: str = Field(min_length=1, max_length=128)
    packet: MarketPacket
    limits: JudgmentLimits
    configuration: dict
    deadline_monotonic: float = Field(gt=0)
    parent_pid: int = Field(gt=0, strict=True)


class JudgmentResult(Contract):
    decision: TradeDecision
    usage: UsageEvidence | None = None
    counted_input_tokens: int | None = Field(default=None, gt=0, strict=True)
    error: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    @model_validator(mode="after")
    def evidence(self):
        if self.error and self.decision.action != Action.HOLD:
            raise ValueError("An error result must HOLD")
        if self.error is None and (self.usage is None or self.counted_input_tokens is None):
            raise ValueError("Successful judgments require response usage and input count")
        return self


@dataclass(frozen=True)
class JudgmentOutcome:
    packet: MarketPacket
    result: JudgmentResult
    estimated_cost: Decimal | None


async def run_judgment_process(request, api_key):
    """Fixed child, pinned API origin, only the explicitly supplied model credential."""
    payload = request.model_dump_json().encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Judgment request exceeded protocol limit")
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    env["OPENAI_API_KEY"] = api_key
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.execution.judgment_worker",
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    )
    process = None
    try:
        async with asyncio.timeout(max(0, request.deadline_monotonic - time.monotonic())):
            process = await asyncio.shield(spawn)
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            data = bytearray()
            while chunk := await process.stdout.read(4096):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ValueError("Judgment response exceeded protocol limit")
            await process.wait()
            if process.returncode:
                raise RuntimeError("Judgment child failed")
            return JudgmentResult.model_validate_json(data)
    finally:
        if process is None:
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
            if not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
        if process is not None:
            await _cleanup(process)


class JudgmentCoordinator:
    def __init__(self, costs: CostAccounting, limits: JudgmentLimits):
        if type(costs) is not CostAccounting:
            raise ValueError("The fixture cost authority is required")
        self.costs = costs
        self.limits = JudgmentLimits.model_validate(limits.model_dump())
        policy = costs.policy
        maximum = (
            Decimal(self.limits.max_input_tokens) * policy.input_per_million
            + Decimal(self.limits.max_output_tokens) * policy.output_per_million
        ) / 1_000_000
        if maximum > policy.max_call_cost:
            raise ValueError("Request token ceilings exceed the frozen cost reservation")
        with costs.engine.journal.write() as db:
            costs.engine._control(db)
            costs._policy(db)
            frozen = json.dumps(configuration(costs, self.limits), sort_keys=True)
            row = db.execute(
                "SELECT policy_json FROM execution_judgment_policy WHERE id=1"
            ).fetchone()
            if row:
                if row[0] != frozen:
                    raise ValueError("Judgment policy is immutable")
            else:
                if db.execute("SELECT 1 FROM execution_model_calls").fetchone():
                    raise ValueError("Judgment policy requires enrollment before model receipts")
                db.execute("INSERT INTO execution_judgment_policy VALUES(1,?,NULL)", (frozen,))
                from datetime import datetime

                costs.engine.journal.event(
                    db,
                    datetime.now().astimezone(),
                    "MODEL_JUDGMENT_POLICY_ENROLLED",
                    json.loads(frozen),
                )

    def _configuration(self, db):
        row = db.execute("SELECT policy_json FROM execution_judgment_policy WHERE id=1").fetchone()
        if row is None or row[0] != json.dumps(
            configuration(self.costs, self.limits), sort_keys=True
        ):
            raise ExecutionBlocked("JUDGMENT_CONFIGURATION_CHANGED")

    async def decide(self, source_key, packet, *, api_key, now, clock):
        """Returns judgment evidence only. Caller must independently prepare/govern/dispatch."""
        _clock(now)
        if (
            not isinstance(api_key, str)
            or not 1 <= len(api_key) <= 512
            or not api_key.strip()
            or any(c.isspace() for c in api_key)
        ):
            raise ValueError("An explicit single model API credential is required")
        engine = self.costs.engine
        packet = engine._validated_packet(packet)
        with engine.journal.read() as db:
            control = engine._control(db)
            self.costs._policy(db)
            self._configuration(db)
            engine._ready(control, now)
            _, packet = engine._govern(
                fail_closed_agent_run(RuntimeError()).decision,
                packet,
                Ledger.model_validate_json(control["ledger_json"]),
                Snapshot.model_validate_json(control["snapshot_json"]),
                now,
                db,
                source_key,
            )
            window = engine.calendar.current_window(now)
            if window is None:
                raise ExecutionBlocked("MARKET_CLOSED")
            packet = packet.model_copy(update={"session_context": window.context()})
            reviewed_revision = engine.journal.revision(db)
        request = JudgmentRequest(
            model=self.costs.policy.model,
            packet=packet,
            limits=self.limits,
            configuration=configuration(self.costs, self.limits),
            deadline_monotonic=time.monotonic() + self.limits.process_timeout_seconds,
            parent_pid=os.getpid(),
        )
        if len(request.model_dump_json().encode()) > MAX_REQUEST_BYTES:
            raise ValueError("Judgment request exceeded protocol limit")
        if not self.costs.begin(source_key, packet, now=now, expected_revision=reviewed_revision)[
            "invoke_model"
        ]:
            raise ExecutionBlocked("MODEL_SOURCE_ALREADY_ATTEMPTED")
        try:
            result = await run_judgment_process(request, api_key)
        except asyncio.CancelledError:
            with engine.journal.write() as db:
                engine.journal.event(
                    db, now, "MODEL_JUDGMENT_INTERRUPTED", {"source_key": source_key}
                )
            raise
        except Exception as exc:  # noqa: BLE001 -- model boundary always yields fail-closed HOLD
            result = JudgmentResult(
                decision=fail_closed_agent_run(exc).decision, error=type(exc).__name__
            )
        completed = clock()
        _clock(completed)
        if completed < now:
            raise ValueError("Judgment completion clock regressed")
        amount = None
        violation = result.usage is not None and (
            result.usage.model != request.model
            or result.usage.input_tokens > request.limits.max_input_tokens
            or result.usage.output_tokens > request.limits.max_output_tokens
            or result.counted_input_tokens != result.usage.input_tokens
        )
        if violation:
            result = result.model_copy(
                update={
                    "decision": fail_closed_agent_run(ValueError()).decision,
                    "error": "ModelEvidenceViolation",
                }
            )
        with engine.journal.write() as db:
            engine._control(db)
            self.costs._policy(db)
            self._configuration(db)
            if result.usage is not None and result.usage.model == request.model:
                amount = self.costs._settle(
                    db, source_key, result.usage, result.decision, now=completed
                )
            if violation:
                db.execute(
                    "UPDATE execution_judgment_policy SET blocked_reason='MODEL_EVIDENCE_VIOLATION' WHERE id=1"
                )
            engine.journal.event(
                db,
                completed,
                "MODEL_JUDGMENT_RECORDED",
                {
                    "source_key": source_key,
                    "result": result.model_dump(mode="json"),
                    "estimated_cost": str(amount) if amount is not None else None,
                },
            )
        return JudgmentOutcome(packet, result, amount)
