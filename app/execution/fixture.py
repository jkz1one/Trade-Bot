"""Local fake venue only. No transport, credentials, broker tools or model calls."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.execution.models import ZERO, Fill, Intent, Observation, Snapshot, VenuePosition


class LocalFixtureVenue:
    def __init__(self, capital: Decimal):
        self.cash = capital
        self.position: VenuePosition | None = None
        self.orders: dict[str, Observation] = {}
        self.submit_count = 0
        self.lose_next_ack = False

    def accept(self, intent: Intent, now: datetime) -> str:
        self.submit_count += 1
        if intent.client_id in self.orders:
            raise RuntimeError("Fixture received a duplicate submission")
        order_id = "fixture-" + intent.client_id
        self.orders[intent.client_id] = Observation(
            order_id=order_id,
            client_id=intent.client_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            status="OPEN",
            filled_quantity=ZERO,
            updated_at=now,
        )
        if self.lose_next_ack:
            self.lose_next_ack = False
            raise TimeoutError("Fixture accepted order but lost acknowledgment")
        return order_id

    def fill(self, client_id, quantity, price, at, *, fee=ZERO, fill_id=None):
        order = self.orders[client_id]
        if order.status not in {"OPEN", "PARTIAL"}:
            raise ValueError("Fixture order is terminal")
        fill = Fill(
            fill_id=fill_id or uuid4().hex,
            order_id=order.order_id,
            quantity=quantity,
            price=price,
            fee=fee,
            occurred_at=at,
        )
        total = order.filled_quantity + quantity
        updated = Observation(
            **{
                **order.model_dump(),
                "filled_quantity": total,
                "status": "FILLED" if total == order.quantity else "PARTIAL",
                "updated_at": at,
                "fills": [*order.fills, fill],
            }
        )
        if order.side == "BUY":
            if self.position and self.position.symbol != order.symbol:
                raise ValueError("Fixture cannot have two positions")
            cost = quantity * price + fee
            if cost > self.cash:
                raise ValueError("Insufficient fixture cash")
            old = self.position
            old_quantity = old.quantity if old else ZERO
            basis = old.quantity * old.entry_price if old else ZERO
            position = VenuePosition(
                symbol=order.symbol,
                quantity=old_quantity + quantity,
                entry_price=(basis + quantity * price) / (old_quantity + quantity),
            )
            self.cash -= cost
            self.position = position
        else:
            if not self.position or self.position.symbol != order.symbol:
                raise ValueError("No fixture position to sell")
            remaining = self.position.quantity - quantity
            if remaining < 0 or self.cash + quantity * price < fee:
                raise ValueError("Fixture sale would exceed position or cash")
            self.cash += quantity * price - fee
            self.position = (
                VenuePosition(
                    symbol=order.symbol, quantity=remaining, entry_price=self.position.entry_price
                )
                if remaining
                else None
            )
        self.orders[client_id] = updated
        return fill

    def terminal(self, client_id, status, at):
        order = self.orders[client_id]
        if order.status not in {"OPEN", "PARTIAL"}:
            raise ValueError("Fixture order is already terminal")
        self.orders[client_id] = Observation(
            **{**order.model_dump(), "status": status, "updated_at": at}
        )

    def snapshot(self, at, *, snapshot_id=None):
        reserved = sum(
            (
                (o.quantity - o.filled_quantity) * o.limit_price
                for o in self.orders.values()
                if o.side == "BUY" and o.status in {"OPEN", "PARTIAL"}
            ),
            ZERO,
        )
        return Snapshot(
            snapshot_id=snapshot_id or uuid4().hex,
            captured_at=at,
            cash=self.cash,
            safe_buying_power=max(ZERO, self.cash - reserved),
            positions=[self.position] if self.position else [],
            orders=list(self.orders.values()),
        )
