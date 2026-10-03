from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from time import perf_counter

from app.agent.trader import TraderAgent
from app.config import Settings
from app.domain.models import AccountState, Action, ExecutionResult, MarketPacket, Position
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
    ):
        if settings.normalized_mode != "SHADOW":
            raise RuntimeError("ShadowOrchestrator requires TRADER_MODE=SHADOW")
        if settings.live_enabled:
            raise RuntimeError("SHADOW must not run with live execution enabled")
        self.settings = settings
        self.repo = repo
        self.gateway = gateway
        self.agent = agent
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
            position = local.model_copy(update={"current_price": current, "quantity": broker.quantity})

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

    async def _review(self, decision, risk, packet, account_number: str) -> ExecutionResult:
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
                status="SKIPPED", symbol=decision.symbol, message="No SHADOW review for action"
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

    async def cycle(self):
        started = perf_counter()
        truth = await self.reads.truth()
        reconciliation = reconcile_truth(self.repo, truth)
        candidates = await self.market.candidates(
            truth.account.account_number,
            self.settings.initial_symbols,
        )
        account = self._account_state(truth, candidates, reconciliation.reconciled)
        packet = MarketPacket(
            as_of=datetime.now(timezone.utc),
            account=account,
            candidates=candidates,
            regime=self.market.regime(candidates),
            recent_lessons=([] if reconciliation.reconciled else [
                "Broker/local reconciliation failed: " + ", ".join(reconciliation.reasons)
            ]),
        )
        run = await asyncio.to_thread(self.agent.decide, packet)
        risk = govern(
            run.decision,
            packet,
            self.settings,
            system_enabled=self.system_enabled,
            broker_reconciled=reconciliation.reconciled,
            daily_entries=self.daily_entries,
        )
        execution = ExecutionResult(
            status="SKIPPED", symbol=run.decision.symbol, message="SHADOW: no executable action"
        )
        if risk.approved and run.decision.symbol:
            execution = await self._review(
                run.decision, risk, packet, truth.account.account_number
            )
            if run.decision.action == Action.OPEN_LONG:
                self.daily_entries += 1

        latency_ms = int((perf_counter() - started) * 1000)
        self.repo.save_cycle(
            packet, run.decision, risk, execution, self.settings.model_name, latency_ms
        )
        if run.input_tokens or run.output_tokens:
            self.repo.save_model_usage(
                self.settings.model_name,
                run.input_tokens,
                run.output_tokens,
                self.settings.model_input_usd_per_million,
                self.settings.model_output_usd_per_million,
            )
        self.repo.save_account_snapshot(account)
        spy = next((c for c in candidates if c.quote.symbol == self.settings.benchmark_symbol), None)
        if spy:
            self.repo.save_benchmark(spy.quote.symbol, spy.quote.last)
        return packet, run.decision, risk, execution, reconciliation, truth
