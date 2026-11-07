"""New native owners preserve closed losses while later full entry advice is pending."""

import asyncio
import json
import shutil
import sqlite3
import traceback
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_execution import intent_for
from test_option_position_outcome import read_owned
from test_option_scope_ai import ai_owner
from test_option_scope_arming import refresh
from test_option_scope_context import bind
from test_option_scope_execution import sell
from test_option_scope_series import SHIFT, shifted
from test_option_scope_structure import bind as bind_structure
from test_option_scope_watch import choice, ready, revision

from app.execution.engine import ExecutionBlocked
from app.options.coordinator import DegenFrame
from app.options.entry_judgment import hold, result_for
from app.options.position_outcome import native_position_outcome
from app.options.replay import _capture_boundary
from app.options.scope_execution_export import export_scope_execution, verify_scope_execution_export


def close_first(c, venue, times, frame, result=None):
    result = result if result is not None else asyncio.run(c.cycle(frame))
    assert result["status"] == "OPEN", result
    buy = intent_for(c.engine, result["client_id"])
    clocks = {"source_at": times[0], "received_at": times[0]}
    quote = frame.scope.frame.quote.model_copy(update=clocks)
    underlying = frame.scope.underlying.model_copy(update=clocks)
    venue.fill(buy, buy.quantity, quote, times[0], fill_id="first-fill", underlying=underlying)
    assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
    sell(c.engine, venue, buy, quote, underlying, times[0])
    outcome = read_owned(c.engine, buy)
    assert outcome["status"] == "COMPLETE" and outcome["outcome"] == "LOSS", outcome
    risk = c.engine.refresh_loss_control(now=times[0])
    assert risk["consumed_entries"] == 1
    return buy, outcome


def next_session(c, venue, times, original, state, tick=None):
    frame = DegenFrame.model_validate(shifted(original.model_dump(mode="json")))
    scope = frame.scope
    scope = scope.model_copy(update={"frame": bind(bind_structure(scope.frame), scope.context)})
    start = times[0] + SHIFT
    times[0] = start
    ready(c.engine, venue, times[0])
    c.engine.refresh_loss_control(now=times[0])
    fresh, context = refresh(scope.frame, times[0])
    if tick:
        tick(scope, fresh, context)
    c.scope_book.call(
        scope.play_key,
        choice(scope.frame.metadata.instrument.contract.right, "trend_pullback_continuation"),
        fresh,
        context,
        now=times[0],
        expected_revision=revision(c.engine),
    )
    for seconds in range(0, 60, 10):
        times[0] = start + timedelta(seconds=seconds)
        ready(c.engine, venue, times[0])
        fresh, context = refresh(scope.frame, times[0])
        if tick:
            tick(scope, fresh, context)
        c.scope_book.observe_arming(
            f"next-sample-{seconds}",
            scope.play_key,
            frame=fresh,
            context=context,
            now=times[0],
            expected_revision=revision(c.engine),
        )
    times[0] = start + timedelta(seconds=60)
    ready(c.engine, venue, times[0])
    fresh, context = refresh(scope.frame, times[0])
    if tick:
        tick(scope, fresh, context)
    clocks = {"source_at": times[0], "received_at": times[0]}
    frame = frame.model_copy(
        update={
            "scope": scope.model_copy(
                update={
                    "frame": fresh,
                    "context": context,
                    "underlying": scope.underlying.model_copy(update=clocks),
                }
            ),
            "quotes": tuple(q.model_copy(update=clocks) for q in frame.quotes),
            "underlyings": tuple(u.model_copy(update=clocks) for u in frame.underlyings),
            "histories": tuple(h.model_copy(update=clocks) for h in frame.histories),
            "inventories": tuple(
                i.model_copy(
                    update=clocks
                    | {"contracts": tuple(m.model_copy(update=clocks) for m in i.contracts)}
                )
                for i in frame.inventories
            ),
            "swing": tuple(
                s.model_copy(
                    update={
                        "metadata": s.metadata.model_copy(update=clocks),
                        "catalyst": s.catalyst.model_copy(update=clocks),
                    }
                )
                for s in frame.swing
            ),
        }
    )
    state["owner"] = c, venue, times, frame
    return frame


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("carry", [False, True])
def test_native_second_paid_scope_entry_preserves_first_loss(tmp_path, monkeypatch, right, carry):
    with ai_owner(tmp_path, monkeypatch, right=right, carry=carry, later_entry=True) as (
        c,
        venue,
        times,
        frame,
        state,
    ):
        first, original = close_first(c, venue, times, frame)
        later = next_session(c, venue, times, frame, state)
        run = c._model_run
        checkpoints = []

        async def pending(request, secret, *, broad):
            # Validate saved pending evidence outside the original model deadline.
            _capture_boundary(c.engine.journal, tmp_path / "pending.db")
            checkpoints.append("pending")
            return await run(request, secret, broad=broad)

        monkeypatch.setattr(c, "_model_run", pending)
        failure = []
        halt = c.engine._halt

        def trace_halt(*args):
            failure.append(traceback.format_exc())
            return halt(*args)

        monkeypatch.setattr(c.engine, "_halt", trace_halt)
        second = asyncio.run(c.cycle(later))
        assert second["status"] == "OPEN", (second.get("reason"), failure)
        assert checkpoints == ["pending"]
        with sqlite3.connect(tmp_path / "pending.db") as db:
            db.row_factory = sqlite3.Row
            old = native_position_outcome(db, first.client_id, c.engine.limits.population_id)
        assert old["status"] == "COMPLETE", old
        assert (
            old["net_after_known_execution_and_model_costs"]
            == original["net_after_known_execution_and_model_costs"]
        )
        assert len(old["unallocated_account_calls"]) == 1
        assert old["unallocated_account_calls"][0]["model_cost"] is None
        buy = intent_for(c.engine, second["client_id"])
        assert buy.client_id != first.client_id
        assert buy.exit_at <= later.scope.frame.session.protect_at
        assert buy.approval_expires_at <= state["request"].packet.valid_until
        clocks = {"source_at": times[0], "received_at": times[0]}
        quote = later.scope.frame.quote.model_copy(update=clocks)
        underlying = later.scope.underlying.model_copy(update=clocks)
        venue.fill(buy, buy.quantity, quote, times[0], fill_id="second-fill", underlying=underlying)
        assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
        sell(c.engine, venue, buy, quote, underlying, times[0], key="second-close")
        risk = c.engine.refresh_loss_control(now=times[0])
        assert risk["consumed_entries"] == 2 and risk["locked"], risk
        assert (
            read_owned(c.engine, first)["net_after_known_execution_and_model_costs"]
            == original["net_after_known_execution_and_model_costs"]
        )
        exported = export_scope_execution(
            c.engine.journal, now=times[0], data_cost=".01", host_cost=".02"
        )
        assert (
            verify_scope_execution_export(exported, exported["export_hash"])["status"]
            == "VERIFIED_NATIVE_ACCOUNTING"
        )
        assert len(exported["evidence"]["execution_model_calls"]) == 2
        assert Decimal(exported["report"]["model_costs"]["known_cost"]) > Decimal(
            original["known_model_cost"]
        )
        assert exported["report"]["net_after_all_costs"] is not None


@pytest.mark.parametrize("enrolled", [False, True])
def test_later_hold_keeps_charge_without_changing_prior_outcome(tmp_path, monkeypatch, enrolled):
    with ai_owner(tmp_path, monkeypatch, later_entry=enrolled) as (c, venue, times, frame, state):
        first, original = close_first(c, venue, times, frame)
        later = next_session(c, venue, times, frame, state)
        run = c._model_run

        async def held(request, secret, *, broad):
            result = await run(request, secret, broad=broad)
            return result_for(request, plan=hold(request.packet), count=1000, usage=result.usage)

        monkeypatch.setattr(c, "_model_run", held)
        second = asyncio.run(c.cycle(later))
        assert second["status"] == "HOLD", second
        outcome = read_owned(c.engine, first)
        assert outcome["status"] == ("COMPLETE" if enrolled else "INCOMPLETE"), outcome
        assert outcome["known_model_cost"] == original["known_model_cost"]
        assert len(outcome["unallocated_account_calls"]) == 1
        assert Decimal(outcome["unallocated_account_calls"][0]["model_cost"]) > 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 2
            assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 2
            row = db.execute(
                "SELECT policy_json FROM execution_option_loss_control WHERE id=1"
            ).fetchone()
            assert ("entry_cost_attribution" in json.loads(row[0])) == enrolled


@pytest.fixture(scope="module")
def unknown_later_entry(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-unknown-entry")
    with (
        pytest.MonkeyPatch.context() as patch,
        ai_owner(root, patch, later_entry=True) as (c, venue, times, frame, state),
    ):
        first, original = close_first(c, venue, times, frame)
        later = next_session(c, venue, times, frame, state)

        async def unknown(request, secret, *, broad):
            _capture_boundary(c.engine.journal, root / "pending.db")
            return result_for(request, error="FIXTURE_USAGE_UNKNOWN")

        patch.setattr(c, "_model_run", unknown)
        result = asyncio.run(c.cycle(later))
        assert result["status"] == "HOLD", result
        outcome = read_owned(c.engine, first)
        assert outcome["status"] == "COMPLETE", outcome
        exported = export_scope_execution(
            c.engine.journal, now=times[0], data_cost="0", host_cost="0"
        )
        return root, first.client_id, c.engine.limits.population_id, original, exported


def test_unknown_later_call_stays_unknown_in_account_totals(unknown_later_entry):
    _, _, _, _, exported = unknown_later_entry
    assert exported["report"]["model_costs"]["unknown_calls"] == 1
    assert exported["report"]["net_after_all_costs"] is None
    assert (
        verify_scope_execution_export(exported, exported["export_hash"])["accounting_status"]
        == "INCOMPLETE"
    )


@pytest.mark.parametrize("damage", ["clock", "request", "policy", "model", "replay"])
def test_unproven_later_call_never_preserves_complete_outcome(
    tmp_path, unknown_later_entry, damage
):
    root, entry, population, old, _ = unknown_later_entry
    path = tmp_path / "damaged.db"
    shutil.copy2(root / "pending.db", path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        key = db.execute(
            "SELECT source_key FROM execution_model_calls ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]
        if damage == "clock":
            db.execute(
                "UPDATE execution_model_calls SET started_at=? WHERE source_key=?",
                (old["closed_at"], key),
            )
        elif damage == "request":
            row = db.execute(
                "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
            ).fetchone()
            result = json.loads(row[0])
            result["entry_request"]["packet"]["account"]["captured_at"] = old["closed_at"]
            db.execute(
                "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                (json.dumps(result), key),
            )
        elif damage == "policy":
            value = json.loads(
                db.execute("SELECT policy_json FROM execution_option_loss_control").fetchone()[0]
            )
            value.pop("entry_cost_attribution")
            db.execute(
                "UPDATE execution_option_loss_control SET policy_json=?", (json.dumps(value),)
            )
        else:
            value = json.loads(
                db.execute("SELECT policy_json FROM execution_option_strategy").fetchone()[0]
            )
            if damage == "model":
                value.pop("entry_model")
            else:
                value["replay_model"] = {"arm": "C"}
            db.execute("UPDATE execution_option_strategy SET policy_json=?", (json.dumps(value),))
        try:
            result = native_position_outcome(db, entry, population)
        except (ValueError, ExecutionBlocked):
            return
        assert result["status"] == "INCOMPLETE", result
        assert result["net_after_known_execution_and_model_costs"] is None


def test_native_enrollment_preserves_legacy_serialization_and_requires_full_entry(tmp_path):
    from test_option_scope_arbitration import shared

    from app.options.lifecycle import NativeLossPolicy

    old = NativeLossPolicy(max_consecutive_losses=2, cooldown_seconds=1800)
    assert (
        old.model_dump_json()
        == '{"version":"native-position-loss-v1","max_consecutive_losses":2,"cooldown_seconds":1800}'
    )
    with pytest.raises(ValueError):
        NativeLossPolicy.model_validate(old.model_dump() | {"entry_cost_attribution": "unknown"})
    with (
        pytest.raises(ValueError, match="frozen model costs"),
        shared(tmp_path / "no-costs", later_entry=True),
    ):
        pass
    with (
        pytest.raises(ValueError, match="native full-entry"),
        shared(tmp_path / "no-entry", costs=True, later_entry=True),
    ):
        pass


def test_runtime_settings_and_reopen_keep_frozen_attribution(tmp_path, monkeypatch):
    from test_option_runtime import policy as runtime_policy

    from app.options.engine import OptionExecution
    from app.options.runtime_models import RuntimeSettings
    from app.options.venue import DurableOptionVenue

    with ai_owner(tmp_path, monkeypatch, later_entry=True) as (c, _, times, _, _):
        settings = RuntimeSettings(
            limits=c.engine.limits,
            execution=c.engine.policy,
            setup=c.policy,
            selection=c.selection,
            scope_policy=c.scope_policy,
            runtime=runtime_policy(tmp_path, scope_inputs="scope-runtime-inputs-v1"),
            key_file=str(c.key_file),
            judgment_limits=c.judgment_limits,
            entry_policy=c.entry_policy,
        )
        assert RuntimeSettings.model_validate_json(settings.model_dump_json()) == settings
        with pytest.raises(ValueError, match="native full-entry"):
            RuntimeSettings.model_validate(settings.model_dump() | {"entry_policy": None})
        at = times[0]
    venue = DurableOptionVenue(tmp_path / "venue.db")
    with OptionExecution.open(
        tmp_path / "options.db", settings.limits, settings.execution, venue, now=at
    ) as engine:
        assert engine.policy.loss_control.entry_cost_attribution == "later-flat-entry-v1"
    changed = settings.execution.model_copy(
        update={
            "loss_control": settings.execution.loss_control.model_copy(
                update={"entry_cost_attribution": None}
            )
        }
    )
    with (
        pytest.raises(ValueError, match="configuration is immutable"),
        OptionExecution.open(tmp_path / "options.db", settings.limits, changed, venue, now=at),
    ):
        pass


def test_continuous_runtime_second_entry_uses_delivered_fresh_scope(tmp_path, monkeypatch):
    from test_option_runtime import enable
    from test_option_runtime import policy as runtime_policy
    from test_option_scope_runtime import send

    from app.options.runtime import OptionRuntime

    with ai_owner(tmp_path, monkeypatch, later_entry=True) as (c, venue, times, frame, state):
        fresh = c.scope_refresh
        model = c._model_run
        runtime = OptionRuntime(
            c, runtime_policy(tmp_path, scope_inputs="scope-runtime-inputs-v1"), create=True
        )
        enable(runtime)

        async def execute(value):
            started, release = asyncio.Event(), asyncio.Event()

            async def wait(request, secret, *, broad):
                started.set()
                await release.wait()
                return await model(request, secret, broad=broad)

            monkeypatch.setattr(c, "_model_run", wait)
            send(runtime, value, kind="CYCLE")
            await runtime.tick()
            await asyncio.wait_for(started.wait(), 15)
            times[0] += timedelta(seconds=1)
            delivered = await fresh(value.scope.play_key)
            send(runtime, DegenFrame(scope=delivered))
            supervise = c.supervise

            async def delivered_tick(*args):
                # tick() has durably accepted the MARKET packet before it
                # awaits supervision. Model completion remains independent
                # of the supervisor process, under the original deadline.
                release.set()
                return await supervise(*args)

            monkeypatch.setattr(c, "supervise", delivered_tick)
            try:
                await runtime.tick()
            finally:
                monkeypatch.setattr(c, "supervise", supervise)
            await runtime.task
            return c.report()["cycles"][0]["result"]

        first_result = asyncio.run(execute(frame))
        first, original = close_first(c, venue, times, frame, first_result)

        def advance(scope, current, context):
            clocks = {"source_at": times[0], "received_at": times[0]}
            delivered = scope.model_copy(
                update={
                    "frame": current,
                    "context": context,
                    "underlying": scope.underlying.model_copy(update=clocks),
                }
            )
            send(runtime, DegenFrame(scope=delivered))
            asyncio.run(runtime.tick())

        later = next_session(c, venue, times, frame, state, tick=advance)
        second = asyncio.run(execute(later))
        assert second["status"] == "OPEN", second
        assert (
            read_owned(c.engine, first)["net_after_known_execution_and_model_costs"]
            == original["net_after_known_execution_and_model_costs"]
        )
        with c.engine.journal.read() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM execution_model_calls WHERE cost IS NOT NULL"
                ).fetchone()[0]
                == 2
            )
            assert (
                db.execute("SELECT count(*) FROM execution_option_scope_runtime_inputs").fetchone()[
                    0
                ]
                == 12
            )
        exported = export_scope_execution(c.engine.journal, now=times[0])
        assert (
            verify_scope_execution_export(exported, exported["export_hash"])["accounting_status"]
            == "INCOMPLETE"
        )
