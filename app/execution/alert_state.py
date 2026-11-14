"""Read-only delivery backlog health; no transport or trading authority."""

import json


def report(db, now):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_alert_delivery'"
    ).fetchone():
        return {"status": "UNCONFIGURED", "pending": 0}
    policy = json.loads(
        db.execute("SELECT policy_json FROM execution_alert_delivery").fetchone()[0]
    )
    row = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(d.status='EXHAUSTED'),0),"
        "MIN(julianday(e.occurred_at)),MAX(julianday(e.occurred_at)),COUNT(julianday(e.occurred_at)) "
        "FROM execution_alerts a JOIN execution_events e ON e.sequence=a.event_sequence "
        "LEFT JOIN execution_alert_attempts d ON d.event_sequence=a.event_sequence "
        "WHERE d.status IS NULL OR d.status!='DELIVERED'"
    ).fetchone()
    # A bounded aggregate avoids loading the entire undelivered history into the transport.
    age = now.timestamp() - (row[2] - 2440587.5) * 86400 if row[2] is not None else None
    future = (row[3] - 2440587.5) * 86400 - now.timestamp() if row[3] is not None else 0
    blocked = (
        row[1] > 0
        or row[4] != row[0]
        or future > 0.001
        or (age is not None and age > policy["limits"]["max_pending_age_seconds"] + 0.001)
    )
    return {
        "status": "BLOCKED" if blocked else "PENDING" if row[0] else "OK",
        "pending": row[0],
        "oldest_age_seconds": round(age, 3) if age is not None else None,
        "exhausted": row[1],
    }


def entry_reasons(db, now):
    return ["EXECUTION_ALERT_DELIVERY_NOT_READY"] if report(db, now)["status"] == "BLOCKED" else []
