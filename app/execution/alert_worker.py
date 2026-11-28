"""One verified-TLS sink request. No broker/model secrets or database handles."""

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

from app.execution.alerts import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    AlertReceipt,
    AlertRequest,
    ca_bytes,
)


def private_token(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
            or info.st_size not in {64, 65}
        ):
            raise ValueError("Private owner-only token file required")
        value = os.read(fd, 66).decode("ascii")
        if len(value) == 65 and value.endswith("\n"):
            value = value[:-1]
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("A 32-byte lowercase hex sink token is required")
        return value
    finally:
        os.close(fd)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate receipt fields")
        result[key] = value
    return result


def perform(request):
    if (request.ca_file is None) != (request.ca_sha256 is None):
        raise ValueError("CA binding required")
    body = request.message.model_dump_json().encode()
    if hashlib.sha256(body).hexdigest() != request.payload_sha256:
        raise ValueError("Alert payload binding mismatch")
    context = ssl.create_default_context()
    if request.ca_file:
        ca = ca_bytes(request.ca_file)
        if hashlib.sha256(ca).hexdigest() != request.ca_sha256:
            raise ValueError("CA configuration changed")
        context.load_verify_locations(cadata=ca.decode("ascii"))
    token = private_token(request.token_file)
    remaining = request.deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Alert deadline expired")
    origin = urlsplit(request.config.origin)
    # http.client neither follows redirects nor discovers proxies from the environment.
    connection = http.client.HTTPSConnection(
        origin.hostname,
        port=origin.port or 443,
        timeout=remaining,
        context=context,
    )
    try:
        connection.request(
            "POST",
            "/v1/alerts",
            body=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Idempotency-Key": request.message.delivery_id,
            },
        )
        response = connection.getresponse()
        if (
            response.status not in {200, 202}
            or response.getheader("Content-Type", "").split(";")[0].strip() != "application/json"
            or response.getheader("Content-Encoding") not in {None, "identity"}
        ):
            raise ValueError("Sink did not return an accepted JSON receipt")
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("Sink receipt exceeded protocol limit")
        receipt = AlertReceipt.model_validate(json.loads(data, object_pairs_hook=unique_object))
        if (
            not receipt.accepted
            or receipt.delivery_id != request.message.delivery_id
            or receipt.payload_sha256 != request.payload_sha256
        ):
            raise ValueError("Sink receipt binding mismatch")
        return receipt
    finally:
        connection.close()


def _watch(request):
    while os.getppid() == request.parent_pid and time.monotonic() < request.deadline_monotonic:
        time.sleep(0.05)
    os._exit(98)


def main():
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            return 1
        request = AlertRequest.model_validate_json(data)
        if os.getppid() != request.parent_pid:
            return 1
        threading.Thread(target=_watch, args=(request,), daemon=True).start()
        result = perform(request)
        sys.stdout.write(result.model_dump_json())
        return 0
    except Exception:  # noqa: BLE001 -- errors must not print sink credentials or payload
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
