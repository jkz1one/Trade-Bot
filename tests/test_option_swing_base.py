"""Full base evidence reaches the shared native owner without changing legacy seeds."""

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from test_option_entry_coordination import fake_model
from test_option_execution import intent_for, ledger
from test_option_shared_strategy import shared_frame, swing_input
from test_option_swing_target_derivation import owner
from test_option_swing_target_derivation import request as target_request
from test_option_swing_targets import touch

from app.options.engine import fingerprint
from app.options.shared_strategy import lock_seeds
from app.options.swing import (
    SwingBaseHistory,
    SwingDailyBar,
    SwingHourlyHistory,
    SwingPolicy,
    SwingSeed,
)
from app.options.swing_base import direction, evaluate_base
from app.options.swing_lifecycle import load_terminal
from app.options.swing_targets import SwingSeedBuildRequest, build_swing_seed, target_issues
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def base_request(right="CALL", *, seed=None, policy=None):
    seed = seed or swing_input(right).seed
    right = seed.instrument.contract.right
    raw = target_request(seed=seed, policy=policy).model_dump()
    raw["policy"] = SwingPolicy.model_validate(
        raw["policy"]
        | {
            "daily_lookback": 55,
            "daily_base": {"hourly_source": "fixture-hourly", "hourly_lookback": 54},
        }
    )
    cal = XNYSCalendar().calendar
    session = cal.previous_session(seed.target_session.isoformat())
    sessions = [session]
    for _ in range(54):
        sessions.insert(0, cal.previous_session(sessions[0]))

    def bar(begin, end, *, breakout=False):
        o, high, low, close = (
            (D(599), D(600), D(598), D("599.8")) if breakout else (D(598), D(599), D(597), D(598))
        )
        if right == "PUT":
            o, high, low, close = 1200 - o, 1200 - low, 1200 - high, 1200 - close
        return SwingDailyBar(
            begins_at=begin,
            closes_at=end,
            open=o,
            high=high,
            low=low,
            close=close,
            volume=130000 if breakout else 100000,
            interpolated=False,
        )

    daily = tuple(
        bar(
            cal.session_open(s).to_pydatetime(),
            cal.session_close(s).to_pydatetime(),
            breakout=n == 54,
        )
        for n, s in enumerate(sessions)
    )
    raw["history"] = SwingBaseHistory.model_validate(
        seed.history.model_dump()
        | {
            "version": "swing-base-daily-v1",
            "bars": daily,
        }
    )
    hourly, end = [], cal.session_close(session).to_pydatetime()
    for _ in range(54):
        opened = cal.session_open(session).to_pydatetime()
        begins = opened + timedelta(hours=int((end - opened).total_seconds() - 1) // 3600)
        hourly.insert(0, bar(begins, end))
        end = begins
        if end == opened:
            session = cal.previous_session(session)
            end = cal.session_close(session).to_pydatetime()
    raw["hourly_history"] = SwingHourlyHistory(
        symbol=seed.history.symbol,
        bars=tuple(hourly),
        source="fixture-hourly",
        source_at=seed.history.source_at,
        received_at=seed.history.received_at,
        entitlement="REALTIME",
        complete=True,
    )
    return SwingSeedBuildRequest.model_validate(raw)


def base_frame(right="CALL", *, seed=None, policy=None):
    item = swing_input(right)
    req = base_request(right, seed=seed, policy=policy)
    item = item.model_copy(update={"seed": build_swing_seed(req)})
    return clear_prior_stop(shared_frame(right, item), right), req.policy


def clear_prior_stop(frame, right="CALL"):
    histories = tuple(
        h.model_copy(
            update={
                "bars": tuple(
                    b.model_copy(update={"low": max(b.low, D("598.2"))})
                    if right == "CALL"
                    else b.model_copy(update={"high": min(b.high, D("601.8"))})
                    for b in h.bars
                )
            }
        )
        for h in frame.histories
    )
    return frame.model_copy(update={"histories": histories})


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("precision", [4, 28])
def test_original_base_geometry_uses_prior_base_atr_and_exact_risk(right, precision):
    req = base_request(right)
    with localcontext() as ctx:
        ctx.prec = precision
        seed = build_swing_seed(req)
        evidence = evaluate_base(seed)
    expected = D("598.1015") if right == "CALL" else D("601.9015")
    assert evidence.invalidation == expected
    assert evidence.prior_atr == 2 and evidence.volume_ratio == D("1.3")
    assert evidence.reasons == ()
    assert evidence.daily_direction == evidence.hourly_direction == "neutral"
    assert seed.target_geometry.invalidation == expected
    assert not target_issues(seed, req.policy)
    assert SwingSeed.model_validate(seed.model_dump(mode="json")) == seed
    assert "version" in seed.model_dump()["history"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "source",
        "symbol",
        "late",
        "future",
        "gap",
        "unfinished",
        "interpolated",
        "zero-volume",
        "incomplete",
        "delayed",
        "legacy-daily",
    ],
)
def test_missing_or_invalid_hourly_source_never_becomes_neutral(damage):
    req = base_request()
    h = req.hourly_history
    changes = {
        "source": {"source": "other"},
        "symbol": {"symbol": "QQQ"},
        "late": {"received_at": req.created_at + timedelta(seconds=1)},
        "future": {"source_at": req.created_at + timedelta(seconds=1)},
        "incomplete": {"complete": False},
        "delayed": {"entitlement": "DELAYED"},
    }
    if damage in changes:
        req = req.model_copy(update={"hourly_history": h.model_copy(update=changes[damage])})
    elif damage == "missing":
        req = req.model_copy(update={"hourly_history": None})
    elif damage == "legacy-daily":
        req = req.model_copy(update={"history": swing_input().seed.history})
    else:
        bars = list(h.bars)
        c = {
            "gap": {"begins_at": bars[0].begins_at + timedelta(minutes=1)},
            "unfinished": {"closes_at": bars[0].closes_at + timedelta(minutes=1)},
            "interpolated": {"interpolated": True},
            "zero-volume": {"volume": 0},
        }
        bars[0] = bars[0].model_copy(update=c[damage])
        req = req.model_copy(update={"hourly_history": h.model_copy(update={"bars": tuple(bars)})})
    with pytest.raises(ValueError):
        build_swing_seed(req)


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("volume", "SWING_BASE_VOLUME_EXPANSION_REQUIRED"),
        ("close", "SWING_BASE_STRONG_CLOSE_REQUIRED"),
        ("boundary", "SWING_BASE_BOUNDARY_CLOSE_REQUIRED"),
        ("extension", "SWING_BASE_ATR_EXTENSION_EXCEEDED"),
        ("width", "SWING_BASE_COMPRESSION_REQUIRED"),
        ("opposed", "SWING_BASE_REGIME_OPPOSED"),
    ],
)
def test_each_source_rule_blocks_base_candidate(damage, reason, tmp_path):
    req = base_request()
    bars = list(req.history.bars)
    current = bars[-1]
    if damage == "volume":
        bars[-1] = current.model_copy(update={"volume": 119999})
    elif damage == "close":
        bars[-1] = current.model_copy(update={"high": D(602)})
    elif damage == "boundary":
        bars[-1] = current.model_copy(update={"close": D(599)})
    elif damage == "extension":
        bars[-1] = current.model_copy(update={"high": D(603), "close": D("602.9")})
    elif damage == "width":
        bars[-10] = bars[-10].model_copy(update={"low": D(500)})
    else:
        h = req.hourly_history
        hourly = tuple(
            b.model_copy(
                update={
                    "open": D(700 - n),
                    "close": D(700 - n),
                    "high": D(701 - n),
                    "low": D(699 - n),
                }
            )
            for n, b in enumerate(h.bars)
        )
        req = req.model_copy(update={"hourly_history": h.model_copy(update={"bars": hourly})})
    req = req.model_copy(update={"history": req.history.model_copy(update={"bars": tuple(bars)})})
    seed = build_swing_seed(req)
    assert reason in evaluate_base(seed).reasons
    item = swing_input().model_copy(update={"seed": seed})
    f = shared_frame(item=item)
    with owner(tmp_path, swing=req.policy) as (c, _, _):
        plans = c.quote_plan(f.histories, (), f.swing)
        scan = next(s for s in plans["scans"] if s.version == "swing-next-session-v1")
        assert reason in scan.observations[0].reasons
        assert scan.observations[0].status != "CONFIRMED"


def test_old_enrollment_and_unavailable_regime_cannot_accept_new_inputs():
    req = base_request()
    with pytest.raises(ValueError):
        SwingPolicy.model_validate(req.policy.model_dump() | {"daily_base": None})
    with pytest.raises(ValueError):
        direction(req.history.bars[:35])
    seed = build_swing_seed(req)
    assert target_issues(seed, target_request().policy) == ("SWING_BASE_ENROLLMENT_REQUIRED",)
    assert "daily_base" not in target_request().policy.model_dump()
    assert "hourly_history" not in build_swing_seed(target_request()).model_dump()


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("ai", [False, True])
def test_native_base_entry_actual_fill_and_original_stop(tmp_path, monkeypatch, right, ai):
    f, policy = base_frame(right)
    with owner(tmp_path, right, swing=policy, ai=ai) as (c, v, times):
        calls = fake_model(monkeypatch, c) if ai else []
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        selected = next(x for x in result["candidates"] if x["family"] == "SWING_DAILY_BASE")
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
        assert intent["entry_lineage"]["setup"] == "SWING_DAILY_BASE"
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
def test_original_base_stop_and_target_retire_across_restart(tmp_path, right, reason):
    f, policy = base_frame(right)
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
def test_paid_fresh_rejection_retains_base_charge(tmp_path, monkeypatch, right):
    f, policy = base_frame(right)
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


@pytest.mark.parametrize("target", [date(2026, 3, 9), date(2026, 11, 30)])
def test_original_hourly_coverage_uses_actual_dst_and_half_day_calendar(target):
    req = base_request(seed=swing_input(target=target).seed)
    seed = build_swing_seed(req)
    assert not target_issues(seed, req.policy)
    assert any(
        (b.closes_at - b.begins_at) == timedelta(minutes=30) for b in seed.hourly_history.bars
    )
    if target.month == 11:
        assert seed.hourly_history.bars[-1].closes_at.hour == 18


def test_unknown_base_entry_usage_stays_unknown(tmp_path, monkeypatch):
    f, policy = base_frame()
    with owner(tmp_path, swing=policy, ai=True) as (c, v, _):
        fake_model(
            monkeypatch, c, changes=lambda req, result: result.model_copy(update={"usage": None})
        )
        r = asyncio.run(c.cycle(f))
        assert r["status"] != "OPEN" and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None


def test_prior_observed_base_stop_blocks_before_quote_request(tmp_path):
    req = base_request()
    item = swing_input().model_copy(update={"seed": build_swing_seed(req)})
    f = shared_frame(item=item)  # Original opening low 598 is below the base stop 598.1015.
    with owner(tmp_path, swing=req.policy) as (c, v, _):
        plans = c.quote_plan(f.histories, (), f.swing)
        scan = next(s for s in plans["scans"] if s.version == "swing-next-session-v1")
        assert scan.terminal.status == "INVALIDATED" and v.submit_count == 0


def test_runtime_delivery_retains_original_base_evidence_and_terminal(tmp_path):
    from test_option_runtime import enable, packet, step
    from test_option_runtime import policy as runtime_policy

    from app.options.runtime import OptionRuntime

    f, policy = base_frame()
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
