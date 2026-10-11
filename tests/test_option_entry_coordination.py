"""Full-plan durable entry, original dispatch authority and independent PAPER exits."""

import asyncio
import json
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame, policies
from test_option_entry_reasoning import packet_for, plan_for
from test_option_execution import configuration, intent_for, ledger

from app.execution.economics import CostPolicy, UsageEvidence
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.options import entry_judgment
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.lifecycle import OptionIntent, OptionPosition
from app.options.venue import DurableOptionVenue


@contextmanager
def owned_entry(path, right="CALL"):
    data, limits, policy = configuration(
        right, cost_policy=CostPolicy(total_budget="1", daily_budget=".1")
    )
    venue = DurableOptionVenue(path / "venue.db", limits=limits, capital=policy.capital)
    key = path / "model.key"
    key.write_text("fixture-only\n")
    key.chmod(0o600)
    times = [AT]
    with OptionExecution.open(
        path / "options.db", limits, policy, venue, now=AT, create=True
    ) as engine:
        assert engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        engine.assess(None, None, now=AT)
        setup, selection = policies()
        c = DegenCoordinator(
            engine,
            setup,
            selection,
            create=True,
            clock=lambda: times[0],
            judgment_limits=JudgmentLimits(),
            key_file=key,
            entry_policy=packet_for(right).policy,
        )
        yield c, venue, data, times


def fake_model(monkeypatch, c, *, action="ENTER", changes=None, after=None):
    calls = []

    async def run(request, key):
        assert key == "fixture-only"
        with c.engine.journal.read() as db:
            row = db.execute("SELECT * FROM execution_model_calls").fetchone()
            assert row["cost"] is None and row["packet_hash"] == fingerprint(
                entry_judgment.request_content(request)
            )
            evidence = json.loads(
                db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0]
            )
            assert evidence["entry_request"] == request.model_dump(mode="json")
        calls.append(request)
        result = entry_judgment.result_for(
            request,
            plan=entry_judgment.hold(request.packet)
            if action == "HOLD"
            else plan_for(request.packet),
            count=1000,
            usage=UsageEvidence(
                request_id="entry-response",
                model=request.configuration.costs.model,
                input_tokens=1000,
                output_tokens=100,
            ),
        )
        if changes:
            result = changes(request, result)
        if after:
            after(request, result)
        return result

    monkeypatch.setattr(entry_judgment, "run_entry_process", run)
    return calls


def cycle(c, right="CALL"):
    return asyncio.run(c.cycle(frame(right)))


def filled(c, venue, result, right="CALL", quantity=None):
    intent = intent_for(c.engine, result["client_id"])
    venue.fill(
        intent, quantity or intent.quantity, frame(right).quotes[0], AT, fill_id="entry-fill"
    )
    assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
    return intent


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_full_plan_cost_and_protection_survive_fill_restart_and_target_exit(
    tmp_path, monkeypatch, right
):
    with owned_entry(tmp_path, right) as (c, venue, _, _times):
        calls = fake_model(monkeypatch, c)
        result = cycle(c, right)
        assert result["status"] == "OPEN", result
        intent = filled(c, venue, result, right)
        expected = plan_for(calls[0].packet)
        assert intent.entry_protection.plan_hash == fingerprint(expected)
        assert intent.exit_at == intent.order_expires_at == AT + timedelta(seconds=600)
        assert ledger(c.engine).position.entry_protection == intent.entry_protection
        assert cycle(c, right) == result and len(calls) == venue.submit_count == 1
        with c.engine.journal.read() as db:
            model = db.execute("SELECT * FROM execution_model_calls").fetchone()
            assert Decimal(model["cost"]) == Decimal(".00015")
            assert model["decision_hash"] == fingerprint(expected)
            approval = json.loads(
                db.execute("SELECT approval_json FROM execution_orders").fetchone()[0]
            )
            assert approval["entry_result"]["plan"] == expected.model_dump(mode="json")
        saved = (
            c.engine.limits,
            c.engine.policy,
            c.policy,
            c.selection,
            c.judgment_limits,
            c.key_file,
            c.entry_policy,
        )
    limits, policy, setup, selection, judgment_limits, key_file, entry_policy = saved
    with OptionExecution.open(tmp_path / "options.db", limits, policy, venue, now=AT) as engine:
        reopened = DegenCoordinator(
            engine,
            setup,
            selection,
            clock=lambda: AT,
            judgment_limits=judgment_limits,
            key_file=key_file,
            entry_policy=entry_policy,
        )
        assert engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        q, u = frame(right).quotes[0], frame(right).underlyings[0]
        target = expected.underlying_target
        # Crossing only the optimistic spread side must not trigger a target.
        before = u.model_copy(
            update={"bid": target - Decimal(".01"), "ask": target + Decimal(".01")}
        )
        assert engine.assess(q, before, now=AT)["status"] == "HEALTHY"
        hit = u.model_copy(update={"bid": target, "ask": target})
        managed = asyncio.run(reopened.supervise((q,), (hit,)))
        assert managed["status"] == "OPEN" and managed["exit_reason"] == "UNDERLYING_TARGET"
        assert len(calls) == 1 and venue.submit_count == 2
        # Reconciliation cannot erase a sticky exit even if price retraces.
        assert engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        assert engine.assess(q, u, now=AT)["exit_reason"] == "UNDERLYING_TARGET"


@pytest.mark.parametrize(
    "damage", ["hold", "unknown", "foreign", "late", "invalid", "count", "error"]
)
def test_unusable_model_results_never_order_and_cost_is_not_lost(tmp_path, monkeypatch, damage):
    with owned_entry(tmp_path) as (c, venue, _, times):

        def changes(r, result):
            if damage == "unknown":
                return result.model_copy(
                    update={
                        "usage": None,
                        "error": "ValueError",
                        "plan": entry_judgment.hold(r.packet),
                    }
                )
            if damage == "foreign":
                return result.model_copy(update={"request_id": "f" * 32})
            if damage == "invalid":
                return result.model_copy(
                    update={
                        "plan": result.plan.model_copy(update={"underlying_target": Decimal(599)})
                    }
                )
            if damage == "count":
                return result.model_copy(update={"counted_input_tokens": 999})
            if damage == "error":
                return result.model_copy(
                    update={"error": "ValueError", "plan": entry_judgment.hold(r.packet)}
                )
            return result

        fake_model(
            monkeypatch,
            c,
            action="HOLD" if damage == "hold" else "ENTER",
            changes=changes,
            after=(lambda r, v: times.__setitem__(0, AT + timedelta(seconds=6)))
            if damage == "late"
            else None,
        )
        result = cycle(c)
        assert result["status"] == "HOLD" and venue.submit_count == 0
        with c.engine.journal.read() as db:
            row = db.execute("SELECT * FROM execution_model_calls").fetchone()
            assert (row["cost"] is None) == (damage in {"unknown", "foreign"})
            if row["cost"] is not None:
                assert Decimal(row["cost"]) == Decimal(".00015")
            if damage not in {"hold", "late", "error"}:
                assert db.execute("SELECT halted FROM execution_control").fetchone()[0]


@pytest.mark.parametrize("damage", ["target", "condition", "horizon", "protection"])
def test_dispatch_rechecks_full_plan_before_any_attempt(tmp_path, monkeypatch, damage):
    with owned_entry(tmp_path) as (c, venue, _, _):

        def changes(r, result):
            if damage == "condition":
                return result.model_copy(
                    update={
                        "plan": plan_for(r.packet, condition="ABOVE", underlying_trigger="600.5")
                    }
                )
            if damage == "horizon":
                return result.model_copy(update={"plan": plan_for(r.packet, horizon_seconds=1)})
            return result

        fake_model(monkeypatch, c, changes=changes)
        dispatch = c.engine.dispatch

        async def altered(client_id, q, u, *, now):
            if damage == "target":
                u = u.model_copy(update={"bid": Decimal(602), "ask": Decimal(602)})
            elif damage == "condition":
                u = u.model_copy(update={"bid": Decimal("600.4"), "ask": Decimal("600.5")})
            elif damage == "horizon":
                now += timedelta(seconds=1)
            else:
                with c.engine.journal.write() as db:
                    raw = json.loads(
                        db.execute(
                            "SELECT intent_json FROM execution_orders WHERE client_id=?",
                            (client_id,),
                        ).fetchone()[0]
                    )
                    raw.pop("entry_protection")
                    db.execute(
                        "UPDATE execution_orders SET intent_json=? WHERE client_id=?",
                        (json.dumps(raw), client_id),
                    )
            return await dispatch(client_id, q, u, now=now)

        monkeypatch.setattr(c.engine, "dispatch", altered)
        result = cycle(c)
        assert result["status"] == "REJECTED", result
        assert venue.submit_count == 0
        with c.engine.journal.read() as db:
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            assert row["attempted_at"] is None and row["active_lock"] is None


def test_time_exit_without_quotes_is_retained_and_unfilled_entry_cannot_outlive_horizon(
    tmp_path, monkeypatch
):
    with owned_entry(tmp_path) as (c, venue, _, times):
        fake_model(monkeypatch, c)
        result = cycle(c)
        intent = filled(c, venue, result, quantity=1)
        times[0] = intent.exit_at
        assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
        assessed = c.engine.assess(None, None, now=times[0])
        assert assessed["status"] == "BLOCKED" and assessed["exit_reason"] == "TIME_EXIT"
        assert ledger(c.engine).position.exit_required_at == intent.exit_at
        with pytest.raises(ValueError, match="lifetime"):
            venue.fill(intent, 1, frame().quotes[0], intent.exit_at, fill_id="late")
        # An unresolved entry remains a blocker; no cancel or replacement is invented.
        assert venue.submit_count == 1


def test_interruption_retains_request_unknown_cost_and_never_replays(tmp_path, monkeypatch):
    with owned_entry(tmp_path) as (c, venue, _, _):

        async def interrupted(request, key):
            raise asyncio.CancelledError()

        monkeypatch.setattr(entry_judgment, "run_entry_process", interrupted)
        with pytest.raises(asyncio.CancelledError):
            cycle(c)
        again = cycle(c)
        assert again["reason"] == "DEGEN_CYCLE_INTERRUPTED" and venue.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None
            evidence = json.loads(
                db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0]
            )
            assert "entry_request" in evidence


def test_frozen_selector_cannot_silently_become_entry_reasoner(tmp_path):
    from test_option_judgment import owned_model

    with owned_model(tmp_path) as (c, venue, _, _):
        saved = (
            c.engine.limits,
            c.engine.policy,
            c.policy,
            c.selection,
            c.judgment_limits,
            c.key_file,
        )
    limits, policy, setup, selection, judgment_limits, key_file = saved
    with (
        OptionExecution.open(tmp_path / "options.db", limits, policy, venue, now=AT) as engine,
        pytest.raises(ExecutionBlocked, match="FROZEN_DEGEN"),
    ):
        DegenCoordinator(
            engine,
            setup,
            selection,
            clock=lambda: AT,
            judgment_limits=judgment_limits,
            key_file=key_file,
            entry_policy=packet_for().policy,
        )


def test_new_enrollment_rejects_proposal_only_entry(tmp_path):
    with owned_entry(tmp_path) as (c, _, data, _):
        result = c.engine.prepare(
            "bypass", data["proposal"], data["quote"], data["underlying"], now=AT
        )
        assert result["status"] == "REJECTED" and result["reason"] == "FULL_ENTRY_PLAN_REQUIRED"


def test_legacy_records_keep_exact_serialized_shape(tmp_path):
    from test_option_execution import enter, owned

    with owned(tmp_path) as (engine, venue, data):
        intent = enter(engine, venue, data)
        position = ledger(engine).position
        assert "entry_protection" not in intent.model_dump(mode="json")
        assert "entry_protection" not in position.model_dump(mode="json")
        assert OptionIntent.model_validate_json(intent.model_dump_json()) == intent
        assert OptionPosition.model_validate_json(position.model_dump_json()) == position


@pytest.mark.parametrize("damage", ["receipt", "cost", "snapshot"])
def test_lost_receipt_or_changed_protection_cannot_gain_authority(tmp_path, monkeypatch, damage):
    with owned_entry(tmp_path) as (c, venue, _, _):
        fake_model(monkeypatch, c)
        if damage == "snapshot":
            result = cycle(c)
            filled(c, venue, result)
            snap = venue.snapshot(AT)
            bad = snap.model_copy(
                update={
                    "snapshot_id": "changed-protection",
                    "position": snap.position.model_copy(update={"entry_protection": None}),
                }
            )
            rejected = c.engine.reconcile(bad, now=AT)
            assert not rejected["reconciled"]
            assert "OPTION_POSITION_TERMS_MISMATCH" in rejected["issues"]
        else:
            dispatch = c.engine.dispatch

            async def altered(client_id, q, u, *, now):
                with c.engine.journal.write() as db:
                    if damage == "receipt":
                        row = db.execute(
                            "SELECT cycle_key,result_json FROM execution_option_opportunities"
                        ).fetchone()
                        evidence = json.loads(row[1])
                        evidence.pop("entry_result")
                        db.execute(
                            "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                            (json.dumps(evidence), row[0]),
                        )
                    else:
                        db.execute("UPDATE execution_model_calls SET cost=NULL")
                return await dispatch(client_id, q, u, now=now)

            monkeypatch.setattr(c.engine, "dispatch", altered)
            result = cycle(c)
            assert result["status"] == "REJECTED" and venue.submit_count == 0


def test_partial_fills_keep_same_plan_and_target_blocks_additional_authority(tmp_path, monkeypatch):
    with owned_entry(tmp_path) as (c, venue, _, _):
        calls = fake_model(monkeypatch, c)
        result = cycle(c)
        intent = filled(c, venue, result, quantity=1)
        q, u = frame().quotes[0], frame().underlyings[0]
        hit = u.model_copy(update={"bid": Decimal(602), "ask": Decimal(602)})
        blocked = asyncio.run(c.supervise((q,), (hit,)))
        assert blocked["status"] == "EXIT_BLOCKED"
        assert ledger(c.engine).position.exit_reason == "UNDERLYING_TARGET"
        venue.fill(intent, 1, q, AT, fill_id="second-partial")
        assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        position = ledger(c.engine).position
        assert position.quantity == 2 and position.entry_protection == intent.entry_protection
        assert position.exit_reason == "UNDERLYING_TARGET"
        assert cycle(c) == result and len(calls) == venue.submit_count == 1
