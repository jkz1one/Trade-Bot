"""Common observations drive independent native watches, never copied approvals."""

import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_execution import configuration
from test_option_scope import AT
from test_option_scope_execution import execution_policy
from test_option_scope_execution_replay import request as legacy_request
from test_option_scope_market_tape import inputs, record
from test_option_scope_replay import tape as watch_steps

from app.options.coordinator import DegenFrame
from app.options.engine import OptionExecution, fingerprint
from app.options.lifecycle import OptionExecutionPolicy
from app.options.scope_arbitration import ScopeCycleInput
from app.options.scope_execution_export import verify_scope_execution_export
from app.options.scope_execution_replay import ScopeExecutionReplay, run_scope_execution_replay
from app.options.scope_replay import _perform, _revision
from app.options.scope_tape_watch import ScopeTapeWatchAction, resolve_scope_watch_action
from app.options.scope_watch import ScopeWatchBook
from app.options.venue import DurableOptionVenue


def request(tmp_path, right="CALL", *, expire=True):
    header, frame = inputs(right)
    frames, actions = [], []
    for step in watch_steps(right, expire=expire):
        sequence = None
        if step.frame is not None:
            at = step.at
            price = step.frame.histories[0].bars[-1].close
            u = frame.scope.underlying.model_copy(
                update={"source_at": at, "received_at": at, "bid": price, "ask": price}
            )
            frames.append(
                (
                    at,
                    "SCOPE",
                    DegenFrame(
                        scope=ScopeCycleInput(
                            play_key=step.play_key,
                            frame=step.frame,
                            context=step.context,
                            underlying=u,
                        )
                    ),
                )
            )
            sequence = len(frames)
        actions.append(
            ScopeTapeWatchAction(
                key=step.key,
                kind=step.kind,
                at=step.at,
                play_key=step.play_key,
                sequence=sequence,
                choice=step.choice,
            )
        )
    tape = record(tmp_path / "source.tape", header, frames)
    return ScopeExecutionReplay(
        limits=header.limits.model_copy(
            update={"population_id": "tape-watch-A", "account_id": "account-A"}
        ),
        execution=OptionExecutionPolicy.model_validate(
            configuration()[2].model_dump() | execution_policy()
        ),
        watch=header.scope.watch,
        scope_tape=tape,
        started_at=header.opens_at,
        steps=tuple(actions),
        data_cost=".01",
        host_cost=".02",
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_common_tape_independent_native_watch_owners_and_exports(tmp_path, right):
    req = request(tmp_path, right, expire=False)
    reports = []
    for arm in "ABCD":
        owner = req.model_copy(
            update={
                "limits": req.limits.model_copy(
                    update={
                        "population_id": "tape-watch-" + arm,
                        "account_id": "account-" + arm,
                    }
                )
            }
        )
        report = run_scope_execution_replay(owner, tmp_path / arm)
        reports.append(report)
        assert report["status"] == "COMPLETE_TAPE_WATCH_REPLAY"
        assert not report["comparison_complete"]
        assert report["economic_conclusion"] == "NOT_EVALUATED"
        assert report["tape_hash"] == req.scope_tape.digest
        assert report["accounting"]["orders"] == []
        assert report["accounting"]["model_costs"]["unknown_calls"] == 0
        assert Decimal(report["accounting"]["net_after_all_costs"]) == Decimal("-.03")
        review = report["actions"][-1]["result"]["record"]["admission_review"]
        assert review["eligible"], review
        assert review["admission"]["quantity"] == 2
        for source, action in zip(owner.steps, report["actions"], strict=True):
            resolved, binding = resolve_scope_watch_action(owner.scope_tape, source)
            assert action["tape_binding"] == binding
            assert action["step_hash"] == fingerprint(source)
            assert binding["resolved_step_hash"] == fingerprint(resolved)
            assert action["result"]["revision"] > action["expected_revision"]
        exported = json.loads((tmp_path / arm / "native.json").read_text())
        verified = verify_scope_execution_export(exported, report["export_hash"])
        assert verified["status"] == "VERIFIED_NATIVE_ACCOUNTING"
        assert json.loads((tmp_path / arm / "report.json").read_text()) == report
        assert json.loads((tmp_path / arm / "inputs.json").read_text())[
            "request_hash"
        ] == fingerprint(owner)
    assert len({r["request_hash"] for r in reports}) == 4
    assert len({r["export_hash"] for r in reports}) == 4
    bindings = [r["actions"][-1]["result"]["record"]["entry_binding"] for r in reports]
    assert len({fingerprint(b) for b in bindings}) == 4
    # No linked databases, shared balances or shared action rows.
    with sqlite3.connect(tmp_path / "A/options.db") as db:
        db.execute("DELETE FROM execution_option_scope_watch_actions")
    for arm in "BCD":
        with sqlite3.connect(tmp_path / arm / "options.db") as db:
            assert (
                db.execute("SELECT count(*) FROM execution_option_scope_watch_actions").fetchone()[
                    0
                ]
                == 8
            )


def test_timer_expiry_missing_observation_and_native_rejection(tmp_path):
    req = request(tmp_path)
    steps = list(req.steps)
    steps.insert(
        -1,
        ScopeTapeWatchAction(
            kind="OBSERVE_ARMING",
            key="missing",
            play_key="first",
            at=steps[-2].at + timedelta(seconds=1),
        ),
    )
    steps.append(
        ScopeTapeWatchAction(
            kind="OBSERVE_ARMING",
            key="after-expiry",
            play_key="first",
            at=steps[-1].at,
        )
    )
    report = run_scope_execution_replay(
        req.model_copy(update={"steps": tuple(steps)}), tmp_path / "run"
    )
    missing, expiry, rejected = report["actions"][-3:]
    assert missing["result"]["record"]["arming"]["status"] == "RESET"
    assert missing["tape_binding"]["input_hash"] is None
    assert expiry["result"]["record"]["status"] == "EXPIRED_UNFILLED"
    assert expiry["tape_binding"]["event_hash"] is None
    assert rejected["result"]["status"] == "REJECTED"
    assert report["accounting"]["scope"]["watches"][0]["recorded_status"] == "EXPIRED_UNFILLED"


def test_stale_reference_keeps_original_clocks_and_never_refreshes_admission(tmp_path):
    req = request(tmp_path, expire=False)
    last = req.steps[-1].model_copy(update={"at": AT + timedelta(minutes=5), "sequence": 1})
    step, binding = resolve_scope_watch_action(req.scope_tape, last)
    assert step.frame == req.scope_tape.events[0].frame.scope.frame
    assert step.frame.quote.received_at == AT
    assert binding["recorded_at"] == AT.isoformat()
    report = run_scope_execution_replay(
        req.model_copy(update={"steps": (*req.steps[:-1], last)}), tmp_path / "run"
    )
    assert not report["actions"][-1]["result"]["record"]["admission_review"]["eligible"]
    assert report["accounting"]["orders"] == []


@pytest.mark.parametrize("cost", ["data_cost", "host_cost"])
def test_unknown_operating_costs_stay_unknown(tmp_path, cost):
    req = request(tmp_path).model_copy(update={cost: None})
    report = run_scope_execution_replay(req, tmp_path / "run")
    assert report["accounting"][cost] is None
    assert report["accounting"]["net_after_all_costs"] is None
    assert report["accounting"]["status"] == "INCOMPLETE"


def test_each_owner_computes_admission_from_its_own_funds(tmp_path):
    req = request(tmp_path, expire=False)
    normal = run_scope_execution_replay(req, tmp_path / "normal")
    small = req.model_copy(
        update={
            "execution": req.execution.model_copy(
                update={
                    "capital": Decimal(300),
                    "daily_loss_limit": Decimal(200),
                    "total_loss_limit": Decimal(250),
                }
            )
        }
    )
    constrained = run_scope_execution_replay(small, tmp_path / "constrained")
    assert normal["actions"][-1]["result"]["record"]["admission_review"]["eligible"]
    assert not constrained["actions"][-1]["result"]["record"]["admission_review"]["eligible"]
    assert constrained["accounting"]["ledger"]["cash"] == "300"
    assert normal["accounting"]["ledger"]["cash"] == "1000"


def test_restart_retains_original_watch_and_reads_native_revision(tmp_path):
    req = request(tmp_path, expire=False)
    home = tmp_path / "run"
    run_scope_execution_replay(req.model_copy(update={"steps": req.steps[:4]}), home)
    venue = DurableOptionVenue(home / "venue.db")
    now = req.steps[3].at
    with OptionExecution.open(
        home / "options.db", req.limits, req.execution, venue, now=now
    ) as engine:
        book = ScopeWatchBook(engine, req.watch, now=now)
        original = book.snapshot()["watches"][0]["locked_frame"]
        for action in req.steps[4:]:
            step, _ = resolve_scope_watch_action(req.scope_tape, action)
            assert engine.reconcile(venue.snapshot(step.at), now=step.at)["reconciled"]
            engine.assess(None, step.underlying, now=step.at)
            before = _revision(engine)
            result = _perform(book, step, before)
            assert result["revision"] > before
            assert result["record"]["locked_frame"] == original
        assert result["record"]["admission_review"]["eligible"]
        assert original["session"] == req.scope_tape.header.scope.session.model_dump(mode="json")


@pytest.mark.parametrize(
    "defect",
    [
        "no-tape",
        "no-scope",
        "watch",
        "limits",
        "start",
        "raw-watch",
        "native-entry",
        "duplicate-key",
        "reverse-clock",
        "future",
        "missing-event",
        "foreign-play",
        "seal",
        "outside-session",
        "shared-owner",
    ],
)
def test_invalid_bindings_fail_before_output_or_owner_creation(tmp_path, defect):
    req = request(tmp_path, expire=False)
    changes = {}
    if defect == "no-tape":
        changes["scope_tape"] = None
    elif defect == "no-scope":
        header = req.scope_tape.header.model_copy(update={"scope": None})
        changes["scope_tape"] = req.scope_tape.model_copy(update={"header": header})
    elif defect == "watch":
        changes["watch"] = req.watch.model_copy(update={"max_called_plays_per_session": 1})
    elif defect == "limits":
        changes["limits"] = req.limits.model_copy(update={"underlying_source": "foreign"})
    elif defect == "start":
        changes["started_at"] = req.started_at + timedelta(seconds=1)
    elif defect == "raw-watch":
        changes["steps"] = (resolve_scope_watch_action(req.scope_tape, req.steps[0])[0],)
    elif defect == "native-entry":
        changes["steps"] = (legacy_request().steps[-4],)
    elif defect == "duplicate-key":
        changes["steps"] = (req.steps[0], req.steps[0])
    elif defect == "reverse-clock":
        changes["steps"] = tuple(reversed(req.steps))
    elif defect in {"future", "missing-event", "foreign-play", "outside-session"}:
        override = {
            "future": {"sequence": len(req.steps)},
            "missing-event": {"sequence": 100},
            "foreign-play": {"play_key": "other", "key": "other"},
            "outside-session": {"at": req.scope_tape.header.closes_at + timedelta(seconds=6)},
        }[defect]
        changes["steps"] = (req.steps[0].model_copy(update=override),)
    elif defect == "seal":
        changes["scope_tape"] = req.scope_tape.model_copy(
            update={"seal": req.scope_tape.seal.model_copy(update={"last_hash": "0" * 64})}
        )
    elif defect == "shared-owner":
        changes["execution"] = req.execution.model_copy(
            update={"scope_arbitration": "shared-scope-selection-v1"}
        )
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        run_scope_execution_replay(req.model_copy(update=changes), output)
    assert not output.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", True),
        ("sequence", "1"),
        ("sequence", 0),
        ("expected_revision", 1),
        ("frame", {}),
        ("receipt", {}),
        ("quantity", 2),
        ("account", {}),
        ("cost", "0"),
        ("session", {}),
    ],
)
def test_reference_contract_rejects_authority_and_payload_overrides(field, value):
    raw = {
        "key": "first",
        "kind": "CALL",
        "play_key": "first",
        "at": AT,
        "sequence": 1,
        "choice": watch_steps()[0].choice,
        field: value,
    }
    with pytest.raises(ValueError):
        ScopeTapeWatchAction.model_validate(raw)


def test_create_only_and_legacy_request_serialization(tmp_path):
    old = legacy_request()
    assert "scope_tape" not in old.model_dump()
    assert fingerprint(old) == "d1dc48e390794786fa04dca86b61a85e8859beae06eb0e264ea199cbd46bcc49"
    assert ScopeExecutionReplay.model_validate_json(old.model_dump_json()) == old
    req = request(tmp_path)
    report = run_scope_execution_replay(req, tmp_path / "run")
    with pytest.raises(FileExistsError):
        run_scope_execution_replay(req, tmp_path / "run")
    assert json.loads((tmp_path / "run/report.json").read_text()) == report


@pytest.mark.parametrize("kind", ["OBSERVE_QUOTE", "NEUTRALIZE"])
@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_quote_invalidation_and_completed_bar_neutral_reset(tmp_path, kind, right):
    from test_option_scope_context import context
    from test_option_scope_watch import append

    req = request(tmp_path, right, expire=False)
    first = req.scope_tape.events[0].frame.scope
    broken = append(first.frame, **{"low" if right == "CALL" else "high": "100"})
    neutral = append(broken, close="100.5" if right == "CALL" else "99.5")
    frames = [(AT, "SCOPE", DegenFrame(scope=first))]
    actions = [req.steps[0]]
    for key, f, action_kind in (
        ("invalidate", broken, "OBSERVE_QUOTE" if kind == "OBSERVE_QUOTE" else "ADVANCE"),
        ("neutral", neutral, "NEUTRALIZE"),
    ):
        now = f.histories[0].received_at
        u = first.underlying.model_copy(
            update={"source_at": now, "received_at": now, "bid": Decimal(100), "ask": Decimal(100)}
        )
        frames.append(
            (
                now,
                "SCOPE",
                DegenFrame(
                    scope=ScopeCycleInput(
                        play_key="first",
                        frame=f,
                        context=context(f),
                        underlying=u,
                    )
                ),
            )
        )
        actions.append(
            ScopeTapeWatchAction(
                key=key, kind=action_kind, at=now, play_key="first", sequence=len(frames)
            )
        )
    tape = record(tmp_path / "reset.tape", req.scope_tape.header, frames)
    req = req.model_copy(update={"scope_tape": tape, "steps": tuple(actions)})
    report = run_scope_execution_replay(req, tmp_path / "reset")
    final = report["actions"][-1]["result"]["record"]
    assert final["status"] == "INVALIDATED_UNFILLED"
    assert final["neutral_reset"]
    step, _ = resolve_scope_watch_action(tape, actions[1])
    if kind == "OBSERVE_QUOTE":
        assert step.frame is None and step.context is None and step.underlying is not None
    else:
        assert step.frame == broken and step.context is None and step.underlying is None


def test_market_event_cannot_substitute_for_scope_observation(tmp_path):
    req = request(tmp_path, expire=False)
    tape = record(tmp_path / "market.tape", req.scope_tape.header, [(AT, "MARKET", DegenFrame())])
    with pytest.raises(ValueError, match="not available"):
        resolve_scope_watch_action(tape, req.steps[0])


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": None},
        {"choice": None},
        {"play_key": "other"},
        {"kind": "ADVANCE"},
        {"kind": "NEUTRALIZE", "choice": None, "sequence": None},
    ],
)
def test_call_and_reset_require_exact_instruction_fields(change):
    value = ScopeTapeWatchAction(
        key="first",
        kind="CALL",
        play_key="first",
        at=AT,
        sequence=1,
        choice=watch_steps()[0].choice,
    )
    with pytest.raises(ValueError):
        ScopeTapeWatchAction.model_validate(value.model_dump() | change)


def test_unexpected_mutating_rejection_leaves_incomplete_run(tmp_path, monkeypatch):
    from app.execution.engine import ExecutionBlocked
    from app.options import scope_execution_replay as module

    req = request(tmp_path)
    req = req.model_copy(update={"steps": req.steps[:1]})
    native = module._perform

    def broken(book, step, revision):
        native(book, step, revision)
        raise ExecutionBlocked("INJECTED_AFTER_MUTATION")

    monkeypatch.setattr(module, "_perform", broken)
    with pytest.raises(ValueError, match="changed its journal"):
        run_scope_execution_replay(req, tmp_path / "interrupted")
    assert not (tmp_path / "interrupted/report.json").exists()
    assert (
        json.loads((tmp_path / "interrupted/interrupted.json").read_text())["status"]
        == "INCOMPLETE_FIXTURE_REPLAY"
    )
