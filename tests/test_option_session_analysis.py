"""Frozen paired analysis: exact arithmetic, intact sessions and withheld unknowns."""

import json
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_evaluation import bundle_for
from test_option_managed_replay import managed_complete as managed_complete

from app.options.attribution import DecisionAttribution
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.evaluation_models import EvaluationBundle, SessionAnalysisPolicy
from app.options.session_analysis import _bootstrap, _quantile, _starts, session_analysis
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def policy(**changes):
    return SessionAnalysisPolicy.model_validate(
        {
            "primary_arm": "C",
            "block_sessions": 2,
            "minimum_blocks": 4,
            "replicates": 1000,
            "seed": 17,
            "confidence": ".95",
            "declared_trial_ids": ["fixture-v1"],
        }
        | changes
    )


def analysis_bundle(count=8):
    b = bundle_for()
    sessions, evidence, benchmarks = [], [], []
    first = b.manifest.sessions[0]
    day = first.opens_at
    while len(sessions) < count:
        window = XNYSCalendar().current_window(day)
        if window is None:
            day += timedelta(days=1)
            continue
        shift = day - first.opens_at
        session = first.model_copy(
            update={"key": window.session_date, "opens_at": day, "closes_at": window.closes_at}
        )
        sessions.append(session)

        def key(value, shift=shift):
            return "degen:" + str(int(value.split(":")[1]) + int(shift.total_seconds()) // 300)

        for arm in b.evidence:
            calls = tuple(
                call.model_copy(
                    update={
                        "source_key": key(call.source_key),
                        "started_at": call.started_at + shift,
                        "completed_at": call.completed_at + shift,
                        "usage": call.usage.model_copy(
                            update={"request_id": call.usage.request_id + "-" + session.key}
                        ),
                    }
                )
                for call in arm.calls
            )
            evidence.append(
                arm.model_copy(
                    update={
                        "session_key": session.key,
                        "cycles": tuple(
                            cycle.model_copy(update={"key": key(cycle.key)}) for cycle in arm.cycles
                        ),
                        "calls": calls,
                        "host_cost": D(len(sessions)) if arm.arm == "C" else D(".02"),
                    }
                )
            )
        mark = b.benchmarks[0]
        benchmarks.append(
            mark.model_copy(
                update={
                    "session_key": session.key,
                    **{
                        name: getattr(mark, name).model_copy(
                            update={
                                "source_at": getattr(mark, name).source_at + shift,
                                "received_at": getattr(mark, name).received_at + shift,
                            }
                        )
                        for name in ("start", "end")
                    },
                }
            )
        )
        day += timedelta(days=1)
    return EvaluationBundle.model_validate(
        b.model_copy(
            update={
                "manifest": b.manifest.model_copy(
                    update={"sessions": tuple(sessions), "session_analysis": policy()}
                ),
                "evidence": tuple(evidence),
                "benchmarks": tuple(benchmarks),
            }
        ).model_dump()
    )


@pytest.fixture(scope="module")
def enrolled():
    return analysis_bundle()


def test_absent_policy_preserves_manifest_serialization_and_hash():
    manifest = bundle_for().manifest
    data = manifest.model_dump(mode="json")
    assert "session_analysis" not in data
    assert (
        fingerprint(manifest) == "64ddf7393f883079213c4dd60a82e4f799a62ef9d0f994acd733e9d32b9e37df"
    )
    assert evaluate(bundle_for())["session_analysis"] == {"status": "NOT_ENROLLED"}


@pytest.mark.parametrize(
    "changes",
    [
        {"block_sessions": 1},
        {"block_sessions": True},
        {"minimum_blocks": 3},
        {"replicates": 999},
        {"replicates": 10001},
        {"seed": -1},
        {"seed": True},
        {"confidence": ".999"},
        {"confidence": 0.95},
        {"confidence": "NaN"},
        {"declared_trial_ids": []},
        {"declared_trial_ids": ["a", "a"]},
        {"primary_arm": "A"},
        {"version": "other"},
    ],
)
def test_invalid_policy(changes):
    with pytest.raises(ValidationError):
        policy(**changes)


@pytest.mark.parametrize(
    "changes",
    [{"primary_arm": "D"}, {"block_sessions": 3}, {"regime_labels": ["up"]}],
)
def test_manifest_enrollment_gates(enrolled, changes):
    data = enrolled.manifest.model_dump()
    data["session_analysis"] = policy(**changes)
    with pytest.raises(ValidationError):
        type(enrolled.manifest).model_validate(data)


def test_short_horizon_cannot_enroll():
    data = bundle_for().manifest.model_dump()
    data["session_analysis"] = policy()
    with pytest.raises(ValidationError):
        type(bundle_for().manifest).model_validate(data)


def test_complete_cost_adjusted_pairing_and_frozen_primary(enrolled):
    result = evaluate(enrolled)
    analysis = result["session_analysis"]
    assert result["status"] == "COMPLETE_ARITHMETIC"
    assert analysis["status"] == "COMPLETE_DIAGNOSTIC"
    assert D(analysis["mean_net_difference"]) == D(result["mean_paired_net_difference"]["C"])
    assert D(analysis["mean_net_difference"]) == D("-4.48015")
    assert analysis["endpoint"] == "C_minus_A_net_equity_per_session"
    assert analysis["planned_sessions"] == analysis["complete_sessions"] == 8
    assert analysis["policy"]["declared_trial_ids"] == ["fixture-v1"]
    assert analysis["regime_coverage"] == "NOT_PROVIDED"
    assert analysis["economic_conclusion"] == result["economic_conclusion"] == "INCONCLUSIVE"
    assert not result["execution_authority"] and not result["live_enabled"]
    assert D(analysis["percentile_interval"]["lower_minus_hurdle"]) == (
        D(analysis["percentile_interval"]["lower"]) - enrolled.manifest.hurdle_per_session
    )


@pytest.mark.parametrize("failure", ["missing", "unknown_cost", "open_boundary", "spy"])
def test_unknown_session_withholds_interval_and_retains_denominator(enrolled, failure):
    b = enrolled
    evidence = list(b.evidence)
    if failure == "missing":
        evidence.pop(-1)
    elif failure == "unknown_cost":
        evidence[-1] = evidence[-1].model_copy(update={"host_cost": None})
    elif failure == "open_boundary":
        evidence[-1] = evidence[-1].model_copy(update={"closing_complete": False})
    else:
        b = b.model_copy(update={"benchmarks": b.benchmarks[:-1]})
    result = evaluate(b.model_copy(update={"evidence": tuple(evidence)}))
    analysis = result["session_analysis"]
    assert analysis["status"] == "INCONCLUSIVE"
    assert analysis["planned_sessions"] == 8 and analysis["complete_sessions"] == 7
    assert analysis["mean_net_difference"] is analysis["percentile_interval"] is None
    blocks = [g for g in analysis["concentration"] if g["kind"] == "chronological_block"]
    assert blocks[-1]["planned_sessions"] == 2 and blocks[-1]["complete_sessions"] == 1
    assert blocks[-1]["net_difference_sum"] is None
    assert len(blocks[-1]["sessions"]) == 2


def test_seeded_exact_reference_and_wrap(monkeypatch):
    import app.options.session_analysis as module

    # Repeated start 7 samples indices 7,0,7,0,...: wrap, pairing and session denominator.
    monkeypatch.setattr(module, "_starts", lambda *_: iter([7] * 4000))
    values = list(map(D, range(8)))
    assert _bootstrap(values, policy()) == (D("3.5"), D("3.5"))
    # Final partial block must not inflate N for a nondivisible horizon.
    monkeypatch.setattr(module, "_starts", lambda *_: iter([7] * 3000))
    assert _bootstrap(values, policy(block_sessions=3)) == (D("23") / 8, D("23") / 8)


def test_quantiles_interpolate_and_random_stream_is_versioned():
    assert _quantile([D(0), D(10), D(20), D(30)], D(".25")) == D("7.50")
    stream = _starts(17, 8)
    assert [next(stream) for _ in range(12)] == [6, 5, 3, 1, 5, 5, 6, 4, 4, 0, 0, 3]


def test_context_independence_reproducibility_and_policy_hash(enrolled):
    report = evaluate(enrolled)
    with localcontext() as context:
        context.prec = 4
        assert evaluate(enrolled) == report
    changed = enrolled.manifest.model_copy(update={"session_analysis": policy(seed=18)})
    assert fingerprint(changed) != fingerprint(enrolled.manifest)
    stream, other = _starts(17, 8), _starts(18, 8)
    assert [next(stream) for _ in range(20)] != [next(other) for _ in range(20)]
    assert session_analysis(changed, report["sessions"])["policy"]["seed"] == 18


def test_regime_concentration_and_no_promotion_even_above_hurdle(enrolled):
    rows = evaluate(enrolled)["sessions"]
    for row in rows:
        row["paired_net_difference"]["C"] = "100"
    manifest = enrolled.manifest.model_copy(
        update={"session_analysis": policy(regime_labels=["calm"] * 4 + ["volatile"] * 4)}
    )
    report = session_analysis(manifest, rows)
    assert report["percentile_interval"]["lower"] == "100.000"
    assert report["economic_conclusion"] == "INCONCLUSIVE" and not report["execution_authority"]
    groups = [g for g in report["concentration"] if g["kind"] == "declared_regime"]
    assert [(g["label"], g["net_difference_sum"]) for g in groups] == [
        ("calm", "400"),
        ("volatile", "400"),
    ]
    assert D(report["largest_absolute_session_share"]) == D(1) / 8
    for row in rows:
        row["paired_net_difference"]["C"] = "0"
    assert session_analysis(manifest, rows)["largest_absolute_session_share"] is None


def test_cli_serializes_analysis_without_mutating_bundle(enrolled, tmp_path):
    path = tmp_path / "bundle.json"
    original = enrolled.model_dump_json()
    path.write_text(original)
    result = subprocess.run(
        [sys.executable, "-m", "app.options.evaluation_cli", "--bundle", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["session_analysis"] == evaluate(enrolled)["session_analysis"]
    assert path.read_text() == original


@pytest.mark.parametrize("unknown_management", [False, True])
def test_primary_d_retains_entry_and_management_charges(
    enrolled, managed_complete, unknown_management
):
    # Keep the real option entry, later management, fills, receipts and ledgers
    # from one complete offline replay. Later sessions carry those same balances.
    replay = EvaluationBundle.model_validate(managed_complete[-1]["bundle"])
    first = replay.manifest.sessions[0]
    assert first.key == enrolled.manifest.sessions[0].key
    definitions = replay.manifest.arms
    evidence = list(replay.evidence)
    accounts = {a.arm: a for a in replay.evidence}
    if unknown_management:
        native = accounts["D"]
        missing = next(c for c in native.calls if c.role == "MANAGEMENT")
        evidence[evidence.index(native)] = native.model_copy(
            update={
                "calls": tuple(
                    c.model_copy(update={"usage": None}) if c == missing else c
                    for c in native.calls
                ),
                "cycles": tuple(
                    c.model_copy(
                        update={
                            "attribution": c.attribution.model_copy(
                                update={"model_cost": None, "cost_status": "UNKNOWN"}
                            )
                        }
                    )
                    if c.key == missing.source_key
                    else c
                    for c in native.cycles
                ),
            }
        )
    for session in enrolled.manifest.sessions[1:]:
        template = next(
            a for a in enrolled.evidence if a.session_key == session.key and a.arm == "A"
        )
        for definition in definitions:
            account = accounts[definition.arm]
            cycles = template.cycles
            if definition.arm == "D":
                cycles = tuple(
                    c.model_copy(
                        update={
                            "attribution": DecisionAttribution(
                                source_key=c.key,
                                role="ENTRY",
                                model_attempted=False,
                                cost_status="NOT_CALLED",
                            )
                        }
                    )
                    for c in cycles
                )
            evidence.append(
                template.model_copy(
                    update={
                        "arm": definition.arm,
                        "definition_hash": fingerprint(definition),
                        "initial": account.closing,
                        "closing": account.closing,
                        "cycles": cycles,
                    }
                )
            )
    manifest = replay.manifest.model_copy(
        update={
            "sessions": (first, *enrolled.manifest.sessions[1:]),
            "session_analysis": policy(primary_arm="D"),
        }
    )
    bundle = replay.model_copy(
        update={
            "manifest": manifest,
            "evidence": tuple(evidence),
            "benchmarks": (*replay.benchmarks, *enrolled.benchmarks[1:]),
        }
    )
    result = evaluate(bundle)
    analysis = result["session_analysis"]
    assert analysis["endpoint"] == "D_minus_A_net_equity_per_session"
    assert analysis["economic_conclusion"] == "INCONCLUSIVE"
    assert analysis["planned_sessions"] == 8
    actual = result["sessions"][0]["arms"]["D"]
    charges = actual["model_cost_by_role"]
    assert D(charges["ENTRY"]["known_cost"]) == D(".00015")
    if unknown_management:
        assert charges["MANAGEMENT"]["unknown_calls"] == 1
        assert "MODEL_COST_UNKNOWN" in actual["reasons"]
        assert analysis["percentile_interval"] is None and analysis["complete_sessions"] == 7
    else:
        assert D(charges["MANAGEMENT"]["known_cost"]) == D(".00015")
        assert analysis["status"] == "COMPLETE_DIAGNOSTIC" and analysis["complete_sessions"] == 8
        observed = managed_complete[-1]["report"]["sessions"][0]
        assert D(analysis["mean_net_difference"]) == D(observed["paired_net_difference"]["D"]) / 8
        assert (
            result["sessions"][0]["management_net_difference_D_minus_C"]
            == observed["management_net_difference_D_minus_C"]
        )
