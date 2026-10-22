"""One-bankroll history contracts. Legacy option/stock cohorts cannot enroll these."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

# Public compatibility re-exports; primitives live below the lifecycle boundary.
from app.mixed.stock_models import (  # noqa: F401
    Shares,
    StockFill,
    StockInstrument,
    StockIntent,
    StockLimits,
    StockLot,
    StockPosition,
    StockQuote,
)
from app.options.lifecycle import OptionFill, OptionIntent, OptionLedger, OptionReceipt
from app.options.models import (
    Money,
    Name,
    OptionLimits,
    OptionRecord,
)

ZERO = Decimal(0)
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class MixedPolicy(OptionRecord):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    mode: Literal["PAPER"] = "PAPER"
    capital: Money = Field(gt=0)
    daily_loss_limit: Money = Field(gt=0)
    total_loss_limit: Money = Field(gt=0)
    options: OptionLimits
    stocks: StockLimits

    @model_validator(mode="after")
    def one_brokerage(self):
        if self.options.provider != self.stocks.provider:
            raise ValueError("Mixed history requires one frozen brokerage provider")
        if not self.daily_loss_limit <= self.total_loss_limit <= self.capital:
            raise ValueError("Mixed losses must fit one original capital")
        return self


class MixedLedger(OptionLedger):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    stock_position: StockPosition | None = None

    @model_validator(mode="after")
    def one_position(self):
        if self.position is not None and self.stock_position is not None:
            raise ValueError("Only one position across stocks and options")
        return self


class StockTrade(OptionRecord):
    kind: Literal["STOCK_FILL"] = "STOCK_FILL"
    intent: StockIntent
    attempted_at: datetime
    fill: StockFill


class OptionTrade(OptionRecord):
    kind: Literal["OPTION_FILL"] = "OPTION_FILL"
    intent: OptionIntent
    attempted_at: datetime
    fill: OptionFill


class Settlement(OptionRecord):
    kind: Literal["SETTLEMENT"] = "SETTLEMENT"
    receipt: OptionReceipt


CashEvent = Annotated[StockTrade | OptionTrade | Settlement, Field(discriminator="kind")]


class CostRecord(OptionRecord):
    cost_id: Name
    kind: Literal["ENTRY_MODEL", "MANAGEMENT_MODEL", "DATA", "HOST", "OPERATING"]
    occurred_at: datetime
    amount: Money | None = Field(ge=0)
    entry_client_id: Name | None = None
    evidence_hash: Digest


class CostResolution(OptionRecord):
    cost_id: Name
    recorded_at: datetime
    amount: Money = Field(ge=0)
    evidence_hash: Digest


class Reservation(OptionRecord):
    """An unresolved native order, not a model proposal or a new approval."""

    intent: StockIntent | OptionIntent
    status: Literal["PREPARED", "SUBMITTING", "UNKNOWN", "OPEN", "PARTIAL"]


class TerminalOrder(OptionRecord):
    intent: StockIntent | OptionIntent
    status: Literal["FILLED", "CANCELED", "REJECTED", "EXPIRED"]
    observed_at: datetime
    order_id: Name | None
    attempted_at: datetime | None


class CashHistory(OptionRecord):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    account_id: Name
    population_id: Name
    venue_id: Name
    policy: MixedPolicy
    opened_at: datetime
    captured_at: datetime
    events: tuple[CashEvent, ...] = Field(default=(), max_length=10000)
    costs: tuple[CostRecord, ...] = Field(default=(), max_length=10000)
    cost_resolutions: tuple[CostResolution, ...] = Field(default=(), max_length=10000)
    reservations: tuple[Reservation, ...] = Field(default=(), max_length=1)
    terminals: tuple[TerminalOrder, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def account_binding(self):
        if not 0 <= (self.captured_at - self.opened_at).total_seconds() <= 366 * 86400:
            raise ValueError("Bounded original history interval required")
        if (self.account_id, self.population_id) != (
            self.policy.options.account_id,
            self.policy.options.population_id,
        ):
            raise ValueError("Mixed history must bind its one original account/population")
        return self


class CashProjection(OptionRecord):
    version: Literal["mixed-cash-history-v1"] = "mixed-cash-history-v1"
    ledger: MixedLedger
    reserved_cash: Money = Field(ge=0)
    available_settled_cash: Money = Field(ge=0)
    known_cost: Money = Field(ge=0)
    unknown_cost_ids: tuple[Name, ...]
    daily_cost: dict[str, Money]
    net_realized_pnl: Money | None
    daily_loss_available: Money | None = Field(ge=0)
    total_loss_available: Money | None = Field(ge=0)
    entry_blockers: tuple[Name, ...]


class StockProposal(OptionRecord):
    action: Literal["HOLD", "OPEN_LONG", "CLOSE"]
    instrument: StockInstrument | None = None
    source_hash: Digest | None = None
    family: Literal["DEGEN", "SWING"] | None = None
    source_at: datetime | None = None
    valid_until: datetime | None = None
    exit_at: datetime | None = None
    original_invalidation: Money | None = Field(default=None, gt=0)
    original_target: Money | None = Field(default=None, gt=0)
    thesis: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def terms(self):
        if self.action != "HOLD" and self.instrument is None:
            raise ValueError("An exact stock instrument is required")
        if self.action == "OPEN_LONG" and (
            any(
                getattr(self, k) is None
                for k in (
                    "source_hash",
                    "family",
                    "source_at",
                    "valid_until",
                    "exit_at",
                    "original_invalidation",
                    "original_target",
                )
            )
            or not self.source_at < self.valid_until <= self.exit_at
        ):
            raise ValueError("Original stock source, geometry and deadlines are required")
        return self


class StockAdmission(OptionRecord):
    version: Literal["mixed-stock-admission-v1"] = "mixed-stock-admission-v1"
    mode: Literal["PAPER"] = "PAPER"
    outcome: Literal["HOLD", "REJECTED", "APPROVED"]
    action: Literal["HOLD", "OPEN_LONG", "CLOSE"]
    reasons: tuple[Name, ...] = ()
    history_hash: Digest
    proposal_hash: Digest
    approved_at: datetime
    approval_expires_at: datetime | None = None
    quantity: Shares = Field(default=ZERO, ge=0)
    limit_price: Money | None = Field(default=None, gt=0)
    entry_debit: Money = Field(default=ZERO, ge=0)
    reserved_exit_fee: Money = Field(default=ZERO, ge=0)
