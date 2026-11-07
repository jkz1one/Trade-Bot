"""A full weekend carry through four independent native owners and detached export."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame
from test_option_managed_replay import managed_settings, managed_tape
from test_option_replay_series import later_tape
from test_option_swing_execution import carry_frame, fresh, settings

from app.options.coordinator import DegenFrame
from app.options.evaluation import evaluate
from app.options.evaluation_models import EvaluationBundle, EvaluationSession
from app.options.market_tape import TapeRecorder, load_tape
from app.options.replay import ReplaySettings, run_replay_series
from app.options.replay_model import ReplayScript, ScriptedDecision


def carry_tape(root, later=False):
    source = managed_tape(root, full=True)
    if later:
        source = later_tape(source, root)
    original = carry_frame()
    _, swing, _ = settings()
    header = source.header.model_copy(update={"swing": swing})
    target = AT + (timedelta(days=3) if later else timedelta())
    from test_option_swing_carry import request

    research = request(target=target.date())
    item = research.item.model_copy(
        update={
            "seed": research.item.seed.model_copy(
                update={"carry_exit_session": research.exit_session}
            )
        }
    )
    deadline = target.replace(hour=19, minute=40)
    with TapeRecorder(root / "carry.tape", header) as recorder:
        for e in source.events:
            at = e.recorded_at
            q, u = fresh(original, at)
            f = DegenFrame(quotes=(q,), underlyings=(u,))
            if e.kind == "CYCLE":
                if at == AT and not later:
                    f = original
                elif later and at == target:
                    h = frame().histories[0]
                    shift = timedelta(days=3)
                    h = h.model_copy(
                        update={
                            "source_at": at,
                            "received_at": at,
                            "bars": tuple(
                                b.model_copy(update={"begins_at": b.begins_at + shift})
                                for b in h.bars
                            ),
                        }
                    )
                    f = f.model_copy(update={"histories": (h,)})
                else:
                    h = (
                        frame()
                        .histories[0]
                        .model_copy(update={"source_at": at, "received_at": at, "bars": ()})
                    )
                    f = f.model_copy(update={"histories": (h,)})
            if e.kind == "CYCLE":
                current = item.model_copy(
                    update={
                        "metadata": item.metadata.model_copy(
                            update={"source_at": at, "received_at": at}
                        ),
                        "catalyst": item.catalyst.model_copy(
                            update={"source_at": at, "received_at": at}
                        ),
                    }
                )
                f = f.model_copy(update={"swing": (current,)})
            recorder.append(f, recorded_at=at, kind=e.kind)
            if later and at == deadline:
                when = at + timedelta(seconds=1)
                q, u = fresh(original, when)
                recorder.append(
                    DegenFrame(quotes=(q,), underlyings=(u,)), recorded_at=when, kind="MARKET"
                )
        recorder.seal()
    return load_tape(root / "carry.tape")


def carry_settings(tapes):
    old = managed_settings(tapes[0])
    _, _, owner = settings(ai=True)
    arms = tuple(
        a.model_copy(
            update={
                "policy": a.policy.model_copy(
                    update={"swing_carry": owner.swing_carry, "loss_control": owner.loss_control}
                )
            }
        )
        for a in old.manifest.arms
    )
    manifest = old.manifest.model_copy(
        update={
            "arms": arms,
            "sessions": tuple(
                EvaluationSession(
                    key=t.header.session_key,
                    opens_at=t.header.opens_at,
                    closes_at=t.header.closes_at,
                    tape_hash=t.digest,
                )
                for t in tapes
            ),
        }
    )
    entry = old.broad.decisions[0].model_copy(
        update={"horizon_seconds": 279600, "underlying_target": Decimal(605)}
    )
    manage = ScriptedDecision(
        cycle_key="position:" + str(int((AT + timedelta(days=3)).timestamp()) // 300),
        delay_seconds=2,
        action="EXIT_ALL",
    )
    return ReplaySettings.model_validate(
        old.model_dump()
        | {
            "manifest": manifest,
            "entry_policy": old.entry_policy.model_copy(
                update={"max_carry_horizon_seconds": 600000}
            ),
            "position_policy": old.position_policy.model_copy(
                update={"swing_carry": "bounded-swing-carry-v1"}
            ),
            "broad": ReplayScript(arm="C", decisions=(entry,)),
            "managed": ReplayScript(arm="D", decisions=(entry, manage)),
        }
    )


@pytest.fixture(scope="module")
def carried(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-carry-series")
    later = root / "later"
    later.mkdir(mode=0o700)
    tapes = (carry_tape(root), carry_tape(later, True))
    result = asyncio.run(run_replay_series(carry_settings(tapes), tapes, root / "run"))
    return root, tapes, result


def test_carry_series_retains_accounts_every_cost_and_original_entry(carried):
    _, tapes, result = carried
    report = result["report"]
    rows = result["bundle"]["evidence"]
    assert report["recorded_market_verified"], report
    assert report["status"] == "INCONCLUSIVE"  # Open daily boundaries are not invented marks.
    for first, last in zip(rows[:4], rows[4:], strict=True):
        assert first["closing"]["position"]["swing_carry"]
        assert last["initial"] == first["closing"]
        assert last["closing"]["position"] is None
        assert len(first["orders"]) == len(last["orders"]) == 1
        entry, close = first["orders"][0]["intent"], last["orders"][0]["intent"]
        assert close["closing_entry_client_id"] == entry["client_id"]
        assert close["exit_at"] == entry["exit_at"]
        assert len(first["cycles"]) == len(last["cycles"]) == 78
        total = report["carry_accounting"][first["arm"]]
        assert total["status"] == "COMPLETE_ARITHMETIC", total
        model_cost = sum(
            Decimal(r["arms"][first["arm"]]["known_model_cost"]) for r in report["sessions"]
        )
        assert Decimal(total["net_change"]) == Decimal(last["closing"]["cash"]) - Decimal(
            first["initial"]["cash"]
        ) - model_cost - Decimal(".06")
        assert total["benchmark_comparison"] is None
    assert len({r["orders"][0]["intent"]["client_id"] for r in rows[:4]}) == 4
    assert [c["role"] for r in (rows[3], rows[7]) for c in r["calls"]] == ["ENTRY", "MANAGEMENT"]
    assert report["carry_accounting"]["D"]["known_model_cost"] == "0.00030"
    bundle = EvaluationBundle.model_validate(result["bundle"])
    assert evaluate(bundle, tapes=tapes) == report


def test_detached_carry_unknown_cost_missing_entry_and_open_end_are_inconclusive(carried):
    _, tapes, result = carried
    bundle = EvaluationBundle.model_validate(result["bundle"])
    rows = list(bundle.evidence)
    d = rows[-1]
    rows[-1] = d.model_copy(update={"data_cost": None})
    report = evaluate(bundle.model_copy(update={"evidence": tuple(rows)}), tapes=tapes)
    assert report["carry_accounting"]["D"]["net_change"] is None
    assert "ALLOCATED_COST_UNKNOWN" in report["carry_accounting"]["D"]["reasons"]
    rows[-1] = d.model_copy(update={"orders": ()})
    report = evaluate(bundle.model_copy(update={"evidence": tuple(rows)}), tapes=tapes)
    assert report["carry_accounting"]["D"]["net_change"] is None


def test_open_period_and_unknown_model_bill_never_report_net(carried):
    _, tapes, result = carried
    bundle = EvaluationBundle.model_validate(result["bundle"])
    first = bundle.manifest.sessions[0]
    short = bundle.model_copy(
        update={
            "manifest": bundle.manifest.model_copy(update={"sessions": (first,)}),
            "evidence": tuple(r for r in bundle.evidence if r.session_key == first.key),
            "benchmarks": tuple(b for b in bundle.benchmarks if b.session_key == first.key),
        }
    )
    report = evaluate(short, tapes=tapes[:1])
    assert all(
        a["net_change"] is None and "OPEN_PERIOD_BOUNDARY_UNVALUED" in a["reasons"]
        for a in report["carry_accounting"].values()
    )
    rows = list(bundle.evidence)
    d = rows[-1]
    calls = tuple(c.model_copy(update={"usage": None}) for c in d.calls)
    cycles = tuple(
        c.model_copy(
            update={
                "attribution": c.attribution.model_copy(
                    update={"model_cost": None, "cost_status": "UNKNOWN"}
                )
            }
        )
        if c.model_called
        else c
        for c in d.cycles
    )
    rows[-1] = d.model_copy(update={"calls": calls, "cycles": cycles})
    report = evaluate(bundle.model_copy(update={"evidence": tuple(rows)}), tapes=tapes)
    assert report["carry_accounting"]["D"]["net_change"] is None
    assert "MODEL_COST_UNKNOWN" in report["carry_accounting"]["D"]["reasons"]
