"""Scope consumes exact admissions into native PAPER orders and full-cost loss controls."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_execution import intent_for
from test_option_scope_entry import policy as research_policy
from test_option_scope_management import admitted
from test_option_scope_observer import observer
from test_option_scope_watch import owned, revision

from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy
from app.options.scope_watch import ScopeWatchPolicy


def execution_policy():
    return {
        "scope_execution": "scope-native-v1",
        "partial_closes": "whole-contract-v1",
        "target_exits": "frozen-target-milestones-v2",
        "target_stops": "frozen-target-stops-v1",
        "target_entry_reference": "fill-weighted-underlying-v1",
        "entry_premium_protection": "tighten-only-v1",
        "entry_time_protection": "tighten-only-v1",
        "loss_control": NativeLossPolicy(
            max_consecutive_losses=2,
            cooldown_seconds=1800,
            families=(
                FamilyLossPolicy(family="SCOPE", max_consecutive_losses=2, cooldown_seconds=1800),
            ),
        ),
    }


def policy():
    return ScopeWatchPolicy.model_validate(
        research_policy().model_dump()
        | {
            "native_execution": "scope-native-v1",
            "direction_reset": {"cooldown_seconds": 600, "confirmation_bars": 2},
        }
    )


def prepared(e, v, right="CALL", quantity=2):
    book, _out, f, _c, u, now = admitted(e, v, right, quantity, p=policy())
    result = book.prepare_entry("first", expected_revision=revision(e), now=now)
    assert result["status"] == "PREPARED", result
    return book, intent_for(e, result["client_id"]), f, u, now


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("quantity", [1, 2, 3])
def test_native_entry_fills_and_owned_lifecycle(tmp_path, right, quantity):
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, intent, f, u, now = prepared(e, v, right, quantity)
        assert intent.entry_lineage.family == "SCOPE"
        assert intent.quantity == quantity
        assert book.snapshot()["watches"][0]["status"] == "ORDER_WORKING"
        assert asyncio.run(e.dispatch(intent.client_id, f.quote, u, now=now)) == "OPEN"
        v.fill(intent, quantity, f.quote, now, fill_id="scope-entry-fill", underlying=u)
        assert e.reconcile(v.snapshot(now), now=now)["reconciled"]
        assert book.snapshot()["watches"][0]["status"] == "POSITION_OPEN"
        result = observer(e, now).report()
        assert result["status"] == "OK", result
        assert result["scope"]["status"] == "NATIVE_PAPER"
        assert result["scope"]["active_watch"]["native_execution"]["client_id"] == intent.client_id


def filled(e, v, right="CALL", quantity=2):
    book, buy, f, u, now = prepared(e, v, right, quantity)
    assert asyncio.run(e.dispatch(buy.client_id, f.quote, u, now=now)) == "OPEN"
    v.fill(buy, quantity, f.quote, now, fill_id="entry-fill", underlying=u)
    assert e.reconcile(v.snapshot(now), now=now)["reconciled"]
    return book, buy, f, u, now


def sell(e, v, buy, q, u, now, *, key="close", quantity=None):
    from test_option_partial_close import close

    result = e.prepare(key, close(buy, quantity), q, u, now=now)
    assert result["status"] == "PREPARED", result
    intent = intent_for(e, result["client_id"])
    assert asyncio.run(e.dispatch(intent.client_id, q, u, now=now)) == "OPEN"
    v.fill(intent, intent.quantity, q, now, fill_id=key + "-fill", underlying=u)
    assert e.reconcile(v.snapshot(now), now=now)["reconciled"]
    return intent


def test_scale_runner_full_cost_loss_and_persistent_cooldown(tmp_path):
    from test_option_position_outcome import read_owned

    from app.options.engine import OptionExecution
    from app.options.scope_watch import ScopeWatchBook

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, buy, f, u, now = filled(e, v)
        sell(e, v, buy, f.quote, u, now, key="scale", quantity=1)
        assert book.snapshot()["watches"][0]["status"] == "POSITION_OPEN"
        assert e.refresh_loss_control(now=now)["consumed_entries"] == 0
        sell(e, v, buy, f.quote, u, now)
        assert book.snapshot()["watches"][0]["status"] == "CLOSED"
        outcome = read_owned(e, buy)
        state = e.refresh_loss_control(now=now)
        assert outcome["status"] == "COMPLETE"
        assert outcome["entry_lineage"]["family"] == "SCOPE"
        assert Decimal(outcome["execution_fees"]) > 0
        assert state["families"][0]["consecutive_losses"] == 1
        assert state["families"][0]["consumed_entries"] == 1
        assert state["families"][0]["cooldown_until"] == (
            now + timedelta(minutes=30)
        ).isoformat().replace("+00:00", "Z")
        assert observer(e, now).report()["status"] == "OK"
        path, limits, ep = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, ep, v, now=now) as e:
        book = ScopeWatchBook(e, policy(), now=now)
        assert book.snapshot()["watches"][0]["status"] == "CLOSED"
        assert e.refresh_loss_control(now=now)["consumed_entries"] == 1


@pytest.mark.parametrize("case", ["expired", "target", "stop", "wrong_contract", "price"])
def test_dispatch_refresh_rejects_without_attempt_and_never_rearms(tmp_path, case):
    from app.execution.engine import ExecutionBlocked

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, buy, f, u, now = prepared(e, v)
        q = f.quote
        if case == "expired":
            now = buy.approval_expires_at
        elif case in {"target", "stop"}:
            price = (
                buy.target_exit_schedule.steps[0].underlying_price
                if case == "target"
                else buy.original_underlying_invalidation
            )
            u = u.model_copy(update={"bid": price, "ask": price})
        elif case == "wrong_contract":
            q = q.model_copy(
                update={"instrument": q.instrument.model_copy(update={"instrument_id": "wrong"})}
            )
        else:
            q = q.model_copy(update={"bid": Decimal("2.1"), "ask": Decimal("2.1")})
        assert asyncio.run(e.dispatch(buy.client_id, q, u, now=now)) == "REJECTED"
        assert v.submit_count == 0
        assert book.snapshot()["watches"][0]["status"] == "ENDED_UNFILLED"
        assert e.refresh_loss_control(now=now)["consumed_entries"] == 0
        with pytest.raises(ExecutionBlocked):
            book.prepare_entry("first", expected_revision=revision(e), now=now)


def test_four_contract_missing_objective_stays_blocked(tmp_path):
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, _, _, _, _, now = admitted(e, v, quantity=4, p=policy())
        out = book.prepare_entry("first", expected_revision=revision(e), now=now)
        assert out["status"] == "REJECTED"
        assert out["reason"] == "SCOPE_THIRD_TARGET_UNSPECIFIED"
        assert book.snapshot()["watches"][0]["status"] == "WATCHING"
        assert v.submit_count == 0


def test_consumption_rolls_back_order_decision_receipt_and_watch(tmp_path, monkeypatch):
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, _, _, _, _, now = admitted(e, v, p=policy())
        before = book.snapshot()
        event = e.journal.event

        def fail(db, at, kind, payload, client_id=None):
            event(db, at, kind, payload, client_id)
            if kind == "SCOPE_ENTRY_CONSUMED":
                raise RuntimeError("injected")

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="injected"):
            book.prepare_entry("first", expected_revision=revision(e), now=now)
        assert book.snapshot() == before
        with e.journal.read() as db:
            for table in (
                "execution_orders",
                "execution_option_decisions",
                "execution_option_scope_entries",
            ):
                assert db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_partial_entry_then_canceled_remainder_keeps_position_and_consumes_one_play(tmp_path):
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, buy, f, u, now = prepared(e, v, quantity=3)
        assert asyncio.run(e.dispatch(buy.client_id, f.quote, u, now=now)) == "OPEN"
        v.fill(buy, 1, f.quote, now, fill_id="partial", underlying=u)
        assert e.reconcile(v.snapshot(now), now=now)["reconciled"]
        v.record_terminal(buy.client_id, "CANCELED", now)
        assert e.reconcile(v.snapshot(now), now=now)["reconciled"]
        assert book.snapshot()["watches"][0]["status"] == "POSITION_OPEN"
        sell(e, v, buy, f.quote, u, now)
        assert book.snapshot()["watches"][0]["status"] == "CLOSED"
        assert e.refresh_loss_control(now=now)["consumed_entries"] == 1


def second_session_entry(e, v, book):
    from datetime import date, datetime

    from test_option_scope import AT
    from test_option_scope_arming import refresh
    from test_option_scope_contract import data
    from test_option_scope_watch import choice, ready

    from app.options.models import UnderlyingQuote
    from app.options.scope import ScopePreflightInput

    shift = timedelta(days=3)

    def shifted(value):
        if isinstance(value, dict):
            return {k: shifted(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [shifted(v) for v in value]
        if isinstance(value, (datetime, date)):
            return value + shift
        return value

    f = ScopePreflightInput.model_validate(shifted(data()[0].model_dump()))
    at = AT + shift
    f, c = refresh(f, at)
    ready(e, v, at)
    book.call(
        "second",
        choice("CALL", "trend_pullback_continuation"),
        f,
        c,
        now=at,
        expected_revision=revision(e),
    )
    for seconds in range(0, 61, 10):
        now = at + timedelta(seconds=seconds)
        ready(e, v, now)
        fresh, c = refresh(f, now)
        if seconds < 60:
            book.observe_arming(
                "second-" + str(seconds),
                "second",
                frame=fresh,
                context=c,
                now=now,
                expected_revision=revision(e),
            )
        else:
            price = fresh.histories[0].bars[-1].close
            u = UnderlyingQuote(
                symbol="SPX",
                source=e.limits.underlying_source,
                source_at=now,
                received_at=now,
                complete=True,
                entitlement="REALTIME",
                bid=price,
                ask=price,
            )
            result = book.review_admission(
                "second-review",
                "second",
                frame=fresh,
                context=c,
                underlying=u,
                now=now,
                expected_revision=revision(e),
            )
            assert result["record"]["admission_review"]["eligible"], result
    out = book.prepare_entry("second", expected_revision=revision(e), now=now)
    assert out["status"] == "PREPARED", out
    buy = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch(buy.client_id, fresh.quote, u, now=now)) == "OPEN"
    v.fill(buy, buy.quantity, fresh.quote, now, fill_id="second-entry-fill", underlying=u)
    assert e.reconcile(v.snapshot(now), now=now)["reconciled"]
    return buy, fresh, u, now


def test_two_actual_losses_lock_scope_and_signed_reset_preserves_global_history(tmp_path):
    from test_option_loss_reset import KEY, accounting, apply, request
    from test_option_scope_watch import ready

    from app.options.operator import OptionsControl, sign
    from app.options.scope_execution_export import (
        export_scope_execution,
        verify_scope_execution_export,
    )

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, buy, f, u, now = filled(e, v)
        sell(e, v, buy, f.quote, u, now)
        buy2, f2, u2, at = second_session_entry(e, v, book)
        sell(e, v, buy2, f2.quote, u2, at, key="second-close")
        state = e.refresh_loss_control(now=at)
        assert state["locked"] and state["families"][0]["locked"]
        assert state["families"][0]["consecutive_losses"] == 2
        OptionsControl.enroll(e, KEY, now=at)
        early = request(e, at=at, loss_family="SCOPE")
        assert apply(e, early, at)["status"] == "REJECTED"
        later = at + timedelta(minutes=30)
        ready(e, v, later)
        before = accounting(e)
        command = request(e, at=later, loss_family="SCOPE")
        bad = command.model_copy(update={"reason": "Unsigned change"})
        with pytest.raises(ValueError, match="authentication"):
            OptionsControl(e, KEY).apply(bad, sign(command, KEY), now=later)
        out = apply(e, command, later)
        assert out["status"] == "APPLIED", out
        assert accounting(e) == before
        state = e.refresh_loss_control(now=later)
        assert state["locked"] and state["consecutive_losses"] == 2
        assert (
            not state["families"][0]["locked"] and state["families"][0]["consecutive_losses"] == 0
        )
        assert state["families"][0]["consumed_entries"] == 2
        exported = export_scope_execution(e.journal, now=later, data_cost=".01", host_cost=".02")
        assert len(exported["report"]["loss_control"]["resets"]) == 1
        assert (
            verify_scope_execution_export(exported, exported["export_hash"])["status"]
            == "VERIFIED_NATIVE_ACCOUNTING"
        )
        assert len(book.snapshot()["watches"]) == 2


def test_scope_targets_runner_deadline_and_fill_reference_share_native_protection(tmp_path):
    from test_option_execution import ledger

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, buy, f, u, now = filled(e, v)
        at = now + timedelta(seconds=1)
        price = buy.target_exit_schedule.steps[0].underlying_price
        q = f.quote.model_copy(update={"source_at": at, "received_at": at})
        target = u.model_copy(
            update={"source_at": at, "received_at": at, "bid": price, "ask": price}
        )
        result = asyncio.run(e.protective_tick(q, target, now=at))
        assert result["status"] == "OPEN", result
        scale = intent_for(e, result["client_id"])
        assert scale.quantity == 1 and scale.closing_entry_client_id == buy.client_id
        v.fill(scale, 1, q, at, fill_id="target-sale", underlying=target)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        position = ledger(e).position
        assert position.quantity == 1
        assert position.tightened_underlying_invalidation == u.ask
        assert position.entry_time_protection == buy.entry_time_protection
        deadline = buy.exit_at
        q = q.model_copy(update={"source_at": deadline, "received_at": deadline})
        target = target.model_copy(update={"source_at": deadline, "received_at": deadline})
        result = asyncio.run(e.protective_tick(q, target, now=deadline))
        assert result["status"] == "OPEN", result
        runner = intent_for(e, result["client_id"])
        assert runner.quantity == 1
        v.fill(runner, 1, q, deadline, fill_id="deadline-sale", underlying=target)
        assert e.reconcile(v.snapshot(deadline), now=deadline)["reconciled"]
        assert book.snapshot()["watches"][0]["status"] == "CLOSED"
        assert e.refresh_loss_control(now=deadline)["families"][0]["consumed_entries"] == 1


@pytest.mark.parametrize(
    "field",
    [
        "target_exit_schedule",
        "entry_time_protection",
        "entry_lineage",
        "original_underlying_invalidation",
    ],
)
def test_native_receipt_catches_coordinated_intent_approval_tamper(tmp_path, field):
    import json

    from test_option_execution import ledger

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, buy, f, u, now = prepared(e, v)
        with e.journal.write() as db:
            row = db.execute("SELECT intent_json,approval_json FROM execution_orders").fetchone()
            intent, approval = (json.loads(x) for x in row)
            if field == "target_exit_schedule":
                intent[field]["steps"][0]["quantity"] = 0
            elif field == "entry_time_protection":
                intent[field]["exit_by"] = (
                    buy.entry_time_protection.exit_by + timedelta(minutes=1)
                ).isoformat()
            elif field == "entry_lineage":
                intent[field]["family"] = "SWING"
            else:
                intent[field] = "90"
            if field in approval:
                approval[field] = intent[field]
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=?",
                (json.dumps(intent), json.dumps(approval)),
            )
        assert asyncio.run(e.dispatch(buy.client_id, f.quote, u, now=now)) == "REJECTED"
        assert v.submit_count == 0 and ledger(e).position is None
        # Invalid native evidence cannot release the watch for another attempt.
        assert book.snapshot()["watches"][0]["status"] == "ORDER_WORKING"


def test_separate_scope_accounts_do_not_share_losses_or_native_receipts(tmp_path):
    from test_option_scope import AT

    from app.options.scope_watch import ScopeWatchBook

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    with (
        owned(
            a,
            enroll=False,
            execution_policy_changes=execution_policy(),
            population_id="scope-a",
            account_id="scope-a",
        ) as (e, v, _),
        owned(
            b,
            enroll=False,
            execution_policy_changes=execution_policy(),
            population_id="scope-b",
            account_id="scope-b",
        ) as (other, ov, _),
    ):
        _, buy, f, u, now = filled(e, v)
        sell(e, v, buy, f.quote, u, now)
        ob = ScopeWatchBook(other, policy(), now=AT, create=True)
        assert e.refresh_loss_control(now=now)["families"][0]["consecutive_losses"] == 1
        assert other.refresh_loss_control(now=now)["families"][0]["consecutive_losses"] == 0
        assert not ob.snapshot()["watches"] and ov.submit_count == 0


def test_native_enrollment_cannot_migrate_existing_research_watch(tmp_path):
    from test_option_scope import AT

    from app.execution.engine import ExecutionBlocked
    from app.options.scope_watch import ScopeWatchBook

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, _v, _):
        ScopeWatchBook(e, research_policy(), now=AT, create=True)
        with pytest.raises(ExecutionBlocked, match="FROZEN_SCOPE"):
            ScopeWatchBook(e, policy(), now=AT)


@pytest.mark.parametrize("unknown", [False, True])
def test_scope_retains_recorded_entry_charge_and_unresolved_management_cost(tmp_path, unknown):
    """Stored charge fixtures: Scope is deterministic, but existing charges cannot disappear."""
    from test_option_position_outcome import read_owned
    from test_option_scope_arming import refresh
    from test_option_scope_watch import ready

    from app.execution.economics import CostPolicy, UsageEvidence
    from app.options.engine import fingerprint
    from app.options.models import OptionProposal
    from app.options.scope_execution_export import export_scope_execution

    ep = execution_policy() | {"cost_policy": CostPolicy(total_budget="1", daily_budget=".1")}
    with owned(tmp_path, enroll=False, execution_policy_changes=ep) as (e, v, _):
        book, result, f, _, u, now = admitted(e, v, p=policy())
        proposal = OptionProposal.model_validate(result["record"]["admission_review"]["proposal"])
        from app.options.scope_execution import entry_source

        source = entry_source("first", "paid-review")
        # An already admitted entry advisory charge, retained as stored fixture evidence.
        with e.journal.write() as db:
            e._admit_model_attempt(db, source, fingerprint(proposal), now, None)
        e.record_model_usage(
            source,
            UsageEvidence(
                request_id="scope-advisory",
                model=e.policy.cost_policy.model,
                input_tokens=1000,
                output_tokens=100,
            ),
            proposal,
            now=now,
        )
        at = now + timedelta(seconds=1)
        ready(e, v, at)
        f, c = refresh(f, at)
        u = u.model_copy(update={"source_at": at, "received_at": at})
        result = book.review_admission(
            "paid-review",
            "first",
            frame=f,
            context=c,
            underlying=u,
            now=at,
            expected_revision=revision(e),
        )
        assert result["record"]["admission_review"]["eligible"]
        out = book.prepare_entry("first", expected_revision=revision(e), now=at)
        assert out["status"] == "PREPARED", out
        buy = intent_for(e, out["client_id"])
        assert asyncio.run(e.dispatch(buy.client_id, f.quote, u, now=at)) == "OPEN"
        v.fill(buy, buy.quantity, f.quote, at, fill_id="paid-entry", underlying=u)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        if unknown:
            # Unallocated interrupted advice is incomplete evidence, never a free call.
            with e.journal.write() as db:
                db.execute(
                    "INSERT INTO execution_model_calls VALUES(?,?,?,NULL,NULL,NULL,NULL)",
                    ("unresolved-management", "a" * 64, at.isoformat()),
                )
        sell(e, v, buy, f.quote, u, at)
        outcome = read_owned(e, buy)
        state = e.refresh_loss_control(now=at)
        assert Decimal(outcome["known_model_cost"]) == Decimal(".00015")
        export = export_scope_execution(e.journal, now=at, data_cost=".01", host_cost=".02")
        if unknown:
            assert outcome["status"] == "INCOMPLETE"
            assert "ACCOUNT_MODEL_COST_LINK_UNPROVEN" in outcome["reasons"]
            assert state["consumed_entries"] == 0
            assert export["report"]["net_after_all_costs"] is None
            assert export["report"]["model_costs"]["unknown_calls"] == 1
        else:
            assert state["families"][0]["consumed_entries"] == 1
            assert Decimal(outcome["net_after_known_execution_and_model_costs"]) == Decimal(
                export["report"]["ledger"]["cash"]
            ) - e.policy.capital - Decimal(".00015")


def test_rejected_stale_preparation_allows_fresh_admission_but_only_one_consumption(
    tmp_path, monkeypatch
):
    from test_option_scope_arming import refresh
    from test_option_scope_watch import ready

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, _, f, _, u, now = admitted(e, v, p=policy())
        select = book.entry_selection
        cached = select("first", expected_revision=revision(e), now=now)
        old_revision = revision(e)
        ready(e, v, now)
        monkeypatch.setattr(book, "entry_selection", lambda *a, **k: cached)
        out = book.prepare_entry("first", expected_revision=old_revision, now=now)
        assert out["status"] == "REJECTED" and out["reason"] == "SCOPE_ENTRY_REVISION_CHANGED"
        assert book.prepare_entry("first", expected_revision=old_revision, now=now) == out
        monkeypatch.setattr(book, "entry_selection", select)
        at = now + timedelta(seconds=1)
        ready(e, v, at)
        f, c = refresh(f, at)
        u = u.model_copy(update={"source_at": at, "received_at": at})
        book.review_admission(
            "fresh-after-race",
            "first",
            frame=f,
            context=c,
            underlying=u,
            now=at,
            expected_revision=revision(e),
        )
        cached = select("first", expected_revision=revision(e), now=at)
        rev = revision(e)
        monkeypatch.setattr(book, "entry_selection", lambda *a, **k: cached)
        out = book.prepare_entry("first", expected_revision=rev, now=at)
        assert out["status"] == "PREPARED", out
        assert book.prepare_entry("first", expected_revision=rev, now=at) == out
        with e.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 1
            assert (
                db.execute("SELECT COUNT(*) FROM execution_option_scope_entries").fetchone()[0] == 1
            )
            assert db.execute("SELECT COUNT(*) FROM execution_option_decisions").fetchone()[0] == 2


def test_native_scope_observer_labels_filled_play_and_remains_read_only(tmp_path):
    from fastapi.testclient import TestClient

    from app.web.options import create_options_app

    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        book, buy, _, _, now = filled(e, v)
        before = book.snapshot()
        secret = tmp_path / "observer-password"
        secret.write_text("fixture-observer-password-only")
        secret.chmod(0o600)
        client = TestClient(
            create_options_app(e.journal.path, e.limits.population_id, secret, clock=lambda: now)
        )
        assert client.get("/?family=SCOPE").status_code == 401
        client.auth = ("trader", secret.read_text())
        html = client.get("/?family=SCOPE")
        assert html.status_code == 200
        assert "Scope PAPER plays" in html.text and "POSITION_OPEN" in html.text
        assert buy.client_id in html.text
        assert "Scope is not enrolled for this population" not in html.text
        assert client.post("/api/options").status_code == 405
        assert book.snapshot() == before


def test_native_observer_rejects_orphaned_consumption_receipt(tmp_path):
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        _, buy, _, _, now = prepared(e, v)
        with e.journal.write() as db:
            db.execute("DELETE FROM execution_orders WHERE client_id=?", (buy.client_id,))
        assert observer(e, now).report()["status"] == "UNAVAILABLE"
