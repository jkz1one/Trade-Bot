"""Exact stored position cash flows, independent accounts and conservative missing links."""
# ruff: noqa: F811

import asyncio
import json
import shutil
import sqlite3
from decimal import Decimal

import pytest
from test_option_admission import NOW
from test_option_execution import enter, intent_for, owned, underlying_at
from test_option_managed_replay import DKEY, managed_complete  # noqa: F401

from app.options.models import OptionProposal
from app.options.observer import OptionObserver
from app.options.position_outcome import native_position_outcome


def read_owned(engine, entry):
    with engine.journal.read() as db:
        return native_position_outcome(db, entry.client_id, engine.limits.population_id)


@pytest.mark.parametrize("arm", list("ABCD"))
def test_native_replay_costs_and_independent_identity(managed_complete, arm):
    root, _, _, replay = managed_complete
    evidence = next(r for r in replay["bundle"]["evidence"] if r["arm"] == arm)
    entry = evidence["orders"][0]["intent"]["client_id"]
    path = root / f"run/{arm}/journal.db"
    before = path.read_bytes()
    result = OptionObserver(path, f"evaluation-{arm}").position_outcome(entry)
    assert result["status"] == "COMPLETE", result
    assert result["population_id"] == f"evaluation-{arm}"
    costs = replay["report"]["sessions"][0]["arms"][arm]
    assert Decimal(result["known_model_cost"]) == Decimal(costs["known_model_cost"])
    assert Decimal(result["net_after_known_execution_and_model_costs"]) == (
        Decimal(evidence["closing"]["cash"]) - 1000 - Decimal(costs["known_model_cost"])
    )
    if arm == "D":
        assert {c["role"] for c in result["model_calls"]} == {"ENTRY", "MANAGEMENT"}
        assert len(result["model_calls"]) == 2
    assert not result["execution_authority"] and not result["live_enabled"]
    assert not result["data_host_costs_included"]
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="population"):
        OptionObserver(path, "another-account").position_outcome(entry)
    with pytest.raises(ValueError, match="entry"):
        OptionObserver(path, f"evaluation-{arm}").position_outcome("absent-entry")


@pytest.mark.parametrize("damage", ["fill", "cost", "approval", "consumption", "orphan"])
def test_corrupt_native_evidence_fails_closed(managed_complete, tmp_path, damage):
    root, _, _, replay = managed_complete
    path = tmp_path / "copy.db"
    shutil.copy2(root / "run/D/journal.db", path)
    entry = next(r for r in replay["bundle"]["evidence"] if r["arm"] == "D")["orders"][0]["intent"][
        "client_id"
    ]
    with sqlite3.connect(path) as db:
        if damage == "fill":
            db.execute("DELETE FROM execution_fills WHERE client_id=?", (entry,))
        elif damage == "orphan":
            db.execute("UPDATE execution_fills SET client_id='missing'")
        elif damage == "cost":
            db.execute("UPDATE execution_model_calls SET cost='0' WHERE source_key=?", (DKEY,))
        elif damage == "approval":
            db.execute(
                "UPDATE execution_orders SET approval_json=json_remove(approval_json,'$.position_result') WHERE source_key=?",
                (DKEY,),
            )
        else:
            db.execute("DELETE FROM execution_option_decisions WHERE source_key=?", (DKEY,))
    with pytest.raises(ValueError):
        OptionObserver(path, "evaluation-D").position_outcome(entry)


@pytest.mark.parametrize("quantity", [None, 1])
def test_open_and_partial_entries_have_no_realized_outcome(tmp_path, quantity):
    with owned(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data, quantity)
        result = read_owned(engine, entry)
        assert result["status"] == "INCOMPLETE"
        assert result["outcome"] is None
        assert result["net_after_known_execution_and_model_costs"] is None
        assert result["entry_quantity"] == (quantity or entry.quantity)
        assert result["gross_realized"] is None


@pytest.mark.parametrize("protective,legacy", [(True, False), (False, False), (False, True)])
def test_linked_protective_exit_and_unlinked_manual_close(tmp_path, protective, legacy):
    with owned(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        if protective:
            result = asyncio.run(
                engine.protective_tick(
                    data["quote"], underlying_at(data, bid="598", ask="598.01"), now=NOW
                )
            )
        else:
            result = engine.prepare(
                "close",
                OptionProposal(action="CLOSE", contract=entry.instrument.contract, thesis="Close"),
                data["quote"],
                now=NOW,
            )
            asyncio.run(engine.dispatch(result["client_id"], data["quote"], now=NOW))
        sell = intent_for(engine, result["client_id"])
        venue.fill(sell, sell.quantity, data["quote"], NOW, fill_id="closed-fill")
        engine.reconcile(venue.snapshot(NOW), now=NOW)
        if legacy:
            with engine.journal.write() as db:
                row = db.execute(
                    "SELECT intent_json,approval_json FROM execution_orders WHERE client_id=?",
                    (sell.client_id,),
                ).fetchone()
                intent, approval = map(json.loads, row)
                intent.pop("closing_entry_client_id")
                approval.pop("closing_entry_client_id")
                db.execute(
                    "UPDATE execution_orders SET intent_json=?,approval_json=? WHERE client_id=?",
                    (json.dumps(intent), json.dumps(approval), sell.client_id),
                )
        result = read_owned(engine, entry)
        if not legacy:
            assert result["status"] == "COMPLETE", result
            assert result["outcome"] == "LOSS"
            assert Decimal(result["gross_realized"]) == -16
            assert Decimal(result["execution_fees"]) == Decimal("7.20")
            assert Decimal(result["net_after_known_execution_and_model_costs"]) == Decimal("-23.20")
        else:
            assert result["status"] == "INCOMPLETE"
            assert "UNLINKED_SAME_INSTRUMENT_EXIT" in result["reasons"]
            assert result["net_after_known_execution_and_model_costs"] is None


@pytest.mark.parametrize("unknown", [False, True])
def test_unallocated_account_calls_never_disappear(managed_complete, tmp_path, unknown):
    root, _, _, replay = managed_complete
    path = tmp_path / "unallocated.db"
    shutil.copy2(root / "run/D/journal.db", path)
    entry = next(r for r in replay["bundle"]["evidence"] if r["arm"] == "D")["orders"][0]["intent"][
        "client_id"
    ]
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO execution_model_calls SELECT 'unallocated',packet_hash,started_at,usage_json,NULL,decision_hash,cost FROM execution_model_calls LIMIT 1"
        )
        if unknown:
            db.execute("UPDATE execution_model_calls SET cost=NULL WHERE source_key='unallocated'")
    result = OptionObserver(path, "evaluation-D").position_outcome(entry)
    assert result["status"] == "INCOMPLETE"
    assert result["net_after_known_execution_and_model_costs"] is None
    assert "ACCOUNT_MODEL_COST_LINK_UNPROVEN" in result["reasons"]
    assert result["unallocated_account_calls"][0]["cost_status"] == (
        "UNKNOWN" if unknown else "CONFIGURED_ESTIMATE"
    )


def test_unknown_entry_cost_is_not_zero(managed_complete, tmp_path):
    root, _, _, replay = managed_complete
    path = tmp_path / "unknown.db"
    shutil.copy2(root / "run/C/journal.db", path)
    entry = next(r for r in replay["bundle"]["evidence"] if r["arm"] == "C")["orders"][0]["intent"][
        "client_id"
    ]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE execution_model_calls SET cost=NULL")
    result = OptionObserver(path, "evaluation-C").position_outcome(entry)
    assert "POSITION_MODEL_COST_UNKNOWN" in result["reasons"]
    assert result["net_after_known_execution_and_model_costs"] is None


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN"])
def test_management_without_exit_retains_charge_and_requires_receipt(tmp_path, monkeypatch, action):
    from test_option_position_coordination import (
        enter_position,
        management_frame,
        model,
        owned_manager,
    )

    with owned_manager(tmp_path) as (c, venue, times):
        entry = enter_position(c, venue, times, monkeypatch)
        model(monkeypatch, c, action)
        result = asyncio.run(c.cycle(management_frame()))
        outcome = read_owned(c.engine, entry)
        assert len(outcome["orders"]) == 1
        assert {r["role"] for r in outcome["model_calls"]} == {"ENTRY", "MANAGEMENT"}
        assert Decimal(outcome["known_model_cost"]) == Decimal(".00030")
        # Simulated damaged evidence, using the owner's transaction/fence in this fixture.
        with c.engine.journal.write() as db:
            db.execute(
                "DELETE FROM execution_model_calls WHERE source_key=?", (result["cycle_key"],)
            )
        with pytest.raises(ValueError, match="attempt"):
            read_owned(c.engine, entry)


def test_unfilled_entry_has_no_realized_outcome(tmp_path):
    with owned(tmp_path) as (engine, _, data):
        result = engine.prepare(
            "unfilled", data["proposal"], data["quote"], data["underlying"], now=NOW
        )
        entry = intent_for(engine, result["client_id"])
        outcome = read_owned(engine, entry)
        assert outcome["entry_quantity"] == outcome["exit_quantity"] == 0
        assert outcome["outcome"] is None
        assert outcome["net_after_known_execution_and_model_costs"] is None


def test_unreconciled_contract_receipt_cannot_supply_entry_link(tmp_path):
    from app.options.lifecycle import OptionReceipt

    with owned(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        receipt = OptionReceipt(
            receipt_id="settlement",
            sequence=2,
            kind="EXPIRED_WORTHLESS",
            occurred_at=NOW,
            contract=entry.instrument.contract,
            quantity=entry.quantity,
            cash_change="0",
        )
        with engine.journal.write() as db:
            db.execute(
                "INSERT INTO execution_option_receipts VALUES(?,?)",
                (receipt.receipt_id, receipt.model_dump_json()),
            )
        with pytest.raises(ValueError, match="snapshot coverage"):
            read_owned(engine, entry)
