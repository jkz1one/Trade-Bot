"""Versioned multi-play state in the existing durable PAPER venue.

All holdings use the same cash balance and globally ordered receipt sequence.
Legacy fixture schemas remain scalar and are never implicitly enrolled.
"""

from typing import Literal

from pydantic import Field, model_validator

from app.mixed.portfolio_accounting import PortfolioLedger, PortfolioPolicy, entry_id, play_id
from app.mixed.stock_models import StockIntent, StockPosition
from app.options.lifecycle import TERMINAL, OptionIntent, OptionPosition, OptionVenueSnapshot
from app.options.models import Name
from app.options.venue import VenueState


class PortfolioVenueState(VenueState):
    positions: dict[Name, StockPosition | OptionPosition] = Field(default_factory=dict)
    intents: dict[Name, StockIntent | OptionIntent] = Field(default_factory=dict)
    settlement_plays: dict[Name, Name] = Field(default_factory=dict)

    @model_validator(mode="after")
    def portfolio_binding(self):
        PortfolioLedger(
            cash=self.cash,
            settled_cash=self.settled_cash,
            high_watermark=self.cash,
            position=self.position,
            stock_position=self.stock_position,
            positions=self.positions,
        )
        orders = (*self.orders, *self.stock_orders)
        if set(self.intents) != {o.client_id for o in orders}:
            raise ValueError("Portfolio venue requires every original intent")
        for order in orders:
            intent = self.intents[order.client_id]
            if any(
                getattr(order, k) != getattr(intent, k)
                for k in ("client_id", "instrument", "side", "quantity", "limit_price")
            ):
                raise ValueError("Portfolio order changed original terms")
        active = [play_id(self.intents[o.client_id]) for o in orders if o.status not in TERMINAL]
        if len(active) != len(set(active)):
            raise ValueError("One unresolved order per play required")
        expected = {r.receipt_id for r in self.receipts if r.kind != "FUNDS_SETTLED"}
        if set(self.settlement_plays) != expected:
            raise ValueError("Exact option settlement play bindings required")
        return self


class PortfolioVenueSnapshot(OptionVenueSnapshot):
    environment: Literal["LOCAL_PORTFOLIO_FIXTURE"] = "LOCAL_PORTFOLIO_FIXTURE"
    portfolio_policy: PortfolioPolicy
    positions: dict[Name, StockPosition | OptionPosition]
    settlement_plays: dict[Name, Name] = Field(default_factory=dict)

    @model_validator(mode="after")
    def portfolio_binding(self):
        if self.stock_limits != self.portfolio_policy.stocks:
            raise ValueError("Portfolio stock policy changed")
        PortfolioLedger(
            cash=self.cash,
            settled_cash=self.settled_cash,
            high_watermark=self.cash,
            position=self.position,
            stock_position=self.stock_position,
            positions=self.positions,
        )
        return self


def view(state, identity):
    held = state.positions.get(identity)
    return state.model_copy(
        update={
            "position": held if isinstance(held, OptionPosition) else None,
            "stock_position": held if isinstance(held, StockPosition) else None,
        }
    )


def merge(prior, updated, identity):
    positions = dict(prior.positions)
    held = updated.position or updated.stock_position
    if held is None:
        positions.pop(identity, None)
    else:
        if entry_id(held) != identity:
            raise ValueError("Venue mutation changed play identity")
        positions[identity] = held
    return updated.model_copy(
        update={"position": None, "stock_position": None, "positions": positions}
    )


def projection(venue, state, at):
    """Reconstruct venue economics independently from all retained native receipts."""
    from app.mixed.accounting import reconstruct
    from app.mixed.models import OptionTrade, Reservation, Settlement, StockTrade
    from app.mixed.portfolio_accounting import PortfolioHistory

    events, reservations = [], []
    for order in (*state.orders, *state.stock_orders):
        intent = state.intents[order.client_id]
        cls = StockTrade if isinstance(intent, StockIntent) else OptionTrade
        events.extend(
            cls(intent=intent, attempted_at=intent.prepared_at, fill=f) for f in order.fills
        )
        if order.status not in TERMINAL:
            reservations.append(Reservation(intent=intent, status=order.status))
    events.extend(
        Settlement(receipt=r, play_id=state.settlement_plays.get(r.receipt_id))
        for r in state.receipts
    )
    opened = min((i.prepared_at for i in state.intents.values()), default=at)
    h = PortfolioHistory(
        account_id=venue.account_id,
        population_id=venue.population_id,
        venue_id=venue.venue_id,
        policy=venue.portfolio_policy,
        opened_at=opened,
        captured_at=at,
        events=tuple(events),
        reservations=tuple(reservations),
    )
    return reconstruct(h)


def validate(venue, state, at):
    result = projection(venue, state, at)
    if (result.ledger.cash, result.ledger.settled_cash, result.ledger.positions) != (
        state.cash,
        state.settled_cash,
        state.positions,
    ):
        raise ValueError("Portfolio venue economics do not match receipts")
    if result.reserved_cash > state.settled_cash:
        raise ValueError("Portfolio venue reservations exceed shared settled funds")
    return result


def accepting(venue, state, intent, at):
    """Defense in depth inside the venue's single SQLite write transaction."""
    from app.mixed.portfolio_accounting import exit_reserve, intent_identity, unfilled_debit
    from app.mixed.portfolio_capacity import INDEX_UNDERLYINGS

    original = merge(state, state, play_id(intent))
    result = validate(venue, original, at)
    if intent.side == "BUY":
        instrument, underlying, _ = intent_identity(intent)
        p = venue.portfolio_policy
        required = unfilled_debit(p, intent, 0) + exit_reserve(
            p, intent.quantity, isinstance(intent, StockIntent)
        )
        reasons = []
        if len(result.commitments) >= p.max_plays:
            reasons.append("PLAY_CAPACITY")
        if any(
            c.instrument_id == instrument or c.underlying == underlying for c in result.commitments
        ):
            reasons.append("DUPLICATE_EXPOSURE")
        if result.reserved_cash + required > state.settled_cash:
            reasons.append("SETTLED_FUNDS")

        def envelope(c):
            return c.invested_loss + c.remaining_debit + c.exit_reserve

        if sum(map(envelope, result.commitments)) + required > p.exposure_limit:
            reasons.append("ACCOUNT_EXPOSURE")
        if (
            underlying in INDEX_UNDERLYINGS
            and sum(envelope(c) for c in result.commitments if c.underlying in INDEX_UNDERLYINGS)
            + required
            > p.index_exposure_limit
        ):
            reasons.append("CORRELATED_INDEX_EXPOSURE")
        # The venue knows fills, not model/operating costs. The native journal must
        # separately approve the complete loss budget; no zero costs are invented.
        if reasons:
            raise ValueError(";".join(reasons))
    elif play_id(intent) not in original.positions:
        raise ValueError("Portfolio close targets unknown or closed play")
    if any(
        play_id(state.intents[o.client_id]) == play_id(intent) and o.status not in TERMINAL
        for o in (*state.orders, *state.stock_orders)
    ):
        raise ValueError("Portfolio play already has an unresolved order")
