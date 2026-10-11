"""Sealed shared market observations, point-in-time replay and paired source checks."""

import json
import os
import signal
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame, policies
from test_option_admission import NOW
from test_option_evaluation import KEY, OPEN, bundle_for, change_arm, round_trip

from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.market_tape import (
    RecordedTape,
    TapeHeader,
    TapeRecorder,
    load_tape,
    replay_shortlist,
)


def header_for(bundle=None):
    b = bundle or bundle_for()
    s = b.manifest.sessions[0]
    setup, selection = policies()
    return TapeHeader(
        experiment_id=b.manifest.experiment_id,
        session_key=s.key,
        declared_at=b.manifest.declared_at,
        opens_at=s.opens_at,
        closes_at=s.closes_at,
        limits=b.manifest.arms[0].limits,
        setup=setup,
        selection=selection,
    )


def record_bundle(
    tmp_path, b=None, *, omit_cycle=False, omit_fill=False, late_fill=False, late_cycle=False
):
    b = b or bundle_for()
    h = header_for(b)
    events = []
    for c in b.evidence[0].cycles:
        at = OPEN + timedelta(seconds=(int(c.key.split(":")[1]) * 300 - int(OPEN.timestamp())))
        if omit_cycle and c.key == KEY:
            continue
        if late_cycle and c.key == KEY:
            at += timedelta(seconds=1)
        events.append((at, "CYCLE", DegenFrame()))
    for a in b.evidence:
        for order in a.orders:
            for f in order.observation.fills if order.observation else ():
                if not omit_fill:
                    at = f.occurred_at + (timedelta(seconds=1) if late_fill else timedelta())
                    events.append((at, "MARKET", DegenFrame(quotes=(f.quote,))))
    for q in (b.benchmarks[0].start, b.benchmarks[0].end):
        events.append((q.received_at, "MARKET", DegenFrame(underlyings=(q,))))
    path = tmp_path / "common.tape"
    tmp_path.chmod(0o700)
    with TapeRecorder(path, h) as recorder:
        for at, kind, f in sorted(events, key=lambda e: e[0]):
            recorder.append(f, recorded_at=at, kind=kind)
        digest = recorder.seal()
    tape = load_tape(path)
    assert tape.digest == digest
    frames = {e.cycle_key: fingerprint(e.frame) for e in tape.events if e.kind == "CYCLE"}
    evidence = tuple(
        a.model_copy(
            update={
                "tape_hash": digest,
                "cycles": tuple(
                    c.model_copy(update={"frame_hash": frames.get(c.key, c.frame_hash)})
                    for c in a.cycles
                ),
            }
        )
        for a in b.evidence
    )
    m = b.manifest.model_copy(
        update={"sessions": (b.manifest.sessions[0].model_copy(update={"tape_hash": digest}),)}
    )
    return b.model_copy(update={"manifest": m, "evidence": evidence}), tape, path


def test_sealed_recording_binds_complete_comparison_and_no_authority(tmp_path):
    b, tape, path = record_bundle(tmp_path)
    before = path.read_bytes()
    r = evaluate(b, tapes=(tape,))
    assert r["status"] == "COMPLETE_ARITHMETIC"
    assert r["recorded_market_verified"]
    assert r["market_evidence"] == "SEALED_LOCAL_FIXTURE_TAPES"
    assert r["economic_conclusion"] == "INCONCLUSIVE"
    assert not r["execution_authority"] and not r["live_enabled"]
    assert r["totals"] == evaluate(b)["totals"]
    assert not evaluate(b)["recorded_market_verified"]
    assert path.read_bytes() == before


def test_native_fills_require_actual_subsequent_tape_quotes(tmp_path):
    start, end, orders = round_trip(tmp_path / "engine")
    b = change_arm(bundle_for(), 0, initial=start, closing=end, orders=orders)
    b, tape, _ = record_bundle(tmp_path, b)
    r = evaluate(b, tapes=(tape,))
    assert r["status"] == "COMPLETE_ARITHMETIC"
    assert Decimal(r["sessions"][0]["arms"]["A"]["venue_fees"]) == Decimal("7.2")


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("missing", "SEALED_MARKET_TAPE_MISSING"),
        ("hash", "RECORDED_TAPE_BINDING_MISMATCH"),
        ("experiment", "RECORDED_TAPE_BINDING_MISMATCH"),
        ("limits", "RECORDED_TAPE_BINDING_MISMATCH"),
        ("frame", "CYCLE_FRAME_NOT_RECORDED"),
        ("spy", "SPY_BOUNDARY_NOT_RECORDED"),
        ("omit_cycle", "RECORDED_CYCLE_COVERAGE_INCOMPLETE"),
        ("late_cycle", "MODEL_STARTED_BEFORE_RECORDED_INPUT"),
    ],
)
def test_missing_or_changed_recording_suppresses_totals(tmp_path, damage, reason):
    b, tape, _ = record_bundle(
        tmp_path, **({damage: True} if damage in {"omit_cycle", "late_cycle"} else {})
    )
    tapes = (tape,)
    if damage == "missing":
        tapes = ()
    elif damage in {"hash", "experiment"}:
        update = (
            {"experiment_id": "other"}
            if damage == "experiment"
            else {"sessions": (b.manifest.sessions[0].model_copy(update={"tape_hash": "f" * 64}),)}
        )
        b = b.model_copy(update={"manifest": b.manifest.model_copy(update=update)})
    elif damage == "limits":
        arms = tuple(
            a.model_copy(
                update={"limits": a.limits.model_copy(update={"option_source": "other-feed"})}
            )
            for a in b.manifest.arms
        )
        b = b.model_copy(update={"manifest": b.manifest.model_copy(update={"arms": arms})})
    elif damage == "frame":
        cycles = list(b.evidence[1].cycles)
        cycles[0] = cycles[0].model_copy(update={"frame_hash": "f" * 64})
        b = change_arm(b, cycles=tuple(cycles))
    elif damage == "spy":
        q = b.benchmarks[0].end.model_copy(update={"bid": "607", "ask": "607"})
        b = b.model_copy(update={"benchmarks": (b.benchmarks[0].model_copy(update={"end": q}),)})
    r = evaluate(b, tapes=tapes)
    assert r["status"] == "INCONCLUSIVE"
    assert reason in r["sessions"][0]["reasons"]
    assert r["totals"]["A"]["net_change"] is None
    assert r["mean_paired_net_difference"]["B"] is None
    assert r["planned_sessions"] == 1


@pytest.mark.parametrize("damage", ["omit_fill", "late_fill"])
def test_unrecorded_or_late_quote_cannot_backfill_a_fill(tmp_path, damage):
    start, end, orders = round_trip(tmp_path / "engine")
    b = change_arm(bundle_for(), 0, initial=start, closing=end, orders=orders)
    b, tape, _ = record_bundle(tmp_path, b, **{damage: True})
    r = evaluate(b, tapes=(tape,))
    assert "FILL_QUOTE_NOT_RECORDED_BY_FILL_TIME" in r["sessions"][0]["reasons"]
    assert r["totals"]["A"]["net_change"] is None


def test_shortlist_replays_existing_scanner_at_recorded_time(tmp_path):
    h, f = header_for(), frame()
    with TapeRecorder(tmp_path / "tape", h) as recorder:
        e = recorder.append(f, recorded_at=AT)
        recorder.append(
            DegenFrame(quotes=f.quotes), recorded_at=AT + timedelta(seconds=2), kind="MARKET"
        )
        recorder.seal()
    tape = load_tape(tmp_path / "tape")
    with pytest.raises(ValueError, match="not available"):
        replay_shortlist(tape, e.cycle_key, as_of=AT - timedelta(microseconds=1))
    r = replay_shortlist(tape, e.cycle_key, as_of=AT)
    assert r == replay_shortlist(tape, e.cycle_key, as_of=AT + timedelta(minutes=10))
    assert r["missing"] == []
    assert any(s["status"] == "CONFIRMED" for s in r["scans"][0]["observations"])
    assert r["plans"][0]["instruments"] == [f.quotes[0].instrument.model_dump(mode="json")]
    assert len(tape.available(AT)) == 1
    assert len(tape.available(AT + timedelta(seconds=2))) == 2


def test_empty_cycle_is_retained_and_does_not_borrow_later_history(tmp_path):
    with TapeRecorder(tmp_path / "tape", header_for()) as recorder:
        e = recorder.append(DegenFrame(), recorded_at=AT - timedelta(minutes=5))
        recorder.append(frame(), recorded_at=AT)
        recorder.seal()
    r = replay_shortlist(load_tape(tmp_path / "tape"), e.cycle_key, as_of=AT)
    assert r["scans"] == [] and r["plans"] == []
    assert r["missing"] == ["SPY:HISTORY_MISSING"]


@pytest.mark.parametrize(
    "damage",
    [
        "future_quote",
        "reversed_receipt",
        "future_bar",
        "foreign_source",
        "foreign_symbol",
        "duplicate_quote",
        "future_metadata",
        "duplicate_metadata",
        "market_history",
    ],
)
def test_unavailable_or_ambiguous_inputs_rejected_before_append(tmp_path, damage):
    f = frame()
    if damage in {"future_quote", "reversed_receipt", "foreign_source", "duplicate_quote"}:
        q = f.quotes[0]
        changes = {
            "future_quote": {"received_at": AT + timedelta(seconds=1)},
            "reversed_receipt": {"source_at": AT + timedelta(seconds=1)},
            "foreign_source": {"source": "foreign"},
            "duplicate_quote": {},
        }[damage]
        qs = (q, q) if damage == "duplicate_quote" else (q.model_copy(update=changes),)
        f = f.model_copy(update={"quotes": qs})
    elif damage == "future_bar":
        h = f.histories[0]
        bars = (*h.bars, h.bars[-1].model_copy(update={"begins_at": AT}))
        f = f.model_copy(update={"histories": (h.model_copy(update={"bars": bars}),)})
    elif damage == "foreign_symbol":
        f = f.model_copy(
            update={"underlyings": (f.underlyings[0].model_copy(update={"symbol": "QQQ"}),)}
        )
    elif damage in {"future_metadata", "duplicate_metadata"}:
        i = f.inventories[0]
        contracts = (
            (i.contracts[0], i.contracts[0])
            if damage == "duplicate_metadata"
            else (i.contracts[0].model_copy(update={"received_at": AT + timedelta(seconds=1)}),)
        )
        f = f.model_copy(update={"inventories": (i.model_copy(update={"contracts": contracts}),)})
    path = tmp_path / "tape"
    with TapeRecorder(path, header_for()) as recorder:
        before = path.read_bytes()
        with pytest.raises(ValueError):
            recorder.append(
                f, recorded_at=AT, kind="MARKET" if damage == "market_history" else "CYCLE"
            )
        assert path.read_bytes() == before


@pytest.mark.parametrize(
    "damage", ["duplicate_cycle", "regressing", "closed_cycle", "outside", "naive"]
)
def test_recording_sequence_and_session_guards(tmp_path, damage):
    h = header_for()
    with TapeRecorder(tmp_path / "tape", h) as recorder:
        recorder.append(DegenFrame(), recorded_at=AT)
        at = {
            "duplicate_cycle": AT + timedelta(seconds=1),
            "regressing": AT - timedelta(minutes=5),
            "closed_cycle": h.closes_at,
            "outside": h.closes_at + timedelta(seconds=6),
            "naive": AT.replace(tzinfo=None),
        }[damage]
        with pytest.raises(ValueError):
            recorder.append(DegenFrame(), recorded_at=at)


@pytest.mark.parametrize("damage", ["truncate", "remove", "reorder", "change", "seal", "append"])
def test_seal_and_hash_chain_reject_changed_artifact(tmp_path, damage):
    _, _, path = record_bundle(tmp_path)
    lines = path.read_bytes().splitlines(keepends=True)
    if damage == "truncate":
        lines[-1] = lines[-1][:-1]
    elif damage == "remove":
        del lines[2]
    elif damage == "reorder":
        lines[2], lines[3] = lines[3], lines[2]
    elif damage == "change":
        row = json.loads(lines[2])
        row["value"]["recorded_at"] = NOW.isoformat()
        lines[2] = json.dumps(row).encode() + b"\n"
    elif damage == "seal":
        row = json.loads(lines[-1])
        row["value"]["last_hash"] = "f" * 64
        lines[-1] = json.dumps(row).encode() + b"\n"
    else:
        lines.append(lines[2])
    path.write_bytes(b"".join(lines))
    with pytest.raises(ValueError):
        load_tape(path)


def test_create_only_and_no_implicit_seal_or_resume(tmp_path):
    p = tmp_path / "tape"
    with TapeRecorder(p, header_for()) as recorder:
        recorder.append(DegenFrame(), recorded_at=AT)
    original = p.read_bytes()
    with pytest.raises(ValueError, match="Sealed tape"):
        load_tape(p)
    with pytest.raises(FileExistsError):
        TapeRecorder(p, header_for())
    assert p.read_bytes() == original
    with pytest.raises(ValueError, match="closed"):
        recorder.seal()


def test_sigkill_retains_durable_unsealed_prefix(tmp_path):
    header = tmp_path / "header.json"
    header.write_text(header_for().model_dump_json())
    script = """
import sys, signal
from pathlib import Path
from app.options.market_tape import TapeHeader, TapeRecorder
from app.options.coordinator import DegenFrame
h=TapeHeader.model_validate_json(Path(sys.argv[1]).read_bytes())
r=TapeRecorder(sys.argv[2],h)
r.append(DegenFrame(),recorded_at=h.opens_at)
print('durable',flush=True)
signal.pause()
"""
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", script, str(header), str(tmp_path / "tape")],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        import select

        assert select.select([child.stdout], [], [], 10)[0]
        assert child.stdout.readline().strip() == "durable"
        os.kill(child.pid, signal.SIGKILL)
        assert child.wait(timeout=10) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stdout.close()
    path = tmp_path / "tape"
    assert len(path.read_bytes().splitlines()) == 2
    with pytest.raises(ValueError, match="Sealed tape"):
        load_tape(path)


def test_write_failure_cannot_be_followed_by_seal(tmp_path, monkeypatch):
    import app.options.market_tape as module

    with TapeRecorder(tmp_path / "tape", header_for()) as recorder:
        original = module.os.write

        def broken(fd, data):
            original(fd, data[:8])
            raise OSError("interrupted")

        monkeypatch.setattr(module.os, "write", broken)
        with pytest.raises(OSError):
            recorder.append(DegenFrame(), recorded_at=AT)
        monkeypatch.setattr(module.os, "write", original)
        with pytest.raises(ValueError, match="interrupted"):
            recorder.seal()
    with pytest.raises(ValueError):
        load_tape(tmp_path / "tape")


@pytest.mark.parametrize("damage", ["symlink", "public", "fifo", "oversize", "directory"])
def test_reader_rejects_unsafe_or_unbounded_files(tmp_path, damage):
    _, _, path = record_bundle(tmp_path)
    if damage == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(path)
        path = alias
    elif damage == "public":
        path.chmod(0o644)
    elif damage == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif damage == "oversize":
        with path.open("ab") as stream:
            stream.truncate(33 * 1024 * 1024)
    else:
        path = tmp_path
    with pytest.raises((ValueError, OSError)):
        load_tape(path)


def test_installed_cli_accepts_tape_and_retains_missing_coverage(tmp_path):
    b, _, path = record_bundle(tmp_path, omit_cycle=True)
    source = tmp_path / "bundle.json"
    source.write_text(b.model_dump_json())
    before = path.read_bytes()
    r = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.evaluation_cli",
            "--bundle",
            str(source),
            "--tape",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert r.returncode == 1, r.stderr
    assert "RECORDED_CYCLE_COVERAGE_INCOMPLETE" in json.loads(r.stdout)["sessions"][0]["reasons"]
    assert path.read_bytes() == before


def test_typed_copy_cannot_bypass_hash_validation(tmp_path):
    b, tape, _ = record_bundle(tmp_path)
    forged = tape.model_copy(update={"events": tape.events[1:]})
    with pytest.raises(ValueError):
        evaluate(b, tapes=(forged,))
    with pytest.raises(ValueError):
        RecordedTape.model_validate_json(forged.model_dump_json())


def test_duplicate_tapes_rejected(tmp_path):
    b, tape, _ = record_bundle(tmp_path)
    with pytest.raises(ValueError, match="Duplicate session"):
        evaluate(b, tapes=(tape, tape))


def test_private_directory_required_without_changing_existing_mode(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="private tape directory"):
        TapeRecorder(tmp_path / "tape", header_for())
    assert tmp_path.stat().st_mode & 0o777 == 0o755
    assert not (tmp_path / "tape").exists()


def test_sealed_recorder_rejects_more_events_and_resealing(tmp_path):
    with TapeRecorder(tmp_path / "tape", header_for()) as recorder:
        recorder.append(DegenFrame(), recorded_at=AT)
        recorder.seal()
        before = (tmp_path / "tape").read_bytes()
        with pytest.raises(ValueError, match="closed"):
            recorder.append(DegenFrame(), recorded_at=AT + timedelta(minutes=5))
        with pytest.raises(ValueError, match="closed"):
            recorder.seal()
        assert (tmp_path / "tape").read_bytes() == before


@pytest.mark.parametrize("unsealed", [False, True])
def test_cli_complete_or_unavailable_tape(tmp_path, unsealed):
    b, _, path = record_bundle(tmp_path)
    source = tmp_path / "bundle.json"
    source.write_text(b.model_dump_json())
    if unsealed:
        path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:-1]))
    r = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.evaluation_cli",
            "--bundle",
            str(source),
            "--tape",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert r.returncode == (2 if unsealed else 0), r.stderr
    result = json.loads(r.stdout)
    assert result["status"] == ("UNAVAILABLE" if unsealed else "COMPLETE_ARITHMETIC")
    assert not result["execution_authority"]
    assert not result["live_enabled"]
    if unsealed:
        assert str(path) not in r.stdout and not r.stderr
