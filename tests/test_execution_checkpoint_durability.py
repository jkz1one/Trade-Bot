"""Evidence success requires durable parent entries, without execution authority."""

import asyncio
import json
import os
import stat
from pathlib import Path

import pytest

from app.execution import checkpoint, checkpoint_transfer
from app.execution.checkpoint_cli import main
from app.execution.checkpoint_transfer import ArchiveConfig
from app.execution.engine import ExecutionEngine
from tests.test_execution_alert_delivery import (
    certificate as certificate,  # noqa: PLC0414 -- pytest fixture registration
)
from tests.test_execution_checkpoint import (
    archive as archive,  # noqa: PLC0414 -- pytest fixture registration
)
from tests.test_execution_checkpoint import c as c  # noqa: PLC0414 -- pytest fixture registration
from tests.test_execution_checkpoint import pair_bytes
from tests.test_execution_rehearsal import NOW


def flushed_paths(monkeypatch):
    events = []
    original = os.fsync

    def fsync(fd):
        original(fd)
        events.append(
            (Path(os.readlink(f"/proc/self/fd/{fd}")), stat.S_ISDIR(os.fstat(fd).st_mode))
        )

    monkeypatch.setattr(os, "fsync", fsync)
    return events


def hierarchy_before_work(events, ancestor, outer, inner):
    directories = [path for path, is_directory in events if is_directory]
    first = directories.index(outer)
    assert directories.index(ancestor, first + 1) < directories.index(inner)
    assert directories.index(outer, directories.index(inner) + 1) > directories.index(inner)
    assert outer.stat().st_mode & 0o777 == inner.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("operation", ("export", "stage"))
def test_nested_evidence_flushes_ancestors_and_final_publication(c, monkeypatch, operation):
    before = pair_bytes(c)
    events = flushed_paths(monkeypatch)
    outer, inner = c.root / "new-parent", c.root / "new-parent" / "new-child"
    if operation == "export":
        output = inner / "export.tbcp"
        result = checkpoint.export_checkpoint(c.engine.journal.path, output, now=NOW)
        assert checkpoint.inspect_checkpoint(output, expected_sha256=result["checkpoint_sha256"])
    else:
        output = inner / "review"
        result = checkpoint.stage_checkpoint(c.bundle, output, expected_sha256=c.pin)
        assert result["summary"]["unknown_model_calls"] == 1
        marker = events.index((output / "verified-evidence.json", False))
        assert events[marker + 1 : marker + 3] == [(output, True), (inner, True)]
        with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
            ExecutionEngine(output / "execution.evidence.db", c.engine.settings)
    assert not result["execution_authority"] and not result["network_calls"]
    hierarchy_before_work(events, c.root, outer, inner)
    # Parent entries were committed before any evidence file could be acknowledged.
    assert events.index((inner, True)) < next(
        i for i, (_, directory) in enumerate(events) if not directory
    )
    assert pair_bytes(c) == before


@pytest.mark.parametrize("failure", ("anchor", "new-directory", "new-parent"))
def test_ancestor_flush_failure_stops_export_and_explicit_retry_flushes_retained_directory(
    c, monkeypatch, failure
):
    before = pair_bytes(c)
    outer, inner = c.root / "new-parent", c.root / "new-parent" / "new-child"
    output = inner / "failed.tbcp"
    original = checkpoint._fsync_dir

    def failed(path):
        if (
            failure == "anchor"
            and path == c.root
            and not outer.exists()
            or failure == "new-directory"
            and path == outer
            or failure == "new-parent"
            and path == c.root
            and outer.exists()
        ):
            raise OSError("PRIVATE-FSYNC-PATH")
        original(path)

    with monkeypatch.context() as patch:
        patch.setattr(checkpoint, "_fsync_dir", failed)
        with pytest.raises(OSError):
            checkpoint.export_checkpoint(c.engine.journal.path, output, now=NOW)
    assert not output.exists() and pair_bytes(c) == before
    assert not list(c.root.rglob(".checkpoint-*"))
    if outer.exists():
        assert outer.stat().st_mode & 0o777 == 0o700
    events = flushed_paths(monkeypatch)
    result = checkpoint.export_checkpoint(c.engine.journal.path, inner / "distinct.tbcp", now=NOW)
    assert result["status"] == "EXPORTED" and pair_bytes(c) == before
    hierarchy_before_work(events, c.root, outer, inner)


def test_final_recovery_parent_flush_failure_cannot_report_success_or_keep_verified_marker(
    c, monkeypatch, capsys
):
    before = pair_bytes(c)
    parent = c.root / "new-parent"
    output = parent / "review"
    original = checkpoint._fsync_dir

    def failed(path):
        if path == parent and (output / "verified-evidence.json").exists():
            raise OSError("PRIVATE-FSYNC-PATH")
        original(path)

    with monkeypatch.context() as patch:
        patch.setattr(checkpoint, "_fsync_dir", failed)
        assert (
            main(["stage", "--bundle", str(c.bundle), "--sha256", c.pin, "--output", str(output)])
            == 1
        )
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "ERROR", "error_class": "OSError", "execution_authority": False}
    assert not output.exists() and pair_bytes(c) == before
    # An operator-selected distinct quarantine remains possible, never automatic replay.
    assert checkpoint.stage_checkpoint(c.bundle, parent / "distinct", expected_sha256=c.pin)


def test_nested_tls_retention_source_loss_and_quarantine_preserve_only_evidence(
    c, archive, monkeypatch
):
    events = flushed_paths(monkeypatch)
    real_run = checkpoint_transfer._run
    receipts = c.root / "receipts" / "session"
    recovery = c.root / "recovered" / "session"
    calls = []

    async def run(request):
        calls.append(request.operation)
        if request.operation == "PUT":
            hierarchy_before_work(events, c.root, receipts.parent, receipts)
            state = json.loads((receipts / "receipt.json").read_text())
            assert state["status"] == "IN_FLIGHT"
        else:
            hierarchy_before_work(events, c.root, recovery.parent, recovery)
        return await real_run(request)

    monkeypatch.setattr(checkpoint_transfer, "_run", run)
    accepted = asyncio.run(
        checkpoint_transfer.upload_checkpoint(
            c.bundle,
            archive.config,
            expected_sha256=c.pin,
            token_file=archive.token,
            receipt_file=receipts / "receipt.json",
        )
    )
    assert accepted["status"] == "REMOTE_ACCEPTED" and not accepted["execution_authority"]
    c.engine.journal.path.unlink()
    Path(str(c.engine.journal.path) + ".authority.db").unlink()
    c.bundle.unlink()
    downloaded = recovery / "checkpoint.tbcp"
    assert (
        asyncio.run(
            checkpoint_transfer.download_checkpoint(
                downloaded,
                archive.config,
                expected_sha256=c.pin,
                token_file=archive.token,
            )
        )["status"]
        == "DOWNLOADED_VERIFIED_EVIDENCE"
    )
    staged = recovery / "review"
    result = checkpoint.stage_checkpoint(downloaded, staged, expected_sha256=c.pin)
    assert result["summary"]["unknown_model_calls"] == 1 and not result["execution_authority"]
    assert calls == ["PUT", "GET"] and archive.calls == [("PUT", c.pin), ("GET", c.pin)]
    before = (staged / "execution.evidence.db").read_bytes()
    with pytest.raises(ValueError, match="RESTORE_AUTHORITY_MISSING"):
        ExecutionEngine(staged / "execution.evidence.db", c.engine.settings)
    assert (staged / "execution.evidence.db").read_bytes() == before
    assert not (staged / "execution.evidence.db.authority.db").exists()


@pytest.mark.parametrize("operation", ("upload", "download"))
def test_archive_parent_flush_failure_prevents_child_admission(c, monkeypatch, operation):
    before = pair_bytes(c)
    parent = c.root / "uncommitted" / "child"
    original = checkpoint._fsync_dir

    def failed(path):
        if path == parent.parent:
            raise OSError("PRIVATE-FSYNC-PATH")
        original(path)

    async def forbidden(request):
        raise AssertionError("Archive child admitted before directory durability")

    monkeypatch.setattr(checkpoint, "_fsync_dir", failed)
    monkeypatch.setattr(checkpoint_transfer, "_run", forbidden)
    config = ArchiveConfig(origin="https://archive.invalid")
    output = parent / "output"
    with pytest.raises(OSError):
        if operation == "upload":
            asyncio.run(
                checkpoint_transfer.upload_checkpoint(
                    c.bundle,
                    config,
                    expected_sha256=c.pin,
                    token_file=c.root / "unused.token",
                    receipt_file=output,
                )
            )
        else:
            asyncio.run(
                checkpoint_transfer.download_checkpoint(
                    output,
                    config,
                    expected_sha256=c.pin,
                    token_file=c.root / "unused.token",
                )
            )
    assert not output.exists() and pair_bytes(c) == before
    assert not list(c.root.rglob(".checkpoint-download-*"))


def test_existing_parent_modes_and_unrelated_evidence_are_not_changed(c):
    parent = c.root / "existing"
    parent.mkdir(mode=0o750)
    parent.chmod(0o750)  # The fixture's existing mode must not depend on the operator's umask.
    sentinel = parent / "retained-evidence"
    sentinel.write_bytes(b"retained")
    before = pair_bytes(c)
    result = checkpoint.export_checkpoint(c.engine.journal.path, parent / "new.tbcp", now=NOW)
    assert result["status"] == "EXPORTED"
    assert parent.stat().st_mode & 0o777 == 0o750 and sentinel.read_bytes() == b"retained"
    assert pair_bytes(c) == before
