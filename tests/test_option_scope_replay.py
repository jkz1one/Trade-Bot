"""Scope watch replay is native research evidence, never trade performance."""

import json
import stat
import subprocess
import sys
from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_option_execution import configuration
from test_option_scope import AT
from test_option_scope_arming import refresh
from test_option_scope_contract import data
from test_option_scope_owned_admission import policy
from test_option_scope_watch import append, choice
from test_option_scope_watch import policy as watch_policy

from app.options.engine import fingerprint
from app.options.models import UnderlyingQuote
from app.options.scope_replay import ScopeReplayRequest, ScopeReplayStep, main, run_scope_replay
from app.options.scope_watch import ScopeDirectionResetPolicy


def settings(steps, *, watch=None, population="scope-research-replay"):
    _, limits, execution = configuration()
    limits = limits.model_copy(
        update={
            "allowed_underlyings": ("SPX",),
            "provider": "fixture-provider",
            "option_source": "fixture-quote",
            "population_id": population,
        }
    )
    return ScopeReplayRequest(
        limits=limits,
        execution=execution,
        watch=watch or policy(),
        started_at=AT,
        steps=tuple(steps),
    )


def tape(right="CALL", *, expire=True):
    f, c = data(right)
    steps = [
        ScopeReplayStep(
            key="first",
            kind="CALL",
            at=AT,
            play_key="first",
            choice=choice(right, "trend_pullback_continuation"),
            frame=f,
            context=c,
        )
    ]
    for seconds in range(0, 60, 10):
        now = AT + timedelta(seconds=seconds)
        fresh, c = refresh(f, now)
        steps.append(
            ScopeReplayStep(
                key=f"sample-{seconds}",
                kind="OBSERVE_ARMING",
                at=now,
                play_key="first",
                frame=fresh,
                context=c,
            )
        )
    now = AT + timedelta(seconds=60)
    fresh, c = refresh(f, now)
    price = fresh.histories[0].bars[-1].close
    u = UnderlyingQuote(
        symbol="SPX",
        source=configuration()[1].underlying_source,
        source_at=now,
        received_at=now,
        complete=True,
        entitlement="REALTIME",
        bid=price,
        ask=price,
    )
    steps.append(
        ScopeReplayStep(
            key="review",
            kind="REVIEW_ADMISSION",
            at=now,
            play_key="first",
            frame=fresh,
            context=c,
            underlying=u,
        )
    )
    if expire:
        steps.append(
            ScopeReplayStep(
                key="expire", kind="ADVANCE", at=f.session.entry_cutoff_at, play_key="first"
            )
        )
    return steps


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_native_call_hold_admission_expiry_and_private_saved_receipts(tmp_path, right):
    request = settings(tape(right))
    home = tmp_path / "run"
    report = run_scope_replay(request, home)
    assert report["status"] == "COMPLETE_RESEARCH_REPLAY"
    assert report["recorded_actions"] == 9 and report["rejected_actions"] == 0
    assert report["economic_conclusion"] == "NOT_EVALUATED"
    assert not report["execution_authority"] and not report["live_enabled"]
    assert not report["orders"] and not report["fills"]
    assert report["scope"]["active_watch"] is None
    assert report["scope"]["watches"][0]["recorded_status"] == "EXPIRED_UNFILLED"
    admission = json.loads((home / "actions/007.json").read_text())["receipt"]["record"][
        "admission_review"
    ]
    assert admission["eligible"] and admission["admission"]["quantity"] == 2
    assert admission["admission"]["full_premium_loss"] == "415.60"
    assert admission["admission"]["reserved_exit_fees"] == "3.30"
    for action, step in zip(report["steps"], request.steps, strict=True):
        saved = json.loads((home / action["artifact"]).read_text())
        assert saved["step_hash"] == fingerprint(step)
        assert saved["receipt_hash"] == fingerprint(saved["receipt"])
        assert saved["receipt"]["revision"] > saved["expected_revision"]
        assert stat.S_IMODE((home / action["artifact"]).stat().st_mode) == 0o600
    assert json.loads((home / "report.json").read_text()) == report
    assert json.loads((home / "inputs.json").read_text())["request_hash"] == fingerprint(request)
    assert not (home / "interrupted.json").exists()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_rejection_is_recorded_without_call_credit_or_fake_sizing(tmp_path):
    steps = tape(expire=False)
    # Same already-active watch must reject a second CALL without consuming it.
    steps.insert(1, steps[0].model_copy(update={"key": "second", "play_key": "second"}))
    # A missing sample is a recorded RESET, not a raised action rejection.
    steps.append(
        ScopeReplayStep(
            key="missing",
            kind="OBSERVE_ARMING",
            at=steps[-1].at + timedelta(seconds=1),
            play_key="first",
        )
    )
    report = run_scope_replay(settings(steps), tmp_path / "run")
    assert report["rejected_actions"] == 1
    rejected = report["steps"][1]
    assert rejected["reason"] == "SCOPE_WATCH_ALREADY_ACTIVE" and rejected["receipt_hash"] is None
    assert report["scope"]["total_watches"] == 1
    assert report["scope"]["active_watch"]["arming"]["recorded_status"] == "RESET"
    assert report["scope"]["active_watch"]["decision_evidence"]["latest_sample"] == {
        "quality": None,
        "contract": None,
    }


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_invalidation_and_fresh_neutral_reset_replay(tmp_path, right):
    first = tape(right)[0]
    f = first.frame
    # Original trend invalidation is 100 in both reflected fixtures.
    f = append(f, **{"low" if right == "CALL" else "high": "100"})
    invalidation = ScopeReplayStep(
        key="invalidate", kind="ADVANCE", at=f.histories[0].received_at, play_key="first", frame=f
    )
    f = append(f, close="100.5" if right == "CALL" else "99.5")
    neutral = ScopeReplayStep(
        key="neutral", kind="NEUTRALIZE", at=f.histories[0].received_at, play_key="first", frame=f
    )
    wp = watch_policy(
        direction_reset=ScopeDirectionResetPolicy(cooldown_seconds=600, confirmation_bars=2)
    )
    report = run_scope_replay(settings([first, invalidation, neutral], watch=wp), tmp_path / "run")
    assert report["recorded_actions"] == 3 and report["rejected_actions"] == 0
    record = json.loads((tmp_path / "run/actions/002.json").read_text())["receipt"]["record"]
    assert record["status"] == "INVALIDATED_UNFILLED" and record["neutral_reset"]
    assert report["scope"]["total_watches"] == 1 and not report["scope"]["active_watch"]


def test_independent_accounts_and_identical_request_reproduction(tmp_path):
    request = settings(tape(expire=False))
    a = run_scope_replay(request, tmp_path / "a")
    b = run_scope_replay(request, tmp_path / "b")
    assert a == b
    other = settings(tape(expire=False), population="scope-other-owner")
    c = run_scope_replay(other, tmp_path / "c")
    assert c["request_hash"] != a["request_hash"] and c["population_id"] != a["population_id"]
    assert json.loads((tmp_path / "a/report.json").read_text()) == a
    assert not c["orders"] and not c["fills"]


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate",
        "rewound",
        "future_receipt",
        "extra_authority",
        "call_key",
        "choice_override",
        "underlying_override",
    ],
)
def test_tape_rejects_ambiguous_or_unauthorized_inputs_before_creation(tmp_path, damage):
    raw = settings(tape()).model_dump(mode="json")
    if damage == "duplicate":
        raw["steps"][1]["key"] = "first"
    if damage == "rewound":
        raw["steps"][1]["at"] = (AT - timedelta(seconds=1)).isoformat()
    if damage == "future_receipt":
        raw["steps"][0]["frame"]["quote"]["received_at"] = (AT + timedelta(seconds=1)).isoformat()
    if damage == "extra_authority":
        raw["steps"][0]["approved_quantity"] = 4
    if damage == "call_key":
        raw["steps"][0]["play_key"] = "other"
    if damage == "choice_override":
        raw["steps"][1]["choice"] = raw["steps"][0]["choice"]
    if damage == "underlying_override":
        raw["steps"][1]["underlying"] = raw["steps"][-2]["underlying"]
    with pytest.raises(ValidationError):
        ScopeReplayRequest.model_validate(raw)
    assert not list(tmp_path.iterdir())


def test_existing_and_interrupted_paths_are_never_resumed(tmp_path, monkeypatch):
    from app.options import scope_replay

    request = settings(tape())
    home = tmp_path / "run"
    original = scope_replay._perform

    def fail(book, step, rev):
        if step.key == "sample-10":
            raise RuntimeError("fixture interruption")
        return original(book, step, rev)

    monkeypatch.setattr(scope_replay, "_perform", fail)
    with pytest.raises(RuntimeError, match="fixture interruption"):
        run_scope_replay(request, home)
    assert (home / "inputs.json").exists() and (home / "actions/000.json").exists()
    assert not (home / "report.json").exists()
    assert (
        json.loads((home / "interrupted.json").read_text())["status"]
        == "INCOMPLETE_RESEARCH_REPLAY"
    )
    before = {p.relative_to(home): p.read_bytes() for p in home.rglob("*.json")}
    with pytest.raises(FileExistsError):
        run_scope_replay(request, home)
    assert before == {p.relative_to(home): p.read_bytes() for p in home.rglob("*.json")}


def test_cli_private_request_and_create_only_output(tmp_path, capsys):
    path = tmp_path / "request.json"
    path.write_text(settings(tape(expire=False)).model_dump_json())
    path.chmod(0o644)
    assert main(["--request", str(path), "--output", str(tmp_path / "unsafe")]) == 2
    assert not (tmp_path / "unsafe").exists()
    path.chmod(0o600)
    assert main(["--request", str(path), "--output", str(tmp_path / "run")]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[-1])["status"] == "COMPLETE_RESEARCH_REPLAY"
    assert main(["--request", str(path), "--output", str(tmp_path / "run")]) == 2


def test_installed_cli_runs_outside_checkout(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(settings(tape(expire=False)).model_dump_json())
    path.chmod(0o600)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.scope_replay",
            "--request",
            str(path),
            "--output",
            str(tmp_path / "run"),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "COMPLETE_RESEARCH_REPLAY"


def test_replay_never_calls_native_order_or_paid_model_preparation(tmp_path, monkeypatch):
    from app.options.engine import OptionExecution

    def forbidden(*args, **kwargs):
        pytest.fail("Scope research replay cannot prepare or dispatch orders")

    monkeypatch.setattr(OptionExecution, "prepare", forbidden)
    monkeypatch.setattr(OptionExecution, "dispatch", forbidden)
    report = run_scope_replay(settings(tape(expire=False)), tmp_path / "run")
    assert report["data_cost"] is None and report["host_cost"] is None
    assert report["net_return"] is None and not report["orders"] and not report["fills"]


@pytest.mark.parametrize("mode", ["relative", "symlink"])
def test_output_requires_new_absolute_owned_destination(tmp_path, monkeypatch, mode):
    request = settings(tape(expire=False))
    monkeypatch.chdir(tmp_path)
    if mode == "relative":
        with pytest.raises(ValueError, match="Absolute"):
            run_scope_replay(request, "relative")
        assert not (tmp_path / "relative").exists()
    else:
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        with pytest.raises(FileExistsError):
            run_scope_replay(request, link)
        assert not list(target.iterdir())


@pytest.mark.parametrize("quantity", [2, 4])
def test_management_review_exports_pass_and_missing_third_target_without_execution(
    tmp_path, quantity
):
    from decimal import Decimal

    from test_option_scope_management import watch_policy as managed_policy

    steps = tape(expire=False)
    if quantity == 4:
        last = steps[-1]
        q = last.frame.quote.model_copy(
            update={"bid": Decimal(1), "ask": Decimal(1), "ask_size": 4}
        )
        steps[-1] = last.model_copy(update={"frame": last.frame.model_copy(update={"quote": q})})
    report = run_scope_replay(settings(steps, watch=managed_policy()), tmp_path / "run")
    admission = report["scope"]["active_watch"]["admission"]
    assert admission["recorded_eligible"] and admission["result"]["quantity"] == quantity
    plan = admission["management"]
    assert plan["passed"] is (quantity == 2)
    assert plan["reasons"] == ([] if quantity == 2 else ["SCOPE_THIRD_TARGET_UNSPECIFIED"])
    assert not plan["native_execution_ready"] and not report["orders"]
