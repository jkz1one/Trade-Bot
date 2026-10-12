"""Durable opt-in management costs, atomic consumption and independent protection."""

import asyncio
import json
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame, policies
from test_option_entry_coordination import fake_model, filled
from test_option_entry_reasoning import packet_for
from test_option_execution import configuration, intent_for, ledger

from app.execution.economics import CostPolicy, UsageEvidence
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.options import position_judgment as judgment
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.position_coordination import apply_position_plan
from app.options.position_reasoning import PositionPlan, PositionReasoningPolicy
from app.options.venue import DurableOptionVenue

D = Decimal
MANAGE_AT = AT + timedelta(minutes=5)


@contextmanager
def owned_manager(path, right="CALL", *, costs=None):
    _, limits, policy = configuration(
        right, cost_policy=costs or CostPolicy(total_budget="1", daily_budget=".1")
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
            position_policy=PositionReasoningPolicy(max_lease_seconds=5),
        )
        yield c, venue, times


def management_frame(right="CALL", at=MANAGE_AT):
    f = frame(right)
    h = f.histories[0]
    last = h.bars[-1]
    new = last.model_copy(
        update={"begins_at": AT, "open": last.close, "low": last.close, "high": last.close}
    )
    return f.model_copy(
        update={
            "histories": (
                h.model_copy(update={"source_at": at, "received_at": at, "bars": (*h.bars, new)}),
            ),
            "quotes": tuple(
                q.model_copy(update={"source_at": at, "received_at": at}) for q in f.quotes
            ),
            "underlyings": tuple(
                u.model_copy(update={"source_at": at, "received_at": at}) for u in f.underlyings
            ),
        }
    )


def enter_position(c, venue, times, monkeypatch, right="CALL", quantity=None):
    fake_model(monkeypatch, c)
    result = asyncio.run(c.cycle(frame(right)))
    assert result["status"] == "OPEN", result
    intent = filled(c, venue, result, right, quantity)
    times[0] = MANAGE_AT
    return intent


def model(monkeypatch, c, action="TIGHTEN", *, after=None, changes=None):
    calls = []

    async def run(request, key):
        assert key == "fixture-only"
        with c.engine.journal.read() as db:
            stored = db.execute(
                "SELECT * FROM execution_model_calls ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            assert stored["cost"] is None and stored["packet_hash"] == fingerprint(
                judgment.request_content(request)
            )
        p = request.packet
        plan = PositionPlan(
            decision_id=p.decision_id,
            packet_hash=fingerprint(p),
            entry_client_id=p.position.entry_client_id,
            position_revision=p.position_revision,
            action=action,
            underlying_invalidation=("600.2" if p.position.contract.right == "CALL" else "599.8")
            if action == "TIGHTEN"
            else None,
            evidence_ids=(p.evidence_ids[0], p.evidence_ids[5]),
            thesis="Reassess held thesis",
            change_since_entry="Completed context changed",
            uncertainty="No guaranteed fill or outcome",
        )
        result = judgment.result_for(
            request,
            plan=plan,
            count=1000,
            usage=UsageEvidence(
                request_id="position-receipt",
                model=request.configuration.costs.model,
                input_tokens=1000,
                output_tokens=100,
            ),
        )
        if changes:
            result = changes(request, result)
        calls.append((request, result))
        if after:
            await after(request, result)
        return result

    monkeypatch.setattr(judgment, "run_position_process", run)
    return calls


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_native_management_pays_once_consumes_once_and_preserves_protection(
    tmp_path, monkeypatch, right, action
):
    with owned_manager(tmp_path, right) as (c, venue, times):
        entry = enter_position(c, venue, times, monkeypatch, right)
        original = ledger(c.engine).position
        calls = model(monkeypatch, c, action)
        f = management_frame(right)
        result = asyncio.run(c.cycle(f))
        assert (
            result["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), result
        assert len(calls) == 1
        assert asyncio.run(c.cycle(f)) == result and len(calls) == 1
        request, receipt = calls[0]
        applied = apply_position_plan(
            c, result["cycle_key"], request, receipt, f.quotes[0], f.underlyings[0], now=times[0]
        )
        assert applied == result["position_action"]
        p = ledger(c.engine).position
        assert p.original_underlying_invalidation == original.original_underlying_invalidation
        assert p.exit_at == original.exit_at and p.entry_protection == original.entry_protection
        with c.engine.journal.read() as db:
            costs = [D(r[0]) for r in db.execute("SELECT cost FROM execution_model_calls")]
            assert costs == [D(".00015"), D(".00015")]
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM execution_events WHERE kind='OPTION_POSITION_PLAN_CONSUMED'"
                ).fetchone()[0]
                == 1
            )
        if action == "TIGHTEN":
            assert p.tightened_underlying_invalidation == receipt.plan.underlying_invalidation
        if action == "EXIT_ALL":
            sell = intent_for(c.engine, result["client_id"])
            assert (
                sell.quantity == entry.quantity
                and sell.position_protection.plan_hash == fingerprint(receipt.plan)
            )
            venue.fill(sell, sell.quantity, f.quotes[0], times[0], fill_id="managed-exit")
            assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
            assert ledger(c.engine).position is None and venue.submit_count == 2
        else:
            assert venue.submit_count == 1


@pytest.mark.parametrize(
    "damage", ["missing", "foreign_model", "foreign_packet", "late", "count", "error"]
)
def test_failed_management_keeps_cost_or_uncertainty_without_action(tmp_path, monkeypatch, damage):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        original = ledger(c.engine).position

        def change(request, result):
            if damage == "missing":
                return result.model_copy(
                    update={
                        "plan": judgment.maintain(request.packet),
                        "error": "TimeoutError",
                        "usage": None,
                    }
                )
            if damage == "foreign_model":
                return result.model_copy(
                    update={"usage": result.usage.model_copy(update={"model": "foreign"})}
                )
            if damage == "foreign_packet":
                return result.model_copy(update={"packet_hash": "f" * 64})
            if damage == "count":
                return result.model_copy(update={"counted_input_tokens": 999})
            if damage == "error":
                return result.model_copy(
                    update={"plan": judgment.maintain(request.packet), "error": "ValueError"}
                )
            return result

        async def after(request, result):
            if damage == "late":
                times[0] += timedelta(seconds=6)

        calls = model(monkeypatch, c, changes=change, after=after)
        result = asyncio.run(c.cycle(management_frame()))
        assert len(calls) == 1 and venue.submit_count == 1 and result["status"] == "HELD", result
        assert (
            ledger(c.engine).position.tightened_underlying_invalidation
            == original.tightened_underlying_invalidation
        )
        with c.engine.journal.read() as db:
            row = db.execute(
                "SELECT cost FROM execution_model_calls ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if damage in {"missing", "foreign_model", "foreign_packet"}:
                assert row[0] is None
            else:
                assert D(row[0]) == D(".00015")
            assert not db.execute(
                "SELECT 1 FROM execution_events WHERE kind='OPTION_POSITION_PLAN_CONSUMED'"
            ).fetchone()
        if damage != "late":
            assert asyncio.run(c.cycle(management_frame())) == result


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_independent_exit_during_model_call_wins_and_usage_is_kept(tmp_path, monkeypatch, action):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        f = management_frame()

        async def target(request, result):
            u = f.underlyings[0].model_copy(update={"bid": D(602), "ask": D(602)})
            exit_result = await c.supervise(f.quotes, (u,))
            assert exit_result["status"] == "OPEN", exit_result

        calls = model(monkeypatch, c, action, after=target)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "MANDATORY_EXIT", result
        assert len(calls) == 1 and venue.submit_count == 2
        assert ledger(c.engine).position.exit_reason == "UNDERLYING_TARGET"
        with c.engine.journal.read() as db:
            sell = json.loads(
                db.execute(
                    "SELECT approval_json FROM execution_orders WHERE json_extract(intent_json,'$.side')='SELL'"
                ).fetchone()[0]
            )
            assert sell["origin"] == "PROTECTIVE"
            assert D(
                db.execute(
                    "SELECT cost FROM execution_model_calls ORDER BY rowid DESC LIMIT 1"
                ).fetchone()[0]
            ) == D(".00015")


@pytest.mark.parametrize("damage", ["tightened", "halt", "pending", "quote"])
def test_changed_state_during_reasoning_cannot_use_old_approval(tmp_path, monkeypatch, damage):
    from app.options.models import OptionProposal

    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        f = management_frame()

        async def changed(request, result):
            if damage == "tightened":
                c.engine.tighten_invalidation("600.4", f.quotes[0], f.underlyings[0], now=times[0])
            elif damage == "halt":
                c._model_halt("OPERATOR_HALT", times[0])
            elif damage == "pending":
                c.engine.prepare(
                    "external-reviewed-close",
                    OptionProposal(
                        action="CLOSE",
                        contract=request.packet.position.contract,
                        thesis="Owned close",
                    ),
                    f.quotes[0],
                    now=times[0],
                )
            else:
                await c.supervise((), ())

        model(monkeypatch, c, after=changed)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "REJECTED", result
        assert venue.submit_count == 1
        assert ledger(c.engine).position.tightened_underlying_invalidation == D(
            "600.4" if damage == "tightened" else "600"
        )


@pytest.mark.parametrize("action", ["TIGHTEN", "EXIT_ALL"])
def test_consumption_failure_rolls_back_mutation_and_close_preparation(
    tmp_path, monkeypatch, action
):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        model(monkeypatch, c, action)
        original = c.engine.journal.event

        def failed(db, at, kind, *args, **kwargs):
            if kind == "OPTION_POSITION_PLAN_CONSUMED":
                raise RuntimeError("fixture interruption")
            return original(db, at, kind, *args, **kwargs)

        monkeypatch.setattr(c.engine.journal, "event", failed)
        result = asyncio.run(c.cycle(management_frame()))
        assert result["reason"] == "DEGEN_CYCLE_FAILED" and venue.submit_count == 1
        assert ledger(c.engine).position.tightened_underlying_invalidation == D(600)
        with c.engine.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 1
            assert not db.execute(
                "SELECT 1 FROM execution_option_decisions WHERE source_key=?",
                (result["cycle_key"],),
            ).fetchone()
            assert D(
                db.execute(
                    "SELECT cost FROM execution_model_calls ORDER BY rowid DESC LIMIT 1"
                ).fetchone()[0]
            ) == D(".00015")


def test_cancellation_retains_unknown_attempt_and_does_not_retry(tmp_path, monkeypatch):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        calls = []

        async def interrupted(request, key):
            calls.append(request)
            raise asyncio.CancelledError

        monkeypatch.setattr(judgment, "run_position_process", interrupted)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(c.cycle(management_frame()))
        assert asyncio.run(c.cycle(management_frame()))["reason"] == "DEGEN_CYCLE_INTERRUPTED"
        assert len(calls) == venue.submit_count == 1
        report = c.engine.journal.report(now=times[0])
        assert report["halted"] and report["economics"]["unknown_calls"] == 1


def test_restart_preserves_applied_stop_and_never_repeats_call(tmp_path, monkeypatch):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        calls = model(monkeypatch, c)
        result = asyncio.run(c.cycle(management_frame()))
        saved = (
            c.engine.limits,
            c.engine.policy,
            c.policy,
            c.selection,
            c.judgment_limits,
            c.key_file,
            c.entry_policy,
            c.position_policy,
        )
    limits, policy, setup, selection, judgment_limits, key, entry_policy, position_policy = saved
    with OptionExecution.open(
        tmp_path / "options.db", limits, policy, venue, now=times[0]
    ) as engine:
        c = DegenCoordinator(
            engine,
            setup,
            selection,
            clock=lambda: times[0],
            judgment_limits=judgment_limits,
            key_file=key,
            entry_policy=entry_policy,
            position_policy=position_policy,
        )
        assert asyncio.run(c.cycle(management_frame())) == result and len(calls) == 1
        assert engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
        assert ledger(engine).position.tightened_underlying_invalidation == D("600.2")
        from app.options.observer import OptionObserver

        observed = OptionObserver(
            engine.journal.path, c.engine.limits.population_id, clock=lambda: times[0]
        ).report()
        assert observed["status"] == "OK", observed


@pytest.mark.parametrize("damage", ["strip", "plan", "cost", "consumption", "mandatory"])
def test_native_dispatch_rechecks_complete_bound_receipt(tmp_path, monkeypatch, damage):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        model(monkeypatch, c, "EXIT_ALL")
        dispatch = c.engine.dispatch

        async def changed(client, quote, underlying, *, now):
            with c.engine.journal.write() as db:
                row = db.execute(
                    "SELECT approval_json FROM execution_orders WHERE client_id=?", (client,)
                ).fetchone()
                approval = json.loads(row[0])
                if damage == "strip":
                    for field in ("position_request", "position_result", "origin"):
                        approval.pop(field)
                elif damage == "plan":
                    approval["position_result"]["plan"]["thesis"] = "changed"
                elif damage == "cost":
                    db.execute(
                        "UPDATE execution_model_calls SET cost=NULL WHERE source_key=?",
                        ("degen:" + str(int(times[0].timestamp()) // 300),),
                    )
                elif damage == "consumption":
                    db.execute(
                        "DELETE FROM execution_option_decisions WHERE source_key=?",
                        ("degen:" + str(int(times[0].timestamp()) // 300),),
                    )
                db.execute(
                    "UPDATE execution_orders SET approval_json=? WHERE client_id=?",
                    (json.dumps(approval), client),
                )
            if damage == "mandatory":
                underlying = underlying.model_copy(update={"bid": D(602), "ask": D(602)})
            return await dispatch(client, quote, underlying, now=now)

        monkeypatch.setattr(c.engine, "dispatch", changed)
        result = asyncio.run(c.cycle(management_frame()))
        assert result["status"] == "REJECTED", result
        assert venue.submit_count == 1
        if damage == "mandatory":
            assert ledger(c.engine).position.exit_reason == "UNDERLYING_TARGET"


def test_reserved_call_budget_blocks_before_management_child(tmp_path, monkeypatch):
    with owned_manager(tmp_path, costs=CostPolicy(total_budget="1", daily_budget=".01")) as (
        c,
        venue,
        times,
    ):
        enter_position(c, venue, times, monkeypatch)
        calls = model(monkeypatch, c)
        result = asyncio.run(c.cycle(management_frame()))
        assert result["reason"] == "OPTION_MODEL_ADMISSION_BLOCKED", result
        assert calls == [] and venue.submit_count == 1
        assert c.engine.journal.report(now=times[0])["economics"]["unknown_calls"] == 0


def test_partially_filled_entry_cannot_start_management(tmp_path, monkeypatch):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch, quantity=1)
        calls = model(monkeypatch, c)
        result = asyncio.run(c.cycle(management_frame()))
        assert result["reason"] == "POSITION_PREFLIGHT_UNAVAILABLE", result
        assert calls == [] and venue.submit_count == 1


def test_management_cannot_be_added_to_existing_entry_cohort(tmp_path):
    from test_option_entry_coordination import owned_entry

    with owned_entry(tmp_path) as (c, venue, _, times):
        saved = (
            c.engine.limits,
            c.engine.policy,
            c.policy,
            c.selection,
            c.judgment_limits,
            c.key_file,
            c.entry_policy,
        )
    limits, policy, setup, selection, judgment_limits, key, entry_policy = saved
    with (
        OptionExecution.open(
            tmp_path / "options.db", limits, policy, venue, now=times[0]
        ) as engine,
        pytest.raises(ExecutionBlocked, match="FROZEN_DEGEN"),
    ):
        DegenCoordinator(
            engine,
            setup,
            selection,
            clock=lambda: times[0],
            judgment_limits=judgment_limits,
            key_file=key,
            entry_policy=entry_policy,
            position_policy=PositionReasoningPolicy(max_lease_seconds=5),
        )


def test_consumed_revision_cannot_rebind_to_second_source_or_changed_plan(tmp_path, monkeypatch):
    with owned_manager(tmp_path) as (c, venue, times):
        enter_position(c, venue, times, monkeypatch)
        calls = model(monkeypatch, c)
        f = management_frame()
        result = asyncio.run(c.cycle(f))
        request, receipt = calls[0]
        with pytest.raises(ExecutionBlocked, match="REVISION_ALREADY_CONSUMED"):
            apply_position_plan(
                c, "different-source", request, receipt, f.quotes[0], f.underlyings[0], now=times[0]
            )
        changed = receipt.model_copy(
            update={"plan": receipt.plan.model_copy(update={"underlying_invalidation": D("600.3")})}
        )
        with pytest.raises(ExecutionBlocked, match="IDENTITY_CONFLICT"):
            apply_position_plan(
                c,
                result["cycle_key"],
                request,
                changed,
                f.quotes[0],
                f.underlyings[0],
                now=times[0],
            )
        assert ledger(c.engine).position.tightened_underlying_invalidation == D("600.2")
