"""Native share management, full costs and mandatory exits with no external calls."""

import asyncio
from datetime import timedelta
from decimal import Decimal as D

import pytest
from test_degen_options import AT
from test_mixed_entry import owner
from test_mixed_native_owner import changed, intent_for
from test_mixed_selection import quote, stock_frame
from test_option_position_coordination import management_frame

from app.execution.economics import UsageEvidence
from app.mixed.sources import StockCycleInput
from app.options import position_judgment as j
from app.options.engine import fingerprint
from app.options.position_reasoning import PositionPlan


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_native_paid_stock_management(tmp_path, monkeypatch, action):
    with owner(tmp_path, monkeypatch, management=True) as (c, v, times, state):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="position-entry")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        f = changed(management_frame(), stocks=(StockCycleInput(quote=quote(times[0])),))

        async def run(request, _key):
            state["position_request"] = request
            p = request.packet
            times[0] += timedelta(seconds=1)
            plan = PositionPlan(
                decision_id=p.decision_id,
                packet_hash=fingerprint(p),
                entry_client_id=entry.client_id,
                position_revision=p.position_revision,
                action=action,
                underlying_invalidation=D(600) if action == "TIGHTEN" else None,
                evidence_ids=(p.evidence_ids[0], p.evidence_ids[5]),
                thesis="Retain original stock thesis",
                change_since_entry="Completed current context",
                uncertainty="Fixture only",
            )
            result = j.result_for(
                request,
                plan=plan,
                count=100,
                usage=UsageEvidence(
                    request_id="stock-management",
                    model=request.configuration.costs.model,
                    input_tokens=100,
                    output_tokens=20,
                ),
            )
            j.validate_result(request, result)
            return result

        monkeypatch.setattr(j, "run_position_process", run)
        out = asyncio.run(c.cycle(f))
        assert (
            out["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), {k: v for k, v in out.items() if k not in {"position_request", "position_result"}}
        assert state["position_request"].packet.entry_thesis == state["result"].plan
        with c.engine.journal.read() as db:
            calls = db.execute("SELECT cost FROM execution_model_calls").fetchall()
            assert len(calls) == 2 and all(D(r[0]) == D(".00002") for r in calls)
        if action == "TIGHTEN":
            from app.mixed.native_store import protection

            with c.engine.journal.read() as db:
                assert protection(c.engine, db).invalidation == D(600)
        if action == "EXIT_ALL":
            closing = intent_for(c.engine, out["client_id"])
            assert closing.quantity == entry.quantity
            times[0] += timedelta(seconds=1)
            v.fill_stock(
                closing, closing.quantity, quote(times[0]), times[0], fill_id="position-close"
            )
            assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
            from app.mixed.native_outcome import stock_outcome

            with c.engine.journal.read() as db:
                result = stock_outcome(c.engine, db, entry.client_id)
            assert result["known_model_cost"] == "0.00004", result
            assert result["status"] == "COMPLETE", result
        import json

        from app.execution.engine import ExecutionBlocked
        from app.mixed.paid_costs import records

        # The persisted charge and advice are still verified after application.
        with c.engine.journal.write() as db:
            if action == "EXIT_ALL":
                db.execute(
                    "UPDATE execution_model_calls SET cost='0' WHERE source_key=?",
                    (out["cycle_key"],),
                )
            else:
                field = "inputs_json" if action == "MAINTAIN" else "result_json"
                data = json.loads(
                    db.execute(
                        f"SELECT {field} FROM execution_option_opportunities WHERE cycle_key=?",
                        (out["cycle_key"],),
                    ).fetchone()[0]
                )
                if action == "MAINTAIN":
                    data["histories"][0]["source_at"] = AT.isoformat()
                else:
                    data["position_result"]["plan"]["thesis"] = "Altered after application"
                db.execute(
                    f"UPDATE execution_option_opportunities SET {field}=? WHERE cycle_key=?",
                    (json.dumps(data), out["cycle_key"]),
                )
        with c.engine.journal.read() as db, pytest.raises((ValueError, ExecutionBlocked)):
            records(db, c.engine.policy)


@pytest.mark.parametrize("fault", ["unknown", "late", "mandatory", "widen", "reader", "partial"])
def test_stock_management_cannot_override_native_truth(tmp_path, monkeypatch, fault):
    from app.mixed.native_store import protection

    with owner(tmp_path, monkeypatch, management=True) as (c, v, times, _):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN"
        entry = intent_for(c.engine, out["client_id"])
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="failure-entry")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        f = changed(management_frame(), stocks=(StockCycleInput(quote=quote(times[0])),))

        async def run(request, _key):
            p = request.packet
            times[0] += timedelta(seconds=6 if fault == "late" else 1)
            if fault == "unknown":
                return j.result_for(request, error="TimeoutError")
            if fault == "partial":
                # A real observed partial close during the wait makes the original
                # owned quantity obsolete, even if the quoted symbol is unchanged.
                from app.mixed.models import StockProposal

                prepared = c.engine.prepare_stock(
                    "during-management",
                    StockProposal(
                        action="CLOSE", instrument=entry.instrument, thesis="Observed partial close"
                    ),
                    quote(times[0]),
                    now=times[0],
                    close_quantity=D(".1"),
                )
                assert prepared["status"] == "PREPARED", prepared
                assert (
                    await c.engine.dispatch_stock(
                        prepared["client_id"], quote(times[0]), now=times[0]
                    )
                    == "OPEN"
                )
                closing = intent_for(c.engine, prepared["client_id"])
                times[0] += timedelta(seconds=1)
                v.fill_stock(
                    closing,
                    closing.quantity,
                    quote(times[0]),
                    times[0],
                    fill_id="during-management-fill",
                )
                assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
            plan = PositionPlan(
                decision_id=p.decision_id,
                packet_hash=fingerprint(p),
                entry_client_id=entry.client_id,
                position_revision=p.position_revision,
                action="TIGHTEN",
                underlying_invalidation=D(500) if fault == "widen" else D(600),
                evidence_ids=(p.evidence_ids[0], p.evidence_ids[5]),
                thesis="Paid review",
                change_since_entry="Current context",
                uncertainty="Fixture only",
            )
            return j.result_for(
                request,
                plan=plan,
                count=100,
                usage=UsageEvidence(
                    request_id="failed-management",
                    model=request.configuration.costs.model,
                    input_tokens=100,
                    output_tokens=20,
                ),
            )

        monkeypatch.setattr(j, "run_position_process", run)
        if fault in {"mandatory", "reader"}:

            async def refresh(_instrument):
                if fault == "reader":
                    raise OSError("private reader failure")
                return quote(times[0], bid=D(599), ask=D("599.01"))

            c.stock_refresh = refresh
        out = asyncio.run(c.cycle(f))
        assert out["status"] not in {"TIGHTENED", "OPEN"}, {
            k: v for k, v in out.items() if k not in {"position_request", "position_result"}
        }
        with c.engine.journal.read() as db:
            guard = protection(c.engine, db)
            assert guard.invalidation == entry.original_invalidation
            rows = db.execute("SELECT cost FROM execution_model_calls ORDER BY rowid").fetchall()
            assert len(rows) == 2 and (rows[-1][0] is None) == (fault == "unknown")
        if fault == "mandatory":
            assert out["management"]["status"] == "OPEN", out


def test_stock_management_real_worker_mock_transport(tmp_path, monkeypatch):
    from test_execution_judgment import response, sdk_client

    from app.options.position_judgment_worker import perform

    with owner(tmp_path, monkeypatch, management=True) as (c, v, times, _):
        out = asyncio.run(c.cycle(stock_frame()))
        entry = intent_for(c.engine, out["client_id"])
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="worker-entry")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        f = changed(management_frame(), stocks=(StockCycleInput(quote=quote(times[0])),))

        async def run(request, _key):
            data = response()
            data["output"][0]["content"][0]["text"] = j.maintain(request.packet).model_dump_json()
            client, calls = sdk_client(output=data)
            with client:
                result = perform(request, client)
            assert result.error is None
            assert len(calls) == 2 and all(body["tools"] == [] for _, body in calls)
            return result

        monkeypatch.setattr(j, "run_position_process", run)
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "MAINTAIN", out


@pytest.mark.parametrize("choice", ["OPTION", "SCOPE"])
@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_mixed_paid_option_management_keeps_native_terms(tmp_path, monkeypatch, choice, action):
    from test_mixed_entry import scope_owner
    from test_option_execution import intent_for as option_intent
    from test_option_execution import ledger
    from test_option_scope_execution import sell
    from test_option_scope_position import fake_model
    from test_option_scope_position import management_frame as scope_frame

    from app.options.position_outcome import native_position_outcome

    with scope_owner(tmp_path, monkeypatch, choice, management=True) as (c, v, times, f):
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "OPEN", out
        entry = option_intent(c.engine, out["client_id"])
        q, u = (
            (f.scope.frame.quote, f.scope.underlying)
            if choice == "SCOPE"
            else (f.quotes[0], f.underlyings[0])
        )
        q = changed(q, source_at=times[0], received_at=times[0])
        u = changed(u, source_at=times[0], received_at=times[0])
        v.fill(entry, entry.quantity, q, times[0], fill_id="mixed-option-entry", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        current = (
            scope_frame(f, times[0])
            if choice == "SCOPE"
            else changed(
                f,
                histories=management_frame().histories,
                quotes=tuple(
                    changed(q, source_at=times[0], received_at=times[0]) for q in f.quotes
                ),
                underlyings=tuple(
                    changed(u, source_at=times[0], received_at=times[0]) for u in f.underlyings
                ),
            )
        )
        original = ledger(c.engine).position
        calls = fake_model(monkeypatch, action)
        out = asyncio.run(c.cycle(current))
        assert (
            out["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), out
        assert len(calls) == 1
        if choice == "SCOPE":
            assert calls[0][0].packet.scope_context.selection.version == "mixed-entry-plan-v1"
        held = ledger(c.engine).position
        for name in (
            "target_exit_schedule",
            "entry_premium_protection",
            "entry_time_protection",
            "exit_at",
            "original_underlying_invalidation",
        ):
            assert getattr(held, name) == getattr(original, name)
        assert asyncio.run(c.cycle(current)) == out
        q, u = (
            (current.scope.frame.quote, current.scope.underlying)
            if choice == "SCOPE"
            else (current.quotes[0], current.underlyings[0])
        )
        if action == "EXIT_ALL":
            closing = option_intent(c.engine, out["client_id"])
            v.fill(
                closing, closing.quantity, q, times[0], fill_id="mixed-option-exit", underlying=u
            )
            assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        else:
            sell(c.engine, v, entry, q, u, times[0], key="mixed-final")
        with c.engine.journal.read() as db:
            outcome = native_position_outcome(db, entry.client_id, c.engine.limits.population_id)
        assert outcome["status"] == "COMPLETE", outcome
        assert D(outcome["known_model_cost"]) == D(".00017"), outcome
        assert len(outcome["model_calls"]) == 2


@pytest.mark.parametrize("interrupted", [False, True])
def test_stock_management_restart_never_repeats_paid_attempt(tmp_path, monkeypatch, interrupted):
    import json

    from app.options.coordinator import DegenCoordinator
    from app.options.engine import OptionExecution

    with owner(tmp_path, monkeypatch, management=True) as (c, v, times, _):
        out = asyncio.run(c.cycle(stock_frame()))
        entry = intent_for(c.engine, out["client_id"])
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="restart-entry")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        f = changed(management_frame(), stocks=(StockCycleInput(quote=quote(times[0])),))

        async def run(request, _key):
            if interrupted:
                raise asyncio.CancelledError()
            plan = changed(
                j.maintain(request.packet), action="TIGHTEN", underlying_invalidation=D(600)
            )
            return j.result_for(
                request,
                plan=plan,
                count=100,
                usage=UsageEvidence(
                    request_id="restart-management",
                    model=request.configuration.costs.model,
                    input_tokens=100,
                    output_tokens=20,
                ),
            )

        monkeypatch.setattr(j, "run_position_process", run)
        if interrupted:
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(c.cycle(f))
            with c.engine.journal.read() as db:
                out = json.loads(
                    db.execute(
                        "SELECT result_json FROM execution_option_opportunities ORDER BY started_at DESC LIMIT 1"
                    ).fetchone()[0]
                )
        else:
            out = asyncio.run(c.cycle(f))
            assert out["status"] == "TIGHTENED", out
        saved = c.engine.limits, c.engine.policy
        config = {
            "stock_policy": c.stock_policy,
            "entry_policy": c.entry_policy,
            "position_policy": c.position_policy,
            "judgment_limits": c.judgment_limits,
            "key_file": c.key_file,
            "stock_refresh": c.stock_refresh,
        }
        setup, selection = c.policy, c.selection
    with OptionExecution.open(tmp_path / "engine.db", *saved, v, now=times[0]) as e:
        restored = DegenCoordinator(e, setup, selection, clock=lambda: times[0], **config)
        assert asyncio.run(restored.cycle(f)) == out
        with e.journal.read() as db:
            from app.mixed.native_store import protection

            assert protection(e, db).invalidation == (
                entry.original_invalidation if interrupted else D(600)
            )
            rows = db.execute("SELECT cost FROM execution_model_calls ORDER BY rowid").fetchall()
            assert len(rows) == 2 and (rows[-1][0] is None) == interrupted
        times[0] += timedelta(seconds=1)
        assert e.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        result = asyncio.run(
            e.protective_stock_tick(quote(times[0], bid=D(599), ask=D("599.01")), now=times[0])
        )
        assert result["status"] == "OPEN", result
        assert v.submit_count == 2
