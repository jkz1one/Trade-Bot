"""Native paid Scope replay: delivered fresh inputs, original leases and actual fills."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_entry_reasoning import packet_for
from test_option_scope_arming import refresh
from test_option_scope_context import bind
from test_option_scope_market_tape import record
from test_option_scope_position import management_frame
from test_option_scope_trading_replay import request as baseline

from app.execution.economics import CostPolicy
from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenFrame
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.scope_execution_export import verify_scope_execution_export
from app.options.scope_model_replay import ScopeModelReplay, run_scope_model_replay
from app.options.scope_replay_model import ScopeReplayScript, ScopeScriptedDecision


def request(
    tmp_path,
    *,
    arm="C",
    right="CALL",
    action="ENTER",
    delay=1,
    management="EXIT_ALL",
    fresh=True,
    protect_pending=False,
):
    old = baseline(tmp_path, right)
    cycle = next(e for e in old.tape.events if e.kind == "CYCLE")
    item = cycle.frame.scope
    at = cycle.recorded_at
    frames = [(e.recorded_at, e.kind, e.frame) for e in old.tape.events if e.recorded_at <= at]
    when = at + timedelta(seconds=1)
    f, context = refresh(item.frame, when)
    context = context.model_copy(
        update={"prior": item.context.prior, "previous_session": item.context.previous_session}
    )
    f = bind(f, context)
    updated = item.model_copy(
        update={
            "frame": f,
            "context": context,
            "underlying": item.underlying.model_copy(
                update={"source_at": when, "received_at": when}
            ),
        }
    )
    if fresh:
        frames.append((when, "SCOPE", DegenFrame(scope=updated)))
    for e in old.tape.events:
        if e.recorded_at <= at:
            continue
        when = e.recorded_at + (
            timedelta(seconds=1) if e.recorded_at == at + timedelta(seconds=1) else timedelta()
        )
        frame = e.frame.model_copy(
            update={
                "quotes": tuple(
                    q.model_copy(update={"source_at": when, "received_at": when})
                    for q in e.frame.quotes
                ),
                "underlyings": tuple(
                    u.model_copy(update={"source_at": when, "received_at": when})
                    for u in e.frame.underlyings
                ),
            }
        )
        frames.append((when, e.kind, frame))
    manage_at = at.replace(second=0, microsecond=0) + timedelta(minutes=5)
    current = management_frame(cycle.frame, manage_at).scope
    frames.append((manage_at, "CYCLE", DegenFrame(scope=current)))
    for seconds in (1, 2):
        when = manage_at + timedelta(seconds=seconds)
        frames.append(
            (
                when,
                "MARKET",
                DegenFrame(
                    quotes=(
                        current.frame.quote.model_copy(
                            update={"source_at": when, "received_at": when}
                        ),
                    ),
                    underlyings=(
                        current.underlying.model_copy(
                            update={
                                "source_at": when,
                                "received_at": when,
                                **(
                                    {
                                        "bid": Decimal("99" if right == "CALL" else "101"),
                                        "ask": Decimal("99" if right == "CALL" else "101"),
                                    }
                                    if protect_pending
                                    else {}
                                ),
                            }
                        ),
                    ),
                ),
            )
        )
    frames.sort(key=lambda x: x[0])
    tape = record(tmp_path / "model.tape", old.tape.header, frames)
    decisions = [
        ScopeScriptedDecision(
            cycle_key=cycle.cycle_key, delay_seconds=delay, action=action, scope=action == "ENTER"
        )
    ]
    if arm == "D":
        stop = (
            (Decimal(100) + current.underlying.bid) / 2
            if right == "CALL"
            else (Decimal(100) + current.underlying.ask) / 2
        )
        decisions.append(
            ScopeScriptedDecision(
                cycle_key="position:" + str(int(manage_at.timestamp()) // 300),
                delay_seconds=2 if protect_pending else 1,
                action=management,
                **({"underlying_invalidation": stop} if management == "TIGHTEN" else {}),
            )
        )
    return ScopeModelReplay(
        tape=tape,
        limits=old.limits,
        watch_actions=old.watch_actions,
        execution=old.execution.model_copy(
            update={
                "scope_arbitration": "shared-scope-entry-v1",
                "cost_policy": CostPolicy(total_budget="1", daily_budget=".1"),
            }
        ),
        scope=old.scope.model_copy(update={"version": "shared-scope-entry-v1"}),
        script=ScopeReplayScript(arm=arm, decisions=tuple(decisions)),
        judgment_limits=JudgmentLimits(process_timeout_seconds=5, request_timeout_seconds=3),
        entry_policy=packet_for(right).policy.model_copy(
            update={"scope_selection": "scope-fixed-plan-v1"}
        ),
        position_policy=PositionReasoningPolicy(
            max_lease_seconds=5, scope_management="scope-fixed-position-v1"
        )
        if arm == "D"
        else None,
        data_cost=".01",
        host_cost=".02",
    )


def rows(path, table):
    with sqlite3.connect(path / "options.db") as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM " + table)]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "arm,management", [("C", "EXIT_ALL"), ("D", "MAINTAIN"), ("D", "TIGHTEN"), ("D", "EXIT_ALL")]
)
def test_native_cd_paid_entry_management_and_full_cost_export(tmp_path, right, arm, management):
    req = request(tmp_path, arm=arm, right=right, management=management)
    home = tmp_path / "run"
    report = asyncio.run(run_scope_model_replay(req, home))
    a = report["accounting"]
    assert a["status"] == "COMPLETE_FLAT_ACCOUNTING", a
    assert len(a["orders"]) == 2, a
    assert Decimal(a["execution_fees"]) > 0
    calls = rows(home, "execution_model_calls")
    assert len(calls) == (2 if arm == "D" else 1)
    assert all(Decimal(c["cost"]) > 0 for c in calls)
    assert Decimal(a["net_after_all_costs"]) == Decimal(
        a["ledger"]["cash"]
    ) - req.execution.capital - sum(Decimal(c["cost"]) for c in calls) - Decimal(".03")
    cycles = [json.loads(r["result_json"]) for r in rows(home, "execution_option_opportunities")]
    entry = next(c for c in cycles if "scope_paid_review" in c)
    assert entry["entry_timely"] is True
    assert entry["status"] == "OPEN"
    assert rows(home, "execution_control")[0]["halted"] == 0
    assert entry["scope_paid_review"]["model_charge"]["cost"] != "0"
    assert (
        entry["scope_fresh_candidate"]["binding"]["revision"]
        > entry["scope_candidate"]["binding"]["revision"]
    )
    assert report["fresh_reads"][0]["sequence"] == next(
        e.sequence
        for e in req.tape.events
        if e.recorded_at
        == next(e.recorded_at for e in req.tape.events if e.kind == "CYCLE") + timedelta(seconds=1)
    )
    orders = rows(home, "execution_orders")
    buy = next(
        json.loads(r["intent_json"])
        for r in orders
        if json.loads(r["intent_json"])["side"] == "BUY"
    )
    original = entry["entry_request"]["packet"]["valid_until"]
    assert buy["approval_expires_at"] <= original
    if arm == "D":
        managed = next(c for c in cycles if "position_result" in c)
        assert managed["position_timely"] is True
        assert managed["position_result"]["plan"]["action"] == management
        assert managed["position_result"]["error"] is None, managed
    export = json.loads((home / "native.json").read_text())
    assert (
        verify_scope_execution_export(export, report["export_hash"])["status"]
        == "VERIFIED_NATIVE_ACCOUNTING"
    )
    assert report == json.loads((home / "report.json").read_text())
    assert not report["comparison_complete"] and not report["live_enabled"]


@pytest.mark.parametrize("variant", ["late", "hold", "unknown", "missing", "stale"])
def test_rejected_entry_never_erases_charges_or_creates_fills(tmp_path, variant):
    req = request(
        tmp_path,
        action={"hold": "HOLD", "unknown": "UNKNOWN"}.get(variant, "ENTER"),
        delay=5 if variant == "late" else 1,
        fresh=variant != "stale",
    )
    # A rejected entry leaves no holding to manage. Keep later observations but
    # do not request a held-only management cycle on a flat account.
    first = next(e for e in req.tape.events if e.kind == "CYCLE")
    frames = [
        (e.recorded_at, "SCOPE" if e.kind == "CYCLE" and e != first else e.kind, e.frame)
        for e in req.tape.events
    ]
    req = req.model_copy(
        update={"tape": record(tmp_path / "rejected.tape", req.tape.header, frames)}
    )
    if variant == "missing":
        req = req.model_copy(update={"script": req.script.model_copy(update={"decisions": ()})})
    home = tmp_path / "run"
    report = asyncio.run(run_scope_model_replay(req, home))
    if variant == "stale":
        assert len(report["fresh_reads"]) == 1
        evidence = json.loads(rows(home, "execution_option_opportunities")[0]["result_json"])
        assert evidence["reason"] == "SCOPE_POST_COST_ADMISSION_REJECTED"
        assert (
            "SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED"
            in evidence["scope_fresh_review"]["admission_review"]["reasons"]
        )
    else:
        assert report["fresh_reads"] == []
    if variant in {"unknown", "missing"}:
        assert report["accounting"]["net_after_all_costs"] is None
        assert report["accounting"]["model_costs"]["unknown_calls"]
    assert rows(home, "execution_orders") == []
    assert rows(home, "execution_fills") == []
    calls = rows(home, "execution_model_calls")
    assert len(calls) == 1
    if variant in {"unknown", "missing"}:
        assert calls[0]["cost"] is None
    else:
        assert Decimal(calls[0]["cost"]) > 0
    if variant == "late":
        evidence = json.loads(rows(home, "execution_option_opportunities")[0]["result_json"])
        assert evidence["entry_timely"] is False
        assert evidence["entry_result"]["plan"]["action"] == "ENTER"


@pytest.mark.parametrize(
    "variant", ["cost", "scope", "entry", "management", "carry", "tape", "hash"]
)
def test_unbound_or_mismatched_contracts_fail_before_output(tmp_path, variant):
    from app.options.scope_replay_enrollment import ScopeReplayEnrollment, validate_adapter
    from app.options.scope_replay_model import ScopeReplayModel

    req = request(tmp_path)
    if variant == "hash":
        with pytest.raises(ValueError, match="script enrollment"):
            validate_adapter(
                ScopeReplayEnrollment(
                    tape_hash="a" * 64, request_hash="b" * 64, script_hash="c" * 64
                ),
                ScopeReplayModel(req.script),
            )
        return
    changes = {
        "cost": {"execution": req.execution.model_copy(update={"cost_policy": None})},
        "scope": {"scope": req.scope.model_copy(update={"version": "shared-scope-selection-v1"})},
        "entry": {"entry_policy": req.entry_policy.model_copy(update={"scope_selection": None})},
        "management": {
            "position_policy": PositionReasoningPolicy(
                max_lease_seconds=5, scope_management="scope-fixed-position-v1"
            )
        },
        "carry": {
            "entry_policy": req.entry_policy.model_copy(update={"max_carry_horizon_seconds": 86400})
        },
        "tape": {
            "tape": req.tape.model_copy(
                update={"seal": req.tape.seal.model_copy(update={"last_hash": "0" * 64})}
            )
        },
    }
    home = tmp_path / "run"
    with pytest.raises(ValueError):
        asyncio.run(run_scope_model_replay(req.model_copy(update=changes[variant]), home))
    assert not home.exists()


@pytest.mark.parametrize("unknown", [False, True])
def test_pending_management_cannot_delay_mandatory_protection(tmp_path, unknown):
    req = request(
        tmp_path, arm="D", management="UNKNOWN" if unknown else "MAINTAIN", protect_pending=True
    )
    home = tmp_path / "run"
    report = asyncio.run(run_scope_model_replay(req, home))
    calls = rows(home, "execution_model_calls")
    assert len(calls) == 2
    assert report["accounting"]["ledger"]["position"] is None
    events = rows(home, "execution_events")
    consumed = [e for e in events if e["kind"] == "NATIVE_LOSS_OUTCOME_CONSUMED"]
    if unknown:
        assert calls[-1]["cost"] is None
        assert report["accounting"]["net_after_all_costs"] is None
        assert not consumed
    else:
        assert report["accounting"]["status"] == "COMPLETE_FLAT_ACCOUNTING"
        assert all(Decimal(c["cost"]) > 0 for c in calls)
        assert len(consumed) == 1
        terminal = [e for e in events if e["kind"] == "DEGEN_CYCLE_COMPLETED"][-1]
        assert consumed[0]["sequence"] > terminal["sequence"]
        assert consumed[0]["occurred_at"] == terminal["occurred_at"]
    sell = next(
        json.loads(r["intent_json"])
        for r in rows(home, "execution_orders")
        if json.loads(r["intent_json"])["side"] == "SELL"
    )
    assert "UNDERLYING_INVALIDATION" in sell["thesis"]
    from datetime import datetime

    manage_at = [e.recorded_at for e in req.tape.events if e.kind == "CYCLE"][-1]
    assert datetime.fromisoformat(sell["prepared_at"]) == manage_at + timedelta(seconds=1)
    managed = next(
        json.loads(r["result_json"])
        for r in rows(home, "execution_option_opportunities")
        if "position_result" in json.loads(r["result_json"])
    )
    assert datetime.fromisoformat(managed["position_completed_at"]) > datetime.fromisoformat(
        sell["prepared_at"]
    )


def test_frozen_enrollment_reopen_tamper_unknown_allocation_and_create_only(tmp_path):
    from app.execution.engine import ExecutionBlocked
    from app.options.coordinator import DegenCoordinator
    from app.options.engine import OptionExecution, fingerprint
    from app.options.scope_replay_enrollment import ScopeReplayEnrollment, validate_stored
    from app.options.scope_replay_model import ScopeReplayModel
    from app.options.venue import DurableOptionVenue

    req = request(tmp_path).model_copy(update={"host_cost": None})
    home = tmp_path / "run"
    report = asyncio.run(run_scope_model_replay(req, home))
    assert report["accounting"]["host_cost"] is None
    assert report["accounting"]["net_after_all_costs"] is None
    assert len(rows(home, "execution_fills")) == 2
    config = json.loads(rows(home, "execution_option_strategy")[0]["policy_json"])
    assert config["scope_replay"] == report["enrollment"]
    assert config["scope_replay"]["request_hash"] == fingerprint(req)
    for field in ("script_hash", "version"):
        altered = json.loads(json.dumps(config))
        altered["scope_replay"][field] = "0" * 64
        with pytest.raises(ExecutionBlocked):
            validate_stored(altered)
    for field in ("position_model", "replay_model", "scope_replay"):
        altered = json.loads(json.dumps(config))
        if field == "position_model":
            altered[field] = {}
        else:
            del altered[field]
        with pytest.raises(ExecutionBlocked):
            validate_stored(altered)
    venue = DurableOptionVenue(home / "venue.db")

    async def no_refresh(play):
        raise AssertionError("Restart must not refresh or retry")

    with OptionExecution.open(
        home / "options.db", req.limits, req.execution, venue, now=req.tape.header.closes_at
    ) as engine:
        c = DegenCoordinator(
            engine,
            req.tape.header.setup,
            req.tape.header.selection,
            clock=lambda: req.tape.header.closes_at,
            scope_policy=req.scope,
            swing_policy=req.tape.header.swing,
            scope_refresh=no_refresh,
            scope_replay=ScopeReplayEnrollment.model_validate(report["enrollment"]),
            replay_model=ScopeReplayModel(req.script),
            judgment_limits=req.judgment_limits,
            entry_policy=req.entry_policy,
        )
        first = next(e for e in req.tape.events if e.kind == "CYCLE")
        c.clock = lambda: first.recorded_at
        retained = asyncio.run(c.cycle(first.frame))
        assert retained == json.loads(
            rows(home, "execution_option_opportunities")[0]["result_json"]
        )
        assert c.replay_model.used == set()
        assert len(rows(home, "execution_model_calls")) == 1
    with pytest.raises(FileExistsError):
        asyncio.run(run_scope_model_replay(req, home))
    assert json.loads((home / "report.json").read_text()) == report
