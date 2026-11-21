"""Read-only supervisor health gates, shared without importing a service or adapter."""

import json
from datetime import datetime


def report(db, now):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_supervisor'").fetchone():
        return {"status": "UNCONFIGURED", "fresh": False}
    row = db.execute("SELECT * FROM execution_supervisor WHERE id=1").fetchone()
    if row is None:
        return {"status": "UNCONFIGURED", "fresh": False}
    policy = json.loads(row["policy_json"])
    age = (
        (now - datetime.fromisoformat(row["heartbeat_at"])).total_seconds()
        if row["heartbeat_at"]
        else None
    )
    result = json.loads(row["result_json"]) if row["result_json"] else None
    return {
        "status": row["status"],
        "fresh": row["status"] == "RUNNING"
        and age is not None
        and 0 <= age <= policy["limits"]["max_age_seconds"]
        and result is not None
        and result["status"] == "OK",
        "heartbeat_at": row["heartbeat_at"],
        "age_seconds": age,
        "generation": row["generation"],
        "policy": policy,
        "last_result": result,
        "last_feed_sequence": row["feed_sequence"],
    }


def entry_reasons(db, now):
    state = report(db, now)
    return (
        []
        if state["status"] == "UNCONFIGURED" or state["fresh"]
        else ["EXECUTION_SUPERVISOR_NOT_READY"]
    )
