"""Shared Scope management stays bound to native ownership and all paid costs."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_execution import intent_for, ledger
from test_option_scope_ai import ai_owner
from test_option_scope_arming import refresh
from test_option_scope_context import bind
from test_option_scope_structure import bind as bind_structure

from app.execution.economics import UsageEvidence
from app.options import position_judgment as judgment
from app.options.engine import fingerprint
from app.options.position_reasoning import PositionPlan, PositionReasoningPolicy


def management_frame(f, at):
    sf = f.scope.frame
    histories = []
    for h in sf.histories:
        bars = list(h.bars)
        while bars[-1].ends_at + timedelta(minutes=5) <= at:
            b = bars[-1]
            bars.append(
                b.model_copy(
                    update={
                        "begins_at": b.ends_at,
                        "open": b.close,
                        "high": b.close,
                        "low": b.close,
                    }
                )
            )
        histories.append(h.model_copy(update={"bars": tuple(bars)}))
    sf = sf.model_copy(update={"histories": tuple(histories)})
    sf, context = refresh(sf, at)
    context = context.model_copy(
        update={
            "prior": f.scope.context.prior,
            "previous_session": f.scope.context.previous_session,
        }
    )
    sf = bind(bind_structure(sf), context)
    u = f.scope.underlying.model_copy(update={"source_at": at, "received_at": at})
    return f.model_copy(
        update={
            "scope": f.scope.model_copy(update={"frame": sf, "context": context, "underlying": u})
        }
    )


def enter(c, v, times, f):
    result = asyncio.run(c.cycle(f))
    assert result["status"] == "OPEN", result
    buy = intent_for(c.engine, result["client_id"])
    q = f.scope.frame.quote.model_copy(update={"source_at": times[0], "received_at": times[0]})
    u = f.scope.underlying.model_copy(update={"source_at": times[0], "received_at": times[0]})
    v.fill(buy, buy.quantity, q, times[0], fill_id="scope-entry", underlying=u)
    assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
    times[0] = times[0].replace(second=0, microsecond=0) + timedelta(minutes=5)
    return buy, management_frame(f, times[0])


def fake_model(monkeypatch, action, *, after=None):
    calls = []

    async def run(request, key):
        p = request.packet
        stop = (
            p.position.tightened_underlying_invalidation
            + (p.underlying.bid if p.position.contract.right == "CALL" else p.underlying.ask)
        ) / 2
        plan = PositionPlan(
            decision_id=p.decision_id,
            packet_hash=fingerprint(p),
            entry_client_id=p.position.entry_client_id,
            position_revision=p.position_revision,
            action=action,
            underlying_invalidation=stop if action == "TIGHTEN" else None,
            evidence_ids=(p.evidence_ids[0], p.evidence_ids[5]),
            thesis="Fixture held Scope thesis",
            change_since_entry="Completed context refreshed",
            uncertainty="Fixture evidence only",
        )
        result = judgment.result_for(
            request,
            plan=plan,
            count=1000,
            usage=UsageEvidence(
                request_id="scope-manage",
                model=request.configuration.costs.model,
                input_tokens=1000,
                output_tokens=100,
            ),
        )
        calls.append((request, result))
        if after:
            after(request, result)
        return result

    monkeypatch.setattr(judgment, "run_position_process", run)
    return calls


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_scope_native_management(tmp_path, monkeypatch, right, action):
    from test_option_position_outcome import read_owned
    from test_option_scope_execution import sell

    from app.options.attribution import decision_attribution
    from app.options.scope_execution_export import (
        export_scope_execution,
        verify_scope_execution_export,
    )

    policy = PositionReasoningPolicy(
        max_lease_seconds=5, scope_management="scope-fixed-position-v1"
    )
    with ai_owner(tmp_path, monkeypatch, right=right, position_policy=policy) as (
        c,
        v,
        times,
        f,
        _,
    ):
        buy, current = enter(c, v, times, f)
        if action == "MAINTAIN":
            assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
            asyncio.run(c.supervise((current.scope.frame.quote,), (current.scope.underlying,)))
            sell(
                c.engine,
                v,
                buy,
                current.scope.frame.quote,
                current.scope.underlying,
                times[0],
                key="scale-before-management",
                quantity=1,
            )
        original = ledger(c.engine).position
        calls = fake_model(monkeypatch, action)
        result = asyncio.run(c.cycle(current))
        assert (
            result["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), result
        assert len(calls) == 1
        assert asyncio.run(c.cycle(current)) == result
        packet = calls[0][0].packet
        assert packet.scope_context.original.binding.play_key == "first"
        assert packet.scan == packet.scope_context.scan
        assert packet.scope_context.selection.thesis == "Fixture fixed Scope selection"
        p = ledger(c.engine).position
        for name in (
            "target_exit_schedule",
            "entry_premium_protection",
            "entry_time_protection",
            "exit_at",
            "original_underlying_invalidation",
        ):
            assert getattr(p, name) == getattr(original, name)
        with c.engine.journal.read() as db:
            attr = decision_attribution(db, result["cycle_key"], result, c.engine.policy)
            assert attr.role == "MANAGEMENT" and attr.entry_client_id == buy.client_id
            assert attr.model_cost == Decimal(".00015")
        q, u = current.scope.frame.quote, current.scope.underlying
        if action == "EXIT_ALL":
            close = intent_for(c.engine, result["client_id"])
            v.fill(close, close.quantity, q, times[0], fill_id="scope-exit", underlying=u)
            assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        else:
            sell(c.engine, v, buy, q, u, times[0], key="final")
        outcome = read_owned(c.engine, buy)
        assert not outcome["reasons"], outcome
        assert Decimal(outcome["known_model_cost"]) == Decimal(".00030")
        exported = export_scope_execution(
            c.engine.journal, now=times[0], data_cost=".01", host_cost=".02"
        )
        assert (
            verify_scope_execution_export(exported, exported["export_hash"])["status"]
            == "VERIFIED_NATIVE_ACCOUNTING"
        )


@pytest.mark.parametrize("fault", ["missing", "foreign_play", "stale", "foreign_quote", "payload"])
def test_scope_context_failure_starts_no_management_call(tmp_path, monkeypatch, fault):
    policy = PositionReasoningPolicy(
        max_lease_seconds=5, scope_management="scope-fixed-position-v1"
    )
    with ai_owner(tmp_path, monkeypatch, position_policy=policy) as (c, v, times, f, _):
        _, current = enter(c, v, times, f)
        calls = fake_model(monkeypatch, "MAINTAIN")
        s = current.scope
        if fault == "missing":
            current = current.model_copy(update={"scope": None})
        elif fault == "foreign_play":
            current = current.model_copy(
                update={"scope": s.model_copy(update={"play_key": "foreign"})}
            )
        elif fault == "stale":
            current = current.model_copy(
                update={"scope": s.model_copy(update={"context": f.scope.context})}
            )
        elif fault == "foreign_quote":
            current = current.model_copy(
                update={
                    "scope": s.model_copy(
                        update={"frame": s.frame.model_copy(update={"quote": current.quotes[0]})}
                    )
                }
            )
        else:
            evidence = s.frame.evidence
            current = current.model_copy(
                update={
                    "scope": s.model_copy(
                        update={
                            "frame": s.frame.model_copy(
                                update={
                                    "evidence": tuple(
                                        e.model_copy(update={"payload_hash": "0" * 64})
                                        if e.kind == "technical_structure"
                                        else e
                                        for e in evidence
                                    )
                                }
                            )
                        }
                    )
                }
            )
        result = asyncio.run(c.cycle(current))
        assert not calls, result
        with c.engine.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 1


@pytest.mark.parametrize("fault", ["late", "unknown", "stop"])
def test_paid_scope_management_failure_and_independent_protection(tmp_path, monkeypatch, fault):
    policy = PositionReasoningPolicy(
        max_lease_seconds=5, scope_management="scope-fixed-position-v1"
    )
    with ai_owner(tmp_path, monkeypatch, position_policy=policy) as (c, v, times, f, _):
        _, current = enter(c, v, times, f)

        def after(request, result):
            if fault == "late":
                times[0] += timedelta(seconds=6)
            elif fault == "unknown":
                raise ValueError("fixture response lost")
            else:
                u = current.scope.underlying
                price = request.packet.position.original_underlying_invalidation
                c._position_underlyings = (
                    u.model_copy(update={"bid": price, "ask": price + Decimal(".1")}),
                )

        fake_model(monkeypatch, "MAINTAIN", after=after)
        result = asyncio.run(c.cycle(current))
        assert result["status"] in {"HELD", "MANDATORY_EXIT", "REJECTED"}, result
        with c.engine.journal.read() as db:
            costs = [
                r[0] for r in db.execute("SELECT cost FROM execution_model_calls ORDER BY rowid")
            ]
            assert len(costs) == 2
            assert (costs[1] is None) == (fault == "unknown")
        if fault == "stop":
            assert ledger(c.engine).position.exit_reason == "UNDERLYING_INVALIDATION"


def test_scope_management_requires_explicit_policy(tmp_path, monkeypatch):
    with (
        pytest.raises(ValueError, match="matching enrollment"),
        ai_owner(
            tmp_path, monkeypatch, position_policy=PositionReasoningPolicy(max_lease_seconds=5)
        ),
    ):
        pass


def test_scope_management_packet_restart_worker_and_tamper(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    from pydantic import ValidationError
    from test_execution_judgment import response

    from app.options.coordinator import DegenCoordinator
    from app.options.engine import OptionExecution
    from app.options.position_reasoning import PositionPacket
    from app.options.scope_position import verify_owned_context

    policy = PositionReasoningPolicy(
        max_lease_seconds=5, scope_management="scope-fixed-position-v1"
    )
    with ai_owner(tmp_path, monkeypatch, position_policy=policy) as (c, v, times, f, _):
        buy, current = enter(c, v, times, f)
        path, limits, owner_policy = c.engine.journal.path, c.engine.limits, c.engine.policy
    with OptionExecution.open(path, limits, owner_policy, v, now=times[0]) as engine:
        c = DegenCoordinator(
            engine,
            c.policy,
            c.selection,
            clock=lambda: times[0],
            scope_policy=c.scope_policy,
            scope_refresh=c.scope_refresh,
            judgment_limits=c.judgment_limits,
            key_file=c.key_file,
            entry_policy=c.entry_policy,
            position_policy=c.position_policy,
        )
        monkeypatch.setattr(c, "_model_secret", lambda: "fixture-never-transmitted")
        calls = fake_model(monkeypatch, "MAINTAIN")
        out = asyncio.run(c.cycle(current))
        assert out["status"] == "MAINTAIN", out
        request, _ = calls[0]
        packet = request.packet
        for changes in (
            {"scope_context": None},
            {
                "scan": packet.scope_context.scan.model_copy(
                    update={"evaluated_at": times[0] + timedelta(seconds=1)}
                )
            },
            {
                "scope_context": packet.scope_context.model_copy(
                    update={"current": current.scope.model_copy(update={"play_key": "other"})}
                )
            },
        ):
            with pytest.raises(ValidationError):
                PositionPacket.model_validate(
                    packet.model_copy(update=changes).model_dump(warnings=False)
                )
        with c.engine.journal.read() as db:
            verify_owned_context(db, packet)
        # Actual installed worker entry point; SDK HTTP transport remains a fixture.
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
        # Recreate only the pure worker lease, never a second durable attempt.
        renewed = judgment.create_request(
            packet, request.configuration, request_id="d" * 32, now=packet.as_of
        )
        # fake_model replaced this symbol; invoke the original module function saved below.
        result = asyncio.run(REAL_WORKER(renewed, "fixture-never-transmitted"))
        assert result.error is None and result.plan.action == "MAINTAIN"
        with c.engine.journal.write() as db:
            db.execute(
                "UPDATE execution_orders SET intent_json=json_set(intent_json,'$.thesis','changed') WHERE client_id=?",
                (buy.client_id,),
            )
            with pytest.raises(ValueError):
                verify_owned_context(db, packet)


REAL_WORKER = judgment.run_position_process


@pytest.mark.parametrize("family", ["DEGEN", "SWING"])
def test_shared_scope_management_owner_retains_other_families(tmp_path, monkeypatch, family):
    policy = PositionReasoningPolicy(
        max_lease_seconds=5, scope_management="scope-fixed-position-v1"
    )
    with ai_owner(tmp_path, monkeypatch, family=family, position_policy=policy) as (
        c,
        v,
        times,
        f,
        _,
    ):
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        buy = intent_for(c.engine, result["client_id"])
        q = next(q for q in f.quotes if q.instrument == buy.instrument)
        u = next(u for u in f.underlyings if u.symbol == buy.instrument.contract.underlying)
        clocks = {"source_at": times[0], "received_at": times[0]}
        v.fill(
            buy,
            buy.quantity,
            q.model_copy(update=clocks),
            times[0],
            fill_id="other-entry",
            underlying=u.model_copy(update=clocks),
        )
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] = times[0].replace(second=0, microsecond=0) + timedelta(minutes=5)
        clocks = {"source_at": times[0], "received_at": times[0]}
        histories = []
        for h in f.histories:
            bars = list(h.bars)
            while bars[-1].ends_at + timedelta(minutes=5) <= times[0]:
                b = bars[-1]
                bars.append(
                    b.model_copy(
                        update={
                            "begins_at": b.ends_at,
                            "open": b.close,
                            "high": b.close,
                            "low": b.close,
                        }
                    )
                )
            histories.append(h.model_copy(update=clocks | {"bars": tuple(bars)}))
        current = f.model_copy(
            update={
                "histories": tuple(histories),
                "quotes": (q.model_copy(update=clocks),),
                "underlyings": (u.model_copy(update=clocks),),
            }
        )
        calls = fake_model(monkeypatch, "MAINTAIN")
        managed = asyncio.run(c.cycle(current))
        assert managed["status"] == "MAINTAIN", managed
        assert len(calls) == 1 and calls[0][0].packet.scope_context is None
        assert calls[0][0].packet.entry.entry_lineage.family == family
