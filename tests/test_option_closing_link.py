"""Owner-derived close identity survives preparation, dispatch and stored projection."""

import asyncio
import json

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import enter, intent_for, owned

from app.options.attribution import order_attribution
from app.options.lifecycle import OptionIntent
from app.options.models import OptionProposal


def prepare_close(engine, data, entry):
    result = engine.prepare(
        "close",
        OptionProposal(
            action="CLOSE", contract=entry.instrument.contract, thesis="Close held position"
        ),
        data["quote"],
        now=NOW,
    )
    assert result["status"] == "PREPARED"
    return intent_for(engine, result["client_id"])


def test_owner_records_exact_close_and_historical_retry(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        close = prepare_close(engine, data, entry)
        assert close.closing_entry_client_id == entry.client_id
        assert prepare_close(engine, data, entry) == close
        with engine.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (close.client_id,)
            ).fetchone()
            assert json.loads(row["approval_json"])["closing_entry_client_id"] == entry.client_id
            assert order_attribution(db, row)["entry_client_id"] == entry.client_id
        assert "closing_entry_client_id" not in entry.model_dump(mode="json")
        assert asyncio.run(engine.dispatch(close.client_id, data["quote"], now=NOW)) == "OPEN"


@pytest.mark.parametrize(
    "damage", ["approval", "intent", "held", "missing_approval", "missing_intent"]
)
def test_dispatch_rejects_changed_close_identity_before_attempt(tmp_path, damage):
    with owned(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        close = prepare_close(engine, data, entry)
        with engine.journal.write() as db:
            if damage == "held":
                db.execute(
                    "UPDATE execution_control SET ledger_json=json_set(ledger_json,'$.position.entry_client_id','other-entry')"
                )
            else:
                column = "approval_json" if "approval" in damage else "intent_json"
                if damage.startswith("missing"):
                    db.execute(
                        f"UPDATE execution_orders SET {column}=json_remove({column},'$.closing_entry_client_id') WHERE client_id=?",
                        (close.client_id,),
                    )
                else:
                    db.execute(
                        f"UPDATE execution_orders SET {column}=json_set({column},'$.closing_entry_client_id','other-entry') WHERE client_id=?",
                        (close.client_id,),
                    )
        assert asyncio.run(engine.dispatch(close.client_id, data["quote"], now=NOW)) == "REJECTED"
        assert venue.submit_count == 1
        with engine.journal.read() as db:
            row = db.execute(
                "SELECT attempted_at,active_lock FROM execution_orders WHERE client_id=?",
                (close.client_id,),
            ).fetchone()
            assert tuple(row) == (None, None)
            event = db.execute(
                "SELECT payload FROM execution_events WHERE kind='OPTION_DISPATCH_REJECTED' AND client_id=?",
                (close.client_id,),
            ).fetchone()
            assert json.loads(event[0])["reason"] == "OPTION_CLOSING_ENTRY_CHANGED"


def test_buy_cannot_claim_a_closing_link(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        with pytest.raises(ValidationError, match="Closing entry"):
            OptionIntent.model_validate(entry.model_dump() | {"closing_entry_client_id": "other"})


@pytest.mark.parametrize("legacy", [False, True])
def test_stored_close_conflict_is_not_attributed(tmp_path, legacy):
    with owned(tmp_path) as (engine, venue, data):
        entry = enter(engine, venue, data)
        close = prepare_close(engine, data, entry)
        with engine.journal.write() as db:
            if legacy:
                db.execute(
                    "UPDATE execution_orders SET intent_json=json_remove(intent_json,'$.closing_entry_client_id') WHERE client_id=?",
                    (close.client_id,),
                )
            else:
                db.execute(
                    "UPDATE execution_orders SET approval_json=json_set(approval_json,'$.closing_entry_client_id','other') WHERE client_id=?",
                    (close.client_id,),
                )
        with engine.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (close.client_id,)
            ).fetchone()
            with pytest.raises(ValueError, match="closing entry"):
                order_attribution(db, row)
