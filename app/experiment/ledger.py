"""Versioned next-quote PAPER accounting. No broker, model or persistence authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.prompts import TRADER_INSTRUCTIONS, TRADER_PROMPT_VERSION
from app.config import Settings
from app.domain.models import AccountState, Action, Position, TradeDecision
from app.risk.governor import govern
from app.risk.policy import TIERS

ZERO = Decimal(0)
POLICY = "v1-next-quote-paper"
QUANTITY_STEP = Decimal("0.00000001")


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy: str = POLICY
    capital: Decimal = Field(default=Decimal(10), gt=0)
    slippage_bps: Decimal = Field(default=Decimal(5), ge=0, le=1000)
    fee_per_fill: Decimal = Field(default=ZERO, ge=0)
    benchmark_symbol: str = "SPY"
    model: str
    input_price: Decimal = Field(ge=0)
    output_price: Decimal = Field(ge=0)
    risk_settings: dict
    risk_policy_hash: str
    market_config: dict
    prompt_version: str
    prompt_hash: str

    @model_validator(mode="after")
    def valid_economics(self):
        if self.capital <= 2 * self.fee_per_fill:
            raise ValueError("Initial capital must cover both benchmark execution fees")
        if self.benchmark_symbol != "SPY":
            raise ValueError("The experiment benchmark must remain SPY")
        return self

    @classmethod
    def capture(
        cls, settings, model, *, capital=Decimal(10), slippage_bps=Decimal(5), fee_per_fill=ZERO
    ):
        return cls(
            capital=capital,
            slippage_bps=slippage_bps,
            fee_per_fill=fee_per_fill,
            benchmark_symbol=settings.benchmark_symbol,
            model=model,
            input_price=settings.model_input_usd_per_million,
            output_price=settings.model_output_usd_per_million,
            market_config={
                "symbols": settings.initial_symbols,
                "bar_interval": settings.shadow_bar_interval,
                "lookback_days": settings.shadow_lookback_days,
            },
            prompt_version=TRADER_PROMPT_VERSION + ":virtual-account-v1",
            prompt_hash=hashlib.sha256(TRADER_INSTRUCTIONS.encode()).hexdigest(),
            risk_settings={
                key: str(getattr(settings, key))
                for key in (
                    "min_order_notional",
                    "quote_max_age_seconds",
                    "max_daily_entries",
                    "exit_cooldown_minutes",
                )
            },
            risk_policy_hash=hashlib.sha256(
                json.dumps(
                    [(str(upper), asdict(policy)) for upper, policy in TIERS],
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest(),
        )

    def settings(self):
        return Settings(mode="PAPER", live_enabled=False, **self.risk_settings)


class PendingProposal(BaseModel):
    source_cycle_id: int | None = None
    decision: TradeDecision
    approved_notional: Decimal = Field(gt=0)
    available_at: datetime
    expires_at: datetime
    session_date: str


class LedgerState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cash: Decimal = Field(ge=0)
    position: Position | None = None
    position_session: str | None = None
    hold_overnight: bool = False
    pending: PendingProposal | None = None
    realized_price_pnl: Decimal = ZERO
    fees_paid: Decimal = Field(default=ZERO, ge=0)
    known_model_cost: Decimal = Field(default=ZERO, ge=0)
    unknown_model_calls: int = Field(default=0, ge=0)
    high_watermark: Decimal = Field(gt=0)
    max_drawdown: Decimal = Field(default=ZERO, ge=0)
    benchmark_quantity: Decimal = Field(default=ZERO, ge=0)
    benchmark_cash: Decimal = Field(default=ZERO, ge=0)
    benchmark_bid: Decimal | None = None
    benchmark_started_at: datetime | None = None
    last_as_of: datetime | None = None
    session_date: str | None = None
    daily_entries: int = 0
    last_close_at: datetime | None = None


class PaperLedger:
    def __init__(self, config: ExperimentConfig, state: LedgerState, *, unaccounted_calls=0):
        if config.policy != POLICY:
            raise ValueError("Unsupported synthetic execution policy")
        self.config, self.state = config, state.model_copy(deep=True)
        self.settings = config.settings()
        self.unaccounted_calls = unaccounted_calls
        self.fills = []
        self.events = []
        self.position_fresh = self.state.position is None
        self.benchmark_fresh = False
        self.ready = False

    @property
    def unknown_model_calls(self):
        return self.state.unknown_model_calls + self.unaccounted_calls

    def quote(self, packet, symbol, at):
        quote = next((c.quote for c in packet.candidates if c.quote.symbol == symbol), None)
        if quote is None or quote.timestamp.tzinfo is None or quote.timestamp.utcoffset() is None:
            return None
        if not 0 <= (at - quote.timestamp).total_seconds() <= self.settings.quote_max_age_seconds:
            return None
        return quote if quote.bid <= quote.ask else None

    def buy_price(self, quote):
        return quote.ask * (1 + self.config.slippage_bps / Decimal(10000))

    def sell_price(self, quote):
        return quote.bid * (1 - self.config.slippage_bps / Decimal(10000))

    def equity(self):
        pos = self.state.position
        return self.state.cash + (pos.market_value - self.config.fee_per_fill if pos else ZERO)

    def account(self):
        reserve = self.state.known_model_cost + (
            self.config.fee_per_fill if self.state.position else ZERO
        )
        equity = max(ZERO, self.equity() - self.state.known_model_cost)
        return AccountState(
            equity=equity,
            cash=max(ZERO, self.state.cash - reserve),
            buying_power=max(ZERO, self.state.cash - reserve),
            high_watermark=max(self.state.high_watermark, equity),
            realized_pnl=self.state.realized_price_pnl - self.state.fees_paid,
            position=self.state.position,
        )

    def risk(self, decision, packet, at):
        candidates = [
            candidate.model_copy(
                update={
                    "quote": candidate.quote.model_copy(
                        update={
                            "bid": self.sell_price(candidate.quote),
                            "ask": self.buy_price(candidate.quote),
                        }
                    )
                }
            )
            for candidate in packet.candidates
        ]
        account = self.account()
        if decision.action == Action.OPEN_LONG:
            account = account.model_copy(
                update={"buying_power": max(ZERO, account.buying_power - self.config.fee_per_fill)}
            )
        risk_packet = packet.model_copy(update={"account": account, "candidates": candidates})
        kwargs = {
            "now": at,
            "system_enabled": self.ready and self.unknown_model_calls == 0,
            "daily_entries": self.state.daily_entries,
            "in_exit_cooldown": self.state.last_close_at is not None
            and (at - self.state.last_close_at).total_seconds()
            < self.settings.exit_cooldown_minutes * 60,
        }
        result = govern(decision, risk_packet, self.settings, **kwargs)
        if result.approved and decision.action == Action.OPEN_LONG and self.config.fee_per_fill:
            # Reserve both entry and exit fees inside the existing governor budget.
            cap = max(
                ZERO,
                result.approved_notional
                - 2 * self.config.fee_per_fill / result.effective_loss_distance,
            )
            account = account.model_copy(update={"buying_power": min(account.buying_power, cap)})
            result = govern(
                decision,
                risk_packet.model_copy(update={"account": account}),
                self.settings,
                **kwargs,
            )
            if result.approved:
                planned = result.planned_risk_dollars + 2 * self.config.fee_per_fill
                result = result.model_copy(
                    update={
                        "planned_risk_dollars": planned,
                        "planned_risk_fraction": planned / account.equity,
                    }
                )
        return result

    def _sell(self, quote, at, reason, source=None):
        pos = self.state.position
        price = self.sell_price(quote)
        proceeds = pos.quantity * price
        if self.state.cash + proceeds < self.config.fee_per_fill:
            self.events.append("EXIT_FEE_EXCEEDS_AVAILABLE_CASH")
            return False
        self.state.cash += proceeds - self.config.fee_per_fill
        self.state.realized_price_pnl += pos.quantity * (price - pos.entry_price)
        self.state.fees_paid += self.config.fee_per_fill
        self.fills.append(
            {
                "side": "SELL",
                "symbol": pos.symbol,
                "quantity": str(pos.quantity),
                "price": str(price),
                "notional": str(proceeds),
                "fee": str(self.config.fee_per_fill),
                "quote_timestamp": quote.timestamp.isoformat(),
                "observed_at": at.isoformat(),
                "reason": reason,
                "source_cycle_id": source,
            }
        )
        self.state.position = None
        self.state.position_session = None
        self.state.pending = None
        self.state.last_close_at = at
        self.position_fresh = True
        return True

    def prepare(self, packet, window):
        at = packet.as_of
        if not window.is_open(at) or at.tzinfo is None:
            raise ValueError("Synthetic transitions require the scheduled regular session")
        if self.state.last_as_of is not None and at <= self.state.last_as_of:
            raise ValueError("Synthetic packets must advance time; historical replay is forbidden")
        if self.state.session_date != window.session_date:
            self.state.session_date, self.state.daily_entries = window.session_date, 0
        benchmark = self.quote(packet, self.config.benchmark_symbol, at)
        self.benchmark_fresh = benchmark is not None and benchmark.fractional_tradable
        if self.benchmark_fresh:
            self.state.benchmark_bid = self.sell_price(benchmark)
            if self.state.benchmark_started_at is None:
                budget = max(ZERO, self.config.capital - self.config.fee_per_fill)
                quantity = (budget / self.buy_price(benchmark)).quantize(
                    QUANTITY_STEP, rounding=ROUND_DOWN
                )
                if quantity <= 0:
                    self.benchmark_fresh = False
                else:
                    self.state.benchmark_quantity = quantity
                    self.state.benchmark_cash = (
                        self.config.capital
                        - quantity * self.buy_price(benchmark)
                        - self.config.fee_per_fill
                    )
                    self.state.benchmark_started_at = at
        self.ready = self.benchmark_fresh
        pos = self.state.position
        if pos:
            quote = self.quote(packet, pos.symbol, at)
            self.position_fresh = quote is not None
            if quote:
                pos.current_price = self.sell_price(quote)
                reason = (
                    "INVALIDATION"
                    if quote.bid <= pos.original_invalidation
                    else "MISSED_SESSION_EXIT"
                    if not self.state.hold_overnight
                    and self.state.position_session != window.session_date
                    else "SESSION_EXIT"
                    if not self.state.hold_overnight
                    and at >= window.closes_at - timedelta(minutes=15)
                    else None
                )
                if reason:
                    self._sell(quote, at, reason)
        pending = self.state.pending
        if pending:
            if at >= pending.expires_at or pending.session_date != window.session_date:
                self.events.append("PROPOSAL_EXPIRED")
                self.state.pending = None
            else:
                quote = self.quote(packet, pending.decision.symbol, at)
                if quote is None or quote.timestamp <= pending.available_at:
                    self.events.append("WAITING_FOR_FRESH_FORWARD_QUOTE")
                else:
                    result = self.risk(pending.decision, packet, at)
                    decision = pending.decision
                    self.state.pending = None
                    if not result.approved:
                        self.events.extend(
                            ["FILL_REVALIDATION_REJECTED", *result.rejection_reasons]
                        )
                    elif decision.action == Action.CLOSE:
                        self._sell(quote, at, "MODEL_CLOSE", pending.source_cycle_id)
                    elif (
                        quote.bid <= decision.invalidation_price
                        or at >= window.closes_at - timedelta(minutes=15)
                    ):
                        self.events.append("ENTRY_INVALIDATED_OR_NO_FORWARD_SESSION")
                    else:
                        amount = min(pending.approved_notional, result.approved_notional)
                        price = self.buy_price(quote)
                        quantity = (amount / price).quantize(QUANTITY_STEP, rounding=ROUND_DOWN)
                        spent = quantity * price
                        if quantity <= 0 or spent < self.settings.min_order_notional:
                            self.events.append("FILL_BELOW_MINIMUM_NOTIONAL")
                        else:
                            self.state.cash -= spent + self.config.fee_per_fill
                            self.state.fees_paid += self.config.fee_per_fill
                            self.state.position = Position(
                                symbol=quote.symbol,
                                quantity=quantity,
                                entry_price=price,
                                current_price=self.sell_price(quote),
                                original_invalidation=decision.invalidation_price,
                                thesis=decision.thesis,
                                opened_at=at,
                            )
                            self.state.position_session = window.session_date
                            self.state.hold_overnight = decision.hold_overnight
                            self.state.daily_entries += 1
                            self.position_fresh = True
                            self.fills.append(
                                {
                                    "side": "BUY",
                                    "symbol": quote.symbol,
                                    "quantity": str(quantity),
                                    "price": str(price),
                                    "notional": str(spent),
                                    "fee": str(self.config.fee_per_fill),
                                    "quote_timestamp": quote.timestamp.isoformat(),
                                    "observed_at": at.isoformat(),
                                    "reason": "MODEL_ENTRY",
                                    "source_cycle_id": pending.source_cycle_id,
                                }
                            )
        self.ready = self.ready and self.position_fresh and self.state.pending is None
        self.state.last_as_of = at
        self.check()

    def charge_model(self, input_tokens, output_tokens, *, attempted):
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Negative model usage")
        if input_tokens or output_tokens:
            cost = (
                Decimal(input_tokens) * self.config.input_price
                + Decimal(output_tokens) * self.config.output_price
            ) / Decimal(1000000)
            self.state.known_model_cost += cost
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "input_price_per_million": str(self.config.input_price),
                "output_price_per_million": str(self.config.output_price),
                "estimated_cost": str(cost),
            }
        if attempted:
            self.state.unknown_model_calls += 1
        return None

    def propose(self, decision, packet, completed_at, window, *, agent_error=None):
        risk = self.risk(decision, packet, completed_at)
        if risk.approved and (
            not window.is_open(completed_at)
            or window.scheduled_for + timedelta(minutes=15) >= window.closes_at
        ):
            risk = risk.model_copy(
                update={
                    "approved": False,
                    "approved_notional": ZERO,
                    "rejection_reasons": [*risk.rejection_reasons, "NO_FORWARD_SESSION_SLOT"],
                }
            )
        if risk.approved and not agent_error:
            self.state.pending = PendingProposal(
                decision=decision,
                approved_notional=risk.approved_notional,
                available_at=completed_at,
                expires_at=min(completed_at + timedelta(minutes=20), window.closes_at),
                session_date=window.session_date,
            )
        self.update_drawdown()
        self.check()
        return risk

    def update_drawdown(self):
        if self.position_fresh and self.unknown_model_calls == 0:
            equity = max(ZERO, self.equity() - self.state.known_model_cost)
            self.state.high_watermark = max(self.state.high_watermark, equity)
            self.state.max_drawdown = max(
                self.state.max_drawdown, 1 - equity / self.state.high_watermark
            )

    def check(self):
        pos = self.state.position
        left = self.state.cash + (pos.quantity * pos.entry_price if pos else ZERO)
        right = self.config.capital + self.state.realized_price_pnl - self.state.fees_paid
        if self.state.cash < 0 or abs(left - right) > Decimal("0.000000000000000001"):
            raise RuntimeError("Synthetic cash conservation failed")

    def snapshot(self):
        gross = self.equity() if self.position_fresh else None
        net = (
            gross - self.state.known_model_cost
            if gross is not None and self.unknown_model_calls == 0
            else None
        )
        benchmark = (
            self.state.benchmark_cash
            + self.state.benchmark_quantity * self.state.benchmark_bid
            - self.config.fee_per_fill
            if self.benchmark_fresh and self.state.benchmark_started_at is not None
            else None
        )
        return {
            "mode": "SYNTHETIC_PAPER",
            "policy": POLICY,
            "as_of": self.state.last_as_of.isoformat(),
            "cash": str(self.state.cash),
            "position": self.state.position.model_dump(mode="json")
            if self.state.position
            else None,
            "pending": self.state.pending.model_dump(mode="json") if self.state.pending else None,
            "gross_liquidation_equity": str(gross) if gross is not None else None,
            "net_after_model_cost_equity": str(net) if net is not None else None,
            "gross_return_fraction": str(gross / self.config.capital - 1)
            if gross is not None
            else None,
            "net_return_fraction": str(net / self.config.capital - 1) if net is not None else None,
            "benchmark_liquidation_equity": str(benchmark) if benchmark is not None else None,
            "benchmark_return_fraction": str(benchmark / self.config.capital - 1)
            if benchmark is not None
            else None,
            "net_excess_fraction": str((net - benchmark) / self.config.capital)
            if net is not None and benchmark is not None
            else None,
            "known_model_cost": str(self.state.known_model_cost),
            "unknown_model_calls": self.unknown_model_calls,
            "fees_paid": str(self.state.fees_paid),
            "realized_price_pnl": str(self.state.realized_price_pnl),
            "high_watermark": str(self.state.high_watermark),
            "max_drawdown_fraction": str(self.state.max_drawdown) if net is not None else None,
            "position_valuation_fresh": self.position_fresh,
            "benchmark_valuation_fresh": self.benchmark_fresh,
            "events": self.events,
        }
