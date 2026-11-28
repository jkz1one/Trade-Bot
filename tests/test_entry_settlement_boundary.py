"""Real mixed runtime boundaries with scripted paid replies and native PAPER orders."""

import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_mixed_entry import owner
from test_mixed_native_owner import changed
from test_mixed_selection import stock_frame
from test_option_runtime import enable, policy, step

from app.mixed import portfolio_execution
from app.options.runtime import OptionRuntime
from app.options.runtime_models import PortfolioRuntimePacket


@contextmanager
def runtime(tmp_path, monkeypatch):
    with owner(tmp_path, monkeypatch, choice="OPTION", portfolio=True, delay=0) as context:
        c, _, times, _ = context
        r = OptionRuntime(c, policy(tmp_path, mixed_inputs="mixed-runtime-inputs-v1"), create=True)
        enable(r)
        packet = PortfolioRuntimePacket(
            sequence=1, kind="CYCLE", recorded_at=times[0],
            population_id=c.engine.limits.population_id,
            frame=changed(stock_frame(), portfolio_version="portfolio-frame-v2"),
        )
        path = Path(r.policy.feed_file)
        path.write_text(packet.model_dump_json())
        path.chmod(0o600)
        yield r, *context


def saved_reply(c, saved, *, settled=True):
    with c.engine.journal.read(verify_restore=True) as db:
        call, = db.execute("SELECT cost,usage_json FROM execution_model_calls")
        assert (call["cost"] is not None) == settled
        if settled:
            assert Decimal(call["cost"]) == Decimal(".00002")
            assert json.loads(call["usage_json"]) == saved["result"].usage.model_dump(mode="json")
        decision = json.loads(db.execute(
            "SELECT result_json FROM execution_option_opportunities").fetchone()[0])
        assert decision["entry_request"] == saved["request"].model_dump(mode="json")
        assert decision["entry_result"] == saved["result"].model_dump(mode="json")
        orders = [dict(row) for row in db.execute("SELECT * FROM execution_portfolio_orders")]
    return decision, orders


@pytest.mark.parametrize("combined", [True, False])
def test_charge_and_attempt_are_durable_before_native_handoff(tmp_path, monkeypatch, combined):
    with runtime(tmp_path, monkeypatch) as (r, c, venue, _, saved):
        if not combined:
            monkeypatch.setattr(r.mixed, "protection_complete", lambda: False)
        write, native = c.engine.journal.write, portfolio_execution.run_option_process
        committed = []

        @contextmanager
        def observe():
            statements = []
            with write() as db:
                db.set_trace_callback(statements.append)
                yield db
            committed.append(statements)

        async def handoff(*args, **kwargs):
            decision, orders = saved_reply(c, saved)
            assert decision["entry_review"]["outcome"] == "ELIGIBLE"
            order, = orders
            assert order["status"] == "SUBMITTING" and order["attempted_at"]
            charge = [i for i, sql in enumerate(committed) if any(
                "UPDATE execution_model_calls SET usage_json" in s for s in sql)]
            attempt = [i for i, sql in enumerate(committed) if any(
                "UPDATE execution_portfolio_orders SET status='SUBMITTING'" in s for s in sql)]
            assert len(charge) == len(attempt) == 1
            assert attempt[0] - charge[0] == (0 if combined else 1)
            return await native(*args, **kwargs)

        monkeypatch.setattr(c.engine.journal, "write", observe)
        monkeypatch.setattr(portfolio_execution, "run_option_process", handoff)
        asyncio.run(step(r))
        decision, _ = saved_reply(c, saved)
        assert decision["status"] == "OPEN", decision.get("reason")
        assert venue.submit_count == 1
        asyncio.run(step(r))
        assert venue.submit_count == 1


@pytest.mark.parametrize("fault", ["selection", "reservation", "commit", "usage"])
def test_failed_combined_write_keeps_reply_and_never_hands_off(tmp_path, monkeypatch, fault):
    from app.options import entry_coordination

    with runtime(tmp_path, monkeypatch) as (r, c, venue, _, saved):
        write = c.engine.journal.write
        if fault == "selection":
            def reject(*args, **kwargs):
                raise ValueError("injected selection failure")
            monkeypatch.setattr(entry_coordination, "_regular_option_choice", reject)
        elif fault in {"reservation", "usage"}:
            with write() as db:
                if fault == "reservation":
                    db.execute("CREATE TRIGGER reject_entry BEFORE INSERT ON execution_portfolio_orders "
                               "BEGIN SELECT RAISE(ABORT,'injected reservation failure'); END")
                else:
                    db.execute("CREATE TRIGGER reject_usage BEFORE INSERT ON execution_events "
                               "WHEN NEW.kind='OPTION_MODEL_USAGE_RECORDED' "
                               "BEGIN SELECT RAISE(ABORT,'injected usage failure'); END")
        else:
            @contextmanager
            def reject_commit():
                with write() as db:
                    yield db
                    if db.execute("SELECT 1 FROM execution_portfolio_orders WHERE status='SUBMITTING'").fetchone():
                        raise OSError("injected commit failure")
            monkeypatch.setattr(c.engine.journal, "write", reject_commit)
        asyncio.run(step(r))
        decision, orders = saved_reply(c, saved, settled=fault != "usage")
        assert not orders and venue.submit_count == 0
        assert decision["reason"] == "DEGEN_CYCLE_FAILED"
        if fault in {"reservation", "commit"}:
            assert decision["entry_review"]["outcome"] == "ELIGIBLE"
        asyncio.run(step(r))
        assert venue.submit_count == 0
        saved_reply(c, saved, settled=fault != "usage")


def test_process_loss_inside_combined_writer_leaves_unknown_charge_and_no_order(tmp_path, monkeypatch):
    from app.mixed import portfolio_options

    with runtime(tmp_path, monkeypatch) as (r, c, venue, times, _):
        assert c.engine.journal.enable_restore_fence(now=times[0])["status"] == "VERIFIED"
        begin = portfolio_options.begin

        def die_before_commit(*args, **kwargs):
            admitted = begin(*args, **kwargs)
            assert not isinstance(admitted, str)
            os._exit(91)  # No Python exception handler or rollback callback runs.

        with monkeypatch.context() as patch:
            patch.setattr(portfolio_options, "begin", die_before_commit)
            pid = os.fork()
            if pid == 0:
                asyncio.run(step(r))
                os._exit(92)
            _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 91
        with c.engine.journal.read(verify_restore=True) as db:
            call, = db.execute("SELECT cost,usage_json FROM execution_model_calls")
            assert tuple(call) == (None, None)
            assert not db.execute("SELECT 1 FROM execution_portfolio_orders").fetchone()
            evidence = json.loads(db.execute(
                "SELECT result_json FROM execution_option_opportunities").fetchone()[0])
            assert evidence["entry_request"] and "entry_result" not in evidence
        assert venue.submit_count == 0
        assert not c.engine.mixed_account(now=times[0]).budgets_known
        asyncio.run(c.cycle(stock_frame()))
        with c.engine.journal.read(verify_restore=True) as db:
            assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM execution_portfolio_orders").fetchone()
        assert venue.submit_count == 0


def test_original_deadline_still_expires_inside_combined_writer(tmp_path, monkeypatch):
    with runtime(tmp_path, monkeypatch) as (r, c, venue, times, saved):
        model, usage = c._model_run, c.engine.record_entry_usage

        async def near_deadline(request, *args, **kwargs):
            result = await model(request, *args, **kwargs)
            times[0] = request.packet.valid_until - timedelta(seconds=.335549)
            return result

        def delayed_usage(*args, **kwargs):
            result = usage(*args, **kwargs)
            times[0] += timedelta(seconds=.958359)
            return result

        monkeypatch.setattr(c, "_model_run", near_deadline)
        monkeypatch.setattr(c.engine, "record_entry_usage", delayed_usage)
        asyncio.run(step(r))
        decision, orders = saved_reply(c, saved)
        assert decision["entry_timely"] is True
        assert decision["reason"] == "ORIGINAL_PLAN_DEADLINE_EXPIRED"
        assert not orders and venue.submit_count == 0
        assert times[0] - saved["request"].packet.valid_until == timedelta(seconds=.622810)


@pytest.mark.parametrize("success", [True, False])
def test_pending_protection_settles_before_waiting_without_holding_writer(tmp_path, monkeypatch, success):
    with runtime(tmp_path, monkeypatch) as (r, c, venue, _, saved):
        model = c._model_run
        checked = []

        async def during_protection(request, *args, **kwargs):
            result = await model(request, *args, **kwargs)
            pending = asyncio.get_running_loop().create_future()
            r._scope_tick = pending

            async def finish_tick():
                try:
                    _, orders = saved_reply(c, saved)
                    assert not orders
                    # Acquiring a real second SQLite writer proves no transaction
                    # stayed open across the await. No data is changed.
                    with sqlite3.connect(c.engine.journal.path, timeout=.05) as db:
                        db.execute("BEGIN IMMEDIATE")
                        db.rollback()
                    checked.append(True)
                finally:
                    pending.set_result(success)

            saved["tick"] = asyncio.create_task(finish_tick())
            return result

        monkeypatch.setattr(c, "_model_run", during_protection)

        async def exercise():
            await step(r)
            await saved["tick"]

        asyncio.run(exercise())
        decision, orders = saved_reply(c, saved)
        assert checked == [True]
        assert venue.submit_count == int(success)
        assert len(orders) == int(success)
        assert decision["status"] == ("OPEN" if success else "HOLD")
        if not success:
            assert decision["blocker"] == "MIXED_RUNTIME_PROTECTION_TICK_INCOMPLETE"


def test_commit_time_still_consumes_native_deadline(tmp_path, monkeypatch):
    with runtime(tmp_path, monkeypatch) as (r, c, venue, _, saved):
        submit = portfolio_execution.submit

        async def delayed_commit(engine, intent, now, started):
            return await submit(engine, intent, now, started - engine.policy.process_timeout_seconds)

        monkeypatch.setattr(portfolio_execution, "submit", delayed_commit)
        asyncio.run(step(r))
        decision, orders = saved_reply(c, saved)
        assert decision["status"] == "REJECTED" and venue.submit_count == 0
        order, = orders
        assert order["attempted_at"] and order["active_play"] is None
        asyncio.run(step(r))
        assert venue.submit_count == 0


@pytest.mark.parametrize("update", [
    "above_limit", "missing_option", "missing_underlying", "regressed", "conflict",
    "unchanged", "improved", "stop_requested", "interrupted_protection",
])
def test_combined_boundary_rechecks_current_delivery_without_renewing_paid_choice(tmp_path, monkeypatch, update):
    from app.options.coordinator import DegenFrame

    with runtime(tmp_path, monkeypatch) as (r, c, venue, times, saved):
        model = c._model_run

        async def changed_market(request, *args, **kwargs):
            result = await model(request, *args, **kwargs)
            chosen = next(o for o in request.packet.opportunities
                          if o.candidate.candidate_id == result.plan.candidate_id)
            times[0] += timedelta(seconds=1)
            q = changed(chosen.quote, source_at=times[0], received_at=times[0])
            u = changed(chosen.underlying, source_at=times[0], received_at=times[0])
            if update == "above_limit":
                q = changed(q, bid=q.bid + 1, ask=q.ask + 1)
            elif update == "improved":
                q = changed(q, bid=q.bid - Decimal(".01"), ask=q.ask - Decimal(".01"))
            elif update == "regressed":
                q = changed(q, source_at=chosen.quote.source_at - timedelta(seconds=1))
            elif update == "conflict":
                q = changed(q, source_at=chosen.quote.source_at, ask_size=q.ask_size + 1)
            packet = PortfolioRuntimePacket(
                sequence=2, kind="MARKET", recorded_at=times[0],
                population_id=c.engine.limits.population_id,
                frame=DegenFrame(portfolio_version="portfolio-frame-v2",
                                 quotes=() if update == "missing_option" else (q,),
                                 underlyings=() if update == "missing_underlying" else (u,)),
            )
            Path(r.policy.feed_file).write_text(packet.model_dump_json())
            await r.tick()
            if update == "stop_requested":
                r.stop = asyncio.Event()
                r.stop.set()
            elif update == "interrupted_protection":
                r._scope_tick = asyncio.get_running_loop().create_future()
                r._scope_tick.set_result(False)
            return result

        monkeypatch.setattr(c, "_model_run", changed_market)
        asyncio.run(step(r))
        decision, orders = saved_reply(c, saved)
        admitted = update in {"unchanged", "improved"}
        assert decision["status"] == ("OPEN" if admitted else "HOLD"), decision.get("reason")
        assert venue.submit_count == len(orders) == int(admitted)
        if admitted or update in {"above_limit", "conflict", "regressed"}:
            assert decision["option_market_sequence"] == 2
        if update == "improved":
            assert venue.snapshot(times[0]).orders[0].limit_price < (
                saved["request"].packet.opportunities[0].candidate.admission.limit_price)
        if update == "regressed":
            assert decision["reason"] == "EVIDENCE_IDENTITY_OR_TIME_REGRESSION"
