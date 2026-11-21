"""Settlement outcomes come from the complete native event stream, never contract matching."""

import asyncio
import json
from contextlib import contextmanager
from decimal import Decimal

import pytest
from test_option_admission import NOW
from test_option_execution import configuration, enter, intent_for, ledger, owned, quote_at
from test_option_position_outcome import read_owned

from app.options.engine import OptionExecution
from app.options.lifecycle import OptionReceipt
from app.options.models import OptionProposal
from app.options.venue import DurableOptionVenue


@contextmanager
def cash_owner(path, right="CALL"):
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
            "settlement_session": "PM",
        }
    )
    limits = limits.model_copy(update={"allowed_underlyings": ("SPX",)})
    data["proposal"] = data["proposal"].model_copy(update={"contract": contract})
    data["quote"] = data["quote"].model_copy(
        update={"instrument": data["quote"].instrument.model_copy(update={"contract": contract})}
    )
    data["underlying"] = data["underlying"].model_copy(update={"symbol": "SPX"})
    venue = DurableOptionVenue(path / "venue.db", limits=limits, capital=policy.capital)
    with OptionExecution.open(
        path / "options.db", limits, policy, venue, now=NOW, create=True
    ) as engine:
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        engine.assess(None, None, now=NOW)
        yield engine, venue, data


def settle(engine, venue, entry, *, value="602", quantity=None, sequence=2):
    quantity = entry.quantity if quantity is None else quantity
    contract = entry.instrument.contract
    intrinsic = max(
        Decimal(0), (Decimal(value) - contract.strike) * (1 if contract.right == "CALL" else -1)
    )
    receipt = OptionReceipt(
        receipt_id="settlement",
        sequence=sequence,
        kind="CASH_SETTLEMENT",
        contract=contract,
        quantity=quantity,
        occurred_at=contract.settles_at,
        settlement_value=value,
        cash_change=intrinsic * 100 * quantity,
    )
    venue.record_receipt(receipt)
    assert engine.reconcile(venue.snapshot(receipt.occurred_at), now=receipt.occurred_at)[
        "reconciled"
    ]
    return receipt


@pytest.mark.parametrize(
    "right,value", [("CALL", "602"), ("PUT", "598"), ("CALL", "600"), ("PUT", "600")]
)
def test_cash_settlement_exact_entry_fees_and_cash_conservation(tmp_path, right, value):
    with cash_owner(tmp_path, right) as (engine, venue, data):
        entry = enter(engine, venue, data)
        receipt = settle(engine, venue, entry, value=value)
        before = engine.journal.path.read_bytes()
        result = read_owned(engine, entry)
        assert result["status"] == "COMPLETE", result
        assert result["settlement_quantity"] == entry.quantity
        assert result["exit_quantity"] == 0 and result["exit_premium"] == "0"
        assert Decimal(result["settlement_cash"]) == receipt.cash_change
        assert result["settlements"][0]["entry_client_id"] == entry.client_id
        assert result["fill_ids"] == ["entry-fill"]
        assert result["closed_at"] == receipt.occurred_at.isoformat()
        assert (
            Decimal(result["net_after_known_execution_and_model_costs"])
            == ledger(engine).cash - 1000
        )
        assert Decimal(result["execution_fees"]) == Decimal("3.60")
        assert result["outcome"] == ("LOSS" if value == "600" else "WIN")
        assert engine.journal.path.read_bytes() == before
        assert not result["execution_authority"]


@pytest.mark.parametrize("right,value", [("CALL", "599"), ("PUT", "601")])
def test_authoritative_worthless_expiry_is_full_premium_loss_with_fees(tmp_path, right, value):
    with owned(tmp_path, right) as (engine, venue, data):
        entry = enter(engine, venue, data)
        receipt = OptionReceipt(
            receipt_id="worthless",
            sequence=2,
            kind="EXPIRED_WORTHLESS",
            contract=entry.instrument.contract,
            quantity=entry.quantity,
            occurred_at=entry.instrument.contract.expires_at,
            settlement_value=value,
            cash_change="0",
        )
        venue.record_receipt(receipt)
        assert engine.reconcile(venue.snapshot(receipt.occurred_at), now=receipt.occurred_at)[
            "reconciled"
        ]
        result = read_owned(engine, entry)
        assert result["status"] == "COMPLETE" and result["outcome"] == "LOSS"
        assert Decimal(result["net_after_known_execution_and_model_costs"]) == Decimal("-407.60")
        assert result["settlements"][0]["kind"] == "EXPIRED_WORTHLESS"


def test_partial_sale_then_cash_settlement_counts_remaining_contracts_once(tmp_path):
    with cash_owner(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        quote = quote_at(data, bid_size=1)
        close = engine.prepare(
            "partial-close",
            OptionProposal(
                action="CLOSE", contract=entry.instrument.contract, thesis="Sell available size"
            ),
            quote,
            now=NOW,
        )
        sell = intent_for(engine, close["client_id"])
        assert sell.quantity == 1
        assert asyncio.run(engine.dispatch(sell.client_id, quote, now=NOW)) == "OPEN"
        venue.fill(sell, 1, quote, NOW, fill_id="partial-exit")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        settle(engine, venue, entry, quantity=entry.quantity - 1, sequence=3)
        result = read_owned(engine, entry)
        assert result["status"] == "COMPLETE", result
        assert (
            result["entry_quantity"] == result["exit_quantity"] + result["settlement_quantity"] == 4
        )
        assert len(result["fill_ids"]) == 2 and len(result["settlements"]) == 1
        assert (
            Decimal(result["net_after_known_execution_and_model_costs"])
            == ledger(engine).cash - 1000
        )
        assert Decimal(result["execution_fees"]) == Decimal("5.25")


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "identity",
        "sequence",
        "cash",
        "ledger",
        "snapshot",
        "account",
        "incomplete",
        "fills",
    ],
)
def test_damaged_settlement_history_cannot_produce_net(tmp_path, damage):
    with cash_owner(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        settle(engine, venue, entry)
        with engine.journal.write() as db:
            if damage == "missing":
                db.execute("DELETE FROM execution_option_receipts")
            elif damage == "identity":
                db.execute("UPDATE execution_option_receipts SET receipt_id='different'")
            elif damage == "ledger":
                db.execute(
                    "UPDATE execution_control SET ledger_json=json_set(ledger_json,'$.realized_pnl','999')"
                )
            elif damage == "account":
                db.execute(
                    "UPDATE execution_control SET snapshot_json=json_set(snapshot_json,'$.account_id','foreign-account')"
                )
            elif damage == "incomplete":
                db.execute(
                    "UPDATE execution_control SET snapshot_json=json_set(snapshot_json,'$.complete',json('false'))"
                )
            elif damage == "fills":
                db.execute(
                    "UPDATE execution_control SET snapshot_json=json_set(snapshot_json,'$.orders',json('[]'))"
                )
            elif damage == "snapshot":
                db.execute(
                    "UPDATE execution_control SET snapshot_json=json_set(snapshot_json,'$.cash','1500')"
                )
            else:
                receipt = json.loads(
                    db.execute("SELECT payload FROM execution_option_receipts").fetchone()[0]
                )
                receipt["sequence" if damage == "sequence" else "cash_change"] = (
                    3 if damage == "sequence" else "799"
                )
                db.execute("UPDATE execution_option_receipts SET payload=?", (json.dumps(receipt),))
                snap = json.loads(
                    db.execute("SELECT snapshot_json FROM execution_control").fetchone()[0]
                )
                snap["receipts"] = [receipt]
                db.execute("UPDATE execution_control SET snapshot_json=?", (json.dumps(snap),))
        with pytest.raises(ValueError):
            read_owned(engine, entry)


def test_later_same_contract_settlement_belongs_only_to_second_entry(tmp_path):
    with cash_owner(tmp_path) as (engine, venue, data):
        first = enter(engine, venue, data)
        result = engine.prepare(
            "close-first",
            OptionProposal(
                action="CLOSE", contract=first.instrument.contract, thesis="Close first entry"
            ),
            data["quote"],
            now=NOW,
        )
        sell = intent_for(engine, result["client_id"])
        assert asyncio.run(engine.dispatch(sell.client_id, data["quote"], now=NOW)) == "OPEN"
        venue.fill(sell, sell.quantity, data["quote"], NOW, fill_id="first-exit")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        engine.assess(None, None, now=NOW)
        result = engine.prepare(
            "second-entry", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        assert result["status"] == "PREPARED", result
        second = intent_for(engine, result["client_id"])
        assert (
            asyncio.run(
                engine.dispatch(second.client_id, data["quote"], data["underlying"], now=NOW)
            )
            == "OPEN"
        )
        venue.fill(second, second.quantity, data["quote"], NOW, fill_id="second-entry-fill")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        settle(engine, venue, second, sequence=4)
        a, b = read_owned(engine, first), read_owned(engine, second)
        assert a["status"] == b["status"] == "COMPLETE"
        assert a["settlements"] == []
        assert b["settlements"][0]["entry_client_id"] == second.client_id
        assert (
            Decimal(a["net_after_known_execution_and_model_costs"])
            + Decimal(b["net_after_known_execution_and_model_costs"])
            == ledger(engine).cash - 1000
        )


@pytest.mark.parametrize("unknown_entry_cost", [False, True])
def test_expiry_retains_paid_entry_and_nonorder_management_costs(
    tmp_path, monkeypatch, unknown_entry_cost
):
    from test_option_position_coordination import (
        enter_position,
        management_frame,
        model,
        owned_manager,
    )

    with owned_manager(tmp_path) as (c, venue, times):
        entry = enter_position(c, venue, times, monkeypatch)
        model(monkeypatch, c, "MAINTAIN")
        assert asyncio.run(c.cycle(management_frame()))["status"] == "MAINTAIN"
        receipt = OptionReceipt(
            receipt_id="paid-expiry",
            sequence=2,
            kind="EXPIRED_WORTHLESS",
            contract=entry.instrument.contract,
            quantity=entry.quantity,
            occurred_at=entry.instrument.contract.expires_at,
            settlement_value="599",
            cash_change="0",
        )
        venue.record_receipt(receipt)
        assert c.engine.reconcile(venue.snapshot(receipt.occurred_at), now=receipt.occurred_at)[
            "reconciled"
        ]
        if unknown_entry_cost:
            with c.engine.journal.write() as db:
                db.execute(
                    "UPDATE execution_model_calls SET cost=NULL WHERE source_key=?",
                    (entry.source_key,),
                )
        outcome = read_owned(c.engine, entry)
        if unknown_entry_cost:
            assert outcome["status"] == "INCOMPLETE"
            assert outcome["net_after_known_execution_and_model_costs"] is None
            assert "POSITION_MODEL_COST_UNKNOWN" in outcome["reasons"]
            assert len(outcome["model_calls"]) == 2
            return
        assert outcome["status"] == "COMPLETE" and outcome["outcome"] == "LOSS"
        assert {r["role"] for r in outcome["model_calls"]} == {"ENTRY", "MANAGEMENT"}
        assert Decimal(outcome["known_model_cost"]) == Decimal(".00030")
        assert Decimal(outcome["net_after_known_execution_and_model_costs"]) == ledger(
            c.engine
        ).cash - 1000 - Decimal(".00030")
