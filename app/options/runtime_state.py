"""Stored runtime evidence only. No owner, feed read or recovery authority."""

import json
from datetime import datetime

from app.options.runtime_models import RuntimePolicy


def _json(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 256 * 1024:
        raise ValueError("Bounded stored runtime record required")
    return json.loads(raw)


def report(db, now):
    if (
        db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_option_runtime'").fetchone()
        is None
    ):
        return {"status": "NOT_ENROLLED", "freshness": "NOT_RECORDED"}
    row = db.execute("SELECT * FROM execution_option_runtime WHERE id=1").fetchone()
    if row is None:
        raise ValueError("Runtime enrollment is missing")
    config = _json(row["config_json"])
    policy = RuntimePolicy.model_validate(config["runtime"])
    engine = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
    strategy = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
    if config["engine"] != _json(engine[0]) or config["strategy"] != _json(strategy[0]):
        raise ValueError("Runtime frozen owner binding changed")
    if row["status"] not in {"ENROLLED", "RUNNING", "BLOCKED", "STOPPING", "STOPPED", "FAILED"}:
        raise ValueError("Invalid stored runtime status")
    heartbeat = datetime.fromisoformat(row["heartbeat_at"]) if row["heartbeat_at"] else None
    age = (now - heartbeat).total_seconds() if heartbeat else None
    freshness = (
        "MISSING"
        if age is None
        else "FUTURE"
        if age < 0
        else ("STALE" if age >= policy.heartbeat_max_age_seconds else "FRESH")
    )
    from app.options.release_identity import stored_release

    extra = {}
    if policy.scope_inputs is not None:
        extra["scope_inputs"] = {
            "statuses": {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT status,COUNT(*) FROM execution_option_scope_runtime_inputs GROUP BY status"
                )
            },
            "latest": [
                dict(r)
                for r in db.execute(
                    "SELECT sequence,packet_hash,accepted_at,action_key,status "
                    "FROM execution_option_scope_runtime_inputs ORDER BY sequence DESC LIMIT 20"
                )
            ],
        }
    return {
        **extra,
        "release": stored_release(db, row["generation"]),
        "status": row["status"],
        "freshness": freshness,
        "heartbeat_at": row["heartbeat_at"],
        "age_seconds": age,
        "generation": row["generation"],
        "reason": row["reason"],
        "feed_sequence": row["feed_sequence"],
        "session": _json(row["session_json"]) if row["session_json"] else None,
        "cycles": {
            r[0]: r[1]
            for r in db.execute(
                "SELECT status,COUNT(*) FROM execution_option_runtime_slots GROUP BY status"
            )
        },
        "latest_slots": [
            dict(r)
            for r in db.execute(
                "SELECT slot,session,status,reason,started_at,completed_at FROM execution_option_runtime_slots ORDER BY slot DESC LIMIT 20"
            )
        ],
        "worker_liveness": "NOT_VERIFIED_BY_STORED_HEARTBEAT",
        "execution_authority": False,
    }


def entry_reasons(db, now):
    state = report(db, now)
    return (
        []
        if state["status"] == "NOT_ENROLLED"
        or (state["status"] == "RUNNING" and state["freshness"] == "FRESH")
        else ["OPTION_RUNTIME_NOT_READY"]
    )
