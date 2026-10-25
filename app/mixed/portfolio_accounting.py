"""Versioned multi-play projection of one globally ordered native cash history.

The scalar reducers receive the same current account balance and an explicitly
selected position. They are never funded independently. No order authority lives
here; enrollment/admission must still happen in the native owner's transaction.
"""

from decimal import Decimal
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from app.mixed.models import (
    CashHistory,
    CashProjection,
    MixedLedger,
    MixedPolicy,
    Reservation,
    StockAdmission,
)
from app.mixed.portfolio_capacity import PlayCommitment, PortfolioCapacity
from app.mixed.stock_models import StockIntent, StockPosition
from app.options.lifecycle import OptionIntent, OptionPosition
from app.options.models import Money, Name

ZERO = Decimal(0)
VERSION = "mixed-cash-history-v2"


class PortfolioPolicy(MixedPolicy):
    version: Literal["mixed-cash-history-v2"] = VERSION
    max_plays: StrictInt = Field(default=2, ge=0, le=2)
    exposure_limit: Money = Field(gt=0)
    index_exposure_limit: Money = Field(gt=0)

    @model_validator(mode="after")
    def shared_limits(self):
        if (
            not self.index_exposure_limit
            <= self.exposure_limit
            <= min(
                self.capital, self.options.max_account_exposure, self.stocks.max_account_exposure
            )
        ):
            raise ValueError("Portfolio exposure must fit both existing account ceilings")
        return self


class PortfolioLedger(MixedLedger):
    version: Literal["mixed-cash-history-v2"] = VERSION
    positions: dict[Name, StockPosition | OptionPosition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def keyed_positions(self):
        if self.position is not None or self.stock_position is not None:
            raise ValueError("Portfolio positions require explicit play identity")
        if len(self.positions) > 2:
            raise ValueError("Portfolio supports at most two held plays")
        underlyings, instruments = set(), set()
        for play_id, position in self.positions.items():
            if play_id != entry_id(position):
                raise ValueError("Portfolio position key must bind original entry")
            underlying = symbol(position)
            instrument = instrument_id(position)
            if underlying in underlyings or instrument in instruments:
                raise ValueError("Duplicate portfolio exposure")
            underlyings.add(underlying)
            instruments.add(instrument)
        return self


class PortfolioHistory(CashHistory):
    version: Literal["mixed-cash-history-v2"] = VERSION
    policy: PortfolioPolicy
    reservations: tuple[Reservation, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def typed_reservations(self):
        ids = [r.intent.client_id for r in self.reservations]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate portfolio reservation identity")
        return self


class PortfolioProjection(CashProjection):
    version: Literal["mixed-cash-history-v2"] = VERSION
    ledger: PortfolioLedger
    commitments: tuple[PlayCommitment, ...] = Field(default=(), max_length=2)


class PortfolioStockAdmission(StockAdmission):
    version: Literal["mixed-portfolio-stock-admission-v2"] = "mixed-portfolio-stock-admission-v2"
    play_id: Name | None


def parse_history(history):
    value = history.model_dump(warnings=False)
    cls = PortfolioHistory if value.get("version") == VERSION else CashHistory
    return cls.model_validate(value)


def entry_id(position):
    return (
        position.entry.client_id
        if isinstance(position, StockPosition)
        else position.entry_client_id
    )


def symbol(position):
    return (
        position.instrument.symbol
        if isinstance(position, StockPosition)
        else position.contract.underlying
    )


def instrument_id(position):
    if isinstance(position, StockPosition):
        return position.instrument.instrument_id
    return position.contract.contract_id


def intent_identity(intent):
    if isinstance(intent, StockIntent):
        return intent.instrument.instrument_id, intent.instrument.symbol, intent.family
    lineage = intent.entry_lineage
    if lineage is None:
        raise ValueError("Portfolio option entry requires original strategy lineage")
    return (
        intent.instrument.contract.contract_id,
        intent.instrument.contract.underlying,
        lineage.family,
    )


def check_option_source_size(intent, fill, used):
    """A later receipt timestamp cannot renew size from the same source quote."""
    q = fill.quote
    key = (q.instrument.contract.contract_id, intent.side, q.source, q.source_at)
    previous, quantity = used.get(key, (q, 0))
    if previous.instrument != q.instrument or any(
        getattr(previous, name) != getattr(q, name)
        for name in ("bid", "ask", "bid_size", "ask_size")
    ):
        raise ValueError("PORTFOLIO_OPTION_SOURCE_QUOTE_CHANGED")
    quantity += fill.quantity
    size = q.ask_size if intent.side == "BUY" else q.bid_size
    if size is None or quantity > size:
        raise ValueError("PORTFOLIO_OPTION_SOURCE_SIZE_EXCEEDED")
    used[key] = (q, quantity)


def play_id(intent):
    if intent.side == "BUY":
        return intent.client_id
    if intent.closing_entry_client_id is None:
        raise ValueError("Portfolio sale requires exact original entry identity")
    return intent.closing_entry_client_id


def select(state, identity):
    """Transient reducer view; keeps all account cash, costs and realized P&L."""
    held = state.positions.get(identity)
    fields = {k: v for k, v in state.model_dump().items() if k in MixedLedger.model_fields}
    fields.update(version="mixed-cash-history-v1", position=None, stock_position=None)
    fields["stock_position" if isinstance(held, StockPosition) else "position"] = held
    return MixedLedger.model_validate(fields)


def merge(state, identity, updated):
    positions = dict(state.positions)
    held = updated.stock_position or updated.position
    if held is None:
        positions.pop(identity, None)
    else:
        if entry_id(held) != identity:
            raise ValueError("Reducer changed play identity")
        positions[identity] = held
    fields = updated.model_dump()
    fields.update(
        version=VERSION,
        position=None,
        stock_position=None,
        positions=positions,
        # The scalar reducer cannot declare the account flat while another play remains.
        high_watermark=max(state.high_watermark, updated.cash if not positions else ZERO),
    )
    return PortfolioLedger.model_validate(fields)


def apply_trade(state, intent, fill):
    from app.mixed.accounting import _apply_stock, _merge, _option_part
    from app.options.accounting import apply_fill

    identity = play_id(intent)
    current = select(state, identity)
    if intent.side == "SELL" and identity not in state.positions:
        raise ValueError("Portfolio sale targets unknown or closed play")
    if isinstance(intent, OptionIntent):
        if current.stock_position is not None:
            raise ValueError("Portfolio option sale targets stock play")
        if intent.side == "SELL" and (
            intent.original_underlying_invalidation
            != current.position.original_underlying_invalidation
            or intent.exit_at != current.position.exit_at
        ):
            raise ValueError("Portfolio sale changed original option protection")
        updated = _merge(current, apply_fill(_option_part(current), intent, fill))
    else:
        updated = _apply_stock(current, intent, fill)
    return merge(state, identity, updated)


def remaining_budget(history, projection, underlying):
    """Shared full-loss headroom for native quantity sizing, not extra bankroll."""
    from app.mixed.portfolio_capacity import INDEX_UNDERLYINGS

    committed = sum(
        (c.invested_loss + c.remaining_debit + c.exit_reserve for c in projection.commitments), ZERO
    )
    p = history.policy
    budget = min(
        projection.available_settled_cash,
        max(ZERO, (projection.daily_loss_available or ZERO) - committed),
        max(ZERO, (projection.total_loss_available or ZERO) - committed),
        max(ZERO, p.exposure_limit - committed),
    )
    if underlying in INDEX_UNDERLYINGS:
        index = sum(
            (
                c.invested_loss + c.remaining_debit + c.exit_reserve
                for c in projection.commitments
                if c.underlying in INDEX_UNDERLYINGS
            ),
            ZERO,
        )
        budget = min(budget, max(ZERO, p.index_exposure_limit - index))
    return budget


def candidate_blockers(history, projection, underlying, instrument):
    reasons = list(projection.entry_blockers)
    if any(
        c.underlying == underlying or c.instrument_id == instrument for c in projection.commitments
    ):
        reasons.append("DUPLICATE_EXPOSURE")
    return tuple(dict.fromkeys(reasons))


def apply_settlement(state, event):
    from app.mixed.accounting import _merge, _option_part
    from app.options.accounting import apply_receipt

    if event.receipt.kind == "FUNDS_SETTLED":
        if event.play_id is not None:
            raise ValueError("Funds settlement is account-wide")
        identity = None
    else:
        identity = event.play_id
        if identity is None or not isinstance(state.positions.get(identity), OptionPosition):
            raise ValueError("Portfolio settlement requires exact owned option play")
    current = select(state, identity)
    return merge(
        state, identity, _merge(current, apply_receipt(_option_part(current), event.receipt))
    )


def reservations(history, state, intents, quantities, debits):
    from app.mixed.accounting import _validate_intent

    p = history.policy
    amounts = {}
    for identity, held in state.positions.items():
        intent = intents.get(identity)
        if intent is None or intent.side != "BUY":
            raise ValueError("Portfolio position missing original entry")
        instrument, underlying, family = intent_identity(intent)
        reserve = exit_reserve(p, held.quantity, isinstance(held, StockPosition))
        amounts[identity] = {
            "play_id": identity,
            "entry_client_id": identity,
            "instrument_id": instrument,
            "underlying": underlying,
            "family": family,
            "invested_loss": held.basis,
            "remaining_debit": ZERO,
            "exit_reserve": reserve,
            "has_position": True,
            "pending_entry": False,
            "uncertain": False,
        }
    working_plays = set()
    for item in history.reservations:
        intent = item.intent
        _validate_intent(p, intent)
        identity = play_id(intent)
        if identity in working_plays:
            raise ValueError("One unresolved order per play required")
        working_plays.add(identity)
        if not history.opened_at <= intent.prepared_at <= history.captured_at:
            raise ValueError("MIXED_FUTURE_RESERVATION")
        if intent.client_id in intents and intents[intent.client_id] != intent:
            raise ValueError("MIXED_RESERVATION_INTENT_CHANGED")
        filled = quantities.get(intent.client_id, ZERO)
        if (
            filled >= intent.quantity
            or (item.status == "PARTIAL" and not filled)
            or (filled and item.status in {"PREPARED", "SUBMITTING", "OPEN"})
        ):
            raise ValueError("MIXED_RESERVATION_FILL_CONFLICT")
        if intent.side == "BUY":
            instrument, underlying, family = intent_identity(intent)
            current = amounts.setdefault(
                identity,
                {
                    "play_id": identity,
                    "entry_client_id": identity,
                    "instrument_id": instrument,
                    "underlying": underlying,
                    "family": family,
                    "invested_loss": ZERO,
                    "has_position": False,
                    "uncertain": False,
                },
            )
            current.update(
                pending_entry=True,
                remaining_debit=unfilled_debit(p, intent, filled),
                exit_reserve=exit_reserve(p, intent.quantity, isinstance(intent, StockIntent)),
            )
        else:
            held = state.positions.get(identity)
            if held is None or isinstance(held, StockPosition) != isinstance(intent, StockIntent):
                raise ValueError("MIXED_RESERVATION_UNOWNED_SALE")
            if (isinstance(held, StockPosition) and held.instrument != intent.instrument) or (
                isinstance(held, OptionPosition) and held.contract != intent.instrument.contract
            ):
                raise ValueError("MIXED_RESERVATION_UNOWNED_SALE")
            if intent.quantity - filled > held.quantity:
                raise ValueError("MIXED_RESERVATION_OVERSELL")
        amounts[identity]["uncertain"] |= item.status in {"UNKNOWN", "SUBMITTING"}
        intents[intent.client_id] = intent
    commitments = tuple(PlayCommitment(**a) for a in amounts.values())
    if len(commitments) > 2:
        raise ValueError("Portfolio supports at most two committed plays")
    for field in ("underlying", "instrument_id"):
        if len({getattr(c, field) for c in commitments}) != len(commitments):
            raise ValueError("Duplicate portfolio exposure")
    reserved = sum((c.remaining_debit + c.exit_reserve for c in commitments), ZERO)
    blockers = []
    if len(commitments) >= p.max_plays:
        blockers.append("PLAY_CAPACITY")
    if any(c.uncertain for c in commitments):
        blockers.append("ACCOUNT_UNCERTAIN")
    if reserved > state.settled_cash:
        blockers.append("MIXED_EXIT_RESERVE_UNFUNDED")
    return reserved, blockers, commitments


def unfilled_debit(policy, intent, filled):
    """Reserve remaining units at the fixed limit, not price savings on filled units."""
    remaining = intent.quantity - filled
    if isinstance(intent, StockIntent):
        p = policy.stocks
        return remaining * (intent.limit_price + p.entry_fee_per_share) + (
            p.entry_fee_per_order if not filled else ZERO
        )
    p = policy.options
    return remaining * (
        intent.limit_price * intent.instrument.contract.multiplier + p.entry_fee_per_contract
    ) + (p.entry_fee_per_order if not filled else ZERO)


def exit_reserve(policy, quantity, stock):
    if stock:
        return quantity * (
            policy.stocks.exit_fee_per_share
            + policy.stocks.exit_fee_per_order / policy.stocks.share_step
        )
    return quantity * (policy.options.exit_fee_per_contract + policy.options.exit_fee_per_order)


def capacity(history, projection, *, revision, reconciled, halted):
    if not isinstance(history, PortfolioHistory) or not isinstance(projection, PortfolioProjection):
        raise ValueError("Versioned portfolio history required")  # noqa: TRY004 -- enrollment version
    return PortfolioCapacity(
        account_id=history.account_id,
        population_id=history.population_id,
        revision=revision,
        max_plays=history.policy.max_plays,
        settled_cash=projection.ledger.settled_cash,
        daily_loss_remaining=projection.daily_loss_available or ZERO,
        total_loss_remaining=projection.total_loss_available or ZERO,
        exposure_limit=history.policy.exposure_limit,
        index_exposure_limit=history.policy.index_exposure_limit,
        costs_known=not projection.unknown_cost_ids,
        reconciled=reconciled,
        halted=halted,
        plays=projection.commitments,
    )
