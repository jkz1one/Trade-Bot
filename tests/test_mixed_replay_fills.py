"""Later executable shares obey one source size despite receipt aliases."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_mixed_accounting import buy, changed, policy, trade

from app.mixed.replay import stock_fill_quantity
from app.mixed.stock_models import StockObservation


@pytest.mark.parametrize(
    "kind", ["receipt_alias", "new_source", "unknown_size", "stale", "wide", "changed_source"]
)
def test_recorded_stock_fill_capacity_retains_original_executable_source(kind):
    entry = buy()
    first = trade(entry, 1, quantity="1")
    q = changed(first.fill.quote, ask_size="1")
    first = trade(entry, 1, quantity="1", q=q)
    at = first.fill.occurred_at + timedelta(seconds=1)
    current = changed(q, received_at=at)
    if kind == "new_source":
        current = changed(current, source_at=at)
    elif kind == "unknown_size":
        current = changed(current, source_at=at, ask_size=None)
    elif kind == "stale":
        at += timedelta(seconds=30)
    elif kind == "wide":
        current = changed(current, source_at=at, bid="10")
    elif kind == "changed_source":
        current = changed(current, ask_size="2")
    order = StockObservation(
        intent=entry,
        client_id=entry.client_id,
        order_id=first.fill.order_id,
        instrument=entry.instrument,
        side=entry.side,
        quantity=entry.quantity,
        limit_price=entry.limit_price,
        status="PARTIAL",
        filled_quantity="1",
        updated_at=first.fill.occurred_at,
        fills=(first.fill,),
    )
    snapshot = SimpleNamespace(stock_orders=(order,))
    if kind == "changed_source":
        with pytest.raises(ValueError, match="conflicts"):
            stock_fill_quantity(entry, order, snapshot, current, at, policy().stocks)
    else:
        assert stock_fill_quantity(entry, order, snapshot, current, at, policy().stocks) == Decimal(
            kind == "new_source"
        )
