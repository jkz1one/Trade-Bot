"""Loss pauses precede paid entry calls without disabling owned management."""

import asyncio
from datetime import datetime, timedelta

import pytest
from test_degen_options import inventory
from test_option_admission import NOW
from test_option_execution import intent_for, owned
from test_option_loss_control import POLICY, ready, trade
from test_option_position_coordination import (
    enter_position,
    management_frame,
    model,
    owned_manager,
)

from app.execution.economics import CostPolicy
from app.execution.engine import ExecutionBlocked
from app.options.engine import EntryModelBlocked, OptionExecution
from app.options.lifecycle import NativeLossPolicy
from app.options.models import OptionProposal

COSTS = CostPolicy(total_budget="1", daily_budget=".1")


def counts(engine):
    with engine.journal.read() as db:
        return tuple(
            db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in (
                "execution_model_calls",
                "execution_orders",
                "execution_option_loss_outcomes",
            )
        )


def test_entry_call_recognizes_loss_before_cost_admission_and_persists_cooldown(tmp_path):
    with owned(tmp_path, loss_control=POLICY, cost_policy=COSTS) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        recognized = NOW + timedelta(minutes=2)
        with pytest.raises(EntryModelBlocked, match="NATIVE_LOSS_COOLDOWN"):
            engine.begin_model_attempt("unpaid", "a" * 64, now=recognized)
        state = engine.journal.report(now=recognized)
        assert not state["halted"]
        assert counts(engine) == (0, 2, 1)
        assert datetime.fromisoformat(
            state["loss_control"]["cooldown_until"]
        ) == recognized + timedelta(minutes=30)
        assert state["economics"]["unknown_calls"] == 0
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, policy, venue, now=recognized) as engine:
        boundary = recognized + timedelta(minutes=30)
        ready(engine, venue, data, boundary)
        engine.begin_model_attempt("allowed", "b" * 64, now=boundary)
        assert counts(engine) == (1, 2, 1)
        assert engine.journal.report(now=boundary)["economics"]["unknown_calls"] == 1


def test_threshold_lock_still_blocks_paid_call_after_cooldown(tmp_path):
    policy = NativeLossPolicy(max_consecutive_losses=1, cooldown_seconds=1800)
    with owned(tmp_path, loss_control=policy, cost_policy=COSTS) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        engine.refresh_loss_control(now=NOW)
        later = NOW + timedelta(minutes=30)
        ready(engine, venue, data, later)
        with pytest.raises(EntryModelBlocked, match="NATIVE_LOSS_LOCKED"):
            engine.begin_model_attempt("unpaid", "a" * 64, now=later)
        assert counts(engine) == (0, 2, 1)
        assert not engine.journal.report(now=later)["halted"]


def test_bad_loss_evidence_never_creates_a_model_attempt(tmp_path):
    with owned(tmp_path, loss_control=POLICY, cost_policy=COSTS) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        engine.refresh_loss_control(now=NOW)
        with engine.journal.write() as db:
            db.execute("UPDATE execution_option_loss_outcomes SET outcome_hash='bad'")
        before = engine.journal.path.read_bytes()
        with pytest.raises(ExecutionBlocked, match="NATIVE_LOSS_OUTCOME_CHANGED"):
            engine.begin_model_attempt("unpaid", "a" * 64, now=NOW)
        assert engine.journal.path.read_bytes() == before


def test_pause_audit_failure_rolls_back_risk_and_attempt(tmp_path, monkeypatch):
    with owned(tmp_path, loss_control=POLICY, cost_policy=COSTS) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        event = engine.journal.event

        def fail(db, at, kind, payload):
            if kind == "OPTION_ENTRY_MODEL_RISK_PAUSED":
                raise RuntimeError("fixture pause persistence failure")
            return event(db, at, kind, payload)

        before = engine.journal.path.read_bytes()
        monkeypatch.setattr(engine.journal, "event", fail)
        with pytest.raises(RuntimeError, match="pause persistence"):
            engine.begin_model_attempt("unpaid", "a" * 64, now=NOW)
        assert engine.journal.path.read_bytes() == before
        assert counts(engine) == (0, 2, 0)


def test_unenrolled_population_keeps_existing_model_admission(tmp_path):
    with owned(tmp_path, cost_policy=COSTS) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        engine.begin_model_attempt("paid", "a" * 64, now=NOW)
        with engine.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 1
        assert engine.journal.report(now=NOW)["loss_control"] is None


def test_coordinator_pause_never_starts_worker_or_creates_global_halt(tmp_path, monkeypatch):
    with owned_manager(tmp_path, loss_policy=POLICY) as (c, venue, times):
        entry = enter_position(c, venue, times, monkeypatch)
        f = management_frame().model_copy(update={"inventories": (inventory(at=times[0]),)})
        q = f.quotes[0]
        assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
        c.engine.assess(q, f.underlyings[0], now=times[0])
        prepared = c.engine.prepare(
            "close",
            OptionProposal(
                action="CLOSE", contract=entry.instrument.contract, thesis="Close fixture loss"
            ),
            q,
            now=times[0],
        )
        sell = intent_for(c.engine, prepared["client_id"])
        assert asyncio.run(c.engine.dispatch(sell.client_id, q, now=times[0])) == "OPEN"
        venue.fill(sell, sell.quantity, q, times[0], fill_id="close-loss")

        async def forbidden(*args, **kwargs):
            raise AssertionError("Blocked entry must not start model worker")

        monkeypatch.setattr(c, "_model_run", forbidden)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "HOLD", result
        assert result["reason"] == "ENTRY_MODEL_RISK_PAUSE", result
        assert result["blocker"] == "NATIVE_LOSS_COOLDOWN"
        assert counts(c.engine) == (1, 2, 1)
        assert not c.engine.journal.report(now=times[0])["halted"]
        before = c.engine.journal.report(now=times[0])
        with c.engine.journal.read() as db:
            revision = c.engine.journal.revision(db)
        assert asyncio.run(c.cycle(f)) == result
        after = c.engine.journal.report(now=times[0])
        assert after["loss_control"] == before["loss_control"]
        assert after["economics"] == before["economics"]
        assert counts(c.engine) == (1, 2, 1)
        with c.engine.journal.read() as db:
            assert c.engine.journal.revision(db) == revision


@pytest.mark.parametrize("action", ["MAINTAIN", "EXIT_ALL"])
def test_owned_management_retains_paid_admission_despite_pending_entry_outcome(
    tmp_path, monkeypatch, action
):
    with owned_manager(tmp_path, loss_policy=POLICY) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        assert c.engine.refresh_loss_control(now=times[0])["reasons"] == [
            "NATIVE_LOSS_OUTCOME_PENDING"
        ]
        calls = model(monkeypatch, c, action)
        result = asyncio.run(c.cycle(management_frame()))
        assert result["status"] == ("MAINTAIN" if action == "MAINTAIN" else "OPEN"), result
        assert len(calls) == 1
        with c.engine.journal.read() as db:
            rows = db.execute("SELECT cost FROM execution_model_calls").fetchall()
        assert len(rows) == 2 and all(row[0] is not None for row in rows)
