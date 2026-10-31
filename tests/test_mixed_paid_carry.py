"""Paid share entry and management preserve the original source-bound carry."""

import asyncio
from datetime import date, timedelta

from test_degen_options import AT
from test_mixed_native_owner import changed, intent_for
from test_mixed_selection import quote, source_fixture, stock_frame
from test_mixed_stock_carry import carry_policy
from test_option_position_coordination import management_frame

from app.execution.economics import UsageEvidence
from app.mixed.native_store import position
from app.mixed.sources import StockCycleInput
from app.options import position_judgment as j
from app.options.engine import fingerprint
from app.options.entry_judgment import result_for


def test_paid_stock_carry_keeps_original_horizon_and_thesis(tmp_path, monkeypatch):
    import test_mixed_entry as fixture

    source, swing, item, _ = source_fixture()
    source = changed(source, carry_exit_session=date(2026, 10, 12))
    item = changed(item, swing=source)
    settings, stocks = fixture.settings, fixture.stock_policy
    monkeypatch.setattr(fixture, "settings", lambda: settings(stock_carry=carry_policy()))
    monkeypatch.setattr(fixture, "stock_policy", lambda: stocks(swing=swing))
    with fixture.owner(tmp_path, monkeypatch, management=True) as (c, v, times, state):
        original_run = c._model_run

        async def select(request, secret, *, broad):
            original = await original_run(request, secret, broad=broad)
            selected = next(
                o for o in request.packet.stocks if o.candidate.proposal.family == "SWING"
            )
            plan = changed(
                original.plan,
                candidate_id=selected.candidate.candidate_id,
                evidence_ids=(fingerprint(selected),),
                thesis="Original carried source",
            )
            state["carry_plan"] = plan
            return result_for(
                request, plan=plan, count=original.counted_input_tokens, usage=original.usage
            )

        monkeypatch.setattr(c, "_model_run", select)
        out = asyncio.run(c.cycle(stock_frame(item=item)))
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        assert entry.carry.sessions[-1].session == date(2026, 10, 12)
        assert entry.exit_at == entry.carry.exit_at
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="paid-carry-entry")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        current = changed(management_frame(), stocks=(StockCycleInput(quote=quote(times[0])),))

        async def maintain(request, _key):
            assert request.packet.entry_thesis == state["carry_plan"]
            assert request.packet.original_source.candidate.proposal.carry == entry.carry
            return j.result_for(
                request,
                plan=j.maintain(request.packet),
                count=100,
                usage=UsageEvidence(
                    request_id="paid-carry-management",
                    model=request.configuration.costs.model,
                    input_tokens=100,
                    output_tokens=20,
                ),
            )

        monkeypatch.setattr(j, "run_position_process", maintain)
        out = asyncio.run(c.cycle(current))
        assert out["status"] == "MAINTAIN", out
        with c.engine.journal.read() as db:
            assert position(c.engine, db).entry == entry
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 2


def test_flat_entry_charge_at_close_clock_belongs_to_next_actual_entry(monkeypatch):
    import sqlite3
    from decimal import Decimal

    from app.mixed import paid_costs
    from app.mixed.models import CostRecord

    records = (
        CostRecord(
            cost_id="next-call",
            kind="ENTRY_MODEL",
            occurred_at=AT,
            amount=".00002",
            evidence_hash="a" * 64,
        ),
        CostRecord(
            cost_id="closing-management",
            kind="MANAGEMENT_MODEL",
            occurred_at=AT,
            amount=".00003",
            entry_client_id="closed",
            evidence_hash="b" * 64,
        ),
    )
    monkeypatch.setattr(paid_costs, "records", lambda db, policy: records)
    intervals = [
        ("closed", AT - timedelta(minutes=5), AT),
        ("next", AT + timedelta(seconds=1), None),
    ]
    with sqlite3.connect(":memory:") as db:
        db.execute(
            "CREATE TABLE execution_option_opportunities(cycle_key TEXT PRIMARY KEY,status TEXT)"
        )
        db.executemany(
            "INSERT INTO execution_option_opportunities VALUES(?,'COMPLETE')",
            [(r.cost_id,) for r in records],
        )
        for entry, expected in (("closed", ".00003"), ("next", ".00002")):
            result = paid_costs.apply(
                db,
                None,
                {"entry_client_id": entry, "net_after_known_execution_and_model_costs": "1"},
                intervals,
            )
            assert Decimal(result["known_model_cost"]) == Decimal(expected)
            assert Decimal(result["net_after_known_execution_and_model_costs"]) == 1 - Decimal(
                expected
            )
