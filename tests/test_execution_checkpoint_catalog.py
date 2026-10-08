"""Local bounded capture, failure durability and native evidence-only recovery."""

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.execution import checkpoint
from app.execution import checkpoint_catalog as catalog
from app.execution.checkpoint_cli import main
from app.execution.engine import ExecutionEngine
from tests.test_execution_checkpoint import c as c
from tests.test_execution_checkpoint import pair_bytes
from tests.test_execution_rehearsal import NOW, decision, packet

PYTHON = os.environ.get("PAPER_CHECKPOINT_TEST_PYTHON", sys.executable)
UNITS = Path(__file__).parent.parent / "deploy" / "paper"


def initialize(c, **kwargs):
    root = c.root / "captures"
    catalog.initialize_catalog(c.engine.journal.path, root, **kwargs)
    return root


def jobs(root):
    return [p for p in root.iterdir() if p.is_dir()]


def test_capture_preserves_unknown_order_and_halt_in_quarantine(c):
    c.engine = ExecutionEngine(c.root / "unknown-order.db", c.engine.settings)
    c.engine.reconcile(c.venue.snapshot(NOW), now=NOW)
    entry = c.engine.prepare("entry", decision(), packet(), now=NOW)
    c.venue.lose_next_ack = True
    assert c.engine.dispatch(entry.client_id, c.venue, now=NOW, packet=packet()) == "UNKNOWN"
    c.engine.journal.enable_restore_fence(now=NOW)
    before = pair_bytes(c)
    root = initialize(c)
    saved = catalog.capture(root, now=NOW)
    assert pair_bytes(c) == before
    assert saved["status"] == "LOCAL_CAPTURED"
    assert not any(
        saved[k] for k in ("execution_authority", "network_calls", "off_host_protection")
    )
    assert root.stat().st_mode & 0o777 == 0o700
    job = root / saved["capture_id"]
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in job.iterdir())
    staged = checkpoint.stage_checkpoint(
        job / "checkpoint.tbcp", c.root / "review", expected_sha256=saved["checkpoint_sha256"]
    )
    assert staged["summary"]["halted_at_checkpoint"]
    assert staged["summary"]["active_orders"] == 1
    assert staged["summary"]["unresolved_attempts"] == 1
    assert staged["summary"]["unknown_model_calls"] == 0
    with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
        ExecutionEngine(c.root / "review" / "execution.evidence.db", c.engine.settings)
    assert c.venue.submit_count == 1 and pair_bytes(c) == before


def test_exclusive_initialization_and_new_generations_keep_source_binding(c):
    before = pair_bytes(c)
    root = initialize(c)
    policy = (root / "policy.json").read_bytes()
    with pytest.raises(FileExistsError):
        catalog.initialize_catalog(c.engine.journal.path, root)
    assert pair_bytes(c) == before and (root / "policy.json").read_bytes() == policy
    first = catalog.capture(root, now=NOW)
    c.engine.halt("new retained halt", now=NOW + timedelta(seconds=1))
    second = catalog.capture(root, now=NOW + timedelta(seconds=1))
    assert first["manifest"]["authority_id"] == second["manifest"]["authority_id"]
    assert first["manifest"]["generation"] < second["manifest"]["generation"]
    result = catalog.report(root, limit=1)
    assert result["completed"] == 2 and result["captures"][0]["capture_id"] == second["capture_id"]


@pytest.mark.parametrize(
    "options",
    [
        {"max_captures": 0},
        {"max_captures": 91},
        {"max_captures": True},
        {"timeout_seconds": 31},
        {"timeout_seconds": True},
    ],
)
def test_invalid_policy_does_not_create_catalog(c, options):
    before = pair_bytes(c)
    with pytest.raises(ValueError):
        initialize(c, **options)
    assert not (c.root / "captures").exists() and pair_bytes(c) == before


@pytest.mark.parametrize("fault", ["missing", "public", "symlink", "fifo"])
def test_bad_source_fails_before_admission(c, fault):
    root = initialize(c)
    path = c.engine.journal.path
    if fault == "public":
        path.chmod(0o644)
    else:
        original = path.with_suffix(".saved")
        path.rename(original)
        if fault == "symlink":
            path.symlink_to(original)
        elif fault == "fifo":
            os.mkfifo(path, mode=0o600)
    with pytest.raises((OSError, ValueError)):
        catalog.capture(root, now=NOW)
    assert not jobs(root)
    assert catalog.report(root)["admitted"] == 0


def test_foreign_pair_is_not_admitted(c, monkeypatch):
    root = initialize(c)
    actual = catalog._source

    def foreign(*args):
        fence, summary = actual(*args)
        return {**fence, "authority_id": "foreign"}, summary

    monkeypatch.setattr(catalog, "_source", foreign)
    with pytest.raises(ValueError, match="authority changed"):
        catalog.capture(root, now=NOW)
    assert not jobs(root)


@pytest.mark.parametrize("phase", ["export", "receipt"])
def test_failed_job_is_never_promoted_replayed_or_pruned(c, monkeypatch, phase):
    root = initialize(c, max_captures=2)
    before = pair_bytes(c)
    function = "export_checkpoint" if phase == "export" else "_publish"
    target = checkpoint if phase == "export" else catalog
    original = getattr(target, function)

    def fail(*args, **kwargs):
        raise OSError("fixture interruption")

    monkeypatch.setattr(target, function, fail)
    with pytest.raises(OSError):
        catalog.capture(root, now=NOW)
    orphan = jobs(root)[0]
    assert (orphan / "checkpoint.tbcp").exists() == (phase == "receipt")
    assert catalog.report(root)["incomplete"] == 1
    monkeypatch.setattr(target, function, original)
    saved = catalog.capture(root, now=NOW)
    assert saved["capture_id"] != orphan.name
    result = catalog.report(root)
    assert result["capacity_exhausted"] and result["incomplete"] == result["completed"] == 1
    with pytest.raises(catalog.CaptureLimitReached):
        catalog.capture(root, now=NOW)
    assert len(jobs(root)) == 2 and pair_bytes(c) == before


def test_low_space_rejects_before_admission(c, monkeypatch):
    root = initialize(c)
    before = pair_bytes(c)
    monkeypatch.setattr(catalog.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(ValueError, match="space"):
        catalog.capture(root, now=NOW)
    assert not jobs(root) and pair_bytes(c) == before


def test_source_check_and_export_share_one_cooperative_deadline(c, monkeypatch):
    root = initialize(c, timeout_seconds=0.005)
    actual = catalog._source

    def slow(*args):
        result = actual(*args)
        time.sleep(0.015)
        return result

    monkeypatch.setattr(catalog, "_source", slow)
    with pytest.raises(TimeoutError):
        catalog.capture(root, now=NOW)
    assert not jobs(root)


def test_source_rebinding_after_export_has_no_success_receipt(c, monkeypatch):
    root = initialize(c)
    actual = checkpoint.export_checkpoint

    def rebound(*args, **kwargs):
        result = actual(*args, **kwargs)
        result["manifest"]["authority_id"] = "foreign"
        return result

    monkeypatch.setattr(checkpoint, "export_checkpoint", rebound)
    with pytest.raises(ValueError, match="authority changed"):
        catalog.capture(root, now=NOW)
    assert catalog.report(root)["incomplete"] == 1


def test_capture_lease_spans_export_and_blocks_duplicate_without_admission(c, monkeypatch):
    root = initialize(c)
    entered, release = threading.Event(), threading.Event()
    original = checkpoint.export_checkpoint

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(checkpoint, "export_checkpoint", delayed)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(catalog.capture, root, now=NOW)
        try:
            assert entered.wait(3)
            with pytest.raises(catalog.CaptureAlreadyRunning):
                catalog.capture(root, now=NOW)
            assert len(jobs(root)) == 1 and catalog.report(root)["incomplete"] == 1
        finally:
            release.set()
        assert future.result()["status"] == "LOCAL_CAPTURED"


@pytest.mark.parametrize(
    "fault",
    [
        "bundle",
        "receipt",
        "receipt-id",
        "receipt-manifest",
        "duplicate",
        "oversized",
        "job-symlink",
        "policy-extra",
        "unexpected-entry",
        "public-root",
        "root-symlink",
        "lock-symlink",
    ],
)
def test_tampered_catalog_fails_closed(c, fault):
    root = initialize(c)
    saved = catalog.capture(root, now=NOW)
    job = root / saved["capture_id"]
    receipt = job / "receipt.json"
    if fault == "bundle":
        (job / "checkpoint.tbcp").write_bytes(b"changed")
    elif fault == "receipt":
        receipt.write_text("invalid")
    elif fault in {"receipt-id", "receipt-manifest"}:
        value = json.loads(receipt.read_text())
        if fault == "receipt-id":
            value["capture_id"] = "0" * 32
        else:
            value["manifest"]["generation"] += 1
        receipt.write_text(json.dumps(value))
    elif fault == "duplicate":
        receipt.write_text('{"capture_id":"' + saved["capture_id"] + '",' + receipt.read_text()[1:])
    elif fault == "oversized":
        receipt.write_text("x" * 8193)
    elif fault == "job-symlink":
        job.rename(root / "moved")
        job.symlink_to(root / "moved")
    elif fault == "policy-extra":
        value = json.loads((root / "policy.json").read_text())
        value["unknown"] = True
        (root / "policy.json").write_text(json.dumps(value))
    elif fault == "unexpected-entry":
        (root / "foreign").mkdir(mode=0o700)
    elif fault == "public-root":
        root.chmod(0o755)
    elif fault == "root-symlink":
        root.rename(c.root / "moved")
        root.symlink_to(c.root / "moved")
    else:
        (root / ".capture.lock").unlink()
        (root / ".capture.lock").symlink_to(receipt)
    with pytest.raises((ValueError, OSError)):
        catalog.capture(root, now=NOW) if fault == "lock-symlink" else catalog.report(root)


def test_cli_sanitizes_errors_and_retains_evidence_only_flags(c, capsys):
    root = c.root / "captures"
    assert (
        main(["capture-init", "--journal", str(c.engine.journal.path), "--directory", str(root)])
        == 0
    )
    assert main(["capture", "--directory", str(root)]) == 0
    assert main(["capture-report", "--directory", str(root)]) == 0
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(not r["execution_authority"] and not r["off_host_protection"] for r in outputs)
    assert main(["capture", "--directory", str(c.root / "credential-secret-path")]) == 1
    assert "credential-secret-path" not in capsys.readouterr().out


def native(*args):
    result = subprocess.run(
        [PYTHON, "-I", "-m", "app.execution.checkpoint_cli", *map(str, args)],
        capture_output=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stderr
    return json.loads(result.stdout)


def test_native_capture_report_and_quarantine_after_source_loss(c):
    root = c.root / "captures"
    native("capture-init", "--journal", c.engine.journal.path, "--directory", root)
    saved = native("capture", "--directory", root)
    c.engine.journal.path.unlink()
    Path(str(c.engine.journal.path) + ".authority.db").unlink()
    assert native("capture-report", "--directory", root)["completed"] == 1
    staged = native(
        "stage",
        "--bundle",
        root / saved["capture_id"] / "checkpoint.tbcp",
        "--sha256",
        saved["checkpoint_sha256"],
        "--output",
        c.root / "quarantine",
    )
    assert staged["summary"]["unknown_model_calls"] == 1 and not staged["execution_authority"]
    with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
        ExecutionEngine(c.root / "quarantine" / "execution.evidence.db", c.engine.settings)


def test_native_kill_during_paired_export_retains_incomplete_admission_and_releases_locks(c):
    root = initialize(c)
    marker = c.root / "backup-entered"
    before = pair_bytes(c)
    code = (
        "from app.execution import checkpoint, checkpoint_catalog; from pathlib import Path; import time\n"
        f"def block(*args, **kwargs):\n Path({str(marker)!r}).touch(); time.sleep(60)\n"
        "checkpoint._backup=block\n"
        f"checkpoint_catalog.capture({str(root)!r})\n"
    )
    process = subprocess.Popen(
        [PYTHON, "-I", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        end = time.monotonic() + 10
        while not marker.exists():
            assert process.poll() is None and time.monotonic() < end
            time.sleep(0.025)
        orphan = jobs(root)[0]
        process.send_signal(signal.SIGKILL)
        output, errors = process.communicate(timeout=5)
        assert process.returncode == -signal.SIGKILL and not output and not errors
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert native("capture-report", "--directory", root)["incomplete"] == 1
    saved = native("capture", "--directory", root)
    assert saved["capture_id"] != orphan.name and orphan.exists()
    assert native("capture-report", "--directory", root)["completed"] == 1
    assert pair_bytes(c) == before


def test_native_systemd_parser_and_network_disabled_checkpoint_contract(tmp_path):
    binary = shutil.which("systemd-analyze")
    if binary is None:
        pytest.skip("Native systemd parser unavailable")
    service = (UNITS / "trade-bot-paper-checkpoint.service").read_text()
    assert "PrivateNetwork=yes" in service and "RestrictAddressFamilies=AF_UNIX" in service
    assert "Restart=no" in service and "-/etc/trade-bot-paper" in service
    assert "Requires=" not in service and "PartOf=" not in service
    paths = []
    for suffix in ("service", "timer"):
        text = (UNITS / f"trade-bot-paper-checkpoint.{suffix}").read_text()
        text = text.replace("/opt/trade-bot-paper/venv/bin/python", PYTHON)
        text = text.replace("User=tradebot-paper", f"User={os.geteuid()}")
        text = text.replace("Group=tradebot-paper", f"Group={os.getegid()}")
        target = tmp_path / f"trade-bot-paper-checkpoint.{suffix}"
        target.write_text(text)
        paths.append(str(target))
    result = subprocess.run([binary, "verify", "--man=no", *paths], capture_output=True, timeout=15)
    assert result.returncode == 0 and not result.stderr
