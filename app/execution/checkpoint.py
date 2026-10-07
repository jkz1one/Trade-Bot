"""Private paired execution evidence checkpoints. Recovery never grants execution authority."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import struct
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field

from app.domain.models import utc_now
from app.execution import restore
from app.execution.journal import ExecutionJournal
from app.execution.models import Contract

MAGIC = b"TBCKPT1\n"
MAX_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 4096
HASH = r"^[0-9a-f]{64}$"


class CheckpointManifest(Contract):
    schema_version: Literal["execution-evidence-checkpoint-v1"] = "execution-evidence-checkpoint-v1"
    created_at: datetime
    authority_id: str = Field(min_length=1, max_length=64)
    generation: int = Field(ge=0, strict=True)
    state_hash: str = Field(pattern=HASH)
    journal_bytes: int = Field(gt=0, le=MAX_BYTES, strict=True)
    journal_sha256: str = Field(pattern=HASH)
    authority_bytes: int = Field(gt=0, le=MAX_BYTES, strict=True)
    authority_sha256: str = Field(pattern=HASH)


def private_file(path, *, max_bytes=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
            or not 0 < info.st_size <= max_bytes
        ):
            raise ValueError("A bounded private owner-only regular file is required")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def file_hash(stream):
    digest = hashlib.sha256()
    size = 0
    while data := stream.read(65536):
        size += len(data)
        if size > MAX_BYTES:
            raise ValueError("Checkpoint exceeded size limit")
        digest.update(data)
    return digest.hexdigest(), size


def _pin(value):
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("An independently retained lowercase SHA-256 pin is required")


def _deadline(value):
    if type(value) not in {int, float} or not 0 < value <= 30:
        raise ValueError("A bounded checkpoint deadline is required")
    return time.monotonic() + value


def _check_time(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("Checkpoint deadline exceeded")


def _db(path, *, writable=False, deadline):
    _check_time(deadline)
    db = sqlite3.connect(
        "file:" + quote(str(path)) + "?mode=" + ("rw" if writable else "ro"),
        uri=True,
        timeout=min(5, max(0, deadline - time.monotonic())),
        isolation_level=None,
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA trusted_schema=OFF")
    db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    return db


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _backup(source, target, deadline):
    with target.open("xb"):
        target.chmod(0o600)
    original = _db(source, deadline=deadline)
    snapshot = sqlite3.connect(target)
    try:

        def progress(status, remaining, total):
            _check_time(deadline)
            if total * original.execute("PRAGMA page_size").fetchone()[0] > MAX_BYTES:
                raise ValueError("Database exceeded checkpoint size limit")

        original.backup(snapshot, pages=128, progress=progress, sleep=0.01)
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Checkpoint SQLite integrity check failed")
    finally:
        snapshot.close()
        original.close()


def _pair(journal, authority, deadline):
    db = _db(journal, deadline=deadline)
    try:
        db.execute("BEGIN")
        fence = restore.status(db, authority)
        if fence["status"] != "VERIFIED":
            raise ValueError(fence.get("reason", "Verified restore authority required"))
        control = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
        if not control or json.loads(control["config_json"])["schema"] != "execution-rehearsal-v1":
            raise ValueError("Execution evidence schema is incompatible")
        value = db.execute(
            "SELECT state_hash FROM authority.restore_authority WHERE id=1"
        ).fetchone()[0]
        summary = {
            "halted_at_checkpoint": bool(control["halted"]),
            "active_orders": db.execute(
                "SELECT COUNT(*) FROM execution_orders WHERE active_lock=1"
            ).fetchone()[0],
            "unresolved_attempts": db.execute(
                "SELECT COUNT(*) FROM execution_orders WHERE status IN ('SUBMITTING','UNKNOWN')"
            ).fetchone()[0],
            "unknown_model_calls": db.execute(
                "SELECT COUNT(*) FROM execution_model_calls WHERE usage_json IS NULL"
            ).fetchone()[0],
            "revision": ExecutionJournal.revision(db),
        }
        return {**fence, "state_hash": value}, summary
    finally:
        db.close()


def export_checkpoint(journal_path, output, *, now=None, timeout_seconds=10):
    now = now or utc_now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Checkpoint clock must be timezone-aware")
    deadline = _deadline(timeout_seconds)
    source = Path(journal_path).expanduser().absolute()
    authority = restore.authority_path(source)
    target = Path(output).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise ValueError("Checkpoint output must be a new file")
    for path in (source, authority):
        with private_file(path):
            pass
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".checkpoint-", dir=target.parent))
    lock = None
    try:
        lock = _db(source, writable=True, deadline=deadline)
        # Hold both RESERVED locks, then use separate read connections for backup.
        # Never advance the source authority generation or commit a source mutation.
        if not restore.begin_fenced_write(lock, authority):
            raise ValueError("Verified restore authority required")
        journal_copy, authority_copy = stage / "journal.db", stage / "authority.db"
        _backup(source, journal_copy, deadline)
        _backup(authority, authority_copy, deadline)
        lock.rollback()
        fence, _ = _pair(journal_copy, authority_copy, deadline)
        with private_file(journal_copy) as stream:
            journal_hash, journal_size = file_hash(stream)
        with private_file(authority_copy) as stream:
            authority_hash, authority_size = file_hash(stream)
        manifest = CheckpointManifest(
            created_at=now.astimezone(UTC),
            authority_id=fence["authority_id"],
            generation=fence["generation"],
            state_hash=fence["state_hash"],
            journal_bytes=journal_size,
            journal_sha256=journal_hash,
            authority_bytes=authority_size,
            authority_sha256=authority_hash,
        )
        header = manifest.model_dump_json().encode()
        size = len(MAGIC) + 4 + len(header) + journal_size + authority_size
        if len(header) > MAX_MANIFEST_BYTES or size > MAX_BYTES:
            raise ValueError("Checkpoint exceeded size limit")
        bundle = stage / "checkpoint.tbcp"
        with bundle.open("xb") as stream:
            bundle.chmod(0o600)
            stream.write(MAGIC + struct.pack(">I", len(header)) + header)
            for path in (journal_copy, authority_copy):
                with private_file(path) as original:
                    shutil.copyfileobj(original, stream, length=65536)
            stream.flush()
            os.fsync(stream.fileno())
        with private_file(bundle) as stream:
            digest, size = file_hash(stream)
        _check_time(deadline)
        os.link(bundle, target)  # Exclusive publication: no overwrite or final symlink traversal.
        _fsync_dir(target.parent)
        return {
            "status": "EXPORTED",
            "checkpoint_sha256": digest,
            "byte_count": size,
            "manifest": manifest.model_dump(mode="json"),
            "network_calls": False,
            "execution_authority": False,
        }
    finally:
        if lock is not None:
            lock.close()
        shutil.rmtree(stage)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate checkpoint manifest fields")
        result[key] = value
    return result


def _unpack(bundle, stage, expected_sha256, deadline):
    _pin(expected_sha256)
    with private_file(bundle) as stream:
        digest, total_size = file_hash(stream)
        if digest != expected_sha256:
            raise ValueError("Checkpoint does not match independently retained pin")
        stream.seek(0)
        if stream.read(len(MAGIC)) != MAGIC:
            raise ValueError("Invalid checkpoint envelope")
        length = stream.read(4)
        if (
            len(length) != 4
            or not 0 < (header_size := struct.unpack(">I", length)[0]) <= MAX_MANIFEST_BYTES
        ):
            raise ValueError("Invalid checkpoint manifest size")
        header = stream.read(header_size)
        if len(header) != header_size:
            raise ValueError("Truncated checkpoint manifest")
        manifest = CheckpointManifest.model_validate(json.loads(header, object_pairs_hook=_unique))
        if (
            len(MAGIC) + 4 + header_size + manifest.journal_bytes + manifest.authority_bytes
            != total_size
        ):
            raise ValueError("Checkpoint byte counts do not match")
        for name, size, expected in (
            ("execution.evidence.db", manifest.journal_bytes, manifest.journal_sha256),
            ("authority.evidence.db", manifest.authority_bytes, manifest.authority_sha256),
        ):
            with (stage / name).open("xb") as output:
                (stage / name).chmod(0o600)
                remaining = size
                digest = hashlib.sha256()
                while remaining:
                    _check_time(deadline)
                    chunk = stream.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError("Truncated checkpoint database")
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
                if digest.hexdigest() != expected:
                    raise ValueError("Checkpoint member hash mismatch")
    journal, authority = stage / "execution.evidence.db", stage / "authority.evidence.db"
    for path in (journal, authority):
        db = _db(path, deadline=deadline)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Checkpoint SQLite integrity check failed")
        finally:
            db.close()
    fence, summary = _pair(journal, authority, deadline)
    if any(fence[k] != getattr(manifest, k) for k in ("authority_id", "generation", "state_hash")):
        raise ValueError("Checkpoint manifest authority binding mismatch")
    return manifest, summary


def inspect_checkpoint(bundle, *, expected_sha256, timeout_seconds=10):
    with tempfile.TemporaryDirectory(prefix="trade-bot-evidence-") as directory:
        manifest, summary = _unpack(
            Path(bundle), Path(directory), expected_sha256, _deadline(timeout_seconds)
        )
    return {
        "status": "VERIFIED_EVIDENCE",
        "checkpoint_sha256": expected_sha256,
        "manifest": manifest.model_dump(mode="json"),
        "summary": summary,
        "execution_authority": False,
        "network_calls": False,
    }


def stage_checkpoint(bundle, output_directory, *, expected_sha256, timeout_seconds=10):
    destination = Path(output_directory).expanduser().absolute()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.mkdir(mode=0o700, exist_ok=False)
    try:
        manifest, summary = _unpack(
            Path(bundle), destination, expected_sha256, _deadline(timeout_seconds)
        )
        result = {
            "status": "QUARANTINED_EVIDENCE",
            "checkpoint_sha256": expected_sha256,
            "manifest": manifest.model_dump(mode="json"),
            "summary": summary,
            "execution_authority": False,
            "network_calls": False,
        }
        marker = destination / "verified-evidence.json"
        with marker.open("x") as stream:
            marker.chmod(0o600)
            json.dump(result, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_dir(destination)
        return result
    except BaseException:
        shutil.rmtree(destination)
        raise
