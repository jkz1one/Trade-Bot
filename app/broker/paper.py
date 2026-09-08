from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.broker.base import Broker
from app.domain.models import AccountState, ExecutionResult, Position, Quote, RiskDecision, TradeDecision
from app.storage.repository import Repository


class PaperBroker(Broker):
    def __init__(self, repo: Repository, starting_capital: Decimal):
        self.repo = repo
        self.repo.ensure_initial_capital(starting_capital)
        self.position = self.repo.load_open_position()
        self.realized_pnl = self.repo.realized_pnl_total()
        open_cost = self.position.quantity * self.position.entry_price if self.position else Decimal("0")
        self.cash = self.repo.capital_flow_total() + self.realized_pnl - open_cost
        current_equity = self.cash + (self.position.market_value if self.position else Decimal("0"))
        persisted_hwm = self.repo.latest_high_watermark()
        self.high_watermark = max(current_equity, persisted_hwm or current_equity)
        self._execution_cache: dict[str, ExecutionResult] = {}

    def account_state(self, quotes: dict[str, Quote] | None = None) -> AccountState:
        if self.position and quotes and self.position.symbol in quotes:
            q = quotes[self.position.symbol]
            self.position.current_price = q.bid
        market_value = self.position.market_value if self.position else Decimal("0")
        equity = self.cash + market_value
        self.high_watermark = max(self.high_watermark, equity)
        return AccountState(equity=equity, cash=self.cash, buying_power=self.cash, high_watermark=self.high_watermark, realized_pnl=self.realized_pnl, position=self.position)

    def execute(
        self,
        decision: TradeDecision,
        risk: RiskDecision,
        quote: Quote,
        *,
        idempotency_key: str | None = None,
    ) -> ExecutionResult:
        if idempotency_key and idempotency_key in self._execution_cache:
            return self._execution_cache[idempotency_key]
        if not risk.approved:
            return ExecutionResult(status="SKIPPED", symbol=decision.symbol, message="Risk governor did not approve action")

        order_id = f"paper-{idempotency_key}" if idempotency_key else f"paper-{uuid4().hex}"
        if decision.action.value == "OPEN_LONG":
            if self.position is not None:
                return ExecutionResult(status="REJECTED", symbol=decision.symbol, message="Paper broker already has a position")
            fill_price = quote.ask
            notional = risk.approved_notional
            quantity = notional / fill_price
            if notional > self.cash:
                return ExecutionResult(status="REJECTED", symbol=decision.symbol, message="Insufficient paper cash")
            self.cash -= notional
            self.position = Position(
                symbol=quote.symbol, quantity=quantity, entry_price=fill_price, current_price=fill_price,
                original_invalidation=decision.invalidation_price, thesis=decision.thesis,
                opened_at=datetime.now(timezone.utc),
            )
            self.repo.save_fill(order_id, quote.symbol, notional, fill_price, quantity, decision.invalidation_price, decision.thesis)
            result = ExecutionResult(status="FILLED", order_id=order_id, symbol=quote.symbol, notional=notional, fill_price=fill_price, filled_quantity=quantity, message="Synthetic paper buy fill at ask")
        elif decision.action.value == "CLOSE":
            if self.position is None or self.position.symbol != quote.symbol:
                return ExecutionResult(status="REJECTED", symbol=decision.symbol, message="No matching paper position to close")
            fill_price = quote.bid
            quantity = self.position.quantity
            notional = quantity * fill_price
            realized = self.repo.save_close(order_id, quote.symbol, notional, fill_price, quantity)
            self.cash += notional
            self.realized_pnl += realized
            self.position = None
            result = ExecutionResult(status="FILLED", order_id=order_id, symbol=quote.symbol, notional=notional, fill_price=fill_price, filled_quantity=quantity, message="Synthetic paper sell fill at bid")
        else:
            return ExecutionResult(status="REJECTED", symbol=decision.symbol, message="Action is not implemented by Slice 1 paper broker")

        if idempotency_key:
            self._execution_cache[idempotency_key] = result
        return result

    def deposit(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("deposit must be positive")
        self.repo.add_capital_event("DEPOSIT", amount)
        self.cash += amount
        self.high_watermark += amount

    def withdraw(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("withdrawal must be positive")
        if amount > self.cash:
            raise ValueError("withdrawal exceeds available paper cash")
        self.repo.add_capital_event("WITHDRAWAL", -amount)
        self.cash -= amount
        self.high_watermark = max(Decimal("0"), self.high_watermark - amount)
