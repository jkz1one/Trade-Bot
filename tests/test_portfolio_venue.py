"""Actual shared durable PAPER venue receipts, never broker operations."""

from datetime import timedelta

import pytest
from test_mixed_accounting import changed, sell
from test_mixed_venue import q
from test_portfolio_accounting import portfolio, two_stocks

from app.options.venue import DurableOptionVenue


def venue(tmp_path):
    p = portfolio().policy
    return DurableOptionVenue(
        tmp_path / "venue.db",
        limits=p.options,
        stock_limits=p.stocks,
        capital=p.capital,
        portfolio_policy=p,
    )


def test_two_pending_and_held_stocks_keep_one_balance_and_independent_exits(tmp_path):
    v = venue(tmp_path)
    a, b = two_stocks()
    at = a.prepared_at
    for i in (a, b):
        v._accept_stock(i, at, None, None)
    snap = v.snapshot(at)
    assert len(snap.stock_orders) == 2 and not snap.positions
    third = changed(a, client_id="third", source_key="third")
    with pytest.raises(ValueError, match="PLAY_CAPACITY"):
        v._accept_stock(third, at, None, None)
    at += timedelta(seconds=1)
    for i in (a, b):
        v.fill_stock(i, i.quantity, q(i, at), at, fill_id=i.client_id)
    before = v.snapshot(at)
    assert set(before.positions) == {a.client_id, b.client_id}
    assert before.position is None and before.stock_position is None
    v = DurableOptionVenue(v.path)
    assert v.snapshot(at) == before
    closing = sell(a, quantity="1")
    at = closing.prepared_at
    v._accept_stock(closing, at, None, None)
    at += timedelta(seconds=1)
    v.fill_stock(
        closing,
        closing.quantity,
        q(closing, at, bid="102", ask="102.01"),
        at,
        fill_id="partial-close",
    )
    after = v.snapshot(at)
    assert after.positions[b.client_id] == before.positions[b.client_id]
    assert after.positions[a.client_id].quantity == 1
    assert after.cash > before.cash


def test_confirmed_cancellation_releases_only_unfilled_commitment(tmp_path):
    v = venue(tmp_path)
    a, b = two_stocks()
    at = a.prepared_at
    for i in (a, b):
        v._accept_stock(i, at, None, None)
    at += timedelta(seconds=1)
    v.fill_stock(a, "1", q(a, at), at, fill_id="partial")
    v.record_stock_terminal(a.client_id, "CANCELED", at)
    v.record_stock_terminal(b.client_id, "CANCELED", at)
    snap = v.snapshot(at)
    assert set(snap.positions) == {a.client_id}
    replacement = changed(b, client_id="replacement", source_key="replacement")
    v._accept_stock(replacement, at, None, None)
    duplicate = changed(a, client_id="duplicate", source_key="duplicate")
    with pytest.raises(ValueError, match="DUPLICATE_EXPOSURE"):
        v._accept_stock(duplicate, at, None, None)


def test_fixed_child_snapshots_preserve_two_pending_orders(tmp_path):
    import asyncio

    from app.options.process import run_option_process

    v = venue(tmp_path)
    a, b = two_stocks()
    for i in (a, b):
        result = asyncio.run(
            run_option_process(v, now=i.prepared_at, timeout_seconds=5, stock_intent=i)
        )
        assert result.order_id
    result = asyncio.run(run_option_process(v, now=a.prepared_at, timeout_seconds=5))
    assert result.snapshot.environment == "LOCAL_PORTFOLIO_FIXTURE"
    assert len(result.snapshot.stock_orders) == 2


def test_two_concurrent_duplicate_entries_cannot_claim_same_exposure(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    v = venue(tmp_path)
    a, _ = two_stocks()
    b = changed(a, client_id="racing", source_key="racing")

    def attempt(i):
        try:
            return DurableOptionVenue(v.path)._accept_stock(i, i.prepared_at, None, None)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (a, b)))
    assert sum(x is not None for x in outcomes) == 1
    assert v.submit_count == 1
