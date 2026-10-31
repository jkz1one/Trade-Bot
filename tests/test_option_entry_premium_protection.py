"""Entry-frozen premium protection can only tighten owner risk, across real native fills."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW
from test_option_execution import intent_for, ledger, owned, quote_at
from test_option_partial_close import fill
from test_option_position_outcome import read_owned
from test_option_target_exits import at_target, schedule

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.lifecycle import EntryPremiumProtection
from app.options.models import OptionProposal

D = Decimal
ENROLLED = {"entry_premium_protection": "tighten-only-v1"}


def protection(fraction=".35"):
    return EntryPremiumProtection(maximum_loss_fraction=fraction)


def prepare(e, d, *, risk=None, **kwargs):
    return e.prepare(
        "entry",
        d["proposal"],
        d["quote"],
        d["underlying"],
        now=NOW,
        entry_premium_protection=risk or protection(),
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
@pytest.mark.parametrize(
    "bid,expected",
    [(".656500000001", None), (".6565", "PREMIUM_CATASTROPHE"), (".60", "PREMIUM_CATASTROPHE")],
)
def test_exact_frozen_boundary_uses_actual_basis_and_executable_bid(tmp_path, right, bid, expected):
    with owned(tmp_path, right, **ENROLLED) as (e, v, d):
        buy = enter(e, v, d)
        assert ledger(e).position.basis == D(404)
        assert buy.approved_full_premium_loss == D("414.20")
        q = quote_at(d, bid=D(bid), ask=D(".70"))
        out = e.assess(q, d["underlying"], now=NOW)
        assert out["exit_reason"] == expected
        assert v.submit_count == 1
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (buy.client_id,)
            ).fetchone()
            assert order_attribution(db, row)[
                "entry_premium_protection"
            ] == protection().model_dump(mode="json")


def test_runner_keeps_entry_protection_and_all_fees_after_scale_and_restart(tmp_path):
    with owned(
        tmp_path, partial_closes="whole-contract-v1", target_exits="frozen-targets-v1", **ENROLLED
    ) as (e, v, d):
        buy = enter(e, v, d, target_exit_schedule=schedule())
        out = asyncio.run(e.protective_tick(d["quote"], at_target(d), now=NOW))
        scale = intent_for(e, out["client_id"])
        fill(e, v, scale, d["quote"])
        assert ledger(e).position.quantity == 2
        assert ledger(e).position.entry_premium_protection == protection()
        assert read_owned(e, buy)["status"] == "INCOMPLETE"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=NOW) as e:
        q = quote_at(d, bid=D(".60"), ask=D(".61"))
        out = asyncio.run(e.protective_tick(q, d["underlying"], now=NOW))
        assert out["status"] == "OPEN" and out["exit_reason"] == "PREMIUM_CATASTROPHE"
        runner = intent_for(e, out["client_id"])
        assert runner.quantity == 2 and runner.entry_premium_protection is None
        fill(e, v, runner, q)
        result = read_owned(e, buy)
        assert result["status"] == "COMPLETE" and D(result["execution_fees"]) == D("8.20")
        assert (
            D(result["net_after_known_execution_and_model_costs"])
            == ledger(e).cash - e.policy.capital
        )
        with e.journal.read() as db:
            for intent in (scale, runner):
                row = db.execute(
                    "SELECT * FROM execution_orders WHERE client_id=?", (intent.client_id,)
                ).fetchone()
                assert order_attribution(db, row)[
                    "entry_premium_protection"
                ] == protection().model_dump(mode="json")


def test_premium_latch_preempts_prepared_target_and_survives_rebound(tmp_path):
    with owned(
        tmp_path, partial_closes="whole-contract-v1", target_exits="frozen-targets-v1", **ENROLLED
    ) as (e, v, d):
        buy = enter(e, v, d, target_exit_schedule=schedule())
        e.assess(d["quote"], at_target(d), now=NOW)
        out = e.prepare(
            "scale",
            OptionProposal(
                action="CLOSE", contract=buy.instrument.contract, close_quantity=2, thesis="Scale"
            ),
            d["quote"],
            at_target(d),
            now=NOW,
            target_exit_stage=1,
        )
        assert out["status"] == "PREPARED"
        q = quote_at(d, bid=D(".60"), ask=D(".61"))
        out = asyncio.run(e.protective_tick(q, at_target(d), now=NOW))
        assert out["exit_reason"] == "PREMIUM_CATASTROPHE" and out["status"] == "OPEN"
        assert intent_for(e, out["client_id"]).quantity == 4
        assert (
            e.assess(d["quote"], d["underlying"], now=NOW)["exit_reason"] == "PREMIUM_CATASTROPHE"
        )
        assert v.submit_count == 2


@pytest.mark.parametrize("fault", ["stale", "size", "source", "missing", "crossed"])
def test_bad_option_evidence_cannot_manufacture_premium_trigger(tmp_path, fault):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        enter(e, v, d)
        q = quote_at(d, bid=D(".60"), ask=D(".61"))
        if fault == "stale":
            q = q.model_copy(update={"source_at": NOW - timedelta(minutes=1)})
        elif fault == "size":
            q = q.model_copy(update={"bid_size": 0})
        elif fault == "source":
            q = q.model_copy(update={"source": "foreign"})
        elif fault == "crossed":
            q = q.model_copy(update={"ask": D(".59")})
        else:
            q = None
        out = e.assess(q, d["underlying"], now=NOW)
        assert out["status"] == "BLOCKED" and out["exit_reason"] is None
        assert ledger(e).position.quantity == 4 and v.submit_count == 1


@pytest.mark.parametrize("fraction", [".500000000001", ".60"])
def test_cannot_widen_owner_limit(tmp_path, fraction):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d, risk=protection(fraction))
        assert out["status"] == "REJECTED" and out["reason"] == "OPTION_ENTRY_PREMIUM_CANNOT_WIDEN"
        assert v.submit_count == 0


@pytest.mark.parametrize("fraction", [True, 0, "-1", "1", 0.35, "NaN"])
def test_invalid_fraction_rejected(fraction):
    with pytest.raises(ValidationError):
        protection(fraction)


def test_opt_in_required_and_old_owner_cannot_migrate(tmp_path):
    with owned(tmp_path) as (e, v, d):
        assert "entry_premium_protection" not in e.policy.model_dump()
        assert prepare(e, d)["reason"] == "OPTION_ENTRY_PREMIUM_NOT_ENROLLED"
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(path, limits, policy.model_copy(update=ENROLLED), v, now=NOW),
    ):
        pass


@pytest.mark.parametrize("origin", ["MODEL", "PROTECTIVE"])
def test_model_or_protective_origin_cannot_attach_entry_terms(tmp_path, origin):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d, origin=origin)
        assert out["status"] == "REJECTED" and v.submit_count == 0


@pytest.mark.parametrize("side", ["intent", "approval", "both_wider"])
def test_dispatch_rechecks_frozen_premium_and_owner_cap(tmp_path, side):
    with owned(tmp_path, **ENROLLED) as (e, v, d):
        out = prepare(e, d)
        with e.journal.write() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            for field in ("intent_json", "approval_json"):
                if side != "both_wider" and not field.startswith(side):
                    continue
                value = json.loads(row[field])
                value["entry_premium_protection"] = protection(
                    ".6" if side == "both_wider" else ".4"
                ).model_dump(mode="json")
                db.execute(
                    f"UPDATE execution_orders SET {field}=? WHERE client_id=?",
                    (json.dumps(value), out["client_id"]),
                )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 0


def test_independent_entry_thresholds_do_not_leak(tmp_path):
    with (
        owned(tmp_path / "a", **ENROLLED) as (a, va, da),
        owned(tmp_path / "b", **ENROLLED) as (b, vb, db),
    ):
        enter(a, va, da)
        enter(b, vb, db, risk=protection(".45"))
        q = quote_at(da, bid=D(".60"), ask=D(".61"))
        assert a.assess(q, da["underlying"], now=NOW)["exit_reason"] == "PREMIUM_CATASTROPHE"
        assert (
            b.assess(quote_at(db, bid=D(".60"), ask=D(".61")), db["underlying"], now=NOW)[
                "exit_reason"
            ]
            is None
        )
