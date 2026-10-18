"""Earlier deterministic deadlines survive native fills, scales, restart and export."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import intent_for, ledger, owned, quote_at, underlying_at
from test_option_partial_close import close, fill
from test_option_position_outcome import read_owned
from test_option_target_exits import at_target, schedule

from app.execution.engine import ExecutionBlocked
from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.lifecycle import EntryTimeProtection, OptionIntent, OptionPosition
from app.options.models import OptionProposal

ENROLLED = {"entry_time_protection": "tighten-only-v1"}
DEADLINE = NOW + timedelta(seconds=10)


def protection(at=DEADLINE):
    return EntryTimeProtection(exit_by=at)


def prepare(e, d, at=DEADLINE, **kwargs):
    return e.prepare(
        "entry",
        d["proposal"],
        d["quote"],
        d["underlying"],
        now=NOW,
        entry_time_protection=protection(at),
        **kwargs,
    )


def enter(e, v, d, **kwargs):
    out = prepare(e, d, **kwargs)
    assert out["status"] == "PREPARED", out
    buy = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch(buy.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
    fill(e, v, buy, d["quote"])
    return buy


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_exact_deadline_latches_without_quotes_and_recovery_exits_owned_quantity(tmp_path, right):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        buy = enter(e, v, d)
        assert buy.exit_at == buy.order_expires_at == DEADLINE
        assert buy.approval_expires_at <= DEADLINE
        assert buy.approved_full_premium_loss == Decimal("414.20")
        assert ledger(e).position.entry_time_protection == protection()
        assert e.assess(None, None, now=DEADLINE - timedelta(microseconds=1))["exit_reason"] is None
        assert e.reconcile(v.snapshot(DEADLINE), now=DEADLINE)["reconciled"]
        out = e.assess(None, None, now=DEADLINE)
        assert out["exit_reason"] == "TIME_EXIT"
        assert ledger(e).position.exit_required_at == DEADLINE
        at = DEADLINE + timedelta(seconds=1)
        q, u = quote_at(d, at), underlying_at(d, at)
        out = asyncio.run(e.protective_tick(q, u, now=at))
        assert out["status"] == "OPEN" and out["exit_reason"] == "TIME_EXIT", out
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == buy.quantity and sell.entry_time_protection is None
        assert sell.order_expires_at > DEADLINE  # Deadline cannot prevent the owned exit.
        fill(e, v, sell, q, at)
        outcome = read_owned(e, buy)
        assert outcome["status"] == "COMPLETE"
        assert Decimal(outcome["execution_fees"]) == Decimal("7.20")
        assert (
            Decimal(outcome["net_after_known_execution_and_model_costs"])
            == ledger(e).cash - e.policy.capital
        )
        with e.journal.read() as db:
            for client in (buy.client_id, sell.client_id):
                row = db.execute(
                    "SELECT * FROM execution_orders WHERE client_id=?", (client,)
                ).fetchone()
                assert order_attribution(db, row)[
                    "entry_time_protection"
                ] == protection().model_dump(mode="json")


def test_scale_runner_and_restart_preserve_deadline_and_fee_accounting(tmp_path):
    with owned(
        tmp_path, partial_closes="whole-contract-v1", target_exits="frozen-targets-v1", **ENROLLED
    ) as (e, v, d):
        buy = enter(e, v, d, target_exit_schedule=schedule())
        out = asyncio.run(e.protective_tick(d["quote"], at_target(d), now=NOW))
        scale = intent_for(e, out["client_id"])
        fill(e, v, scale, d["quote"])
        assert ledger(e).position.quantity == 2
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=DEADLINE) as e:
        assert ledger(e).position.exit_at == DEADLINE
        assert ledger(e).position.entry_time_protection == protection()
        q, u = quote_at(d, DEADLINE), underlying_at(d, DEADLINE)
        out = asyncio.run(e.protective_tick(q, u, now=DEADLINE))
        assert out["exit_reason"] == "TIME_EXIT" and out["status"] == "OPEN"
        runner = intent_for(e, out["client_id"])
        assert runner.quantity == 2
        fill(e, v, runner, q, DEADLINE)
        assert Decimal(read_owned(e, buy)["execution_fees"]) == Decimal("8.20")


@pytest.mark.parametrize("attempted", [False, True])
def test_deadline_preempts_only_unattempted_scale_and_preserves_attempted_reservation(
    tmp_path, attempted
):
    with owned(tmp_path, partial_closes="whole-contract-v1", **ENROLLED) as (e, v, d):
        buy = enter(e, v, d)
        out = e.prepare("scale", close(buy, 2), d["quote"], d["underlying"], now=NOW)
        scale = intent_for(e, out["client_id"])
        if attempted:
            assert (
                asyncio.run(e.dispatch(scale.client_id, d["quote"], d["underlying"], now=NOW))
                == "OPEN"
            )
        q, u = quote_at(d, DEADLINE), underlying_at(d, DEADLINE)
        result = asyncio.run(e.protective_tick(q, u, now=DEADLINE))
        assert ledger(e).position.exit_reason == "TIME_EXIT"
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (scale.client_id,)
            ).fetchone()
        if attempted:
            assert row["status"] == "OPEN" and row["active_lock"] == 1
            assert v.submit_count == 2
            v.record_terminal(scale.client_id, "CANCELED", DEADLINE)
            assert e.reconcile(v.snapshot(DEADLINE), now=DEADLINE)["reconciled"]
            result = asyncio.run(e.protective_tick(q, u, now=DEADLINE))
            assert result["status"] == "EXIT_REVIEW_REQUIRED"
            assert v.submit_count == 2 and ledger(e).position.quantity == 4
            return
        else:
            assert row["status"] == "REJECTED" and row["attempted_at"] is None
        assert result["status"] == "OPEN", result
        assert intent_for(e, result["client_id"]).quantity == 4


def test_partial_entry_cannot_fill_after_deadline_and_owned_exit_waits_for_receipt(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d)
        buy = intent_for(e, out["client_id"])
        assert (
            asyncio.run(e.dispatch(buy.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
        )
        v.fill(buy, 1, d["quote"], NOW, fill_id="partial")
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        q, u = quote_at(d, DEADLINE), underlying_at(d, DEADLINE)
        with pytest.raises(ValueError, match="outside ordered DAY lifetime"):
            v.fill(buy, 3, q, DEADLINE, fill_id="too-late")
        asyncio.run(e.protective_tick(q, u, now=DEADLINE))
        assert ledger(e).position.exit_reason == "TIME_EXIT" and v.submit_count == 1
        v.record_terminal(buy.client_id, "EXPIRED", DEADLINE)
        assert e.reconcile(v.snapshot(DEADLINE), now=DEADLINE)["reconciled"]
        out = asyncio.run(e.protective_tick(q, u, now=DEADLINE))
        assert out["status"] == "OPEN"
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 1
        fill(e, v, sell, q, DEADLINE)
        assert read_owned(e, buy)["status"] == "COMPLETE"


@pytest.mark.parametrize("seconds", [-1, 0])
def test_elapsed_deadline_rejects_without_order(tmp_path, seconds):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d, NOW + timedelta(seconds=seconds))
        assert out["status"] == "REJECTED" and out["reason"] == "OPTION_ENTRY_TIME_EXPIRED"
        assert out["client_id"] is None and v.submit_count == 0


def test_near_deadline_bounds_approval_and_dispatch_cannot_reuse_it(tmp_path):
    until = NOW + timedelta(microseconds=1)
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d, until)
        buy = intent_for(e, out["client_id"])
        assert buy.approval_expires_at == buy.order_expires_at == buy.exit_at == until
        assert (
            asyncio.run(
                e.dispatch(buy.client_id, quote_at(d, until), underlying_at(d, until), now=until)
            )
            == "REJECTED"
        )
        assert v.submit_count == 0


def test_later_requested_deadline_cannot_extend_owner_session_or_expiry(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, _v, d):
        until = NOW + timedelta(days=1)
        out = prepare(e, d, until)
        buy = intent_for(e, out["client_id"])
        assert buy.exit_at == NOW.replace(hour=19, minute=45)
        assert buy.order_expires_at == buy.exit_at
        assert buy.entry_time_protection.exit_by == until
        assert (
            asyncio.run(e.dispatch(buy.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
        )


@pytest.mark.parametrize("origin", ["MODEL", "PROTECTIVE"])
def test_untrusted_origin_cannot_attach_time_terms(tmp_path, origin):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d, origin=origin)
        assert out["status"] == "REJECTED" and v.submit_count == 0


def test_hold_cannot_carry_entry_time_terms(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, _v, _d):
        out = e.prepare(
            "hold",
            OptionProposal(action="HOLD", thesis="wait"),
            now=NOW,
            entry_time_protection=protection(),
        )
        assert out["status"] == "REJECTED" and out["reason"] == "OPTION_ENTRY_TIME_NOT_ENROLLED"


def test_opt_in_frozen_and_legacy_encoding_unchanged(tmp_path):
    with owned(tmp_path) as (e, v, d):
        assert "entry_time_protection" not in e.policy.model_dump()
        out = prepare(e, d)
        assert out["reason"] == "OPTION_ENTRY_TIME_NOT_ENROLLED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(path, limits, policy.model_copy(update=ENROLLED), v, now=NOW),
    ):
        pass


@pytest.mark.parametrize("damage", ["intent", "approval", "both", "owner_cutoff"])
def test_dispatch_rechecks_original_decision_and_stricter_owner_cutoff(tmp_path, damage):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d, NOW + timedelta(days=1) if damage == "owner_cutoff" else DEADLINE)
        with e.journal.write() as db:
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            for field in ("intent_json", "approval_json"):
                if damage in {"intent", "approval"} and not field.startswith(damage):
                    continue
                data = json.loads(row[field])
                if damage == "owner_cutoff":
                    if field != "intent_json":
                        continue
                    data["exit_at"] = data["order_expires_at"] = NOW.replace(
                        hour=19, minute=50
                    ).isoformat()
                else:
                    data["entry_time_protection"]["exit_by"] = (
                        DEADLINE + timedelta(seconds=10)
                    ).isoformat()
                db.execute(f"UPDATE execution_orders SET {field}=?", (json.dumps(data),))
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 0


def test_source_retry_cannot_replace_deadline(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, _v, d):
        original = prepare(e, d)
        assert prepare(e, d) == original
        with pytest.raises(ExecutionBlocked, match="OPTION_SOURCE_IDENTITY_CONFLICT"):
            prepare(e, d, DEADLINE + timedelta(seconds=1))


def test_reconciliation_rejects_changed_position_deadline_evidence(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter(e, v, d)
        at = NOW + timedelta(seconds=1)
        snap = v.snapshot(at)
        p = snap.position.model_copy(
            update={"entry_time_protection": protection(DEADLINE + timedelta(seconds=1))}
        )
        out = e.reconcile(snap.model_copy(update={"position": p}), now=at)
        assert not out["reconciled"]


def test_independent_owners_keep_separate_deadlines(tmp_path):
    with (
        owned(tmp_path / "a", **ENROLLED) as (a, va, da),
        owned(tmp_path / "b", **ENROLLED) as (b, vb, db),
    ):
        enter(a, va, da)
        enter(b, vb, db, at=DEADLINE + timedelta(seconds=10))
        assert a.reconcile(va.snapshot(DEADLINE), now=DEADLINE)["reconciled"]
        assert b.reconcile(vb.snapshot(DEADLINE), now=DEADLINE)["reconciled"]
        assert (
            a.assess(quote_at(da, DEADLINE), underlying_at(da, DEADLINE), now=DEADLINE)[
                "exit_reason"
            ]
            == "TIME_EXIT"
        )
        assert (
            b.assess(quote_at(db, DEADLINE), underlying_at(db, DEADLINE), now=DEADLINE)[
                "exit_reason"
            ]
            is None
        )


def test_record_contracts_reject_extended_position_and_non_buy_terms(tmp_path):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        buy = enter(e, v, d)
        with pytest.raises(ValidationError, match="deterministic buy"):
            OptionIntent.model_validate(buy.model_dump() | {"side": "SELL"})
        with pytest.raises(ValidationError, match="frozen entry deadline"):
            OptionPosition.model_validate(
                ledger(e).position.model_dump() | {"exit_at": DEADLINE + timedelta(seconds=1)}
            )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_native_export_retains_deadline_and_portable_accounting_rejects_tampering(
    tmp_path, monkeypatch, right
):
    import test_option_target_export as export

    from app.options.evaluation import evaluate

    monkeypatch.setattr(export, "POLICY", export.POLICY | ENROLLED)
    row, bundle = export.exported(
        export.native_boundary(tmp_path, right, entry_time=protection()),
        data_cost=".01",
        host_cost=".02",
    )
    assert row.closing.position.entry_time_protection == protection()
    report = evaluate(bundle)["sessions"][0]["arms"]["A"]
    assert report["accounting_verified"] and report["net_change"] is None, report
    p = row.closing.position.model_copy(
        update={"entry_time_protection": protection(DEADLINE + timedelta(seconds=1))}
    )
    damaged = row.model_copy(update={"closing": row.closing.model_copy(update={"position": p})})
    result = evaluate(bundle.model_copy(update={"evidence": (damaged,)}))["sessions"][0]["arms"][
        "A"
    ]
    assert not result["accounting_verified"] and result["net_change"] is None


def test_earlier_expiry_guard_wins_and_time_write_rolls_back(tmp_path, monkeypatch):
    import test_option_execution as native

    original = native.configuration

    def earlier_expiry(*args, **kwargs):
        data, limits, policy = original(*args, **kwargs)
        return data, limits, policy.model_copy(update={"expiry_guard_seconds": 1200})

    monkeypatch.setattr(native, "configuration", earlier_expiry)
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        until = NOW + timedelta(days=1)
        event = e.journal.event

        def fail(*args, **kwargs):
            event(*args, **kwargs)
            raise RuntimeError("time audit failure")

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="time audit failure"):
            prepare(e, d, until)
        with e.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM execution_option_decisions").fetchone()[0] == 0
        monkeypatch.setattr(e.journal, "event", event)
        out = prepare(e, d, until)
        buy = intent_for(e, out["client_id"])
        assert buy.exit_at == d["quote"].instrument.contract.last_trading_at - timedelta(
            seconds=1200
        )
        assert (
            asyncio.run(e.dispatch(buy.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
        )
        assert v.submit_count == 1


def test_scope_deadline_handoff_cannot_enable_entry_even_with_owner_time_enrollment(tmp_path):
    from test_option_scope_entry import policy, select
    from test_option_scope_management import admitted
    from test_option_scope_watch import owned as scope_owned

    with scope_owned(tmp_path, enroll=False, execution_policy_changes=ENROLLED) as (e, v, _):
        book, _, f, _, u, now = admitted(e, v, p=policy())
        selected = select(book, now)
        deadline = EntryTimeProtection.model_validate(selected["entry_time_protection"])
        assert deadline.exit_by == f.session.protect_at
        out = e.prepare(
            "scope-time-bound",
            OptionProposal.model_validate(selected["proposal"]),
            f.quote,
            u,
            now=now,
            entry_time_protection=deadline,
        )
        assert out["status"] == "REJECTED"
        assert out["reason"] == "SCOPE_NATIVE_EXECUTION_NOT_ENROLLED"
        assert out["client_id"] is None and v.submit_count == 0
