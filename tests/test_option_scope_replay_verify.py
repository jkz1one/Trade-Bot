"""Portable Scope evidence must match native replay, not just edited self-hashes."""

import json
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest
from test_option_scope_replay import settings, tape

from app.options import scope_replay_verify as verifier
from app.options.engine import OptionExecution, fingerprint
from app.options.scope_replay import run_scope_replay


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    root = tmp_path_factory.mktemp("scope-export")
    result = {}
    for right in ("CALL", "PUT"):
        request = settings(tape(right))
        home = root / right
        run_scope_replay(request, home)
        result[right] = (home, fingerprint(request))
    return result


@pytest.fixture
def copy_export(tmp_path, exported):
    original, digest = exported["CALL"]
    home = tmp_path / "export"
    shutil.copytree(original, home)
    return home, digest


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def snapshot(home):
    return {
        str(p.relative_to(home)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in home.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_full_reproduction_retains_costs_and_never_changes_original(exported, right, monkeypatch):
    home, digest = exported[right]
    before = snapshot(home)

    def forbidden(*args, **kwargs):
        pytest.fail("Research verification cannot prepare or dispatch orders")

    monkeypatch.setattr(OptionExecution, "prepare", forbidden)
    monkeypatch.setattr(OptionExecution, "dispatch", forbidden)
    result = verifier.verify_scope_replay(home, digest)
    assert result["status"] == "VERIFIED_RESEARCH_REPLAY"
    assert result["actions_verified"] == result["recorded_actions"] == 9
    assert result["rejected_actions"] == 0
    assert result["report_hash"] == fingerprint(read(home / "report.json"))
    assert result["economic_conclusion"] == "NOT_EVALUATED"
    assert result["data_cost"] is result["host_cost"] is result["net_return"] is None
    assert result["source_journals_verified"] is False
    assert result["execution_authority"] is result["live_enabled"] is False
    admission = read(home / "actions/007.json")["receipt"]["record"]["admission_review"]
    assert admission["admission"]["full_premium_loss"] == "415.60"
    assert admission["admission"]["reserved_exit_fees"] == "3.30"
    assert snapshot(home) == before


def test_only_json_is_needed_and_original_database_is_never_opened(copy_export):
    home, digest = copy_export
    for p in home.iterdir():
        if p.name not in {"inputs.json", "report.json", "actions"}:
            p.unlink()
    # Poison journal destinations: any attempt to attach an owner here must fail.
    (home / "options.db").mkdir()
    (home / "venue.db").symlink_to("missing-original-database")
    assert verifier.verify_scope_replay(home, digest)["status"] == "VERIFIED_RESEARCH_REPLAY"


@pytest.mark.parametrize(
    "damage",
    [
        "fee",
        "receipt",
        "self_hashes",
        "reason",
        "revision",
        "authority",
        "zero_cost",
        "path",
        "count",
    ],
)
def test_edited_receipts_and_reports_fail_even_with_consistent_self_hashes(copy_export, damage):
    home, digest = copy_export
    path = home / "actions/007.json"
    action = read(path)
    report = read(home / "report.json")
    if damage == "fee":
        action["receipt"]["record"]["admission_review"]["admission"]["reserved_exit_fees"] = "0"
    elif damage in {"receipt", "self_hashes"}:
        action["receipt"]["record"]["admission_review"]["eligible"] = False
    elif damage == "reason":
        action["reason"] = "invented rejection"
    elif damage == "revision":
        action["expected_revision"] += 1
    elif damage == "authority":
        report["execution_authority"] = 0  # Equal in Python, different JSON authority type.
    elif damage == "zero_cost":
        report["host_cost"] = "0"
    elif damage == "path":
        report["steps"][7]["artifact"] = "../../outside.json"
    elif damage == "count":
        report["recorded_actions"] += 1
    if damage == "self_hashes":
        action["receipt_hash"] = fingerprint(action["receipt"])
        report["steps"][7]["receipt_hash"] = action["receipt_hash"]
    write(path, action)
    write(home / "report.json", report)
    with pytest.raises(ValueError, match="differs from native reproduction"):
        verifier.verify_scope_replay(home, digest)


def test_changed_request_cannot_choose_its_own_hash(copy_export, monkeypatch):
    home, digest = copy_export
    inputs = read(home / "inputs.json")
    inputs["request"]["limits"]["population_id"] = "different-account"
    from app.options.scope_replay import ScopeReplayRequest

    inputs["request_hash"] = fingerprint(ScopeReplayRequest.model_validate(inputs["request"]))
    write(home / "inputs.json", inputs)
    monkeypatch.setattr(
        verifier, "run_scope_replay", lambda *a: pytest.fail("Must reject before replay")
    )
    with pytest.raises(ValueError, match="expected frozen input"):
        verifier.verify_scope_replay(home, digest)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_report",
        "missing_action",
        "extra_action",
        "interrupted",
        "dangling_marker",
        "action_symlink",
        "actions_symlink",
        "root_symlink",
        "fifo",
        "public_file",
        "public_directory",
        "duplicate_key",
        "nonfinite",
        "oversize",
        "budget",
        "nonobject",
    ],
)
def test_incomplete_ambiguous_and_unsafe_exports_fail_before_reproduction(
    copy_export, tmp_path, monkeypatch, damage
):
    home, digest = copy_export
    action = home / "actions/000.json"
    if damage == "missing_report":
        (home / "report.json").unlink()
    elif damage == "missing_action":
        action.unlink()
    elif damage == "extra_action":
        write(home / "actions/999.json", {})
    elif damage == "interrupted":
        write(home / "interrupted.json", {})
    elif damage == "dangling_marker":
        (home / "interrupted.json").symlink_to("absent")
    elif damage == "action_symlink":
        action.unlink()
        action.symlink_to(home / "report.json")
    elif damage == "actions_symlink":
        (home / "actions").rename(tmp_path / "elsewhere")
        (home / "actions").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    elif damage == "root_symlink":
        link = tmp_path / "link"
        link.symlink_to(home, target_is_directory=True)
        home = link
    elif damage == "fifo":
        action.unlink()
        os.mkfifo(action, 0o600)
    elif damage == "public_file":
        action.chmod(0o644)
    elif damage == "public_directory":
        (home / "actions").chmod(0o755)
    elif damage == "duplicate_key":
        action.write_text('{"status":"RECORDED","status":"REJECTED"}')
    elif damage == "nonfinite":
        action.write_text('{"value":NaN}')
    elif damage == "oversize":
        monkeypatch.setattr(verifier, "MAX_ACTION_BYTES", 1)
    elif damage == "budget":
        monkeypatch.setattr(verifier, "MAX_EXPORT_BYTES", 1)
    elif damage == "nonobject":
        action.write_text("[]")
    monkeypatch.setattr(
        verifier, "run_scope_replay", lambda *a: pytest.fail("Must reject before replay")
    )
    with pytest.raises((ValueError, TypeError, OSError)):
        verifier.verify_scope_replay(home, digest)


@pytest.mark.parametrize("digest", [None, "", "A" * 64, "g" * 64, "a" * 63])
def test_independent_hash_is_required(copy_export, digest):
    home, _ = copy_export
    with pytest.raises(ValueError, match="Expected Scope request hash"):
        verifier.verify_scope_replay(home, digest)


def test_rejected_actions_and_missing_evidence_resets_are_valid_research(tmp_path):
    steps = tape(expire=False)
    steps.insert(1, steps[0].model_copy(update={"key": "second", "play_key": "second"}))
    steps[-1] = steps[-1].model_copy(update={"frame": None, "context": None, "underlying": None})
    request = settings(steps)
    home = tmp_path / "run"
    report = run_scope_replay(request, home)
    assert report["scope"]["active_watch"]["arming"]["recorded_status"] == "RESET"
    result = verifier.verify_scope_replay(home, fingerprint(request))
    assert result["status"] == "VERIFIED_RESEARCH_REPLAY"
    assert result["rejected_actions"] == 1 and result["recorded_actions"] == 8


def test_missing_third_target_stays_blocked_in_verified_export(tmp_path):
    from decimal import Decimal

    from test_option_scope_management import watch_policy

    steps = tape(expire=False)
    last = steps[-1]
    quote = last.frame.quote.model_copy(
        update={"bid": Decimal(1), "ask": Decimal(1), "ask_size": 4}
    )
    steps[-1] = last.model_copy(update={"frame": last.frame.model_copy(update={"quote": quote})})
    request = settings(steps, watch=watch_policy())
    home = tmp_path / "run"
    report = run_scope_replay(request, home)
    management = report["scope"]["active_watch"]["admission"]["management"]
    assert management["reasons"] == ["SCOPE_THIRD_TARGET_UNSPECIFIED"]
    assert management["passed"] is management["native_execution_ready"] is False
    result = verifier.verify_scope_replay(home, fingerprint(request))
    assert result["status"] == "VERIFIED_RESEARCH_REPLAY"
    assert result["execution_authority"] is False


def test_failed_reproduction_cleans_temporary_state_and_cli_hides_details(
    copy_export, tmp_path, monkeypatch, capsys
):
    home, digest = copy_export
    before = snapshot(home)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(
        verifier, "TemporaryDirectory", lambda **kw: TemporaryDirectory(dir=scratch, **kw)
    )

    def fail(request, output):
        output.mkdir()
        (output / "partial.json").write_text("private fixture details")
        raise TimeoutError("private fixture details")

    monkeypatch.setattr(verifier, "run_scope_replay", fail)
    assert verifier.main(["--export", str(home), "--request-hash", digest]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "UNAVAILABLE"
    assert "private" not in str(result)
    assert not list(scratch.iterdir())
    assert snapshot(home) == before


def test_installed_verifier_cli_outside_checkout(copy_export, tmp_path):
    home, digest = copy_export
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.scope_replay_verify",
            "--export",
            str(home),
            "--request-hash",
            digest,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "VERIFIED_RESEARCH_REPLAY"
