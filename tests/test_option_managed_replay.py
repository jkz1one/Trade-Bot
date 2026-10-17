"""Arm D owns its own account, paid management and receipt-linked stored attribution."""

import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame
from test_option_admission import END, inputs
from test_option_evaluation import OPEN, bundle_for
from test_option_execution import quote_at, underlying_at
from test_option_market_tape import header_for
from test_option_position_coordination import MANAGE_AT, management_frame
from test_option_replay import KEY, settings_for

from app.options.coordinator import DegenFrame
from app.options.evaluation_export import export_comparison
from app.options.evaluation_models import EvaluationManifest
from app.options.market_tape import TapeRecorder, load_tape
from app.options.observer import OptionObserver
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.replay import ReplaySettings, run_replay
from app.options.replay_model import ReplayScript, ScriptedDecision

MKEY = "position:" + str(int(MANAGE_AT.timestamp()) // 300)
DKEY = MKEY.replace("position:", "degen:")


def managed_tape(root, *, race=False, fill_exit=True, full=False):
    b = bundle_for()
    with TapeRecorder(root / "managed.tape", header_for(b)) as recorder:
        recorder.append(
            DegenFrame(underlyings=(b.benchmarks[0].start,)), recorded_at=OPEN, kind="MARKET"
        )
        for n in range(78):
            at = OPEN + timedelta(minutes=5 * n)
            if not full and at not in (AT, MANAGE_AT):
                continue
            f = (
                frame()
                if at == AT
                else management_frame()
                if at == MANAGE_AT
                else DegenFrame(
                    histories=(
                        frame()
                        .histories[0]
                        .model_copy(update={"source_at": at, "received_at": at, "bars": ()}),
                    ),
                    underlyings=(underlying_at(inputs(), at),),
                )
            )
            recorder.append(f, recorded_at=at)
            if at in (AT, MANAGE_AT):
                for second in range(1, 7):
                    when = at + timedelta(seconds=second)
                    breach = at == MANAGE_AT and (second >= 4 or (race and second >= 2))
                    u = underlying_at(
                        inputs(),
                        when,
                        bid=Decimal(590) if breach else Decimal("600.8"),
                        ask=Decimal("590.01") if breach else Decimal("600.81"),
                    )
                    recorder.append(
                        DegenFrame(
                            quotes=(quote_at(inputs(), when),)
                            if (fill_exit or at == AT or second <= 2)
                            else (),
                            underlyings=(u,),
                        ),
                        recorded_at=when,
                        kind="MARKET",
                    )
        recorder.append(
            DegenFrame(underlyings=(b.benchmarks[0].end,)), recorded_at=END, kind="MARKET"
        )
        recorder.seal()
    return load_tape(root / "managed.tape")


def managed_settings(tape, action="EXIT_ALL", delay=2):
    old = settings_for(tape)
    d = old.manifest.arms[2].model_copy(
        update={
            "arm": "D",
            "limits": old.manifest.arms[2].limits.model_copy(
                update={"population_id": "evaluation-D", "account_id": "account-D"}
            ),
        }
    )
    return ReplaySettings.model_validate(
        old.model_dump()
        | {
            "manifest": old.manifest.model_dump() | {"arms": (*old.manifest.arms, d)},
            "managed": ReplayScript(
                arm="D",
                decisions=(
                    old.broad.decisions[0],
                    ScriptedDecision(
                        cycle_key=MKEY,
                        delay_seconds=delay,
                        action=action,
                        underlying_invalidation="600.2" if action == "TIGHTEN" else None,
                    ),
                ),
            ),
            "position_policy": PositionReasoningPolicy(max_lease_seconds=5),
        }
    )


@pytest.fixture(scope="module")
def managed_complete(tmp_path_factory):
    root = tmp_path_factory.mktemp("managed-replay")
    tape = managed_tape(root, full=True)
    settings = managed_settings(tape)
    result = asyncio.run(run_replay(settings, tape, root / "run"))
    return root, tape, settings, result


def test_arm_d_costs_ownership_and_proposal_approval_fill_lineage(managed_complete):
    root, _tape, _settings, result = managed_complete
    assert result["report"]["status"] == "COMPLETE_ARITHMETIC", result["report"]
    rows = {r["arm"]: r for r in result["bundle"]["evidence"]}
    assert set(rows) == set("ABCD")
    d = rows["D"]
    assert len(d["calls"]) == 2
    assert [c["role"] for c in d["calls"]] == ["ENTRY", "MANAGEMENT"]
    assert len(rows["C"]["calls"]) == 1
    attr = next(c["attribution"] for c in d["cycles"] if c["key"] == DKEY)
    assert attr["proposal_action"] == "EXIT_ALL"
    assert attr["review_outcome"] == "ELIGIBLE"
    assert attr["application_status"] == "PREPARED"
    assert attr["order_status"] == "FILLED" and attr["attempted"]
    assert attr["filled_quantity"] == attr["approved_quantity"] > 0
    assert attr["fill_ids"] == [f["fill_id"] for f in d["orders"][1]["observation"]["fills"]]
    assert attr["entry_client_id"] == d["orders"][0]["intent"]["client_id"]
    assert (
        d["orders"][1]["intent"]["position_protection"]["position_revision"]
        == attr["position_revision"]
    )
    assert (
        d["orders"][1]["observation"]["fills"][0]["occurred_at"]
        > d["orders"][1]["decision_completed_at"]
    )
    costs = result["report"]["sessions"][0]["arms"]
    assert Decimal(costs["D"]["known_model_cost"]) == 2 * Decimal(costs["C"]["known_model_cost"])
    assert (
        costs["D"]["model_cost_by_role"]["ENTRY"] == costs["D"]["model_cost_by_role"]["MANAGEMENT"]
    )
    assert Decimal(
        result["report"]["sessions"][0]["management_net_difference_D_minus_C"]
    ) == Decimal(costs["D"]["net_change"]) - Decimal(costs["C"]["net_change"])
    assert Decimal(costs["D"]["net_change"]) == Decimal(d["closing"]["cash"]) - 1000 - Decimal(
        costs["D"]["known_model_cost"]
    ) - Decimal(".03")
    assert result["report"]["economic_conclusion"] == "INCONCLUSIVE"
    assert len({r["orders"][0]["intent"]["client_id"] for r in rows.values()}) == 4
    assert result["scheduling"]["D"]["model_scripts_used"] == sorted([KEY, MKEY])
    view = OptionObserver(root / "run/D/journal.db", "evaluation-D", clock=lambda: END).report(
        limit=100
    )
    assert view["status"] == "OK", view
    assert next(o for o in view["opportunities"] if o["cycle_key"] == DKEY)["attribution"] == attr
    assert (
        next(o for o in view["orders"] if o["side"] == "SELL")["attribution"]["origin"]
        == "POSITION_MODEL"
    )
    assert not view["network_calls"]


@pytest.mark.parametrize(
    "action,delay,race",
    [
        ("MAINTAIN", 2, False),
        ("TIGHTEN", 2, False),
        ("EXIT_ALL", 5, False),
        ("EXIT_ALL", 2, True),
        ("UNKNOWN", 2, False),
    ],
)
def test_management_outcomes_keep_costs_and_independent_protection(tmp_path, action, delay, race):
    tape = managed_tape(tmp_path, race=race)
    result = asyncio.run(run_replay(managed_settings(tape, action, delay), tape, tmp_path / "run"))
    d = result["bundle"]["evidence"][3]
    attr = next(c["attribution"] for c in d["cycles"] if c["key"] == DKEY)
    assert d["closing"]["position"] is None
    assert len(d["calls"]) == 2
    assert (d["calls"][1]["usage"] is None) == (action == "UNKNOWN")
    assert attr["client_id"] is None and attr["fill_ids"] == []
    if action in {"MAINTAIN", "TIGHTEN"}:
        assert (
            attr["application_status"] == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED"}[action]
        )
    if action == "UNKNOWN":
        assert attr["cost_status"] == "UNKNOWN"
        assert result["report"]["status"] == "INCONCLUSIVE"
    else:
        assert Decimal(attr["model_cost"]) > 0
    assert d["orders"][1]["intent"].get("position_protection") is None


def test_management_approval_without_subsequent_fill_is_not_execution(tmp_path):
    tape = managed_tape(tmp_path, fill_exit=False)
    result = asyncio.run(run_replay(managed_settings(tape), tape, tmp_path / "run"))
    d = result["bundle"]["evidence"][3]
    attr = next(c["attribution"] for c in d["cycles"] if c["key"] == DKEY)
    assert attr["application_status"] == "PREPARED"
    assert attr["attempted"] and attr["filled_quantity"] == 0 and not attr["fill_ids"]
    assert d["closing"]["position"] is not None
    assert result["report"]["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("damage", ["receipt", "consumption", "fill", "revision", "cost", "plan"])
def test_export_rejects_broken_stored_attribution(managed_complete, tmp_path, damage):
    root, tape, _settings, result = managed_complete
    copy = tmp_path / "D.db"
    shutil.copy2(root / "run/D/journal.db", copy)
    with sqlite3.connect(copy) as db:
        if damage == "receipt":
            db.execute(
                "UPDATE execution_orders SET approval_json=json_remove(approval_json,'$.position_result') WHERE json_extract(approval_json,'$.origin')='POSITION_MODEL'"
            )
        elif damage == "consumption":
            db.execute("DELETE FROM execution_option_decisions WHERE source_key=?", (DKEY,))
        elif damage == "fill":
            db.execute(
                "DELETE FROM execution_fills WHERE client_id=(SELECT client_id FROM execution_orders WHERE source_key=?)",
                (DKEY,),
            )
        elif damage == "revision":
            db.execute(
                "UPDATE execution_orders SET intent_json=json_set(intent_json,'$.position_protection.position_revision',1) WHERE source_key=?",
                (DKEY,),
            )
        elif damage == "cost":
            db.execute("UPDATE execution_model_calls SET cost='0' WHERE source_key=?", (DKEY,))
        else:
            db.execute(
                "UPDATE execution_option_decisions SET inputs_json=json_set(inputs_json,'$.position_result.plan.action','MAINTAIN') WHERE source_key=?",
                (DKEY,),
            )
    manifest = EvaluationManifest.model_validate(result["bundle"]["manifest"])
    sources = {
        a: {
            "journal": copy if a == "D" else root / f"run/{a}/journal.db",
            "data_cost": "0",
            "host_cost": "0",
        }
        for a in "ABCD"
    }
    with pytest.raises(ValueError):
        export_comparison(manifest, tape, sources)


def test_four_arm_export_cli_reads_without_authority(managed_complete, tmp_path):
    root, _tape, _settings, result = managed_complete
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "manifest": result["bundle"]["manifest"],
                "tape": str(root / "managed.tape"),
                "sources": [
                    {
                        "arm": a,
                        "journal": str(root / f"run/{a}/sessions/2026-10-09.db"),
                        "data_cost": ".01",
                        "host_cost": ".02",
                    }
                    for a in "ABCD"
                ],
            }
        )
    )
    request.chmod(0o600)
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.evaluation_export_cli",
            "--request",
            str(request),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert json.loads(process.stdout)["bundle"] == result["bundle"]


@pytest.mark.parametrize(
    "change",
    [
        "missing_script",
        "missing_policy",
        "wrong_arm",
        "duplicate_population",
        "missing_arm",
        "different_entry",
    ],
)
def test_rejects_unenrolled_or_shared_managed_configuration(managed_complete, tmp_path, change):
    _, tape, settings, _ = managed_complete
    data = settings.model_dump()
    if change == "missing_script":
        data["managed"] = None
    elif change == "missing_policy":
        data["position_policy"] = None
    elif change == "wrong_arm":
        data["managed"]["arm"] = "C"
    elif change == "duplicate_population":
        data["manifest"]["arms"][3]["limits"]["population_id"] = data["manifest"]["arms"][2][
            "limits"
        ]["population_id"]
    elif change == "different_entry":
        data["managed"]["decisions"][0]["delay_seconds"] = 3
    else:
        data["manifest"]["arms"] = data["manifest"]["arms"][:3]
    with pytest.raises(ValueError):
        asyncio.run(run_replay(ReplaySettings.model_validate(data), tape, tmp_path / "bad"))
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("unknown", [False, True])
def test_arm_d_multi_session_preserves_accounts_costs_and_unknown_history(tmp_path, unknown):
    from test_option_replay_series import SHIFT, later_tape

    from app.options.evaluation_models import EvaluationSession
    from app.options.lifecycle import OptionReceipt
    from app.options.replay import ScriptedSettlement, run_replay_series

    first = managed_tape(tmp_path)
    later = later_tape(first, tmp_path)
    settings = managed_settings(first, "UNKNOWN" if unknown else "EXIT_ALL")
    data = settings.model_dump()
    data["manifest"]["sessions"] = (
        *settings.manifest.sessions,
        EvaluationSession(
            key=later.header.session_key,
            opens_at=later.header.opens_at,
            closes_at=later.header.closes_at,
            tape_hash=later.digest,
        ),
    )
    for name in ("narrow", "broad", "managed"):
        script = getattr(settings, name)
        data[name] = script.model_copy(
            update={
                "decisions": (
                    *script.decisions,
                    *(
                        d.model_copy(
                            update={
                                "cycle_key": d.cycle_key.split(":")[0]
                                + ":"
                                + str(
                                    int(d.cycle_key.split(":")[1])
                                    + int(SHIFT.total_seconds()) // 300
                                )
                            }
                        )
                        for d in script.decisions
                    ),
                )
            }
        )
    data["settlements"] = tuple(
        ScriptedSettlement(
            arm=a,
            receipt=OptionReceipt(
                receipt_id="explicit-funds",
                sequence=3,
                kind="FUNDS_SETTLED",
                occurred_at=later.header.opens_at - timedelta(hours=1),
                cash_change="384.4",
            ),
        )
        for a in "ABCD"
    )
    result = asyncio.run(
        run_replay_series(ReplaySettings.model_validate(data), (first, later), tmp_path / "run")
    )
    rows = result["bundle"]["evidence"]
    for before, after in zip(rows[:4], rows[4:], strict=True):
        assert after["initial"] == before["closing"]
        assert after["receipts"][0]["cash_change"] == "384.4"
        assert after["initial"]["cash"] != "1000"
    before, after = rows[3], rows[7]
    assert len(before["calls"]) == 2
    assert len(after["calls"]) == (0 if unknown else 2)
    assert (before["calls"][1]["usage"] is None) == unknown
    assert all(
        c["source_key"] not in {x["source_key"] for x in before["calls"]} for c in after["calls"]
    )
    assert (
        result["source_proof"][7]["previous_export_hash"]
        == result["source_proof"][3]["export_hash"]
    )
    assert (
        result["report"]["totals"]["D"]["net_change"] is None
    )  # Sparse tape retains missing slots.


@pytest.mark.parametrize("change", ["role", "cost", "fill", "attribution"])
def test_evaluator_rejects_inconsistent_management_projection(managed_complete, change):
    from app.options.evaluation import evaluate
    from app.options.evaluation_models import EvaluationBundle

    _, tape, _, result = managed_complete
    raw = json.loads(json.dumps(result["bundle"]))
    d = raw["evidence"][3]
    cycle = next(c for c in d["cycles"] if c["key"] == DKEY)
    if change == "role":
        d["calls"][1]["role"] = "ENTRY"
    elif change == "cost":
        cycle["attribution"]["model_cost"] = "0"
    elif change == "fill":
        cycle["attribution"]["fill_ids"] = []
    else:
        cycle["attribution"] = None
    report = evaluate(EvaluationBundle.model_validate(raw), tapes=(tape,))
    assert report["status"] == "INCONCLUSIVE"
    assert any("ATTRIBUTION" in r for r in report["sessions"][0]["arms"]["D"]["reasons"])


def test_paid_completion_after_close_retains_charge_without_complete_totals():
    from test_option_evaluation import change_arm

    from app.options.evaluation import evaluate

    bundle = bundle_for()
    call = (
        bundle.evidence[1].calls[0].model_copy(update={"completed_at": END + timedelta(seconds=1)})
    )
    report = evaluate(change_arm(bundle, calls=(call,)))
    arm = report["sessions"][0]["arms"]["B"]
    assert Decimal(arm["known_model_cost"]) > 0
    assert arm["unknown_model_calls"] == 0
    assert "MODEL_COMPLETION_AFTER_SESSION" in arm["reasons"]
    assert report["totals"]["B"]["net_change"] is None
