"""Original Scope watch receipts consumed by the common two-play PAPER owner."""

import asyncio
from datetime import timedelta

import pytest
from test_mixed_native_owner import changed
from test_option_scope_execution import execution_policy, policy
from test_option_scope_management import admitted
from test_option_scope_watch import owned, revision
from test_portfolio_controls import get_intent

from app.mixed.accounting import reconstruct
from app.mixed.portfolio_store import history
from app.options.models import OptionProposal


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_scope_native_portfolio_entry_partial_exit_restart_identity(tmp_path, right):
    with owned(
        tmp_path, enroll=False, portfolio=True, execution_policy_changes=execution_policy()
    ) as (e, v, _):
        book, _, f, _, u, now = admitted(e, v, right, 2, p=policy())
        result = book.prepare_entry("first", expected_revision=revision(e), now=now)
        assert result["status"] == "PREPARED", result
        entry = get_intent(e, result["client_id"])
        assert entry.entry_lineage.family == "SCOPE"
        assert asyncio.run(e.dispatch(entry.client_id, f.quote, u, now=now)) == "OPEN"
        v.fill(entry, entry.quantity, f.quote, now, fill_id="scope-entry", underlying=u)
        assert e.reconcile(v.snapshot(now), now=now)["reconciled"]
        assert book.snapshot()["watches"][0]["status"] == "POSITION_OPEN"
        at = now + timedelta(seconds=1)
        q = changed(f.quote, source_at=at, received_at=at)
        fresh = changed(u, source_at=at, received_at=at)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        result = e.prepare(
            "scope-partial",
            OptionProposal(
                action="CLOSE",
                contract=entry.instrument.contract,
                close_quantity=1,
                thesis="Partial fixture exit",
            ),
            q,
            fresh,
            now=at,
            play_id=entry.client_id,
        )
        assert result["status"] == "PREPARED", result
        close = get_intent(e, result["client_id"])
        assert asyncio.run(e.dispatch(close.client_id, q, fresh, now=at)) == "OPEN"
        v.fill(close, 1, q, at, fill_id="scope-partial", underlying=fresh)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        with e.journal.read() as db:
            held = reconstruct(history(e, db, e.portfolio_policy, at)).ledger.positions[
                entry.client_id
            ]
        assert (
            held.quantity == 1
            and held.original_underlying_invalidation == entry.original_underlying_invalidation
        )
        assert held.target_exit_schedule == entry.target_exit_schedule
        assert book.snapshot()["watches"][0]["status"] == "POSITION_OPEN"
        path, limits, execution = e.journal.path, e.limits, e.policy
    from app.options.engine import OptionExecution

    with OptionExecution.open(path, limits, execution, v, now=at) as e:
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        with e.journal.read() as db:
            assert list(reconstruct(history(e, db, e.portfolio_policy, at)).ledger.positions) == [
                entry.client_id
            ]


def test_paid_scope_uses_full_original_receipt_and_shared_native_owner(tmp_path, monkeypatch):
    from test_option_scope_ai import ai_owner

    with ai_owner(tmp_path, monkeypatch, portfolio=True) as (c, v, times, frame, *_rest):
        out = asyncio.run(c.cycle(frame))
        assert out["entries"], out
        selected = out["entries"][0]
        assert selected["status"] == "OPEN", {
            k: v
            for k, v in selected.items()
            if k in {"status", "reason", "prepared", "error_class"}
        }
        entry = get_intent(c.engine, selected["client_id"])
        assert entry.entry_lineage.family == "SCOPE" and v.submit_count == 1
        with c.engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 1
            from app.mixed.paid_costs import records

            assert records(db, c.engine.policy)[0].entry_client_id == entry.client_id
        q = changed(frame.scope.frame.quote, source_at=times[0], received_at=times[0])
        u = changed(frame.scope.underlying, source_at=times[0], received_at=times[0])
        v.fill(entry, entry.quantity, q, times[0], fill_id="paid-scope", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]


@pytest.mark.parametrize(
    "action,production_worker",
    [("MAINTAIN", False), ("TIGHTEN", False), ("EXIT_ALL", False), ("MAINTAIN", True)],
)
def test_scope_management_retains_full_original_packet_and_exact_cost_owner(
    tmp_path, monkeypatch, action, production_worker
):
    from test_option_scope_ai import ai_owner
    from test_option_scope_position import fake_model, management_frame

    from app.mixed.paid_costs import records
    from app.options.position_reasoning import PositionReasoningPolicy

    policy = PositionReasoningPolicy(
        max_lease_seconds=5,
        scope_management="scope-fixed-position-v1",
        mixed_management="mixed-stock-position-v1",
    )
    limits = None
    if production_worker:
        from app.mixed.simulation_profile import configuration

        settings, _ = configuration()
        policy, limits = settings.position_policy, settings.judgment_limits
    with ai_owner(
        tmp_path, monkeypatch, portfolio=True, position_policy=policy, judgment_limits=limits
    ) as (
        c,
        v,
        times,
        frame,
        _state,
    ):
        out = asyncio.run(c.cycle(frame))
        assert out["entries"][0]["status"] == "OPEN", out["entries"][0].get("reason")
        entry = get_intent(c.engine, out["entries"][0]["client_id"])
        q = changed(frame.scope.frame.quote, source_at=times[0], received_at=times[0])
        u = changed(frame.scope.underlying, source_at=times[0], received_at=times[0])
        v.fill(entry, entry.quantity, q, times[0], fill_id="entry", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        original_watch = c.scope_book.snapshot()["watches"][0]
        times[0] = times[0].replace(second=0, microsecond=0) + timedelta(minutes=5)
        current = management_frame(frame, times[0])
        calls = fake_model(monkeypatch, action)
        out = asyncio.run(c.cycle(current))
        result = out["management"]["discretionary"]
        assert (
            result["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), {k: v for k, v in result.items() if k in {"status", "reason", "error_class"}}
        packet = calls[0][0].packet
        assert len(calls) == 1
        assert v.submit_count == (2 if action == "EXIT_ALL" else 1)
        assert out["entries"][0]["scope_candidate"] is None
        assert out["entries"][0]["scope_owned"]["client_id"] == entry.client_id
        current_watch = c.scope_book.snapshot()["watches"][0]
        assert current_watch["arming"] == original_watch["arming"]
        assert current_watch["admission_review"] == original_watch["admission_review"]
        assert (
            packet.play_id == entry.client_id
            and packet.original_context["binding"]["play_key"] == "first"
        )
        assert packet.original_decision["scope"] is True
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT halted FROM execution_control WHERE id=1").fetchone()[0]
            assert (
                db.execute("SELECT count(*) FROM execution_option_scope_entries").fetchone()[0] == 1
            )
            assert len(records(db, c.engine.policy)) == 2
            assert all(r.entry_client_id == entry.client_id for r in records(db, c.engine.policy))
        if action == "EXIT_ALL":
            from decimal import Decimal

            from app.mixed.portfolio_loss import outcomes

            sale = get_intent(c.engine, result["client_id"])
            v.fill(
                sale,
                sale.quantity,
                current.scope.frame.quote,
                times[0],
                fill_id="managed-exit",
                underlying=current.scope.underlying,
            )
            assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
            with c.engine.journal.read() as db:
                completed = outcomes(history(c.engine, db, c.engine.portfolio_policy, times[0]))
                assert len(completed) == 1
                assert completed[0]["entry_client_id"] == entry.client_id
                assert Decimal(completed[0]["model_cost"]) == sum(
                    r.amount for r in records(db, c.engine.policy)
                )
        if production_worker:
            # Exercise the installed SDK worker with the existing production
            # budgets (15s process, 20s management lease). The separate legacy
            # five-second test and all native quote gates stay unchanged.
            import sys
            from pathlib import Path

            from test_execution_judgment import response
            from test_option_scope_position import REAL_WORKER
            from app.options import position_judgment as judgment

            request = calls[0][0]
            assert request.configuration.limits == limits
            assert packet.policy == policy
            output = response()
            output["output"][0]["content"][0]["text"] = judgment.maintain(packet).model_dump_json()
            real_spawn = asyncio.create_subprocess_exec
            source = (
                f"import sys\nsys.path[:0]=[{str(Path(__file__).parent.parent)!r},{str(Path(__file__).parent)!r}]\n"
                "import app.options.position_judgment_worker as worker\n"
                "from test_execution_judgment import sdk_client\n"
                f"output={output!r}\n"
                "def factory(**kw):\n"
                " assert kw['base_url']=='https://api.openai.com/v1' and kw['max_retries']==0\n"
                " return sdk_client(output=output)[0]\n"
                "worker.OpenAI=factory\nraise SystemExit(worker.main())\n"
            )

            async def spawn(*args, **kwargs):
                assert args == (sys.executable, "-I", "-m", "app.options.position_judgment_worker")
                return await real_spawn(sys.executable, "-I", "-c", source, **kwargs)

            monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
            renewed = judgment.create_request(
                packet, request.configuration, request_id="d" * 32, now=packet.as_of
            )
            result = asyncio.run(REAL_WORKER(renewed, "fixture-never-transmitted"))
            assert result.error is None and result.plan.action == "MAINTAIN"


@pytest.mark.parametrize("coverage", ["missing", "foreign"])
def test_owned_scope_context_cannot_be_reused_as_an_entry(tmp_path, monkeypatch, coverage):
    from test_option_scope_ai import ai_owner
    from test_option_scope_position import management_frame

    with ai_owner(tmp_path, monkeypatch, portfolio=True) as (c, v, times, frame, _):
        out = asyncio.run(c.cycle(frame))
        assert out["entries"][0]["status"] == "OPEN", out
        entry = get_intent(c.engine, out["entries"][0]["client_id"])
        clocks = {"source_at": times[0], "received_at": times[0]}
        v.fill(
            entry,
            entry.quantity,
            changed(frame.scope.frame.quote, **clocks),
            times[0],
            fill_id="entry",
            underlying=changed(frame.scope.underlying, **clocks),
        )
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = times[0].replace(second=0, microsecond=0) + timedelta(minutes=5)
        current = management_frame(frame, times[0])
        scope = current.scope
        current = changed(
            current,
            scope=None if coverage == "missing" else changed(scope, play_key="foreign"),
            held_quotes=(scope.frame.quote,) if coverage == "missing" else (),
            held_underlyings=(scope.underlying,) if coverage == "missing" else (),
        )
        out = asyncio.run(c.cycle(current))
        decision = out["entries"][0]
        if coverage == "missing":
            assert decision["scope_candidate"] is None
            assert decision["scope_owned"]["client_id"] == entry.client_id
        else:
            assert decision["blocker"] == "EXACT_SCOPE_WATCH_COVERAGE_REQUIRED"
        assert v.submit_count == 1
        with c.engine.journal.read() as db:
            assert bool(db.execute("SELECT halted FROM execution_control").fetchone()[0]) == (
                coverage == "foreign"
            )
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 1
            assert (
                db.execute("SELECT count(*) FROM execution_option_scope_entries").fetchone()[0] == 1
            )


def test_scope_lost_ack_recovers_filled_contract_after_restart(tmp_path):
    from app.options.engine import OptionExecution
    with owned(tmp_path, enroll=False, portfolio=True, execution_policy_changes=execution_policy()) as (engine, venue, _):
        book, _, frame, _, underlying, now = admitted(engine, venue, 'CALL', 2, p=policy())
        result = book.prepare_entry('first', expected_revision=revision(engine), now=now)
        entry = get_intent(engine, result['client_id'])
        venue.fault = 'LOST_ACK'
        assert asyncio.run(engine.dispatch(entry.client_id, frame.quote, underlying, now=now)) == 'UNKNOWN'
        venue.fault = 'NONE'
        venue.fill(entry, entry.quantity, frame.quote, now, fill_id='option-recovery', underlying=underlying)
        path, limits, execution = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, execution, venue, now=now) as engine:
        assert engine.reconcile(venue.snapshot(now), now=now)['attempt_recovery'] == {'matched':1, 'unresolved':0}
        assert asyncio.run(engine.dispatch(entry.client_id, frame.quote, underlying, now=now)) == 'FILLED'
        assert venue.submit_count == 1
