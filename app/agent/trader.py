from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.agent.prompts import TRADER_INSTRUCTIONS
from app.domain.models import Action, Horizon, MarketPacket, TradeDecision


@dataclass(frozen=True)
class AgentRun:
    decision: TradeDecision
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


def fail_closed_agent_run(exc: Exception) -> AgentRun:
    """Convert an agent/model failure into an auditable HOLD without leaking error details."""
    error_name = type(exc).__name__
    return AgentRun(
        decision=TradeDecision(
            action=Action.HOLD,
            confidence=0,
            setup_quality=0,
            horizon=Horizon.INTRADAY,
            thesis="Agent run failed; fail-closed HOLD selected.",
            invalidation_reason="No position-changing action is permitted after an agent failure.",
            evidence=[],
            risks=[f"Agent failure: {error_name}"],
            why_now="Preserve capital and wait for a successful future decision cycle.",
        ),
        error=error_name,
    )


class TraderAgent(ABC):
    @property
    def model_identifier(self) -> str:
        return type(self).__name__

    @abstractmethod
    def decide(self, packet: MarketPacket) -> AgentRun: ...


class StubTraderAgent(TraderAgent):
    @property
    def model_identifier(self) -> str:
        return "stub"

    def __init__(self, decision: TradeDecision | None = None):
        self._decision = decision

    def decide(self, packet: MarketPacket) -> AgentRun:
        if self._decision is not None:
            return AgentRun(self._decision)
        return AgentRun(
            TradeDecision(
                action=Action.HOLD,
                confidence=0,
                setup_quality=0,
                horizon=Horizon.INTRADAY,
                thesis="Stub agent is configured to abstain.",
                invalidation_reason="No position-changing proposal was configured.",
                evidence=[],
                risks=["Stub agent does not make market judgments"],
                why_now="Use the stub only to validate the deterministic SHADOW pipeline.",
            )
        )


class OpenAIAgentsTrader(TraderAgent):
    """Reasoning adapter. It exposes no brokerage or other tools to the model."""

    @property
    def model_identifier(self) -> str:
        return self._model

    def __init__(self, model: str):
        try:
            from agents import Agent
        except ImportError as exc:
            raise RuntimeError(
                "Install the `openai-agents` package to use OpenAIAgentsTrader"
            ) from exc
        self._model = model
        self._agent = Agent(
            name="Trader Agent",
            model=model,
            instructions=TRADER_INSTRUCTIONS,
            output_type=TradeDecision,
            tools=[],
        )

    def decide(self, packet: MarketPacket) -> AgentRun:
        from agents import Runner

        packet_json = json.dumps(
            packet.model_dump(mode="json"),
            separators=(",", ":"),
        )
        result = Runner.run_sync(
            self._agent,
            "MARKET_PACKET_JSON\n" + packet_json,
            max_turns=1,
        )
        usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
        return AgentRun(
            decision=result.final_output,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )

    async def decide_isolated(self, packet, *, timeout_seconds, request_timeout_seconds):
        from app.agent.process import run_model_process

        return await run_model_process(
            self._model, packet, timeout_seconds=timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )
