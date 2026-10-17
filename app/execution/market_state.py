"""Read-only authority and warmup bounds for explicit continuous market collection."""

import json
from datetime import datetime


def report(db, now):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_market_service'"
    ).fetchone():
        return {"status": "UNCONFIGURED", "fresh": False}
    row = db.execute("SELECT * FROM execution_market_service WHERE id=1").fetchone()
    if row is None:
        return {"status": "UNCONFIGURED", "fresh": False}
    policy = json.loads(row["policy_json"])
    age = (
        (now - datetime.fromisoformat(row["last_success_at"])).total_seconds()
        if row["last_success_at"]
        else None
    )
    quote_age = (
        (now - datetime.fromisoformat(row["oldest_quote_at"])).total_seconds()
        if row["oldest_quote_at"]
        else None
    )
    attempt_age = (
        (now - datetime.fromisoformat(row["attempt_started_at"])).total_seconds()
        if row["attempt_started_at"]
        else None
    )
    heartbeat_age = (
        (now - datetime.fromisoformat(row["heartbeat_at"])).total_seconds()
        if row["heartbeat_at"]
        else None
    )
    return {
        "status": row["status"],
        "generation": row["generation"],
        "fresh": row["status"] in {"RUNNING", "COLLECTING"}
        and age is not None
        and 0 <= age <= policy["limits"]["max_age_seconds"]
        and quote_age is not None
        and 0 <= quote_age <= policy["quote_max_age_seconds"],
        "waiting_flat": (
            row["status"] == "COLLECTING"
            and attempt_age is not None
            and 0 <= attempt_age <= policy["read_timeout_seconds"] + 2
        )
        or (
            row["status"] == "IDLE"
            and heartbeat_age is not None
            and 0 <= heartbeat_age <= policy["limits"]["poll_seconds"] + 2
        ),
        "heartbeat_at": row["heartbeat_at"],
        "last_success_at": row["last_success_at"],
        "oldest_quote_at": row["oldest_quote_at"],
        "age_seconds": age,
        "attempt_started_at": row["attempt_started_at"],
        "last_feed_sequence": row["feed_sequence"],
        "error_class": row["error_class"],
    }


def entry_reasons(db, now):
    state = report(db, now)
    return (
        []
        if state["status"] == "UNCONFIGURED" or state["fresh"]
        else ["EXECUTION_MARKET_SERVICE_NOT_READY"]
    )
