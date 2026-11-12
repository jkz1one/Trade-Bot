#!/usr/bin/env python3
"""Credential-free PAPER soak in a new directory, never an existing account."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOMINAL_SECONDS = 21480


def validate(output, seconds, seed_mib):
    if not sys.flags.isolated:
        raise ValueError("ISOLATED_PYTHON_REQUIRED")
    if type(seconds) is not int or not 60 <= seconds <= 23400:
        raise ValueError("DURATION_MUST_BE_60_TO_23400_SECONDS")
    if type(seed_mib) is not int or not 0 <= seed_mib <= 256:
        raise ValueError("SEED_MUST_BE_0_TO_256_MIB")
    if not output.is_absolute() or output.resolve() != output or output.is_relative_to(ROOT):
        raise ValueError("NEW_ABSOLUTE_OUTPUT_OUTSIDE_CHECKOUT_REQUIRED")
    if output.exists() or output.is_symlink():
        raise ValueError("EXISTING_OUTPUT_OR_ACCOUNT_REFUSED")
    interfaces = [
        line.split(":")[0].strip() for line in Path("/proc/net/dev").read_text().splitlines()[2:]
    ]
    if any(name != "lo" for name in interfaces):
        raise ValueError("NETWORK_NAMESPACE_WITH_LOOPBACK_ONLY_REQUIRED")
    import app

    installed = Path(app.__file__).resolve().parent
    if installed.is_relative_to(ROOT):
        raise ValueError("NONEDITABLE_INSTALLED_PACKAGE_REQUIRED")
    manifest = {}
    for path in sorted((ROOT / "app").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT / "app")
        if path.read_bytes() != (installed / relative).read_bytes():
            raise ValueError("SOURCE_INSTALL_MISMATCH")
        manifest[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    pins = [
        line.split("==")
        for line in (ROOT / "requirements-runtime.lock").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    if not all(importlib.metadata.version(name) == version for name, version in pins):
        raise ValueError("RUNTIME_PIN_MISMATCH")
    return {
        "application_files": len(manifest),
        "runtime_pins": len(pins),
        "application_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
    }


def run(output, seconds, seed_mib):
    identity = validate(output, seconds, seed_mib)
    output.mkdir(mode=0o700)
    result = {
        "version": "paper-soak-launch-v1",
        "status": "RUNNING",
        **identity,
        "seconds": seconds,
        "seed_mib": seed_mib,
        "network": "ISOLATED",
        "host_acceptance": "UNVERIFIED",
        "wall_clock_soak": "PENDING",
        "synthetic": True,
        "provider_calls": False,
        "model_service_calls": False,
        "live_enabled": False,
    }
    summary = output / "summary.json"
    summary.write_text(json.dumps(result, indent=2) + "\n")
    for name in ("tests", "scripts", "examples"):
        shutil.copytree(
            ROOT / name,
            output / "stage" / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    health = output / "stage/app/mixed"
    health.mkdir(parents=True)
    shutil.copy(ROOT / "app/mixed/paper_health.py", health / "paper_health.py")
    bootstrap = (
        "import os,sys;os.sched_setaffinity(0,{min(os.sched_getaffinity(0))});"
        "sys.path[:0]=" + repr([str(output / "stage"), str(output / "stage/tests")]) + ";"
        "from pathlib import Path;from soak_worker import run;run(Path("
        + repr(str(output))
        + "),"
        + str(seconds)
        + ","
        + str(seed_mib)
        + ")"
    )
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    env.update(
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        TRADER_LIVE_ENABLED="false",
    )
    child = None

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, interrupted)
    try:
        with (output / "worker.log").open("w") as log:
            child = subprocess.Popen(
                [sys.executable, "-I", "-W", "error", "-c", bootstrap],
                cwd=output,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            result["worker_pid"] = child.pid
            result["worker_start_ticks"] = (
                Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
            )
            summary.write_text(json.dumps(result, indent=2) + "\n")
            code = child.wait(timeout=seconds + 180)
        result["child_exit_code"] = code
        progress = (
            json.loads((output / "progress.json").read_text())
            if (output / "progress.json").exists()
            else {}
        )
        result["status"] = (
            "PASSED" if code == 0 and progress.get("status") == "PASSED" else "FAILED"
        )
        result["wall_clock_soak"] = progress.get("wall_clock_full_duration", "NOT_COMPLETED")
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        result.update(status="FAILED", reason="SOAK_RUNNER_INTERRUPTED_OR_TIMED_OUT")
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
        signal.signal(signal.SIGTERM, previous_sigterm)
        summary.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=NOMINAL_SECONDS)
    parser.add_argument("--seed-mib", type=int, default=68)
    args = parser.parse_args()
    try:
        value = run(args.output, args.seconds, args.seed_mib)
    except (OSError, ValueError) as exc:
        value = {"status": "UNAVAILABLE", "reason": str(exc), "live_enabled": False}
    print(json.dumps(value, sort_keys=True))
    raise SystemExit(0 if value["status"] == "PASSED" else 1)
