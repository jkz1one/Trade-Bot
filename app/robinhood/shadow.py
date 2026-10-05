from __future__ import annotations

import asyncio
from decimal import Decimal
from time import perf_counter

from app.agent.prompts import TRADER_PROMPT_VERSION
from app.agent.trader import AgentRun, OpenAIAgentsTrader, TraderAgent, fail_closed_agent_run
from app.config import Settings
from app.domain.models import (
    AccountState, Action, ExecutionResult, MarketPacket, Position, TradeDecision, utc_now,
)
from app.risk.governor import govern
from app.robinhood.gateway import RobinhoodSafeGateway
from app.robinhood.market import RobinhoodMarketData
from app.robinhood.read import RobinhoodReadService, tool_data
from app.robinhood.reconcile import reconcile_truth
from app.storage.repository import Repository


def _order_dump(order) -> dict:
    return order.model_dump(mode="json")


class ShadowOrchestrator:
    """Live Robinhood reads + hypothetical order review. Never places or cancels orders."""

    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        gateway: RobinhoodSafeGateway,
        agent: TraderAgent,
        *, clock=None,
    ):
        if settings.normalized_mode != "SHADOW":
            raise RuntimeError("ShadowOrchestrator requires TRADER_MODE=SHADOW")
        if settings.live_enabled:
            raise RuntimeError("SHADOW must not run with live execution enabled")
        self.settings = settings
        self.repo = repo
        self.gateway = gateway
        self.agent = agent
        self.clock = clock or utc_now
        self.reads = RobinhoodReadService(gateway)
        self.market = RobinhoodMarketData(
            gateway,
            interval=settings.shadow_bar_interval,
            lookback_days=settings.shadow_lookback_days,
        )
        self.system_enabled = True
        self.daily_entries = 0

    def _account_state(self, truth, candidates, reconciled: bool) -> AccountState:
        quotes = {c.quote.symbol: c.quote for c in candidates}
        local = self.repo.load_open_position()
        position: Position | None = None
        if reconciled and local is not None and truth.positions:
            broker = truth.positions[0]
            quote = quotes.get(broker.symbol)
            current = quote.bid if quote else local.current_price
            position = local.model_copy(
                update={"current_price": current, "quantity": broker.quantity}
            )

        equity = truth.portfolio.total_value
        persisted_hwm = self.repo.latest_high_watermark()
        high_watermark = max(equity, persisted_hwm or equity)
        return AccountState(
            equity=equity,
            cash=max(Decimal("0"), truth.portfolio.cash),
            buying_power=max(Decimal("0"), truth.portfolio.buying_power),
            high_watermark=high_watermark,
            realized_pnl=Decimal("0"),
            position=position,
            working_orders=[_order_dump(o) for o in truth.working_orders],
        )

    async def _decide(self, packet: MarketPacket):
        try:
            if isinstance(self.agent, OpenAIAgentsTrader):
                return await self.agent.decide_isolated(
                    packet, timeout_seconds=self.settings.model_process_timeout_seconds,
                    request_timeout_seconds=self.settings.model_request_timeout_seconds,
                )
            return await asyncio.to_thread(self.agent.decide, packet)
        except Exception as exc:
            return fail_closed_agent_run(exc)

    async def _review(
        self, decision, risk, packet, account_number: str
    ) -> ExecutionResult:
        if decision.action == Action.OPEN_LONG:
            args = {
                "account_number": account_number,
                "symbol": decision.symbol,
                "side": "buy",
                "type": "market",
                "dollar_amount": str(risk.approved_notional),
                "market_hours": "regular_hours",
                "time_in_force": "gfd",
            }
        elif decision.action == Action.CLOSE and packet.account.position is not None:
            args = {
                "account_number": account_number,
                "symbol": decision.symbol,
                "side": "sell",
                "type": "market",
                "quantity": str(packet.account.position.quantity),
                "market_hours": "regular_hours",
                "time_in_force": "gfd",
            }
        else:
            return ExecutionResult(
                status="SKIPPED",
                symbol=decision.symbol,
                message="No SHADOW review for action",
            )

        raw = await self.gateway.call_safe("review_equity_order", args)
        review = tool_data(raw)
        alerts = review.get("order_checks") or {}
        message = "SHADOW broker review completed; no order submitted"
        if alerts:
            message += "; broker returned pre-trade alerts"
        return ExecutionResult(
            status="SKIPPED",
            symbol=decision.symbol,
            notional=risk.approved_notional,
            message=message,
            broker_review=review,
        )

    async def cycle(self, *, schedule_window=None, claim_token: str | None = None):
        if schedule_window is not None:
            claim = self.repo.shadow_slot(schedule_window.key)
            if claim is None or claim.status != "CLAIMED" or claim.claim_token != claim_token:
                raise RuntimeError("Scheduled SHADOW must own an active cycle claim before reads")
        started = perf_counter()
        truth = await self.reads.truth()
        reconciliation = reconcile_truth(self.repo, truth)
        candidates = await self.market.candidates(
            truth.account.account_number,
            self.settings.initial_symbols,
        )
        account = self._account_state(truth, candidates, reconciliation.reconciled)
        packet = MarketPacket(
            as_of=self.clock(),
            account=account,
            candidates=candidates,
            regime=self.market.regime(candidates),
            recent_lessons=(
                []
                if reconciliation.reconciled
                else [
                    "Broker/local reconciliation failed: "
                    + ", ".join(reconciliation.reasons)
                ]
            ),
            session_context=schedule_window.context() if schedule_window else None,
        )
        session_blocked = schedule_window is not None and not schedule_window.is_open(self.clock())
        if session_blocked:
            run = AgentRun(TradeDecision(
                action=Action.HOLD, confidence=0, setup_quality=0,
                thesis="The scheduled regular market session ended before model judgment.",
                invalidation_reason="No position-changing action is permitted outside this session.",
                why_now="Wait for a future regular market session.",
            ))
        else:
            run = await self._decide(packet)
        entries, last_close = self.repo.shadow_review_activity(packet.as_of)
        in_cooldown = last_close is not None and (
            packet.as_of - last_close
        ).total_seconds() < self.settings.exit_cooldown_minutes * 60
        risk = govern(
            run.decision,
            packet,
            self.settings,
            system_enabled=self.system_enabled,
            broker_reconciled=reconciliation.reconciled,
            daily_entries=entries,
            in_exit_cooldown=in_cooldown,
        )
        message = (
            f"SHADOW: agent failure ({run.error}); fail-closed HOLD"
            if run.error
            else "SHADOW: no executable action"
        )
        execution = ExecutionResult(
            status="SKIPPED",
            symbol=run.decision.symbol,
            message=message,
            agent_error=run.error,
            session_blocked=session_blocked,
        )
        if risk.approved and run.decision.symbol:
            if schedule_window is not None and not schedule_window.is_open(self.clock()):
                execution = ExecutionResult(
                    status="SKIPPED", symbol=run.decision.symbol, session_blocked=True,
                    message="SHADOW session ended during model judgment; broker review skipped",
                )
            else:
                try:
                    execution = await self._review(
                        run.decision, risk, packet, truth.account.account_number,
                    )
                except Exception as exc:
                    execution = ExecutionResult(
                        status="REJECTED", symbol=run.decision.symbol,
                        message="SHADOW broker review failed; no order submitted",
                        review_error=type(exc).__name__,
                    )
            if execution.broker_review is not None and run.decision.action == Action.OPEN_LONG:
                self.daily_entries += 1

        latency_ms = int((perf_counter() - started) * 1000)
        self.repo.save_shadow_cycle(
            packet,
            run.decision,
            risk,
            execution,
            "session-guard" if session_blocked else
            getattr(self.agent, "model_identifier", type(self.agent).__name__),
            latency_ms=latency_ms,
            prompt_version=TRADER_PROMPT_VERSION,
            input_tokens=run.input_tokens, output_tokens=run.output_tokens,
            input_price=self.settings.model_input_usd_per_million,
            output_price=self.settings.model_output_usd_per_million,
            benchmark_symbol=self.settings.benchmark_symbol,
            reconciliation=reconciliation.model_dump(mode="json"),
            slot_key=schedule_window.key if schedule_window else None,
            claim_token=claim_token,
            outcome_settings=self.settings, completed_at=self.clock(),
        )
        return packet, run.decision, risk, execution, reconciliation, truth
