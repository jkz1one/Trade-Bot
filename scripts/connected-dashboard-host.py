#!/usr/bin/env python3
"""Reviewed dashboard-only switch. No runtime/collector start, configuration or credentials changes."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

ACTIVE = "trade-bot-dashboard"
BACKUP = "trade-bot-dashboard-before-connected-v1"
FAILED = "trade-bot-dashboard-connected-failed-v1"
RETIRED = "trade-bot-dashboard-connected-retired-v1"
OLD_IMAGE = "trade-bot-dashboard:a653cc7e79d178c5ab2de6afb3311829282a7544"
SNAPSHOT = Path("/var/lib/trade-bot-dashboard-publish/connected-v1")
SNAPSHOT_NAME = "connected-v1"
SECRET = "/etc/trade-bot/dashboard_password"
FROZEN = "/var/lib/trade-bot-dashboard/ui-review-v3"
LABEL = "trade-bot.connected-dashboard-v1"
WORKERS = ("trade-bot-shadow-shadow-1", "trade-bot-shadow-observer-1")
LOCK = Path("/run/lock/trade-bot-dashboard-switch.lock")
PORTS = {"8790/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8790"}]}

# Runs inside the existing container. Password bytes never leave that process.
PROBE = r"""
import base64,json,sys,urllib.error,urllib.request
from pathlib import Path
try:
 secret=Path('/run/secrets/dashboard_password').read_bytes().removesuffix(b'\n')
 headers={'Authorization':'Basic '+base64.b64encode(b'trader:'+secret).decode()}
 try:
  urllib.request.urlopen('http://127.0.0.1:8790/',timeout=3)
  raise ValueError('anonymous access')
 except urllib.error.HTTPError as error:
  assert error.code==401
 request=urllib.request.Request('http://127.0.0.1:8790/api/mixed',headers=headers)
 with urllib.request.urlopen(request,timeout=3) as response: data=json.load(response)
 assert data['status']=='OK' and data['accounting']=='VERIFIED'
 assert not data['live_enabled'] and not data['execution_authority'] and not data.get('admin_enabled')
 if sys.argv[1]=='frozen':
  assert data['review']['mode']=='FROZEN_OFFLINE_UI_FIXTURE'
  assert data['review']['as_of']=='2026-10-09T14:00:02+00:00'
  assert data['fill_count']==2 and len(data['positions'])==2
 else:
  assert 'review' not in data
 request=urllib.request.Request('http://127.0.0.1:8790/',headers=headers)
 with urllib.request.urlopen(request,timeout=3) as response:
  html=response.read(2*1024*1024)
  assert bool(b'Paused historical simulation' in html)==(sys.argv[1]=='frozen')
 print(json.dumps({'authenticated':True,'mode':sys.argv[1],'execution_authority':False}))
except Exception:
 print('Dashboard authentication/state probe failed',file=sys.stderr)
 sys.exit(1)
"""


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def command(args, *, timeout=25, allow_failure=False):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode and not allow_failure:
        raise RuntimeError("Host command failed: " + " ".join(args[:2]))
    return result


def docker(*args, **kwargs):
    return command(["docker", *args], **kwargs)


def container(name, *, missing=False):
    result = docker("container", "inspect", name, allow_failure=missing)
    if result.returncode:
        return None
    items = json.loads(result.stdout)
    if len(items) != 1 or items[0]["Name"] != "/" + name:
        raise ValueError("Unexpected container identity")
    return items[0]


def identity(item):
    return {k: item[k] for k in ("Id", "Image", "Config", "HostConfig", "Mounts")} | {
        "started_at": item["State"]["StartedAt"],
        "running": item["State"]["Running"],
        "paused": item["State"]["Paused"],
        "restarts": item["RestartCount"],
    }


def workers():
    return {name: digest(identity(container(name))) for name in WORKERS}


def check_reader(item, *, frozen):
    config, host = item["Config"], item["HostConfig"]
    mounts = {m["Destination"]: (m["Source"], m["RW"]) for m in item["Mounts"]}
    if (
        config["User"] != "10001:10001"
        or not host["ReadonlyRootfs"]
        or host["PortBindings"] != PORTS
        or host.get("Privileged")
        or host.get("CapAdd")
        or host.get("CapDrop") != ["ALL"]
        or mounts
        != {
            "/data": (FROZEN if frozen else str(SNAPSHOT), False),
            "/run/secrets/dashboard_password": (SECRET, False),
        }
        or "TRADER_LIVE_ENABLED=false" not in config["Env"]
        or item["State"]["Paused"]
    ):
        raise ValueError("Unexpected dashboard isolation, mounts or listener")
    if frozen:
        if config["Image"] != OLD_IMAGE or 'review_at=m["as_of"]' not in " ".join(config["Cmd"]):
            raise ValueError("Expected the existing frozen a653cc7 dashboard")
    elif not (config.get("Labels") or {}).get(LABEL) or config["Cmd"][:7] != [
        "python",
        "-I",
        "-W",
        "error",
        "-m",
        "app.mixed.dashboard_reader",
        "serve",
    ]:
        raise ValueError("Expected the retained connected dashboard identity")


def absent(*names):
    if any(container(name, missing=True) is not None for name in names):
        raise ValueError("Reserved dashboard container already exists; preserve and inspect it")


def binding():
    for path, mode in ((SNAPSHOT.parent, 0o700), (SNAPSHOT, 0o711)):
        info = path.lstat()
        if (
            path.resolve() != path
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != mode
        ):
            raise ValueError("Private canonical publisher directory required")
    fd = os.open(SNAPSHOT / "binding.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 4096
        ):
            raise ValueError("Private publisher binding required")
        value = json.loads(os.read(fd, 4097))
    finally:
        os.close(fd)
    if (value["publisher_uid"], value["reader_uid"], value["reader_gid"]) != (0, 10001, 10001):
        raise ValueError("Existing publisher/reader identities required")
    if (
        value["source_journal"] != "/source/options.db"
        or value["destination"] != "/exports/" + SNAPSHOT_NAME
    ):
        raise ValueError("Expected the host-helper publisher binding")
    return value


def reader_args(value, operation):
    return [
        "python",
        "-I",
        "-W",
        "error",
        "-m",
        "app.mixed.dashboard_reader",
        operation,
        "--directory",
        "/data",
        "--binding-json",
        json.dumps(value, sort_keys=True),
        "--password-file",
        "/run/secrets/dashboard_password",
    ]


def isolation():
    return [
        "--read-only",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "256m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "32",
        "--tmpfs",
        "/tmp:size=32m,mode=1777",
        "--mount",
        f"type=bind,src={SNAPSHOT},dst=/data,readonly",
        "--mount",
        f"type=bind,src={SECRET},dst=/run/secrets/dashboard_password,readonly",
        "-e",
        "TRADER_LIVE_ENABLED=false",
    ]


def preflight(image_id, value):
    result = docker(
        "run", "--rm", "--network", "none", *isolation(), image_id, *reader_args(value, "inspect")
    )
    report = json.loads(result.stdout)
    if report["status"] != "SNAPSHOT_READER_READY" or report["binding_sha256"] != digest(value):
        # Native fingerprint uses the same canonical JSON settings, verified in tests.
        raise ValueError("Reader preflight did not verify the expected snapshot")
    return report


def review(release, *, rollback=False):
    active = container(ACTIVE)
    check_reader(active, frozen=not rollback)
    if not rollback and not active["State"]["Running"]:
        raise ValueError("Expected the current dashboard to be running")
    worker_state = workers()
    plan = {
        "version": "connected-dashboard-switch-v1",
        "operation": "rollback" if rollback else "activate",
        "release": release,
        "active_id": active["Id"],
        "active_identity_sha256": digest(identity(active)),
        "workers": worker_state,
        "live_enabled": False,
        "runtime_changed": False,
    }
    if rollback:
        backup = container(BACKUP)
        check_reader(backup, frozen=True)
        if (
            backup["State"]["Running"]
            or (active["Config"].get("Labels") or {}).get(LABEL) != backup["Id"]
        ):
            raise ValueError("Retained rollback identity mismatch")
        absent(RETIRED)
        plan.update(backup_id=backup["Id"], backup_identity_sha256=digest(identity(backup)))
    else:
        absent(BACKUP, FAILED, RETIRED)
        docker("exec", ACTIVE, "python", "-I", "-c", PROBE, "frozen", timeout=15)
        value = binding()
        image = json.loads(docker("image", "inspect", "trade-bot-dashboard:" + release).stdout)[0]
        if "TRADER_RELEASE_SHA=" + release not in image["Config"]["Env"]:
            raise ValueError("Image release identity mismatch")
        report = preflight(image["Id"], value)
        plan.update(
            image_id=image["Id"], binding=value, application_sha256=report["application_sha256"]
        )
    if workers() != worker_state:
        raise ValueError("Existing worker identities changed during review")
    return plan | {"review_sha256": digest(plan)}


def wait_ready(mode):
    deadline = time.monotonic() + 90
    restarts = None
    for _ in range(45):
        current = container(ACTIVE)
        if restarts is None:
            restarts = 0 if mode == "connected" else current["RestartCount"]
        if (
            not current["State"]["Running"]
            or current["State"]["OOMKilled"]
            or current["RestartCount"] != restarts
        ):
            raise RuntimeError("Dashboard stopped, restarted or exhausted memory")
        if (
            docker(
                "exec", ACTIVE, "python", "-I", "-c", PROBE, mode, allow_failure=True, timeout=15
            ).returncode
            == 0
        ):
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(2)
    raise RuntimeError("Dashboard readiness deadline exceeded")


def restore(old_id, *, retain):
    # Never remove a failed container or rename an unrelated process.
    old = container(BACKUP)
    if old["Id"] != old_id:
        raise RuntimeError("Rollback identity changed; manual inspection required")
    check_reader(old, frozen=True)
    current = container(ACTIVE, missing=True)
    if current is not None:
        if (current["Config"].get("Labels") or {}).get(LABEL) != old_id:
            raise RuntimeError("Unexpected active container; manual inspection required")
        absent(retain)
        docker("stop", "--time", "10", ACTIVE)
        docker("rename", ACTIVE, retain)
    docker("rename", BACKUP, ACTIVE)
    docker("start", ACTIVE)
    wait_ready("frozen")


def apply(plan):
    old_id = plan["active_id"]
    if plan["operation"] == "rollback":
        restore(plan["backup_id"], retain=RETIRED)
    else:
        try:
            docker("rename", ACTIVE, BACKUP)
            docker("stop", "--time", "10", BACKUP)
            docker(
                "run",
                "-d",
                "--name",
                ACTIVE,
                "--restart",
                "unless-stopped",
                "--init",
                "--label",
                LABEL + "=" + old_id,
                "--log-opt",
                "max-size=10m",
                "--log-opt",
                "max-file=3",
                "-p",
                "127.0.0.1:8790:8790",
                *isolation(),
                plan["image_id"],
                *reader_args(plan["binding"], "serve"),
            )
            wait_ready("connected")
            current = container(ACTIVE)
            check_reader(current, frozen=False)
            if current["Image"] != plan["image_id"] or current["Config"]["Cmd"] != reader_args(
                plan["binding"], "serve"
            ):
                raise RuntimeError("Started dashboard image or binding changed")
            if workers() != plan["workers"]:
                raise RuntimeError("Existing worker identities changed")
        except (Exception, KeyboardInterrupt):
            # A Docker error can arrive after rename succeeded: inspect identities.
            retained = container(BACKUP, missing=True)
            if retained is not None and retained["Id"] == old_id:
                restore(old_id, retain=FAILED)
                print(
                    "Previous frozen dashboard restored; failed container retained if created.",
                    file=sys.stderr,
                )
            raise
    if workers() != plan["workers"]:
        raise RuntimeError("Existing worker identities changed; inspect host")


def main(argv=None):
    global SNAPSHOT, SNAPSHOT_NAME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("review", "activate", "switch", "review-rollback", "rollback"))
    parser.add_argument("--review-sha256")
    parser.add_argument("--snapshot-name", choices=("connected-v1", "connected-price-options-v1"),
                        default="connected-v1")
    args = parser.parse_args(argv)
    SNAPSHOT_NAME = args.snapshot_name
    SNAPSHOT = SNAPSHOT.parent / SNAPSHOT_NAME
    if (args.operation in ("activate", "rollback")) != (args.review_sha256 is not None):
        parser.error("Only activate/rollback require the exact reviewed --review-sha256")
    lock_fd = None
    try:
        if os.geteuid() != 0:
            raise ValueError("Run on the Trade-Bot server as root")
        lock_fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        lock_info = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(lock_info.st_mode)
            or lock_info.st_uid != 0
            or stat.S_IMODE(lock_info.st_mode) != 0o600
        ):
            raise ValueError("Private dashboard operation lease required")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.chdir(Path(__file__).resolve().parents[1])
        if command(["git", "status", "--porcelain"]).stdout:
            raise ValueError("Clean release checkout required")
        release = command(["git", "rev-parse", "HEAD"]).stdout.strip()
        if not re.fullmatch("[a-f0-9]{40}", release):
            raise ValueError("Pinned release required")
        plan = review(release, rollback=args.operation in ("rollback", "review-rollback"))
        if args.operation == "switch":
            # Explicit one-command switch, retaining the same complete review
            # and second identity check as the manual review/activate workflow.
            print(json.dumps(plan, sort_keys=True), flush=True)
            args.review_sha256 = plan["review_sha256"]
        if args.review_sha256 is None:
            print(json.dumps(plan, sort_keys=True))
            return 0
        if plan["review_sha256"] != args.review_sha256:
            raise ValueError("Review changed; repeat read-only review before switching")
        # Close the review/apply gap by repeating all identities and freshness checks.
        if review(release, rollback=plan["operation"] == "rollback") != plan:
            raise ValueError("Review changed before switch")

        def interrupted(*_args):
            raise InterruptedError("Dashboard switch interrupted")

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, interrupted)
        apply(plan)
        print(
            json.dumps(
                {
                    "status": "DASHBOARD_SWITCHED",
                    "mode": plan["operation"],
                    "runtime_changed": False,
                    "live_enabled": False,
                }
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
        print(
            "Dashboard operation failed. Preserve containers and inspect current state; no worker was started.",
            file=sys.stderr,
        )
        return 2
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
