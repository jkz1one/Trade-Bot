"""No network: host proof exercises the same existing native history mapper."""

import asyncio
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_feed import PREOPEN, policy, reader

spec = importlib.util.spec_from_file_location(
    "history_proof", Path(__file__).parents[1] / "scripts/swing-history-proof.py"
)
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


def artifact(schemas, *, bad=None):
    p = policy()
    _, plan = proof.plan_for(p, PREOPEN)
    result = asyncio.run(
        reader(PREOPEN, [], bad_history=bad)(p.capture, schemas=schemas, plan=plan)
    )
    return (
        p,
        plan,
        {
            "operation": "capture",
            "status": result.status,
            "execution_authority": False,
            "result": result.model_dump(mode="json"),
        },
    )


def test_maps_exact_original_histories(schemas):
    p, plan, raw = artifact(schemas)
    report, history = proof.inspect_capture(p, plan, raw)
    assert report["status"] == "HISTORY_MAPPED"
    assert report["daily_bars"] == {"SPY": 56, "QQQ": 56}
    assert report["hourly_bars"] == {"SPY": 54, "QQQ": 54}
    assert report["completed_reads"] == 4
    assert all(h.entitlement == "UNKNOWN" for h in history.daily)
    assert not report["trading_ready"] and not report["state_modified"]


@pytest.mark.parametrize(
    "bad,status", [("gap", "HISTORY_MAPPING_UNAVAILABLE"), ("transport", "HISTORY_UNAVAILABLE")]
)
def test_failed_capture_keeps_diagnostics(schemas, bad, status):
    p, plan, raw = artifact(schemas, bad=bad)
    report, history = proof.inspect_capture(p, plan, raw)
    assert report["status"] == status and history is None
    assert report["diagnostics"]


def test_mid_session_has_no_plan():
    assert proof.plan_for(policy(), datetime(2026, 10, 27, 18, tzinfo=UTC)) == (None, None)


def test_after_close_prepares_next_session():
    target, plan = proof.plan_for(policy(), datetime(2026, 10, 27, 20, 20, tzinfo=UTC))
    assert str(target) == "2026-10-28" and len(plan.calls) == 4
    assert all(c.arguments["end_time"] == "2026-10-27T20:00:00+00:00" for c in plan.calls)


def test_wrong_receipt_rejected(schemas):
    p, plan, raw = artifact(schemas)
    raw["result"]["observations"][0]["label"] = "wrong"
    with pytest.raises(ValueError):
        proof.inspect_capture(p, plan, raw)


@pytest.mark.parametrize("run", [False, True])
def test_cli_no_auth_for_review_and_preserves_capture_for_run(
    schemas, tmp_path, monkeypatch, capsys, run
):
    p, _plan, raw = artifact(schemas)
    tmp_path.chmod(0o700)
    file = tmp_path / "policy.json"
    file.write_text(p.model_dump_json())
    file.chmod(0o600)
    monkeypatch.setattr(proof, "utc_now", lambda: PREOPEN)
    calls = []

    def fake_capture(args):
        calls.append(args)
        proof.save(Path(args[args.index("--output") + 1]), raw)
        return 0

    monkeypatch.setattr(proof, "capture_main", fake_capture)
    args = [
        "--directory",
        str(tmp_path),
        "--policy",
        str(file),
        "--schemas",
        "/absent/schemas",
        "--oauth-file",
        "/absent/oauth",
    ]
    if run:
        args.append("--run")
    assert proof.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(calls) == int(run)
    if run:
        assert report["status"] == "HISTORY_MAPPED"
        original = (tmp_path / "capture.json").read_bytes()
        assert proof.main(args) == 2
        assert (tmp_path / "capture.json").read_bytes() == original
        assert len(calls) == 1
    else:
        assert report["status"] == "PLAN_ONLY"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["policy.json"]
