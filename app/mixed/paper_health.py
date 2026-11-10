"""Read-only, bounded daily controller evidence for the connected PAPER dashboard."""

import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "paper-desk-health-v1"
FRESH_SECONDS = 180
STATES = {
    "FAILED": "Failed", "STOPPED": "Stopped", "PAUSED": "Paused", "STOPPING": "Stopping",
    "WAITING_NEXT_SESSION": "Scheduled", "READY": "Prepared", "PREPARING": "Preparing",
    "RUNNING": "Running", "STARTING": "Starting", "WAITING_FOR_SETUP": "Waiting for a setup",
    "MISSING_INPUTS": "Missing inputs", "WAITING_FIRST_TICK": "Awaiting controller",
}
CODES = {
    "SESSION_STOPPED_REVIEW_REQUIRED": "The worker stopped early. Operator review required.",
    "CONTAINER_EXIT_NONZERO": "The worker exited with an error.",
    "MANUAL_PAUSE": "Paused by operator.", "BOUNDED_SESSION_ENDED": "Scheduled run ended.",
    "EXPLICIT_SCHEDULE_RESUME": "Daily schedule resumed.", "DAILY_SESSION_ALREADY_FINISHED": "Today's run has ended.",
    "OPTION_RUNTIME_FEED_UNAVAILABLE": "Waiting for valid market data.",
    "WAITING_FOR_SIX_COMPLETED_BARS": "Waiting for six completed five-minute bars.",
}


INPUTS = {
    "INVENTORY_BINDING_COVERAGE_OR_FRESHNESS": "Contract inventory failed its binding, coverage or freshness checks.",
    "NO_CONFIRMED_SETUP": "Candidate setup confirmation was incomplete.",
    "READ_PLAN_OR_SCAN_BLOCKED": "A candidate read plan or scan was blocked.",
    "SCOPE_CURRENT_INPUT_UNAVAILABLE": "Scope inputs are unavailable.",
    "SWING_DERIVED_TARGET_GEOMETRY_INVALID": "Swing target geometry is invalid.",
    "SWING_ORIGINAL_FIRST_TARGET_REQUIRED": "Swing needs an original first target.",
    "SWING_ORIGINAL_SOURCES_UNAVAILABLE": "Original Swing history is unavailable.",
}


def stamp(value):
    if not isinstance(value, str) or len(value) > 48:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def evidence(state, report, *, observed_at, binding_hash):
    reasons = state.get("reasons") or []
    result = {"version": VERSION, "binding_sha256": binding_hash, "observed_at": observed_at,
              "state": state.get("status") if state.get("status") in STATES else "UNKNOWN",
              "reason": next((r for r in reasons if r in CODES), None)}
    schedule = state.get("schedule") or {}
    for key in ("prepare_at", "start_at", "close_at"):
        if stamp(schedule.get(key)):
            result[key] = schedule[key]
    if not report or not re.fullmatch(r"daily-\d{8}", str(report.get("run_id", ""))):
        return result
    operation = report.get("operation", {}).get("state")
    failures = report.get("worker_exit", {}).get("failures", [])
    issue = next((f for f in failures if f.get("component") in ("RUNTIME", "PUBLISHER", "COLLECTOR", "TERMINAL_PUBLISHER")), {})
    clocks = report.get("runtime_evidence", {})
    result["session"] = {
        "run_id": report["run_id"], "state": operation if operation in STATES else "UNKNOWN",
        "at": report.get("window_end") if stamp(report.get("window_end")) else None,
        "seconds": report.get("session_timing", {}).get("elapsed_seconds"),
        "entry_fills": report.get("run_execution", {}).get("entry_fills"),
        "exit_fills": report.get("run_execution", {}).get("exit_fills"),
        "component": issue.get("component"), "timeout": issue.get("error_class") == "FixtureProcessTimeout",
        "feed": clocks.get("feed") if clocks.get("feed") in ("FRESH", "STALE", "MISSING") else "UNKNOWN",
        "heartbeat": clocks.get("heartbeat") if clocks.get("heartbeat") in ("FRESH", "STALE", "MISSING") else "UNKNOWN",
    }
    decisions = report.get("decisions") or []
    decision = decisions[-1] if decisions else {}
    families = report.get("operation", {}).get("family_input_issues", {})
    checks = []
    for items in [*families.values(), *(decision.get(k, []) for k in ("issues", "blocker", "rejections", "contract_exclusions"))]:
        for code in ([items] if isinstance(items, str) else items if isinstance(items, list) else []):
            if isinstance(code, str) and code in INPUTS and code not in checks:
                checks.append(code)
    result["session"]["checks"] = checks[:8]
    scans = decision.get("scans", [])
    if scans:
        setups = [setup for scan in scans for setup in scan.get("setups", [])]
        result["session"]["confirmed"] = sum("CONFIRMED" in s.get("status", []) for s in setups)
    outcomes = report.get("cycle_outcomes")
    if isinstance(outcomes, list):
        result["session"]["completed"] = sum(r["count"] for r in outcomes if "COMPLETE" in r["status"])
        result["session"]["skipped"] = sum(r["count"] for r in outcomes if "SKIPPED" in r["status"])
    for key in ("seconds", "entry_fills", "exit_fills"):
        n = result["session"][key]
        if type(n) not in (int, float) or not 0 <= n <= 1000000:
            result["session"][key] = None
    return result


def display(directory, binding_hash, uid, now):
    unknown = {"state": "UNKNOWN", "title": "Status unavailable",
               "detail": "The daily controller has not published a current status."}
    try:
        fd = os.open(Path(directory) / "paper-status.json", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o444
                    or info.st_uid != uid or not 1 <= info.st_size <= 8192):
                return unknown
            record = json.loads(stream.read(8193))
        at = stamp(record["observed_at"])
        if record["version"] != VERSION or record["binding_sha256"] != binding_hash or at is None:
            return unknown
        fresh = 0 <= (now - at).total_seconds() <= FRESH_SECONDS
        status = record["state"] if fresh and record["state"] in STATES else "UNKNOWN"
        def eastern(t):
            return t.astimezone(ZoneInfo("America/New_York")).strftime("%b %d, %I:%M:%S %p ET")
        result = {"state": status, "title": STATES.get(status, "Controller status unknown"),
                  "checked": eastern(at), "detail": CODES.get(record.get("reason"), "") if fresh else
                  "Controller updates have stopped. Current worker health is unknown."}
        for key, label in (("prepare_at", "Preparation"), ("start_at", "Scheduled start"), ("close_at", "Session close")):
            event = stamp(record.get(key))
            if fresh and event and event >= now:
                result["schedule"] = label + " · " + eastern(event)
                break
        session = record.get("session")
        if session:
            end = stamp(session["at"])
            duration = session["seconds"]
            name = str(session["run_id"])
            if not re.fullmatch(r"daily-[0-9]{8}", name):
                return unknown
            label = STATES.get(session["state"], "Unknown")
            text = f"{name} · {label}"
            if type(duration) in (int, float) and 0 <= duration <= 86400:
                text += f" after {int(duration)//60}m {int(duration)%60:02d}s"
            if end:
                text += " · " + eastern(end)
            result["session"] = text
            component = session["component"]
            if component == "RUNTIME" and session["timeout"]:
                result["failure"] = "Local simulation subprocess timed out."
            elif component in ("RUNTIME", "PUBLISHER", "COLLECTOR", "TERMINAL_PUBLISHER"):
                result["failure"] = component.capitalize() + " stopped with an error."
            for key in ("feed", "heartbeat"):
                result[key] = session[key] if session[key] in ("FRESH", "STALE", "MISSING") else "UNKNOWN"
            result["checks"] = [INPUTS[code] for code in session.get("checks", [])[:8] if isinstance(code, str) and code in INPUTS]
            for key in ("entry_fills", "exit_fills", "completed", "skipped", "confirmed"):
                n = session.get(key)
                result[key] = n if type(n) is int and 0 <= n <= 1000000 else None
        return result
    except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        return unknown
