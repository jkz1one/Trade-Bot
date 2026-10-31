"""Scripted full receipts only: no credentials, model service or paid calls."""

import asyncio
from decimal import Decimal

import pytest
from test_mixed_entry import owner
from test_mixed_selection import stock_frame


@pytest.mark.parametrize("choice", ["STOCK", "OPTION"])
def test_portfolio_entry_uses_one_original_paid_receipt_and_native_dispatch(
    tmp_path, monkeypatch, choice
):
    with owner(tmp_path, monkeypatch, choice=choice, portfolio=True) as (c, v, _times, state):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "COMPLETE", out
        assert len(out["entries"]) == 1
        entry = out["entries"][0]
        assert entry["status"] == "OPEN", {
            k: entry.get(k) for k in ("status", "reason", "blocker", "error_class", "prepared")
        }
        assert v.submit_count == 1
        assert state["request"].packet.version == "portfolio-entry-packet-v2"
        assert state["request"].packet.portfolio_history is not None
        with c.engine.journal.read() as db:
            calls = db.execute("SELECT * FROM execution_model_calls").fetchall()
        assert len(calls) == 1 and Decimal(calls[0]["cost"]) > 0


@pytest.mark.parametrize("mode", ["HOLD", "UNKNOWN", "ERROR"])
def test_portfolio_paid_hold_and_unknown_cost_never_force_second_slot(tmp_path, monkeypatch, mode):
    with owner(tmp_path, monkeypatch, mode=mode, portfolio=True) as (c, v, _times, _state):
        out = asyncio.run(c.cycle(stock_frame()))
        assert len(out["entries"]) == 1, out
        assert out["entries"][0]["status"] == "HOLD"
        assert v.submit_count == 0
        with c.engine.journal.read() as db:
            calls = db.execute("SELECT * FROM execution_model_calls").fetchall()
        assert len(calls) == 1
        assert (calls[0]["cost"] is None) == (mode == "UNKNOWN")


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_exact_portfolio_management_native_consumption(tmp_path, monkeypatch, action):
    from datetime import timedelta

    from test_degen_options import AT
    from test_mixed_native_owner import changed
    from test_mixed_selection import quote
    from test_option_position_coordination import management_frame

    from app.execution.economics import UsageEvidence
    from app.mixed.portfolio_management import current
    from app.mixed.portfolio_store import intent
    from app.mixed.sources import StockCycleInput
    from app.options import position_judgment as j
    from app.options.engine import fingerprint
    from app.options.position_reasoning import PositionPlan

    with owner(tmp_path, monkeypatch, management=True, portfolio=True) as (c, v, times, state):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["entries"][0]["status"] == "OPEN", out.get("management")
        identity = out["entries"][0]["client_id"]
        with c.engine.journal.read() as db:
            entry = intent(
                db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (identity,)
                ).fetchone()
            )
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="management-entry")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        frame = changed(
            management_frame(),
            portfolio_version="portfolio-frame-v2",
            stocks=(StockCycleInput(quote=quote(times[0])),),
        )

        async def worker(request, _secret):
            state["management"] = request
            packet = request.packet
            times[0] += timedelta(seconds=1)
            return j.result_for(
                request,
                plan=PositionPlan(
                    decision_id=packet.decision_id,
                    packet_hash=fingerprint(packet),
                    entry_client_id=packet.play_id,
                    position_revision=packet.position_revision,
                    action=action,
                    underlying_invalidation=Decimal(600) if action == "TIGHTEN" else None,
                    evidence_ids=(packet.evidence_ids[0], packet.evidence_ids[5]),
                    thesis="Original fixture thesis retained",
                    change_since_entry="Completed current context",
                    uncertainty="Scripted offline receipt",
                ),
                count=100,
                usage=UsageEvidence(
                    request_id="portfolio-management",
                    model=request.configuration.costs.model,
                    input_tokens=100,
                    output_tokens=20,
                ),
            )

        monkeypatch.setattr(j, "run_position_process", worker)
        out = asyncio.run(c.cycle(frame))
        result = out["management"]["discretionary"]
        assert (
            result["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), {k: v for k, v in result.items() if k not in {"position_request", "position_result"}}
        assert state["management"].packet.play_id == identity
        assert state["management"].packet.original_decision == state["result"].plan.model_dump(
            mode="json"
        )
        with c.engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 2
            if action == "TIGHTEN":
                assert current(c.engine, db, identity, times[0])[2].invalidation == Decimal(600)
            if action == "EXIT_ALL":
                close = intent(
                    db.execute(
                        "SELECT * FROM execution_portfolio_orders WHERE client_id=?",
                        (result["client_id"],),
                    ).fetchone()
                )
                assert (
                    close.closing_entry_client_id == identity and close.quantity == entry.quantity
                )
        again = asyncio.run(c.cycle(frame))
        assert v.submit_count == (2 if action == "EXIT_ALL" else 1)
        assert again["status"] in {"HELD", "HOLD"}
