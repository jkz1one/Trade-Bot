"""Generated Swing objectives are frozen in common tapes and independent native exports."""

import asyncio
import copy
import json
from decimal import Decimal

import pytest
from test_option_scope_carry_series import request as carry_request
from test_option_scope_market_tape import record
from test_option_swing_target_derivation import request as seed_request

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
from app.options.swing import SwingSeed
from app.options.swing_targets import build_swing_seed


def derived_series(root):
    old = carry_request(root)
    policy = old.sessions[0].baseline.tape.header.swing.model_copy(
        update={"target_derivation": "original-risk-ladder-v1"}
    )
    sessions = []
    for index, session in enumerate(old.sessions):
        tape = session.baseline.tape
        header = TapeHeader.model_validate(tape.header.model_dump() | {"swing": policy})
        frames = []
        for event in tape.events:
            frame = event.frame
            items = tuple(
                item.model_copy(
                    update={"seed": build_swing_seed(seed_request(seed=item.seed, policy=policy))}
                )
                for item in frame.swing
            )
            frames.append(
                (event.recorded_at, event.kind, frame.model_copy(update={"swing": items}))
            )
        new = record(root / f"derived-{index}.tape", header, frames)
        arms = {}
        for name in ("baseline", "shortlist", "entry", "managed"):
            r = getattr(session, name)
            changes = {"tape": new}
            if name in {"entry", "managed"}:
                changes["script"] = r.script.model_copy(
                    update={
                        "decisions": tuple(
                            d.model_copy(update={"underlying_target": Decimal(602)})
                            if d.action == "ENTER"
                            else d
                            for d in r.script.decisions
                        )
                    }
                )
            arms[name] = r.model_copy(update=changes)
        sessions.append(ScopeCarryComparison(**arms))
    return ScopeCarrySeries.model_validate(old.model_dump() | {"sessions": sessions})


@pytest.mark.parametrize("damage", ["missing", "unenrolled", "target"])
def test_tape_rejects_unsupported_or_changed_target_inputs(tmp_path, damage):
    req = derived_series(tmp_path)
    tape = req.sessions[0].baseline.tape
    raw = tape.model_dump(mode="json")
    if damage == "unenrolled":
        raw["header"]["swing"].pop("target_derivation")
    else:
        item = next(e["frame"]["swing"][0] for e in raw["events"] if e["frame"].get("swing"))
        if damage == "missing":
            item["seed"].pop("target_geometry")
        else:
            item["seed"]["target_geometry"]["targets"][2] = "999"
    with pytest.raises(ValueError, match="target derivation"):
        record(
            tmp_path / "invalid.tape",
            TapeHeader.model_validate(raw["header"]),
            [
                (e.recorded_at, e.kind, DegenFrame.model_validate(r["frame"]))
                for e, r in zip(tape.events, raw["events"], strict=True)
            ],
        )


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    root = tmp_path_factory.mktemp("derived-carry")
    req = derived_series(root)
    result = asyncio.run(run_scope_carry_series(req, root / "run"))
    return req, result, json.loads((root / "run/series.json").read_text())


def test_generated_seed_carries_through_independent_paid_management_and_full_costs(replayed):
    req, result, bundle = replayed
    assert result["comparison_complete"], result
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == result
    entered = []
    for arm in "ABCD":
        first, last = [b[arm] for b in bundle["boundaries"]]
        seed = json.loads(first["evidence"]["execution_option_swing_seeds"][0][3])
        assert seed["first_target"] == seed["target_geometry"]["targets"][0]
        held = first["report"]["ledger"]["position"]
        entered.append(held["entry_client_id"])
        assert held["swing_carry"]["first_target"] == seed["first_target"]
        assert held["swing_carry"]["seed_hash"] == fingerprint(SwingSeed.model_validate(seed))
        assert last["report"]["ledger"]["position"] is None
        expected = (
            Decimal(0) if arm == "A" else Decimal(".00030") if arm == "D" else Decimal(".00015")
        )
        native = result["carry_period_accounting"][arm]
        assert Decimal(native["model_costs"]["known_cost"]) == expected
        assert native["model_costs"]["unknown_calls"] == 0
        assert Decimal(last["report"]["execution_fees"]) > 0
        assert Decimal(native["net_after_all_costs"]) == (
            Decimal(last["report"]["ledger"]["cash"])
            - req.sessions[0].baseline.execution.capital
            - expected
            - Decimal(".13")
        )
    assert len(set(entered)) == 4


@pytest.mark.parametrize("damage", ["seed", "seed-hash", "scan", "policy"])
def test_detached_export_rejects_replaced_original_ladder(replayed, damage):
    _, _, original = replayed
    b = copy.deepcopy(original["boundaries"][-1]["C"])
    e = b["evidence"]
    if damage in {"seed", "seed-hash"}:
        row = e["execution_option_swing_seeds"][0]
        seed = json.loads(row[3])
        seed["target_geometry"]["targets"][1] = "999"
        row[3] = json.dumps(seed)
        if damage == "seed-hash":
            row[2] = fingerprint(SwingSeed.model_validate(seed))
    elif damage == "scan":
        row = next(
            r for r in e["execution_option_opportunities"] if r[5] and "target_geometry" in r[5]
        )
        data = json.loads(row[5])
        scan = next(s for s in data["scans"] if s.get("version") == "swing-next-session-v1")
        scan["seed"]["target_geometry"]["targets"][1] = "999"
        row[5] = json.dumps(data)
    else:
        row = e["execution_option_strategy"][0]
        config = json.loads(row[1])
        config["swing"].pop("target_derivation")
        row[1] = json.dumps(config)
    b["export_hash"] = fingerprint({k: v for k, v in b.items() if k != "export_hash"})
    with pytest.raises(ValueError, match="SWING_STORED_ORIGINAL_TARGETS_CHANGED"):
        verify_scope_execution_export(b, b["export_hash"])
