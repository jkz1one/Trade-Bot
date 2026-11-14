"""Explicit whole-contract closes retain runners, exact entry identity and every cost."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import enter, intent_for, ledger, owned, quote_at, underlying_at
from test_option_loss_control import POLICY
from test_option_position_outcome import read_owned

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.models import OptionProposal

D = Decimal
ENROLLMENT = "whole-contract-v1"


def close(entry, quantity=None):
    return OptionProposal(
        action="CLOSE",
        contract=entry.instrument.contract,
        close_quantity=quantity,
        thesis="Deterministic whole-contract exit",
    )


def prepare(engine, entry, data, quantity=2, *, key="scale", at=NOW, quote=None, underlying=None):
    return engine.prepare(
        key,
        close(entry, quantity),
        quote or quote_at(data, at),
        underlying or underlying_at(data, at),
        now=at,
    )


def fill(engine, venue, intent, quote, at=NOW):
    venue.fill(intent, intent.quantity, quote, at, fill_id=intent.source_key + "-fill")
    assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("quantity", [1, 2, 3])
def test_scale_then_runner_conserves_cash_fees_and_exact_entry(tmp_path, right, quantity):
    with owned(tmp_path, right, partial_closes=ENROLLMENT, loss_control=POLICY) as (e, v, d):
        buy = enter(e, v, d)
        original = ledger(e).position
        out = prepare(e, buy, d, quantity)
        assert out["status"] == "PREPARED", out
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == sell.requested_close_quantity == quantity
        assert sell.closing_entry_client_id == buy.client_id
        assert prepare(e, buy, d, quantity) == out
        assert (
            asyncio.run(e.dispatch(sell.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
        )
        fill(e, v, sell, d["quote"])
        position = ledger(e).position
        assert position.quantity == 4 - quantity and position.basis == D(101) * (4 - quantity)
        for field in (
            "entry_client_id",
            "original_underlying_invalidation",
            "tightened_underlying_invalidation",
            "exit_at",
            "entry_protection",
        ):
            assert getattr(position, field) == getattr(original, field)
        assert position.exit_reason is None
        assert read_owned(e, buy)["status"] == "INCOMPLETE"
        assert e.refresh_loss_control(now=NOW)["consumed_entries"] == 0
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (sell.client_id,)
            ).fetchone()
            attr = order_attribution(db, row)
            assert attr["requested_close_quantity"] == attr["filled_quantity"] == quantity
            assert attr["entry_client_id"] == buy.client_id
            account = e._account(db, NOW)
            assert account.reserved_cash == D("1.65") * (4 - quantity)
        runner = prepare(e, buy, d, None, key="runner")
        rest = intent_for(e, runner["client_id"])
        assert rest.quantity == 4 - quantity and rest.requested_close_quantity is None
        assert asyncio.run(e.dispatch(rest.client_id, d["quote"], now=NOW)) == "OPEN"
        fill(e, v, rest, d["quote"])
        result = read_owned(e, buy)
        assert (
            result["status"] == "COMPLETE"
            and result["entry_quantity"] == result["exit_quantity"] == 4
        )
        assert D(result["execution_fees"]) == D("8.20")
        assert D(result["net_after_known_execution_and_model_costs"]) == D("-24.20")
        assert ledger(e).cash == D("975.80") and ledger(e).settled_cash == D("592.40")
        assert e.refresh_loss_control(now=NOW)["consumed_entries"] == 1
        assert v.submit_count == 3
        assert asyncio.run(e.dispatch(sell.client_id, d["quote"], now=NOW)) == "FILLED"
        assert v.submit_count == 3


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, D(1), "1"])
def test_requested_quantity_is_strict_positive_whole_contracts(value):
    with pytest.raises(ValidationError):
        OptionProposal(action="CLOSE", close_quantity=value, thesis="Invalid")


@pytest.mark.parametrize("action", ["HOLD", "OPEN_LONG"])
def test_quantity_cannot_be_used_as_entry_sizing(action):
    from test_option_admission import inputs

    d = inputs()
    with pytest.raises(ValidationError, match="only to CLOSE"):
        OptionProposal(
            action=action,
            contract=d["proposal"].contract,
            underlying_invalidation=d["proposal"].underlying_invalidation,
            close_quantity=1,
            thesis="Invalid",
        )


def test_absent_enrollment_rejects_only_explicit_requests_and_cannot_migrate(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = enter(e, v, d)
        assert "partial_closes" not in e.policy.model_dump()
        assert "close_quantity" not in close(buy).model_dump()
        assert "requested_close_quantity" not in buy.model_dump()
        result = prepare(e, buy, d)
        assert (
            result["status"] == "REJECTED"
            and result["reason"] == "OPTION_PARTIAL_CLOSE_NOT_ENROLLED"
        )
        assert prepare(e, buy, d, None, key="full")["status"] == "PREPARED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(
            path, limits, policy.model_copy(update={"partial_closes": ENROLLMENT}), v, now=NOW
        ),
    ):
        pass


@pytest.mark.parametrize("quantity", [4, 5])
def test_exact_owned_ceiling_and_no_overselling(tmp_path, quantity):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        out = prepare(e, buy, d, quantity)
        assert out["status"] == ("PREPARED" if quantity == 4 else "REJECTED")
        if quantity == 5:
            assert "CLOSE_QUANTITY_EXCEEDS_OWNERSHIP" in out["admission"]["reasons"]
        else:
            assert out["admission"]["quantity"] == 4


def test_liquidity_caps_fixed_order_even_when_bid_size_later_increases(tmp_path):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        small = quote_at(d, bid_size=1)
        out = prepare(e, buy, d, 3, quote=small)
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == 1 and sell.requested_close_quantity == 3
        assert (
            asyncio.run(e.dispatch(sell.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
        )
        fill(e, v, sell, d["quote"])
        assert ledger(e).position.quantity == 3
        before = ledger(e)
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        assert ledger(e) == before
        assert prepare(e, buy, d, 3, quote=small) == out
        assert asyncio.run(e.dispatch(sell.client_id, d["quote"], now=NOW)) == "FILLED"
        assert v.submit_count == 2


@pytest.mark.parametrize("stage", ["prepare", "dispatch"])
@pytest.mark.parametrize("cause", ["stop", "premium", "time"])
def test_mandatory_exit_preempts_scale_and_latches_across_rebound(tmp_path, stage, cause):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        at = ledger(e).position.exit_at - timedelta(seconds=1) if cause == "time" else NOW
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        if stage == "dispatch":
            out = prepare(e, buy, d, at=at)
            assert out["status"] == "PREPARED"
        if cause == "time":
            at += timedelta(seconds=1)
        q = quote_at(d, at, bid=".2", ask=".21") if cause == "premium" else quote_at(d, at)
        u = (
            underlying_at(d, at, bid="598", ask="598.01")
            if cause == "stop"
            else underlying_at(d, at)
        )
        if stage == "prepare":
            out = prepare(e, buy, d, at=at, quote=q, underlying=u)
            assert out["status"] == "REJECTED"
            assert out["reason"] == "OPTION_PARTIAL_CLOSE_FULL_EXIT_REQUIRED"
        else:
            assert asyncio.run(e.dispatch(out["client_id"], q, u, now=at)) == "REJECTED"
        assert v.submit_count == 1
        assert (
            ledger(e).position.exit_reason
            == {
                "stop": "UNDERLYING_INVALIDATION",
                "premium": "PREMIUM_CATASTROPHE",
                "time": "TIME_EXIT",
            }[cause]
        )
        reason = ledger(e).position.exit_reason
        e.assess(quote_at(d, at), underlying_at(d, at), now=at)
        assert ledger(e).position.exit_reason == reason
        # Ordinary owned full closes stay available, including after a rejected scale.
        full = e.prepare("full-after-stop", close(buy), q, now=at)
        assert full["status"] == "PREPARED" and full["admission"]["quantity"] == 4


def test_missing_underlying_blocks_planned_scale_but_not_full_close(tmp_path):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        result = e.prepare("missing", close(buy, 2), d["quote"], now=NOW)
        assert result["reason"] == "OPTION_PARTIAL_CLOSE_FRESH_PROTECTION_REQUIRED"
        assert e.prepare("full", close(buy), d["quote"], now=NOW)["status"] == "PREPARED"


@pytest.mark.parametrize("origin", ["MODEL", "PROTECTIVE"])
def test_scale_quantity_is_deterministic_software_authority(tmp_path, origin):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        out = e.prepare(
            "foreign-origin", close(buy, 2), d["quote"], d["underlying"], now=NOW, origin=origin
        )
        assert (
            out["status"] == "REJECTED"
            and out["reason"] == "OPTION_PARTIAL_CLOSE_DETERMINISTIC_ONLY"
        )


@pytest.mark.parametrize(
    "damage", ["proposal", "missing_proposal", "missing_intent", "approved_quantity"]
)
def test_dispatch_rechecks_requested_and_approved_quantity_before_attempt(tmp_path, damage):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        result = prepare(e, buy, d, 3, quote=quote_at(d, bid_size=1))
        with e.journal.write() as db:
            row = db.execute(
                "SELECT intent_json,approval_json FROM execution_orders WHERE client_id=?",
                (result["client_id"],),
            ).fetchone()
            intent, approval = map(json.loads, row)
            if damage == "proposal":
                approval["proposal"]["close_quantity"] = 4
            elif damage == "missing_proposal":
                del approval["proposal"]["close_quantity"]
            elif damage == "missing_intent":
                del intent["requested_close_quantity"]
            else:
                intent["quantity"] = 2
            db.execute(
                "UPDATE execution_orders SET intent_json=?,approval_json=? WHERE client_id=?",
                (json.dumps(intent), json.dumps(approval), result["client_id"]),
            )
        assert (
            asyncio.run(e.dispatch(result["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 1
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (result["client_id"],)
            ).fetchone()
            assert row["attempted_at"] is None and row["active_lock"] is None
            with pytest.raises(ValueError, match="quantity"):
                order_attribution(db, row)


def test_partial_buy_keeps_single_order_lock(tmp_path):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d, quantity=2)
        out = prepare(e, buy, d, 1)
        assert out["status"] == "REJECTED" and "UNRESOLVED_ORDER" in out["admission"]["reasons"]
        assert v.submit_count == 1


@pytest.mark.parametrize("attempted", [False, True])
def test_independent_protection_supersedes_only_unattempted_scale(tmp_path, attempted):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        out = prepare(e, buy, d)
        if attempted:
            assert (
                asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
                == "OPEN"
            )
        stopped = underlying_at(d, bid="598", ask="598.01")
        result = asyncio.run(e.protective_tick(d["quote"], stopped, now=NOW))
        if attempted:
            assert result["status"] == "EXIT_BLOCKED"
            assert v.submit_count == 2
            # Once the attempted partial order finishes, protection closes the actual remainder.
            scale = intent_for(e, out["client_id"])
            fill(e, v, scale, d["quote"])
            result = asyncio.run(e.protective_tick(d["quote"], d["underlying"], now=NOW))
            assert result["status"] == "OPEN"
            assert intent_for(e, result["client_id"]).quantity == 2
        else:
            assert result["status"] == "OPEN" and v.submit_count == 2
            assert intent_for(e, result["client_id"]).quantity == 4
            with e.journal.read() as db:
                row = db.execute(
                    "SELECT status,attempted_at,active_lock FROM execution_orders WHERE client_id=?",
                    (out["client_id"],),
                ).fetchone()
                assert tuple(row) == ("REJECTED", None, None)
            assert (
                asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
                == "REJECTED"
            )
        assert ledger(e).position.exit_reason == "UNDERLYING_INVALIDATION"


def test_rejected_unattempted_scale_does_not_block_protective_full_exit(tmp_path):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        out = prepare(e, buy, d)
        stop = underlying_at(d, bid="598", ask="598.01")
        assert asyncio.run(e.dispatch(out["client_id"], d["quote"], stop, now=NOW)) == "REJECTED"
        result = asyncio.run(e.protective_tick(d["quote"], d["underlying"], now=NOW))
        assert result["status"] == "OPEN"
        assert intent_for(e, result["client_id"]).quantity == 4
        assert v.submit_count == 2


@pytest.mark.parametrize("unknown", [False, True])
def test_entry_and_management_costs_survive_scale_runner_and_loss_recognition(
    tmp_path, monkeypatch, unknown
):
    from test_option_family_loss import policy as family_policy
    from test_option_position_coordination import (
        enter_position,
        management_frame,
        model,
        owned_manager,
    )

    with owned_manager(tmp_path, loss_policy=family_policy(), partial_closes=ENROLLMENT) as (
        c,
        v,
        times,
    ):
        buy = enter_position(c, v, times, monkeypatch)
        assert buy.quantity > 1
        model(
            monkeypatch,
            c,
            "MAINTAIN",
            changes=(lambda request, result: result.model_copy(update={"usage": None}))
            if unknown
            else None,
        )
        f = management_frame()
        managed = asyncio.run(c.cycle(f))
        assert managed["status"] == ("HELD" if unknown else "MAINTAIN"), managed
        e, at, q, u = c.engine, times[0], f.quotes[0], f.underlyings[0]
        out = e.prepare("scale-with-costs", close(buy, 1), q, u, now=at)
        assert out["status"] == "PREPARED", out
        scale = intent_for(e, out["client_id"])
        assert asyncio.run(e.dispatch(scale.client_id, q, u, now=at)) == "OPEN"
        fill(e, v, scale, q, at)
        partial = read_owned(e, buy)
        assert partial["status"] == "INCOMPLETE" and partial["exit_quantity"] == 1
        assert {row["role"] for row in partial["model_calls"]} == {"ENTRY", "MANAGEMENT"}
        assert D(partial["known_model_cost"]) == D(".00015" if unknown else ".00030")
        assert e.refresh_loss_control(now=at)["consumed_entries"] == 0
        runner = e.prepare("runner-with-costs", close(buy), q, now=at)
        rest = intent_for(e, runner["client_id"])
        assert rest.quantity == buy.quantity - 1
        assert asyncio.run(e.dispatch(rest.client_id, q, now=at)) == "OPEN"
        fill(e, v, rest, q, at)
        result = read_owned(e, buy)
        state = e.refresh_loss_control(now=at)
        if unknown:
            assert result["status"] == "INCOMPLETE"
            assert result["net_after_known_execution_and_model_costs"] is None
            assert "POSITION_MODEL_COST_UNKNOWN" in result["reasons"]
            assert state["consumed_entries"] == 0
        else:
            assert result["status"] == "COMPLETE"
            assert D(result["known_model_cost"]) == D(".00030")
            assert D(result["execution_fees"]) == ledger(e).fees_paid
            assert D(result["net_after_known_execution_and_model_costs"]) == ledger(
                e
            ).cash - e.policy.capital - D(".00030")
            assert state["consumed_entries"] == 1
            assert (
                next(x for x in state["families"] if x["family"] == "DEGEN")["consumed_entries"]
                == 1
            )
            assert (
                next(x for x in state["families"] if x["family"] == "SWING")["consumed_entries"]
                == 0
            )
        assert result["entry_lineage"]["family"] == "DEGEN"


def test_rejected_scale_protection_write_rolls_back_atomically(tmp_path, monkeypatch):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        original = ledger(e)
        event = e.journal.event

        def fail(*args, **kwargs):
            event(*args, **kwargs)
            raise RuntimeError("injected")

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="injected"):
            prepare(e, buy, d, underlying=underlying_at(d, bid="598", ask="598.01"))
        assert ledger(e) == original
        with e.journal.read() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM execution_option_decisions WHERE source_key='scale'"
                ).fetchone()[0]
                == 0
            )


def test_stored_proposal_cannot_report_a_different_scale_quantity(tmp_path):
    with owned(tmp_path, partial_closes=ENROLLMENT) as (e, v, d):
        buy = enter(e, v, d)
        prepare(e, buy, d, 2)
        with e.journal.write() as db:
            db.execute(
                "UPDATE execution_option_decisions SET inputs_json=json_set(inputs_json,'$.proposal.close_quantity',3) WHERE source_key='scale'"
            )
        with pytest.raises(ValueError, match="proposal quantity"):
            read_owned(e, buy)
