"""One private TLS archive operation. Never broker/model calls or journal writes."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import ssl
import stat
import sys
import threading
import time
from urllib.parse import urlsplit

from app.execution.alert_worker import private_token, unique_object
from app.execution.alerts import ca_bytes
from app.execution.checkpoint import MAX_BYTES, file_hash, private_file
from app.execution.checkpoint_transfer import ArchiveReceipt, TransferRequest


def perform(request):
    context = ssl.create_default_context()
    if request.config.ca_file:
        ca = ca_bytes(request.config.ca_file)
        if hashlib.sha256(ca).hexdigest() != request.config.ca_sha256:
            raise ValueError("Archive CA configuration changed")
        context.load_verify_locations(cadata=ca.decode("ascii"))
    token = private_token(request.token_file)
    remaining = request.deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Archive deadline expired")
    origin = urlsplit(request.config.origin)
    connection = http.client.HTTPSConnection(
        origin.hostname, port=origin.port or 443, timeout=remaining, context=context
    )
    path = "/v1/checkpoints/" + request.checkpoint_sha256
    try:
        headers = {"Authorization": "Bearer " + token}
        if request.operation == "PUT":
            with private_file(request.path) as source:
                digest, size = file_hash(source)
                if digest != request.checkpoint_sha256 or size != request.byte_count:
                    raise ValueError("Archive payload changed before submission")
                source.seek(0)
                headers.update(
                    {
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(size),
                        "Idempotency-Key": digest,
                    }
                )
                connection.request("PUT", path, body=source, headers=headers)
            response = connection.getresponse()
            if (
                response.status not in {200, 201}
                or response.getheader("Content-Encoding") not in {None, "identity"}
                or response.getheader("Content-Type", "").split(";")[0].strip()
                != "application/json"
            ):
                raise ValueError("Archive did not return a retention receipt")
            data = response.read(1025)
            if len(data) > 1024:
                raise ValueError("Archive receipt exceeded limit")
            receipt = ArchiveReceipt.model_validate(
                json.loads(data, object_pairs_hook=unique_object)
            )
            if (
                not receipt.retained
                or receipt.checkpoint_sha256 != digest
                or receipt.byte_count != size
            ):
                raise ValueError("Archive receipt binding mismatch")
            return receipt
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        length = response.getheader("Content-Length", "")
        if (
            response.status != 200
            or response.getheader("Content-Encoding") not in {None, "identity"}
            or response.getheader("Content-Type", "").split(";")[0].strip()
            != "application/octet-stream"
            or not length.isascii()
            or not length.isdecimal()
            or len(length) > 9
            or not 0 < int(length) <= MAX_BYTES
        ):
            raise ValueError("Archive did not return a bounded checkpoint")
        fd = os.open(request.path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
                or info.st_size != 0
            ):
                raise ValueError("Private empty download staging file required")
            with os.fdopen(fd, "wb", closefd=False) as target:
                digest = hashlib.sha256()
                size = 0
                while data := response.read(65536):
                    size += len(data)
                    if size > int(length) or size > MAX_BYTES:
                        raise ValueError("Archive download exceeded limit")
                    target.write(data)
                    digest.update(data)
                target.flush()
                os.fsync(target.fileno())
            if digest.hexdigest() != request.checkpoint_sha256 or size != int(length):
                raise ValueError("Downloaded checkpoint does not match the retained pin")
            return ArchiveReceipt(
                checkpoint_sha256=digest.hexdigest(), byte_count=size, retained=True
            )
        finally:
            os.close(fd)
    finally:
        connection.close()


def _watch(request):
    while os.getppid() == request.parent_pid and time.monotonic() < request.deadline_monotonic:
        time.sleep(0.05)
    os._exit(94)


def main():
    try:
        data = sys.stdin.buffer.read(8193)
        if len(data) > 8192:
            return 1
        request = TransferRequest.model_validate_json(data)
        if os.getppid() != request.parent_pid:
            return 1
        threading.Thread(target=_watch, args=(request,), daemon=True).start()
        result = perform(request)
        sys.stdout.write(result.model_dump_json())
        return 0
    except Exception:  # noqa: BLE001 -- credentials, paths and payloads must not enter logs
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
