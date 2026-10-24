"""Private bounded file transport. Only the active native owner applies commands."""

import hashlib
import itertools
import json
import os
import re
import stat
from pathlib import Path

from app.execution.control_api import _secret
from app.options.operator import OptionsControl, body
from app.options.operator_models import SignedOptionsCommand

MAX_COMMAND_BYTES = 16384
MAX_PENDING = 64
NAME = re.compile(r"^[a-f0-9]{32}\.json$")


def private_directory(path):
    info = Path(path).lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Private current-owner command directory required")


def read(path, maximum=MAX_COMMAND_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("Bounded private command artifact required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > maximum or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("Command artifact changed during read")
    return raw


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value):
    """Publish complete durable JSON using a create-only hard link, never a partial request."""
    path = Path(path)
    private_directory(path.parent)
    temporary = path.parent / (".pending-" + os.urandom(16).hex())
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(value, sort_keys=True))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class CommandInbox:
    def __init__(self, engine, key_file):
        self.engine, self.key_file = engine, key_file
        self.inbox = engine.journal.path.parent / "operator-inbox"
        self.receipts = engine.journal.path.parent / "operator-receipts"

    def poll(self, *, now):
        try:
            private_directory(self.inbox)
            private_directory(self.receipts)
            control = OptionsControl(self.engine, bytes.fromhex(_secret(self.key_file)))
            with os.scandir(self.inbox) as entries:
                names = [e.name for e in itertools.islice(entries, MAX_PENDING + 1)]
            if len(names) > MAX_PENDING:
                return "OPTION_OPERATOR_INBOX_OVERFLOW"
            names = sorted(n for n in names if NAME.fullmatch(n))
            if not names:
                return None
            path = self.inbox / names[0]
            digest = None
            try:
                signed = SignedOptionsCommand.model_validate_json(read(path))
                if signed.command.command_id + ".json" != path.name:
                    raise ValueError("Request filename binding mismatch")
                digest = hashlib.sha256(body(signed.command).encode()).hexdigest()
                result = control.apply(signed.command, signed.signature, now=now)
            except (OSError, ValueError):
                result = {
                    "status": "REJECTED",
                    "reason": "INVALID_OPERATOR_REQUEST",
                    "live_enabled": False,
                    "network_calls": False,
                }
            receipt = {"command_fingerprint": digest, "result": result}
            destination = self.receipts / path.name
            try:
                save(destination, receipt)
            except FileExistsError:
                old = json.loads(read(destination))
                if not isinstance(old, dict) or not isinstance(old.get("result"), dict):
                    return "OPTION_OPERATOR_RECEIPT_CONFLICT"
                same = lambda r: {k: v for k, v in r.items() if k != "replayed"}
                if old.get("command_fingerprint") != digest or same(old.get("result", {})) != same(
                    result
                ):
                    return "OPTION_OPERATOR_RECEIPT_CONFLICT"
            path.unlink()
            sync_directory(self.inbox)
            return None
        except (OSError, ValueError):
            return "OPTION_OPERATOR_UNAVAILABLE"
