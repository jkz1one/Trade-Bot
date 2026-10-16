"""Audit-bound risk exports retain independent accounts and full-cost replay history."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_admission import NOW
from test_option_execution import owned
from test_option_family_loss import AFTER, family, loss, policy, seed
from test_option_loss_control import ready
from test_option_loss_model_admission import COSTS
from test_option_loss_reset import KEY, apply, request

from app.options.engine import EntryModelBlocked, fingerprint
from app.options.loss_evidence import (
    LossControlEvidence,
    export_loss_control,
    validate_loss_boundary,
)
from app.options.operator import OptionsControl


def exported(engine, boundary=AFTER):
    with engine.journal.read() as db:
        events = db.execute("SELECT * FROM execution_events ORDER BY sequence").fetchall()
        return export_loss_control(
            db, engine.policy.loss_control, engine.limits.population_id, events, boundary=boundary
        )


def test_fresh_and_legacy_loss_evidence_do_not_mutate_owner(tmp_path):
    with owned(tmp_path, loss_control=policy()) as (e, _, _):
        before = e.journal.path.read_bytes()
        result = exported(e)
        assert result.state.consumed_entries == 0 and not result.consumed
        assert result.policy_hash == fingerprint(policy())
        assert result.state.last_checked_at == NOW
        assert e.journal.path.read_bytes() == before
    other = tmp_path / "legacy"
    other.mkdir()
    with owned(other) as (e, _, _):
        before = e.journal.path.read_bytes()
        assert exported(e) is None
        assert e.journal.path.read_bytes() == before


def test_consumed_family_outcome_pause_reset_and_read_only_replay(tmp_path):
    with owned(tmp_path, loss_control=policy(), cost_policy=COSTS) as (e, v, d):
        OptionsControl.enroll(e, KEY, now=NOW)
        loss(e, v, d)
        seed(e, v, d, "paused", "DEGEN", AFTER)
        with pytest.raises(EntryModelBlocked):
            e.begin_model_attempt("paused", "a" * 64, now=AFTER)
        before = exported(e)
        assert before.consumed[0].outcome == "LOSS"
        assert before.consumed[0].entry_lineage.family == "DEGEN"
        assert before.consumed[0].execution_fees > 0
        assert before.entry_pauses[0].reasons == ("NATIVE_FAMILY_MODEL_ENTRY_PAUSED",)
        assert apply(e, request(e, loss_family="DEGEN"))["status"] == "APPLIED"
        snapshot = e.journal.path.read_bytes()
        after = exported(e)
        assert after.consumed == before.consumed
        assert after.entry_pauses == before.entry_pauses
        assert after.resets[0].loss_family == "DEGEN"
        assert not after.state.families[0].locked
        validate_loss_boundary(after, policy(), AFTER, before)
        assert exported(e) == after
        assert e.journal.path.read_bytes() == snapshot


@pytest.mark.parametrize(
    "damage",
    [
        "state",
        "hash",
        "record",
        "missing_consumption",
        "missing_review",
        "future_review",
        "family_count",
        "policy",
        "reset_receipt",
    ],
)
def test_export_rejects_changed_native_risk_evidence(tmp_path, damage):
    with owned(tmp_path, loss_control=policy()) as (e, v, d):
        OptionsControl.enroll(e, KEY, now=NOW)
        loss(e, v, d)
        ready(e, v, d, AFTER)
        if damage == "reset_receipt":
            assert apply(e, request(e, loss_family="DEGEN"))["status"] == "APPLIED"
        with e.journal.write() as db:
            if damage == "state":
                db.execute(
                    "UPDATE execution_option_loss_control SET state_json=json_set(state_json,'$.locked',json('true'))"
                )
            elif damage == "hash":
                db.execute("UPDATE execution_option_loss_outcomes SET outcome_hash=?", ("0" * 64,))
            elif damage == "record":
                db.execute(
                    "UPDATE execution_option_loss_outcomes SET record_json=json_set(record_json,'$.known_model_cost','999')"
                )
            elif damage == "missing_consumption":
                db.execute("DELETE FROM execution_events WHERE kind='NATIVE_LOSS_OUTCOME_CONSUMED'")
            elif damage == "missing_review":
                db.execute("DELETE FROM execution_events WHERE kind='NATIVE_LOSS_CONTROL_REVIEWED'")
            elif damage == "future_review":
                db.execute(
                    "UPDATE execution_events SET occurred_at=? WHERE kind='NATIVE_LOSS_CONTROL_REVIEWED'",
                    ((AFTER + timedelta(days=1)).isoformat(),),
                )
            elif damage == "family_count":
                db.execute(
                    "UPDATE execution_option_loss_control SET state_json=json_set(state_json,'$.families[0].consumed_entries',0)"
                )
                db.execute(
                    "UPDATE execution_events SET payload=json_set(payload,'$.families[0].consumed_entries',0) WHERE kind='NATIVE_LOSS_CONTROL_REVIEWED'"
                )
            elif damage == "policy":
                db.execute(
                    "UPDATE execution_option_loss_control SET policy_json=json_set(policy_json,'$.cooldown_seconds',1801)"
                )
            else:
                db.execute("DELETE FROM execution_commands")
        before = e.journal.path.read_bytes()
        with pytest.raises(ValueError):
            exported(e)
        assert e.journal.path.read_bytes() == before


def test_portable_policy_family_and_history_binding(tmp_path):
    with owned(tmp_path, loss_control=policy()) as (e, v, d):
        loss(e, v, d)
        original = exported(e)
        with pytest.raises(ValueError, match="ENROLLMENT"):
            validate_loss_boundary(None, policy(), AFTER)
        with pytest.raises(ValueError, match="POLICY"):
            validate_loss_boundary(original, policy(global_limit=1), AFTER)
        with pytest.raises(ValueError, match="AFTER_BOUNDARY"):
            validate_loss_boundary(original, policy(), NOW - timedelta(seconds=1))
        raw = original.model_dump(mode="json")
        raw["state"]["consumed_entries"] = raw["state"]["families"][0]["consumed_entries"] = 0
        raw["consumed"] = []
        lost = LossControlEvidence.model_validate(raw)
        with pytest.raises(ValueError, match="HISTORY_CHANGED"):
            validate_loss_boundary(lost, policy(), AFTER, original)
        raw = original.model_dump(mode="json")
        raw["consumed"][0]["outcome"] = "WIN"
        with pytest.raises(ValueError, match="sign mismatch"):
            LossControlEvidence.model_validate(raw)


@pytest.fixture(scope="module")
def risk_series(tmp_path_factory):
    from test_option_managed_replay import managed_settings
    from test_option_replay_series import SHIFT
    from test_option_shared_replay import shared_tape

    from app.options.evaluation_models import EvaluationSession
    from app.options.replay import ReplaySettings, run_replay_series
    from app.options.replay_model import ReplayScript

    root = tmp_path_factory.mktemp("loss-series")
    later = root / "later"
    later.mkdir(mode=0o700)
    tapes = (shared_tape(root, full=True), shared_tape(later, full=True, later=True))
    settings = managed_settings(tapes[0])
    h = tapes[1].header
    definitions = tuple(
        a.model_copy(
            update={"policy": a.policy.model_copy(update={"loss_control": policy(global_limit=1)})}
        )
        for a in settings.manifest.arms
    )
    manifest = settings.manifest.model_copy(
        update={
            "arms": definitions,
            "sessions": (
                *settings.manifest.sessions,
                EvaluationSession(
                    key=h.session_key,
                    opens_at=h.opens_at,
                    closes_at=h.closes_at,
                    tape_hash=tapes[1].digest,
                ),
            ),
        }
    )
    scripts = {}
    for name in ("narrow", "broad", "managed"):
        script = getattr(settings, name)
        scripts[name] = ReplayScript(
            arm=script.arm,
            decisions=(
                *script.decisions,
                *(
                    d.model_copy(
                        update={
                            "cycle_key": d.cycle_key.split(":")[0]
                            + ":"
                            + str(
                                int(d.cycle_key.split(":")[1]) + int(SHIFT.total_seconds()) // 300
                            )
                        }
                    )
                    for d in script.decisions
                ),
            ),
        )
    settings = ReplaySettings.model_validate(
        settings.model_dump() | {"manifest": manifest, **scripts}
    )
    return root, tapes, asyncio.run(run_replay_series(settings, tapes, root / "run"))


def test_shared_abcd_locks_survive_next_session_and_keep_all_costs(risk_series):
    root, tapes, result = risk_series
    assert result["report"]["status"] == "COMPLETE_ARITHMETIC", result["report"]
    assert result["report"]["economic_conclusion"] == "INCONCLUSIVE"
    rows = result["bundle"]["evidence"]
    assert len(rows) == 8
    for first, later in zip(rows[:4], rows[4:], strict=True):
        a, b = first["loss_control"], later["loss_control"]
        assert a["state"]["locked"] and b["state"]["locked"]
        assert family(a["state"], "SWING")["locked"]
        assert not family(a["state"], "DEGEN")["locked"]
        assert a["state"]["consumed_entries"] == b["state"]["consumed_entries"] == 1
        assert a["consumed"] == b["consumed"]
        assert a["consumed"][0]["recognized_at"] == tapes[0].header.closes_at.isoformat().replace(
            "+00:00", "Z"
        )
        assert len(a["consumed"]) == 1 and a["consumed"][0]["entry_lineage"]["family"] == "SWING"
        assert not later["calls"] and not later["orders"]
        assert later["initial"] == first["closing"] == later["closing"]
        assert b["state"]["last_checked_at"] == tapes[1].header.closes_at.isoformat().replace(
            "+00:00", "Z"
        )
        if first["arm"] != "A":
            assert b["entry_pauses"] and all(
                "NATIVE_LOSS_LOCKED" in x["reasons"] for x in b["entry_pauses"]
            )
        for index, row in enumerate((first, later)):
            report = result["report"]["sessions"][index]["arms"][row["arm"]]
            assert report["stored_loss_control"] == row["loss_control"]
            assert Decimal(report["net_change"]) == Decimal(row["closing"]["cash"]) - Decimal(
                row["initial"]["cash"]
            ) - Decimal(report["known_model_cost"]) - Decimal(".03")
        path = root / "run" / first["arm"] / "sessions" / (tapes[0].header.session_key + ".db")
        with sqlite3.connect(path) as db:
            saved = json.loads(
                db.execute("SELECT state_json FROM execution_option_loss_control").fetchone()[0]
            )
        assert saved == a["state"]
    assert [c["role"] for c in rows[3]["calls"]] == ["ENTRY", "MANAGEMENT"]
    assert Decimal(rows[3]["loss_control"]["consumed"][0]["known_model_cost"]) == Decimal(".00030")
    assert len({r["loss_control"]["consumed"][0]["entry_client_id"] for r in rows[:4]}) == 4


def test_evaluator_rejects_removed_or_rewritten_risk_history(risk_series):
    from copy import deepcopy

    from app.options.evaluation import evaluate
    from app.options.evaluation_models import EvaluationBundle

    _, _, result = risk_series
    data = deepcopy(result["bundle"])
    data["evidence"][0].pop("loss_control")
    report = evaluate(EvaluationBundle.model_validate(data))
    assert (
        "LOSS_CONTROL_EVIDENCE_ENROLLMENT_MISMATCH" in report["sessions"][0]["arms"]["A"]["reasons"]
    )
    data = deepcopy(result["bundle"])
    data["evidence"][4]["loss_control"]["consumed"][0]["outcome_hash"] = "a" * 64
    report = evaluate(EvaluationBundle.model_validate(data))
    assert "LOSS_CONTROL_HISTORY_CHANGED" in report["sessions"][1]["arms"]["A"]["reasons"]


def test_native_export_binds_pause_to_completed_cycle(risk_series, tmp_path):
    import shutil

    from app.options.evaluation_export import export_series
    from app.options.evaluation_models import EvaluationManifest

    root, tapes, result = risk_series
    manifest = EvaluationManifest.model_validate(result["bundle"]["manifest"])
    sources = {
        t.header.session_key: {
            a: {
                "journal": root / "run" / a / "sessions" / (t.header.session_key + ".db"),
                "data_cost": ".01",
                "host_cost": ".02",
            }
            for a in "ABCD"
        }
        for t in tapes
    }
    target = tmp_path / "changed.db"
    shutil.copy2(sources[tapes[1].header.session_key]["B"]["journal"], target)
    with sqlite3.connect(target) as db:
        db.execute(
            "UPDATE execution_events SET payload=json_set(payload,'$.reasons',json('[\"NATIVE_LOSS_COOLDOWN\"]')) WHERE kind='OPTION_ENTRY_MODEL_RISK_PAUSED'"
        )
    sources[tapes[1].header.session_key]["B"]["journal"] = target
    with pytest.raises(ValueError, match="risk pause completion mismatch"):
        export_series(manifest, tapes, sources)


def test_consumed_management_cost_cannot_become_unknown(risk_series, tmp_path):
    import shutil

    from app.options.evaluation_models import EvaluationManifest

    root, tapes, result = risk_series
    manifest = EvaluationManifest.model_validate(result["bundle"]["manifest"])
    d = manifest.arms[3]
    target = tmp_path / "unknown.db"
    shutil.copy2(root / "run" / "D" / "sessions" / (tapes[0].header.session_key + ".db"), target)
    with sqlite3.connect(target) as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "UPDATE execution_model_calls SET cost=NULL WHERE source_key=(SELECT source_key FROM execution_model_calls ORDER BY started_at DESC LIMIT 1)"
        )
        events = db.execute("SELECT * FROM execution_events ORDER BY sequence").fetchall()
        with pytest.raises(ValueError):
            export_loss_control(
                db,
                d.policy.loss_control,
                d.limits.population_id,
                events,
                boundary=tapes[0].header.closes_at,
            )
