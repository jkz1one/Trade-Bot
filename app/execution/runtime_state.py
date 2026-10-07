"""Read-only entry authority for the opt-in fixture PAPER service."""

import json
from datetime import datetime


def report(db, now):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_runtime'").fetchone():
        return {"status": "UNCONFIGURED", "fresh": False}
    row = db.execute("SELECT * FROM execution_runtime WHERE id=1").fetchone()
    if row is None:
        return {"status": "UNCONFIGURED", "fresh": False}
    policy = json.loads(row["policy_json"])
    age = (
        (now - datetime.fromisoformat(row["heartbeat_at"])).total_seconds()
        if row["heartbeat_at"]
        else None
    )
    return {
        "status": row["status"],
        "fresh": row["status"] == "RUNNING"
        and age is not None
        and 0 <= age <= policy["limits"]["max_age_seconds"],
        "heartbeat_at": row["heartbeat_at"],
        "age_seconds": age,
        "generation": row["generation"],
        "agent": policy["agent"],
        "cycles": {
            r[0]: r[1]
            for r in db.execute(
                "SELECT status,COUNT(*) FROM execution_runtime_cycles GROUP BY status"
            )
        },
        "latest_cycles": [
            {
                "slot": r["slot"],
                "status": r["status"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "feed_sequence": r["feed_sequence"],
                "result": json.loads(r["result_json"]) if r["result_json"] else None,
            }
            for r in db.execute(
                "SELECT * FROM execution_runtime_cycles ORDER BY slot DESC LIMIT 20"
            )
        ],
    }


def entry_reasons(db, now):
    state = report(db, now)
    return (
        []
        if state["status"] == "UNCONFIGURED" or state["fresh"]
        else ["EXECUTION_RUNTIME_NOT_READY"]
    )
