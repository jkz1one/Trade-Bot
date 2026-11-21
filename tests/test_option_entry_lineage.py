"""Native family identity follows exact entries, closes and every model charge."""

import asyncio
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_degen_options import AT, frame, owned_strategy
from test_option_entry_coordination import fake_model
from test_option_execution import intent_for
from test_option_position_outcome import read_owned
from test_option_shared_strategy import owner, shared_frame

from app.options.attribution import order_attribution
from app.options.engine import fingerprint
from app.options.lifecycle import OptionIntent
from app.options.models import OptionProposal


def attribution(engine, client_id):
    with engine.journal.read() as db:
        return order_attribution(
            db,
            db.execute("SELECT * FROM execution_orders WHERE client_id=?", (client_id,)).fetchone(),
        )


@pytest.mark.parametrize("family", ["DEGEN", "SWING"])
@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("ai", [False, True])
def test_entry_close_and_cost_outcome_keep_exact_family(tmp_path, monkeypatch, family, right, ai):
    priority = (family, "DEGEN" if family == "SWING" else "SWING")
    with owner(tmp_path, right, ai=ai, priority=priority) as (c, venue, _):
        if ai:
            fake_model(monkeypatch, c)
        f = shared_frame(right)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        entry = intent_for(c.engine, result["client_id"])
        link = entry.entry_lineage
        assert link.family == family
        assert link.opportunity_key == entry.source_key
        selected = next(x for x in result["candidates"] if x["candidate_id"] == link.candidate_id)
        from app.options.selection import parse_candidate

        assert link.candidate_hash == fingerprint(parse_candidate(selected))
        assert attribution(c.engine, entry.client_id)["entry_lineage"] == link.model_dump(
            mode="json"
        )
        q = next(q for q in f.quotes if q.instrument == entry.instrument)
        venue.fill(entry, entry.quantity, q, AT, fill_id="entry")
        assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        closed = c.engine.prepare(
            "close",
            OptionProposal(
                action="CLOSE", contract=entry.instrument.contract, thesis="Close owned position"
            ),
            q,
            now=AT,
        )
        assert closed["status"] == "PREPARED"
        assert asyncio.run(c.engine.dispatch(closed["client_id"], q, now=AT)) == "OPEN"
        sell = intent_for(c.engine, closed["client_id"])
        assert sell.entry_lineage is None
        assert attribution(c.engine, sell.client_id)["entry_lineage"] == link.model_dump(
            mode="json"
        )
        venue.fill(sell, sell.quantity, q, AT, fill_id="exit")
        assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        outcome = read_owned(c.engine, entry)
        assert outcome["entry_lineage"] == link.model_dump(mode="json")
        assert outcome["status"] == "COMPLETE"
        assert Decimal(outcome["known_model_cost"]) == (Decimal(".00015") if ai else 0)
        assert Decimal(outcome["net_after_known_execution_and_model_costs"]) == Decimal(
            outcome["exit_premium"]
        ) - Decimal(outcome["entry_premium"]) - Decimal(outcome["execution_fees"]) - Decimal(
            outcome["known_model_cost"]
        )
        assert asyncio.run(c.cycle(f)) == result


@pytest.mark.parametrize(
    "damage", ["candidate", "duplicate", "selection", "approval", "instrument", "delete"]
)
def test_changed_lineage_blocks_dispatch_before_attempt(tmp_path, monkeypatch, damage):
    with owner(tmp_path) as (c, venue, _):
        original = c.engine.dispatch

        async def changed(client_id, quote, underlying, *, now):
            with c.engine.journal.write() as db:
                row = db.execute(
                    "SELECT * FROM execution_orders WHERE client_id=?", (client_id,)
                ).fetchone()
                if damage == "approval":
                    a = json.loads(row["approval_json"])
                    a["entry_lineage"]["family"] = "DEGEN"
                    db.execute(
                        "UPDATE execution_orders SET approval_json=? WHERE client_id=?",
                        (json.dumps(a), client_id),
                    )
                elif damage == "delete":
                    db.execute(
                        "DELETE FROM execution_option_opportunities WHERE cycle_key=?",
                        (row["source_key"],),
                    )
                else:
                    data = json.loads(
                        db.execute(
                            "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
                            (row["source_key"],),
                        ).fetchone()[0]
                    )
                    selected = next(
                        x for x in data["candidates"] if x["candidate_id"] == data["candidate_id"]
                    )
                    if damage == "candidate":
                        selected["proposal"]["thesis"] = "Changed setup evidence"
                    if damage == "duplicate":
                        data["candidates"].append(selected)
                    if damage == "selection":
                        data["candidate_id"] = "0" * 64
                    if damage == "instrument":
                        selected["instrument"]["instrument_id"] = "other"
                    db.execute(
                        "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                        (json.dumps(data), row["source_key"]),
                    )
            return await original(client_id, quote, underlying, now=now)

        monkeypatch.setattr(c.engine, "dispatch", changed)
        result = asyncio.run(c.cycle(shared_frame()))
        assert result["status"] != "OPEN"
        assert venue.submit_count == 0
        with c.engine.journal.read() as db:
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            assert row["status"] == "REJECTED" and row["attempted_at"] is None
            assert row["active_lock"] is None


def test_unlabeled_historical_intents_are_not_backfilled(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        result = asyncio.run(c.cycle(frame()))
        entry = intent_for(c.engine, result["client_id"])
        assert entry.entry_lineage.family == "DEGEN"
        raw = entry.model_dump(mode="json")
        raw.pop("entry_lineage")
        historical = OptionIntent.model_validate(raw)
        assert "entry_lineage" not in historical.model_dump(mode="json")
        assert historical.model_dump(mode="json") == raw
        previous_fields = entry.model_dump(exclude={"entry_lineage"})
        assert fingerprint(historical) == fingerprint(previous_fields)
        with c.engine.journal.write() as db:
            row = db.execute(
                "SELECT approval_json FROM execution_orders WHERE client_id=?", (entry.client_id,)
            ).fetchone()
            approval = json.loads(row[0])
            approval.pop("entry_lineage")
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=? WHERE client_id=?",
                (historical.model_dump_json(), json.dumps(approval), entry.client_id),
            )
        assert "entry_lineage" not in attribution(c.engine, entry.client_id)


@pytest.mark.parametrize("damage", ["family", "key", "side"])
def test_frozen_lineage_cannot_claim_scope_or_another_order(tmp_path, damage):
    with owner(tmp_path) as (c, _, _):
        r = asyncio.run(c.cycle(shared_frame()))
        raw = intent_for(c.engine, r["client_id"]).model_dump(mode="json")
        if damage == "family":
            raw["entry_lineage"]["family"] = "SCOPE"
        if damage == "key":
            raw["entry_lineage"]["opportunity_key"] = "foreign"
        if damage == "side":
            raw["side"] = "SELL"
        with pytest.raises(ValidationError):
            OptionIntent.model_validate(raw)


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_management_advice_inherits_entry_family_with_cost(tmp_path, monkeypatch, action):
    from test_option_position_coordination import (
        enter_position,
        management_frame,
        model,
        owned_manager,
    )

    with owned_manager(tmp_path) as (c, venue, times):
        entry = enter_position(c, venue, times, monkeypatch)
        model(monkeypatch, c, action)
        asyncio.run(c.cycle(management_frame()))
        outcome = read_owned(c.engine, entry)
        assert outcome["entry_lineage"]["family"] == "DEGEN"
        assert {x["entry_lineage"]["candidate_hash"] for x in outcome["model_calls"]} == {
            entry.entry_lineage.candidate_hash
        }
        assert {x["role"] for x in outcome["model_calls"]} == {"ENTRY", "MANAGEMENT"}
        assert Decimal(outcome["known_model_cost"]) == Decimal(".00030")


@pytest.mark.parametrize("damage", ["approval", "intent", "candidate"])
def test_stored_lineage_damage_cannot_relabel_an_existing_trade(tmp_path, damage):
    with owner(tmp_path) as (c, _, _):
        result = asyncio.run(c.cycle(shared_frame()))
        entry = intent_for(c.engine, result["client_id"])
        with c.engine.journal.write() as db:
            if damage == "candidate":
                data = json.loads(
                    db.execute(
                        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
                        (entry.source_key,),
                    ).fetchone()[0]
                )
                candidate = next(
                    x
                    for x in data["candidates"]
                    if x["candidate_id"] == entry.entry_lineage.candidate_id
                )
                candidate["proposal"]["thesis"] = "Rewritten history"
                db.execute(
                    "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                    (json.dumps(data), entry.source_key),
                )
            else:
                column = "approval_json" if damage == "approval" else "intent_json"
                raw = json.loads(
                    db.execute(
                        f"SELECT {column} FROM execution_orders WHERE client_id=?",
                        (entry.client_id,),
                    ).fetchone()[0]
                )
                raw["entry_lineage"]["family"] = "DEGEN"
                db.execute(
                    f"UPDATE execution_orders SET {column}=? WHERE client_id=?",
                    (json.dumps(raw), entry.client_id),
                )
        with pytest.raises(ValueError, match="LINEAGE"):
            attribution(c.engine, entry.client_id)
