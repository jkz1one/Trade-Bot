"""Family risk integration with native fills; seeded candidates are not setup proof."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import owned, quote_at, underlying_at
from test_option_loss_control import attempt, ready, trade
from test_option_loss_model_admission import COSTS, counts
from test_option_loss_reset import KEY, accounting, apply, request

from app.execution.engine import ExecutionBlocked
from app.options.engine import EntryModelBlocked, OptionExecution, fingerprint
from app.options.governor import admit_option
from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy
from app.options.operator import OptionsControl, sign
from app.options.selection import DegenCandidate, SwingCandidate

AFTER = NOW + timedelta(minutes=30)


def policy(global_limit=2, family_limit=1):
    return NativeLossPolicy(
        max_consecutive_losses=global_limit,
        cooldown_seconds=1800,
        families=tuple(
            FamilyLossPolicy(family=f, max_consecutive_losses=family_limit, cooldown_seconds=1800)
            for f in ("DEGEN", "SWING")
        ),
    )


def seed(engine, venue, data, key, family, at):
    """Real governor admission and selected lineage; no claim of scanner acceptance."""
    ready(engine, venue, data, at)
    q, u = quote_at(data, at), underlying_at(data, at)
    with engine.journal.write() as db:
        admission = admit_option(
            data["proposal"],
            q,
            u,
            engine._account(db, at),
            engine._effective_limits(),
            engine._session(q.instrument.contract, at),
            now=at,
        )
        assert admission.outcome == "APPROVED", admission
        cls = SwingCandidate if family == "SWING" else DegenCandidate
        candidate = cls(
            candidate_id=fingerprint({"key": key}),
            symbol=q.instrument.contract.underlying,
            family="SWING_DAILY_BREAKOUT" if family == "SWING" else "ORB_CONTINUATION",
            instrument=q.instrument,
            proposal=data["proposal"],
            admission=admission,
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS execution_option_opportunities(cycle_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,started_at TEXT NOT NULL,inputs_json TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT)"
        )
        result = {
            "candidate_id": candidate.candidate_id,
            "candidates": [candidate.model_dump(mode="json")],
        }
        db.execute(
            "INSERT INTO execution_option_opportunities VALUES(?,?,?,?,?,?)",
            (key, fingerprint(result), at.isoformat(), "{}", "SELECTED", json.dumps(result)),
        )
    return candidate


def family(state, name):
    return next(s for s in state["families"] if s["family"] == name)


def loss(engine, venue, data, key="loss", name="DEGEN", at=NOW):
    seed(engine, venue, data, key, name, at)
    trade(engine, venue, data, key, at)
    return engine.refresh_loss_control(now=at)


def test_other_family_win_does_not_clear_streak_or_block_itself(tmp_path):
    with owned(tmp_path, loss_control=policy(family_limit=2)) as (e, v, d):
        d["proposal"] = d["proposal"].model_copy(update={"max_entry_debit": Decimal(110)})
        first = loss(e, v, d)
        assert family(first, "DEGEN")["consecutive_losses"] == 1
        seed(e, v, d, "swing-win", "SWING", AFTER)
        trade(e, v, d, "swing-win", AFTER, win=True)
        state = e.refresh_loss_control(now=AFTER)
        assert state["consecutive_losses"] == 0
        assert family(state, "DEGEN")["consecutive_losses"] == 1
        assert family(state, "SWING")["consecutive_losses"] == 0
        later = AFTER + timedelta(seconds=1)
        state = loss(e, v, d, "second", at=later)
        assert not state["locked"] and family(state, "DEGEN")["locked"]
        later += timedelta(minutes=30)
        seed(e, v, d, "blocked", "DEGEN", later)
        assert "NATIVE_FAMILY_LOCKED:DEGEN" in attempt(e, d, "blocked", later)["reason"]
        seed(e, v, d, "allowed", "SWING", later)
        assert attempt(e, d, "allowed", later)["status"] == "PREPARED"
        assert family(state, "DEGEN")["consumed_entries"] == 2
        assert family(state, "SWING")["consumed_entries"] == 1


@pytest.mark.parametrize("target", [None, "DEGEN"])
def test_signed_reset_only_clears_selected_scope_and_preserves_economics(tmp_path, target):
    with owned(tmp_path, loss_control=policy(global_limit=1)) as (e, v, d):
        OptionsControl.enroll(e, KEY, now=NOW)
        loss(e, v, d)
        ready(e, v, d, AFTER)
        before = accounting(e)
        command = request(e, loss_family=target)
        result = apply(e, command)
        assert result["status"] == "APPLIED", result
        state = e.journal.report(now=AFTER)["loss_control"]
        assert state["locked"] == (target is not None)
        assert family(state, "DEGEN")["locked"] == (target is None)
        assert state["consumed_entries"] == family(state, "DEGEN")["consumed_entries"] == 1
        assert accounting(e) == before
        snapshot = e.journal.path.read_bytes()
        assert apply(e, command, AFTER + timedelta(days=1)) == result | {"replayed": True}
        assert e.journal.path.read_bytes() == snapshot
        seed(e, v, d, "still-blocked", "DEGEN", AFTER)
        assert attempt(e, d, "still-blocked", AFTER)["status"] == "REJECTED"


def test_reset_other_family_remains_locked(tmp_path):
    with owned(tmp_path, loss_control=policy()) as (e, v, d):
        OptionsControl.enroll(e, KEY, now=NOW)
        loss(e, v, d)
        loss(e, v, d, "swing-loss", "SWING", AFTER)
        later = AFTER + timedelta(minutes=30)
        ready(e, v, d, later)
        result = apply(e, request(e, at=later, loss_family="DEGEN"), later)
        assert result["status"] == "APPLIED", result
        state = e.journal.report(now=later)["loss_control"]
        assert state["locked"] and family(state, "SWING")["locked"]
        assert not family(state, "DEGEN")["locked"]


@pytest.mark.parametrize("case", ["cooldown", "unlocked", "stale", "signature"])
def test_family_reset_rejects_invalid_review(tmp_path, case):
    with owned(tmp_path, loss_control=policy()) as (e, v, d):
        OptionsControl.enroll(e, KEY, now=NOW)
        loss(e, v, d)
        at = NOW if case == "cooldown" else AFTER
        ready(e, v, d, at)
        c = request(e, at=at, loss_family="SWING" if case == "unlocked" else "DEGEN")
        if case == "signature":
            changed = c.model_copy(update={"loss_family": "SWING"})
            with pytest.raises(ValueError):
                OptionsControl(e, KEY).apply(changed, sign(c, KEY), now=at)
        else:
            if case == "stale":
                e.refresh_loss_control(now=at)
            assert apply(e, c, at)["status"] == "REJECTED"
        assert family(e.journal.report(now=at)["loss_control"], "DEGEN")["locked"]


@pytest.mark.parametrize("candidates", ["paused", "missing", "malformed", "mixed"])
def test_prepaid_family_gate_and_mixed_packet_accounting(tmp_path, candidates):
    with owned(tmp_path, loss_control=policy(), cost_policy=COSTS) as (e, v, d):
        loss(e, v, d)
        seed(e, v, d, "next", "DEGEN", AFTER)
        if candidates != "paused":
            swing = seed(e, v, d, "swing", "SWING", AFTER)
            with e.journal.write() as db:
                row = json.loads(
                    db.execute(
                        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key='next'"
                    ).fetchone()[0]
                )
                if candidates == "mixed":
                    row["candidates"].append(swing.model_dump(mode="json"))
                else:
                    row["candidates"] = [] if candidates == "missing" else [None]
                db.execute(
                    "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key='next'",
                    (json.dumps(row),),
                )
        if candidates == "mixed":
            e.begin_model_attempt("next", "a" * 64, now=AFTER)
            assert counts(e) == (1, 2, 1)
            assert e.journal.report(now=AFTER)["economics"]["unknown_calls"] == 1
        else:
            with pytest.raises(EntryModelBlocked, match="NATIVE_FAMILY_MODEL_"):
                e.begin_model_attempt("next", "a" * 64, now=AFTER)
            assert counts(e) == (0, 2, 1)
            assert not e.journal.report(now=AFTER)["halted"]


def test_unlabeled_entry_and_fresh_dispatch_lock_are_blocked(tmp_path):
    with owned(tmp_path, loss_control=policy()) as (e, v, d):
        assert "NATIVE_FAMILY_LINEAGE_REQUIRED" in attempt(e, d, "direct", NOW)["reason"]
        seed(e, v, d, "selected", "DEGEN", NOW)
        p = attempt(e, d, "selected", NOW)
        assert p["status"] == "PREPARED"
        with e.journal.write() as db:
            db.execute(
                "UPDATE execution_option_loss_control SET state_json=json_set(state_json,'$.families[0].locked',json('true'),'$.families[0].consecutive_losses',1)"
            )
        assert (
            asyncio.run(e.dispatch(p["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 0
        with e.journal.read() as db:
            assert db.execute("SELECT attempted_at FROM execution_orders").fetchone()[0] is None


@pytest.mark.parametrize("unknown", [False, True])
def test_real_coordinator_management_retains_family_and_all_costs(tmp_path, monkeypatch, unknown):
    from test_option_execution import intent_for
    from test_option_position_coordination import (
        enter_position,
        management_frame,
        model,
        owned_manager,
    )

    from app.options.models import OptionProposal

    with owned_manager(tmp_path, loss_policy=policy()) as (c, v, times):
        entry = enter_position(c, v, times, monkeypatch)
        model(monkeypatch, c, "MAINTAIN")
        assert asyncio.run(c.cycle(management_frame()))["status"] == "MAINTAIN"
        q = (
            management_frame()
            .quotes[0]
            .model_copy(update={"bid": Decimal("1.03"), "ask": Decimal("1.04")})
        )
        p = c.engine.prepare(
            "exit",
            OptionProposal(
                action="CLOSE",
                contract=entry.instrument.contract,
                thesis="Cost-inclusive family loss",
            ),
            q,
            now=times[0],
        )
        sell = intent_for(c.engine, p["client_id"])
        assert asyncio.run(c.engine.dispatch(sell.client_id, q, now=times[0])) == "OPEN"
        v.fill(sell, sell.quantity, q, times[0], fill_id="exit")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        if unknown:
            with c.engine.journal.write() as db:
                db.execute(
                    "UPDATE execution_model_calls SET cost=NULL WHERE source_key=?",
                    (entry.source_key,),
                )
        state = c.engine.refresh_loss_control(now=times[0])
        assert family(state, "DEGEN")["locked"] == (not unknown)
        assert state["consumed_entries"] == (0 if unknown else 1)
        if unknown:
            assert "NATIVE_LOSS_OUTCOME_PENDING" in state["reasons"]
        else:
            with c.engine.journal.read() as db:
                record = json.loads(
                    db.execute("SELECT record_json FROM execution_option_loss_outcomes").fetchone()[
                        0
                    ]
                )
            assert record["entry_lineage"]["family"] == "DEGEN"
            assert Decimal(record["exit_premium"]) > Decimal(record["entry_premium"])
            assert Decimal(record["net_after_known_execution_and_model_costs"]) < 0
            assert Decimal(record["known_model_cost"]) == Decimal(".00030")
            assert {x["role"] for x in record["model_calls"]} == {"ENTRY", "MANAGEMENT"}


def test_frozen_policy_reopen_and_legacy_omission(tmp_path):
    legacy = NativeLossPolicy(max_consecutive_losses=2, cooldown_seconds=1800)
    assert "families" not in legacy.model_dump(mode="json")
    with pytest.raises(ValidationError):
        NativeLossPolicy.model_validate(
            policy().model_dump() | {"families": (policy().families[0],) * 2}
        )
    with owned(tmp_path, loss_control=policy()) as (e, v, d):
        loss(e, v, d)
        path, limits, frozen = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, frozen, v, now=AFTER) as e:
        assert family(e.journal.report(now=AFTER)["loss_control"], "DEGEN")["locked"]
    with (
        pytest.raises((ValueError, ExecutionBlocked)),
        OptionExecution.open(
            path, limits, frozen.model_copy(update={"loss_control": legacy}), v, now=AFTER
        ),
    ):
        pass


@pytest.mark.parametrize(
    "change",
    [
        {"family": "SCOPE"},
        {"max_consecutive_losses": 3},
        {"cooldown_seconds": 1799},
        {"cooldown_seconds": True},
    ],
)
def test_family_policy_bounds(change):
    with pytest.raises(ValidationError):
        FamilyLossPolicy.model_validate(policy().families[0].model_dump() | change)


def test_family_target_is_signed_reset_only(tmp_path):
    with owned(tmp_path, loss_control=policy()) as (e, _, _):
        OptionsControl.enroll(e, KEY, now=NOW)
        assert "loss_family" not in request(e).model_dump(mode="json")
        for changes in ({"action": "HALT", "loss_family": "DEGEN"}, {"loss_family": "SCOPE"}):
            with pytest.raises(ValidationError):
                request(e, **changes)


def test_family_reset_cli_inbox_and_independent_accounts(tmp_path):
    from pathlib import Path

    from app.options.operator_cli import review, submit
    from app.options.operator_inbox import CommandInbox, save

    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    with (
        owned(tmp_path / "first", loss_control=policy()) as (e, v, d),
        owned(tmp_path / "second", loss_control=policy()) as (other, ov, od),
    ):
        for engine, venue, data in ((e, v, d), (other, ov, od)):
            OptionsControl.enroll(engine, KEY, now=NOW)
            loss(engine, venue, data)
            ready(engine, venue, data, AFTER)
        with pytest.raises(ValueError, match="binding mismatch"):
            apply(other, request(e, loss_family="DEGEN"))
        key = tmp_path / "operator.key"
        key.write_text(KEY.hex())
        key.chmod(0o600)
        for name in ("operator-inbox", "operator-receipts"):
            (e.journal.path.parent / name).mkdir(mode=0o700)
        artifact = tmp_path / "review.json"
        save(artifact, review(e.journal.path, e.limits.population_id, key, now=AFTER))
        before = e.journal.path.read_bytes()
        queued = submit(
            e.journal.path,
            artifact,
            key,
            "RESET_LOSS_LOCK",
            "reviewer",
            "Reviewed family history",
            now=AFTER,
            loss_family="DEGEN",
        )
        assert e.journal.path.read_bytes() == before
        assert CommandInbox(e, key).poll(now=AFTER) is None
        result = json.loads(Path(queued["receipt_file"]).read_text())["result"]
        assert result["status"] == "APPLIED" and result["loss_family"] == "DEGEN"
        assert not family(e.journal.report(now=AFTER)["loss_control"], "DEGEN")["locked"]
        assert family(other.journal.report(now=AFTER)["loss_control"], "DEGEN")["locked"]


def test_family_reset_receipt_failure_rolls_back_state(tmp_path, monkeypatch):
    with owned(tmp_path, loss_control=policy()) as (e, v, d):
        OptionsControl.enroll(e, KEY, now=NOW)
        loss(e, v, d)
        ready(e, v, d, AFTER)
        command = request(e, loss_family="DEGEN")
        before = e.journal.path.read_bytes()
        event = e.journal.event

        def fail(db, now, kind, payload):
            if kind == "OPTIONS_OPERATOR_COMMAND":
                raise RuntimeError("fixture receipt failure")
            return event(db, now, kind, payload)

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="receipt failure"):
            apply(e, command)
        assert e.journal.path.read_bytes() == before
