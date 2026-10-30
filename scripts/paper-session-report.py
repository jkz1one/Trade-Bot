#!/usr/bin/env python3
"""Read a retained session's decision reasons without a build, run or provider call."""

import argparse
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CODE = re.compile(r"[A-Z][A-Z0-9_]{1,95}\Z")
STATE = Path("/var/lib/trade-bot-connected")


def codes(value):
    """Only bounded machine-code leaves from explicitly selected evidence fields."""
    found = set()

    def visit(item, depth=0):
        if depth > 8 or len(found) >= 100:
            return
        if isinstance(item, str) and CODE.fullmatch(item):
            found.add(item)
        elif isinstance(item, dict):
            for child in list(item.values())[:100]:
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item[:100]:
                visit(child, depth + 1)

    visit(value)
    return sorted(found)


def outcome(raw):
    value = json.loads(raw) if raw else {}
    result = {"status": codes(value.get("status")), "reason": codes(value.get("reason"))}
    for field in ("issues", "blocker", "unavailable_families", "rejections",
                  "stock_rejections", "scope_rejections"):
        selected = codes(value.get(field))
        if selected:
            result[field] = selected
    result["option_candidates"] = len(value.get("candidates") or [])
    result["stock_candidates"] = len(value.get("stock_candidates") or [])
    result["scans"] = []
    for scan in (value.get("scans") or [])[:12]:
        result["scans"].append({
            "symbol": codes(scan.get("symbol")),
            "issues": codes(scan.get("issues")),
            "setups": [{"family": codes(o.get("family")), "status": codes(o.get("status")),
                        "reasons": codes(o.get("reasons"))}
                       for o in (scan.get("observations") or [])[:12]],
        })
    result["contract_exclusions"] = sorted(set(
        code for plan in (value.get("read_plans") or [])[:12]
        for code in codes([plan.get("issues"), plan.get("exclusions")])
    ))
    return result


def connection(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


def report(directory, started, finished):
    start = datetime.fromisoformat(started).astimezone(timezone.utc).isoformat()
    end = datetime.fromisoformat(finished).astimezone(timezone.utc).isoformat()
    if end < start:
        raise ValueError("INVALID_SESSION_WINDOW")
    result = {"window_start": start, "window_end": end, "live_enabled": False,
              "provider_calls": False, "state_modified": False}
    db = connection(directory / "owner/options.db")
    try:
        result["cycles"] = [dict(r) for r in db.execute(
            "SELECT slot,status,reason,started_at,completed_at FROM execution_option_runtime_slots "
            "WHERE started_at>=? AND started_at<=? ORDER BY slot LIMIT 25", (start, end))]
        result["decisions"] = []
        for row in db.execute(
            "SELECT cycle_key,started_at,status,CASE WHEN length(result_json)<=524288 "
            "THEN result_json ELSE NULL END AS result_json FROM execution_option_opportunities "
            "WHERE started_at>=? AND started_at<=? ORDER BY started_at LIMIT 25", (start, end)
        ):
            result["decisions"].append({"cycle_key": row["cycle_key"],
                "started_at": row["started_at"], "stored_status": row["status"],
                "evidence_available": row["result_json"] is not None,
                **outcome(row["result_json"])})
        result["reviewed_entry_resumes"] = db.execute(
            "SELECT COUNT(*) FROM execution_events WHERE kind='OPTION_REVIEWED_RESUME' "
            "AND occurred_at>=? AND occurred_at<=?", (start, end)).fetchone()[0]
        result["current_runtime"] = [dict(r) for r in db.execute(
            "SELECT status,reason,feed_sequence FROM execution_option_runtime WHERE id=1")]
        result["current_control"] = [dict(r) for r in db.execute(
            "SELECT halted,halt_reason FROM execution_control WHERE id=1")]
        result["account_total_fills"] = db.execute("SELECT COUNT(*) FROM execution_fills").fetchone()[0]
    finally:
        db.close()
    db = connection(directory / "collector/collector.db")
    try:
        result["collection"] = [dict(r) for r in db.execute(
            "SELECT status,COUNT(*) AS attempts,MIN(sequence) AS first_sequence,"
            "MAX(sequence) AS last_sequence FROM attempts WHERE started_at>=? "
            "AND started_at<=? GROUP BY status", (start, end))]
    finally:
        db.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", args.run_id):
        raise ValueError("INVALID_RUN_ID")
    fmt = '{"state":{{json .State}},"label":{{json (index .Config.Labels "trade-bot.connected-session-v1")}}}'
    inspected = subprocess.run(
        ["docker", "inspect", "--format", fmt, "trade-bot-connected-" + args.run_id],
        capture_output=True, text=True, timeout=10,
    )
    if inspected.returncode or len(inspected.stdout) > 16384:
        raise ValueError("SESSION_INSPECTION_FAILED")
    container = json.loads(inspected.stdout)
    if not container.get("label"):
        raise ValueError("NOT_A_CONNECTED_SESSION")
    state = container["state"]
    if state["Status"] != "exited":
        raise ValueError("SESSION_NOT_FINISHED")
    result = report(STATE, state["StartedAt"], state["FinishedAt"])
    result.update(run_id=args.run_id, container_exit_code=state["ExitCode"],
                  status="SAVED_SESSION_REPORT")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError,
            sqlite3.Error, subprocess.TimeoutExpired) as exc:
        reason = str(exc) if type(exc) is ValueError and CODE.fullmatch(str(exc)) else type(exc).__name__
        print(json.dumps({"status": "UNAVAILABLE", "reason": reason,
                          "state_modified": False, "provider_calls": False}))
        raise SystemExit(2)
