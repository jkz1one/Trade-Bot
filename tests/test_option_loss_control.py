"""Native outcome-driven cooldown/lock, independent of entry source and global resume."""

import asyncio
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import intent_for, owned, quote_at, underlying_at

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution
from app.options.lifecycle import NativeLossPolicy
from app.options.models import OptionProposal

POLICY = NativeLossPolicy(max_consecutive_losses=2, cooldown_seconds=1800)


def ready(engine, venue, data, at):
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
    engine.assess(quote_at(data, at), underlying_at(data, at), now=at)


def trade(engine, venue, data, key, at, *, win=False):
    ready(engine, venue, data, at)
    q, u = quote_at(data, at), underlying_at(data, at)
    prepared = engine.prepare(key, data["proposal"], q, u, now=at)
    assert prepared["status"] == "PREPARED", prepared
    buy = intent_for(engine, prepared["client_id"])
    assert asyncio.run(engine.dispatch(buy.client_id, q, u, now=at)) == "OPEN"
    venue.fill(buy, buy.quantity, q, at, fill_id=key + "-buy")
    ready(engine, venue, data, at)
    close_quote = quote_at(data, at, bid="1.10", ask="1.15") if win else q
    result = engine.prepare(
        key + "-close",
        OptionProposal(
            action="CLOSE", contract=buy.instrument.contract, thesis="Close native risk fixture"
        ),
        close_quote,
        now=at,
    )
    sell = intent_for(engine, result["client_id"])
    assert asyncio.run(engine.dispatch(sell.client_id, close_quote, now=at)) == "OPEN"
    venue.fill(sell, sell.quantity, close_quote, at, fill_id=key + "-sell")
    ready(engine, venue, data, at)
    return buy


def attempt(engine, data, key, at):
    return engine.prepare(
        key, data["proposal"], quote_at(data, at), underlying_at(data, at), now=at
    )


def test_loss_starts_cooldown_on_recognition_and_retry_is_idempotent(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        trade(engine, venue, data, "first", NOW)
        recognized = NOW + timedelta(minutes=2)
        state = engine.refresh_loss_control(now=recognized)
        assert state["consecutive_losses"] == state["consumed_entries"] == 1
        assert datetime.fromisoformat(state["cooldown_until"]) == recognized + timedelta(minutes=30)
        assert state == engine.refresh_loss_control(now=recognized)
        result = attempt(engine, data, "blocked", recognized)
        assert result["status"] == "REJECTED" and "NATIVE_LOSS_COOLDOWN" in result["reason"]
        assert venue.submit_count == 2
        boundary = recognized + timedelta(minutes=30)
        ready(engine, venue, data, boundary)
        assert attempt(engine, data, "after", boundary)["status"] == "PREPARED"


def test_two_losses_lock_persists_after_cooldown_and_global_resume(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        trade(engine, venue, data, "first", NOW)
        engine.refresh_loss_control(now=NOW)
        later = NOW + timedelta(minutes=30)
        trade(engine, venue, data, "second", later)
        state = engine.refresh_loss_control(now=later)
        assert state["locked"] and state["consecutive_losses"] == 2
        after = later + timedelta(minutes=30)
        ready(engine, venue, data, after)
        with engine.journal.read() as db:
            revision = engine.journal.revision(db)
            before = db.execute("SELECT ledger_json FROM execution_control").fetchone()[0]
        engine.resume("Reviewed unrelated global halt", expected_revision=revision, now=after)
        result = attempt(engine, data, "third", after)
        assert result["status"] == "REJECTED" and "NATIVE_LOSS_LOCKED" in result["reason"]
        assert "COOLDOWN" not in result["reason"]
        with engine.journal.read() as db:
            assert db.execute("SELECT ledger_json FROM execution_control").fetchone()[0] == before
        assert venue.submit_count == 4
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, policy, venue, now=after) as reopened:
        assert reopened.journal.report(now=after)["loss_control"]["locked"]
        assert "NATIVE_LOSS_LOCKED" in attempt(reopened, data, "restart", after)["reason"]


def test_known_win_breaks_streak_without_refunding_loss_or_cash(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        trade(engine, venue, data, "first", NOW)
        engine.refresh_loss_control(now=NOW)
        later = NOW + timedelta(minutes=30)
        trade(engine, venue, data, "winner", later, win=True)
        state = engine.refresh_loss_control(now=later)
        assert state["consecutive_losses"] == 0 and not state["locked"]
        assert state["consumed_entries"] == 2
        assert not state["reasons"]
        with engine.journal.read() as db:
            records = db.execute(
                "SELECT record_json FROM execution_option_loss_outcomes"
            ).fetchall()
            assert len(records) == 2


def test_dispatch_rechecks_persisted_lock_before_worker(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        result = attempt(engine, data, "prepared", NOW)
        assert result["status"] == "PREPARED"
        # Simulates a newly persisted independent risk review before dispatch.
        with engine.journal.write() as db:
            db.execute(
                "UPDATE execution_option_loss_control SET state_json=json_set(state_json,'$.locked',json('true'),'$.consecutive_losses',2)"
            )
        assert (
            asyncio.run(
                engine.dispatch(result["client_id"], data["quote"], data["underlying"], now=NOW)
            )
            == "REJECTED"
        )
        assert venue.submit_count == 0
        with engine.journal.read() as db:
            assert db.execute("SELECT attempted_at FROM execution_orders").fetchone()[0] is None


def test_open_position_blocks_new_entry_but_hold_and_close_work(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        from test_option_execution import enter

        entry = enter(engine, venue, data)
        state = engine.refresh_loss_control(now=NOW)
        assert state["consumed_entries"] == 0
        assert state["reasons"] == ["NATIVE_LOSS_OUTCOME_PENDING"]
        assert attempt(engine, data, "another", NOW)["status"] == "REJECTED"
        assert (
            engine.prepare("hold", OptionProposal(action="HOLD", thesis="Wait"), now=NOW)["status"]
            == "HOLD"
        )
        close = engine.prepare(
            "close",
            OptionProposal(action="CLOSE", contract=entry.instrument.contract, thesis="Risk exit"),
            data["quote"],
            now=NOW,
        )
        assert close["status"] == "PREPARED"
        assert asyncio.run(engine.dispatch(close["client_id"], data["quote"], now=NOW)) == "OPEN"


def test_clock_policy_and_disabled_cohort_boundaries(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        with pytest.raises(ExecutionBlocked, match="CLOCK_REWOUND"):
            engine.refresh_loss_control(now=NOW - timedelta(seconds=1))
        path, limits, policy = engine.journal.path, engine.limits, engine.policy
    changed = policy.model_copy(
        update={"loss_control": NativeLossPolicy(max_consecutive_losses=1, cooldown_seconds=1800)}
    )
    with (
        pytest.raises((ValueError, ExecutionBlocked)),
        OptionExecution.open(path, limits, changed, venue, now=NOW),
    ):
        pass
    other = tmp_path / "other"
    other.mkdir()
    with owned(other) as (engine, venue, data):
        assert "loss_control" not in engine.policy.model_dump(mode="json")
        assert engine.journal.report(now=NOW)["loss_control"] is None
        with pytest.raises(ExecutionBlocked, match="NOT_ENROLLED"):
            engine.refresh_loss_control(now=NOW)
        assert attempt(engine, data, "normal", NOW)["status"] == "PREPARED"


@pytest.mark.parametrize(
    "values",
    [{"max_consecutive_losses": 3}, {"cooldown_seconds": 1799}, {"cooldown_seconds": True}],
)
def test_source_floor_and_ceiling_are_not_relaxed(values):
    with pytest.raises(ValidationError):
        NativeLossPolicy.model_validate(POLICY.model_dump() | values)


@pytest.mark.parametrize("unknown", [False, True])
def test_paid_management_costs_and_unknown_usage_cannot_clear_loss(tmp_path, monkeypatch, unknown):
    import json
    from decimal import Decimal

    from test_option_position_coordination import (
        enter_position,
        management_frame,
        model,
        owned_manager,
    )

    with owned_manager(tmp_path, loss_policy=POLICY) as (c, venue, times):
        entry = enter_position(c, venue, times, monkeypatch)
        model(monkeypatch, c, "MAINTAIN")
        assert asyncio.run(c.cycle(management_frame()))["status"] == "MAINTAIN"
        q = (
            management_frame()
            .quotes[0]
            .model_copy(update={"bid": Decimal("1.03"), "ask": Decimal("1.04")})
        )
        result = c.engine.prepare(
            "cost-exit",
            OptionProposal(
                action="CLOSE",
                contract=entry.instrument.contract,
                thesis="Close with small premium gain",
            ),
            q,
            now=times[0],
        )
        sell = intent_for(c.engine, result["client_id"])
        assert asyncio.run(c.engine.dispatch(sell.client_id, q, now=times[0])) == "OPEN"
        venue.fill(sell, sell.quantity, q, times[0], fill_id="paid-exit")
        assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
        if unknown:
            with c.engine.journal.write() as db:
                db.execute(
                    "UPDATE execution_model_calls SET cost=NULL WHERE source_key=?",
                    (entry.source_key,),
                )
        state = c.engine.refresh_loss_control(now=times[0])
        if unknown:
            assert state["consumed_entries"] == state["consecutive_losses"] == 0
            assert "NATIVE_LOSS_OUTCOME_PENDING" in state["reasons"]
        else:
            assert state["consecutive_losses"] == 1
            with c.engine.journal.read() as db:
                record = json.loads(
                    db.execute("SELECT record_json FROM execution_option_loss_outcomes").fetchone()[
                        0
                    ]
                )
            assert Decimal(record["exit_premium"]) > Decimal(record["entry_premium"])
            assert Decimal(record["net_after_known_execution_and_model_costs"]) < 0
            assert Decimal(record["known_model_cost"]) == Decimal(".00030")
            assert {call["role"] for call in record["model_calls"]} == {"ENTRY", "MANAGEMENT"}


def test_changed_consumed_record_fails_closed_without_partial_write(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        trade(engine, venue, data, "first", NOW)
        engine.refresh_loss_control(now=NOW)
        with engine.journal.write() as db:
            db.execute("UPDATE execution_option_loss_outcomes SET outcome_hash=?", ("f" * 64,))
        with engine.journal.read() as db:
            before = db.execute("SELECT state_json FROM execution_option_loss_control").fetchone()[
                0
            ]
        with pytest.raises(ExecutionBlocked, match="OUTCOME_CHANGED"):
            engine.refresh_loss_control(now=NOW + timedelta(seconds=1))
        with engine.journal.read() as db:
            assert (
                db.execute("SELECT state_json FROM execution_option_loss_control").fetchone()[0]
                == before
            )
        assert attempt(engine, data, "blocked", NOW)["status"] == "REJECTED"
        assert venue.submit_count == 2


def test_new_buy_rejection_and_unfilled_terminal_do_not_reset_streak(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        engine.refresh_loss_control(now=NOW)
        later = NOW + timedelta(minutes=30)
        ready(engine, venue, data, later)
        prepared = attempt(engine, data, "unfilled", later)
        q, u = quote_at(data, later), underlying_at(data, later)
        assert asyncio.run(engine.dispatch(prepared["client_id"], q, u, now=later)) == "OPEN"
        venue.record_terminal(prepared["client_id"], "CANCELED", later)
        ready(engine, venue, data, later)
        state = engine.refresh_loss_control(now=later)
        assert state["consecutive_losses"] == state["consumed_entries"] == 1
        assert not state["reasons"]


def test_entry_guard_automatically_consumes_loss_and_persists_block(tmp_path):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        result = attempt(engine, data, "auto-block", NOW)
        assert result["status"] == "REJECTED" and "NATIVE_LOSS_COOLDOWN" in result["reason"]
        state = engine.journal.report(now=NOW)["loss_control"]
        assert state["consecutive_losses"] == state["consumed_entries"] == 1
        assert venue.submit_count == 2


def test_expiry_loss_can_trigger_stricter_single_loss_lock(tmp_path):
    from test_option_execution import enter

    from app.options.lifecycle import OptionReceipt

    policy = NativeLossPolicy(max_consecutive_losses=1, cooldown_seconds=1800)
    with owned(tmp_path, loss_control=policy) as (engine, venue, data):
        entry = enter(engine, venue, data)
        at = entry.instrument.contract.expires_at
        venue.record_receipt(
            OptionReceipt(
                receipt_id="expiry",
                sequence=2,
                kind="EXPIRED_WORTHLESS",
                contract=entry.instrument.contract,
                quantity=entry.quantity,
                occurred_at=at,
                settlement_value="599",
                cash_change="0",
            )
        )
        assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
        state = engine.refresh_loss_control(now=at)
        assert state["locked"] and state["consecutive_losses"] == 1
        assert datetime.fromisoformat(state["cooldown_until"]) == at + timedelta(minutes=30)


def test_outcome_and_control_audit_commit_atomically(tmp_path, monkeypatch):
    with owned(tmp_path, loss_control=POLICY) as (engine, venue, data):
        trade(engine, venue, data, "loss", NOW)
        original = engine.journal.event

        def fail(db, now, kind, *args, **kwargs):
            if kind == "NATIVE_LOSS_OUTCOME_CONSUMED":
                raise RuntimeError("simulated audit write failure")
            return original(db, now, kind, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(engine.journal, "event", fail)
            with pytest.raises(RuntimeError, match="audit write"):
                engine.refresh_loss_control(now=NOW)
        with engine.journal.read() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM execution_option_loss_outcomes").fetchone()[0] == 0
            )
        state = engine.journal.report(now=NOW)["loss_control"]
        assert state["consumed_entries"] == state["consecutive_losses"] == 0
        assert engine.refresh_loss_control(now=NOW)["consecutive_losses"] == 1
