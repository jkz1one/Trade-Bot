"""Explicit independent native-TLS checkpoint archive. Never trading or restore authority."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import ssl
import stat
from pathlib import Path
from urllib.parse import urlsplit

from app.execution.checkpoint_archive import ArchiveServer, ArchiveStore, initialize


def _tls_file(path, *, private):
    path = Path(path).absolute()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or not 0 < info.st_size <= 1024 * 1024
            or (private and stat.S_IMODE(info.st_mode) != 0o600)
        ):
            raise ValueError("Bounded owned TLS files and a private key required")
    finally:
        os.close(fd)
    return str(path)


def serve(*, directory, origin, token_file, certfile, keyfile, host, port, timeout_seconds):
    parsed = urlsplit(origin)
    if (
        not origin.isascii()
        or any(c.isspace() for c in origin)
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port == 0
        or "*" in parsed.netloc
        or "\\" in parsed.netloc
        or parsed.netloc.endswith(":")
    ):
        raise ValueError("An explicit native HTTPS origin is required")
    ipaddress.ip_address(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("An explicit bounded listener port is required")
    if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 30:
        raise ValueError("A bounded archive connection deadline is required")
    certfile, keyfile = _tls_file(certfile, private=False), _tls_file(keyfile, private=True)

    def no_password():
        raise ValueError("Interactive TLS key passwords are disabled")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile, keyfile, password=no_password)
    with (
        ArchiveStore(directory) as store,
        ArchiveServer(
            (host, port),
            store=store,
            context=context,
            token_file=Path(token_file).absolute(),
            authority=parsed.netloc.lower(),
            timeout_seconds=timeout_seconds,
        ) as server,
    ):
        stopped = False

        def stop(signum, frame):
            nonlocal stopped
            stopped = True

        previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            for signum in previous:
                signal.signal(signum, stop)
            while not stopped:
                server.handle_request()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--directory", required=True)
    init.add_argument("--max-objects", type=int, required=True)
    report = commands.add_parser("report")
    report.add_argument("--directory", required=True)
    listen = commands.add_parser("serve")
    for name in ("directory", "origin", "token-file", "certfile", "keyfile"):
        listen.add_argument("--" + name, required=True)
    listen.add_argument("--host", default="127.0.0.1")
    listen.add_argument("--port", type=int, default=8790)
    listen.add_argument("--timeout-seconds", type=float, default=30)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "init":
            result = initialize(**args)
        elif command == "report":
            with ArchiveStore(args["directory"]) as store:
                result = store.report()
        else:
            serve(**args)
            return 0
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:  # noqa: BLE001 -- do not echo archive paths, bytes or credentials
        print(
            json.dumps(
                {"status": "ERROR", "error_class": type(exc).__name__, "execution_authority": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
