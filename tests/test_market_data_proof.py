"""Bounded host proof: fresh clocks are evidence, never entitlement or fill permission."""

import copy
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_robinhood_read_mapping import envelope, equity, option

from app.options.read_capture import CaptureResult
from app.options.read_gateway import CapturePlan, OptionReadGateway, ReadSchemas
from app.web.mixed_view import price_text

SPEC = importlib.util.spec_from_file_location(
    "market_data_proof", Path(__file__).resolve().parents[1] / "scripts/market-data-proof.py"
)
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)
AT = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)


@pytest.fixture
def schemas():
    return ReadSchemas.model_validate_json(
        (Path(__file__).parent / "fixtures/robinhood_read_schemas.json").read_bytes()
    )


def artifact(schemas, plan, at):
    observations = []
    for call in plan.calls:
        if call.tool == "get_equity_quotes":
            rows = []
            for symbol in call.arguments["symbols"]:
                row = equity(symbol)
                for key in ("venue_bid_time", "venue_ask_time", "venue_last_trade_time"):
                    row[key] = at.isoformat()
                rows.append({"quote": row})
        else:
            rows = []
            for identity in call.arguments["instrument_ids"]:
                row = option()
                row.update(instrument_id=identity, updated_at=at.isoformat())
                rows.append({"quote": row})
        observations.append(
            {"tool": call.tool, "label": call.label, "completed": True, "raw": envelope(rows)}
        )
    result = CaptureResult(
        request_id="a" * 32,
        policy_sha256="b" * 64,
        operation="CAPTURE",
        started_at=at,
        collected_at=at + timedelta(seconds=2),
        elapsed_seconds=2,
        status="COMPLETE",
        schemas=schemas,
        plan=plan,
        observations=observations,
    )
    return {"status": "COMPLETE", "result": result.model_dump(mode="json")}


def test_three_samples_revalidate_pinned_schema_and_clocks_without_authority(schemas):
    plan = proof.plan_at(AT)
    gateway = OptionReadGateway(None)
    gateway.schemas = schemas
    gateway.validate_plan(plan, schemas)
    samples = [
        proof.inspect_capture(artifact(schemas, plan, AT + timedelta(seconds=20 * i)), plan)
        for i in range(3)
    ]
    report = proof.summarize(samples, ["REGULAR"] * 3)
    assert report["status"] == "FRESH_ADVANCING_QUOTES"
    assert report["regular_session_quote_proof"]
    assert len(report["subjects"]) == 4
    assert not report["paper_trading_ready"] and not report["execution_authority"]
    for row in report["subjects"]:
        assert row["latest"]["entitlement"] == "UNKNOWN"
        assert row["latest"]["age_seconds_at_capture"] == 2
        if row["latest"]["asset"] == "STOCK":
            assert row["latest"]["bid_size"] is None


def test_stale_repeat_premarket_and_regression_do_not_pass(schemas):
    plan = proof.plan_at(AT)
    sample = proof.inspect_capture(artifact(schemas, plan, AT), plan)
    assert not proof.summarize([sample] * 3, ["REGULAR"] * 3)["regular_session_quote_proof"]
    later = proof.inspect_capture(artifact(schemas, plan, AT + timedelta(seconds=20)), plan)
    assert not proof.summarize([sample, later, later], ["OUTSIDE_REGULAR"] * 3)[
        "regular_session_quote_proof"
    ]
    report = proof.summarize([sample, later, sample], ["REGULAR"] * 3)
    assert all(r["source_clock_regressed"] for r in report["subjects"])
    stale = artifact(schemas, plan, AT)
    stale["result"]["collected_at"] = (AT + timedelta(hours=1)).isoformat()
    assert not any(r["fresh_book"] for r in proof.inspect_capture(stale, plan))


def test_future_crossed_missing_or_changed_identity_is_not_usable(schemas):
    plan = proof.plan_at(AT)
    original = artifact(schemas, plan, AT)
    for key, value in [
        ("venue_ask_time", (AT + timedelta(seconds=10)).isoformat()),
        ("bid_price", "9999"),
    ]:
        changed = copy.deepcopy(original)
        changed["result"]["observations"][0]["raw"]["structuredContent"]["data"]["results"][0][
            "quote"
        ][key] = value
        assert not proof.inspect_capture(changed, plan)[0]["fresh_book"]
    changed = copy.deepcopy(original)
    changed["result"]["observations"][0]["raw"]["structuredContent"]["data"]["results"].pop()
    with pytest.raises(ValueError, match="coverage"):
        proof.inspect_capture(changed, plan)
    changed = copy.deepcopy(original)
    changed["result"]["observations"][0]["label"] = "other"
    with pytest.raises(ValueError, match="receipt"):
        proof.inspect_capture(changed, plan)


def test_bounded_runner_retains_three_captures_and_never_reuses_output(tmp_path, schemas):
    directory = tmp_path / "proof"
    directory.mkdir(mode=0o700)
    calls, pauses = [], []

    def capture(args):
        calls.append(args)
        plan = CapturePlan.model_validate_json(Path(args[args.index("--plan") + 1]).read_text())
        sample = artifact(schemas, plan, AT + timedelta(seconds=len(calls) * 20))
        Path(args[args.index("--output") + 1]).write_text(json.dumps(sample))
        return 0

    report = proof.run(
        directory,
        "/unused/schemas",
        "/unused/oauth",
        clock=lambda: AT,
        capture=capture,
        pause=pauses.append,
        calendar=SimpleNamespace(current_window=lambda _: True),
    )
    assert len(calls) == 3 and pauses == [20, 20]
    assert report["regular_session_quote_proof"]
    assert len(report["artifacts"]) == 3
    assert (directory / "report.json").is_file()
    with pytest.raises(ValueError, match="never overwrite"):
        proof.run(directory, "/unused/schemas", "/unused/oauth")


def test_capture_failure_stops_without_retry_or_secret_in_report(tmp_path):
    directory = tmp_path / "proof"
    directory.mkdir(mode=0o700)
    calls = []

    def fail(args):
        calls.append(args)
        return 1

    report = proof.run(
        directory,
        "/unused/schemas",
        "/unused/SECRET",
        clock=lambda: AT,
        capture=fail,
        pause=lambda _: pytest.fail("No retry"),
        calendar=SimpleNamespace(current_window=lambda _: None),
    )
    assert len(calls) == 1 and report["samples_completed"] == 0
    assert report["failures"][0]["reason"] == "CAPTURE_FAILED"
    assert "SECRET" not in json.dumps(report)


def test_expired_fixed_option_samples_are_not_requested():
    plan = proof.plan_at(AT + timedelta(days=1))
    assert not plan.instrument_ids
    assert [call.tool for call in plan.calls] == ["get_equity_quotes"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("599.940000000000", "599.94"),
        ("601.2", "601.20"),
        ("599.9401250000", "599.940125"),
        ("0.00031", "0.00031"),
        (None, "Unavailable"),
    ],
)
def test_price_padding_is_removed_without_losing_exact_precision(value, expected):
    assert price_text(value) == expected
