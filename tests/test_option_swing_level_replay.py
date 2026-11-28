"""Higher-timeframe level variants retain independent native carry accounting."""

import asyncio
import copy
import json
from decimal import Decimal

import pytest
from test_option_scope_market_tape import record
from test_option_swing_levels import CASES, level_request
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
from app.options.swing_level_models import LEVEL_FAMILIES
from app.options.swing_targets import build_swing_seed


def mirror_frame(frame):
    def instrument(i):
        return (
            i.model_copy(update={"contract": i.contract.model_copy(update={"right": "PUT"})})
            if i.contract.underlying == "SPY"
            else i
        )

    quotes = tuple(
        q.model_copy(update={"instrument": instrument(q.instrument)}) for q in frame.quotes
    )
    underlying = tuple(
        u.model_copy(update={"bid": 1200 - u.ask, "ask": 1200 - u.bid}) if u.symbol == "SPY" else u
        for u in frame.underlyings
    )
    histories = tuple(
        h.model_copy(
            update={
                "bars": tuple(
                    b.model_copy(
                        update={
                            "open": 1200 - b.open,
                            "close": 1200 - b.close,
                            "low": 1200 - b.high,
                            "high": 1200 - b.low,
                        }
                    )
                    for b in h.bars
                )
            }
        )
        if h.symbol == "SPY"
        else h
        for h in frame.histories
    )
    items = tuple(
        i.model_copy(
            update={
                "seed": i.seed.model_copy(update={"instrument": instrument(i.seed.instrument)}),
                "metadata": i.metadata.model_copy(
                    update={
                        "instrument": instrument(i.metadata.instrument),
                        "delta": -abs(i.metadata.delta),
                    }
                ),
            }
        )
        for i in frame.swing
    )
    return frame.model_copy(
        update={"quotes": quotes, "underlyings": underlying, "histories": histories, "swing": items}
    )


def level_series(root, key="previous_week_high", right="CALL"):
    old = derived_series(root)
    first = next(
        e.frame.swing[0].seed for e in old.sessions[0].baseline.tape.events if e.frame.swing
    )
    policy = level_request(
        key, seed=first, policy=old.sessions[0].baseline.tape.header.swing
    ).policy
    sessions = []
    for n, session in enumerate(old.sessions):
        tape = session.baseline.tape
        header = TapeHeader.model_validate(tape.header.model_dump() | {"swing": policy})
        frames = []
        for e in tape.events:
            frame = mirror_frame(e.frame) if right == "PUT" else e.frame
            items = tuple(
                i.model_copy(
                    update={
                        "seed": build_swing_seed(level_request(key, seed=i.seed, policy=policy))
                    }
                )
                for i in frame.swing
            )
            frame = frame.model_copy(update={"swing": items})
            frames.append((e.recorded_at, e.kind, frame))
        new = record(root / f"level-{n}.tape", header, frames)
        arms = {}
        for name in ("baseline", "shortlist", "entry", "managed"):
            r = getattr(session, name)
            changes = {"tape": new}
            if name in {"entry", "managed"}:
                changes["script"] = r.script.model_copy(
                    update={
                        "decisions": tuple(
                            d.model_copy(
                                update={
                                    "underlying_target": Decimal("601.8")
                                    if right == "CALL"
                                    else Decimal("598.2")
                                }
                            )
                            if d.action == "ENTER"
                            else d
                            for d in r.script.decisions
                        )
                    }
                )
            arms[name] = r.model_copy(update=changes)
        sessions.append(ScopeCarryComparison(**arms))
    return ScopeCarrySeries.model_validate(old.model_dump() | {"sessions": sessions})


@pytest.mark.parametrize("damage", ["unenrolled", "source", "future", "missing"])
def test_common_tape_rejects_unbound_level_inputs(tmp_path, damage):
    r = level_series(tmp_path)
    tape = r.sessions[0].baseline.tape
    raw = tape.model_dump(mode="json")
    if damage == "unenrolled":
        raw["header"]["swing"].pop("higher_levels")
        raw["header"]["swing"]["daily_lookback"] = 3
    else:
        seed = next(
            e["frame"]["swing"][0]["seed"] for e in raw["events"] if e["frame"].get("swing")
        )
        if damage == "missing":
            seed.pop("level_key")
        elif damage == "source":
            seed["history"]["source"] = "foreign"
        else:
            seed["history"]["source_at"] = "2026-10-10T22:00:00Z"
    with pytest.raises(ValueError):
        record(
            tmp_path / "invalid.tape",
            TapeHeader.model_validate(raw["header"]),
            [
                (e.recorded_at, e.kind, DegenFrame.model_validate(v["frame"]))
                for e, v in zip(tape.events, raw["events"], strict=True)
            ],
        )


@pytest.fixture(scope="module", params=CASES)
def replayed(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("level-carry")
    req = level_series(root, *request.param)
    result = asyncio.run(run_scope_carry_series(req, root / "run"))
    return req, result, json.loads((root / "run/series.json").read_text())


def test_level_variants_independent_carry_fills_paid_management_and_all_costs(replayed):
    req, report, bundle = replayed
    assert report["comparison_complete"], report
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == report
    ids = []
    for arm in "ABCD":
        first, last = [b[arm] for b in bundle["boundaries"]]
        held = first["report"]["ledger"]["position"]
        ids.append(held["entry_client_id"])
        buy = next(
            json.loads(row[3])
            for row in last["evidence"]["execution_orders"]
            if json.loads(row[3])["side"] == "BUY"
        )
        assert buy["entry_lineage"]["family"] == "SWING"
        assert (
            buy["entry_lineage"]["setup"]
            == LEVEL_FAMILIES[
                next(
                    e.frame.swing[0].seed.level_key
                    for e in req.sessions[0].baseline.tape.events
                    if e.frame.swing
                )
            ]
        )
        seed = json.loads(first["evidence"]["execution_option_swing_seeds"][0][3])
        assert held["swing_carry"]["first_target"] == seed["first_target"]
        assert "hourly_history" not in seed
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


@pytest.mark.parametrize("damage", ["source", "level-rule", "family", "enrollment"])
def test_native_export_rejects_rehashed_family_substitution(replayed, damage):
    b = copy.deepcopy(replayed[2]["boundaries"][-1]["C"])
    e = b["evidence"]
    if damage == "source":
        row = e["execution_option_swing_seeds"][0]
        seed = json.loads(row[3])
        seed["history"]["source"] = "foreign"
        row[3] = json.dumps(seed)
    elif damage == "enrollment":
        row = e["execution_option_strategy"][0]
        config = json.loads(row[1])
        config["swing"].pop("higher_levels")
        config["swing"]["daily_lookback"] = 3
        row[1] = json.dumps(config)
    else:
        row = next(
            row
            for row in e["execution_option_opportunities"]
            if row[5] and "level_evidence" in row[5]
        )
        data = json.loads(row[5])
        scan = next(s for s in data["scans"] if s["version"] == "swing-next-session-v1")
        if damage == "level-rule":
            scan["level_evidence"]["level_price"] = "9"
        else:
            scan["observations"][0]["family"] = "SWING_DAILY_BREAKOUT"
        row[5] = json.dumps(data)
    b["export_hash"] = fingerprint({k: v for k, v in b.items() if k != "export_hash"})
    with pytest.raises(ValueError):
        verify_scope_execution_export(b, b["export_hash"])
