"""Source-derived daily MA variants through the shared native PAPER owner."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

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
from app.options.swing_lifecycle import load_terminal
from app.options.swing_ma import evaluate_ma
from app.options.swing_ma_models import MA_FAMILIES
from app.options.swing_targets import SwingSeedBuildRequest, build_swing_seed, target_issues
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def ma_request(right="CALL", period=8, *, seed=None, policy=None):
    policy = (
        policy.model_copy(update={"ma_pullback": None, "daily_base": None, "daily_lookback": 3})
        if policy is not None
        else None
    )
    raw = base_request(right, seed=seed, policy=policy).model_dump()
    right = raw["instrument"]["contract"]["right"]
    raw["policy"].update(
        daily_base=None,
        daily_lookback=56,
        ma_pullback={
            "periods": (8, 21, 50),
            "hourly_source": "fixture-hourly",
            "hourly_lookback": 54,
        },
    )
    raw["ma_period"] = period
    bars = raw["history"]["bars"]
    cal = XNYSCalendar().calendar
    previous = cal.previous_session(bars[0]["begins_at"].date().isoformat())
    bars = [
        dict(
            bars[0],
            begins_at=cal.session_open(previous).to_pydatetime(),
            closes_at=cal.session_close(previous).to_pydatetime(),
        )
    ] + list(bars)
    for n, b in enumerate(bars):
        close = D("588.2") + D(".2") * n if n < 55 else D("599.8")
        o, low, high = close - D(".1"), close - D(".2"), close + D(".2")
        if n == 55:
            # A strong confirmed daily body touches all three rising averages.
            o, low, high = D("590"), D("589.8"), D(600)
        if right == "PUT":
            o, low, high, close = 1200 - o, 1200 - high, 1200 - low, 1200 - close
        b.update(open=o, low=low, high=high, close=close)
    raw["history"].update(version="swing-ma-daily-v1", bars=bars)
    return SwingSeedBuildRequest.model_validate(raw)


def ma_frame(right="CALL", period=8):
    req = ma_request(right, period)
    item = swing_input(right).model_copy(update={"seed": build_swing_seed(req)})
    return shared_frame(right, item), req.policy


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("period", [8, 21, 50])
@pytest.mark.parametrize("precision", [4, 28])
def test_ma_geometry_matches_independent_rational_average_and_original_risk(
    right, period, precision
):
    req = ma_request(right, period)
    values = [Fraction(b.close) for b in req.history.bars]
    if period == 50:
        expected = sum(values[-50:]) / 50
    else:
        expected = values[0]
        for value in values[1:]:
            expected = value * Fraction(2, period + 1) + expected * Fraction(period - 1, period + 1)
    with localcontext() as ctx:
        ctx.prec = precision
        seed = build_swing_seed(req)
        evidence = evaluate_ma(seed)
    assert abs(Fraction(evidence.moving_average) - expected) < Fraction(1, 10**12)
    assert evidence.reasons == () and evidence.confirmations
    assert evidence.daily_direction == ("bullish" if right == "CALL" else "bearish")
    assert seed.target_geometry.reference == 600
    assert seed.target_geometry.invalidation == (D("589.8") if right == "CALL" else D("610.2"))
    sign = 1 if right == "CALL" else -1
    assert seed.target_geometry.targets == tuple(D(600) + sign * D("10.2") * n for n in (1, 2, 3))
    assert not target_issues(seed, req.policy)
    assert SwingSeed.model_validate_json(seed.model_dump_json()) == seed


@pytest.mark.parametrize(
    "damage",
    [
        "period",
        "enrollment",
        "history",
        "hourly",
        "source",
        "future",
        "gap",
        "interpolated",
        "volume",
    ],
)
def test_ma_input_boundary_rejects_missing_unenrolled_or_corrupt_evidence(damage):
    raw = ma_request().model_dump()
    if damage == "period":
        raw["ma_period"] = None
    elif damage == "enrollment":
        raw["policy"]["ma_pullback"]["periods"] = (21,)
    elif damage == "history":
        raw["history"]["version"] = "swing-base-daily-v1"
    elif damage == "hourly":
        raw["hourly_history"] = None
    elif damage == "source":
        raw["hourly_history"]["source"] = "foreign"
    elif damage == "future":
        raw["history"]["received_at"] = raw["created_at"] + timedelta(seconds=1)
    else:
        b = raw["history"]["bars"][0]
        b.update(
            {"begins_at": b["begins_at"] + timedelta(minutes=1)}
            if damage == "gap"
            else {"interpolated": True}
            if damage == "interpolated"
            else {"volume": 0}
        )
    with pytest.raises(ValueError):
        build_swing_seed(SwingSeedBuildRequest.model_validate(raw))


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("direction", "SWING_MA_DAILY_DIRECTION_REQUIRED"),
        ("trend", "SWING_MA_ESTABLISHED_TREND_REQUIRED"),
        ("test", "SWING_MA_TEST_REQUIRED"),
        ("close", "SWING_MA_FAVORABLE_CLOSE_REQUIRED"),
        ("confirmation", "SWING_MA_DIRECTIONAL_CONFIRMATION_REQUIRED"),
    ],
)
def test_ma_source_rule_blocks_native_candidate(tmp_path, damage, reason):
    raw = ma_request().model_dump()
    bars = raw["history"]["bars"]
    if damage == "direction":
        for b in bars[:-1]:
            b.update(open=D(600), high=D(601), low=D(599), close=D(600))
    elif damage == "trend":
        bars[-2].update(open=D(590), high=D(591), low=D(589), close=D(590))
    elif damage == "test":
        bars[-1].update(open=D(610), high=D(612), low=D(610), close=D(612))
    elif damage == "close":
        bars[-1].update(open=D(590), high=D(600), low=D(580), close=D(580))
    else:
        bars[-1].update(open=D("599.7"), low=D("599.6"), high=D("600.4"), close=D("599.8"))
    req = SwingSeedBuildRequest.model_validate(raw)
    seed = build_swing_seed(req)
    assert reason in evaluate_ma(seed).reasons
    f = shared_frame(item=swing_input().model_copy(update={"seed": seed}))
    with owner(tmp_path, swing=req.policy) as (c, v, _):
        result = c.quote_plan(f.histories, (), f.swing)
        scan = next(s for s in result["scans"] if s.version == "swing-next-session-v1")
        assert reason in scan.observations[0].reasons
        assert scan.observations[0].status != "CONFIRMED" and v.submit_count == 0


def test_ma_diagnostics_do_not_change_pinned_confirmation_rules():
    raw = ma_request().model_dump()
    raw["history"]["bars"][-1]["volume"] = 1
    for n, b in enumerate(raw["hourly_history"]["bars"]):
        b.update(open=D(700 - n), close=D(700 - n), high=D(701 - n), low=D(699 - n))
    e = evaluate_ma(build_swing_seed(SwingSeedBuildRequest.model_validate(raw)))
    assert e.reasons == ()
    assert "SWING_MA_LOW_CONFIRMATION_VOLUME" in e.warnings
    assert "SWING_MA_HOURLY_OPPOSED" in e.warnings


def test_ma_never_appears_in_frozen_legacy_contracts():
    old = legacy_request()
    seed = build_swing_seed(old)
    assert "ma_period" not in seed.model_dump()
    assert "ma_pullback" not in old.policy.model_dump()
    assert target_issues(build_swing_seed(ma_request()), old.policy) == (
        "SWING_MA_ENROLLMENT_REQUIRED",
    )
    with pytest.raises(ValueError):
        SwingPolicy.model_validate(
            ma_request().policy.model_dump()
            | {"daily_base": {"hourly_source": "fixture-hourly", "hourly_lookback": 54}}
        )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("period", [8, 21, 50])
def test_native_ma_entry_actual_fill_and_original_stop(tmp_path, monkeypatch, right, ai, period):
    f, policy = ma_frame(right, period)
    with owner(tmp_path, right, swing=policy, ai=ai) as (c, v, times):
        calls = fake_model(monkeypatch, c) if ai else []
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        selected = next(x for x in result["candidates"] if x["family"] == MA_FAMILIES[period])
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
        assert intent["entry_lineage"]["setup"] == MA_FAMILIES[period]
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


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("reason", ["TARGET_CONSUMED", "INVALIDATED"])
@pytest.mark.parametrize("period", [8, 21, 50])
def test_original_ma_stop_and_target_retire_across_restart(tmp_path, right, reason, period):
    f, policy = ma_frame(right, period)
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


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("period", [8, 21, 50])
def test_paid_fresh_rejection_retains_ma_charge(tmp_path, monkeypatch, right, period):
    f, policy = ma_frame(right, period)
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


def test_unknown_ma_entry_usage_stays_unknown(tmp_path, monkeypatch):
    f, policy = ma_frame(period=21)
    with owner(tmp_path, swing=policy, ai=True) as (c, v, _):
        fake_model(
            monkeypatch, c, changes=lambda req, result: result.model_copy(update={"usage": None})
        )
        r = asyncio.run(c.cycle(f))
        assert r["status"] != "OPEN" and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None


@pytest.mark.parametrize("period", [8, 21, 50])
def test_runtime_delivery_retains_original_ma_evidence_and_terminal(tmp_path, period):
    from test_option_runtime import enable, packet, step
    from test_option_runtime import policy as runtime_policy

    from app.options.runtime import OptionRuntime

    f, policy = ma_frame(period=period)
    with owner(tmp_path, swing=policy) as (c, v, _):
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
            assert locked.hourly_history == f.swing[0].seed.hourly_history
        assert v.submit_count == 0


@pytest.mark.parametrize("period", [8, 21, 50])
@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("atr_dominates", [False, True])
def test_original_ma_buffer_uses_average_or_atr_without_moving_targets(
    period, right, atr_dominates
):
    from decimal import ROUND_CEILING, ROUND_FLOOR

    raw = ma_request(right, period).model_dump()
    b = raw["history"]["bars"][-1]
    b.update(
        open=D("599.6") if right == "CALL" else D("600.4"),
        low=D("599.4") if right == "CALL" else D(600),
        high=D(600) if right == "CALL" else D("600.6"),
    )
    if atr_dominates:
        raw["history"]["bars"][-5].update(high=D(1000), low=D(200))
    req = SwingSeedBuildRequest.model_validate(raw)
    bars = req.history.bars
    values = [Fraction(x.close) for x in bars]
    if period == 50:
        average = sum(values[-50:]) / 50
    else:
        average = values[0]
        for value in values[1:]:
            average = (value * 2 + average * (period - 1)) / (period + 1)
    trs = [
        max(
            Fraction(b.high - b.low),
            abs(Fraction(b.high - bars[n - 1].close)),
            abs(Fraction(b.low - bars[n - 1].close)),
        )
        for n, b in enumerate(bars)
        if n >= len(bars) - 14
    ]
    atr = sum(trs) / 14
    average_buffer = average * (Fraction(6, 1000) if period == 50 else Fraction(4, 1000))
    atr_buffer = atr * Fraction(15, 100)
    assert (atr_buffer > average_buffer) == atr_dominates
    stop = (
        average - max(average_buffer, atr_buffer)
        if right == "CALL"
        else average + max(average_buffer, atr_buffer)
    )
    exact_stop = (D(stop.numerator) / D(stop.denominator)).quantize(
        D(".000000000001"), rounding=ROUND_CEILING if right == "CALL" else ROUND_FLOOR
    )
    seed = build_swing_seed(req)
    assert seed.target_geometry.invalidation == exact_stop


@pytest.mark.parametrize(
    "shape,expected",
    [
        ("engulf", "ENGULFING"),
        ("rejection", "REJECTION"),
        ("strong", "STRONG_CLOSE"),
        ("doji", None),
        ("inside", None),
    ],
)
@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_only_directional_source_candle_confirmations_authorize(shape, expected, right):
    from app.options.swing_ma import confirmations

    bars = list(ma_request().history.bars)
    previous = bars[-2].model_copy(
        update={"open": D(599), "close": D("599.2"), "low": D(598), "high": D(601)}
    )
    o, h, l, c = {
        "engulf": (598, 600, 598, 600),
        "rejection": (599, 600, 590, 600),
        "strong": (598, 600, 598, 600),
        "doji": (599, 600, 598, 599),
        "inside": (599, 600, 598.5, 599.1),
    }[shape]
    o, h, l, c = (D(str(x)) for x in (o, h, l, c))
    current = bars[-1].model_copy(update={"open": o, "high": h, "low": l, "close": c})
    if right == "PUT":
        previous, current = [
            b.model_copy(
                update={
                    "open": 1200 - b.open,
                    "close": 1200 - b.close,
                    "low": 1200 - b.high,
                    "high": 1200 - b.low,
                }
            )
            for b in (previous, current)
        ]
    tags = confirmations([previous, current], right == "CALL")
    assert expected in tags if expected else not tags
