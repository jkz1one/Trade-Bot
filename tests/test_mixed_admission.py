"""Order-free native admission projections from one mixed cash history."""

from datetime import timedelta
from decimal import Decimal

import pytest
from test_mixed_accounting import (
    NOW,
    H,
    allocation,
    buy,
    changed,
    history,
    instrument,
    policy,
    trade,
)
from test_mixed_accounting import option_trades as option_trades  # noqa: PLC0414
from test_option_execution import configuration

from app.mixed.governor import admit_stock, option_account
from app.mixed.models import CostRecord, Reservation, StockProposal, StockQuote
from app.options.governor import admit_option
from app.options.models import SessionWindow

D = Decimal


def proposal(**changes):
    p = StockProposal(
        action="OPEN_LONG",
        instrument=instrument(),
        source_hash=H,
        family="SWING",
        source_at=NOW - timedelta(seconds=20),
        valid_until=NOW + timedelta(seconds=3),
        exit_at=NOW + timedelta(minutes=20),
        original_invalidation="90",
        original_target="120",
        thesis="Original completed-source share proposal",
    )
    return changed(p, **changes)


def quote(**changes):
    q = StockQuote(
        instrument=instrument(),
        source="stock-tape",
        source_at=NOW,
        received_at=NOW,
        entitlement="REALTIME",
        complete=True,
        bid="99.99",
        ask="100",
        bid_size="10",
        ask_size="10",
    )
    return changed(q, **changes)


def session(**changes):
    s = SessionWindow(
        source=policy().options.session_source,
        underlying="SPY",
        opens_at=NOW - timedelta(hours=1),
        entry_cutoff_at=NOW + timedelta(hours=1),
        closes_at=NOW + timedelta(hours=2),
    )
    return changed(s, **changes)


def admit(h=None, p=None, q=None, s=None, **kwargs):
    return admit_stock(
        p or proposal(),
        q or quote(),
        h or history(),
        s or session(),
        now=kwargs.pop("now", NOW),
        reconciled=kwargs.pop("reconciled", True),
        **kwargs,
    )


def test_stock_admission_uses_one_full_cost_budget_and_original_deadline():
    result = admit()
    assert result.outcome == "APPROVED"
    assert result.quantity == 5  # 600 daily full-loss headroom includes both sets of fees.
    assert result.entry_debit == D("500.15")
    assert result.reserved_exit_fee == D(".55")
    assert result.approval_expires_at == NOW + timedelta(seconds=3)
    assert len(result.history_hash) == 64 and len(result.proposal_hash) == 64


def test_native_reconciliation_is_required_explicitly_by_default():
    r = admit_stock(proposal(), quote(), history(), session(), now=NOW)
    assert r.outcome == "REJECTED"
    assert "MIXED_FRESH_RECONCILIATION_REQUIRED" in r.reasons
    assert not option_account(history()).reconciled


def test_stock_holding_blocks_existing_native_option_governor():
    h = history((trade(buy(), 1),))
    account = option_account(h, reconciled=True)
    assert account.position.kind == "EQUITY" and account.position.quantity == 2
    data, limits, _ = configuration()
    result = admit_option(
        data["proposal"],
        data["quote"],
        data["underlying"],
        account,
        limits,
        data["session"],
        now=NOW,
    )
    assert result.outcome == "REJECTED"
    assert account.cash == D("799.88")


def test_option_holding_blocks_stock_admission(option_trades):
    events, _ = option_trades
    r = admit(h=history(events[:1]))
    assert r.outcome == "REJECTED" and "MIXED_POSITION_OWNED" in r.reasons


@pytest.mark.parametrize("kind", ["STOCK", "OPTION"])
def test_pending_order_in_either_instrument_blocks_stock_admission(option_trades, kind):
    intent = buy() if kind == "STOCK" else option_trades[0][0].intent
    r = admit(h=history(reservations=(Reservation(intent=intent, status="UNKNOWN"),)))
    assert r.outcome == "REJECTED" and "MIXED_ORDER_UNRESOLVED" in r.reasons


def test_all_charges_reduce_new_stock_quantity_after_previous_option_loss(option_trades):
    events, _ = option_trades
    costs = (
        *allocation(),
        CostRecord(
            cost_id="management",
            kind="MANAGEMENT_MODEL",
            occurred_at=NOW,
            amount="100",
            entry_client_id=events[0].intent.client_id,
            evidence_hash=H,
        ),
    )
    r = admit(h=history(events, costs=costs))
    assert r.outcome == "APPROVED" and r.quantity == 4
    assert option_account(history(events, costs=costs), reconciled=True).daily_loss_available == D(
        "476.8"
    )


@pytest.mark.parametrize(
    "defect",
    [
        "unknown-cost",
        "missing-allocation",
        "stale-account",
        "future-account",
        "halted",
        "expired-source",
        "cutoff",
        "wrong-session",
        "stale-quote",
        "future-quote",
        "wrong-source",
        "foreign-instrument",
        "delayed",
        "incomplete",
        "missing-size",
        "zero-size",
        "spread",
        "cheap",
        "stop-breached",
        "target-passed",
        "unfunded",
    ],
)
def test_stock_admission_fails_closed(defect):
    h, p, q, s = history(), proposal(), quote(), session()
    kwargs = {}
    if defect == "unknown-cost":
        h = changed(
            h,
            costs=(
                *h.costs,
                CostRecord(
                    cost_id="unknown",
                    kind="ENTRY_MODEL",
                    occurred_at=NOW,
                    amount=None,
                    evidence_hash=H,
                ),
            ),
        )
    if defect == "missing-allocation":
        h = changed(h, costs=())
    if defect == "stale-account":
        h = changed(
            h, captured_at=NOW - timedelta(seconds=policy().options.account_max_age_seconds)
        )
    if defect == "future-account":
        h = changed(h, captured_at=NOW + timedelta(seconds=1))
    if defect == "halted":
        kwargs["entry_halted"] = True
    if defect == "expired-source":
        p = changed(p, valid_until=NOW)
    if defect == "cutoff":
        s = changed(s, entry_cutoff_at=NOW)
    if defect == "wrong-session":
        s = changed(s, underlying="QQQ")
    if defect == "stale-quote":
        q = changed(
            q, source_at=NOW - timedelta(seconds=30), received_at=NOW - timedelta(seconds=30)
        )
    if defect == "future-quote":
        q = changed(q, source_at=NOW + timedelta(seconds=1), received_at=NOW + timedelta(seconds=1))
    if defect == "wrong-source":
        q = changed(q, source="wrong")
    if defect == "foreign-instrument":
        q = changed(q, instrument=changed(q.instrument, instrument_id="foreign"))
    if defect == "delayed":
        q = changed(q, entitlement="DELAYED")
    if defect == "incomplete":
        q = changed(q, complete=False)
    if defect == "missing-size":
        q = changed(q, ask_size=None)
    if defect == "zero-size":
        q = changed(q, ask_size="0")
    if defect == "spread":
        q = changed(q, bid="70")
    if defect == "cheap":
        q = changed(q, bid="4", ask="4.01")
    if defect == "stop-breached":
        p = changed(p, original_invalidation="100")
    if defect == "target-passed":
        p = changed(p, original_target="99")
    if defect == "unfunded":
        h = changed(
            h, policy=changed(h.policy, capital="10", daily_loss_limit="5", total_loss_limit="10")
        )
    assert admit(h=h, p=p, q=q, s=s, **kwargs).outcome == "REJECTED"


def test_original_source_expiry_is_not_extended_by_fresh_quote_or_new_account():
    p = proposal(valid_until=NOW + timedelta(seconds=1))
    first = admit(p=p)
    assert first.approval_expires_at == NOW + timedelta(seconds=1)
    now = NOW + timedelta(seconds=1)
    assert (
        admit(
            h=history(captured_at=now), p=p, q=quote(source_at=now, received_at=now), now=now
        ).outcome
        == "REJECTED"
    )


def test_close_retains_independence_from_entry_halt_unknown_cost_and_entry_cutoff():
    h = history((trade(buy(), 1),), costs=())
    p = StockProposal(action="CLOSE", instrument=instrument(), thesis="Independent mandatory exit")
    q = quote(bid="4", ask="100", bid_size="1")
    r = admit(h=h, p=p, q=q, s=session(entry_cutoff_at=NOW), entry_halted=True)
    assert r.outcome == "APPROVED" and r.quantity == 1 and r.limit_price == 4
    assert r.entry_debit == 0 and r.reserved_exit_fee == 0


def test_close_requires_exact_stock_ownership_and_executable_size():
    p = StockProposal(action="CLOSE", instrument=instrument(), thesis="Close owned stock only")
    assert admit(p=p).outcome == "REJECTED"
    h = history((trade(buy(), 1),))
    assert admit(h=h, p=p, q=quote(bid_size=None)).outcome == "REJECTED"
    assert admit(h=h, p=p, q=quote(bid_size=".5")).outcome == "REJECTED"


def test_hold_has_no_order_or_model_activity():
    r = admit_stock(
        StockProposal(action="HOLD", thesis="Stay cash"), None, history(), None, now=NOW
    )
    assert r.outcome == "HOLD" and r.quantity == 0


def test_fractional_share_admission_obeys_frozen_increment():
    p = policy()
    p = changed(
        p,
        stocks=changed(
            p.stocks, share_step=".00000001", entry_fee_per_order="0", exit_fee_per_order="0"
        ),
    )
    h = history(policy=p)
    r = admit(h=h, q=quote(ask_size=".12345678"))
    assert r.outcome == "APPROVED" and r.quantity == D(".12345678")
    assert r.entry_debit == D("12.3469125678")
