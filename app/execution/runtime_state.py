"""Read-only entry authority for the opt-in fixture PAPER service."""

import hashlib
import json
from datetime import datetime


def resolutions_enabled(db):
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_runtime_resolutions'"
        ).fetchone()
        is not None
    )


def unresolved(db):
    if resolutions_enabled(db):
        total = 0
        for row in db.execute(
            "SELECT c.*,r.cycle_hash AS resolution_hash FROM execution_runtime_cycles c LEFT JOIN execution_runtime_resolutions r ON r.slot=c.slot WHERE c.status IN ('CLAIMED','INTERRUPTED')"
        ):
            original = dict(row)
            saved = original.pop("resolution_hash")
            digest = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
            total += row["status"] == "CLAIMED" or saved != digest
        return total
    return db.execute(
        "SELECT COUNT(*) FROM execution_runtime_cycles WHERE status IN ('CLAIMED','INTERRUPTED')"
    ).fetchone()[0]


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
        "unresolved_cycles": unresolved(db),
        "resolved_cycles": db.execute(
            "SELECT COUNT(*) FROM execution_runtime_resolutions"
        ).fetchone()[0]
        if resolutions_enabled(db)
        else 0,
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
                "resolution": dict(resolution)
                if (
                    resolutions_enabled(db)
                    and (
                        resolution := db.execute(
                            "SELECT resolved_at,command_id,cycle_hash FROM execution_runtime_resolutions WHERE slot=?",
                            (r["slot"],),
                        ).fetchone()
                    )
                )
                else None,
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
