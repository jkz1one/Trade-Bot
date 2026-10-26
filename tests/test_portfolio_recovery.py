"""Native uncertain attempts and partial-entry terminal evidence across restarts."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from test_mixed_venue import q
from test_portfolio_controls import NOW, get_intent, owned, stock

from app.mixed.accounting import reconstruct
from app.mixed.portfolio_store import history
from app.options.engine import OptionExecution


@pytest.mark.parametrize("fault", ["LOST_ACK", "INVALID_ACK", "CRASH_AFTER_ACCEPT"])
def test_uncertain_attempt_retains_capacity_and_never_resubmits(tmp_path, fault):
    with owned(tmp_path) as (e, v):
        pr, quote = stock("SPY")
        out = e.prepare_stock("uncertain", pr, quote, now=NOW)
        assert out["status"] == "PREPARED", out
        v.fault = fault
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "UNKNOWN"
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "UNKNOWN"
        assert v.submit_count == 1
        with e.journal.read() as db:
            p = reconstruct(history(e, db, e.portfolio_policy, NOW))
            assert p.commitments[0].uncertain and p.reserved_cash > 0
        other, oq = stock("QQQ")
        blocked = e.prepare_stock("blocked", other, oq, now=NOW)
        assert blocked["status"] == "REJECTED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    v.fault = "NONE"
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "OPEN"
        assert v.submit_count == 1
        with e.journal.read() as db:
            assert len(reconstruct(history(e, db, e.portfolio_policy, NOW)).commitments) == 1
            assert e._control(db)["halted"]


def test_partial_entry_cancel_releases_only_unfilled_cash_and_preserves_other_play(tmp_path):
    with owned(tmp_path) as (e, v):
        entries = []
        for symbol in ("SPY", "QQQ"):
            pr, quote = stock(symbol)
            out = e.prepare_stock(symbol, pr, quote, now=NOW)
            assert out["status"] == "PREPARED"
            entry = get_intent(e, out["client_id"])
            assert asyncio.run(e.dispatch_stock(entry.client_id, quote, now=NOW)) == "OPEN"
            entries.append(entry)
        at = NOW + timedelta(seconds=1)
        partial = Decimal(".1")
        for entry, quantity in zip(entries, (partial, entries[1].quantity), strict=True):
            v.fill_stock(entry, quantity, q(entry, at), at, fill_id=entry.client_id)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        with e.journal.read() as db:
            before = reconstruct(history(e, db, e.portfolio_policy, at))
        v.record_stock_terminal(entries[0].client_id, "CANCELED", at)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        with e.journal.read() as db:
            after = reconstruct(history(e, db, e.portfolio_policy, at))
        assert after.ledger == before.ledger
        assert len(after.commitments) == 2 and after.reserved_cash < before.reserved_cash
        assert after.ledger.positions[entries[0].client_id].quantity == partial
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=at) as e:
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        with e.journal.read() as db:
            assert reconstruct(history(e, db, e.portfolio_policy, at)) == after


def test_restart_after_durable_submit_marker_never_retries_unobserved_order(tmp_path):
    from app.mixed.portfolio_execution import begin_stock

    with owned(tmp_path) as (e, v):
        pr, quote = stock("SPY")
        out = e.prepare_stock("crash-before-child", pr, quote, now=NOW)
        assert begin_stock(e, out["client_id"], quote, NOW).client_id == out["client_id"]
        assert v.submit_count == 0
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "UNKNOWN"
        assert v.submit_count == 0
        with e.journal.read() as db:
            p = reconstruct(history(e, db, e.portfolio_policy, NOW))
            assert len(p.commitments) == 1 and p.commitments[0].uncertain and p.reserved_cash > 0
