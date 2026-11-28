"""Combined enrollment never converts Scope into carry or moves Swing's original exit."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_execution import intent_for, ledger
from test_option_scope_ai import ai_owner
from test_option_scope_arbitration import shared
from test_option_scope_position import enter, fake_model, management_frame

from app.options.engine import OptionExecution, fingerprint
from app.options.entry_reasoning import EntryReasoningPolicy, SharedScopeCarryEntryPlan, plan_class
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.runtime import OptionRuntime
from app.options.runtime_cli import _coordinator
from app.options.runtime_models import RuntimeSettings
from app.options.scope_carry import validate_enrollment
from app.options.scope_execution_export import export_scope_execution, verify_scope_execution_export


def management():
    return PositionReasoningPolicy(
        max_lease_seconds=5,
        scope_management="scope-fixed-position-v1",
        swing_carry="bounded-swing-carry-v1",
        scope_carry="shared-scope-carry-v1",
    )


def runtime_settings(c, path):
    from test_option_runtime import policy

    return RuntimeSettings(
        limits=c.engine.limits,
        execution=c.engine.policy,
        setup=c.policy,
        selection=c.selection,
        scope_policy=c.scope_policy,
        swing_policy=c.swing_policy,
        entry_policy=c.entry_policy,
        position_policy=c.position_policy,
        judgment_limits=c.judgment_limits,
        key_file=str(c.key_file) if c.key_file else None,
        runtime=policy(path, scope_inputs="scope-runtime-inputs-v1"),
    )


def next_session(f, at):
    delta = at.date() - f.histories[0].received_at.date()
    histories = tuple(
        h.model_copy(
            update={
                "source_at": at,
                "received_at": at,
                "bars": tuple(
                    b.model_copy(update={"begins_at": b.begins_at + delta}) for b in h.bars
                ),
            }
        )
        for h in f.histories
    )
    return f.model_copy(
        update={
            "histories": histories,
            "quotes": tuple(
                q.model_copy(update={"source_at": at, "received_at": at}) for q in f.quotes
            ),
            "underlyings": tuple(
                u.model_copy(update={"source_at": at, "received_at": at}) for u in f.underlyings
            ),
            "inventories": (),
            "swing": (),
            "scope": None,
        }
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("family", ["DEGEN", "SWING", "SCOPE"])
def test_combined_paid_entry_native_terms_and_export(tmp_path, monkeypatch, right, family):
    with ai_owner(tmp_path, monkeypatch, family=family, right=right, carry=True) as (
        c,
        v,
        t,
        f,
        state,
    ):
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "OPEN", out
        buy = intent_for(c.engine, out["client_id"])
        assert buy.entry_lineage.family == family
        p = state["request"].packet
        assert isinstance(plan_class(p.policy), type)
        assert state["request"].configuration.prompt_version == "shared-scope-carry-entry-v1"
        assert buy.approval_expires_at <= p.valid_until
        if family == "SWING":
            assert buy.swing_carry and buy.exit_at == buy.swing_carry.exit_at
            assert buy.exit_at.date().isoformat() == "2026-10-12"
            assert buy.order_expires_at.date() == p.as_of.date()
        else:
            assert buy.swing_carry is None and buy.exit_at.date() == p.as_of.date()
        if family == "SCOPE":
            assert out["scope_paid_review"]["model_charge"]["cost"] != "0"
            assert buy.exit_at <= f.scope.frame.session.protect_at
        q = (
            f.scope.frame.quote
            if family == "SCOPE"
            else next(q for q in f.quotes if q.instrument == buy.instrument)
        )
        u = f.scope.underlying if family == "SCOPE" else f.underlyings[0]
        q = q.model_copy(update={"source_at": t[0], "received_at": t[0]})
        u = u.model_copy(update={"source_at": t[0], "received_at": t[0]})
        v.fill(buy, buy.quantity, q, t[0], fill_id="combined-entry", underlying=u)
        assert c.engine.reconcile(v.snapshot(t[0]), now=t[0])["reconciled"]
        export = export_scope_execution(c.engine.journal, now=t[0])
        verified = verify_scope_execution_export(export, export["export_hash"])
        assert verified["accounting_status"] == "INCOMPLETE"
        assert export["report"]["net_after_all_costs"] is None
        assert export["report"]["shared_families"] == ["DEGEN", "SCOPE", "SWING"]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("family", ["SWING", "SCOPE"])
@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_combined_management_retains_per_position_context_and_costs(
    tmp_path, monkeypatch, right, family, action
):
    with ai_owner(
        tmp_path, monkeypatch, family=family, right=right, carry=True, position_policy=management()
    ) as (c, v, t, f, _):
        if family == "SCOPE":
            buy, current = enter(c, v, t, f)
        else:
            out = asyncio.run(c.cycle(f))
            assert out["status"] == "OPEN", out
            buy = intent_for(c.engine, out["client_id"])
            q = next(q for q in f.quotes if q.instrument == buy.instrument)
            v.fill(
                buy, buy.quantity, q, t[0], fill_id="combined-entry", underlying=f.underlyings[0]
            )
            assert c.engine.reconcile(v.snapshot(t[0]), now=t[0])["reconciled"]
            t[0] = t[0].replace(second=0, microsecond=0) + timedelta(days=3)
            current = next_session(f, t[0])
        calls = fake_model(monkeypatch, action)
        out = asyncio.run(c.cycle(current))
        assert (
            out["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), out
        assert len(calls) == 1
        packet = calls[0][0].packet
        assert calls[0][0].configuration.prompt_version == "option-position-scope-carry-v1"
        assert (packet.scope_context is not None) == (family == "SCOPE")
        assert (packet.carry_context is not None) == (family == "SWING")
        if family == "SCOPE":
            assert isinstance(packet.scope_context.selection, SharedScopeCarryEntryPlan)
            assert packet.scope_context.selection.thesis == "Fixture fixed Scope selection"
        else:
            assert packet.carry_context.overnight_coverage == "NOT_CONTINUOUSLY_OBSERVED"
            assert packet.position.swing_carry == buy.swing_carry
        assert packet.position.exit_at == buy.exit_at
        if action == "EXIT_ALL":
            sell = intent_for(c.engine, out["client_id"])
            q = (
                current.scope.frame.quote
                if family == "SCOPE"
                else next(q for q in current.quotes if q.instrument == buy.instrument)
            )
            v.fill(sell, sell.quantity, q, t[0], fill_id="combined-close")
            assert c.engine.reconcile(v.snapshot(t[0]), now=t[0])["reconciled"]
            assert ledger(c.engine).position is None
        with c.engine.journal.read() as db:
            charges = [Decimal(r[0]) for r in db.execute("SELECT cost FROM execution_model_calls")]
            assert len(charges) == 2 and all(x > 0 for x in charges)
        export = export_scope_execution(
            c.engine.journal, now=t[0], data_cost=".02", host_cost=".03"
        )
        verify_scope_execution_export(export, export["export_hash"])
        if action == "EXIT_ALL":
            report = export["report"]
            assert report["status"] == "COMPLETE_FLAT_ACCOUNTING", report["reasons"]
            assert Decimal(report["net_after_all_costs"]) == ledger(
                c.engine
            ).cash - c.engine.policy.capital - sum(charges) - Decimal(".05")


@pytest.mark.parametrize("family", ["SWING", "SCOPE"])
def test_runtime_restart_original_deadline_and_missing_feed_protection(
    tmp_path, monkeypatch, family
):
    from test_option_runtime import enable, step
    from test_option_scope_runtime import send

    with ai_owner(
        tmp_path, monkeypatch, family=family, carry=True, position_policy=management()
    ) as (c, v, t, f, _):
        s = runtime_settings(c, tmp_path)
        fixture_refresh = c.scope_refresh
        r = OptionRuntime(c, s.runtime, create=True)
        enable(r)
        c.scope_refresh = fixture_refresh
        out = asyncio.run(c.cycle(f))
        c.scope_refresh = r.scope.fresh
        assert out["status"] == "OPEN", out
        buy = intent_for(c.engine, out["client_id"])
        q = (
            f.scope.frame.quote
            if family == "SCOPE"
            else next(q for q in f.quotes if q.instrument == buy.instrument)
        )
        u = f.scope.underlying if family == "SCOPE" else f.underlyings[0]
        v.fill(buy, buy.quantity, q, t[0], fill_id="restart-entry", underlying=u)
        assert c.engine.reconcile(v.snapshot(t[0]), now=t[0])["reconciled"]
        path = c.engine.journal.path
    at = buy.exit_at
    with OptionExecution.open(path, s.limits, s.execution, v, now=at) as engine:
        c = _coordinator(engine, s, False, lambda: at)
        r = OptionRuntime(c, s.runtime)
        enable(r)
        assert ledger(engine).position.exit_at == buy.exit_at
        # No packet can erase the independently latched original deadline.
        asyncio.run(step(r))
        assert ledger(engine).position.exit_reason == "TIME_EXIT"
        if family == "SWING":
            assert c.scope_book.snapshot()["watches"][0]["status"] == "EXPIRED_UNFILLED"
        if family == "SCOPE":
            current = management_frame(f, at)
        else:
            current = next_session(f, at)
        from app.options.coordinator import DegenFrame

        current = DegenFrame(
            quotes=current.quotes, underlyings=current.underlyings, scope=current.scope
        )
        send(r, current, kind="MARKET")
        asyncio.run(step(r))
        with engine.journal.read() as db:
            sells = [
                intent_for(engine, row[0])
                for row in db.execute("SELECT client_id FROM execution_orders ORDER BY rowid")
            ]
        assert len(sells) == 2 and sells[-1].side == "SELL"
        assert sells[-1].exit_at == buy.exit_at


@pytest.mark.parametrize("part", ["owner", "scope", "swing", "entry", "position", "replay"])
def test_incomplete_combined_enrollment_rejected(tmp_path, monkeypatch, part):
    with ai_owner(tmp_path, monkeypatch, carry=True, position_policy=management()) as (
        c,
        _,
        _,
        _,
        _,
    ):
        parts = {
            "owner": c.engine.policy,
            "scope": c.scope_policy,
            "swing": c.swing_policy,
            "entry": c.entry_policy,
            "position": c.position_policy,
        }
        if part == "replay":
            parts["replay"] = True
        elif part == "swing":
            parts[part] = None
        else:
            parts[part] = parts[part].model_copy(update={"scope_carry": None})
        with pytest.raises(ValueError, match="matching shared Scope carry"):
            validate_enrollment(**parts)


def test_legacy_schema_serialization_and_unsupported_pairing():
    from test_option_entry_reasoning import packet_for

    from app.options import entry_judgment, position_judgment

    p = packet_for().policy
    assert "scope_carry" not in p.model_dump()
    assert entry_judgment.prompt_version(p) == "option-entry-thesis-v1"
    old = PositionReasoningPolicy(max_lease_seconds=5)
    assert "scope_carry" not in old.model_dump()
    assert position_judgment.instructions(old) == position_judgment.INSTRUCTIONS
    for marker in [None, "shared-scope-carry-v1"]:
        values = p.model_dump() | {
            "scope_selection": "scope-fixed-shortlist-v1",
            "max_carry_horizon_seconds": 600000,
            "scope_carry": marker,
        }
        with pytest.raises(ValueError):
            EntryReasoningPolicy.model_validate(values)
    with pytest.raises(ValueError):
        PositionReasoningPolicy(
            max_lease_seconds=5,
            scope_management="scope-fixed-position-v1",
            swing_carry="bounded-swing-carry-v1",
        )


def test_deterministic_combined_carry_and_stored_enrollment_tamper(tmp_path):
    with shared(tmp_path, priority=("SWING", "SCOPE", "DEGEN"), carry=True) as (c, _v, t, f):
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "OPEN", out
        assert intent_for(c.engine, out["client_id"]).swing_carry is not None
        value = export_scope_execution(c.engine.journal, now=t[0])
        # Rehashing an export cannot substitute an unmarked owner/strategy.
        row = value["evidence"]["execution_option_strategy"][0]
        config = json.loads(row[1])
        config["scope"].pop("scope_carry")
        row[1] = json.dumps(config)
        value["export_hash"] = fingerprint({k: v for k, v in value.items() if k != "export_hash"})
        with pytest.raises(ValueError):
            verify_scope_execution_export(value, value["export_hash"])


@pytest.mark.parametrize(
    "damage", ["degen_horizon", "swing_horizon", "swing_target", "scope_refresh"]
)
def test_combined_paid_rejection_does_not_relax_native_boundaries(tmp_path, monkeypatch, damage):
    family = (
        "SCOPE" if damage == "scope_refresh" else "DEGEN" if damage == "degen_horizon" else "SWING"
    )
    with ai_owner(tmp_path, monkeypatch, family=family, carry=True) as (c, _v, _t, f, _state):
        original = c._model_run

        async def changed(request, secret, *, broad):
            result = await original(request, secret, broad=broad)
            if damage == "scope_refresh":
                return result
            values = result.plan.model_dump()
            if damage == "degen_horizon":
                values["horizon_seconds"] = 600000
            elif damage == "swing_horizon":
                values["horizon_seconds"] += 60
            else:
                values["underlying_target"] += Decimal(1)
            from app.options.entry_judgment import result_for

            return result_for(
                request,
                plan=SharedScopeCarryEntryPlan.model_validate(values),
                count=result.counted_input_tokens,
                usage=result.usage,
            )

        monkeypatch.setattr(c, "_model_run", changed)
        if damage == "scope_refresh":

            async def missing(_play):
                return None

            c.scope_refresh = missing
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "HOLD", out
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()
            costs = [r[0] for r in db.execute("SELECT cost FROM execution_model_calls")]
            assert len(costs) == 1 and Decimal(costs[0]) > 0


def test_combined_scope_schema_never_accepts_replacement_terms():
    values = {
        "decision_id": "0" * 64,
        "packet_hash": "1" * 64,
        "action": "ENTER",
        "scope": True,
        "candidate_id": "2" * 64,
        "evidence_ids": ("2" * 64,),
        "thesis": "Fixed Scope",
        "uncertainty": "Fixture",
    }
    for field, value in [
        ("horizon_seconds", 600000),
        ("underlying_target", "610"),
        ("condition", "NOW"),
    ]:
        with pytest.raises(ValueError, match="fixed plan"):
            SharedScopeCarryEntryPlan(**values, **{field: value})


@pytest.mark.parametrize(
    "part", ["execution", "scope_policy", "entry_policy", "position_policy", "swing_policy"]
)
def test_runtime_combined_settings_require_matching_contracts(tmp_path, monkeypatch, part):
    with ai_owner(tmp_path, monkeypatch, carry=True, position_policy=management()) as (
        c,
        _,
        _,
        _,
        _,
    ):
        s = runtime_settings(c, tmp_path)
        values = s.model_dump()
        if part == "swing_policy":
            values[part] = None
        else:
            values[part].pop("scope_carry")
        with pytest.raises(ValueError):
            RuntimeSettings.model_validate(values)


@pytest.mark.parametrize("family", ["SWING", "SCOPE"])
def test_combined_entry_worker_uses_full_bound_schema_without_network(
    tmp_path, monkeypatch, family
):
    from test_execution_judgment import response, sdk_client

    from app.options.entry_judgment_worker import perform

    with ai_owner(tmp_path, monkeypatch, family=family, carry=True) as (c, _, _, f, _):
        original = c._model_run

        async def sdk(request, secret, *, broad):
            result = await original(request, secret, broad=broad)
            output = response()
            output["model"] = request.configuration.costs.model
            output["output"][0]["content"][0]["text"] = result.plan.model_dump_json()
            client, calls = sdk_client(output=output)
            with client:
                verified = perform(request, client)
            assert verified.error is None, verified
            assert isinstance(verified.plan, SharedScopeCarryEntryPlan)
            assert len(calls) == 2
            for _, body in calls:
                assert body["tools"] == [] and body["tool_choice"] == "none"
                assert body["text"]["format"]["strict"] is True
                assert "Only supplied Swing carry_terms" in body["instructions"]
                assert "Never replace Scope terms" in body["instructions"]
            return verified

        monkeypatch.setattr(c, "_model_run", sdk)
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "OPEN", out
