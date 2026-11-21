"""Post-cost Scope review retains original terms without granting native authority."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from test_option_scope_arbitration import shared
from test_option_scope_arming import refresh
from test_option_scope_watch import ready, revision

from app.execution.economics import UsageEvidence
from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.models import OptionProposal
from app.options.scope_reapproval import compare_terms, review_paid_scope


def admit(c, f, now, key):
    frame, context = refresh(f.scope.frame, now)
    underlying = f.scope.underlying.model_copy(update={"source_at": now, "received_at": now})
    r = c.scope_book.review_admission(
        key,
        "first",
        expected_revision=revision(c.engine),
        now=now,
        frame=frame,
        context=context,
        underlying=underlying,
    )
    assert r["record"]["admission_review"]["eligible"], r
    return c.scope_book.entry_selection("first", expected_revision=r["revision"], now=now)


def paid(c, v, times, f, *, settle=True):
    ready(c.engine, v, times[0])
    old = admit(c, f, times[0], "before-model")
    proposal = OptionProposal(action="HOLD", thesis="Fixture model receipt; no execution authority")
    source = "degen:" + str(int(times[0].timestamp()) // 300)
    args = {
        "original_action_key": "before-model",
        "play_key": "first",
        "model_source_key": source,
        "request_hash": "a" * 64,
        "decision_hash": fingerprint(proposal),
        "now": times[0],
    }
    with c.engine.journal.write() as db:
        c.engine._admit_model_attempt(db, source, args["request_hash"], times[0], None)
    if settle:
        c.engine.record_model_usage(
            source,
            UsageEvidence(
                request_id="fixture-paid-scope",
                model=c.engine.policy.cost_policy.model,
                input_tokens=1000,
                output_tokens=100,
            ),
            proposal,
            now=times[0],
        )
    times[0] += timedelta(seconds=1)
    args["now"] = times[0]
    return old, args


def review(c, args):
    with c.engine.journal.read() as db:
        return review_paid_scope(
            c.engine,
            db,
            c.scope_policy.watch,
            expected_revision=c.engine.journal.revision(db),
            **args,
        )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_settled_cost_requires_new_admission_and_keeps_original_terms(tmp_path, right):
    with shared(tmp_path, right=right, costs=True) as (c, v, times, f):
        old, args = paid(c, v, times, f)
        with pytest.raises(ExecutionBlocked, match="FRESH_ADMISSION"):
            review(c, args)
        fresh = admit(c, f, times[0], "after-model")
        before = revision(c.engine)
        receipt = review(c, args)
        assert receipt == review(c, args)
        assert revision(c.engine) == before
        assert receipt["authority"] is receipt["live_enabled"] is False
        assert receipt["original_source_key"] != receipt["fresh_source_key"]
        assert receipt["original_packet_hash"] == fingerprint(old)
        assert receipt["fresh_packet_hash"] == fingerprint(fresh)
        assert datetime.fromisoformat(receipt["valid_until"]) == datetime.fromisoformat(
            old["binding"]["valid_until"]
        )
        assert Decimal(receipt["model_charge"]["cost"]) > 0
        assert Decimal(fresh["account"]["total_loss_available"]) < Decimal(
            old["account"]["total_loss_available"]
        )
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_orders").fetchone()
            assert not db.execute("SELECT 1 FROM execution_option_decisions").fetchone()
        # A review is not the shared coordinator selection or authority to buy.
        result = c.scope_book.prepare_entry("first", expected_revision=before, now=times[0])
        assert result["status"] == "REJECTED"


@pytest.mark.parametrize(
    "damage",
    ["request", "decision", "source", "cost", "model", "audit", "unknown_other", "original"],
)
def test_foreign_unknown_or_modified_cost_and_original_evidence_rejected(tmp_path, damage):
    with shared(tmp_path, costs=True) as (c, v, times, f):
        _, args = paid(c, v, times, f)
        admit(c, f, times[0], "after-model")
        if damage in {"request", "decision"}:
            args[damage + "_hash"] = "b" * 64
        elif damage == "source":
            args["model_source_key"] = "foreign"
        else:
            with c.engine.journal.write() as db:
                if damage == "cost":
                    db.execute("UPDATE execution_model_calls SET cost='0'")
                elif damage == "model":
                    db.execute(
                        "UPDATE execution_model_calls SET usage_json=json_set(usage_json,'$.model','foreign')"
                    )
                elif damage == "audit":
                    db.execute(
                        "DELETE FROM execution_events WHERE kind='OPTION_MODEL_USAGE_RECORDED'"
                    )
                elif damage == "unknown_other":
                    db.execute(
                        "INSERT INTO execution_model_calls VALUES('unresolved-management',?, ?,NULL,NULL,NULL,NULL)",
                        ("b" * 64, times[0].isoformat()),
                    )
                else:
                    db.execute(
                        "UPDATE execution_option_scope_watch_actions SET result_json=json_set(result_json,'$.record.geometry.target_one','9999') WHERE action_key='before-model'"
                    )
        with pytest.raises((ExecutionBlocked, ValueError)):
            review(c, args)


def test_intervening_event_stales_fresh_admission(tmp_path):
    with shared(tmp_path, costs=True) as (c, v, times, f):
        _, args = paid(c, v, times, f)
        admit(c, f, times[0], "after-model")
        with c.engine.journal.write() as db:
            c.engine.journal.event(db, times[0], "FIXTURE_INTERVENING_EVENT", {})
        with pytest.raises(ExecutionBlocked, match="FRESH_ADMISSION"):
            review(c, args)


def test_unknown_call_does_not_become_free(tmp_path):
    with shared(tmp_path, costs=True) as (c, v, times, f):
        _, args = paid(c, v, times, f, settle=False)
        result = c.scope_book.review_admission(
            "after-model",
            "first",
            expected_revision=revision(c.engine),
            now=times[0],
            frame=f.scope.frame,
            context=f.scope.context,
            underlying=f.scope.underlying,
        )
        assert not result["record"]["admission_review"]["eligible"]
        with pytest.raises((ExecutionBlocked, ValueError)):
            review(c, args)
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None


@pytest.mark.parametrize(
    "damage",
    [
        "quantity",
        "price",
        "debit",
        "fees",
        "loss",
        "exit_cash",
        "targets",
        "protection",
        "deadline",
        "account",
        "quote",
        "underlying",
        "identity",
        "call",
        "same_action",
    ],
)
def test_original_envelope_cannot_be_replaced_by_new_admission(tmp_path, damage):
    with shared(tmp_path, costs=True) as (c, v, times, f):
        old, _ = paid(c, v, times, f)
        new = deepcopy(admit(c, f, times[0], "after-model"))
        when = times[0]
        if damage == "quantity":
            new["admission"]["quantity"] -= 1
        elif damage in {"price", "debit", "fees", "loss", "exit_cash"}:
            key = {
                "price": "limit_price",
                "debit": "entry_debit",
                "fees": "reserved_exit_fees",
                "loss": "full_premium_loss",
                "exit_cash": "minimum_exit_cash_change",
            }[damage]
            new["admission"][key] = str(
                Decimal(old["admission"][key]) + (-1 if damage == "exit_cash" else 1)
            )
        elif damage == "targets":
            new["management"]["target_exit_schedule"]["steps"][0]["underlying_price"] = "9999"
        elif damage == "protection":
            new["entry_time_protection"]["exit_by"] = (when + timedelta(days=1)).isoformat()
        elif damage == "deadline":
            when = datetime.fromisoformat(old["binding"]["valid_until"])
            new["binding"]["valid_until"] = (when + timedelta(minutes=5)).isoformat()
        elif damage in {"quote", "underlying"}:
            new[damage]["source_at"] = (when - timedelta(seconds=2)).isoformat()
        elif damage == "account":
            new["account"]["captured_at"] = (when - timedelta(minutes=5)).isoformat()
        elif damage == "identity":
            new["binding"]["population_id"] = "other"
        elif damage == "call":
            new["binding"]["original_call_hash"] = "0" * 64
        else:
            new["binding"]["action_key"] = old["binding"]["action_key"]
        with pytest.raises(ExecutionBlocked):
            compare_terms(old, new, now=when)


def test_later_fresh_lease_cannot_extend_original_deadline(tmp_path):
    with shared(tmp_path, costs=True) as (c, v, times, f):
        old, _ = paid(c, v, times, f)
        new = deepcopy(admit(c, f, times[0], "after-model"))

        original_deadline = datetime.fromisoformat(old["binding"]["valid_until"])
        new["binding"]["valid_until"] = (original_deadline + timedelta(seconds=5)).isoformat()
        assert compare_terms(old, new, now=times[0]) == original_deadline


def test_other_owner_cannot_use_review_or_charge(tmp_path):
    with (
        shared(tmp_path / "a", costs=True) as (a, va, ta, fa),
        shared(tmp_path / "b", costs=True) as (b, vb, tb, fb),
    ):
        _, args = paid(a, va, ta, fa)
        admit(a, fa, ta[0], "after-model")
        assert review(a, args)["status"] == "REVIEWED"
        ready(b.engine, vb, tb[0])
        admit(b, fb, tb[0], "before-model")
        tb[0] += timedelta(seconds=1)
        admit(b, fb, tb[0], "after-model")
        with pytest.raises(ExecutionBlocked, match="SETTLED_COST_REQUIRED"):
            review(b, args)
        with b.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_model_calls").fetchone()


@pytest.mark.parametrize(
    "damage",
    [
        "attempt_before_original",
        "settlement_after_fresh",
        "reordered_times",
        "duplicated_settlement",
    ],
)
def test_charge_must_be_between_both_immutable_admissions(tmp_path, damage):
    import json

    with shared(tmp_path, costs=True) as (c, v, times, f):
        old, args = paid(c, v, times, f)
        fresh = admit(c, f, times[0], "after-model")
        with c.engine.journal.write() as db:
            if damage == "attempt_before_original":
                db.execute(
                    "UPDATE execution_events SET sequence=-1 WHERE kind='OPTION_MODEL_ATTEMPT_ADMITTED'"
                )
            elif damage == "settlement_after_fresh":
                db.execute(
                    "UPDATE execution_events SET occurred_at=? WHERE kind='OPTION_MODEL_USAGE_RECORDED'",
                    ((times[0] + timedelta(seconds=1)).isoformat(),),
                )
            elif damage == "reordered_times":
                db.execute(
                    "UPDATE execution_events SET occurred_at=? WHERE kind='OPTION_MODEL_USAGE_RECORDED'",
                    ((times[0] - timedelta(seconds=2)).isoformat(),),
                )
            else:
                payload = db.execute(
                    "SELECT payload FROM execution_events WHERE kind='OPTION_MODEL_USAGE_RECORDED'"
                ).fetchone()[0]
                # Duplicate before the final action so latest revision remains valid.
                db.execute(
                    "INSERT INTO execution_events(sequence,occurred_at,kind,payload) VALUES(-1,?,'OPTION_MODEL_USAGE_RECORDED',?)",
                    (times[0].isoformat(), json.dumps(json.loads(payload))),
                )
        assert old["binding"]["revision"] < fresh["binding"]["revision"]
        with pytest.raises(ExecutionBlocked, match="COST_"):
            review(c, args)
