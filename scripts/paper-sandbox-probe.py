"""Disposable systemd sandbox probe. Opens only harness-created dummy files."""

import json
import os
import sys
import time
from pathlib import Path


def access(path, write=False):
    flags = os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_WRONLY | os.O_APPEND if write else os.O_RDONLY)
    try:
        fd = os.open(path, flags)
        try:
            if write:
                os.write(fd, b"fixture-write\n")
            else:
                os.read(fd, 1)
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


def observe(credentials, outside):
    return {
        peer: {
            "read": access(credentials / peer / "dummy"),
            "write": access(credentials / peer / "dummy", write=True),
        }
        for peer in ("model", "market", "operator", "alerts", "late")
    } | {"outside": {"read": access(outside), "write": access(outside, write=True)}}


def publish(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("x") as stream:
        json.dump(value, stream)
    temporary.replace(path)


def main():
    state, credentials, outside = map(Path, sys.argv[1:])
    publish(
        state / "before.json",
        {"uid": os.geteuid(), "gid": os.getegid(), "access": observe(credentials, outside)},
    )
    deadline = time.monotonic() + 25
    while not (state / "continue").exists():
        if time.monotonic() >= deadline:
            return 1
        time.sleep(0.05)
    publish(state / "after.json", {"access": observe(credentials, outside)})
    # Remain alive for namespace/process identity observation and explicit cleanup.
    while time.monotonic() < deadline:
        time.sleep(0.05)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
