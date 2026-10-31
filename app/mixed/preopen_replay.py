"""Explain one retained pre-open capture offline without changing source bindings."""

import argparse
import json
import sqlite3
import time
from pathlib import Path

from jsonschema.exceptions import ValidationError as SchemaError

from app.mixed.continuous_feed import FeedPolicy
from app.mixed.feed_rollover import load_rollovers, policy_for
from app.mixed.swing_bar_mapping import HistoryMappingError
from app.mixed.swing_bar_mapping import map_history as mapped_history
from app.mixed.swing_feed import map_history, planned_history, snapshot, target_session
from app.options.engine import fingerprint
from app.options.operator_inbox import read
from app.options.read_capture import MAX_RESPONSE_BYTES, CaptureResult, policy_digest
from app.options.read_gateway import ReadSchemas, same_schema_contract
from app.options.venue import private_path
from app.robinhood.schedule import XNYSCalendar


def saved_capture(db, base, schemas, sequence):
    """Validate original evidence and its enrolled session inside caller transaction."""
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Positive saved collector sequence required")
    rows = load_rollovers(db, base, schemas)
    saved = db.execute(
        "SELECT request_hash,raw_json FROM attempts WHERE sequence=? "
        "AND length(CAST(raw_json AS BLOB))<=?", (sequence, MAX_RESPONSE_BYTES),
    ).fetchone()
    if saved is None or saved["raw_json"] is None:
        raise ValueError("Bounded original capture required")
    captured = CaptureResult.model_validate_json(saved["raw_json"])
    checks = {
        "plan": captured.plan is not None and fingerprint(captured.plan) == saved["request_hash"],
        "schema_contract": same_schema_contract(captured.schemas, schemas),
        "operation": captured.operation == "CAPTURE",
        "capture_policy": captured.policy_sha256 == policy_digest(base.capture),
        "capture_clocks": captured.started_at <= captured.collected_at,
    }
    if not all(checks.values()):
        raise CaptureBindingMismatch(checks)
    target = target_session(captured.started_at, XNYSCalendar())
    if target is None:
        raise ValueError("Original pre-open window required")
    policy = policy_for(base, rows, target)
    if policy.swing_history is None:
        raise ValueError("History policy unavailable")
    symbols = tuple(i.symbol for i in policy.stocks)
    selected, calls = planned_history(policy.swing_history, symbols, captured.started_at)
    actual = tuple(c for c in captured.plan.calls if c.label.startswith("swing-"))
    if selected != target or actual != calls or not calls:
        raise ValueError("Original history request mismatch")
    return captured, policy, target, calls


def report(feed_directory, policy_file, schemas_file, sequence):
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Positive saved collector sequence required")
    base = FeedPolicy.model_validate_json(read(policy_file, 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(schemas_file, 256 * 1024))
    path = Path(feed_directory) / "collector.db"
    private_path(path)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    deadline = time.monotonic() + 15
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        captured, policy, target, calls = saved_capture(db, base, schemas, sequence)
        symbols = tuple(i.symbol for i in policy.stocks)
        results = []
        for call, receipt in zip(captured.plan.calls, captured.observations, strict=True):
            if call not in calls:
                continue
            if receipt.get("label") != call.label or receipt.get("tool") != call.tool:
                raise ValueError("Original receipt identity mismatch")
            item = {"label": call.label}
            if receipt.get("completed") is not True:
                item.update(status="BLOCKED", reason="SOURCE_READ_INCOMPLETE")
            else:
                try:
                    mapper = (mapped_history if policy.swing_history.bar_mapping == "utc-day-halfhour-v1"
                              else map_history)
                    histories = mapper(schemas, call, receipt["raw"], received_at=captured.collected_at,
                                       target=target, count=(policy.swing_history.daily_bars
                                       if call.arguments["interval"] == "day" else policy.swing_history.hourly_bars))
                    item.update(status="MAPPED", bars={h.symbol: len(h.bars) for h in histories})
                except (ValueError, TypeError, KeyError, ArithmeticError, SchemaError) as exc:
                    item.update(status="BLOCKED", diagnostic=exc.detail if isinstance(exc, HistoryMappingError)
                                else {"reason": "HISTORY_MAPPING_UNAVAILABLE", "error_class": type(exc).__name__})
            results.append(item)
        # Per-series diagnostics cannot upgrade an incomplete overall capture.
        mapped = False
        if all(item["status"] == "MAPPED" for item in results):
            try:
                snapshot(policy.swing_history, symbols, schemas, captured)
                mapped = True
            except (ValueError, TypeError, KeyError, ArithmeticError, SchemaError):
                pass
        return {"version": "saved-preopen-history-v1", "status": "SAVED_PREOPEN_REPLAY",
                "sequence": sequence, "target_session": target.isoformat(),
                "captured_at": captured.collected_at.isoformat(), "capture_sha256": fingerprint(captured),
                "enrolled_schema_discovered_at": schemas.captured_at.isoformat(),
                "capture_schema_discovered_at": captured.schemas.captured_at.isoformat(),
                "policy_sha256": fingerprint(policy), "history_mapped": mapped, "histories": results,
                "state_modified": False, "provider_calls": False, "model_calls": 0,
                "orders_submitted": 0, "live_enabled": False, "trading_ready": False}
    finally:
        db.close()


class CaptureBindingMismatch(ValueError):
    def __init__(self, checks):
        super().__init__("Original capture binding mismatch")
        self.checks = checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("feed-directory", "policy", "schemas"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--sequence", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        result = report(args.feed_directory, args.policy, args.schemas, args.sequence)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError) as exc:
        from app.execution.failure import failure_details
        result = {"status": "UNAVAILABLE", "reason": "SAVED_PREOPEN_REPLAY_UNAVAILABLE",
                  "state_modified": False, "provider_calls": False, "live_enabled": False,
                  "failure": failure_details(exc)}
        if isinstance(exc, CaptureBindingMismatch):
            result["binding_checks"] = exc.checks
        print(json.dumps(result))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
