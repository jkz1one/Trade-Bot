#!/usr/bin/env python3
"""Prepare and launch one bounded local simulation from retained Robinhood captures.

Explicitly selects observed-quote simulation and standard ETF assumptions. Does
not reset accounts, buy data, enable LIVE, or activate the public dashboard.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo


def launch(captures, target, run_id, seconds, *, invoke, session_root, today):
    if target != today or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", run_id):
        raise ValueError("Today's session and a new simple run ID are required")
    if type(seconds) is not int or not 60 <= seconds <= 3600:
        raise ValueError("Initial simulation run must be bounded to 60..3600 seconds")
    if not Path(captures).is_absolute():
        raise ValueError("Absolute retained capture directory required")
    destination = Path(session_root) / (target + "-" + run_id)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    policy = str(destination / "policy.json")
    common = ["--target-session", target, "--next-policy", policy]
    invoke(["prepare-session", *common, "--capture-directory", str(captures)])
    review = invoke(["review-session", *common])
    invoke(["enroll-session", *common, "--expected-review", review["review_sha256"]])
    run = ["--run-id", run_id, "--seconds", str(seconds), "--resume-flat"]
    plan = invoke(["review-run", *run])
    if not plan.get("degen_option_configuration_ready"):
        raise ValueError("Session option configuration is still blocked; preserve the review")
    return invoke(["run", *run, "--expected-review", plan["review_sha256"]])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capture-directory", required=True)
    p.add_argument("--target-session", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--seconds", type=int, default=600)
    args = p.parse_args(argv)
    if os.geteuid() != 0:
        p.error("Run on the Trade-Bot host as root")
    os.umask(0o077)
    root = Path(__file__).resolve().parents[1]
    session_root = Path("/etc/trade-bot-connected/sessions")
    session_root.mkdir(mode=0o700, exist_ok=True)
    if session_root.is_symlink() or session_root.stat().st_mode & 0o077:
        p.error("Private, nonsymlink session directory required")

    def invoke(arguments):
        output = subprocess.run(
            ["python3", str(root / "scripts/connected-session-host.py"), *arguments],
            check=True, text=True, capture_output=True, cwd=root, timeout=120,
        )
        result = json.loads(output.stdout)
        print(json.dumps(result, sort_keys=True), flush=True)
        return result

    try:
        launch(args.capture_directory, args.target_session, args.run_id, args.seconds,
               invoke=invoke, session_root=session_root,
               today=datetime.now(ZoneInfo("America/New_York")).date().isoformat())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr, end="")
        else:
            print(json.dumps({"status": "NOT_STARTED_OR_INCOMPLETE", "reason": str(exc), "live_enabled": False}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
