"""Independent native virtual clocks, later quote fills and automatic export."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame
from test_option_admission import END, inputs
from test_option_entry_reasoning import packet_for
from test_option_evaluation import OPEN, bundle_for
from test_option_execution import quote_at, underlying_at
from test_option_market_tape import header_for

from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenFrame
from app.options.market_tape import TapeRecorder, load_tape
from app.options.replay import ReplaySettings, run_replay
from app.options.replay_model import ReplayScript, ScriptedDecision

KEY = "degen:" + str(int(AT.timestamp()) // 300)


def settings_for(tape, *, delay=2, action="SELECT"):
    b = bundle_for()
    manifest = b.manifest.model_copy(
        update={"sessions": (b.manifest.sessions[0].model_copy(update={"tape_hash": tape.digest}),)}
    )
    return ReplaySettings(
        manifest=manifest,
        judgment_limits=JudgmentLimits(),
        entry_policy=packet_for().policy,
        narrow=ReplayScript(
            arm="B",
            decisions=(ScriptedDecision(cycle_key=KEY, delay_seconds=delay, action=action),),
        ),
        broad=ReplayScript(
            arm="C",
            decisions=(
                ScriptedDecision(
                    cycle_key=KEY,
                    delay_seconds=1,
                    action="ENTER",
                    condition="NOW",
                    underlying_invalidation="600",
                    underlying_target="602",
                    horizon_seconds=600,
                ),
            ),
        ),
        data_cost_per_arm=".01",
        host_cost_per_arm=".02",
    )


def tape_for(
    root,
    *,
    full=False,
    close_position=True,
    invalidate_at=4,
    first_size=None,
    fill_events=True,
    second_receipt=False,
):
    b = bundle_for()
    with TapeRecorder(root / "common.tape", header_for(b)) as recorder:
        recorder.append(
            DegenFrame(underlyings=(b.benchmarks[0].start,)), recorded_at=OPEN, kind="MARKET"
        )
        for n in range(78):
            at = OPEN + timedelta(minutes=5 * n)
            if not full and at not in (AT, AT + timedelta(minutes=5)):
                continue
            base = frame()
            f = (
                base
                if at == AT
                else DegenFrame(
                    histories=(
                        base.histories[0].model_copy(
                            update={"source_at": at, "received_at": at, "bars": ()}
                        ),
                    ),
                    underlyings=(underlying_at(inputs(), at),),
                )
            )
            recorder.append(f, recorded_at=at)
            if at == AT and fill_events:
                for second in range(1, 6 if close_position else 4):
                    when = AT + timedelta(seconds=second)
                    q = quote_at(inputs(), when)
                    if second == 1 and first_size is not None:
                        q = q.model_copy(update={"ask_size": first_size})
                    u = underlying_at(
                        inputs(),
                        when,
                        **(
                            {"bid": Decimal(590), "ask": Decimal("590.01")}
                            if second >= invalidate_at
                            else {"bid": Decimal("600.8"), "ask": Decimal("600.81")}
                        ),
                    )
                    recorder.append(
                        DegenFrame(quotes=(q,), underlyings=(u,)), recorded_at=when, kind="MARKET"
                    )
                    if second_receipt and second == 2:
                        changed = underlying_at(
                            inputs(), when, bid=Decimal(590), ask=Decimal("590.01")
                        )
                        recorder.append(
                            DegenFrame(underlyings=(changed,)), recorded_at=when, kind="MARKET"
                        )
        recorder.append(
            DegenFrame(underlyings=(b.benchmarks[0].end,)), recorded_at=END, kind="MARKET"
        )
        recorder.seal()
    return load_tape(root / "common.tape")


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("replay-complete")
    tape = tape_for(root, full=True)
    result = asyncio.run(run_replay(settings_for(tape), tape, root / "run"))
    return root, tape, result


def test_independent_delays_native_fills_and_automatic_accounting(completed):
    root, tape, result = completed
    assert result["report"]["status"] == "COMPLETE_ARITHMETIC", result["report"]
    assert result["report"]["recorded_market_verified"]
    assert result["model_evidence"] == "SCRIPTED"
    assert result["report"]["economic_conclusion"] == "INCONCLUSIVE"
    arms = result["bundle"]["evidence"]
    assert [len(a["cycles"]) for a in arms] == [78, 78, 78]
    for arm, second in zip(arms, [1, 3, 2], strict=True):
        assert len(arm["orders"]) == 2, arm
        buy, sell = arm["orders"]
        assert buy["observation"]["fills"][0]["occurred_at"] == (
            AT + timedelta(seconds=second)
        ).isoformat().replace("+00:00", "Z")
        assert sell["intent"]["side"] == "SELL"
        assert sell["observation"]["status"] == "FILLED"
        assert arm["closing"]["position"] is None
    assert Decimal(result["report"]["sessions"][0]["arms"]["B"]["known_model_cost"]) > 0
    assert (root / "run/result.json").is_file()
    assert json.loads((root / "run/manifest.json").read_text()) == result["bundle"]["manifest"]
    assert all(not (root / "run" / arm / "private-model.key").exists() for arm in "ABC")
    with pytest.raises(FileExistsError):
        asyncio.run(run_replay(settings_for(tape), tape, root / "run"))


@pytest.mark.parametrize(
    "delay,action", [(30, "SELECT"), (0, "HOLD"), (1, "UNKNOWN"), (301, "SELECT")]
)
def test_late_hold_and_unknown_never_create_a_free_or_early_entry(tmp_path, delay, action):
    tape = tape_for(tmp_path)
    result = asyncio.run(
        run_replay(settings_for(tape, delay=delay, action=action), tape, tmp_path / "run")
    )
    b = result["bundle"]["evidence"][1]
    assert b["orders"] == []
    assert len(b["calls"]) == 1
    assert (b["calls"][0]["usage"] is None) == (action == "UNKNOWN")
    assert result["report"]["status"] == "INCONCLUSIVE"
    assert not result["live_enabled"]
    if delay == 301:
        assert result["scheduling"]["B"]["skipped_cycles"] == [
            "degen:" + str(int(AT.timestamp()) // 300 + 1)
        ]


def test_missing_response_stays_unknown(tmp_path):
    tape = tape_for(tmp_path)
    settings = settings_for(tape).model_copy(update={"narrow": ReplayScript(arm="B", decisions=())})
    result = asyncio.run(run_replay(settings, tape, tmp_path / "run"))
    b = result["bundle"]["evidence"][1]
    assert b["calls"][0]["usage"] is None
    assert not b["orders"]


def test_missing_exit_quotes_retains_exposure_and_inconclusive_report(tmp_path):
    tape = tape_for(tmp_path, close_position=False)
    result = asyncio.run(run_replay(settings_for(tape), tape, tmp_path / "run"))
    assert all(a["closing"]["position"] is not None for a in result["bundle"]["evidence"])
    assert result["report"]["status"] == "INCONCLUSIVE"
    assert all(t["net_change"] is None for t in result["report"]["totals"].values())


def test_foreign_tape_rejected_before_admission(tmp_path):
    tape = tape_for(tmp_path)
    settings = settings_for(tape)
    settings = settings.model_copy(
        update={"manifest": settings.manifest.model_copy(update={"experiment_id": "foreign"})}
    )
    with pytest.raises(ValueError):
        asyncio.run(run_replay(settings, tape, tmp_path / "run"))
    assert not (tmp_path / "run").exists()


def test_market_change_during_reasoning_rejects_entry(tmp_path):
    tape = tape_for(tmp_path, invalidate_at=2)
    settings = settings_for(tape)
    decision = settings.broad.decisions[0].model_copy(update={"delay_seconds": 3})
    settings = settings.model_copy(update={"broad": ReplayScript(arm="C", decisions=(decision,))})
    result = asyncio.run(run_replay(settings, tape, tmp_path / "run"))
    assert all(not a["orders"] for a in result["bundle"]["evidence"][1:])
    assert all(a["calls"][0]["usage"] is not None for a in result["bundle"]["evidence"][1:])


def test_whole_partial_fills_do_not_reuse_observed_size(tmp_path):
    tape = tape_for(tmp_path, first_size=1)
    result = asyncio.run(run_replay(settings_for(tape), tape, tmp_path / "run"))
    order = result["bundle"]["evidence"][0]["orders"][0]
    fills = order["observation"]["fills"]
    assert [f["quantity"] for f in fills] == [1, order["intent"]["quantity"] - 1]
    assert fills[0]["quote_hash"] != fills[1]["quote_hash"]
    assert order["observation"]["status"] == "FILLED"


def test_unfilled_day_orders_expire_without_inventing_trades(tmp_path):
    tape = tape_for(tmp_path, fill_events=False)
    result = asyncio.run(run_replay(settings_for(tape), tape, tmp_path / "run"))
    for arm in result["bundle"]["evidence"]:
        assert len(arm["orders"]) == 1
        assert arm["orders"][0]["observation"]["status"] == "EXPIRED"
        assert not arm["orders"][0]["observation"]["fills"]
        assert arm["closing"]["position"] is None


def test_interrupt_retains_admission_and_unknown_call_without_resume(tmp_path, monkeypatch):
    from app.options.replay import _ArmReplay

    tape = tape_for(tmp_path)
    original = _ArmReplay.observe

    async def interrupted(owner, at, event=None):
        if owner.c.replay_model is not None and owner.c.replay_model.pending:
            raise asyncio.CancelledError
        return await original(owner, at, event)

    monkeypatch.setattr(_ArmReplay, "observe", interrupted)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_replay(settings_for(tape), tape, tmp_path / "run"))
    assert (tmp_path / "run/admission.json").is_file()
    assert not (tmp_path / "run/result.json").exists()
    with sqlite3.connect(tmp_path / "run/B/journal.db") as db:
        assert db.execute("SELECT cost FROM execution_model_calls").fetchall() == [(None,)]
        assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 0
    with pytest.raises(FileExistsError):
        asyncio.run(run_replay(settings_for(tape), tape, tmp_path / "run"))


def test_installed_cli_retains_result_and_rejects_reuse(tmp_path):
    tape = tape_for(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "settings": settings_for(tape).model_dump(mode="json"),
                "tape": str(tmp_path / "common.tape"),
            }
        )
    )
    request.chmod(0o600)
    args = [
        sys.executable,
        "-I",
        "-m",
        "app.options.replay_cli",
        "--request",
        str(request),
        "--output",
        str(tmp_path / "run"),
    ]
    completed = subprocess.run(args, capture_output=True, text=True, check=False, timeout=90)
    assert completed.returncode == 1, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "INCONCLUSIVE"
    assert report["execution_authority"] is False
    again = subprocess.run(args, capture_output=True, text=True, check=False, timeout=10)
    assert again.returncode == 2
    assert json.loads(again.stdout)["reason"] == "REPLAY_UNAVAILABLE"
    request.chmod(0o644)
    denied = subprocess.run(
        args[:-1] + [str(tmp_path / "forbidden")],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert denied.returncode == 2
    assert not (tmp_path / "forbidden").exists()


def test_all_equal_time_receipts_precede_model_completion(tmp_path):
    tape = tape_for(tmp_path, second_receipt=True)
    result = asyncio.run(run_replay(settings_for(tape), tape, tmp_path / "run"))
    assert not result["bundle"]["evidence"][1]["orders"]
    assert result["bundle"]["evidence"][1]["calls"][0]["usage"] is not None
