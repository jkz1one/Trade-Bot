"""Bounded local evidence captures. Never restores execution authority or sends data."""

import fcntl
import json
import os
import re
import shutil
import stat
import struct
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from app.execution import checkpoint
from app.execution.models import Contract

CAPTURE_ID = r"^[0-9a-f]{32}$"


class CapturePolicy(Contract):
    schema_version: Literal["local-checkpoint-catalog-v1"] = "local-checkpoint-catalog-v1"
    journal: str = Field(min_length=1, max_length=2048)
    authority_id: str = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(gt=0, le=30, strict=True)
    max_captures: int = Field(ge=1, le=90, strict=True)


class CaptureReceipt(Contract):
    schema_version: Literal["local-checkpoint-receipt-v1"] = "local-checkpoint-receipt-v1"
    capture_id: str = Field(pattern=CAPTURE_ID)
    checkpoint_sha256: str = Field(pattern=checkpoint.HASH)
    byte_count: int = Field(gt=0, le=checkpoint.MAX_BYTES, strict=True)
    manifest: checkpoint.CheckpointManifest
    status: Literal["LOCAL_CAPTURED"] = "LOCAL_CAPTURED"
    execution_authority: Literal[False] = False
    off_host_protection: Literal[False] = False


class CaptureAlreadyRunning(RuntimeError):
    pass


class CaptureLimitReached(RuntimeError):
    pass


def _directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise ValueError("A private owner-only directory is required")
        return Path(path).resolve()
    finally:
        os.close(fd)


def _source(path, timeout):
    with checkpoint.private_file(path), checkpoint.private_file(str(path) + ".authority.db"):
        return checkpoint._pair(
            Path(path), Path(str(path) + ".authority.db"), checkpoint._deadline(timeout)
        )


def _publish(path, value):
    staging = path.parent / (".receipt-" + uuid4().hex)
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value.model_dump_json().encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path)
        checkpoint._fsync_dir(path.parent)
    finally:
        staging.unlink(missing_ok=True)


def initialize_catalog(journal, directory, *, timeout_seconds=10, max_captures=30):
    checkpoint._deadline(timeout_seconds)
    fence, _ = _source(journal, timeout_seconds)
    policy = CapturePolicy(
        journal=str(Path(journal).resolve()),
        authority_id=fence["authority_id"],
        timeout_seconds=timeout_seconds,
        max_captures=max_captures,
    )
    root = Path(directory)
    root.mkdir(mode=0o700)
    root = _directory(root)
    _publish(root / "policy.json", policy)
    checkpoint._fsync_dir(root.parent)
    return {"status": "INITIALIZED", "policy": policy.model_dump(mode="json"), **_flags()}


def _policy(root):
    policy = _read(root / "policy.json", CapturePolicy, 4096)
    path = Path(policy.journal)
    if not path.is_absolute() or str(path) != os.path.normpath(policy.journal):
        raise ValueError("Catalog journal must be canonical and absolute")
    return policy


def _read(path, contract, bound):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    with checkpoint.private_file(path, max_bytes=bound) as stream:
        data = stream.read(bound + 1)
        if len(data) > bound:
            raise ValueError("Catalog JSON exceeded its size bound")
        return contract.model_validate_json(json.dumps(json.loads(data, object_pairs_hook=unique)))


def _jobs(root, policy):
    jobs = []
    with os.scandir(root) as entries:
        for count, entry in enumerate(entries, 1):
            if count > policy.max_captures + 2:
                raise ValueError("Catalog exceeded its bounded capacity")
            if entry.name in {"policy.json", ".capture.lock"}:
                continue
            if not re.fullmatch(CAPTURE_ID, entry.name):
                raise ValueError("Unexpected catalog entry")
            jobs.append(_directory(root / entry.name))
    if len(jobs) > policy.max_captures:
        raise ValueError("Catalog exceeded its bounded capacity")
    return sorted(jobs, key=lambda p: p.name)


@contextmanager
def _lease(root):
    fd = os.open(
        root / ".capture.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("Invalid capture lease file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CaptureAlreadyRunning("A capture already holds this catalog") from exc
        yield
    finally:
        os.close(fd)


def _flags():
    return {"network_calls": False, "execution_authority": False, "off_host_protection": False}


def capture(directory, *, now=None):
    root = _directory(directory)
    with _lease(root):
        policy = _policy(root)
        deadline = checkpoint._deadline(policy.timeout_seconds)
        if len(_jobs(root, policy)) >= policy.max_captures:
            raise CaptureLimitReached(
                "Explicitly provision a separate catalog after evidence review"
            )
        if shutil.disk_usage(root).free < 2 * checkpoint.MAX_BYTES + 8192:
            raise ValueError("Insufficient space for a bounded paired capture")
        fence, _ = _source(policy.journal, max(0, deadline - time.monotonic()))
        if fence["authority_id"] != policy.authority_id:
            raise ValueError("Catalog source authority changed")
        checkpoint._check_time(deadline)
        job = root / uuid4().hex
        job.mkdir(mode=0o700)
        checkpoint._fsync_dir(root)
        result = checkpoint.export_checkpoint(
            policy.journal,
            job / "checkpoint.tbcp",
            now=now,
            timeout_seconds=max(0, deadline - time.monotonic()),
        )
        if result["manifest"]["authority_id"] != policy.authority_id:
            raise ValueError("Capture source authority changed")
        receipt = CaptureReceipt(
            capture_id=job.name,
            checkpoint_sha256=result["checkpoint_sha256"],
            byte_count=result["byte_count"],
            manifest=result["manifest"],
        )
        checkpoint._check_time(deadline)
        _publish(job / "receipt.json", receipt)
        return {**receipt.model_dump(mode="json"), **_flags()}


def report(directory, *, limit=25):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("A bounded report limit is required")
    root = _directory(directory)
    policy = _policy(root)
    rows = []
    for job in _jobs(root, policy):
        try:
            receipt = _read(job / "receipt.json", CaptureReceipt, 8192)
        except FileNotFoundError:
            rows.append({"capture_id": job.name, "status": "INCOMPLETE"})
            continue
        if receipt.capture_id != job.name or receipt.manifest.authority_id != policy.authority_id:
            raise ValueError("Receipt binding mismatch")
        with checkpoint.private_file(job / "checkpoint.tbcp") as stream:
            digest, size = checkpoint.file_hash(stream)
            stream.seek(0)
            if stream.read(len(checkpoint.MAGIC)) != checkpoint.MAGIC:
                raise ValueError("Invalid checkpoint envelope")
            header_size = struct.unpack(">I", stream.read(4))[0]
            if not 0 < header_size <= checkpoint.MAX_MANIFEST_BYTES:
                raise ValueError("Invalid checkpoint manifest size")
            manifest = checkpoint.CheckpointManifest.model_validate(
                json.loads(stream.read(header_size), object_pairs_hook=checkpoint._unique)
            )
        if digest != receipt.checkpoint_sha256 or size != receipt.byte_count:
            raise ValueError("Local checkpoint digest mismatch")
        if manifest != receipt.manifest:
            raise ValueError("Receipt manifest mismatch")
        rows.append(receipt.model_dump(mode="json"))
    completed = sum(row["status"] == "LOCAL_CAPTURED" for row in rows)
    rows.sort(key=lambda row: (row.get("manifest", {}).get("created_at", ""), row["capture_id"]))
    return {
        "status": "LOCAL_CATALOG",
        "admitted": len(rows),
        "completed": completed,
        "incomplete": len(rows) - completed,
        "max_captures": policy.max_captures,
        "capacity_exhausted": len(rows) == policy.max_captures,
        "captures": rows[-limit:],
        **_flags(),
    }
