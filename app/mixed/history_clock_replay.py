"""Re-evaluate retained history scans at their original times, offline and read-only."""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.options.coordinator import DegenFrame
from app.options.degen import DegenHistory, scan_degen
from app.options.engine import fingerprint
from app.options.runtime_cli import load
from app.robinhood.schedule import XNYSCalendar


def replay_history(history, policy, at, calendar):
    original = history.model_dump(mode="json")
    if (history.source != "robinhood-mcp"
            or history.simulation_basis != "ROBINHOOD_OBSERVED_V1"):
        raise ValueError("Observed Robinhood history required")
    # Old mapper versions already used the final completed bar's end. Validate
    # that exact equality before applying the new explicit clock interpretation.
    revised = DegenHistory.model_validate(original | {"source_clock_basis": "COMPLETED_BAR_END"})
    scan = scan_degen(revised, policy, calendar.current_window(at), now=at)
    return {
        "symbol": history.symbol, "evaluated_at": at.isoformat(),
        "source_at": history.source_at.isoformat(), "received_at": history.received_at.isoformat(),
        "bar_close_to_receipt_seconds": (history.received_at - history.source_at).total_seconds(),
        "bar_age_at_evaluation_seconds": (at - history.source_at).total_seconds(),
        "complete": history.complete, "entitlement": history.entitlement,
        "replayed_issues": list(scan.issues),
        "setups": [{"family": o.family, "right": o.right, "status": o.status,
                    "reasons": list(o.reasons)} for o in scan.observations],
        "original_history_unchanged": history.model_dump(mode="json") == original,
    }


def report(owner, since, until):
    settings = load(str(owner / "runtime.json"))
    if settings.limits.mode != "PAPER":
        raise ValueError("PAPER owner required")
    calendar = XNYSCalendar()
    db = sqlite3.connect((owner / "options.db").as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    cycles = []
    try:
        for row in db.execute(
            "SELECT cycle_key,fingerprint,inputs_json,result_json FROM execution_option_opportunities "
            "WHERE started_at>=? AND started_at<=? ORDER BY started_at LIMIT 25",
            (since.isoformat(), until.isoformat()),
        ):
            if len(row["inputs_json"]) > 2 * 1024 * 1024 or len(row["result_json"] or "") > 1024 * 1024:
                raise ValueError("Bounded original opportunity required")
            frame = DegenFrame.model_validate_json(row["inputs_json"])
            if fingerprint(frame) != row["fingerprint"]:
                raise ValueError("Original opportunity fingerprint mismatch")
            result = json.loads(row["result_json"] or "{}")
            scans = {scan["symbol"]: scan for scan in result.get("scans", [])}
            histories = []
            for history in frame.histories:
                if history.symbol not in scans:
                    continue
                old = scans[history.symbol]
                item = replay_history(history, settings.setup,
                                      datetime.fromisoformat(old["evaluated_at"]), calendar)
                item["original_issues"] = old.get("issues", [])
                histories.append(item)
            cycles.append({"cycle_key": row["cycle_key"], "histories": histories})
    finally:
        db.close()
    return {"status": "SAVED_HISTORY_REPLAY", "cycles": cycles,
            "configured_max_bar_age_seconds": settings.setup.max_bar_age_seconds,
            "configured_max_receive_lag_seconds": settings.setup.max_receive_lag_seconds,
            "live_enabled": False, "state_modified": False, "provider_calls": False,
            "model_calls": 0, "orders_submitted": 0, "trading_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    args = parser.parse_args()
    since, until = datetime.fromisoformat(args.since), datetime.fromisoformat(args.until)
    if since.utcoffset() is None or until.utcoffset() is None or not 0 <= (until - since).total_seconds() <= 3600:
        raise ValueError("Bounded aware session window required")
    print(json.dumps(report(Path(args.owner), since, until)))


if __name__ == "__main__":
    main()
