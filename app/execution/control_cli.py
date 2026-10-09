"""Native TLS companion for a previously enrolled isolated PAPER operator capability."""

from __future__ import annotations

import argparse
import fcntl
import ipaddress
import json
import os
import signal
import ssl
import stat
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from app.execution.control_api import ControlAPIConfig, create_control_app
from app.execution.engine import ExecutionEngine


class ControlAlreadyRunning(RuntimeError):
    pass


@contextmanager
def control_lease(journal):
    journal = Path(journal).expanduser().absolute()
    retained = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(retained)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("A private owned existing execution journal is required")
        journal = journal.resolve(strict=True)
    finally:
        os.close(retained)
    fd = os.open(
        str(journal) + ".control.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("Private current-owner control lock required")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ControlAlreadyRunning("A control companion already owns this journal") from None
        yield journal
    finally:
        os.close(fd)


def _tls_file(path, *, private):
    path = Path(path).expanduser().absolute()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or not 0 < info.st_size <= 1024 * 1024
            or (private and stat.S_IMODE(info.st_mode) != 0o600)
        ):
            raise ValueError("Bounded owned TLS files and a private key are required")
    finally:
        os.close(fd)
    return str(path)


def serve(journal, *, origin, operator_key_file, read_token_file, certfile, keyfile, host, port):
    # No env-selected bind, proxy authority, plaintext fallback or interactive key password.
    ipaddress.ip_address(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("A bounded explicit listener port is required")
    api_config = ControlAPIConfig(origin=origin)
    with control_lease(journal) as path:
        engine = ExecutionEngine.attach_existing(path)
        app = create_control_app(
            engine,
            api_config,
            operator_key_file=operator_key_file,
            read_token_file=read_token_file,
        )
        certfile, keyfile = _tls_file(certfile, private=False), _tls_file(keyfile, private=True)

        def no_password():
            raise ValueError("Interactive TLS key passwords are disabled")

        validation = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        validation.load_cert_chain(certfile, keyfile, password=no_password)
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            ssl_certfile=certfile,
            ssl_keyfile=keyfile,
            ssl_version=ssl.PROTOCOL_TLS_SERVER,
            proxy_headers=False,
            forwarded_allow_ips="",
            workers=1,
            loop="asyncio",
            ws="none",
            access_log=False,
            log_level="error",
            timeout_keep_alive=5,
            # CPython's native TLS close budget is 30s. Leave margin before the
            # independent host unit's 45s cgroup deadline, rather than racing TLS.
            timeout_graceful_shutdown=35,
            limit_concurrency=8,
        )
        config.load()
        if config.ssl is None or config.ssl.minimum_version < ssl.TLSVersion.TLSv1_2:
            raise ValueError("Native TLS 1.2 or newer is required")
        server = uvicorn.Server(config)
        # Uvicorn replays captured signals after draining. Keep those replays in
        # its graceful handler so our lease and handler cleanup can finish too.
        previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            for signum in previous:
                signal.signal(signum, server.handle_exit)
            server.run()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "journal",
        "origin",
        "operator-key-file",
        "read-token-file",
        "certfile",
        "keyfile",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args(argv)
    try:
        serve(**vars(args))
        return 0
    except Exception as exc:  # noqa: BLE001 -- never echo paths, credentials or request data
        print(json.dumps({"status": "ERROR", "error_class": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
