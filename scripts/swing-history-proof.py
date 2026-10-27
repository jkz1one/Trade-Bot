"""One bounded daily/hourly capture for the enrolled Swing history policy."""

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema.exceptions import ValidationError as SchemaError

from app.domain.models import utc_now
from app.mixed.continuous_feed import FeedPolicy
from app.mixed.swing_feed import planned_history, snapshot
from app.options.operator_inbox import private_directory, save
from app.options.read_capture import CaptureResult
from app.options.read_cli import main as capture_main
from app.options.read_cli import private_json
from app.options.read_gateway import CapturePlan
from app.options.read_mapping import SCHEMA_SHA256, response


def plan_for(policy, now):
    if policy.swing_history is None:
        raise ValueError("Swing history is not enrolled")
    symbols = tuple(i.symbol for i in policy.stocks)
    target, calls = planned_history(policy.swing_history, symbols, now)
    if target is None:
        return None, None
    return target, CapturePlan(purpose="SCHEMA_MAPPING_EVIDENCE", symbols=symbols, calls=calls)


def inspect_capture(policy, plan, artifact):
    result = CaptureResult.model_validate(artifact["result"])
    if (
        artifact.get("operation") != "capture"
        or artifact.get("execution_authority") is not False
        or artifact.get("status") != result.status
        or result.operation != "CAPTURE"
        or result.plan != plan
        or result.schemas is None
        or result.schemas.sha256 != SCHEMA_SHA256
        or result.started_at > result.collected_at
    ):
        raise ValueError("Original pinned capture and plan required")
    diagnostics = []
    for call, receipt in zip(plan.calls, result.observations):
        if receipt.get("label") != call.label or receipt.get("tool") != call.tool:
            raise ValueError("Receipt identity changed")
        item = {"label": call.label, "completed": receipt.get("completed") is True}
        if item["completed"]:
            try:
                _, data = response(result.schemas, call, receipt["raw"], call.tool)
                item["series"] = [
                    {
                        "symbol": row.get("symbol"),
                        "interval": row.get("interval"),
                        "bars": len(row.get("bars") or []),
                        "first_begins_at": (row.get("bars") or [{}])[0].get("begins_at"),
                        "last_begins_at": (row.get("bars") or [{}])[-1].get("begins_at"),
                    }
                    for row in data.get("results", [])
                    if isinstance(row, dict)
                ]
            except (ValueError, KeyError, TypeError, SchemaError):
                item["mapping_status"] = "SCHEMA_UNAVAILABLE"
        diagnostics.append(item)
    report = {
        "version": "bounded-swing-history-proof-v1",
        "status": "HISTORY_UNAVAILABLE",
        "completed_reads": sum(r["completed"] for r in diagnostics),
        "expected_reads": len(plan.calls),
        "diagnostics": diagnostics,
        "captured_at": result.collected_at.isoformat(),
        "entitlement": "UNKNOWN",
        "provider_calls": True,
        "model_calls": 0,
        "orders_submitted": 0,
        "state_modified": False,
        "live_enabled": False,
        "trading_ready": False,
    }
    if result.status != "COMPLETE" or len(result.observations) != len(plan.calls):
        return report, None
    try:
        history = snapshot(policy.swing_history, tuple(plan.symbols), result.schemas, result)
    except (ValueError, KeyError, TypeError, ArithmeticError, SchemaError):
        report["status"] = "HISTORY_MAPPING_UNAVAILABLE"
        return report, None
    report.update(
        status="HISTORY_MAPPED",
        target_session=history.target_session.isoformat(),
        daily_bars={h.symbol: len(h.bars) for h in history.daily},
        hourly_bars={h.symbol: len(h.bars) for h in history.hourly},
    )
    return report, history


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--schemas", required=True)
    parser.add_argument("--oauth-file", required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    directory = Path(args.directory)
    try:
        private_directory(directory)
        policy = FeedPolicy.model_validate(private_json(args.policy))
        target, plan = plan_for(policy, utc_now())
        if plan is None:
            print(json.dumps({"status": "WAIT_FOR_PREOPEN_WINDOW", "provider_calls": False}))
            return 2
        if not args.run:
            print(
                json.dumps(
                    {
                        "status": "PLAN_ONLY",
                        "target_session": str(target),
                        "plan": plan.model_dump(mode="json"),
                        "provider_calls": False,
                    }
                )
            )
            return 0
        # Create-only artifacts prevent accidental reuse or replacement of prior evidence.
        plan_path, raw_path = directory / "plan.json", directory / "capture.json"
        if any(
            (directory / name).exists()
            for name in ("plan.json", "capture.json", "history.json", "report.json")
        ):
            raise ValueError("Unused evidence directory required")
        save(plan_path, plan.model_dump(mode="json"))
        code = capture_main(
            [
                "capture",
                "--oauth-file",
                args.oauth_file,
                "--schemas",
                args.schemas,
                "--schema-sha256",
                SCHEMA_SHA256,
                "--plan",
                str(plan_path),
                "--output",
                str(raw_path),
                "--timeout-seconds",
                str(policy.capture.timeout_seconds),
            ]
        )
        if not raw_path.exists():
            return code or 2
        artifact = private_json(str(raw_path))
        if "result" not in artifact:
            report, history = {"status": "CAPTURE_UNAVAILABLE", "live_enabled": False}, None
        else:
            report, history = inspect_capture(policy, plan, artifact)
        report["requested_target_session"] = str(target)
        report["capture_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if history is not None:
            save(directory / "history.json", history.model_dump(mode="json"))
        save(directory / "report.json", report)
        print(json.dumps(report, sort_keys=True))
        return 0 if history is not None else 2
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError, SchemaError):
        print(json.dumps({"status": "HISTORY_PROOF_UNAVAILABLE", "live_enabled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
