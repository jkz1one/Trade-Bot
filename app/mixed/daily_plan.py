"""Read-only exchange schedule and existing-owner facts for the daily PAPER host."""

import argparse
import json
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.models import utc_now
from app.execution.economics import summary
from app.mixed.connected_runtime import check
from app.mixed.feed_rollover import load_rollovers
from app.options.engine import fingerprint
from app.options.observer import JOURNAL_FILE_ERRORS, OptionObserver
from app.robinhood.schedule import XNYSCalendar

NY = ZoneInfo("America/New_York")


def schedule(now, calendar=None):
    cal = calendar or XNYSCalendar().calendar
    day = now.astimezone(NY).date()
    for offset in range(15):
        target = day + timedelta(days=offset)
        if not cal.is_session(target.isoformat()):
            continue
        opened = cal.session_open(target.isoformat()).to_pydatetime()
        closed = cal.session_close(target.isoformat()).to_pydatetime()
        if now >= closed:
            continue
        # Standard weekly expiry, verified by original capture before enrollment.
        expiry = target + timedelta(days=7)
        while expiry.weekday() != 4:
            expiry += timedelta(days=1)
        while not cal.is_session(expiry.isoformat()):
            expiry -= timedelta(days=1)
        if (expiry - target).days < 7:
            expiry += timedelta(days=7)
            while not cal.is_session(expiry.isoformat()):
                expiry -= timedelta(days=1)
        return {"target_session": target.isoformat(), "open_at": opened.isoformat(),
                "prepare_at": (opened - timedelta(minutes=30)).isoformat(),
                "start_at": (opened + timedelta(minutes=30)).isoformat(),
                "close_at": closed.isoformat(), "swing_expiration": expiry.isoformat()}
    raise ValueError("EXCHANGE_SESSION_UNAVAILABLE")


def failed_snapshot_read(db, owner):
    if (owner["runtime_status"] != "FAILED" or not owner["entry_halted"]
            or owner["halt_reason"] != "OPTION_RUNTIME_FAILED"):
        return False
    start = db.execute("SELECT sequence,payload FROM execution_events WHERE kind='OPTION_RUNTIME_STARTED' "
                       "ORDER BY sequence DESC LIMIT 1").fetchone()
    if start is None or json.loads(start["payload"]).get("generation") != owner["runtime_generation"]:
        return False
    # A later operator action or an unrelated halt cannot be overwritten by
    # the generic shutdown reason and then authorized as a read timeout.
    allowed = {"OPTION_RUNTIME_FEED_UNAVAILABLE", "OPTION_FIXTURE_READ_FAILED", "OPTION_RUNTIME_FAILED"}
    failures = 0
    terminal = False
    for row in db.execute("SELECT sequence,kind,payload FROM execution_events WHERE sequence>? AND "
                          "kind IN ('FIXTURE_READ_FAILED','MANUAL_HALT','OPTIONS_OPERATOR_COMMAND',"
                          "'OPTION_RUNTIME_STOPPED') ORDER BY sequence", (start["sequence"],)):
        kind, value = row["kind"], json.loads(row["payload"])
        if kind == "OPTIONS_OPERATOR_COMMAND" or (kind == "MANUAL_HALT" and value.get("reason") not in allowed):
            return False
        if kind == "FIXTURE_READ_FAILED":
            if value.get("operation") != "snapshot" or value.get("error_class") != "FixtureProcessTimeout":
                return False
            failures += 1
        if kind == "OPTION_RUNTIME_STOPPED":
            terminal = value.get("failed") is True and row["sequence"] == owner["owner_revision"]
    return terminal and failures == 1


def inspect(directory, feed_directory, policy_file, schemas_file, *, now=None):
    now = now or utc_now()
    result, settings, base, schemas, observer = check(
        directory, feed_directory, policy_file, schemas_file, clock_source=lambda: now)
    plan = schedule(now)
    target = plan["target_session"]
    with OptionObserver(feed_directory / "collector.db", base.population_id, native_journal=True).read() as db:
        rows = load_rollovers(db, base, schemas)
    enrolled = next((r for r in rows if r.target_session.isoformat() == target), None)
    latest = rows[-1].policy if rows else base
    with observer.read() as db:
        timeout_reviewable = failed_snapshot_read(db, result["owner_state"])
        costs = summary(db)
        last = db.execute("SELECT occurred_at FROM execution_events "
                          "WHERE kind='OPTION_RUNTIME_STARTED' ORDER BY sequence DESC LIMIT 1").fetchone()
    portfolio = observer.report(limit=100)
    blockers = []
    if (settings.limits.account_id != "local-simulation"
            or settings.limits.population_id != "connected-simulation-1000-v1"
            or settings.execution.capital != Decimal("1000")
            or settings.execution.mixed_owner.portfolio.max_plays != 2
            or Decimal(costs.get("policy", {}).get("daily_budget", "0")) != Decimal("1")
            or Decimal(costs.get("policy", {}).get("total_budget", "0")) != Decimal("5")):
        blockers.append("DAILY_PROFILE_MISMATCH")
    if (portfolio.get("schema") != "mixed-portfolio-observer-v2"
            or portfolio.get("status") != "OK" or portfolio.get("positions")
            or portfolio.get("unresolved") != 0):
        blockers.append("EXISTING_HOLDINGS_OR_UNRESOLVED_ORDERS")
    if costs.get("unknown_calls") or costs.get("judgment_blocked") or costs.get("calls_exceeding_bound"):
        blockers.append("MODEL_COST_OR_EVIDENCE_UNRESOLVED")
    if Decimal(costs.get("known_cost", "0")) >= Decimal("5"):
        blockers.append("MODEL_TOTAL_BUDGET_EXHAUSTED")
    if Decimal(costs.get("daily_cost", {}).get(target, "0")) >= Decimal("1"):
        blockers.append("MODEL_DAILY_BUDGET_EXHAUSTED")
    owner = result["owner_state"]
    if owner["runtime_status"] not in {"ENROLLED", "STOPPED"}:
        blockers.append("OWNER_NOT_NORMALLY_STOPPED")
    if owner["entry_halted"] and owner["halt_reason"] != "OPTION_RUNTIME_STOPPED":
        blockers.append("OWNER_HALT_REQUIRES_REVIEW")
    special = any(p.scope_binding or p.company_earnings or p.carry_intents for p in (base, latest))
    return {"version": "paper-daily-info-v1", "status": "DAILY_INFO", **plan,
            "owner_state": owner, "failed_snapshot_read": timeout_reviewable, "last_runtime_started_at": last[0] if last else None,
            "start_blockers": blockers,
            "automatic_catalog_blockers": ["EXACT_SESSION_BINDINGS_REQUIRED"] if special else [],
            "swing_history_enrolled": base.swing_history is not None,
            "receipt": ({"version": "paper-session-preparation-v1", "target_session": target,
                         "policy_sha256": fingerprint(enrolled.policy),
                         "session_review_sha256": enrolled.review_sha256, "live_enabled": False}
                        if enrolled else None),
            "provider_calls": False, "state_modified": False, "live_enabled": False,
            "trading_ready": False}


def main():
    from pathlib import Path

    p = argparse.ArgumentParser(description=__doc__)
    for name in ("directory", "feed-directory", "policy", "schemas"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    try:
        result = inspect(a.directory, a.feed_directory, a.policy, a.schemas)
    except ValueError as exc:
        if str(exc) not in JOURNAL_FILE_ERRORS:
            raise
        print(json.dumps({"status": "UNAVAILABLE", "reason": str(exc), "live_enabled": False}))
        raise SystemExit(2) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
