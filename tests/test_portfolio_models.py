"""Scripted full receipts only: no credentials, model service or paid calls."""

import asyncio
import json
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


def test_better_option_book_cannot_increase_original_paid_quantity(tmp_path, monkeypatch):
    from datetime import timedelta
    from pathlib import Path

    from test_mixed_native_owner import changed
    from test_option_runtime import enable, policy, step
    from app.options.coordinator import DegenFrame
    from app.options.runtime import OptionRuntime
    from app.options.runtime_models import PortfolioRuntimePacket

    with owner(tmp_path, monkeypatch, choice="OPTION", portfolio=True, delay=0) as (c, venue, times, saved):
        r = OptionRuntime(c, policy(tmp_path, mixed_inputs="mixed-runtime-inputs-v1"), create=True)
        enable(r)
        def deliver(sequence, kind, frame):
            packet = PortfolioRuntimePacket(sequence=sequence, kind=kind, recorded_at=times[0],
                population_id=c.engine.limits.population_id, frame=changed(frame, portfolio_version="portfolio-frame-v2"))
            path = Path(r.policy.feed_file)
            path.write_text(packet.model_dump_json())
            path.chmod(0o600)
        run = c._model_run
        async def cheaper(request, secret, *, broad):
            result = await run(request, secret, broad=broad)
            original = next(o for o in request.packet.opportunities if o.candidate.candidate_id == result.plan.candidate_id)
            saved["ceiling"] = original.candidate.admission
            times[0] += timedelta(seconds=1)
            q = changed(original.quote, source_at=times[0], received_at=times[0],
                        bid=Decimal(".49"), ask=Decimal(".50"))
            u = changed(original.underlying, source_at=times[0], received_at=times[0])
            deliver(2, 'MARKET', DegenFrame(quotes=(q,), underlyings=(u,)))
            await r.tick()
            return result
        monkeypatch.setattr(c, '_model_run', cheaper)
        deliver(1, 'CYCLE', stock_frame())
        asyncio.run(step(r))
        with c.engine.journal.read() as db:
            decision = json.loads(db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0])
        assert decision['status'] == 'OPEN', (decision.get('reason'), decision.get('prepared'))
        reviewed = decision['entry_review']['admission']
        order, = venue.snapshot(times[0]).orders
        assert order.limit_price < saved['ceiling'].limit_price
        assert order.quantity == reviewed['quantity'] == saved['ceiling'].quantity
        assert order.quantity == decision['prepared']['reserved_quantity']
        with c.engine.journal.read() as db:
            from app.mixed.portfolio_store import verify_order
            row = db.execute("SELECT * FROM execution_portfolio_orders WHERE client_id=?", (order.client_id,)).fetchone()
            intent = verify_order(c.engine, db, c.engine.portfolio_policy, row)
            assert intent.approved_entry_debit == Decimal(reviewed['entry_debit'])
            assert intent.approved_full_premium_loss == Decimal(reviewed['full_premium_loss'])
            assert json.loads(row['approval_json'])['paid_entry_admission'] == reviewed


@pytest.mark.parametrize('choice', ['STOCK', 'OPTION'])
def test_shared_paid_shortlist_can_use_a_monotonically_advancing_clock(tmp_path, monkeypatch, choice):
    from datetime import timedelta

    with owner(tmp_path, monkeypatch, choice=choice, portfolio=True) as (c, venue, times, saved):
        def advancing_clock():
            times[0] += timedelta(microseconds=1)
            return times[0]
        monkeypatch.setattr(c, 'clock', advancing_clock)
        result = asyncio.run(c.cycle(stock_frame()))
        entry = result['entries'][0]
        assert entry['status'] == 'OPEN', (entry.get('reason'), entry.get('blocker'), entry.get('error_class'))
        assert saved['request'].packet.stocks and saved['request'].packet.opportunities
        assert venue.submit_count == 1


def test_entry_lease_expiring_during_persistence_skips_model_without_cost_or_halt(tmp_path, monkeypatch):
    from datetime import datetime

    with owner(tmp_path, monkeypatch, choice='OPTION', portfolio=True) as (c, venue, times, _):
        persist = c._pending_evidence
        def slow_write(key, evidence):
            persist(key, evidence)
            if evidence.get('status') == 'MODEL_PENDING':
                times[0] = datetime.fromisoformat(evidence['entry_request']['packet']['valid_until'])
        monkeypatch.setattr(c, '_pending_evidence', slow_write)
        monkeypatch.setattr(c, '_model_run', lambda *a, **kw: pytest.fail('expired model call'))
        result = asyncio.run(c.cycle(stock_frame()))
        assert result['entries'][0]['reason'] == 'ENTRY_PLAN_EXPIRED_BEFORE_MODEL'
        assert venue.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute('SELECT COUNT(*) FROM execution_model_calls').fetchone()[0] == 0
            assert not db.execute('SELECT halted FROM execution_control').fetchone()[0]
