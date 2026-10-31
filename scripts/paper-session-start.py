#!/usr/bin/env python3
"""Prepare a future PAPER session or launch a reviewed bounded session.

Uses the existing simulated account. Retains exact reviews and failures; never
resets an account, enables LIVE, or activates the public dashboard implicitly.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo


class StepFailed(RuntimeError):
    pass


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run_prepared(receipt, run_id, seconds, *, invoke, today):
    if receipt["target_session"] != today:
        raise ValueError("A prepared session can only run on its target date")
    invoke(["snapshot"])
    run = ["--run-id", run_id, "--seconds", str(seconds), "--resume-flat"]
    plan = invoke(["review-run", *run])
    if (not plan.get("degen_option_configuration_ready")
            or plan.get("live_enabled") is not False
            or plan.get("binding", {}).get("policy_sha256") != receipt["policy_sha256"]):
        raise ValueError("Session option configuration is still blocked or differs from preparation")
    return invoke(["run", *run, "--expected-review", plan["review_sha256"]])


def launch(captures, target, run_id, seconds, *, invoke, session_root, today,
           prepare_only=False, prepared_session=None, observed_swing_history=False,
           swing_capture_directory=None, scope_binding=None, earnings_probe=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", run_id):
        raise ValueError("A new simple run ID is required")
    if type(seconds) is not int or not 60 <= seconds <= 3600:
        raise ValueError("Simulation run must be bounded to 60..3600 seconds")
    if prepared_session:
        path = Path(prepared_session)
        if (not path.is_absolute() or path.resolve() != path or path.stat().st_mode & 0o077
                or path.stat().st_uid != os.geteuid()):
            raise ValueError("Private canonical prepared session directory required")
        source = path / "prepared.json"
        if (source.is_symlink() or source.stat().st_size > 16384 or source.stat().st_mode & 0o077
                or source.stat().st_uid != os.geteuid()):
            raise ValueError("Private bounded preparation receipt required")
        receipt = json.loads(source.read_text())
        if (not isinstance(receipt, dict) or receipt.get("version") != "paper-session-preparation-v1"
                or receipt.get("live_enabled") is not False):
            raise ValueError("Preparation receipt version mismatch")
        return run_prepared(receipt, run_id, seconds, invoke=invoke, today=today)
    if date.fromisoformat(target) < date.fromisoformat(today) or (not prepare_only and target != today):
        raise ValueError("Use --prepare-only for a future session; expired sessions cannot run")
    for value in (captures, swing_capture_directory, scope_binding, earnings_probe):
        if value is not None and not Path(value).is_absolute():
            raise ValueError("Absolute retained input paths required")
    if captures is None or (swing_capture_directory and not observed_swing_history):
        raise ValueError("Retained contracts and explicit observed Swing history selection required")
    destination = Path(session_root) / (target + "-" + run_id)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    policy = str(destination / "policy.json")
    common = ["--target-session", target, "--next-policy", policy]
    options = ["--observed-swing-history"] if observed_swing_history else []
    for flag, value in (("--swing-capture-directory", swing_capture_directory),
                        ("--scope-binding", scope_binding), ("--earnings-probe", earnings_probe)):
        if value:
            options += [flag, str(value)]
    invoke(["prepare-session", *common, "--capture-directory", str(captures), *options])
    review = invoke(["review-session", *common])
    if review.get("live_enabled") is not False:
        raise ValueError("Expected PAPER-only session review")
    enrolled = invoke(["enroll-session", *common, "--expected-review", review["review_sha256"]])
    if enrolled.get("status") != "SESSION_ROLLOVER_ENROLLED":
        raise ValueError("Session enrollment did not complete")
    receipt = {"version": "paper-session-preparation-v1", "target_session": target,
               "policy_sha256": review["binding"]["proposed_sha256"],
               "policy_path": policy, "session_review_sha256": review["review_sha256"],
               "live_enabled": False}
    # Save before snapshot publication, so a publication failure is recoverable
    # with --prepared-session without attempting a second rollover.
    save(destination / "prepared.json", receipt)
    if prepare_only:
        invoke(["snapshot"])
        return {"status": "SESSION_PREPARED", "prepared_session": str(destination),
                "target_session": target, "workers_started": False,
                "trading_ready": False, "live_enabled": False}
    return run_prepared(receipt, run_id, seconds, invoke=invoke, today=today)


def invoke_host(root, arguments, *, runner=subprocess.run):
    output = runner(
        ["python3", str(root / "scripts/connected-session-host.py"), *arguments],
        check=False, text=True, capture_output=True, cwd=root, timeout=240,
    )
    result = None
    # The host emits public structured errors on stderr; successes on stdout.
    # Preserve that bounded report, never print arbitrary subprocess stderr.
    for raw in (output.stdout, output.stderr):
        if len(raw) > 65536:
            continue
        try:
            candidate = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(candidate, dict) and candidate.get("status"):
            result = candidate
            break
        # Reviews have a phase rather than a status.
        if isinstance(candidate, dict) and (candidate.get("phase") or candidate.get("version")):
            result = candidate
            break
    if result is not None:
        print(json.dumps({"step": arguments[0], "report": result}, sort_keys=True), flush=True)
    if output.returncode or result is None:
        raise StepFailed("Step failed: " + arguments[0] + "; inspect its structured report above")
    return result


def unused_run_id(run_id, *, runner=subprocess.run):
    name = "trade-bot-connected-" + run_id
    found = runner(["docker", "container", "ls", "-a", "--filter", "name=^/" + name + "$",
                    "--format", "{{.Names}}"], check=True, capture_output=True, text=True, timeout=15)
    if found.stdout.strip():
        raise ValueError("Session name already exists; inspect its report or use a new run ID")


def wait_report(root, run_id, seconds, *, runner=subprocess.run):
    finished = runner(["docker", "wait", "trade-bot-connected-" + run_id],
                      check=True, capture_output=True, text=True, timeout=seconds + 120)
    # Always show saved decisions, including when the runtime exited nonzero.
    report = runner(["python3", str(root / "scripts/paper-session-report.py"), "--run-id", run_id],
                    check=False, capture_output=True, text=True, timeout=30)
    if len(report.stdout) > 262144:
        raise StepFailed("Saved session report exceeded its output bound")
    value = json.loads(report.stdout)
    print(json.dumps(value, sort_keys=True), flush=True)
    if report.returncode or finished.stdout.strip() != "0":
        raise StepFailed("Session stopped with an error; retained report shown above")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--capture-directory")
    source.add_argument("--capture-contracts", action="store_true", help="Capture fresh retained catalogs before preparation")
    source.add_argument("--prepared-session")
    p.add_argument("--target-session")
    p.add_argument("--run-id", default=None)
    p.add_argument("--seconds", type=int, default=600)
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--wait", action="store_true", help="Wait for the bounded run and print its saved decision report")
    p.add_argument("--observed-swing-history", action="store_true")
    p.add_argument("--swing-expiration", help="With --capture-contracts, capture the separate Swing expiry")
    for flag in ("swing-capture-directory", "scope-binding", "earnings-probe"):
        p.add_argument("--" + flag)
    args = p.parse_args(argv)
    if args.wait and args.prepare_only:
        p.error("--wait is only for a session run")
    if args.swing_expiration and (not args.capture_contracts or not args.observed_swing_history or args.swing_capture_directory):
        p.error("--swing-expiration requires --capture-contracts --observed-swing-history and no retained Swing directory")
    if not args.prepared_session and not args.target_session:
        p.error("--target-session is required with retained captures")
    if args.prepared_session and (args.prepare_only or args.target_session or args.observed_swing_history
                                 or args.swing_capture_directory or args.scope_binding or args.earnings_probe):
        p.error("Prepared sessions already bind their target and inputs")
    if os.geteuid() != 0:
        p.error("Run on the Trade-Bot host as root")
    os.umask(0o077)
    root = Path(__file__).resolve().parents[1]
    session_root = Path("/etc/trade-bot-connected/sessions")
    session_root.mkdir(mode=0o700, exist_ok=True)
    if session_root.is_symlink() or session_root.stat().st_mode & 0o077 or session_root.stat().st_uid != 0:
        p.error("Private, nonsymlink session directory required")
    run_id = args.run_id or ("paper-" + datetime.now(ZoneInfo("UTC")).strftime("%m%d-%H%M%S-") + uuid4().hex[:6])
    try:
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", run_id):
            raise ValueError("A new simple run ID is required")
        if not 60 <= args.seconds <= 3600:
            raise ValueError("Simulation run must be bounded to 60..3600 seconds")
        if not args.prepared_session and (date.fromisoformat(args.target_session) < date.fromisoformat(today)
                                          or (not args.prepare_only and args.target_session != today)):
            raise ValueError("Use --prepare-only for a future session; expired sessions cannot run")
        if not args.prepare_only:
            unused_run_id(run_id)
        if args.capture_contracts:
            target = date.fromisoformat(args.target_session)
            if args.swing_expiration and not 7 <= (date.fromisoformat(args.swing_expiration) - target).days <= 45:
                raise ValueError("Swing expiration must be 7..45 days after the target session")
            if (session_root / (args.target_session + "-" + run_id)).exists():
                raise ValueError("Preparation directory already exists; use --prepared-session or a new ID")
            catalog = invoke_host(root, ["capture-session", "--target-session", args.target_session])
            args.capture_directory = catalog["evidence_directory"]
            if args.swing_expiration:
                swing = invoke_host(root, ["capture-session", "--target-session", args.swing_expiration])
                args.swing_capture_directory = swing["evidence_directory"]
        result = launch(args.capture_directory, args.target_session, run_id, args.seconds,
                        invoke=lambda a: invoke_host(root, a), session_root=session_root,
                        today=today,
                        prepare_only=args.prepare_only, prepared_session=args.prepared_session,
                        observed_swing_history=args.observed_swing_history,
                        swing_capture_directory=args.swing_capture_directory,
                        scope_binding=args.scope_binding, earnings_probe=args.earnings_probe)
        print(json.dumps(result, sort_keys=True), flush=True)
        if args.wait:
            wait_report(root, run_id, args.seconds)
    except (OSError, ValueError, KeyError, StepFailed, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "NOT_STARTED_OR_INCOMPLETE",
                          "reason": str(exc) if isinstance(exc, (ValueError, StepFailed)) else type(exc).__name__,
                          "run_id": run_id, "live_enabled": False}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
