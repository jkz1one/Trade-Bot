"""Common original batches compete independently in four carry accounts and portable export."""

import asyncio
import copy
import json
from decimal import Decimal

import pytest
from test_option_scope_market_tape import record
from test_option_swing_batch import batch_frame
from test_option_swing_target_replay import derived_series

from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.market_tape import TapeHeader
from app.options.scope_carry_series import (
    ScopeCarryComparison,
    ScopeCarrySeries,
    run_scope_carry_series,
    verify_scope_carry_series,
)
from app.options.scope_execution_export import verify_scope_execution_export
from app.options.swing_batch import replay_batches


def joint_series(root):
    old = derived_series(root)
    first = next(e.frame.swing[0] for e in old.sessions[0].baseline.tape.events if e.frame.swing)
    original_frame, policy = batch_frame(
        seed=first.seed, policy=old.sessions[0].baseline.tape.header.swing, item=first
    )
    sessions = []
    for n, session in enumerate(old.sessions):
        tape = session.baseline.tape
        header = TapeHeader.model_validate(tape.header.model_dump() | {"swing": policy})
        frames = []
        for e in tape.events:
            frame = e.frame
            batches = tuple(
                batch_frame(seed=i.seed, policy=tape.header.swing, item=i)[0].swing_batches[0]
                for i in frame.swing
            )
            if e.kind == "CYCLE" and not batches:
                batches = original_frame.swing_batches
            frame = frame.model_copy(update={"swing": (), "swing_batches": batches})
            frames.append((e.recorded_at, e.kind, frame))
        new = record(root / f"joint-{n}.tape", header, frames)
        sessions.append(
            ScopeCarryComparison(
                **{
                    name: getattr(session, name).model_copy(update={"tape": new})
                    for name in ("baseline", "shortlist", "entry", "managed")
                }
            )
        )
    return ScopeCarrySeries.model_validate(old.model_dump() | {"sessions": sessions})


@pytest.mark.parametrize(
    "damage", ["unenrolled", "missing", "duplicate", "source", "future", "hourly", "legacy"]
)
def test_common_tape_requires_complete_bound_batch(tmp_path, damage):
    req = joint_series(tmp_path)
    tape = req.sessions[0].baseline.tape
    raw = tape.model_dump(mode="json")
    if damage == "unenrolled":
        raw["header"]["swing"].pop("family_batch")
    else:
        frame = next(e["frame"] for e in raw["events"] if e["frame"].get("swing_batches"))
        batch = frame["swing_batches"][0]
        if damage == "missing":
            frame.pop("swing_batches")
        elif damage == "duplicate":
            frame["swing_batches"] *= 2
        elif damage == "source":
            batch["seed"]["history"]["source"] = "foreign"
        elif damage == "future":
            batch["metadata"][0]["source_at"] = "2026-10-12T22:00:00Z"
        elif damage == "hourly":
            batch["seed"]["hourly_history"] = None
        else:
            from test_option_shared_strategy import swing_input

            frame["swing"] = [swing_input().model_dump(mode="json")]
    with pytest.raises((ValueError, RuntimeError)):
        record(
            tmp_path / "invalid.tape",
            TapeHeader.model_validate(raw["header"]),
            [
                (e.recorded_at, e.kind, DegenFrame.model_validate(v["frame"]))
                for e, v in zip(tape.events, raw["events"], strict=True)
            ],
        )


def test_shortlist_retains_every_family_and_bound_quote_plans(tmp_path):
    req = joint_series(tmp_path)
    tape = req.sessions[0].baseline.tape
    event = next(e for e in tape.events if e.kind == "CYCLE")
    scans, plans, missing = replay_batches(tape, event, {}, ())
    assert not missing, missing
    assert len(scans) == len(plans) == 14
    assert len([s for s in scans if s.observations[0].status == "CONFIRMED"]) > 1


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    root = tmp_path_factory.mktemp("joint-carry")
    req = joint_series(root)
    report = asyncio.run(run_scope_carry_series(req, root / "run"))
    return req, report, json.loads((root / "run/series.json").read_text())


def test_four_independent_family_selections_keep_actual_fills_and_all_costs(replayed):
    req, report, bundle = replayed
    assert report["comparison_complete"], report
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == report
    ids = []
    for arm in "ABCD":
        first, last = [b[arm] for b in bundle["boundaries"]]
        held = first["report"]["ledger"]["position"]
        assert held is not None
        ids.append(held["entry_client_id"])
        assert len(first["evidence"]["execution_option_swing_batches"]) == 1
        assert len(first["evidence"]["execution_option_swing_batch_seeds"]) == 14
        assert not first["evidence"]["execution_option_swing_seeds"]
        buy = next(
            json.loads(row[3])
            for row in last["evidence"]["execution_orders"]
            if json.loads(row[3])["side"] == "BUY"
        )
        assert buy["entry_lineage"]["family"] == "SWING"
        assert buy["entry_lineage"]["setup"] in {
            "SWING_DAILY_8_EMA",
            "SWING_DAILY_21_EMA",
            "SWING_DAILY_50_SMA",
        }
        assert last["report"]["ledger"]["position"] is None
        period = report["carry_period_accounting"][arm]
        charge = (
            Decimal(0) if arm == "A" else Decimal(".00030") if arm == "D" else Decimal(".00015")
        )
        assert Decimal(period["model_costs"]["known_cost"]) == charge
        assert period["model_costs"]["unknown_calls"] == 0
        assert Decimal(last["report"]["execution_fees"]) > 0
        assert Decimal(period["net_after_all_costs"]) == Decimal(
            last["report"]["ledger"]["cash"]
        ) - req.sessions[0].baseline.execution.capital - charge - Decimal(".13")
    assert len(set(ids)) == 4


@pytest.mark.parametrize(
    "damage",
    [
        "root",
        "root-hash",
        "missing-child",
        "child",
        "selected-family",
        "selected-instrument",
        "policy",
    ],
)
def test_export_rejects_rehashed_batch_or_selected_lineage_substitution(replayed, damage):
    b = copy.deepcopy(replayed[2]["boundaries"][-1]["C"])
    e = b["evidence"]
    if damage.startswith("root"):
        row = e["execution_option_swing_batches"][0]
        raw = json.loads(row[3])
        raw["history"]["bars"][0]["volume"] += 1
        row[3] = json.dumps(raw)
        if damage == "root-hash":
            row[2] = fingerprint(raw)
    elif damage == "missing-child":
        e["execution_option_swing_batch_seeds"].pop()
    elif damage == "child":
        row = e["execution_option_swing_batch_seeds"][0]
        raw = json.loads(row[2])
        raw["history"]["source"] = "foreign"
        row[2] = json.dumps(raw)
    elif damage == "policy":
        row = e["execution_option_strategy"][0]
        raw = json.loads(row[1])
        raw["swing"]["ma_pullback"]["periods"] = [8]
        row[1] = json.dumps(raw)
    else:
        row = next(
            r for r in e["execution_option_opportunities"] if r[5] and '"candidates"' in r[5]
        )
        raw = json.loads(row[5])
        candidate = raw.get("entry_result", {}).get("plan", {}).get("candidate_id") or raw.get(
            "candidate_id"
        )
        c = next(c for c in raw["candidates"] if c["candidate_id"] == candidate)
        s = next(
            s
            for s in raw["scans"]
            if s["version"] == "swing-next-session-v1"
            and s["observations"][0]["family"] == c["family"]
            and s["seed"]["instrument"] == c["instrument"]
        )
        if damage == "selected-family":
            s["observations"][0]["family"] = "SWING_WEEKLY_OPEN"
        else:
            s["seed"]["instrument"]["instrument_id"] += "-foreign"
        row[5] = json.dumps(raw)
    b["export_hash"] = fingerprint({k: v for k, v in b.items() if k != "export_hash"})
    with pytest.raises(ValueError):
        verify_scope_execution_export(b, b["export_hash"])


def test_old_tape_cannot_accept_a_child_batch_hash_without_enrollment(tmp_path):
    old = derived_series(tmp_path)
    tape = old.sessions[0].baseline.tape
    frames = []
    for e in tape.events:
        f = e.frame
        if f.swing:
            f = f.model_copy(
                update={
                    "swing": tuple(
                        i.model_copy(
                            update={"seed": i.seed.model_copy(update={"batch_hash": "a" * 64})}
                        )
                        for i in f.swing
                    )
                }
            )
        frames.append((e.recorded_at, e.kind, f))
    with pytest.raises(ValueError, match="target derivation"):
        record(tmp_path / "unenrolled-child.tape", tape.header, frames)
