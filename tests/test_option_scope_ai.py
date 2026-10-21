"""Shared paid entry fixtures use no authenticated provider or model traffic."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta

import pytest
from test_option_entry_reasoning import packet_for, plan_for
from test_option_scope_arbitration import shared
from test_option_scope_arming import refresh

from app.execution.economics import UsageEvidence
from app.execution.judgment import JudgmentLimits
from app.options.engine import fingerprint
from app.options.entry_judgment import hold, result_for
from app.options.entry_reasoning import SharedScopeEntryPlan, plan_class


@contextmanager
def ai_owner(
    path,
    monkeypatch,
    *,
    family="SCOPE",
    right="CALL",
    mode="ENTER",
    position_policy=None,
    carry=False,
    later_entry=False,
):
    state = {}

    async def scope_refresh(play):
        _c, _v, times, f = state["owner"]
        fresh, context = refresh(f.scope.frame, times[0])
        from test_option_scope_context import bind

        context = context.model_copy(
            update={
                "prior": f.scope.context.prior,
                "previous_session": f.scope.context.previous_session,
            }
        )
        fresh = bind(fresh, context)
        return f.scope.model_copy(
            update={
                "frame": fresh,
                "context": context,
                "underlying": f.scope.underlying.model_copy(
                    update={"source_at": times[0], "received_at": times[0]}
                ),
            }
        )

    options = {
        "entry_policy": packet_for(right).policy.model_copy(
            update={
                "scope_selection": "scope-fixed-plan-v1",
                **(
                    {"scope_carry": "shared-scope-carry-v1", "max_carry_horizon_seconds": 600000}
                    if carry
                    else {}
                ),
            }
        ),
        "judgment_limits": JudgmentLimits(process_timeout_seconds=5, request_timeout_seconds=3),
        "key_file": path / "private-model-key",
        "scope_refresh": scope_refresh,
        "position_policy": position_policy,
    }
    with shared(
        path,
        ("SCOPE", "DEGEN") if family != "SWING" and not carry else ("SCOPE", "SWING", "DEGEN"),
        right,
        costs=True,
        ai=True,
        coordinator_options=options,
        carry=carry,
        later_entry=later_entry,
    ) as owner:
        state["owner"] = owner
        c, _, times, _ = owner
        monkeypatch.setattr(c, "_model_secret", lambda: "fixture-never-transmitted")

        async def run(request, secret, *, broad):
            state["request"] = request
            times[0] += timedelta(seconds=1)
            if mode == "HOLD":
                plan = hold(request.packet)
            elif family == "SCOPE":
                plan = plan_class(request.packet.policy)(
                    decision_id=request.packet.decision_id,
                    packet_hash=fingerprint(request.packet),
                    action="ENTER",
                    scope=True,
                    candidate_id=fingerprint(request.packet.scope.model_dump(mode="json")),
                    evidence_ids=(fingerprint(request.packet.scope.model_dump(mode="json")),),
                    thesis="Fixture fixed Scope selection",
                    uncertainty="Full premium at risk",
                )
            else:
                plan = SharedScopeEntryPlan.model_validate(
                    plan_for(
                        request.packet,
                        candidate_id=next(
                            o.candidate.candidate_id
                            for o in request.packet.opportunities
                            if (o.candidate.family == "SWING_DAILY_BREAKOUT") == (family == "SWING")
                        ),
                        evidence_ids=next(
                            o.evidence_ids
                            for o in request.packet.opportunities
                            if (o.candidate.family == "SWING_DAILY_BREAKOUT") == (family == "SWING")
                        ),
                    ).model_dump(mode="json")
                    | {"version": "shared-scope-entry-plan-v1", "scope": False}
                )
            if carry and family != "SCOPE" and mode != "HOLD":
                values = plan.model_dump()
                values["version"] = "shared-scope-carry-plan-v1"
                if family == "SWING":
                    o = next(
                        o
                        for o in request.packet.opportunities
                        if o.candidate.candidate_id == plan.candidate_id
                    )
                    values.update(
                        horizon_seconds=int(
                            (o.scan.carry_terms.exit_at - request.packet.as_of).total_seconds()
                        ),
                        underlying_target=o.scan.carry_terms.first_target,
                    )
                plan = plan_class(request.packet.policy).model_validate(values)
            return result_for(
                request,
                plan=plan,
                count=1000,
                usage=UsageEvidence(
                    request_id="fixture-paid-" + request.packet.cycle_key,
                    model=request.configuration.costs.model,
                    input_tokens=1000,
                    output_tokens=100,
                ),
            )

        monkeypatch.setattr(c, "_model_run", run)
        yield *owner, state


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_scope_ai_paid_cycle_prepares_dispatches_and_retains_plan(tmp_path, monkeypatch, right):
    with ai_owner(tmp_path, monkeypatch, right=right) as (c, _v, _times, f, _state):
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        assert result["scope_arbitration"]["selected"]["family"] == "SCOPE"
        assert result["scope_paid_review"]["model_charge"]["cost"] != "0"
        assert asyncio.run(c.cycle(f)) == result


def test_shared_ai_can_choose_degen_or_hold(tmp_path, monkeypatch):
    for mode in ("ENTER", "HOLD"):
        with ai_owner(tmp_path / mode, monkeypatch, family="DEGEN", mode=mode) as (c, _, _, f, _):
            result = asyncio.run(c.cycle(f))
            assert result["status"] == ("OPEN" if mode == "ENTER" else "HOLD"), result


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_paid_scope_full_cost_outcome_scales_export_and_observer(tmp_path, monkeypatch, right):
    from decimal import Decimal

    from test_option_execution import intent_for
    from test_option_position_outcome import read_owned
    from test_option_scope_execution import sell
    from test_option_scope_observer import observer

    from app.options.attribution import decision_attribution
    from app.options.scope_execution_export import (
        export_scope_execution,
        verify_scope_execution_export,
    )

    with ai_owner(tmp_path, monkeypatch, right=right) as (c, v, times, f, _state):
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        buy = intent_for(c.engine, result["client_id"])
        q = f.scope.frame.quote.model_copy(update={"source_at": times[0], "received_at": times[0]})
        u = f.scope.underlying.model_copy(update={"source_at": times[0], "received_at": times[0]})
        v.fill(buy, buy.quantity, q, times[0], fill_id="paid-entry", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        with c.engine.journal.read() as db:
            attr = decision_attribution(db, result["cycle_key"], result, c.engine.policy)
            assert attr.entry_client_id == buy.client_id
            assert attr.model_cost > 0 and attr.filled_quantity == buy.quantity
            assert attr.role == "ENTRY"
        sell(c.engine, v, buy, q, u, times[0], key="scale", quantity=1)
        assert c.engine.refresh_loss_control(now=times[0])["consumed_entries"] == 0
        sell(c.engine, v, buy, q, u, times[0], key="final")
        outcome = read_owned(c.engine, buy)
        assert not outcome["reasons"], outcome
        assert Decimal(outcome["known_model_cost"]) == Decimal(
            result["scope_paid_review"]["model_charge"]["cost"]
        )
        assert c.engine.refresh_loss_control(now=times[0])["consumed_entries"] == 1
        value = export_scope_execution(
            c.engine.journal, now=times[0], data_cost=".01", host_cost=".02"
        )
        assert (
            verify_scope_execution_export(value, value["export_hash"])["status"]
            == "VERIFIED_NATIVE_ACCOUNTING"
        )
        assert value["report"]["net_after_all_costs"] is not None
        assert all(
            x["scope_paid_review"] == result["scope_paid_review"] for x in value["report"]["orders"]
        )
        view = observer(c.engine, times[0]).report()
        assert view["status"] == "OK", view


@pytest.mark.parametrize("damage", ["repeat_quotes", "expired", "foreign_play", "changed_target"])
def test_fresh_scope_failure_keeps_paid_charge_and_never_tries_second_choice(
    tmp_path, monkeypatch, damage
):
    with ai_owner(tmp_path, monkeypatch) as (c, _v, times, f, _state):
        original = c.scope_refresh

        async def broken(play):
            if damage == "expired":
                times[0] += timedelta(seconds=10)
            fresh = await original(play)
            if damage == "repeat_quotes":
                return f.scope
            if damage == "foreign_play":
                return fresh.model_copy(update={"play_key": "other"})
            if damage == "changed_target":
                # Reaching the original first objective ends the selected play.
                from decimal import Decimal

                u = fresh.underlying.model_copy(update={"bid": Decimal(1000), "ask": Decimal(1000)})
                return fresh.model_copy(update={"underlying": u})
            return fresh

        monkeypatch.setattr(c, "scope_refresh", broken)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "HOLD", result
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()
            rows = db.execute("SELECT cost FROM execution_model_calls").fetchall()
            assert len(rows) == 1 and rows[0][0] is not None
        assert asyncio.run(c.cycle(f)) == result


@pytest.mark.parametrize(
    "damage", ["selection", "paid_review", "cost", "original", "decision", "missing_call"]
)
def test_prepared_ai_entry_rechecks_durable_receipts_before_dispatch(tmp_path, monkeypatch, damage):
    import json

    with ai_owner(tmp_path, monkeypatch) as (c, _v, times, f, _state):
        original_dispatch = c.engine.dispatch

        async def pause(*args, **kwargs):
            return "PREPARED"

        monkeypatch.setattr(c.engine, "dispatch", pause)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "PREPARED", result
        with c.engine.journal.write() as db:
            row = db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()
            data = json.loads(row[0])
            if damage == "selection":
                data["scope_arbitration"]["selected"]["candidate_hash"] = "0" * 64
            elif damage == "paid_review":
                data["scope_paid_review"]["valid_until"] = "2099-01-01T00:00:00Z"
            elif damage == "original":
                data["scope_candidate"]["proposal"]["thesis"] = "changed"
            elif damage == "decision":
                data["entry_result"]["plan"]["candidate_id"] = "0" * 64
            elif damage == "cost":
                db.execute("UPDATE execution_model_calls SET cost='0'")
            else:
                db.execute("DELETE FROM execution_model_calls")
            db.execute(
                "UPDATE execution_option_opportunities SET result_json=?", (json.dumps(data),)
            )
        fresh = awaitable_refresh(c, "first")
        status = asyncio.run(
            original_dispatch(
                result["client_id"], fresh.frame.quote, fresh.underlying, now=times[0]
            )
        )
        assert status == "REJECTED"
        with c.engine.journal.read() as db:
            assert db.execute("SELECT attempted_at FROM execution_orders").fetchone()[0] is None


def awaitable_refresh(c, play):
    return asyncio.run(c.scope_refresh(play))


def test_shared_ai_can_choose_swing_with_scope_alternative(tmp_path, monkeypatch):
    with ai_owner(tmp_path, monkeypatch, family="SWING") as (c, _v, _times, f, _state):
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        assert result["scope_arbitration"]["selected"]["family"] == "SWING"


@pytest.mark.parametrize("mode", ["unknown", "late", "invalid"])
def test_uncertain_late_or_invalid_model_never_enters(tmp_path, monkeypatch, mode):
    with ai_owner(tmp_path, monkeypatch) as (c, _v, times, f, _state):
        run = c._model_run

        async def altered(*args, **kw):
            result = await run(*args, **kw)
            if mode == "unknown":
                raise RuntimeError("fixture lost response")
            if mode == "late":
                times[0] += timedelta(seconds=10)
            if mode == "invalid":
                return result.model_copy(
                    update={"plan": result.plan.model_copy(update={"candidate_id": "0" * 64})}
                )
            return result

        monkeypatch.setattr(c, "_model_run", altered)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "HOLD", result
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()
            cost = db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]
            assert (cost is None) == (mode == "unknown")
        assert asyncio.run(c.cycle(f)) == result


def test_atomic_native_failure_retains_cost_without_consuming_scope(tmp_path, monkeypatch):
    with ai_owner(tmp_path, monkeypatch) as (c, _v, _times, f, _state):
        event = c.engine.journal.event

        def fail(db, at, kind, payload, client_id=None):
            if kind == "SHARED_SCOPE_ENTRY_SELECTED":
                raise RuntimeError("fixture native write failure")
            return event(db, at, kind, payload, client_id)

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
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is not None
        assert c.scope_book.snapshot()["watches"][0]["status"] == "WATCHING"


def test_prepared_restart_retains_paid_plan_and_deadline(tmp_path, monkeypatch):
    from app.options.coordinator import DegenCoordinator
    from app.options.engine import OptionExecution

    with ai_owner(tmp_path, monkeypatch) as (c, v, times, f, _state):

        async def pause(*args, **kw):
            return "PREPARED"

        monkeypatch.setattr(c.engine, "dispatch", pause)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "PREPARED", result
        path, limits, policy = c.engine.journal.path, c.engine.limits, c.engine.policy
        options = {
            "scope_policy": c.scope_policy,
            "entry_policy": c.entry_policy,
            "judgment_limits": c.judgment_limits,
            "key_file": c.key_file,
            "scope_refresh": c.scope_refresh,
        }
        setup, select, now = c.policy, c.selection, times[0]
        fresh = awaitable_refresh(c, "first")
    with OptionExecution.open(path, limits, policy, v, now=now) as engine:
        resumed = DegenCoordinator(engine, setup, select, clock=lambda: now, **options)
        assert asyncio.run(resumed.cycle(f)) == result
        status = asyncio.run(
            engine.dispatch(result["client_id"], fresh.frame.quote, fresh.underlying, now=now)
        )
        assert status == "OPEN"


def test_native_shared_worker_uses_strict_fixed_scope_schema(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    from test_execution_judgment import response

    from app.options.entry_judgment import create_request, request_content, run_entry_process

    with ai_owner(tmp_path, monkeypatch) as (c, _v, _times, f, state):
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        previous = state["request"]
        request = create_request(
            previous.packet, previous.configuration, request_id="a" * 32, now=previous.packet.as_of
        )
        output = response()
        output["output"][0]["content"][0]["text"] = __import__("json").dumps(
            result["entry_result"]["plan"]
        )
        real = asyncio.create_subprocess_exec
        source = (
            f"import sys,os;sys.path[:0]=[{str(Path(__file__).parent.parent)!r},{str(Path(__file__).parent)!r}]\n"
            "import app.options.entry_judgment_worker as worker\nfrom test_execution_judgment import sdk_client\n"
            "def factory(**kw):\n"
            " assert kw['base_url']=='https://api.openai.com/v1' and kw['max_retries']==0\n"
            " assert 'ROBINHOOD_TOKEN' not in os.environ and 'PYTHONPATH' not in os.environ\n"
            f" return sdk_client(output={output!r})[0]\n"
            "worker.OpenAI=factory\nraise SystemExit(worker.main())\n"
        )

        async def spawn(*args, **kw):
            assert args == (sys.executable, "-I", "-m", "app.options.entry_judgment_worker")
            return await real(sys.executable, "-I", "-c", source, **kw)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        received = asyncio.run(run_entry_process(request, "fixture-only"))
        assert received.error is None and received.plan.scope is True
        assert received.usage.input_tokens == 1000
        content = request_content(request)
        assert content["tools"] == [] and content["text"]["format"]["strict"] is True
        assert "scope_candidate_id" in content["input"]


def test_shared_model_can_choose_scope_without_degen_admission(tmp_path, monkeypatch):
    from decimal import Decimal

    with ai_owner(tmp_path, monkeypatch) as (c, _v, _times, f, state):
        u = f.underlyings[0].model_copy(update={"bid": Decimal(599), "ask": Decimal(599)})
        result = asyncio.run(c.cycle(f.model_copy(update={"underlyings": (u,)})))
        assert result["status"] == "OPEN", result
        assert (
            not state["request"].packet.opportunities and state["request"].packet.scope is not None
        )


def test_unknown_model_cost_isolated_from_another_ai_owner(tmp_path, monkeypatch):
    with (
        ai_owner(tmp_path / "a", monkeypatch) as (a, _va, _ta, fa, _sa),
        ai_owner(tmp_path / "b", monkeypatch) as (b, _vb, _tb, fb, _sb),
    ):

        async def lost(*args, **kw):
            raise RuntimeError("fixture lost usage")

        monkeypatch.setattr(a, "_model_run", lost)
        assert asyncio.run(a.cycle(fa))["status"] == "HOLD"
        assert asyncio.run(b.cycle(fb))["status"] == "OPEN"
        with a.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()


def test_later_fresh_admission_cannot_extend_native_expiry(tmp_path, monkeypatch):
    from datetime import datetime

    with ai_owner(tmp_path, monkeypatch) as (c, _v, times, f, _state):
        dispatch = c.engine.dispatch

        async def pause(*args, **kw):
            return "PREPARED"

        monkeypatch.setattr(c.engine, "dispatch", pause)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "PREPARED", result
        times[0] = datetime.fromisoformat(result["scope_candidate"]["binding"]["valid_until"])
        assert times[0] < datetime.fromisoformat(
            result["scope_fresh_candidate"]["binding"]["valid_until"]
        )
        fresh = awaitable_refresh(c, "first")
        assert (
            asyncio.run(
                dispatch(result["client_id"], fresh.frame.quote, fresh.underlying, now=times[0])
            )
            == "REJECTED"
        )
        with c.engine.journal.read() as db:
            assert db.execute("SELECT attempted_at FROM execution_orders").fetchone()[0] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("condition", "NOW"),
        ("underlying_target", "102"),
        ("underlying_invalidation", "99"),
        ("horizon_seconds", 60),
        ("quantity", 1),
    ],
)
def test_scope_model_cannot_replace_trading_terms(field, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SharedScopeEntryPlan.model_validate(
            {
                "scope": True,
                "action": "ENTER",
                "candidate_id": "a" * 64,
                "packet_hash": "b" * 64,
                "decision_id": "c" * 64,
                "evidence_ids": ["a" * 64],
                "thesis": "Fixed plan",
                "uncertainty": "Risk",
                field: value,
            }
        )


@pytest.mark.parametrize("scope_only", [True, False])
def test_paid_family_gate_includes_only_verified_scope_alternatives(
    tmp_path, monkeypatch, scope_only
):
    from decimal import Decimal

    from app.options.loss_control import model_family_reasons

    with ai_owner(tmp_path, monkeypatch) as (c, _v, _times, f, _state):
        if scope_only:
            u = f.underlyings[0].model_copy(update={"bid": Decimal(599), "ask": Decimal(599)})
            f = f.model_copy(update={"underlyings": (u,)})
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        key = result["cycle_key"]
        with c.engine.journal.read() as db:
            state = {
                "families": [
                    {"family": "DEGEN", "reasons": ["paused"]},
                    {"family": "SCOPE", "reasons": []},
                ]
            }
            assert model_family_reasons(c.engine, db, key, state) == []
            state["families"][1]["reasons"] = ["paused"]
            assert model_family_reasons(c.engine, db, key, state) == [
                "NATIVE_FAMILY_MODEL_ENTRY_PAUSED"
            ]
        with c.engine.journal.write() as db:
            import json

            data = json.loads(
                db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0]
            )
            data["scope_candidate"]["binding_hash"] = "0" * 64
            db.execute(
                "UPDATE execution_option_opportunities SET result_json=?", (json.dumps(data),)
            )
            assert model_family_reasons(c.engine, db, key, {"families": []}) == [
                "NATIVE_FAMILY_MODEL_CANDIDATES_REQUIRED"
            ]


def test_scope_refresh_is_bounded_by_original_remaining_lease(tmp_path, monkeypatch):
    with ai_owner(tmp_path, monkeypatch) as (c, _v, times, f, _state):
        run = c._model_run

        async def delayed_model(*args, **kw):
            result = await run(*args, **kw)
            times[0] += timedelta(seconds=3.9)
            return result

        async def stalled_reader(play):
            await asyncio.sleep(30)
            raise AssertionError("Reader must be cancelled")

        monkeypatch.setattr(c, "_model_run", delayed_model)
        monkeypatch.setattr(c, "scope_refresh", stalled_reader)
        result = asyncio.run(c.cycle(f))
        assert result["reason"] == "SCOPE_FRESH_EVIDENCE_TIMEOUT", result
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is not None
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()


def test_shorter_shared_packet_deadline_caps_scope_native_approval(tmp_path, monkeypatch):
    from datetime import datetime

    with ai_owner(tmp_path, monkeypatch) as (c, _v, times, f, state):
        from app.options import entry_coordination

        packet_type = entry_coordination.EntryPacket

        def shorter(**kwargs):
            kwargs["valid_until"] = min(
                kwargs["valid_until"], kwargs["as_of"] + timedelta(seconds=3)
            )
            return packet_type(**kwargs)

        monkeypatch.setattr(entry_coordination, "EntryPacket", shorter)
        dispatch = c.engine.dispatch

        async def pause(*args, **kw):
            return "PREPARED"

        monkeypatch.setattr(c.engine, "dispatch", pause)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "PREPARED", result
        deadline = state["request"].packet.valid_until
        assert deadline < state["request"].packet.scope.binding.valid_until
        assert datetime.fromisoformat(result["prepared"]["admission"]["valid_until"]) == deadline
        times[0] = deadline
        fresh = awaitable_refresh(c, "first")
        assert (
            asyncio.run(
                dispatch(result["client_id"], fresh.frame.quote, fresh.underlying, now=times[0])
            )
            == "REJECTED"
        )


def test_real_clock_progress_between_family_scans_and_scope_admission(tmp_path, monkeypatch):
    from test_option_scope_watch import ready, revision

    with ai_owner(tmp_path, monkeypatch) as (c, v, times, f, state):
        sampled = times[0] - timedelta(seconds=1)
        ready(c.engine, v, sampled)
        frame, context = refresh(f.scope.frame, sampled)
        c.scope_book.observe_arming(
            "pre-read-sample",
            "first",
            frame=frame,
            context=context,
            now=sampled,
            expected_revision=revision(c.engine),
        )
        admit = c.scope_book.review_admission

        def advancing(key, *args, **kw):
            if key.startswith("shared:"):
                times[0] += timedelta(milliseconds=200)
                kw["now"] = times[0]
            return admit(key, *args, **kw)

        monkeypatch.setattr(c.scope_book, "review_admission", advancing)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        packet = state["request"].packet
        assert packet.as_of < packet.scope.binding.evaluated_at < packet.valid_until
        from app.options.entry_judgment import create_request

        with pytest.raises(ValueError):
            create_request(
                packet, state["request"].configuration, request_id="d" * 32, now=packet.as_of
            )
