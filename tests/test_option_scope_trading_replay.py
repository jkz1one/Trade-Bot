"""Scope's deterministic baseline uses later tape receipts for actual native fills."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_scope_arming import refresh
from test_option_scope_market_tape import record
from test_option_scope_tape_watch import request as watch_request

from app.options.coordinator import DegenFrame
from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy, OptionExecutionPolicy
from app.options.scope_arbitration import SharedScopePolicy
from app.options.scope_execution_export import verify_scope_execution_export
from app.options.scope_trading_replay import ScopeTradingReplay, run_scope_trading_replay


def request(tmp_path, right="CALL", *, entry_fill=True, exit_fill=True, nested_fill=False):
    old = watch_request(tmp_path, right, expire=False)
    tape = old.scope_tape
    frames = [(e.recorded_at, e.kind, e.frame) for e in tape.events]
    item = tape.events[-1].frame.scope
    at = tape.events[-1].recorded_at + timedelta(seconds=1)
    f, context = refresh(item.frame, at)
    u = item.underlying.model_copy(update={"source_at": at, "received_at": at})
    fresh = item.model_copy(update={"frame": f, "context": context, "underlying": u})
    from test_degen_options import frame as degen_frame

    def align(value):
        if isinstance(value, dict):
            return {
                k: (
                    at.isoformat()
                    if k in {"source_at", "received_at"}
                    else "fixture-provider"
                    if k == "provider"
                    else "fixture-quote"
                    if k == "source" and "bid" in value and "instrument" in value
                    else align(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [align(v) for v in value]
        return value

    common = DegenFrame.model_validate(align(degen_frame(right).model_dump(mode="json")))
    frames.append((at, "CYCLE", common.model_copy(update={"scope": fresh})))
    for when, enabled in (
        (at + timedelta(seconds=1), entry_fill),
        (tape.header.scope.session.protect_at, True),
        (tape.header.scope.session.protect_at + timedelta(seconds=1), exit_fill),
    ):
        if not enabled:
            continue
        quote = f.quote.model_copy(update={"source_at": when, "received_at": when})
        underlying = u.model_copy(update={"source_at": when, "received_at": when})
        if nested_fill and when == at + timedelta(seconds=1):
            ff, cc = refresh(f, when)
            frame = DegenFrame(
                scope=fresh.model_copy(
                    update={"frame": ff, "context": cc, "underlying": underlying}
                )
            )
            kind = "SCOPE"
        else:
            frame, kind = DegenFrame(quotes=(quote,), underlyings=(underlying,)), "MARKET"
        frames.append((when, kind, frame))
    recorded = record(tmp_path / "trading.tape", tape.header, frames)
    policy = OptionExecutionPolicy.model_validate(
        old.execution.model_dump()
        | {
            "scope_arbitration": "shared-scope-selection-v1",
            "loss_control": NativeLossPolicy(
                max_consecutive_losses=2,
                cooldown_seconds=1800,
                families=tuple(
                    FamilyLossPolicy(family=f, max_consecutive_losses=2, cooldown_seconds=1800)
                    for f in ("SCOPE", "DEGEN")
                ),
            ),
        }
    )
    return ScopeTradingReplay(
        tape=recorded,
        limits=old.limits,
        execution=policy,
        scope=SharedScopePolicy(watch=old.watch, family_priority=("SCOPE", "DEGEN")),
        watch_actions=old.steps,
        data_cost=".01",
        host_cost=".02",
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_scope_baseline_native_later_fills_deadline_and_full_cost_export(tmp_path, right):
    req = request(tmp_path, right)
    report = asyncio.run(run_scope_trading_replay(req, tmp_path / "run"))
    account = report["accounting"]
    assert report["status"] == "COMPLETE_DETERMINISTIC_TAPE_REPLAY"
    assert report["arm"] == "A" and not report["comparison_complete"]
    assert account["status"] == "COMPLETE_FLAT_ACCOUNTING", account
    assert len(account["orders"]) == 2, account
    assert account["scope"]["watches"][0]["recorded_status"] == "CLOSED"
    assert Decimal(account["execution_fees"]) > 0
    assert Decimal(account["net_after_all_costs"]) == Decimal(
        account["ledger"]["cash"]
    ) - req.execution.capital - Decimal(".03")
    assert all(a["status"] == "RECORDED" for a in report["watch_actions"])
    exported = json.loads((tmp_path / "run/native.json").read_text())
    assert (
        verify_scope_execution_export(exported, report["export_hash"])["status"]
        == "VERIFIED_NATIVE_ACCOUNTING"
    )
    intents = [json.loads(r[3]) for r in exported["evidence"]["execution_orders"]]
    buy = next(i for i in intents if i["side"] == "BUY")
    sell = next(i for i in intents if i["side"] == "SELL")
    assert buy["entry_lineage"]["family"] == "SCOPE"
    assert "TIME_EXIT" in sell["thesis"]
    assert buy["exit_at"] == req.tape.header.scope.session.protect_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert exported["evidence"]["execution_model_calls"] == []
    assert json.loads((tmp_path / "run/report.json").read_text()) == report


def reseal(req, tmp_path, frames):
    return req.model_copy(
        update={"tape": record(tmp_path / "changed.tape", req.tape.header, frames)}
    )


@pytest.mark.parametrize(
    "variant", ["nested", "no-entry-fill", "no-exit-fill", "same-source-time", "partial-entry"]
)
def test_only_later_executable_receipts_fill_and_missing_exits_remain_open(tmp_path, variant):
    req = request(
        tmp_path,
        entry_fill=variant != "no-entry-fill",
        exit_fill=variant != "no-exit-fill",
        nested_fill=variant == "nested",
    )
    if variant in {"same-source-time", "partial-entry"}:
        frames = [(e.recorded_at, e.kind, e.frame) for e in req.tape.events]
        index = next(i for i, (_, kind, _) in enumerate(frames) if kind == "MARKET")
        at, kind, frame = frames[index]
        q = frame.quotes[0]
        if variant == "same-source-time":
            q = q.model_copy(update={"source_at": at - timedelta(seconds=1)})
        else:
            q = q.model_copy(update={"ask_size": 1})
        frames[index] = at, kind, frame.model_copy(update={"quotes": (q,)})
        if variant == "partial-entry":
            later = at + timedelta(seconds=1)
            frames.insert(
                index + 1,
                (
                    later,
                    kind,
                    DegenFrame(
                        quotes=(q.model_copy(update={"source_at": later, "received_at": later}),),
                        underlyings=(
                            frame.underlyings[0].model_copy(
                                update={"source_at": later, "received_at": later}
                            ),
                        ),
                    ),
                ),
            )
        req = reseal(req, tmp_path, frames)
    report = asyncio.run(run_scope_trading_replay(req, tmp_path / "run"))
    exported = json.loads((tmp_path / "run/native.json").read_text())
    fills = [json.loads(r[2]) for r in exported["evidence"]["execution_fills"]]
    if variant in {"no-entry-fill", "same-source-time"}:
        assert fills == []
        assert report["accounting"]["ledger"]["position"] is None
        assert Decimal(report["accounting"]["net_after_all_costs"]) == Decimal("-.03")
    elif variant == "no-exit-fill":
        assert len(fills) == 1
        assert report["accounting"]["ledger"]["position"] is not None
        assert report["accounting"]["net_after_all_costs"] is None
        assert "OPEN_POSITION" in report["accounting"]["reasons"]
    else:
        assert len(fills) == (3 if variant == "partial-entry" else 2)
        assert report["accounting"]["scope"]["watches"][0]["recorded_status"] == "CLOSED"


@pytest.mark.parametrize("cost", ["data_cost", "host_cost"])
def test_unknown_operating_cost_withholds_net_after_actual_trading(tmp_path, cost):
    req = request(tmp_path).model_copy(update={cost: None})
    report = asyncio.run(run_scope_trading_replay(req, tmp_path / "run"))
    assert len(report["accounting"]["orders"]) == 2
    assert report["accounting"][cost] is None
    assert report["accounting"]["net_after_all_costs"] is None


def test_timer_only_watch_expiry_runs_without_new_market_receipt(tmp_path):
    from app.options.scope_tape_watch import ScopeTapeWatchAction

    req = request(tmp_path)
    frames = [(e.recorded_at, e.kind, e.frame) for e in req.tape.events if e.kind == "SCOPE"]
    req = reseal(req, tmp_path, frames)
    expiry = ScopeTapeWatchAction(
        key="expiry",
        kind="ADVANCE",
        play_key="first",
        at=req.tape.header.scope.session.entry_cutoff_at,
    )
    req = req.model_copy(update={"watch_actions": (*req.watch_actions, expiry)})
    report = asyncio.run(run_scope_trading_replay(req, tmp_path / "run"))
    assert report["watch_actions"][-1]["receipt"]["record"]["status"] == "EXPIRED_UNFILLED"
    assert report["watch_actions"][-1]["binding"]["event_hash"] is None
    assert report["accounting"]["orders"] == []


def test_equal_time_future_receipt_cannot_call_watch_before_earlier_cycle(tmp_path):
    req = request(tmp_path)
    cycle = next(e for e in req.tape.events if e.kind == "CYCLE")
    frame = cycle.frame
    at = cycle.recorded_at
    tape = record(
        tmp_path / "same-time.tape",
        req.tape.header,
        [
            (at, "CYCLE", frame),
            (at, "SCOPE", DegenFrame(scope=frame.scope)),
        ],
    )
    action = req.watch_actions[0].model_copy(update={"at": at, "sequence": 2})
    req = req.model_copy(update={"tape": tape, "watch_actions": (action,)})
    import sqlite3

    with pytest.raises(ValueError, match="native cycle failed"):
        asyncio.run(run_scope_trading_replay(req, tmp_path / "run"))
    assert not (tmp_path / "run/report.json").exists()
    assert (tmp_path / "run/interrupted.json").exists()
    with sqlite3.connect(tmp_path / "run/options.db") as db:
        assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM execution_option_scope_watches").fetchone()[0] == 0
        cycle_result = json.loads(
            db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0]
        )
    assert cycle_result["blocker"] == "SCOPE_WATCH_NOT_ACTIVE"


def test_native_cycle_failure_is_incomplete_not_successful_flat_replay(tmp_path):
    req = request(tmp_path)
    frames = [
        (e.recorded_at, e.kind, DegenFrame(scope=e.frame.scope) if e.kind == "CYCLE" else e.frame)
        for e in req.tape.events
    ]
    req = reseal(req, tmp_path, frames)
    with pytest.raises(ValueError, match="native cycle failed"):
        asyncio.run(run_scope_trading_replay(req, tmp_path / "run"))
    assert not (tmp_path / "run/report.json").exists()
    assert (tmp_path / "run/interrupted.json").exists()


def test_independent_funded_runs_keep_separate_orders_fills_and_loss_state(tmp_path):
    req = request(tmp_path)
    reports, fills = [], []
    for arm in ("one", "two"):
        owner = req.model_copy(
            update={
                "limits": req.limits.model_copy(
                    update={
                        "population_id": arm,
                        "account_id": "account-" + arm,
                    }
                )
            }
        )
        report = asyncio.run(run_scope_trading_replay(owner, tmp_path / arm))
        reports.append(report)
        exported = json.loads((tmp_path / arm / "native.json").read_text())
        fills.append({r[0] for r in exported["evidence"]["execution_fills"]})
        families = {
            f["family"]: f for f in report["accounting"]["loss_control"]["state"]["families"]
        }
        assert families["SCOPE"]["consecutive_losses"] == 1
        assert families["DEGEN"]["consecutive_losses"] == 0
    assert reports[0]["request_hash"] != reports[1]["request_hash"]
    assert reports[0]["accounting"]["ledger"]["cash"] == reports[1]["accounting"]["ledger"]["cash"]
    assert len(fills[0]) == len(fills[1]) == 2
    assert not fills[0] & fills[1]


@pytest.mark.parametrize(
    "defect",
    [
        "model",
        "ai",
        "limits",
        "watch",
        "missing-family",
        "duplicate",
        "rewind",
        "receipt-order",
        "after-close",
        "seal",
    ],
)
def test_bad_enrollment_rejected_before_creating_output(tmp_path, defect):
    req = request(tmp_path)
    if defect == "model":
        from app.execution.economics import CostPolicy

        req = req.model_copy(
            update={
                "execution": req.execution.model_copy(
                    update={"cost_policy": CostPolicy(total_budget="1", daily_budget=".1")}
                )
            }
        )
    elif defect == "ai":
        req = req.model_copy(
            update={"scope": req.scope.model_copy(update={"version": "shared-scope-entry-v1"})}
        )
    elif defect == "limits":
        req = req.model_copy(
            update={"limits": req.limits.model_copy(update={"underlying_source": "foreign"})}
        )
    elif defect == "watch":
        req = req.model_copy(
            update={
                "scope": req.scope.model_copy(
                    update={
                        "watch": req.scope.watch.model_copy(
                            update={"max_called_plays_per_session": 1}
                        )
                    }
                )
            }
        )
    elif defect == "missing-family":
        loss = req.execution.loss_control.model_copy(update={"families": ()})
        req = req.model_copy(
            update={"execution": req.execution.model_copy(update={"loss_control": loss})}
        )
    elif defect == "duplicate":
        req = req.model_copy(update={"watch_actions": (req.watch_actions[0], req.watch_actions[0])})
    elif defect == "rewind":
        req = req.model_copy(update={"watch_actions": tuple(reversed(req.watch_actions))})
    elif defect == "receipt-order":
        req = req.model_copy(
            update={
                "watch_actions": (
                    req.watch_actions[0].model_copy(update={"sequence": 2}),
                    req.watch_actions[1].model_copy(update={"sequence": 1}),
                )
            }
        )
    elif defect == "after-close":
        req = req.model_copy(
            update={
                "watch_actions": (
                    req.watch_actions[0].model_copy(
                        update={"at": req.tape.header.closes_at + timedelta(seconds=1)}
                    ),
                )
            }
        )
    elif defect == "seal":
        req = req.model_copy(
            update={
                "tape": req.tape.model_copy(
                    update={"seal": req.tape.seal.model_copy(update={"last_hash": "0" * 64})}
                )
            }
        )
    with pytest.raises(ValueError):
        asyncio.run(run_scope_trading_replay(req, tmp_path / "invalid"))
    assert not (tmp_path / "invalid").exists()


def test_create_only_replay_never_reuses_an_existing_owner(tmp_path):
    req = request(tmp_path)
    home = tmp_path / "existing"
    home.mkdir()
    (home / "sentinel").write_text("retain")
    with pytest.raises(FileExistsError):
        asyncio.run(run_scope_trading_replay(req, home))
    assert (home / "sentinel").read_text() == "retain"
    assert not (home / "options.db").exists()
