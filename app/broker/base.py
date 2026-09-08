from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from app.domain.models import AccountState, ExecutionResult, Quote, RiskDecision, TradeDecision


class Broker(ABC):
    @abstractmethod
    def account_state(self, quotes: dict[str, Quote] | None = None) -> AccountState: ...

    @abstractmethod
    def execute(
        self,
        decision: TradeDecision,
        risk: RiskDecision,
        quote: Quote,
        *,
        idempotency_key: str | None = None,
    ) -> ExecutionResult: ...

    @abstractmethod
    def deposit(self, amount: Decimal) -> None: ...

    @abstractmethod
    def withdraw(self, amount: Decimal) -> None: ...
