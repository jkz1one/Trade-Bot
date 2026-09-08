from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.models import Action, Horizon, MarketPacket, TradeDecision
from app.agent.prompts import TRADER_INSTRUCTIONS


@dataclass(frozen=True)
class AgentRun:
    decision: TradeDecision
    input_tokens: int = 0
    output_tokens: int = 0


class TraderAgent(ABC):
    @abstractmethod
    def decide(self, packet: MarketPacket) -> AgentRun: ...


class StubTraderAgent(TraderAgent):
    def __init__(self, decision: TradeDecision | None = None):
        self._decision = decision

    def decide(self, packet: MarketPacket) -> AgentRun:
        if self._decision is not None:
            return AgentRun(self._decision)
        return AgentRun(TradeDecision(
            action=Action.HOLD, confidence=0.5, setup_quality=0.5, horizon=Horizon.INTRADAY,
            thesis="Fixture conditions do not require a trade.",
            invalidation_reason="No position exists to invalidate.", evidence=[], risks=["Demo fixture only"],
            why_now="Abstain until a setup is explicitly supplied.",
        ))


class OpenAIAgentsTrader(TraderAgent):
    """Optional live reasoning adapter. It exposes no brokerage write tools."""

    def __init__(self, model: str):
        try:
            from agents import Agent
        except ImportError as exc:
            raise RuntimeError("Install the `openai-agents` package to use OpenAIAgentsTrader") from exc
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
        result = Runner.run_sync(self._agent, json.dumps(packet.model_dump(mode="json"), separators=(",", ":")))
        usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
        return AgentRun(
            decision=result.final_output,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )
