"""Read-only evidence and child snapshot diagnostics; never prepare or dispatch an order.

Run in the existing installed image, network disabled, evidence mounted read-only.
The 20-second diagnostic observation window does not change any trading deadline.
"""

import argparse
import hashlib
import json
import os
import selectors
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def probe(command, env, payload=b"", timeout=20):
    started = time.monotonic()
    result = {"first_stdout_seconds": None, "stdout_eof_seconds": None}
    with subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    ) as child:
        child.stdin.write(payload)
        child.stdin.close()
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            try:
                while selector.get_map() or child.poll() is None:
                    elapsed = time.monotonic() - started
                    if elapsed >= timeout:
                        raise TimeoutError("Diagnostic observation window exceeded")
                    for key, _ in selector.select(min(0.1, timeout - elapsed)):
                        chunk = os.read(key.fileobj.fileno(), 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            if key.data == "stdout":
                                result["stdout_eof_seconds"] = round(time.monotonic() - started, 3)
                            continue
                        if key.data == "stdout" and result["first_stdout_seconds"] is None:
                            result["first_stdout_seconds"] = round(time.monotonic() - started, 3)
                        buffers[key.data].extend(chunk)
                        if len(buffers[key.data]) > 1024 * 1024:
                            raise ValueError("Diagnostic response exceeded capacity")
                result["returncode"] = child.wait()
            except (TimeoutError, ValueError) as exc:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                result["error"] = str(exc)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["stderr_tail"] = bytes(buffers["stderr"][-4096:]).decode(errors="replace")
        result["stdout"] = bytes(buffers["stdout"]).decode(errors="replace")
        return result


def inspect(source):
    if not source.is_absolute() or not source.is_dir() or source.is_symlink():
        raise ValueError("Absolute retained evidence directory required")
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    names = [
        name + suffix for name in ("venue.db", "options.db") for suffix in ("", "-wal", "-shm")
    ]
    paths = [source / name for name in names if (source / name).exists()]
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size > 64 * 1024 * 1024 for p in paths):
        raise ValueError("Bounded regular retained files required")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    print(json.dumps({"source_sha256": hashes, "operation": "COPY_AND_SNAPSHOT_ONLY"}), flush=True)
    with tempfile.TemporaryDirectory(prefix="review-diagnostic-") as tmp:
        for p in paths:
            shutil.copy2(p, Path(tmp) / p.name)
        with sqlite3.connect(f"file:{tmp}/venue.db?mode=ro", uri=True) as db:
            meta_raw, state_raw = db.execute(
                "SELECT meta,state FROM option_fixture_control WHERE id=1"
            ).fetchone()
        meta, state = json.loads(meta_raw), json.loads(state_raw)
        if meta["limits"]["population_id"] != "ui-review-stock-20261009":
            raise ValueError("Expected isolated UI review population required")
        orders = state.get("stock_orders", [])
        print(
            json.dumps(
                {
                    "submit_count": state["submit_count"],
                    "orders": [
                        {
                            "client_id": o["client_id"],
                            "status": o["status"],
                            "fill_count": len(o["fills"]),
                        }
                        for o in orders
                    ],
                }
            ),
            flush=True,
        )
        imports = probe(
            [
                sys.executable,
                "-I",
                "-X",
                "importtime",
                "-c",
                "import app.options.worker; import app.options.engine",
            ],
            env,
        )
        print(json.dumps({"full_import_probe": imports}), flush=True)
        request = {
            "operation": "snapshot",
            "path": str(Path(tmp) / "venue.db"),
            "venue_id": meta["venue_id"],
            "account_id": meta["limits"]["account_id"],
            "population_id": meta["limits"]["population_id"],
            "now": max((o["updated_at"] for o in orders), default="2026-10-09T15:00:00+00:00"),
            "deadline_monotonic": time.monotonic() + 20,
            "parent_pid": os.getpid(),
            "stock_limits": meta.get("stock_limits"),
            "fault": "NONE",
        }
        result = probe(
            [sys.executable, "-I", "-m", "app.options.worker"], env, json.dumps(request).encode()
        )
        raw = result.pop("stdout")
        try:
            snap = json.loads(raw)["snapshot"]
            result["snapshot"] = {
                "population_id": snap["population_id"],
                "stock_orders": len(snap.get("stock_orders", [])),
            }
        except (ValueError, KeyError, TypeError):
            result["snapshot"] = "NO_VALID_RESPONSE"
        print(json.dumps({"read_only_child_probe": result}), flush=True)
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    print(json.dumps({"source_bytes_unchanged": True, "dispatches": 0, "fills": 0}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    inspect(parser.parse_args().source)
