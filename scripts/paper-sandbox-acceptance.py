"""Opt-in disposable systemd credential sandbox integration, not host acceptance.

Requires root, systemd PID 1 and an already provisioned non-root tradebot-paper
user/group. Never installs production units, initializes a population or reads
real credentials. Fixed reviewed sandbox directives run a dummy probe instead.
"""

import argparse
import grp
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
DIGESTS = {
    "runtime": "afd4847f83c15ea61fd189235083b5028dbb698f23318b09631a8177956a3f4f",
    "control": "ae786560e08674c27dce9724f5c16cdfd980f9b2fa5338146d76edc49557eb74",
    "alerts": "8d14e0c5448c817b49eaf0c360e3afcc69aca7812ff765e9f374f720d190c454",
    "checkpoint": "bb955a17696a7d73713f1db0ca421558b5e0fc9cfd35fd83ac6869768970658a",
}
ALLOWED = {
    "runtime": {"model": False, "market": True},
    "control": {"operator": False},
    "alerts": {"alerts": False},
    "checkpoint": {},
}
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}


class CleanupBlocked(Exception):
    def __init__(self, unit):
        self.unit = unit


class CaseBlocked(RuntimeError):
    def __init__(self, unit, reason):
        self.unit = unit
        super().__init__(reason)


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def command(argv, *, capture=False):
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=ENV,
        timeout=10,
        check=False,
    )
    require(result.returncode == 0, "MANAGER_COMMAND_FAILED")
    if capture:
        require(len(result.stdout) <= 4096, "MANAGER_OUTPUT_TOO_LARGE")
        return result.stdout.decode().strip()


def properties(role, state, credentials):
    raw = (ROOT / "deploy/paper" / f"trade-bot-paper-{role}.service").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == DIGESTS[role], "REVIEWED_UNIT_CHANGED")
    section = None
    result = []
    for line in raw.decode().splitlines():
        if line.startswith("["):
            section = line
        elif section == "[Service]" and "=" in line:
            key = line.split("=", 1)[0]
            # Only lifecycle/command substitutions; all sandbox directives remain.
            if key not in {"Type", "ExecStart", "Restart", "TimeoutStopSec"}:
                result.append(
                    line.replace("/var/lib/trade-bot-paper", str(state)).replace(
                        "/etc/trade-bot-paper", str(credentials)
                    )
                )
    return result + ["Restart=no", "TimeoutStopSec=5", "RuntimeMaxSec=30"]


def dummy(path, uid, gid):
    path.mkdir(mode=0o700)
    os.chown(path, uid, gid)
    file = path / "dummy"
    with file.open("x") as stream:
        stream.write("harmless-acceptance-fixture\n")
    file.chmod(0o600)
    os.chown(file, uid, gid)


def wait_file(path, unit):
    deadline = time.monotonic() + 10
    while not path.exists():
        require(time.monotonic() < deadline, "PROBE_DEADLINE")
        state = command(
            ["/usr/bin/systemctl", "show", "--all", "--value", "--property=ActiveState", unit],
            capture=True,
        )
        require(state in {"active", "activating"}, "PROBE_NOT_RUNNING")
        time.sleep(0.05)
    require(path.stat().st_size <= 4096, "PROBE_OUTPUT_TOO_LARGE")
    return json.loads(path.read_text())


def validate(value, role, present, uid, gid, *, before):
    if before:
        require(value.get("uid") == uid and value.get("gid") == gid, "PROBE_IDENTITY_MISMATCH")
    expected = {
        peer: {
            "read": peer in ALLOWED[role] and peer in present,
            "write": ALLOWED[role].get(peer, False) and peer in present,
        }
        for peer in ("model", "market", "operator", "alerts", "late")
    } | {"outside": {"read": True, "write": False}}
    require(value.get("access") == expected, "SANDBOX_ACCESS_MISMATCH")


def stop(unit):
    command(["/usr/bin/systemctl", "stop", unit])
    state = command(
        ["/usr/bin/systemctl", "show", "--all", "--value", "--property=ActiveState", unit],
        capture=True,
    )
    require(state in {"inactive", "failed"}, "PROBE_CLEANUP_BLOCKED")
    # Only this unique transient name; failure evidence is already in the report.
    subprocess.run(
        ["/usr/bin/systemctl", "reset-failed", unit],
        env=ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


def run_case(role, missing, uid, gid):
    identity = uuid4().hex
    unit = f"trade-bot-paper-acceptance-{identity}.service"
    state = Path("/var/lib") / f"trade-bot-paper-acceptance-{identity}"
    credentials = Path("/etc") / f"trade-bot-paper-acceptance-{identity}"
    admitted = False
    safe_to_remove = True
    created = []
    try:
        for path in (state, credentials):
            path.mkdir(mode=0o755)
            path.chmod(0o755)
            created.append(path)
        population = state / "population"
        population.mkdir(mode=0o700)
        os.chown(population, uid, gid)
        checkpoints = state / "checkpoints"
        checkpoints.mkdir(mode=0o700)
        os.chown(checkpoints, uid, gid)
        outside = state / "outside"
        with outside.open("x") as stream:
            stream.write("harmless-protected-system-fixture\n")
        outside.chmod(0o600)
        os.chown(outside, uid, gid)
        probe = state / "probe.py"
        probe.write_bytes((ROOT / "scripts/paper-sandbox-probe.py").read_bytes())
        probe.chmod(0o644)
        present = {"model", "market", "operator", "alerts"}
        if missing:
            present = (
                {"operator"} if role == "control" else {"alerts"} if role == "alerts" else set()
            )
        for peer in sorted(present):
            dummy(credentials / peer, uid, gid)
        props = properties(role, state, credentials)
        argv = [
            "/usr/bin/systemd-run",
            "--quiet",
            "--no-block",
            "--unit=" + unit,
            "--service-type=exec",
        ] + ["--property=" + prop for prop in props]
        # Record ownership before submission: timeout/lost response can still create a unit.
        admitted = True
        safe_to_remove = False
        command(
            argv
            + [
                "/usr/bin/python3",
                "-I",
                "-B",
                str(probe),
                str(population),
                str(credentials),
                str(outside),
            ]
        )
        before = wait_file(population / "before.json", unit)
        validate(before, role, present, uid, gid, before=True)
        pid = command(
            ["/usr/bin/systemctl", "show", "--all", "--value", "--property=MainPID", unit],
            capture=True,
        )
        require(pid.isdecimal() and int(pid) > 1, "PROBE_PID_MISMATCH")
        require(
            os.readlink(f"/proc/{pid}/ns/mnt") != os.readlink("/proc/1/ns/mnt"),
            "PROBE_NAMESPACE_MISMATCH",
        )
        for peer in sorted({"model", "market", "operator", "alerts", "late"} - present):
            dummy(credentials / peer, uid, gid)
        (population / "continue").touch(mode=0o600)
        after = wait_file(population / "after.json", unit)
        # Absent optional binds stay absent until explicit restart. Never expect new access.
        validate(after, role, present, uid, gid, before=False)
        return {
            "role": role,
            "transient_unit": unit,
            "initial_peers": "missing" if missing else "present",
            "status": "OBSERVED",
            "reviewed_unit_sha256": DIGESTS[role],
            "before": before,
            "after": after,
            "separate_mount_namespace": True,
        }
    except Exception as exc:
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise CaseBlocked(unit, reason) from exc
    finally:
        if admitted:
            try:
                stop(unit)
            except Exception as exc:
                raise CleanupBlocked(unit) from exc
            safe_to_remove = True
        if safe_to_remove:
            for path in reversed(created):
                shutil.rmtree(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="explicitly run disposable systemd probes"
    )
    args = parser.parse_args(argv)
    report = {
        "schema": "paper-sandbox-integration-v1",
        "status": "BLOCKED",
        "cases": [],
        "host_acceptance": "UNVERIFIED",
        "execution_authority": False,
        "live_enabled": False,
    }
    try:
        require(args.run, "EXPLICIT_RUN_REQUIRED")
        require(os.geteuid() == 0, "ROOT_METADATA_AND_TRANSIENT_SERVICE_ACCESS_REQUIRED")
        require(
            Path("/proc/1/comm").read_text().strip() == "systemd", "SYSTEMD_MANAGER_UNAVAILABLE"
        )
        user, group = pwd.getpwnam("tradebot-paper"), grp.getgrnam("tradebot-paper")
        require(
            user.pw_uid > 0 and group.gr_gid > 0 and user.pw_gid == group.gr_gid,
            "DEDICATED_SERVICE_IDENTITY_REQUIRED",
        )
        # Check every template before admitting any manager mutation.
        for role in DIGESTS:
            properties(role, Path("/var/lib/unused"), Path("/etc/unused"))
        for role in DIGESTS:
            for missing in (False, True):
                report["current_case"] = {
                    "role": role,
                    "initial_peers": "missing" if missing else "present",
                }
                report["cases"].append(run_case(role, missing, user.pw_uid, group.gr_gid))
        del report["current_case"]
        report["status"] = "OBSERVED"
    except CleanupBlocked as exc:
        report["reason"] = "PROBE_CLEANUP_BLOCKED"
        report["retained_transient_unit"] = exc.unit
    except CaseBlocked as exc:
        report["reason"] = str(exc)
        report["transient_unit"] = exc.unit
    except RuntimeError as exc:
        report["reason"] = str(exc)
    except Exception as exc:  # noqa: BLE001 -- never echo manager output or fixture paths
        report["reason"] = type(exc).__name__
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
