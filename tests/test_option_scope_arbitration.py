"""One deterministic native owner chooses among Scope, Degen and Swing."""

import asyncio
import json
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_degen_options import frame, policies
from test_option_execution import intent_for
from test_option_scope import AT
from test_option_scope_arming import refresh
from test_option_scope_contract import data
from test_option_scope_execution import execution_policy, policy
from test_option_scope_owned_admission import evidence
from test_option_scope_watch import choice, owned, ready, revision
from test_option_shared_strategy import swing_input, swing_policy

from app.options.coordinator import DegenCoordinator
from app.options.engine import fingerprint
from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy
from app.options.scope_arbitration import ScopeCycleInput, SharedScopePolicy
from app.options.scope_execution_export import export_scope_execution, verify_scope_execution_export


@contextmanager
def shared(path, priority=("SCOPE", "DEGEN"), right="CALL", *, costs=False):
    path.mkdir(parents=True, exist_ok=True)
    ep = execution_policy() | {
        "scope_arbitration": "shared-scope-selection-v1",
        "loss_control": NativeLossPolicy(
            max_consecutive_losses=2,
            cooldown_seconds=1800,
            families=tuple(
                FamilyLossPolicy(family=f, max_consecutive_losses=2, cooldown_seconds=1800)
                for f in priority
            ),
        ),
    }
    if costs:
        from app.execution.economics import CostPolicy

        ep["cost_policy"] = CostPolicy(total_budget="1", daily_budget=".1")
    with owned(
        path, enroll=False, execution_policy_changes=ep, allowed_underlyings=("SPY", "SPX")
    ) as (e, v, _):
        times = [AT]
        setup, selection = policies()
        c = DegenCoordinator(
            e,
            setup,
            selection,
            create=True,
            clock=lambda: times[0],
            scope_policy=SharedScopePolicy(watch=policy(), family_priority=priority),
            swing_policy=swing_policy() if "SWING" in priority else None,
        )
        f, context = data(right)
        c.scope_book.call(
            "first",
            choice(right, "trend_pullback_continuation"),
            f,
            context,
            now=AT,
            expected_revision=revision(e),
        )
        for seconds in range(0, 60, 10):
            times[0] = AT + timedelta(seconds=seconds)
            ready(e, v, times[0])
            fresh, context = refresh(f, times[0])
            c.scope_book.observe_arming(
                f"sample-{seconds}",
                "first",
                frame=fresh,
                context=context,
                now=times[0],
                expected_revision=revision(e),
            )
        fresh, context, u, now = evidence(e, f)
        times[0] = now
        base = frame(right).model_dump(mode="json")

        # Align the two independent evidence families to this owner and current clock.
        def replace(value):
            if isinstance(value, dict):
                return {
                    k: (
                        now.isoformat()
                        if k in {"source_at", "received_at"}
                        else "fixture-provider"
                        if k == "provider"
                        else "fixture-quote"
                        if k == "source" and "bid" in value and "instrument" in value
                        else replace(v)
                    )
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [replace(v) for v in value]
            return value

        base = replace(base)
        if "SWING" in priority:
            item = swing_input(right).model_dump(mode="json")
            # Seed timestamps/identity remain original; only observed catalyst and locked quote advance.
            item["seed"]["instrument"]["provider"] = "fixture-provider"
            item["catalyst"]["source_at"] = now.isoformat()
            item["catalyst"]["received_at"] = now.isoformat()
            item["metadata"] = replace(item["metadata"])
            base["swing"] = [item]
            q = dict(base["quotes"][0])
            q["instrument"] = item["seed"]["instrument"]
            base["quotes"].append(q)
        from app.options.coordinator import DegenFrame

        combined = DegenFrame.model_validate(base).model_copy(
            update={
                "scope": ScopeCycleInput(
                    play_key="first", frame=fresh, context=context, underlying=u
                )
            }
        )
        yield c, v, times, combined


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "priority", [("SCOPE", "DEGEN"), ("DEGEN", "SCOPE"), ("SWING", "SCOPE", "DEGEN")]
)
def test_shared_selection_native_fill_and_portable_accounting(tmp_path, priority, right):
    with shared(tmp_path, priority, right) as (c, v, times, f):
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "OPEN", out
        chosen = out["scope_arbitration"]["selected"]
        assert chosen["family"] == priority[0], out
        assert {x["family"] for x in out["scope_arbitration"]["choices"]} == set(priority)
        assert asyncio.run(c.cycle(f)) == out
        buy = intent_for(c.engine, out["client_id"])
        assert buy.entry_lineage.family == priority[0]
        u = f.scope.underlying if priority[0] == "SCOPE" else f.underlyings[0]
        q = (
            f.scope.frame.quote
            if priority[0] == "SCOPE"
            else next(q for q in f.quotes if q.instrument == buy.instrument)
        )
        v.fill(buy, buy.quantity, q, times[0], fill_id="entry-fill", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        from test_option_scope_observer import observer

        view = observer(c.engine, times[0]).report()
        assert view["status"] == "OK", view
        with c.engine.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 0
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM execution_events WHERE kind='SHARED_SCOPE_ENTRY_SELECTED'"
                ).fetchone()[0]
                == 1
            )
        value = export_scope_execution(c.engine.journal, now=times[0], data_cost="0", host_cost="0")
        assert (
            verify_scope_execution_export(value, value["export_hash"])["accounting_status"]
            == "INCOMPLETE"
        )
        assert value["report"]["net_after_all_costs"] is None


def test_missing_scope_cannot_silently_select_degen(tmp_path):
    with shared(tmp_path) as (c, _, _, f):
        result = asyncio.run(c.cycle(f.model_copy(update={"scope": None})))
        assert result["blocker"] == "EXACT_SCOPE_WATCH_COVERAGE_REQUIRED", result
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()


def test_direct_scope_prepare_cannot_bypass_shared_cycle(tmp_path):
    with shared(tmp_path) as (c, v, times, f):
        ready(c.engine, v, times[0])
        receipt = c.scope_book.review_admission(
            "manual",
            "first",
            expected_revision=revision(c.engine),
            now=times[0],
            frame=f.scope.frame,
            context=f.scope.context,
            underlying=f.scope.underlying,
        )
        out = c.scope_book.prepare_entry(
            "first", expected_revision=receipt["revision"], now=times[0]
        )
        assert out["status"] == "REJECTED"
        assert out["reason"] == "SHARED_SCOPE_CURRENT_CYCLE_REQUIRED"


def test_legacy_hashes_omit_enrollment_and_model_boundary(tmp_path):
    from test_option_execution import configuration

    from app.execution.judgment import JudgmentLimits
    from app.options.lifecycle import OptionExecutionPolicy

    _, _, old = configuration()
    assert "scope_arbitration" not in old.model_dump(mode="json")
    assert "scope" not in frame().model_dump(mode="json")
    assert fingerprint(old) == fingerprint(old.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        OptionExecutionPolicy.model_validate(
            old.model_dump() | {"scope_arbitration": "shared-scope-selection-v1"}
        )
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, _, _):
        from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy

        e.policy = e.policy.model_copy(
            update={
                "scope_arbitration": "shared-scope-selection-v1",
                "loss_control": NativeLossPolicy(
                    max_consecutive_losses=2,
                    cooldown_seconds=1800,
                    families=tuple(
                        FamilyLossPolicy(family=f, max_consecutive_losses=2, cooldown_seconds=1800)
                        for f in ("DEGEN", "SCOPE")
                    ),
                ),
            }
        )
        setup, select = policies()
        with pytest.raises(ValueError, match="deterministic only"):
            DegenCoordinator(
                e,
                setup,
                select,
                scope_policy=SharedScopePolicy(watch=policy(), family_priority=("SCOPE", "DEGEN")),
                judgment_limits=JudgmentLimits(),
            )


@pytest.mark.parametrize("chosen", ["SCOPE", "DEGEN"])
@pytest.mark.parametrize("unknown", [False, True])
def test_full_cost_outcome_and_common_loss_guard(tmp_path, chosen, unknown):
    from test_option_position_outcome import read_owned
    from test_option_scope_execution import sell

    from app.execution.economics import UsageEvidence
    from app.options.models import OptionProposal
    from app.options.scope_execution import entry_source

    priority = (chosen, "DEGEN" if chosen == "SCOPE" else "SCOPE")
    with shared(tmp_path, priority, costs=True) as (c, v, times, f):
        key = "degen:" + str(int(times[0].timestamp()) // 300)
        source = entry_source("first", "shared:" + key) if chosen == "SCOPE" else key
        proposal = OptionProposal(action="HOLD", thesis="Recorded fixture entry advisory")
        ready(c.engine, v, times[0])
        with c.engine.journal.write() as db:
            c.engine._admit_model_attempt(db, source, fingerprint(proposal), times[0], None)
        c.engine.record_model_usage(
            source,
            UsageEvidence(
                request_id="fixture-advice",
                model=c.engine.policy.cost_policy.model,
                input_tokens=1000,
                output_tokens=100,
            ),
            proposal,
            now=times[0],
        )
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "OPEN", out
        buy = intent_for(c.engine, out["client_id"])
        q = f.scope.frame.quote if chosen == "SCOPE" else f.quotes[0]
        u = f.scope.underlying if chosen == "SCOPE" else f.underlyings[0]
        v.fill(buy, buy.quantity, q, times[0], fill_id="entry", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        if unknown:
            with c.engine.journal.write() as db:
                db.execute(
                    "INSERT INTO execution_model_calls VALUES(?,?,?,NULL,NULL,NULL,NULL)",
                    ("interrupted-management", "a" * 64, times[0].isoformat()),
                )
        sell(c.engine, v, buy, q, u, times[0], key="scale", quantity=1)
        assert c.engine.refresh_loss_control(now=times[0])["consumed_entries"] == 0
        sell(c.engine, v, buy, q, u, times[0], key="runner")
        outcome = read_owned(c.engine, buy)
        state = c.engine.refresh_loss_control(now=times[0])
        exported = export_scope_execution(
            c.engine.journal, now=times[0], data_cost=".01", host_cost=".02"
        )
        report = exported["report"]
        assert Decimal(outcome["known_model_cost"]) > 0
        assert Decimal(report["execution_fees"]) > 0
        assert (
            verify_scope_execution_export(exported, exported["export_hash"])["status"]
            == "VERIFIED_NATIVE_ACCOUNTING"
        )
        assert len(report["orders"]) == 3
        assert all(o["scope_arbitration"]["selected"]["family"] == chosen for o in report["orders"])
        if unknown:
            assert report["net_after_all_costs"] is None
            assert "MODEL_COST_UNKNOWN" in report["reasons"]
            assert state["consumed_entries"] == 0
        else:
            assert Decimal(report["net_after_all_costs"]) == Decimal(
                report["ledger"]["cash"]
            ) - c.engine.policy.capital - Decimal(report["model_costs"]["known_cost"]) - Decimal(
                ".03"
            )
            assert state["consumed_entries"] == 1
            assert {x["family"]: x["consumed_entries"] for x in state["families"]} == {
                chosen: 1,
                priority[1]: 0,
            }


@pytest.mark.parametrize("tamper", [False, True])
def test_prepared_restart_and_selection_tamper_fail_before_attempt(tmp_path, monkeypatch, tamper):
    from app.options.engine import OptionExecution
    from app.options.observer import _json

    async def pause(*args, **kwargs):
        return "PREPARED"

    with shared(tmp_path) as (c, v, times, f):
        monkeypatch.setattr(c.engine, "dispatch", pause)
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "PREPARED", out
        path, limits, ep, setup, select, sp, now = (
            c.engine.journal.path,
            c.engine.limits,
            c.engine.policy,
            c.policy,
            c.selection,
            c.scope_policy,
            times[0],
        )
    with OptionExecution.open(path, limits, ep, v, now=now) as e:
        resumed = DegenCoordinator(e, setup, select, scope_policy=sp, clock=lambda: now)
        assert asyncio.run(resumed.cycle(f)) == out
        if tamper:
            with e.journal.write() as db:
                row = db.execute(
                    "SELECT result_json FROM execution_option_opportunities"
                ).fetchone()
                value = _json(row[0])
                value["scope_arbitration"]["selected"]["candidate_hash"] = "0" * 64
                db.execute(
                    "UPDATE execution_option_opportunities SET result_json=?", (json.dumps(value),)
                )
        status = asyncio.run(
            e.dispatch(out["client_id"], f.scope.frame.quote, f.scope.underlying, now=now)
        )
        assert status == ("REJECTED" if tamper else "OPEN")
        with e.journal.read() as db:
            order = db.execute("SELECT attempted_at FROM execution_orders").fetchone()
            assert (order[0] is None) == tamper


def test_atomic_selection_failure_consumes_nothing(tmp_path, monkeypatch):
    with shared(tmp_path) as (c, _, _, f):
        original = c.engine.journal.event

        def fail(db, at, kind, payload, client_id=None):
            if kind == "SHARED_SCOPE_ENTRY_SELECTED":
                raise RuntimeError("fixture write interruption")
            return original(db, at, kind, payload, client_id)

        monkeypatch.setattr(c.engine.journal, "event", fail)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "HOLD"
        with c.engine.journal.read() as db:
            for table in (
                "execution_orders",
                "execution_option_decisions",
                "execution_option_scope_entries",
            ):
                assert not db.execute(f"SELECT 1 FROM {table}").fetchone()
        assert c.scope_book.snapshot()["watches"][0]["status"] == "WATCHING"


def test_shared_scope_held_cycle_keeps_original_target_management(tmp_path):
    with shared(tmp_path) as (c, v, times, f):
        out = asyncio.run(c.cycle(f))
        buy = intent_for(c.engine, out["client_id"])
        v.fill(
            buy,
            buy.quantity,
            f.scope.frame.quote,
            times[0],
            fill_id="entry",
            underlying=f.scope.underlying,
        )
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] += timedelta(minutes=5)
        price = buy.target_exit_schedule.steps[0].underlying_price
        u = f.scope.underlying.model_copy(
            update={"source_at": times[0], "received_at": times[0], "bid": price, "ask": price}
        )
        q = f.scope.frame.quote.model_copy(update={"source_at": times[0], "received_at": times[0]})
        held = f.model_copy(
            update={
                "scope": f.scope.model_copy(
                    update={"underlying": u, "frame": f.scope.frame.model_copy(update={"quote": q})}
                )
            }
        )
        result = asyncio.run(c.cycle(held))
        assert result["status"] == "HELD", result
        assert result["management"]["status"] == "OPEN", result
        scale = intent_for(c.engine, result["management"]["client_id"])
        assert scale.quantity == 1 and scale.closing_entry_client_id == buy.client_id
        assert c.scope_book.snapshot()["watches"][0]["status"] == "POSITION_OPEN"


def test_ineligible_scope_leaves_degen_available(tmp_path):
    with shared(tmp_path) as (c, _, _, f):
        record = c.scope_book.snapshot()["watches"][0]
        target = Decimal(record["geometry"]["target_one"])
        u = f.scope.underlying.model_copy(update={"bid": target, "ask": target})
        result = asyncio.run(
            c.cycle(f.model_copy(update={"scope": f.scope.model_copy(update={"underlying": u})}))
        )
        assert result["status"] == "OPEN", result
        assert result["scope_arbitration"]["selected"]["family"] == "DEGEN"
        assert result["scope_candidate"] is None
        assert not result["scope_review"]["admission_review"]["eligible"]


def test_scope_can_win_without_admitted_degen(tmp_path):
    with shared(tmp_path) as (c, _, _, f):
        # Valid exact quote coverage, but a price beyond the Degen stop rejects its admission.
        u = f.underlyings[0].model_copy(update={"bid": Decimal(599), "ask": Decimal(599)})
        out = asyncio.run(c.cycle(f.model_copy(update={"underlyings": (u,)})))
        assert out["status"] == "OPEN", out
        assert not out["candidates"]
        assert out["scope_arbitration"]["selected"]["family"] == "SCOPE"


def test_unknown_cost_blocks_only_its_independent_owner(tmp_path):
    with (
        shared(tmp_path / "a", costs=True) as (a, _, ta, fa),
        shared(tmp_path / "b", costs=True) as (b, _, _, fb),
    ):
        with a.engine.journal.write() as db:
            db.execute(
                "INSERT INTO execution_model_calls VALUES(?,?,?,NULL,NULL,NULL,NULL)",
                ("unknown-entry", "b" * 64, ta[0].isoformat()),
            )
        stopped = asyncio.run(a.cycle(fa))
        assert stopped["status"] == "HOLD", stopped
        assert asyncio.run(b.cycle(fb))["status"] == "OPEN"
        with a.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()
        assert (
            export_scope_execution(a.engine.journal, now=ta[0])["report"]["net_after_all_costs"]
            is None
        )
