"""Native multi-session state, explicit settlement and retained boundary provenance."""

import asyncio
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from test_option_replay import KEY, settings_for, tape_for

from app.execution.restore import authority_path
from app.options.coordinator import DegenFrame
from app.options.evaluation_export import export_series
from app.options.evaluation_export_cli import ExportBoundary, ExportSource, SeriesExportRequest
from app.options.evaluation_models import EvaluationManifest, EvaluationSession
from app.options.lifecycle import OptionReceipt
from app.options.market_tape import TapeHeader, TapeRecorder, load_tape
from app.options.replay import ScriptedSettlement, run_replay_series
from app.options.replay_model import ReplayScript

SHIFT = timedelta(days=3)
LATER_KEY = "degen:" + str(int(KEY.split(":")[1]) + int(SHIFT.total_seconds()) // 300)


def later_tape(tape, root):
    def shifted(value):
        if isinstance(value, dict):
            return {
                k: v + "-later" if k == "instrument_id" else shifted(v) for k, v in value.items()
            }
        if isinstance(value, list):
            return [shifted(v) for v in value]
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}(T|$)", value):
            return (
                (date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value))
                + SHIFT
            ).isoformat()
        return value

    header = TapeHeader.model_validate(shifted(tape.header.model_dump(mode="json")))
    header = header.model_copy(update={"declared_at": tape.header.declared_at})
    with TapeRecorder(root / "later.tape", header) as recorder:
        for event in tape.events:
            recorder.append(
                DegenFrame.model_validate(shifted(event.frame.model_dump(mode="json"))),
                recorded_at=event.recorded_at + SHIFT,
                kind=event.kind,
            )
        recorder.seal()
    return load_tape(root / "later.tape")


def inputs_for(root, *, full=False, settlement=False, unknown=False, close_position=True):
    first = tape_for(root, full=full, close_position=close_position)
    later = later_tape(first, root)
    settings = settings_for(first, action="UNKNOWN" if unknown else "SELECT")
    manifest = settings.manifest.model_copy(
        update={
            "sessions": (
                settings.manifest.sessions[0],
                EvaluationSession(
                    key=later.header.session_key,
                    opens_at=later.header.opens_at,
                    closes_at=later.header.closes_at,
                    tape_hash=later.digest,
                ),
            )
        }
    )
    scripts = {
        name: ReplayScript(
            arm=script.arm,
            decisions=(
                *script.decisions,
                script.decisions[0].model_copy(
                    update={
                        "cycle_key": LATER_KEY,
                        "action": "SELECT" if name == "narrow" else "ENTER",
                    }
                ),
            ),
        )
        for name, script in (("narrow", settings.narrow), ("broad", settings.broad))
    }
    receipts = (
        tuple(
            ScriptedSettlement(
                arm=arm,
                receipt=OptionReceipt(
                    receipt_id="explicit-unsettled-sale-credit",
                    sequence=3,
                    kind="FUNDS_SETTLED",
                    occurred_at=later.header.opens_at - timedelta(hours=1),
                    cash_change="384.4",
                ),
            )
            for arm in "ABC"
        )
        if settlement
        else ()
    )
    return settings.model_copy(update={"manifest": manifest, "settlements": receipts, **scripts}), (
        first,
        later,
    )


def sources_for(root, manifest):
    return {
        s.key: {
            arm: {
                "journal": str(root / arm / "sessions" / (s.key + ".db")),
                "data_cost": ".01",
                "host_cost": ".02",
            }
            for arm in "ABC"
        }
        for s in manifest.sessions
    }


@pytest.fixture(scope="module")
def complete_series(tmp_path_factory):
    root = tmp_path_factory.mktemp("complete-series")
    settings, tapes = inputs_for(root, full=True, settlement=True)
    result = asyncio.run(run_replay_series(settings, tapes, root / "run"))
    return root, tapes, result


def test_two_full_sessions_keep_bankroll_fees_costs_and_settlement(complete_series):
    root, _, result = complete_series
    report, rows = result["report"], result["bundle"]["evidence"]
    assert report["status"] == "COMPLETE_ARITHMETIC", report
    assert report["planned_sessions"] == report["complete_paired_sessions"] == 2
    assert report["minimum_sessions_met"]
    assert report["economic_conclusion"] == "INCONCLUSIVE"
    assert len(rows) == 6
    for first, later in zip(rows[:3], rows[3:], strict=True):
        assert len(first["cycles"]) == len(later["cycles"]) == 78
        assert later["initial"] == first["closing"]
        assert Decimal(first["closing"]["cash"]) == Decimal("976.8")
        assert Decimal(later["closing"]["cash"]) == Decimal("953.6")
        assert Decimal(later["closing"]["settled_cash"]) == Decimal("569.2")
        assert Decimal(later["closing"]["fees_paid"]) == Decimal("14.4")
        assert later["receipts"][0]["sequence"] == 3
        assert [o["observation"]["fills"][0]["sequence"] for o in later["orders"]] == [4, 5]
        assert later["closing"]["position"] is None
    assert Decimal(report["totals"]["A"]["net_change"]) == Decimal("-46.46")
    assert Decimal(report["totals"]["B"]["net_change"]) == Decimal("-46.4603")
    assert report["totals"]["C"] == report["totals"]["B"]
    proofs = result["source_proof"]
    assert all(p["previous_export_hash"] is None for p in proofs[:3])
    assert all(
        later["previous_export_hash"] == first["export_hash"]
        for first, later in zip(proofs[:3], proofs[3:], strict=True)
    )
    assert (root / "run/result.json").is_file()


@pytest.fixture
def detached(complete_series, tmp_path):
    root, tapes, result = complete_series
    manifest = EvaluationManifest.model_validate(result["bundle"]["manifest"])
    sources = sources_for(root / "run", manifest)
    for session, arms in sources.items():
        for arm, source in arms.items():
            destination = tmp_path / (session + arm + ".db")
            shutil.copy2(source["journal"], destination)
            source["journal"] = str(destination)
            assert not authority_path(destination).exists()
    return manifest, tapes, sources


def test_detached_boundaries_export_without_authority_and_keep_bytes(detached):
    from pathlib import Path

    manifest, tapes, sources = detached
    before = {
        s["journal"]: Path(s["journal"]).read_bytes() for a in sources.values() for s in a.values()
    }
    result = export_series(manifest, tapes, sources)
    assert result["report"]["status"] == "COMPLETE_ARITHMETIC"
    assert all(Path(path).read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize(
    "damage", ["prefix", "owner", "old_model", "old_order", "closing", "missing", "reordered"]
)
def test_later_source_cannot_erase_or_replace_previous_history(detached, damage):
    manifest, tapes, sources = detached
    if damage == "missing":
        sources.pop(manifest.sessions[0].key)
    elif damage == "reordered":
        tapes = tuple(reversed(tapes))
    else:
        arm = "B" if damage == "old_model" else "A"
        with sqlite3.connect(sources[manifest.sessions[1].key][arm]["journal"]) as db:
            if damage == "prefix":
                db.execute(
                    "UPDATE execution_events SET occurred_at='2026-10-08T00:00:00+00:00' WHERE sequence=1"
                )
            elif damage == "owner":
                raw = json.loads(
                    db.execute("SELECT config_json FROM execution_control").fetchone()[0]
                )
                raw["venue_id"] = "replacement-owner"
                db.execute("UPDATE execution_control SET config_json=?", (json.dumps(raw),))
            elif damage == "old_model":
                db.execute("DELETE FROM execution_model_calls WHERE source_key=?", (KEY,))
            elif damage == "old_order":
                db.execute("DELETE FROM execution_orders WHERE source_key=?", (KEY,))
            else:
                raw = json.loads(
                    db.execute("SELECT ledger_json FROM execution_control").fetchone()[0]
                )
                raw["cash"] = "1000"
                db.execute("UPDATE execution_control SET ledger_json=?", (json.dumps(raw),))
    with pytest.raises(ValueError):
        export_series(manifest, tapes, sources)


def test_absent_settlement_never_becomes_spendable_cash(tmp_path):
    settings, tapes = inputs_for(tmp_path)
    result = asyncio.run(run_replay_series(settings, tapes, tmp_path / "run"))
    for first, later in zip(
        result["bundle"]["evidence"][:3], result["bundle"]["evidence"][3:], strict=True
    ):
        assert not later["receipts"]
        assert later["initial"] == first["closing"]
        assert Decimal(later["closing"]["settled_cash"]) == Decimal("184.8")
    assert result["report"]["status"] == "INCONCLUSIVE"  # Deliberately sparse tape.


def test_unknown_cost_and_halt_survive_next_session(tmp_path):
    settings, tapes = inputs_for(tmp_path, unknown=True)
    result = asyncio.run(run_replay_series(settings, tapes, tmp_path / "run"))
    first, later = result["bundle"]["evidence"][1], result["bundle"]["evidence"][4]
    assert first["calls"][0]["usage"] is None
    assert not later["calls"] and not later["orders"]
    assert later["initial"] == first["closing"]
    assert result["report"]["totals"]["B"]["net_change"] is None
    with sqlite3.connect(tmp_path / "run/B/journal.db") as db:
        assert db.execute("SELECT cost FROM execution_model_calls").fetchall() == [(None,)]
        assert db.execute("SELECT halted FROM execution_control").fetchone()[0] == 1


def test_unclosed_position_is_carried_and_never_marked_flat(tmp_path):
    settings, tapes = inputs_for(tmp_path, close_position=False)
    result = asyncio.run(run_replay_series(settings, tapes, tmp_path / "run"))
    for first, later in zip(
        result["bundle"]["evidence"][:3], result["bundle"]["evidence"][3:], strict=True
    ):
        assert later["initial"]["position"] == first["closing"]["position"]
        assert later["closing"]["position"] is not None
    assert result["report"]["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("damage", ["amount", "sequence", "time", "duplicate"])
def test_invalid_settlement_stops_without_a_completion_receipt(tmp_path, damage):
    settings, tapes = inputs_for(tmp_path, settlement=True)
    r = settings.settlements[0]
    changes = {
        "amount": {"cash_change": "1000"},
        "sequence": {"sequence": 100},
        "time": {"occurred_at": tapes[0].header.opens_at},
    }
    receipts = (
        (*settings.settlements, r)
        if damage == "duplicate"
        else (
            r.model_copy(update={"receipt": r.receipt.model_copy(update=changes[damage])}),
            *settings.settlements[1:],
        )
    )
    settings = settings.model_copy(update={"settlements": receipts})
    with pytest.raises(ValueError):
        asyncio.run(run_replay_series(settings, tapes, tmp_path / "run"))
    assert not (tmp_path / "run/result.json").exists()


def test_installed_series_export_cli(detached, tmp_path):
    manifest, tapes, sources = detached
    boundaries = []
    for session, tape in zip(manifest.sessions, tapes, strict=True):
        path = tmp_path / (session.key + ".tape")
        with TapeRecorder(path, tape.header) as recorder:
            for event in tape.events:
                recorder.append(event.frame, recorded_at=event.recorded_at, kind=event.kind)
            recorder.seal()
        boundaries.append(
            ExportBoundary(
                session_key=session.key,
                tape=str(path),
                sources=tuple(ExportSource(arm=a, **s) for a, s in sources[session.key].items()),
            )
        )
    request = tmp_path / "export.json"
    request.write_text(
        SeriesExportRequest(manifest=manifest, boundaries=tuple(boundaries)).model_dump_json()
    )
    request.chmod(0o600)
    command = [
        sys.executable,
        "-I",
        "-m",
        "app.options.evaluation_export_cli",
        "--request",
        str(request),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["report"]["complete_paired_sessions"] == 2


def test_series_replay_cli(tmp_path):
    settings, _ = inputs_for(tmp_path, settlement=True)
    request = tmp_path / "replay.json"
    request.write_text(
        json.dumps(
            {
                "settings": settings.model_dump(mode="json"),
                "tapes": [str(tmp_path / "common.tape"), str(tmp_path / "later.tape")],
            }
        )
    )
    request.chmod(0o600)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.replay_cli",
            "--request",
            str(request),
            "--output",
            str(tmp_path / "run"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["planned_sessions"] == 2
    output = json.loads((tmp_path / "run/result.json").read_text())
    assert output["bundle"]["evidence"][3]["receipts"][0]["cash_change"] == "384.4"


def test_interrupted_rollover_keeps_first_boundary_without_authority(tmp_path, monkeypatch):
    from app.options.replay import _ArmReplay

    settings, tapes = inputs_for(tmp_path)
    original = _ArmReplay.run

    async def interrupted(owner):
        if owner.tape.header.session_key == tapes[1].header.session_key:
            raise asyncio.CancelledError
        return await original(owner)

    monkeypatch.setattr(_ArmReplay, "run", interrupted)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_replay_series(settings, tapes, tmp_path / "run"))
    boundary = tmp_path / "run/A/sessions" / (tapes[0].header.session_key + ".db")
    assert boundary.is_file() and not authority_path(boundary).exists()
    assert not (tmp_path / "run/result.json").exists()
    with sqlite3.connect(boundary) as db:
        assert Decimal(
            json.loads(db.execute("SELECT ledger_json FROM execution_control").fetchone()[0])[
                "cash"
            ]
        ) == Decimal("976.8")


def test_series_size_limit_stops_loading_more_tapes(tmp_path, monkeypatch):
    from app.options import market_tape

    _, tapes = inputs_for(tmp_path)
    size = len(tapes[0].model_dump_json().encode())
    monkeypatch.setattr(market_tape, "MAX_TAPE_BYTES", size)
    yielded = []

    def values():
        for _ in range(60):
            yielded.append(1)
            yield tapes[0]

    with pytest.raises(ValueError, match="Combined"):
        market_tape.validate_tape_series(values())
    assert len(yielded) == 3
