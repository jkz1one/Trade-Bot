"""Three bounded read-only captures; source-clock evidence, never trading authority."""

import argparse
import hashlib
import json
import os
import time
from contextlib import redirect_stdout
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

from jsonschema.exceptions import ValidationError as SchemaError

from app.options.read_capture import CaptureFailure, CaptureResult
from app.options.read_cli import main as capture_main
from app.options.read_gateway import CapturePlan
from app.options.read_mapping import SCHEMA_SHA256, instant, quote_rows, response
from app.robinhood.schedule import XNYSCalendar

# Exact October 26 contracts from the operator's accepted instrument listing.
# Fixed diagnostic subjects, not a strategy shortlist or trade recommendation.
CONTRACTS = {
    "0eb7725e-bf00-4817-8e47-0092d1910f75": "SPY 2026-10-26 760 CALL",
    "6058511b-ce40-4dd6-8ef9-8f5a3736ed90": "QQQ 2026-10-26 705 CALL",
}
FRESH_SECONDS = 30


def plan_at(now):
    now = instant(now)
    include_options = (
        now.astimezone(ZoneInfo("America/New_York")).date().isoformat() == "2026-10-26"
    )
    calls = [
        {"label": "equities", "tool": "get_equity_quotes", "arguments": {"symbols": ["SPY", "QQQ"]}}
    ]
    if include_options:
        calls.append(
            {
                "label": "options",
                "tool": "get_option_quotes",
                "arguments": {"instrument_ids": list(CONTRACTS)},
            }
        )
    return CapturePlan(
        purpose="SCHEMA_MAPPING_EVIDENCE",
        symbols=("SPY", "QQQ"),
        instrument_ids=tuple(CONTRACTS) if include_options else (),
        calls=tuple(calls),
    )


def save(path, value):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def inspect_capture(artifact, plan):
    """Revalidate original plan, pinned schema and exact quote subjects offline."""
    if artifact.get("status") != "COMPLETE":
        raise ValueError("Capture did not complete")
    result = CaptureResult.model_validate(artifact["result"])
    if result.status != "COMPLETE" or result.plan != plan or result.schemas is None:
        raise ValueError("Original complete plan and schemas required")
    if result.schemas.sha256 != SCHEMA_SHA256 or not result.started_at <= result.collected_at:
        raise ValueError("Pinned schema and original clocks required")
    rows = []
    for call, receipt in zip(plan.calls, result.observations, strict=True):
        if (
            receipt.get("tool") != call.tool
            or receipt.get("label") != call.label
            or receipt.get("completed") is not True
        ):
            raise ValueError("Exact completed receipt required")
        _, data = response(result.schemas, call, receipt["raw"], call.tool)
        equity = call.tool == "get_equity_quotes"
        expected = call.arguments["symbols" if equity else "instrument_ids"]
        for quote in quote_rows(data, expected, "symbol" if equity else "instrument_id"):
            identity = quote["symbol" if equity else "instrument_id"]
            clocks = [
                instant(quote[k])
                for k in (("venue_bid_time", "venue_ask_time") if equity else ("updated_at",))
            ]
            source = min(clocks)
            age = (result.collected_at - source).total_seconds()
            bid, ask = (Decimal(str(quote[k])) for k in ("bid_price", "ask_price"))
            valid_book = bid.is_finite() and ask.is_finite() and 0 < bid <= ask
            valid_clock = max(clocks) <= result.collected_at
            rows.append(
                {
                    "subject": identity,
                    "label": identity if equity else CONTRACTS[identity],
                    "asset": "STOCK" if equity else "OPTION",
                    "bid": str(bid),
                    "ask": str(ask),
                    "bid_size": None if equity else quote["bid_size"],
                    "ask_size": None if equity else quote["ask_size"],
                    "source_at": source.isoformat(),
                    "original_source_times": [
                        quote[k]
                        for k in (
                            ("venue_bid_time", "venue_ask_time") if equity else ("updated_at",)
                        )
                    ],
                    "received_at": result.collected_at.isoformat(),
                    "age_seconds_at_capture": round(age, 3),
                    "fresh_book": bool(valid_book and valid_clock and 0 <= age <= FRESH_SECONDS),
                    "entitlement": "UNKNOWN",
                }
            )
    return rows


def summarize(samples, phases):
    subjects = sorted({r["subject"] for sample in samples for r in sample})
    result = []
    for subject in subjects:
        rows = [r for sample in samples for r in sample if r["subject"] == subject]
        clocks = [instant(r["source_at"]) for r in rows]
        monotonic = all(a <= b for a, b in pairwise(clocks))
        advancing = len(set(clocks)) > 1 and monotonic
        result.append(
            {
                "subject": subject,
                "label": rows[0]["label"],
                "samples": len(rows),
                "all_fresh": len(rows) == 3 and all(r["fresh_book"] for r in rows),
                "source_clock_advanced": advancing,
                "source_clock_regressed": not monotonic,
                "latest": rows[-1],
            }
        )
    complete = (
        len(samples) == 3
        and len(phases) == 3
        and bool(result)
        and all(r["samples"] == 3 for r in result)
    )
    fresh = complete and all(r["all_fresh"] and r["source_clock_advanced"] for r in result)
    regular = len(phases) == 3 and all(p == "REGULAR" for p in phases)
    return {
        "status": "FRESH_ADVANCING_QUOTES" if fresh else "INCOMPLETE_OR_STALE_QUOTES",
        "regular_session_quote_proof": bool(fresh and regular),
        "session_phases": phases,
        "samples_completed": len(samples),
        "freshness_threshold_seconds": FRESH_SECONDS,
        "subjects": result,
        "execution_authority": False,
        "orders_submitted": 0,
        "model_calls": 0,
        "paper_trading_ready": False,
        "remaining": [
            "Reviewed option contract terms",
            "Data entitlement",
            "Executable stock sizes",
            "Scope/SPX mapping",
            "Connected simulator/runtime and dashboard activation",
        ],
    }


def run(
    directory,
    schemas,
    oauth_file,
    *,
    clock=lambda: datetime.now(UTC),
    capture=capture_main,
    pause=time.sleep,
    calendar=None,
):
    directory = Path(directory)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("Existing absolute private output directory required")
    if directory.stat().st_mode & 0o777 != 0o700 or directory.stat().st_uid != os.geteuid():
        raise ValueError("Private owned output directory required")
    if any(directory.iterdir()):
        raise ValueError("New empty evidence directory required; never overwrite a prior run")
    calendar = calendar or XNYSCalendar()
    samples, phases, artifacts, failures = [], [], [], []
    for index in range(1, 4):
        now = instant(clock())
        plan = plan_at(now)
        plan_path = directory / f"plan-{index}.json"
        sample_path = directory / f"sample-{index}.json"
        save(plan_path, plan.model_dump(mode="json"))
        phases.append("REGULAR" if calendar.current_window(now) is not None else "OUTSIDE_REGULAR")
        with (directory / f"capture-{index}.json").open("x") as stream, redirect_stdout(stream):
            code = capture(
                [
                    "capture",
                    "--oauth-file",
                    str(oauth_file),
                    "--schemas",
                    str(schemas),
                    "--schema-sha256",
                    SCHEMA_SHA256,
                    "--plan",
                    str(plan_path),
                    "--output",
                    str(sample_path),
                    "--timeout-seconds",
                    "30",
                ]
            )
        if sample_path.is_file():
            artifacts.append(
                {
                    "file": sample_path.name,
                    "sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
                }
            )
        if code:
            failure = {"sample": index, "reason": "CAPTURE_FAILED", "exit_code": code}
            try:
                summary = json.loads((directory / f"capture-{index}.json").read_text())
                if summary.get("failure") is not None:
                    failure["diagnostics"] = CaptureFailure.model_validate(
                        summary["failure"]
                    ).model_dump(mode="json")
            except (ValueError, TypeError):
                pass
            failures.append(failure)
            break
        try:
            rows = inspect_capture(json.loads(sample_path.read_bytes()), plan)
        except (ValueError, KeyError, TypeError, ArithmeticError, SchemaError):
            failures.append({"sample": index, "reason": "QUOTE_VALIDATION_FAILED"})
            break
        samples.append(rows)
        if any(calendar.current_window(instant(r["received_at"])) is None for r in rows):
            phases[-1] = "OUTSIDE_REGULAR"
        save(directory / f"quotes-{index}.json", rows)
        if index < 3:
            pause(20)
    report = summarize(samples, phases)
    report.update(
        {
            "version": "bounded-market-data-proof-v1",
            "observed_at": instant(clock()).isoformat(),
            "artifacts": artifacts,
            "failures": failures,
            "options_sample_expiry": "2026-10-26",
            "options_included": bool(plan.instrument_ids),
        }
    )
    save(directory / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--schemas", required=True)
    parser.add_argument("--oauth-file", required=True)
    parser.add_argument(
        "--run",
        action="store_true",
        help="Explicitly perform at most six market read calls plus three schema discoveries",
    )
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run to perform this bounded read-only data check")
    report = run(args.directory, args.schemas, args.oauth_file)
    print(json.dumps(report, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
