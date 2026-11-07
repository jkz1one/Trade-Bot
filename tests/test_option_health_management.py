"""Frozen observed health actions, durable protection and native economic attribution."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_admission import NOW
from test_option_execution import enter, intent_for, ledger, owned, quote_at, underlying_at
from test_option_greek_health import observed
from test_option_partial_close import fill, prepare

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.health_management import VERSION, stored
from app.options.observer import OptionObserver

D = Decimal
POLICY = {"health_management": VERSION}


def start(e, v, d, quantity=None):
    d["quote"] = observed(d["quote"], theta="-.01")
    return enter(e, v, d, quantity=quantity)


def sample(
    e,
    v,
    d,
    seconds=0,
    *,
    distance="0",
    bid=".98",
    iv=".4",
    delta=None,
    theta="-.01",
    ask=None,
    greek=True,
):
    at = NOW + timedelta(seconds=seconds)
    sign = 1 if d["quote"].instrument.contract.right == "CALL" else -1
    reference = d["underlying"].ask if sign == 1 else d["underlying"].bid
    price = reference + sign * D(distance)
    q = quote_at(d, at, bid=D(bid), ask=D(ask) if ask else D(bid) + D(".01"), greeks=None)
    if greek:
        q = observed(
            q,
            theta=theta,
            implied_volatility=iv,
            delta=delta if delta is not None else D(".5") * sign,
        )
    u = underlying_at(d, at, bid=price, ask=price)
    assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
    return q, u, at


def assess(e, v, d, seconds=0, **kw):
    q, u, at = sample(e, v, d, seconds, **kw)
    return e.assess(q, u, now=at)


def read(e, buy):
    with e.journal.read() as db:
        return stored(db, buy.client_id)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("severe", [False, True])
def test_observed_warnings_tighten_exact_original_risk_and_never_widen(tmp_path, right, severe):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = start(e, v, d)
        sign = 1 if right == "CALL" else -1
        kwargs = {"iv": ".3", "delta": D(".325") * sign} if severe else {"iv": ".34"}
        out = assess(e, v, d, 1, **kwargs)
        r = out["health_management"]
        p = ledger(e).position
        reference = d["underlying"].ask if sign == 1 else d["underlying"].bid
        risk = abs(reference - buy.original_underlying_invalidation)
        expected = reference - sign * risk * D(".25" if severe else ".5")
        assert p.tightened_underlying_invalidation == expected
        assert r["condition"] == ("DEFENSIVE" if severe else "CAUTION")
        assert r["action"] == "TIGHTEN" and r["status"] == "READY"
        assert not r["execution_authority"] and not r["live_enabled"]
        assess(e, v, d, 2, **kwargs)
        assert read(e, buy)["last_decision_at"] == r["last_decision_at"]
        assess(e, v, d, 3)
        assert ledger(e).position.tightened_underlying_invalidation == expected
        assert ledger(e).cash == D("592.40") and v.submit_count == 1


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_crossed_health_cap_latches_then_restart_dispatches_exact_owned_close(tmp_path, right):
    with owned(tmp_path, right, **POLICY) as (e, v, d):
        buy = start(e, v, d)
        risk = D("1.01") if right == "CALL" else D(1)
        q, u, at = sample(e, v, d, 1, distance=-risk * D(".5"), iv=".34")
        out = e.assess(q, u, now=at)
        assert out["exit_reason"] == "HEALTH_MANAGEMENT"
        assert read(e, buy)["action_reason"] == "PRETARGET_RISK_CAP"
        first = ledger(e).position.exit_required_at
        assess(e, v, d, 2, bid="1.1")
        assert ledger(e).position.exit_required_at == first
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=at + timedelta(seconds=1)) as e:
        q, u, at = sample(e, v, d, 3, bid="1.1")
        out = asyncio.run(e.protective_tick(q, u, now=at))
        assert out["status"] == "OPEN" and out["exit_reason"] == "HEALTH_MANAGEMENT"
        sell = intent_for(e, out["client_id"])
        assert sell.quantity == buy.quantity and sell.health_management is None
        fill(e, v, sell, q, at)
        assert ledger(e).position is None
        with e.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (sell.client_id,)
            ).fetchone()
            assert order_attribution(db, row)["health_management"] == VERSION


@pytest.mark.parametrize("reason", ["theta", "iv", "delta"])
def test_covered_stall_plus_decay_requires_exit_and_gap_does_not(tmp_path, reason):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = start(e, v, d)
        for seconds in range(0, 1200, 8):
            assess(e, v, d, seconds)
        kwargs = (
            {"theta": "-.4"}
            if reason == "theta"
            else {"iv": ".3"}
            if reason == "iv"
            else {"delta": ".325"}
        )
        out = assess(e, v, d, 1200, **kwargs)
        assert out["exit_reason"] == "HEALTH_MANAGEMENT"
        assert read(e, buy)["action_reason"] == "STALLED_DECAY"
    with owned(tmp_path / "gap", **POLICY) as (e, v, d):
        buy = start(e, v, d)
        assess(e, v, d)
        out = assess(e, v, d, 1200, **kwargs)
        assert out["exit_reason"] is None
        assert read(e, buy)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("fault", ["greek", "partial", "spread", "stale"])
def test_incomplete_inputs_withhold_new_actions_but_native_exit_remains(tmp_path, fault):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = start(e, v, d, quantity=1 if fault == "partial" else None)
        q, u, at = sample(e, v, d, 1, iv=".3", greek=fault != "greek")
        if fault == "spread":
            q = q.model_copy(update={"ask": None})
        if fault == "stale":
            q = q.model_copy(update={"source_at": NOW - timedelta(seconds=20)})
        e.assess(q, u, now=at)
        assert read(e, buy)["status"] == "INCOMPLETE"
        assert (
            ledger(e).position.tightened_underlying_invalidation
            == buy.original_underlying_invalidation
        )
        u = u.model_copy(update={"bid": D("598"), "ask": D("598")})
        out = e.assess(q, u, now=at)
        assert out["exit_reason"] == "UNDERLYING_INVALIDATION"


def test_spread_and_native_late_session_rules(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = start(e, v, d)
        out = assess(e, v, d, 1, ask="1.2")
        assert out["health_management"]["signals"]["spread_degraded"]
        assert out["health_management"]["condition"] == "DEFENSIVE"
        assert ledger(e).position.tightened_underlying_invalidation == D("599.7575")
        out = assess(e, v, d, 12600, bid="1.02")
        r = read(e, buy)
        assert r["minutes_to_close"] == 90
        assert r["signals"]["late_session"] and r["condition"] == "CAUTION"
        assert r["session_closes_at"] == NOW.replace(hour=20).isoformat()


def test_longer_dated_contract_is_explicitly_outside_daytrade_policy(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        contract = d["quote"].instrument.contract
        contract = contract.model_copy(
            update={
                "expiration": contract.expiration + timedelta(days=3),
                **{
                    key: getattr(contract, key) + timedelta(days=3)
                    for key in ("last_trading_at", "expires_at", "settles_at")
                },
            }
        )
        d["quote"] = d["quote"].model_copy(
            update={"instrument": d["quote"].instrument.model_copy(update={"contract": contract})}
        )
        d["proposal"] = d["proposal"].model_copy(update={"contract": contract})
        buy = start(e, v, d)
        out = assess(e, v, d, 1, iv=".3", delta=".325")
        assert out["health_management"]["status"] == "NOT_APPLICABLE"
        assert (
            ledger(e).position.tightened_underlying_invalidation
            == buy.original_underlying_invalidation
        )


@pytest.mark.parametrize("attempted", [False, True])
def test_health_exit_respects_scale_reservations(tmp_path, attempted):
    with owned(tmp_path, partial_closes="whole-contract-v1", **POLICY) as (e, v, d):
        buy = start(e, v, d)
        q, u, at = sample(e, v, d, 1)
        e.assess(q, u, now=at)
        out = prepare(e, buy, d, 2, at=at, quote=q, underlying=u)
        sell = intent_for(e, out["client_id"])
        if attempted:
            assert asyncio.run(e.dispatch(sell.client_id, q, u, now=at)) == "OPEN"
        low, under, later = sample(e, v, d, 2, distance="-.6", iv=".34")
        out = asyncio.run(e.protective_tick(low, under, now=later))
        if attempted:
            assert out["status"] == "EXIT_BLOCKED" and v.submit_count == 2
            fill(e, v, sell, q, later)
            out = asyncio.run(e.protective_tick(low, under, now=later))
        assert out["status"] == "OPEN" and out["exit_reason"] == "HEALTH_MANAGEMENT"
        assert intent_for(e, out["client_id"]).quantity == (2 if attempted else 4)


def test_target_scale_waits_for_health_evidence_and_posttarget_has_no_new_health_cap(tmp_path):
    from test_option_target_exits import POLICY as TARGET
    from test_option_target_exits import at_target, enter_targets

    with owned(tmp_path, **TARGET, **POLICY) as (e, v, d):
        d["quote"] = observed(d["quote"], theta="-.01")
        buy = enter_targets(e, v, d)
        q, _, at = sample(e, v, d, 1, greek=False)
        out = asyncio.run(e.protective_tick(q, at_target(d, 1, at), now=at))
        assert out["status"] == "HEALTH_MANAGEMENT_BLOCKED"
        assert v.submit_count == 1
        q, _, at = sample(e, v, d, 2, iv=".3", delta=".325")
        out = e.assess(q, at_target(d, 1, at), now=at)
        assert out["health_management"]["condition"] == "DEFENSIVE"
        assert (
            ledger(e).position.tightened_underlying_invalidation
            == buy.original_underlying_invalidation
        )


def test_legacy_owner_cannot_adopt_policy_and_entry_dispatch_rechecks_binding(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = start(e, v, d)
        assert buy.health_management is None and read(e, buy) is None
        path, limits, policy = e.journal.path, e.limits, e.policy
    with (
        pytest.raises(ValueError, match="immutable"),
        OptionExecution.open(path, limits, policy.model_copy(update=POLICY), v, now=NOW),
    ):
        pass
    with owned(tmp_path / "enrolled", **POLICY) as (e, v, d):
        out = e.prepare("entry", d["proposal"], d["quote"], d["underlying"], now=NOW)
        with e.journal.write() as db:
            row = db.execute(
                "SELECT intent_json FROM execution_orders WHERE client_id=?", (out["client_id"],)
            ).fetchone()
            intent = json.loads(row[0])
            intent.pop("health_management")
            db.execute(
                "UPDATE execution_orders SET intent_json=? WHERE client_id=?",
                (json.dumps(intent), out["client_id"]),
            )
        assert (
            asyncio.run(e.dispatch(out["client_id"], d["quote"], d["underlying"], now=NOW))
            == "REJECTED"
        )
        assert v.submit_count == 0


def test_health_audit_failure_rolls_back_stop_and_progress(tmp_path, monkeypatch):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = start(e, v, d)
        assess(e, v, d)
        before, old = ledger(e), read(e, buy)
        event = e.journal.event

        def fail(db, at, kind, payload, client_id=None):
            if kind == "OPTION_HEALTH_ASSESSED":
                raise RuntimeError("health audit unavailable")
            return event(db, at, kind, payload, client_id)

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="health audit"):
            assess(e, v, d, 1, iv=".34")
        assert ledger(e) == before and read(e, buy) == old


def test_observer_health_is_stored_and_stale_not_reassessed(tmp_path):
    with owned(tmp_path, **POLICY) as (e, v, d):
        buy = start(e, v, d)
        assess(e, v, d, 1, iv=".34")
        old = read(e, buy)
        r = OptionObserver(
            e.journal.path, e.limits.population_id, clock=lambda: NOW + timedelta(minutes=30)
        ).report()
        h = r["position"]["health_management"]
        assert h["stored_only"] and not h["observations_fresh"]
        assert h["last_decision_at"] == old["last_decision_at"] and read(e, buy) == old


def test_enrolled_abcd_replay_preserves_all_entry_management_costs(tmp_path, monkeypatch):
    import test_option_managed_replay as fixture
    from test_option_greek_health import (
        test_abcd_native_replay_exports_observed_greeks_and_every_model_charge,
    )

    original = fixture.managed_settings

    def settings(*a, **kw):
        s = original(*a, **kw)
        return s.model_copy(
            update={
                "manifest": s.manifest.model_copy(
                    update={
                        "arms": tuple(
                            arm.model_copy(update={"policy": arm.policy.model_copy(update=POLICY)})
                            for arm in s.manifest.arms
                        )
                    }
                )
            }
        )

    monkeypatch.setattr(fixture, "managed_settings", settings)
    test_abcd_native_replay_exports_observed_greeks_and_every_model_charge(tmp_path, monkeypatch)
    import sqlite3

    for arm in "ABCD":
        with sqlite3.connect(tmp_path / "run" / arm / "journal.db") as db:
            row = db.execute(
                "SELECT intent_json FROM execution_orders WHERE json_extract(intent_json,'$.side')='BUY'"
            ).fetchone()
            buy = json.loads(row[0])
            assert buy["health_management"] == VERSION
            assert stored(db, buy["client_id"])["version"] == VERSION


def test_paid_model_maintain_cannot_undo_health_tightening(tmp_path, monkeypatch):
    import test_option_position_coordination as fixture

    config, frame = fixture.configuration, fixture.frame

    def configuration(*a, **kw):
        return config(*a, **kw, **POLICY)

    def quoted_frame(*a, **kw):
        f = frame(*a, **kw)
        return f.model_copy(update={"quotes": tuple(observed(q, theta="-.01") for q in f.quotes)})

    monkeypatch.setattr(fixture, "configuration", configuration)
    monkeypatch.setattr(fixture, "frame", quoted_frame)
    with fixture.owned_manager(tmp_path) as (c, v, times):
        buy = fixture.enter_position(c, v, times, monkeypatch)
        before = ledger(c.engine).position.tightened_underlying_invalidation

        async def after(request, result):
            times[0] += timedelta(seconds=1)
            f = fixture.management_frame(at=times[0])
            q = observed(f.quotes[0], theta="-.01", implied_volatility=".34")
            assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
            c.engine.assess(q, f.underlyings[0], now=times[0])
            assert ledger(c.engine).position.tightened_underlying_invalidation > before

        fixture.model(monkeypatch, c, action="MAINTAIN", after=after)
        result = asyncio.run(c.cycle(fixture.management_frame()))
        assert result["status"] == "REJECTED", result
        assert ledger(c.engine).position.tightened_underlying_invalidation > before
        with c.engine.journal.read() as db:
            costs = [r[0] for r in db.execute("SELECT cost FROM execution_model_calls")]
            assert len(costs) == 2 and all(D(value) > 0 for value in costs)
        assert read(c.engine, buy)["effective_underlying_stop"] != str(before)


def test_open_native_export_binds_health_enrollment_without_inventing_profit(tmp_path, monkeypatch):
    import test_option_target_export as fixture

    from app.options.evaluation import evaluate

    monkeypatch.setattr(fixture, "POLICY", {**fixture.POLICY, **POLICY})
    boundary = fixture.native_boundary(tmp_path, sold=0)
    row, bundle = fixture.exported(boundary)
    assert row.orders[0].intent.health_management == VERSION
    assert evaluate(bundle)["status"] == "INCONCLUSIVE"
    changed = bundle.model_copy(
        update={
            "manifest": bundle.manifest.model_copy(
                update={
                    "arms": tuple(
                        arm.model_copy(
                            update={
                                "policy": arm.policy.model_copy(update={"health_management": None})
                            }
                        )
                        for arm in bundle.manifest.arms
                    )
                }
            )
        }
    )
    report = evaluate(changed)
    arm = report["sessions"][0]["arms"]["A"]
    assert not arm["accounting_verified"] and arm["net_change"] is None
    from app.options.engine import fingerprint

    changed = changed.model_copy(
        update={
            "evidence": (
                row.model_copy(update={"definition_hash": fingerprint(changed.manifest.arms[0])}),
            )
        }
    )
    report = evaluate(changed)
    assert "HEALTH_MANAGEMENT_POLICY_MISMATCH" in json.dumps(report)
