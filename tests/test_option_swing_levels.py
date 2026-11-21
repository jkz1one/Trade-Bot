"""Completed source periods feed higher-timeframe native Swing setups."""

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from test_option_entry_coordination import fake_model
from test_option_execution import intent_for, ledger
from test_option_shared_strategy import shared_frame, swing_input
from test_option_swing_base import base_request
from test_option_swing_target_derivation import owner
from test_option_swing_target_derivation import request as legacy_request
from test_option_swing_targets import touch

from app.options.engine import fingerprint
from app.options.shared_strategy import lock_seeds
from app.options.swing import SwingPolicy, SwingSeed
from app.options.swing_level_models import LEVEL_FAMILIES
from app.options.swing_levels import evaluate_level
from app.options.swing_lifecycle import load_terminal
from app.options.swing_targets import SwingSeedBuildRequest, build_swing_seed, target_issues
from app.robinhood.schedule import XNYSCalendar

D = Decimal
CASES = [
    ("previous_week_high", "CALL"),
    ("previous_week_low", "PUT"),
    ("previous_month_high", "CALL"),
    ("previous_month_low", "PUT"),
    ("weekly_open", "CALL"),
    ("weekly_open", "PUT"),
]


def level_request(key="previous_week_high", right="CALL", *, seed=None, policy=None):
    if policy is not None:
        policy = policy.model_copy(
            update={
                "higher_levels": None,
                "daily_base": None,
                "ma_pullback": None,
                "daily_lookback": 3,
            }
        )
    raw = base_request(right, seed=seed, policy=policy).model_dump()
    raw["policy"].update(
        daily_base=None,
        ma_pullback=None,
        daily_lookback=56,
        higher_levels={"keys": tuple(LEVEL_FAMILIES)},
    )
    raw.update(level_key=key, hourly_history=None)
    right = raw["instrument"]["contract"]["right"]
    bars = list(raw["history"]["bars"])
    cal = XNYSCalendar().calendar
    prior = cal.previous_session(bars[0]["begins_at"].date().isoformat())
    bars.insert(
        0,
        dict(
            bars[0],
            begins_at=cal.session_open(prior).to_pydatetime(),
            closes_at=cal.session_close(prior).to_pydatetime(),
        ),
    )
    bars[-1].update(
        open=D(598) if right == "CALL" else D(602),
        low=D("597.8") if right == "CALL" else D(600),
        high=D(600) if right == "CALL" else D("602.2"),
    )
    raw["history"].update(version="swing-level-daily-v1", bars=bars)
    return SwingSeedBuildRequest.model_validate(raw)


def level_frame(key="previous_week_high", right="CALL"):
    req = level_request(key, right)
    item = swing_input(right).model_copy(update={"seed": build_swing_seed(req)})
    return shared_frame(right, item), req.policy


@pytest.mark.parametrize("key,right", CASES)
@pytest.mark.parametrize("precision", [4, 28])
def test_original_levels_use_complete_period_prices_and_fixed_risk(key, right, precision):
    req = level_request(key, right)
    with localcontext() as context:
        context.prec = precision
        seed = build_swing_seed(req)
        evidence = evaluate_level(seed)
    price = (
        D(598 if right == "CALL" else 602)
        if key == "weekly_open"
        else D(599 if right == "CALL" else 601)
    )
    stop = price * (D(".9895") if right == "CALL" else D("1.0105"))
    assert evidence.level_price == price and evidence.invalidation == stop
    assert evidence.reasons == () and evidence.confirmations
    assert evidence.breakout_at == seed.history.bars[-1].closes_at
    assert evidence.source_end <= seed.history.source_at <= seed.created_at
    assert seed.target_geometry.reference == 600
    assert seed.target_geometry.invalidation == stop
    assert seed.target_geometry.targets == tuple(D(600) + (D(600) - stop) * n for n in (1, 2, 3))
    assert not target_issues(seed, req.policy)
    assert SwingSeed.model_validate_json(seed.model_dump_json()) == seed


@pytest.mark.parametrize(
    "damage",
    [
        "key",
        "enrollment",
        "history",
        "hourly",
        "source",
        "future",
        "gap",
        "interpolated",
        "volume",
        "partial-period",
        "foreign-period",
    ],
)
def test_level_inputs_never_substitute_unbound_or_partial_periods(damage):
    raw = level_request("previous_month_high").model_dump()
    if damage == "key":
        raw["level_key"] = None
    elif damage == "enrollment":
        raw["policy"]["higher_levels"]["keys"] = ("weekly_open",)
    elif damage == "history":
        raw["history"]["version"] = "swing-base-daily-v1"
    elif damage == "hourly":
        raw["hourly_history"] = base_request().hourly_history
    elif damage == "source":
        raw["history"]["source"] = "foreign"
    elif damage == "future":
        raw["history"]["received_at"] = raw["created_at"] + timedelta(seconds=1)
    else:
        bars = raw["history"]["bars"]
        b = bars[-15] if damage in ("partial-period", "foreign-period") else bars[0]
        b.update(
            {"begins_at": b["begins_at"] + timedelta(minutes=1)}
            if damage in ("gap", "foreign-period")
            else {"interpolated": True}
            if damage == "interpolated"
            else {"volume": 0}
            if damage == "volume"
            else {"begins_at": bars[-14]["begins_at"], "closes_at": bars[-14]["closes_at"]}
        )
    with pytest.raises(ValueError):
        build_swing_seed(SwingSeedBuildRequest.model_validate(raw))


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("break", "SWING_LEVEL_COMPLETED_BREAK_REQUIRED"),
        ("test", "SWING_LEVEL_RETEST_REQUIRED"),
        ("hold", "SWING_LEVEL_ACCEPTANCE_REQUIRED"),
        ("confirmation", "SWING_LEVEL_DIRECTIONAL_CONFIRMATION_REQUIRED"),
        ("direction", "SWING_LEVEL_DIRECTION_REQUIRED"),
    ],
)
def test_level_source_rules_block_native_candidate(tmp_path, damage, reason):
    raw = level_request().model_dump()
    b = raw["history"]["bars"][-1]
    if damage == "break":
        b.update(open=D(598), close=D(598))
    elif damage == "test":
        b.update(open=D(610), low=D(610), high=D(612), close=D(612))
    elif damage == "hold":
        b.update(open=D(598), low=D(590), close=D(590))
    elif damage == "confirmation":
        b.update(open=D("599.7"), low=D("599.6"), high=D("600.4"), close=D("599.8"))
    else:
        raw["level_key"] = "previous_week_low"
    req = SwingSeedBuildRequest.model_validate(raw)
    seed = build_swing_seed(req)
    assert reason in evaluate_level(seed).reasons
    f = shared_frame(item=swing_input().model_copy(update={"seed": seed}))
    with owner(tmp_path, swing=req.policy) as (c, v, _):
        result = c.quote_plan(f.histories, (), f.swing)
        scan = next(s for s in result["scans"] if s.version == "swing-next-session-v1")
        assert reason in scan.observations[0].reasons
        assert scan.observations[0].status != "CONFIRMED" and v.submit_count == 0


@pytest.mark.parametrize("target", [date(2026, 3, 9), date(2026, 11, 30), date(2026, 1, 5)])
@pytest.mark.parametrize("key", ["previous_week_high", "previous_month_high", "weekly_open"])
def test_level_periods_follow_actual_dst_holiday_and_year_boundaries(target, key):
    req = level_request(key, seed=swing_input(target=target).seed)
    seed = build_swing_seed(req)
    e = evaluate_level(seed)
    assert e.source_end <= seed.history.bars[-1].closes_at
    assert not target_issues(seed, req.policy)


def test_legacy_enrollment_never_accepts_level_inputs():
    old = legacy_request()
    assert "higher_levels" not in old.policy.model_dump()
    assert "level_key" not in build_swing_seed(old).model_dump()
    assert target_issues(build_swing_seed(level_request()), old.policy) == (
        "SWING_LEVEL_ENROLLMENT_REQUIRED",
    )
    with pytest.raises(ValueError):
        SwingPolicy.model_validate(
            level_request().policy.model_dump()
            | {"daily_base": {"hourly_source": "fixture-hourly", "hourly_lookback": 54}}
        )


@pytest.mark.parametrize("key,right", CASES)
@pytest.mark.parametrize("ai", [False, True])
def test_native_level_entry_actual_fill_and_original_stop(tmp_path, monkeypatch, key, right, ai):
    f, policy = level_frame(key, right)
    with owner(tmp_path, right, swing=policy, ai=ai) as (c, v, times):
        calls = fake_model(monkeypatch, c) if ai else []
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        selected = next(x for x in result["candidates"] if x["family"] == LEVEL_FAMILIES[key])
        assert selected["proposal"]["underlying_invalidation"] == str(
            f.swing[0].seed.target_geometry.invalidation
        )
        buy = intent_for(c.engine, result["client_id"])
        v.fill(buy, buy.quantity, f.quotes[1], times[0], fill_id="base-buy")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        held = ledger(c.engine).position
        assert held is not None and (len(calls) == 1 if ai else not calls)
        with c.engine.journal.read() as db:
            intent = json.loads(
                db.execute(
                    "SELECT intent_json FROM execution_orders WHERE client_id=?",
                    (held.entry_client_id,),
                ).fetchone()[0]
            )
        assert intent["entry_lineage"]["setup"] == LEVEL_FAMILIES[key]
        assert intent["entry_lineage"]["family"] == "SWING"
        times[0] += timedelta(seconds=1)
        stop = held.original_underlying_invalidation
        u = f.underlyings[0].model_copy(
            update={
                "bid": stop - D(".01"),
                "ask": stop + D(".01"),
                "source_at": times[0],
                "received_at": times[0],
            }
        )
        q = tuple(
            q.model_copy(update={"source_at": times[0], "received_at": times[0]}) for q in f.quotes
        )
        close = asyncio.run(c.supervise((q[1],), (u,)))
        assert close["status"] == "OPEN", close
        sell = intent_for(c.engine, close["client_id"])
        assert sell.closing_entry_client_id == buy.client_id and sell.exit_at == buy.exit_at
        v.fill(sell, sell.quantity, q[1], times[0], fill_id="base-sell")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        assert ledger(c.engine).position is None


@pytest.mark.parametrize("key,right", CASES)
@pytest.mark.parametrize("reason", ["TARGET_CONSUMED", "INVALIDATED"])
def test_original_level_stop_and_target_retire_across_restart(tmp_path, key, right, reason):
    f, policy = level_frame(key, right)
    with owner(tmp_path, right, swing=policy) as (c, v, _):
        lock_seeds(c, f.swing)
        quote = touch(f)
        if reason == "INVALIDATED":
            stop = f.swing[0].seed.target_geometry.invalidation
            quote = f.underlyings[0].model_copy(
                update={"bid": stop - D(".01"), "ask": stop + D(".01")}
            )
        asyncio.run(c.supervise((), (quote,)))
        with c.engine.journal.read() as db:
            terminal = load_terminal(db, f.swing[0].seed)
        assert terminal.status == reason and v.submit_count == 0
    with (
        owner(tmp_path, right, swing=policy, create=False) as (c, _, _),
        c.engine.journal.read() as db,
    ):
        assert load_terminal(db, f.swing[0].seed) == terminal
        raw = json.loads(
            db.execute("SELECT seed_json FROM execution_option_swing_seeds").fetchone()[0]
        )
        assert fingerprint(SwingSeed.model_validate(raw)) == fingerprint(f.swing[0].seed)


@pytest.mark.parametrize("key,right", CASES)
def test_paid_fresh_rejection_retains_level_charge(tmp_path, monkeypatch, key, right):
    f, policy = level_frame(key, right)
    with owner(tmp_path, right, swing=policy, ai=True) as (c, v, _):
        calls = fake_model(monkeypatch, c)
        prepare = c.engine.prepare

        def changed(key, proposal, quote=None, underlying=None, **kwargs):
            return prepare(key, proposal, quote, touch(f), **kwargs)

        monkeypatch.setattr(c.engine, "prepare", changed)
        r = asyncio.run(c.cycle(f))
        assert r["status"] != "OPEN" and len(calls) == 1 and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert D(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) == D(
                ".00015"
            )


def test_unknown_level_entry_usage_stays_unknown(tmp_path, monkeypatch):
    f, policy = level_frame()
    with owner(tmp_path, swing=policy, ai=True) as (c, v, _):
        fake_model(
            monkeypatch, c, changes=lambda req, result: result.model_copy(update={"usage": None})
        )
        r = asyncio.run(c.cycle(f))
        assert r["status"] != "OPEN" and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None


@pytest.mark.parametrize("key,right", CASES)
def test_runtime_delivery_retains_original_level_evidence_and_terminal(tmp_path, key, right):
    from test_option_runtime import enable, packet, step
    from test_option_runtime import policy as runtime_policy

    from app.options.runtime import OptionRuntime

    f, policy = level_frame(key, right)
    with owner(tmp_path, right, swing=policy) as (c, v, _):
        lock_seeds(c, f.swing)
        runtime = OptionRuntime(c, runtime_policy(tmp_path), create=True)
        enable(runtime)
        packet(runtime, value=f.model_copy(update={"underlyings": (touch(f),)}))
        asyncio.run(step(runtime))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed).status == "TARGET_CONSUMED"
            locked = SwingSeed.model_validate_json(
                db.execute("SELECT seed_json FROM execution_option_swing_seeds").fetchone()[0]
            )
            assert locked.level_key == key and locked.hourly_history is None
        assert v.submit_count == 0


def test_weekly_open_requires_available_aligned_daily_regime():
    raw = level_request("weekly_open").model_dump()
    for b in raw["history"]["bars"]:
        b.update(open=D(598), low=D(597), high=D(601), close=D(600))
    req = SwingSeedBuildRequest.model_validate(raw)
    e = evaluate_level(build_swing_seed(req))
    assert e.daily_direction == "neutral"
    assert "SWING_LEVEL_DIRECTION_REQUIRED" in e.reasons


@pytest.mark.parametrize("recent_cross", [True, False])
def test_weekly_level_uses_latest_cross_inside_exact_twelve_bar_window(recent_cross):
    raw = level_request("weekly_open").model_dump()
    bars = raw["history"]["bars"]
    # Weekly open stays 598. An old cross just outside the 13-bar input window
    # must not authorize a current retest. A new final cross supersedes it.
    for b in bars[-14:]:
        b.update(open=D(598), low=D(597), high=D(601), close=D(600))
    bars[-15].update(open=D(597), low=D(596), high=D(598), close=D(597))
    if recent_cross:
        bars[-2].update(close=D(597))
    req = SwingSeedBuildRequest.model_validate(raw)
    e = evaluate_level(build_swing_seed(req))
    assert e.breakout_at == (req.history.bars[-1].closes_at if recent_cross else None)
    assert ("SWING_LEVEL_COMPLETED_BREAK_REQUIRED" in e.reasons) != recent_cross
