"""Explicit bounded archive transfer. Receipts are evidence, never trading enablement."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.domain.models import utc_now
from app.execution.alerts import AlertConfig, ca_bytes
from app.execution.checkpoint import (
    HASH,
    MAX_BYTES,
    _durable_directory,
    _fsync_dir,
    _pin,
    inspect_checkpoint,
    private_file,
)
from app.execution.models import Contract
from app.execution.process import _cleanup


class ArchiveConfig(Contract):
    origin: str = Field(max_length=256)
    timeout_seconds: float = Field(default=30, gt=0, le=30)
    ca_file: str | None = Field(default=None, max_length=1024)
    ca_sha256: str | None = Field(default=None, pattern=HASH)

    @field_validator("origin")
    @classmethod
    def pinned_https(cls, value):
        return AlertConfig(origin=value).origin

    @model_validator(mode="after")
    def paired(self):
        if (self.ca_file is None) != (self.ca_sha256 is None):
            raise ValueError("Optional CA path and digest must be paired")
        return self


def archive_config(origin, *, ca_file=None, timeout_seconds=30):
    path = str(Path(ca_file).expanduser().absolute()) if ca_file else None
    digest = hashlib.sha256(ca_bytes(path)).hexdigest() if path else None
    return ArchiveConfig(
        origin=origin, ca_file=path, ca_sha256=digest, timeout_seconds=timeout_seconds
    )


class ArchiveReceipt(Contract):
    checkpoint_sha256: str = Field(pattern=HASH)
    byte_count: int = Field(gt=0, le=MAX_BYTES, strict=True)
    retained: bool = Field(strict=True)


class TransferRequest(Contract):
    operation: Literal["PUT", "GET"]
    config: ArchiveConfig
    checkpoint_sha256: str = Field(pattern=HASH)
    path: str = Field(min_length=1, max_length=1024)
    token_file: str = Field(min_length=1, max_length=1024)
    byte_count: int | None = Field(default=None, gt=0, le=MAX_BYTES, strict=True)
    parent_pid: int = Field(gt=0, strict=True)
    deadline_monotonic: float = Field(gt=0)

    @model_validator(mode="after")
    def paired(self):
        if (self.operation == "PUT") != (self.byte_count is not None):
            raise ValueError("Only upload includes the local byte count")
        return self


class TransferState(Contract):
    schema_version: Literal["checkpoint-transfer-v1"] = "checkpoint-transfer-v1"
    checkpoint_sha256: str = Field(pattern=HASH)
    configuration_hash: str = Field(pattern=HASH)
    attempt: int = Field(gt=0, strict=True)
    status: Literal["IN_FLIGHT", "UNKNOWN", "REMOTE_ACCEPTED"]
    started_at: datetime
    receipt: ArchiveReceipt | None = None

    @model_validator(mode="after")
    def paired(self):
        if (self.status == "REMOTE_ACCEPTED") != (self.receipt is not None):
            raise ValueError("Only confirmed retention has a receipt")
        if self.receipt and (
            not self.receipt.retained or self.receipt.checkpoint_sha256 != self.checkpoint_sha256
        ):
            raise ValueError("Receipt must match the checkpoint")
        return self


async def _run(request):
    payload = request.model_dump_json().encode()
    if len(payload) > 8192:
        raise ValueError("Archive transfer request exceeded limit")
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "app.execution.checkpoint_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ},
        )
    )
    process = None
    try:
        async with asyncio.timeout(max(0, request.deadline_monotonic - time.monotonic())):
            process = await asyncio.shield(spawn)
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            data = bytearray()
            while chunk := await process.stdout.read(1024):
                data.extend(chunk)
                if len(data) > 1024:
                    raise ValueError("Archive receipt exceeded limit")
            await process.wait()
            if process.returncode:
                raise ValueError("Archive transfer did not confirm evidence")
            result = ArchiveReceipt.model_validate_json(data)
            if (
                not result.retained
                or result.checkpoint_sha256 != request.checkpoint_sha256
                or request.byte_count is not None
                and result.byte_count != request.byte_count
            ):
                raise ValueError("Archive receipt binding mismatch")
            return result
    finally:
        if process is None:
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
            if not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
        if process is not None:
            await _cleanup(process)


def _save(path, state):
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(state.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def upload_checkpoint(
    bundle, config, *, expected_sha256, token_file, receipt_file, retry=False
):
    _pin(expected_sha256)
    config = ArchiveConfig.model_validate(config.model_dump())
    bundle = Path(bundle).expanduser().absolute()
    inspected = inspect_checkpoint(bundle, expected_sha256=expected_sha256)
    size = bundle.stat().st_size
    token = str(Path(token_file).expanduser().absolute())
    configuration_hash = hashlib.sha256(
        json.dumps(
            {
                **config.model_dump(mode="json"),
                "token_file": token,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    state_path = Path(receipt_file).expanduser().absolute()
    _durable_directory(state_path.parent)
    lock_path = Path(str(state_path) + ".lock")
    lock = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        # Reuse the same private-file checks for the lock without requiring nonempty contents.
        info = os.fstat(lock)
        import stat

        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("Private regular receipt lock required")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prior = None
        if state_path.exists() or state_path.is_symlink():
            with private_file(state_path, max_bytes=4096) as stream:
                prior = TransferState.model_validate_json(stream.read())
            if (
                prior.checkpoint_sha256 != expected_sha256
                or prior.configuration_hash != configuration_hash
            ):
                raise ValueError(
                    "Existing transfer belongs to a different checkpoint or destination"
                )
            if prior.status == "REMOTE_ACCEPTED":
                return {
                    "status": "EXISTING_RECEIPT",
                    "receipt": prior.receipt.model_dump(),
                    "network_calls": False,
                    "execution_authority": False,
                }
            if not retry:
                raise ValueError("Unconfirmed transfer requires an explicit same-ID retry")
        else:
            fd = os.open(state_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        state = TransferState(
            checkpoint_sha256=expected_sha256,
            configuration_hash=configuration_hash,
            attempt=prior.attempt + 1 if prior else 1,
            status="IN_FLIGHT",
            started_at=utc_now(),
        )
        _save(state_path, state)  # Durable admission before the child can contact the archive.
        request = TransferRequest(
            operation="PUT",
            config=config,
            checkpoint_sha256=expected_sha256,
            path=str(bundle),
            token_file=token,
            byte_count=size,
            parent_pid=os.getpid(),
            deadline_monotonic=time.monotonic() + config.timeout_seconds,
        )
        try:
            receipt = await _run(request)
        except asyncio.CancelledError:
            raise  # IN_FLIGHT is deliberately not assumed absent from the archive.
        except Exception:  # noqa: BLE001 -- no endpoint/credential/response text in receipts
            _save(state_path, state.model_copy(update={"status": "UNKNOWN"}))
            raise ValueError(
                "Archive retention unconfirmed; inspect or explicitly retry the same checkpoint"
            ) from None
        _save(
            state_path, state.model_copy(update={"status": "REMOTE_ACCEPTED", "receipt": receipt})
        )
        return {
            "status": "REMOTE_ACCEPTED",
            "receipt": receipt.model_dump(),
            "authority_id": inspected["manifest"]["authority_id"],
            "network_calls": True,
            "execution_authority": False,
        }
    finally:
        os.close(lock)


async def download_checkpoint(output, config, *, expected_sha256, token_file):
    _pin(expected_sha256)
    config = ArchiveConfig.model_validate(config.model_dump())
    target = Path(output).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise ValueError("Download requires a new output file")
    _durable_directory(target.parent)
    fd, name = tempfile.mkstemp(prefix=".checkpoint-download-", dir=target.parent)
    os.close(fd)
    try:
        request = TransferRequest(
            operation="GET",
            config=config,
            checkpoint_sha256=expected_sha256,
            path=name,
            token_file=str(Path(token_file).expanduser().absolute()),
            parent_pid=os.getpid(),
            deadline_monotonic=time.monotonic() + config.timeout_seconds,
        )
        result = await _run(request)
        if Path(name).stat().st_size != result.byte_count:
            raise ValueError("Downloaded size does not match child receipt")
        inspect_checkpoint(name, expected_sha256=expected_sha256)
        os.link(name, target)
        _fsync_dir(target.parent)
        return {
            "status": "DOWNLOADED_VERIFIED_EVIDENCE",
            "receipt": result.model_dump(),
            "network_calls": True,
            "execution_authority": False,
        }
    finally:
        os.unlink(name)
