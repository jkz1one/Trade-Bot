"""Durable options PAPER proof, using a local venue and installed native children."""

import asyncio
import ctypes
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_admission import END, NOW, inputs

from app.execution.economics import CostPolicy, UsageEvidence
from app.execution.engine import ExecutionBlocked
from app.execution.journal import ExecutionJournal
from app.options.engine import OptionExecution, OptionJournal
from app.options.lifecycle import (
    CALENDAR_SOURCE,
    OptionExecutionPolicy,
    OptionIntent,
    OptionLedger,
    OptionReceipt,
)
from app.options.models import OptionProposal
from app.options.process import run_option_process
from app.options.venue import DurableOptionVenue

D = Decimal


def configuration(right="CALL", **changes):
    data = inputs(right)
    limits = data["limits"].model_copy(update={"session_source": CALENDAR_SOURCE})
    policy = OptionExecutionPolicy(
        capital="1000",
        daily_loss_limit="600",
        total_loss_limit="800",
        entry_cutoff_minutes=30,
        exit_cutoff_minutes=15,
        expiry_guard_seconds=60,
        premium_catastrophe_fraction=".5",
        supervisor_max_age_seconds=20,
        process_timeout_seconds=5,
        **changes,
    )
    return data, limits, policy


@contextmanager
def owned(tmp_path, right="CALL", **changes):
    data, limits, policy = configuration(right, **changes)
    venue = DurableOptionVenue(tmp_path / "venue.db", limits=limits, capital=policy.capital)
    with OptionExecution.open(
        tmp_path / "options.db", limits, policy, venue, now=NOW, create=True
    ) as engine:
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        engine.assess(None, None, now=NOW)
        yield engine, venue, data


def intent_for(engine, client_id):
    with engine.journal.read() as db:
        return OptionIntent.model_validate_json(
            db.execute(
                "SELECT intent_json FROM execution_orders WHERE client_id=?", (client_id,)
            ).fetchone()[0]
        )


def ledger(engine):
    return OptionLedger.model_validate(engine.journal.report(now=NOW)["ledger"])


def quote_at(data, now=NOW, **changes):
    return data["quote"].model_copy(update={"source_at": now, "received_at": now, **changes})


def underlying_at(data, now=NOW, **changes):
    return data["underlying"].model_copy(update={"source_at": now, "received_at": now, **changes})


def enter(engine, venue, data, quantity=None):
    prepared = engine.prepare("entry", data["proposal"], data["quote"], data["underlying"], now=NOW)
    assert prepared["status"] == "PREPARED", prepared
    intent = intent_for(engine, prepared["client_id"])
    assert (
        asyncio.run(engine.dispatch(intent.client_id, data["quote"], data["underlying"], now=NOW))
        == "OPEN"
    )
    venue.fill(intent, quantity or intent.quantity, data["quote"], NOW, fill_id="entry-fill")
    assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
    return intent


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_whole_partial_fills_exact_cash_no_replay_and_settled_sale_credit(tmp_path, right):
    with owned(tmp_path, right) as (engine, venue, data):
        buy = enter(engine, venue, data, quantity=1)
        assert buy.quantity == 4
        assert buy.approved_full_premium_loss == D("414.20")
        assert ledger(engine).cash == D("897.35")
        assert ledger(engine).position.quantity == 1
        assert (
            asyncio.run(engine.dispatch(buy.client_id, data["quote"], data["underlying"], now=NOW))
            == "PARTIAL"
        )
        assert venue.submit_count == 1
        venue.fill(buy, 3, data["quote"], NOW, fill_id="entry-rest")
        result = engine.reconcile(venue.snapshot(NOW), now=NOW)
        assert result["new_fills"] == 1
        assert ledger(engine).position.basis == D("404")
        assert ledger(engine).cash == D("592.40")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["new_fills"] == 0
        engine.assess(data["quote"], data["underlying"], now=NOW)
        close = engine.prepare(
            "close",
            OptionProposal(
                action="CLOSE", contract=buy.instrument.contract, thesis="Close fixture position"
            ),
            data["quote"],
            now=NOW,
        )
        assert close["status"] == "PREPARED", close
        sell = intent_for(engine, close["client_id"])
        assert asyncio.run(engine.dispatch(sell.client_id, data["quote"], now=NOW)) == "OPEN"
        venue.fill(sell, 4, data["quote"], NOW, fill_id="exit-fill")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        state = ledger(engine)
        assert state.position is None
        assert state.cash == D("976.80")
        assert state.settled_cash == D("592.40")
        assert state.realized_pnl == D("-16")
        assert state.fees_paid == D("7.20")
        assert state.daily_net_pnl["2026-10-09"] == D("-23.20")
        receipt = OptionReceipt(
            receipt_id="settled",
            sequence=4,
            kind="FUNDS_SETTLED",
            occurred_at=NOW,
            cash_change="384.40",
        )
        venue.record_receipt(receipt)
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["new_receipts"] == 1
        assert ledger(engine).settled_cash == state.cash
        assert venue.submit_count == 2


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, D("1"), "1"])
def test_fractional_or_coerced_fixture_fill_rejected_without_mutation(tmp_path, value):
    with owned(tmp_path) as (engine, venue, data):
        buy = enter(engine, venue, data, quantity=1)
        before = venue.snapshot(NOW)
        with pytest.raises(ValueError, match="Whole fill"):
            venue.fill(buy, value, data["quote"], NOW, fill_id="invalid")
        assert venue.snapshot(NOW) == before


def test_no_averaging_down_other_contract_or_equity_schema(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        buy = enter(engine, venue, data)
        engine.assess(data["quote"], data["underlying"], now=NOW)
        result = engine.prepare(
            "second", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        assert result["status"] == "REJECTED"
        assert venue.submit_count == 1
        with pytest.raises(ValueError, match="execution rehearsal"):
            ExecutionJournal(engine.journal.path)
        assert intent_for(engine, buy.client_id).quantity == 4


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "cash",
        "settled",
        "quantity",
        "provider",
        "incomplete",
        "future",
        "account",
        "duplicate",
        "fee",
        "price",
        "sequence",
        "fill-time",
        "snapshot-id",
    ],
)
def test_bad_authority_preserves_owned_position_and_halts(tmp_path, change):
    with owned(tmp_path) as (engine, venue, data):
        enter(engine, venue, data)
        before = ledger(engine)
        snap = venue.snapshot(NOW)
        order = snap.orders[0]
        fill = order.fills[0]
        updates = {"snapshot_id": "bad-" + change}
        if change == "missing":
            updates.update(orders=(), position=None, cash=D("1000"), settled_cash=D("1000"))
        if change == "cash":
            updates["cash"] = snap.cash + 1
        if change == "settled":
            updates["settled_cash"] = snap.settled_cash + 1
        if change == "quantity":
            updates["position"] = snap.position.model_copy(update={"quantity": 3})
        if change == "provider":
            updates["orders"] = (
                order.model_copy(
                    update={
                        "instrument": order.instrument.model_copy(update={"instrument_id": "wrong"})
                    }
                ),
            )
        if change == "incomplete":
            updates["complete"] = False
        if change == "future":
            updates["captured_at"] = NOW + timedelta(seconds=1)
        if change == "account":
            updates["account_id"] = "other"
        if change == "duplicate":
            updates["orders"] = (order, order)
        if change in {"fee", "price", "sequence", "fill-time"}:
            modified = {
                "fee": {"fee": fill.fee + 1},
                "price": {"price": fill.price + D(".01")},
                "sequence": {"sequence": 2},
                "fill-time": {"occurred_at": NOW - timedelta(seconds=1)},
            }[change]
            updates["orders"] = (
                order.model_copy(update={"fills": (fill.model_copy(update=modified),)}),
            )
        if change == "snapshot-id":
            updates.update(snapshot_id=snap.snapshot_id, cash=snap.cash + 1)
        result = engine.reconcile(snap.model_copy(update=updates), now=NOW)
        assert not result["reconciled"]
        assert ledger(engine) == before
        report = engine.journal.report(now=NOW)
        assert report["halted"] and report["issues"] and report["alerts"]


@pytest.mark.parametrize(
    "fault,accepted",
    [
        ("LOST_ACK", True),
        ("INVALID_ACK", True),
        ("OVERSIZED_ACK", True),
        ("CRASH_AFTER_ACCEPT", True),
        ("STALL_BEFORE_ACCEPT", False),
        ("STALL_AFTER_ACCEPT", True),
        ("IGNORE_TERM_AFTER_ACCEPT", True),
    ],
)
def test_native_uncertainty_never_replays_or_assumes_missing_means_flat(tmp_path, fault, accepted):
    with owned(tmp_path) as (engine, venue, data):
        venue.fault = fault
        prepared = engine.prepare(
            "uncertain", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        client = prepared["client_id"]
        # Shrink the original admission lease, rather than renew a deadline in the child.
        assert (
            asyncio.run(
                engine.dispatch(
                    client, data["quote"], data["underlying"], now=NOW + timedelta(seconds=3.5)
                )
            )
            == "UNKNOWN"
        )
        assert (
            asyncio.run(
                engine.dispatch(
                    client, data["quote"], data["underlying"], now=NOW + timedelta(seconds=3.5)
                )
            )
            == "UNKNOWN"
        )
        assert venue.submit_count == int(accepted)
        venue.fault = "NONE"
        result = engine.reconcile(
            venue.snapshot(NOW + timedelta(seconds=3.5)), now=NOW + timedelta(seconds=3.5)
        )
        assert result["reconciled"] == accepted
        assert engine.journal.report(now=NOW)["halted"]
        assert venue.submit_count == int(accepted)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_original_stop_latches_independently_and_survives_restart(tmp_path, right):
    with owned(tmp_path, right) as (engine, venue, data):
        buy = enter(engine, venue, data)
        engine.tighten_invalidation(
            D("599.5") if right == "CALL" else D("600.5"),
            data["quote"],
            data["underlying"],
            now=NOW,
        )
        stop = ledger(engine).position
        assert stop.original_underlying_invalidation == (D("599") if right == "CALL" else D("601"))
        crossed = (
            underlying_at(data, bid="599.4", ask="599.5")
            if right == "CALL"
            else underlying_at(data, bid="600.5", ask="600.6")
        )
        result = engine.assess(data["quote"], crossed, now=NOW)
        assert result["exit_reason"] == "UNDERLYING_INVALIDATION"
        with pytest.raises((ExecutionBlocked, ValidationError)):
            engine.tighten_invalidation(D("599"), data["quote"], data["underlying"], now=NOW)
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(
        path, limits, policy, DurableOptionVenue(venue.path), now=NOW
    ) as restarted:
        assert restarted.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        assert (
            restarted.assess(data["quote"], data["underlying"], now=NOW)["exit_reason"]
            == "UNDERLYING_INVALIDATION"
        )
        exited = asyncio.run(restarted.protective_tick(data["quote"], data["underlying"], now=NOW))
        assert exited["status"] == "OPEN", exited
        sell = intent_for(restarted, exited["client_id"])
        venue.fill(sell, sell.quantity, data["quote"], NOW, fill_id="protective")
        assert restarted.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        assert ledger(restarted).position is None
        assert buy.quantity == sell.quantity


def test_single_contract_allocation_cannot_split_and_reserves_close_fee(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        q = quote_at(data, ask_size=1, bid_size=1)
        prepared = engine.prepare("single", data["proposal"], q, data["underlying"], now=NOW)
        buy = intent_for(engine, prepared["client_id"])
        assert buy.quantity == 1 and buy.approved_full_premium_loss == D("104.30")
        assert asyncio.run(engine.dispatch(buy.client_id, q, data["underlying"], now=NOW)) == "OPEN"
        venue.fill(buy, 1, q, NOW, fill_id="one")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        crossed = underlying_at(data, bid="598", ask="598.01")
        exit_result = asyncio.run(engine.protective_tick(q, crossed, now=NOW))
        assert intent_for(engine, exit_result["client_id"]).quantity == 1


def test_partial_size_protective_close_distinct_progress_and_failed_exit_needs_review(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        enter(engine, venue, data)
        now = NOW + timedelta(seconds=1)
        q = quote_at(data, now, bid_size=1)
        crossed = underlying_at(data, now, bid="598", ask="598.01")
        first = asyncio.run(engine.protective_tick(q, crossed, now=now))
        sell = intent_for(engine, first["client_id"])
        assert sell.quantity == 1
        venue.fill(sell, 1, q, now, fill_id="exit-one")
        now += timedelta(seconds=1)
        second = asyncio.run(
            engine.protective_tick(
                quote_at(data, now, bid_size=1), underlying_at(data, now), now=now
            )
        )
        assert second["client_id"] != first["client_id"]
        assert ledger(engine).position.quantity == 3
        venue.record_terminal(second["client_id"], "REJECTED", now)
        now += timedelta(seconds=1)
        result = asyncio.run(
            engine.protective_tick(quote_at(data, now), underlying_at(data, now), now=now)
        )
        assert result["status"] == "EXIT_REVIEW_REQUIRED"
        assert venue.submit_count == 3
        assert ledger(engine).position.exit_reason == "UNDERLYING_INVALIDATION"


@pytest.mark.parametrize("reason", ["PREMIUM_CATASTROPHE", "TIME_EXIT", "EXPIRY_GUARD", "UNPRICED"])
def test_supervision_uses_executable_bid_fixed_time_and_no_clock_flatness(tmp_path, reason):
    with owned(tmp_path) as (engine, venue, data):
        buy = enter(engine, venue, data)
        now = (
            buy.exit_at
            if reason == "TIME_EXIT"
            else END - timedelta(seconds=30)
            if reason == "EXPIRY_GUARD"
            else NOW
        )
        assert engine.reconcile(venue.snapshot(now), now=now)["reconciled"]
        q = (
            quote_at(data, now, bid=".4", ask=".41")
            if reason == "PREMIUM_CATASTROPHE"
            else None
            if reason == "UNPRICED"
            else quote_at(data, now)
        )
        result = engine.assess(q, underlying_at(data, now), now=now)
        assert ledger(engine).position.quantity == 4
        if reason == "UNPRICED":
            assert result["issue"] == "OPTION_UNPRICED_OR_STALE"
            assert engine.journal.report(now=now)["halted"]
        else:
            assert result["exit_reason"] == reason


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_unexpected_physical_exercise_retains_option_authority_and_exposure_evidence(
    tmp_path, right
):
    with owned(tmp_path, right) as (engine, venue, data):
        buy = enter(engine, venue, data)
        before = ledger(engine)
        at = buy.instrument.contract.expires_at
        shares = buy.quantity * 100 * (1 if right == "CALL" else -1)
        venue.record_receipt(
            OptionReceipt(
                receipt_id="exercise",
                sequence=2,
                kind="PHYSICAL_EXERCISE",
                contract=buy.instrument.contract,
                quantity=buy.quantity,
                occurred_at=at,
                cash_change=-shares * D("600"),
            )
        )
        snap = venue.snapshot(at)
        assert snap.underlying_exposures[0].quantity == shares
        result = engine.reconcile(snap, now=at)
        assert result["issues"] == ["UNEXPECTED_UNDERLYING_EXPOSURE"]
        assert ledger(engine) == before
        assert engine.journal.report(now=at)["halted"]


def test_only_authoritative_worthless_receipt_removes_expired_contract(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        buy = enter(engine, venue, data)
        at = buy.instrument.contract.expires_at
        assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
        assert ledger(engine).position is not None
        receipt = OptionReceipt(
            receipt_id="expired",
            sequence=2,
            kind="EXPIRED_WORTHLESS",
            contract=buy.instrument.contract,
            quantity=buy.quantity,
            occurred_at=at,
            settlement_value="599",
            cash_change="0",
        )
        with pytest.raises(ValueError):
            venue.record_receipt(
                receipt.model_copy(update={"occurred_at": at - timedelta(seconds=1)})
            )
        venue.record_receipt(receipt)
        assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
        assert ledger(engine).position is None
        assert ledger(engine).realized_pnl == D("-404")
        assert ledger(engine).cash == D("592.40")
        missing = venue.snapshot(at).model_copy(
            update={"snapshot_id": "missing-receipt", "receipts": ()}
        )
        assert not engine.reconcile(missing, now=at)["reconciled"]
        assert ledger(engine).position is None


def test_half_day_holiday_and_late_entry_use_real_conservative_calendar(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        at = NOW.replace(month=11, day=27, hour=17)
        contract = data["proposal"].contract.model_copy(
            update={
                "expiration": at.date(),
                "last_trading_at": at.replace(hour=21),
                "expires_at": at.replace(hour=22),
                "settles_at": at + timedelta(days=1),
            }
        )
        window = engine._session(contract, at)
        assert window.closes_at == at.replace(hour=18)
        assert window.entry_cutoff_at == at.replace(hour=17, minute=30)
        assert engine._session(contract, at.replace(day=26)) is None
        assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
        engine.assess(None, None, now=at)
        proposal = data["proposal"].model_copy(update={"contract": contract})
        q = quote_at(
            data, at, instrument=data["quote"].instrument.model_copy(update={"contract": contract})
        )
        prepared = engine.prepare("half-day", proposal, q, underlying_at(data, at), now=at)
        assert prepared["status"] == "PREPARED", prepared
        buy = intent_for(engine, prepared["client_id"])
        assert buy.order_expires_at == at.replace(hour=18)
        assert buy.exit_at == at.replace(hour=17, minute=45)


def test_unknown_model_cost_persists_and_hold_cost_is_charged_without_broker_order(tmp_path):
    policy = CostPolicy(total_budget="1", daily_budget=".1", max_call_cost=".01")
    with owned(tmp_path, cost_policy=policy) as (engine, venue, data):
        engine.begin_model_attempt("model-hold", "a" * 64, now=NOW)
        with pytest.raises(ExecutionBlocked):
            engine.begin_model_attempt("again", "b" * 64, now=NOW)
        result = engine.prepare(
            "blocked", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        assert result["status"] == "REJECTED"
        path, limits, execution_policy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, execution_policy, venue, now=NOW) as engine:
        assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
        hold = OptionProposal(action="HOLD", thesis="No setup")
        usage = UsageEvidence(
            request_id="fixture-request", model="gpt-6-luna", input_tokens=1000, output_tokens=100
        )
        assert engine.record_model_usage("model-hold", usage, hold, now=NOW) == D(".00015")
        assert engine.record_model_usage("model-hold", usage, hold, now=NOW) == D(".00015")
        assert engine.prepare("model-hold", hold, now=NOW, origin="MODEL")["status"] == "HOLD"
        report = engine.journal.report(now=NOW)
        assert report["economics"]["known_cost"] == "0.00015"
        assert ledger(engine).cash == D("1000")
        assert venue.submit_count == 0
        with pytest.raises(ExecutionBlocked):
            engine.begin_model_attempt("model-hold", "a" * 64, now=NOW)


def test_lifetime_owner_and_paired_restore_fence_reject_stale_database(tmp_path):
    with owned(tmp_path) as (engine, venue, _data):
        with (
            pytest.raises(RuntimeError, match="already running"),
            OptionExecution.open(engine.journal.path, engine.limits, engine.policy, venue, now=NOW),
        ):
            pass
        backup = tmp_path / "stale.db"
        shutil.copyfile(engine.journal.path, backup)
        engine.prepare("hold", OptionProposal(action="HOLD", thesis="No setup"), now=NOW)
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    shutil.copyfile(backup, path)
    with (
        pytest.raises(ValueError, match="RESTORED_OR_CHANGED"),
        OptionExecution.open(path, limits, policy, venue, now=NOW),
    ):
        pass


def test_precision_independent_ledger_and_shared_stock_defaults(tmp_path):
    with localcontext() as ctx:
        ctx.prec = 3
        with owned(tmp_path) as (engine, venue, data):
            enter(engine, venue, data)
            assert ledger(engine).cash == D("592.40")
            assert ledger(engine).position.basis == D("404")
    assert ExecutionJournal.schema != OptionJournal.schema


@pytest.mark.parametrize("right,settlement_value", [("CALL", "602"), ("PUT", "598")])
@pytest.mark.parametrize("settlement_session", ["AM", "PM"])
def test_exact_authoritative_cash_settlement_is_not_a_trade_fill(
    tmp_path, right, settlement_value, settlement_session
):
    data, limits, policy = configuration(right)
    contract = data["proposal"].contract.model_copy(
        update={
            "underlying": "SPX",
            "underlying_kind": "INDEX",
            "underlying_market": "US_INDEX",
            "root": "SPXW",
            "deliverable_kind": "CASH",
            "deliverable_units": 0,
            "settlement": "CASH",
            "exercise_style": "EUROPEAN",
            "settlement_session": settlement_session,
        }
    )
    limits = limits.model_copy(update={"allowed_underlyings": ("SPX",)})
    data["proposal"] = data["proposal"].model_copy(update={"contract": contract})
    data["quote"] = data["quote"].model_copy(
        update={"instrument": data["quote"].instrument.model_copy(update={"contract": contract})}
    )
    data["underlying"] = data["underlying"].model_copy(update={"symbol": "SPX"})
    venue = DurableOptionVenue(tmp_path / "venue.db", limits=limits, capital=policy.capital)
    with OptionExecution.open(
        tmp_path / "options.db", limits, policy, venue, now=NOW, create=True
    ) as engine:
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        engine.assess(None, None, now=NOW)
        buy = enter(engine, venue, data)
        receipt = OptionReceipt(
            receipt_id="cash-settlement",
            sequence=2,
            kind="CASH_SETTLEMENT",
            contract=contract,
            quantity=buy.quantity,
            occurred_at=contract.settles_at,
            settlement_value=settlement_value,
            cash_change="800",
        )
        for changes in (
            {"cash_change": "799"},
            {"occurred_at": contract.settles_at - timedelta(seconds=1)},
            {"quantity": 3},
        ):
            with pytest.raises(ValueError):
                venue.record_receipt(receipt.model_copy(update=changes))
        venue.record_receipt(receipt)
        assert engine.reconcile(venue.snapshot(contract.settles_at), now=contract.settles_at)[
            "reconciled"
        ]
        assert ledger(engine).position is None
        assert ledger(engine).cash == D("1392.40")
        assert ledger(engine).settled_cash == D("1392.40")
        assert ledger(engine).realized_pnl == D("396")
        assert venue.submit_count == 1


@pytest.mark.parametrize(
    "at", [NOW + timedelta(seconds=10), NOW.replace(hour=21), NOW.replace(day=10)]
)
def test_model_admission_needs_fresh_account_and_open_entry_window(tmp_path, at):
    policy = CostPolicy(total_budget="1", daily_budget=".1", max_call_cost=".01")
    with owned(tmp_path, cost_policy=policy) as (engine, venue, _data):
        if at.hour != 15:
            assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
            engine.assess(None, None, now=at)
        with pytest.raises(ExecutionBlocked, match="MODEL_ADMISSION_BLOCKED"):
            engine.begin_model_attempt("call", "a" * 64, now=at)
        assert engine.journal.report(now=at)["economics"]["unknown_calls"] == 0


@pytest.mark.parametrize("field", ["proposal", "instrument", "approval"])
def test_frozen_decision_lineage_or_expired_admission_never_submits(tmp_path, field):
    with owned(tmp_path) as (engine, venue, data):
        prepared = engine.prepare(
            "decision", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        if field == "proposal":
            with pytest.raises(ExecutionBlocked, match="IDENTITY_CONFLICT"):
                engine.prepare(
                    "decision",
                    data["proposal"].model_copy(update={"thesis": "Changed decision"}),
                    data["quote"],
                    data["underlying"],
                    now=NOW,
                )
            assert (
                engine.prepare(
                    "decision", data["proposal"], data["quote"], data["underlying"], now=NOW
                )
                == prepared
            )
        else:
            q = (
                data["quote"].model_copy(
                    update={
                        "instrument": data["quote"].instrument.model_copy(
                            update={"instrument_id": "wrong"}
                        )
                    }
                )
                if field == "instrument"
                else data["quote"]
            )
            at = NOW + timedelta(seconds=5) if field == "approval" else NOW
            assert (
                asyncio.run(engine.dispatch(prepared["client_id"], q, data["underlying"], now=at))
                == "REJECTED"
            )
            assert (
                asyncio.run(
                    engine.dispatch(
                        prepared["client_id"], data["quote"], data["underlying"], now=at
                    )
                )
                == "REJECTED"
            )
        assert venue.submit_count == 0


def test_native_child_is_isolated_cancellation_reaps_it_and_retains_reservation(
    tmp_path, monkeypatch
):
    with owned(tmp_path) as (engine, venue, data):
        children = []
        spawn = asyncio.create_subprocess_exec

        async def capture(*args, **kwargs):
            assert args[:4] == (sys.executable, "-I", "-m", "app.options.worker")
            assert set(kwargs["env"]) <= {"PATH", "LANG", "LC_ALL"}
            child = await spawn(*args, **kwargs)
            children.append(child)
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
        monkeypatch.setenv("BROKER_SECRET", "fixture-not-a-credential")
        monkeypatch.setenv("PYTHONPATH", str(tmp_path / "poison"))
        venue.fault = "IGNORE_TERM_AFTER_ACCEPT"
        prepared = engine.prepare(
            "cancelled", data["proposal"], data["quote"], data["underlying"], now=NOW
        )

        async def cancel():
            task = asyncio.create_task(
                engine.dispatch(prepared["client_id"], data["quote"], data["underlying"], now=NOW)
            )
            async with asyncio.timeout(4):
                while venue.submit_count != 1:
                    await asyncio.sleep(0.01)
            assert not engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(cancel())
        assert children and all(c.returncode is not None for c in children)
        report = engine.journal.report(now=NOW)
        assert report["orders"][0]["status"] == "UNKNOWN"
        assert report["orders"][0]["active_lock"] == 1
        assert report["halted"] and venue.submit_count == 1


def test_admission_deadline_covers_durable_write_and_spawn_delay(tmp_path, monkeypatch):
    with owned(tmp_path) as (engine, venue, data):
        prepared = engine.prepare(
            "late-spawn", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        spawn = asyncio.create_subprocess_exec
        children = []

        async def delayed(*args, **kwargs):
            await asyncio.sleep(0.2)
            child = await spawn(*args, **kwargs)
            children.append(child)
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
        assert (
            asyncio.run(
                engine.dispatch(
                    prepared["client_id"],
                    data["quote"],
                    data["underlying"],
                    now=NOW + timedelta(seconds=4.9),
                )
            )
            == "UNKNOWN"
        )
        assert children and all(c.returncode is not None for c in children)
        assert venue.submit_count == 0


def test_sigkill_owner_releases_lock_retains_attempt_and_child_exits(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        prepared = engine.prepare(
            "kill-owner", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(original), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        pytest.skip("Linux child subreaper unavailable")
    pid_path = tmp_path / "child.pid"
    script = """
import asyncio, sys
from pathlib import Path
from datetime import datetime
from app.options.engine import OptionExecution
from app.options.venue import DurableOptionVenue
from app.options.models import OptionLimits, OptionQuote, UnderlyingQuote
from app.options.lifecycle import OptionExecutionPolicy
spawn=asyncio.create_subprocess_exec
async def capture(*args, **kwargs):
    child=await spawn(*args, **kwargs)
    Path(sys.argv[8]).write_text(str(child.pid))
    return child
asyncio.create_subprocess_exec=capture
at=datetime.fromisoformat(sys.argv[9])
venue=DurableOptionVenue(sys.argv[2], fault='IGNORE_TERM_AFTER_ACCEPT')
with OptionExecution.open(sys.argv[1], OptionLimits.model_validate_json(sys.argv[3]), OptionExecutionPolicy.model_validate_json(sys.argv[4]), venue, now=at) as engine:
    asyncio.run(engine.dispatch(sys.argv[5], OptionQuote.model_validate_json(sys.argv[6]), UnderlyingQuote.model_validate_json(sys.argv[7]), now=at))
"""
    child_pid = None
    parent = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(path),
            str(venue.path),
            limits.model_dump_json(),
            policy.model_dump_json(),
            prepared["client_id"],
            data["quote"].model_dump_json(),
            data["underlying"].model_dump_json(),
            str(pid_path),
            NOW.isoformat(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 4
        while venue.submit_count != 1 and time.monotonic() < deadline:
            assert parent.poll() is None
            time.sleep(0.01)
        assert venue.submit_count == 1
        child_pid = int(pid_path.read_text())
        parent.kill()
        assert parent.wait(timeout=3) == -signal.SIGKILL
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            reaped, status = os.waitpid(child_pid, os.WNOHANG)
            if reaped:
                child_pid = None
                assert os.waitstatus_to_exitcode(status) == 96
                break
            time.sleep(0.01)
        assert child_pid is None
        with OptionExecution.open(path, limits, policy, venue, now=NOW) as engine:
            report = engine.journal.report(now=NOW)
            assert report["orders"][0]["status"] == "UNKNOWN"
            assert report["halt_reason"] == "INTERRUPTED_OPTION_ATTEMPT"
            assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
            assert (
                asyncio.run(
                    engine.dispatch(
                        prepared["client_id"], data["quote"], data["underlying"], now=NOW
                    )
                )
                == "OPEN"
            )
            assert venue.submit_count == 1
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        if parent.stderr is not None:
            parent.stderr.close()
        if child_pid is not None:
            os.kill(child_pid, signal.SIGKILL)
            os.waitpid(child_pid, 0)
        libc.prctl(36, original.value, 0, 0, 0)


def test_no_arbitrary_venue_or_missing_authority_adoption(tmp_path):
    with owned(tmp_path) as (engine, venue, _data):
        with pytest.raises(ValueError, match="built-in"):
            asyncio.run(run_option_process(object(), now=NOW, timeout_seconds=1))
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    # Resolve the shared authority convention instead of inventing an options copy.
    from app.execution.restore import authority_path

    authority = authority_path(path)
    authority.unlink()
    with (
        pytest.raises(FileNotFoundError),
        OptionExecution.open(path, limits, policy, venue, now=NOW),
    ):
        pass


def test_observed_liquidity_cannot_be_reused_by_changing_decimal_scale(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        q = quote_at(data, ask_size=1)
        prepared = engine.prepare("one", data["proposal"], q, data["underlying"], now=NOW)
        buy = intent_for(engine, prepared["client_id"])
        assert asyncio.run(engine.dispatch(buy.client_id, q, data["underlying"], now=NOW)) == "OPEN"
        venue.fill(buy, 1, q, NOW, fill_id="first")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        close = engine.prepare(
            "close-one",
            OptionProposal(action="CLOSE", contract=buy.instrument.contract, thesis="Close"),
            q,
            now=NOW,
        )
        sell = intent_for(engine, close["client_id"])
        assert asyncio.run(engine.dispatch(sell.client_id, q, now=NOW)) == "OPEN"
        venue.fill(sell, 1, q, NOW, fill_id="exit")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        engine.assess(None, None, now=NOW)
        q_scaled = q.model_copy(update={"ask": D("1.00"), "bid": D(".980")})
        next_prepared = engine.prepare(
            "next", data["proposal"], q_scaled, data["underlying"], now=NOW
        )
        next_buy = intent_for(engine, next_prepared["client_id"])
        assert (
            asyncio.run(engine.dispatch(next_buy.client_id, q_scaled, data["underlying"], now=NOW))
            == "OPEN"
        )
        with pytest.raises(ValueError, match="unused observed size"):
            venue.fill(next_buy, 1, q_scaled, NOW, fill_id="reused")


def test_uncertainty_clears_only_with_fresh_review_and_never_replays(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        venue.fault = "LOST_ACK"
        prepared = engine.prepare(
            "lost", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        assert (
            asyncio.run(
                engine.dispatch(prepared["client_id"], data["quote"], data["underlying"], now=NOW)
            )
            == "UNKNOWN"
        )
        venue.record_terminal(prepared["client_id"], "REJECTED", NOW)
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        assert engine.journal.report(now=NOW)["halted"]
        engine.assess(None, None, now=NOW)
        revision = engine.journal.report(now=NOW)["revision"]
        with pytest.raises(ExecutionBlocked, match="REVISION_CHANGED"):
            engine.resume("Reviewed rejected order", expected_revision=revision - 1, now=NOW)
        engine.resume("Reviewed complete rejection receipt", expected_revision=revision, now=NOW)
        assert not engine.journal.report(now=NOW)["halted"]
        assert (
            asyncio.run(
                engine.dispatch(prepared["client_id"], data["quote"], data["underlying"], now=NOW)
            )
            == "REJECTED"
        )
        assert venue.submit_count == 1


def test_four_one_contract_catastrophe_exits_conserve_cash_and_reserved_fees(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        enter(engine, venue, data)
        for index in range(4):
            at = NOW + timedelta(seconds=index + 1)
            q = quote_at(data, at, bid=".02", ask=".03", bid_size=1)
            exit_result = asyncio.run(engine.protective_tick(q, underlying_at(data, at), now=at))
            assert exit_result["status"] == "OPEN", exit_result
            sell = intent_for(engine, exit_result["client_id"])
            assert sell.quantity == 1
            # .02 bid minus adverse slippage rounds down to .01, a $1 credit.
            venue.fill(sell, 1, q, at, fill_id=f"exit-{index}")
            assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
        state = ledger(engine)
        assert state.position is None
        assert state.cash == state.settled_cash == D("589.80")
        assert state.realized_pnl == D("-400")
        assert state.fees_paid == D("10.20")
        assert venue.submit_count == 5


def test_cost_bound_exhaustion_halts_entry_without_erasing_usage(tmp_path):
    policy = CostPolicy(total_budget=".01", daily_budget=".01", max_call_cost=".01")
    with owned(tmp_path, cost_policy=policy) as (engine, venue, data):
        engine.begin_model_attempt("expensive", "a" * 64, now=NOW)
        hold = OptionProposal(action="HOLD", thesis="No setup")
        usage = UsageEvidence(
            request_id="over-budget", model="gpt-6-luna", input_tokens=1000000, output_tokens=0
        )
        assert engine.record_model_usage("expensive", usage, hold, now=NOW) == D(".1")
        report = engine.journal.report(now=NOW)
        assert report["halt_reason"] == "MODEL_COST_BOUND_EXCEEDED"
        assert D(report["economics"]["known_cost"]) == D(".1")
        assert (
            engine.prepare("entry", data["proposal"], data["quote"], data["underlying"], now=NOW)[
                "status"
            ]
            == "REJECTED"
        )
        assert engine.prepare("expensive", hold, now=NOW, origin="MODEL")["status"] == "HOLD"
        assert venue.submit_count == 0
