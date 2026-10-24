"""Original source derivation, shared native selection and independent stock protection."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame, policies
from test_mixed_accounting import changed, instrument
from test_mixed_native_owner import intent_for, settings
from test_option_swing_base import base_request
from test_option_swing_levels import level_request
from test_option_swing_ma import ma_request

from app.execution.engine import ExecutionBlocked
from app.mixed.carry import StockCatalyst
from app.mixed.sources import (
    StockCycleInput,
    StockDailyHistory,
    StockSelectionPolicy,
    StockSwingPolicy,
    StockSwingSource,
    geometry,
    validate_source,
)
from app.mixed.stock_models import StockQuote
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution
from app.options.market_tape import TapeEvent, _validate_event
from app.options.runtime_models import RuntimePacket
from app.options.venue import DurableOptionVenue
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def stock_policy(*, asset="STOCK", swing=None):
    return StockSelectionPolicy(
        instruments=(instrument(),),
        family_priority=("SWING", "DEGEN") if swing else ("DEGEN",),
        asset_priority=(asset, "OPTION" if asset == "STOCK" else "STOCK"),
        swing=swing,
    )


def quote(at=AT, **changes):
    return StockQuote(
        instrument=instrument(),
        source="stock-tape",
        source_at=at,
        received_at=at,
        entitlement="REALTIME",
        complete=True,
        bid="600.8",
        ask="600.81",
        bid_size="2",
        ask_size="2",
    ).model_copy(update=changes)


def stock_frame(*, at=AT, item=None):
    f = frame()
    return changed(f, stocks=(item or StockCycleInput(quote=quote(at)),))


@contextmanager
def owner(path, *, asset="STOCK", swing=None, carry=None):
    limits, p = settings(**({"stock_carry": carry} if carry else {}))
    p = changed(
        p, mixed_owner=changed(p.mixed_owner, stocks=changed(p.mixed_owner.stocks, share_step=".1"))
    )
    v = DurableOptionVenue(
        path / "venue.db", limits=limits, stock_limits=p.mixed_owner.stocks, capital=p.capital
    )
    times = [AT]
    with OptionExecution.open(path / "engine.db", limits, p, v, now=AT, create=True) as e:
        assert e.reconcile(v.snapshot(AT), now=AT)["reconciled"]
        e.assess_stock(None, now=AT)
        setup, selection = policies()
        c = DegenCoordinator(
            e,
            setup,
            selection,
            stock_policy=stock_policy(asset=asset, swing=swing),
            create=True,
            clock=lambda: times[0],
        )
        yield c, v, times


@pytest.mark.parametrize("asset", ["STOCK", "OPTION"])
def test_native_single_choice_and_actual_fills(tmp_path, asset):
    with owner(tmp_path, asset=asset) as (c, v, _times):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        chosen = out["mixed_selection"]["selected"]
        assert chosen["asset"] == asset
        assert {x["asset"] for x in out["mixed_selection"]["choices"]} == {"STOCK", "OPTION"}
        assert v.submit_count == 1
        if asset == "STOCK":
            entry = intent_for(c.engine, out["client_id"])
            at = AT + timedelta(seconds=1)
            v.fill_stock(entry, entry.quantity, quote(at), at, fill_id="actual-share-fill")
            assert c.engine.reconcile(v.snapshot(at), now=at)["reconciled"]
            assert c.engine.mixed_account(now=at).position.quantity == entry.quantity
            assert c.engine.journal.report(now=at)["ledger"]["position"] is None
        else:
            assert len(v.snapshot(AT).orders) == 1 and not v.snapshot(AT).stock_orders


def test_option_and_stock_bypasses_rejected(tmp_path):
    with owner(tmp_path) as (c, v, _):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        from app.options.selection import parse_candidate

        cand = parse_candidate(out["candidates"][0])
        f = stock_frame()
        bad = c.engine.prepare("unselected", cand.proposal, f.quotes[0], f.underlyings[0], now=AT)
        assert bad["status"] == "REJECTED"
        from app.mixed.selection import guard_option

        with (
            c.engine.journal.read() as db,
            pytest.raises(ExecutionBlocked, match="MIXED_ORIGINAL_SELECTION_REQUIRED"),
        ):
            guard_option(db, "unselected", cand.proposal, f.quotes[0])
        from app.mixed.sources import StockSourceCandidate

        stock = StockSourceCandidate.model_validate(out["stock_candidates"][0]["candidate"])
        bad = c.engine.prepare_stock("unselected-stock", stock.proposal, quote(), now=AT)
        assert bad["status"] == "REJECTED" and v.submit_count == 1


def test_stock_held_cycle_protects_without_candidate_inputs(tmp_path):
    with owner(tmp_path) as (c, v, times):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        at = AT + timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(at), at, fill_id="owned")
        assert c.engine.reconcile(v.snapshot(at), now=at)["reconciled"]
        times[0] = AT + timedelta(minutes=5)
        f = changed(
            stock_frame(),
            histories=(),
            inventories=(),
            quotes=(),
            underlyings=(),
            stocks=(StockCycleInput(quote=quote(times[0], bid=D("599"), ask=D("599.01"))),),
        )
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "HELD" and out["management"]["status"] == "OPEN", out
        closing = intent_for(c.engine, out["management"]["client_id"])
        assert closing.closing_entry_client_id == entry.client_id


def test_frozen_enrollment_and_restart(tmp_path):
    with owner(tmp_path) as (c, v, _times):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        e = c.engine
        saved = e.limits, e.policy, c.policy, c.selection, c.stock_policy
    limits, p, setup, selection, stocks = saved
    with OptionExecution.open(tmp_path / "engine.db", limits, p, v, now=AT) as e:
        with pytest.raises(ExecutionBlocked, match="FROZEN"):
            DegenCoordinator(
                e,
                setup,
                selection,
                stock_policy=changed(stocks, asset_priority=("OPTION", "STOCK")),
                clock=lambda: AT,
            )
        c = DegenCoordinator(e, setup, selection, stock_policy=stocks, clock=lambda: AT)
        assert asyncio.run(c.cycle(stock_frame())) == out
        assert v.submit_count == 1


def test_bearish_source_does_not_open_stock(tmp_path):
    with owner(tmp_path) as (c, v, _):
        f = changed(
            frame("PUT"), stocks=(StockCycleInput(quote=quote(bid=D("599.2"), ask=D("599.21"))),)
        )
        out = asyncio.run(c.cycle(f))
        assert out["stock_candidates"] == []
        assert out["mixed_selection"]["selected"]["asset"] == "OPTION"
        assert not v.snapshot(AT).stock_orders


@pytest.mark.parametrize("damage", ["missing", "duplicate", "foreign", "stale", "delayed"])
def test_stock_input_boundary_does_not_silently_ignore(tmp_path, damage):
    with owner(tmp_path) as (c, v, _):
        f = stock_frame()
        if damage == "missing":
            f = changed(f, stocks=())
        elif damage == "duplicate":
            f = changed(f, stocks=f.stocks * 2)
        else:
            q = quote()
            if damage == "foreign":
                q = changed(q, instrument=changed(q.instrument, instrument_id="wrong"))
            elif damage == "stale":
                q = changed(
                    q, source_at=AT - timedelta(seconds=30), received_at=AT - timedelta(seconds=30)
                )
            else:
                q = changed(q, entitlement="DELAYED")
            f = changed(f, stocks=(StockCycleInput(quote=q),))
        out = asyncio.run(c.cycle(f))
        assert not out.get("stock_candidates")
        assert not v.snapshot(AT).stock_orders


def source_fixture(family="SWING_DAILY_8_EMA"):
    if family == "SWING_DAILY_BASE":
        req = base_request()
    elif "WEEK" in family or "MONTH" in family:
        from app.options.swing_level_models import LEVEL_FAMILIES

        req = level_request(next(k for k, v in LEVEL_FAMILIES.items() if v == family))
    else:
        req = ma_request()
    bars = req.history.bars
    if len(bars) == 55:
        cal = XNYSCalendar().calendar
        s = cal.previous_session(bars[0].begins_at.date().isoformat())
        bars = (
            changed(
                bars[0],
                begins_at=cal.session_open(s).to_pydatetime(),
                closes_at=cal.session_close(s).to_pydatetime(),
            ),
            *bars,
        )
    h = StockDailyHistory.model_validate(
        req.history.model_dump() | {"version": "stock-swing-daily-v1", "bars": bars}
    )
    p = StockSwingPolicy(
        families=(family,),
        history_source=h.source,
        daily_lookback=56,
        hourly_source="fixture-hourly",
        hourly_lookback=54,
        catalyst_source="stock-catalyst",
        catalyst_max_age_seconds=30,
        maximum_chase_fraction=".0065",
        stop_buffer_fraction=".0001",
    )
    s = StockSwingSource(
        created_at=req.created_at,
        target_session=req.target_session,
        instrument=instrument(),
        history=h,
        hourly_history=req.hourly_history
        if family == "SWING_DAILY_BASE" or "EMA" in family or "SMA" in family
        else None,
    )
    cat = StockCatalyst(
        source="stock-catalyst",
        source_at=AT,
        received_at=AT,
        entitlement="REALTIME",
        complete=True,
        symbol="SPY",
        status="CLEAR",
        valid_through=AT + timedelta(days=4),
    )
    return s, p, StockCycleInput(quote=quote(), swing=s, catalyst=cat), req


@pytest.mark.parametrize(
    "family",
    [
        "SWING_DAILY_BREAKOUT",
        "SWING_DAILY_BASE",
        "SWING_DAILY_8_EMA",
        "SWING_DAILY_21_EMA",
        "SWING_DAILY_50_SMA",
        "SWING_PREVIOUS_WEEK_HIGH",
        "SWING_PREVIOUS_MONTH_HIGH",
        "SWING_WEEKLY_OPEN",
        "SWING_PREVIOUS_WEEK_LOW",
        "SWING_PREVIOUS_MONTH_LOW",
    ],
)
def test_all_stock_swing_source_families_without_option_identity(family):
    s, p, _item, _ = source_fixture(family)
    assert validate_source(s, p, XNYSCalendar()) == s
    reference, stop, reasons = geometry(s, family, p)
    assert reference > stop > 0
    if family.endswith("_LOW"):
        assert reasons
    assert "contract" not in s.instrument.model_dump()


def test_native_swing_stock_selection_and_original_lineage(tmp_path):
    _s, p, item, _ = source_fixture()
    with owner(tmp_path, swing=p) as (c, _v, _):
        out = asyncio.run(c.cycle(stock_frame(item=item)))
        assert out["status"] == "OPEN", out
        assert out["mixed_selection"]["selected"]["family"] == "SWING"
        assert out["selected_asset"] == "STOCK"
        entry = intent_for(c.engine, out["client_id"])
        assert entry.family == "SWING" and entry.original_target > D(600)
        with c.engine.journal.read() as db:
            assert (
                db.execute("SELECT source_hash FROM execution_mixed_stock_sources").fetchone()[0]
                == entry.source_hash
            )


@pytest.mark.parametrize("damage", ["daily-gap", "hourly-gap", "future", "foreign", "incomplete"])
def test_original_sources_reject_rewritten_or_missing_history(damage):
    s, p, _, _ = source_fixture()
    if damage == "future":
        s = changed(s, created_at=AT)
    elif damage == "foreign":
        s = changed(s, history=changed(s.history, symbol="QQQ"))
    elif damage == "incomplete":
        s = changed(s, history=changed(s.history, complete=False))
    elif damage == "daily-gap":
        s = changed(
            s,
            history=changed(
                s.history,
                bars=(
                    changed(
                        s.history.bars[0],
                        begins_at=s.history.bars[0].begins_at + timedelta(minutes=1),
                    ),
                    *s.history.bars[1:],
                ),
            ),
        )
    else:
        s = changed(
            s,
            hourly_history=changed(
                s.hourly_history,
                bars=(
                    changed(
                        s.hourly_history.bars[0],
                        closes_at=s.hourly_history.bars[0].closes_at - timedelta(minutes=1),
                    ),
                    *s.hourly_history.bars[1:],
                ),
            ),
        )
    with pytest.raises(ValueError):
        validate_source(s, p, XNYSCalendar())


def test_old_runtime_and_tape_reject_stock_frames():
    f = stock_frame()
    with pytest.raises(ValueError, match="Stock inputs"):
        RuntimePacket(population_id="p", sequence=1, recorded_at=AT, frame=f)
    from types import SimpleNamespace

    event = TapeEvent(sequence=1, previous_hash="a" * 64, recorded_at=AT, kind="CYCLE", frame=f)
    with pytest.raises(ValueError, match="Stock frames"):
        _validate_event(SimpleNamespace(), event)


@pytest.mark.parametrize(
    "priority",
    [("SCOPE", "SWING", "DEGEN"), ("DEGEN", "SWING", "SCOPE"), ("SWING", "DEGEN", "SCOPE")],
)
def test_native_scope_stock_option_competition(tmp_path, monkeypatch, priority):
    import test_option_scope_arbitration as fixture
    import test_option_scope_watch as watch_fixture
    from test_option_shared_strategy import swing_policy as original_swing_policy

    _limits, p = settings()
    mixed = changed(
        p.mixed_owner,
        stocks=changed(p.mixed_owner.stocks, provider="fixture-provider", share_step=".1"),
    )
    original_execution = fixture.execution_policy
    monkeypatch.setattr(
        fixture, "execution_policy", lambda: original_execution() | {"mixed_owner": mixed}
    )
    monkeypatch.setattr(
        fixture,
        "swing_policy",
        lambda: original_swing_policy(family_priority=tuple(f for f in priority if f != "SCOPE")),
    )
    original_venue = watch_fixture.DurableOptionVenue
    monkeypatch.setattr(
        watch_fixture,
        "DurableOptionVenue",
        lambda *a, **kw: original_venue(*a, stock_limits=mixed.stocks, **kw),
    )
    stock = changed(
        stock_policy(),
        instruments=(changed(instrument(), provider="fixture-provider"),),
        family_priority=priority,
    )
    with fixture.shared(
        tmp_path, priority=priority, coordinator_options={"stock_policy": stock}
    ) as (c, v, times, f):
        q = changed(quote(times[0]), instrument=stock.instruments[0])
        out = asyncio.run(c.cycle(changed(f, stocks=(StockCycleInput(quote=q),))))
        assert out["status"] == "OPEN", out
        assert out["mixed_selection"]["selected"]["family"] == priority[0]
        assert out["mixed_selection"]["selected"]["asset"] == (
            "STOCK" if priority[0] == "DEGEN" else "OPTION"
        )
        assert v.submit_count == 1


@pytest.mark.parametrize("reason", ["INVALIDATED", "TARGET_CONSUMED"])
def test_unfilled_stock_source_retirement_survives_rebound_restart(tmp_path, reason):
    from app.mixed.selection import collect

    s, p, item, _ = source_fixture()
    _, stop, _ = geometry(s, p.families[0], p)
    reference = geometry(s, p.families[0], p)[0]
    target = 2 * reference - stop
    bid = stop if reason == "INVALIDATED" else target
    touched = changed(item, quote=changed(item.quote, bid=bid, ask=bid + D(".01")))
    with owner(tmp_path, swing=p) as (c, v, _):
        data = {"candidates": []}
        collect(c, "observed", stock_frame(item=touched), data)
        with c.engine.journal.read() as db:
            row = db.execute("SELECT evidence_json FROM execution_mixed_stock_terminals").fetchone()
            assert reason in row[0]
        data = {"candidates": []}
        collect(c, "rebound", stock_frame(item=item), data)
        assert all(
            x["candidate"]["proposal"]["family"] != "SWING" for x in data["stock_candidates"]
        )
        saved = c.engine.limits, c.engine.policy, c.policy, c.selection, c.stock_policy
    limits, policy, setup, selection, stocks = saved
    with OptionExecution.open(tmp_path / "engine.db", limits, policy, v, now=AT) as e:
        c = DegenCoordinator(e, setup, selection, stock_policy=stocks, clock=lambda: AT)
        data = {"candidates": []}
        collect(c, "after-restart", stock_frame(item=item), data)
        assert all(
            x["candidate"]["proposal"]["family"] != "SWING" for x in data["stock_candidates"]
        )
        assert v.submit_count == 0


def test_changed_original_stock_source_cannot_replace_locked_root(tmp_path):
    from app.mixed.selection import collect

    s, p, item, _ = source_fixture()
    with owner(tmp_path, swing=p) as (c, _v, _):
        collect(c, "original", stock_frame(item=item), {"candidates": []})
        altered = changed(s, created_at=s.created_at + timedelta(seconds=1))
        with pytest.raises(ExecutionBlocked, match="ORIGINAL_SOURCE_CHANGED"):
            collect(
                c, "rewrite", stock_frame(item=changed(item, swing=altered)), {"candidates": []}
            )


@pytest.mark.parametrize("bad", ["quote", "catalyst"])
def test_completed_target_retires_even_when_entry_evidence_stale(tmp_path, bad):
    from app.mixed.selection import collect

    s, p, item, _ = source_fixture()
    reference, stop, _ = geometry(s, p.families[0], p)
    target = 2 * reference - stop
    f = stock_frame(item=item)
    h = f.histories[0]
    bars = (*h.bars[:-1], changed(h.bars[-1], high=target))
    if bad == "quote":
        item = changed(
            item,
            quote=changed(
                item.quote,
                source_at=AT - timedelta(seconds=30),
                received_at=AT - timedelta(seconds=30),
            ),
        )
    else:
        item = changed(item, catalyst=changed(item.catalyst, status="UNKNOWN"))
    f = changed(f, histories=(changed(h, bars=bars),), stocks=(item,))
    with owner(tmp_path, swing=p) as (c, _v, _):
        collect(c, "observed", f, {"candidates": []})
        with c.engine.journal.read() as db:
            assert (
                "TARGET_CONSUMED"
                in db.execute(
                    "SELECT evidence_json FROM execution_mixed_stock_terminals"
                ).fetchone()[0]
            )


def test_ask_alone_cannot_retire_original_target(tmp_path):
    from app.mixed.selection import collect

    s, p, item, _ = source_fixture()
    reference, stop, _ = geometry(s, p.families[0], p)
    target = 2 * reference - stop
    item = changed(item, quote=changed(item.quote, bid=target - D(".01"), ask=target))
    with owner(tmp_path, swing=p) as (c, _v, _):
        collect(c, "spread", stock_frame(item=item), {"candidates": []})
        with c.engine.journal.read() as db:
            assert (
                db.execute("SELECT count(*) FROM execution_mixed_stock_terminals").fetchone()[0]
                == 0
            )


def test_unselected_and_original_target_attribution_after_close(tmp_path):
    from test_mixed_native_owner import close

    from app.mixed.native_outcome import stock_outcome

    _s, p, item, _ = source_fixture()
    with owner(tmp_path, swing=p) as (c, v, _):
        out = asyncio.run(c.cycle(stock_frame(item=item)))
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        at = AT + timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(at), at, fill_id="original-source-fill")
        assert c.engine.reconcile(v.snapshot(at), now=at)["reconciled"]
        c.engine.assess_stock(quote(at), now=at)
        close(c.engine, v, entry, at + timedelta(seconds=1), bid="602")
        with c.engine.journal.read() as db:
            result = stock_outcome(c.engine, db, entry.client_id)
        assert result["entry_lineage"]["setup_family"] == "SWING_DAILY_8_EMA"
        assert result["entry_lineage"]["candidate_id"] == out["candidate_id"]
        assert D(result["entry_lineage"]["original_targets"][0]) == entry.original_target
        assert result["status"] == "COMPLETE"


def test_original_stock_source_binds_native_carry(tmp_path):
    from datetime import date

    from test_mixed_stock_carry import carry_policy

    s, p, item, _ = source_fixture()
    item = changed(item, swing=changed(s, carry_exit_session=date(2026, 10, 12)))
    with owner(tmp_path, swing=p, carry=carry_policy()) as (c, v, _):
        out = asyncio.run(c.cycle(stock_frame(item=item)))
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        assert entry.carry is not None
        assert entry.carry.source_hash == entry.source_hash
        assert entry.carry.sessions[-1].session == date(2026, 10, 12)
        assert entry.order_expires_at.date() == AT.date()
        at = AT + timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(at), at, fill_id="stock-source-carry")
        assert c.engine.reconcile(v.snapshot(at), now=at)["reconciled"]


@pytest.mark.parametrize("damage", ["proposal", "admission", "frame"])
def test_changed_selection_evidence_cannot_reach_native_attempt(tmp_path, monkeypatch, damage):
    import json

    from app.mixed.selection import receipt
    from app.options.engine import fingerprint

    with owner(tmp_path) as (c, v, _):
        dispatch = c.engine.dispatch_stock

        async def delayed(*args, **kwargs):
            return "PREPARED"

        monkeypatch.setattr(c.engine, "dispatch_stock", delayed)
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "PREPARED", out
        with c.engine.journal.write() as db:
            row = db.execute(
                "SELECT result_json,inputs_json FROM execution_option_opportunities WHERE cycle_key=?",
                (out["cycle_key"],),
            ).fetchone()
            data = json.loads(row[0])
            if damage == "proposal":
                data["stock_candidates"][0]["candidate"]["proposal"]["original_target"] = "650"
            elif damage == "admission":
                data["stock_candidates"][0]["admission"]["quantity"] = "1.9"
            else:
                f = json.loads(row[1])
                f["stocks"][0]["quote"]["ask"] = "601.1"
                db.execute(
                    "UPDATE execution_option_opportunities SET inputs_json=?,fingerprint=? WHERE cycle_key=?",
                    (json.dumps(f), fingerprint(f), out["cycle_key"]),
                )
            data["mixed_selection"] = receipt(c.stock_policy, out["cycle_key"], data)
            db.execute(
                "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                (json.dumps(data), out["cycle_key"]),
            )
        assert asyncio.run(dispatch(out["client_id"], quote(), now=AT)) == "REJECTED"
        assert v.submit_count == 0


def test_stale_dispatch_quote_cannot_retire_source(tmp_path, monkeypatch):
    _s, p, item, _ = source_fixture()
    with owner(tmp_path, swing=p) as (c, v, _):
        dispatch = c.engine.dispatch_stock

        async def delayed(*args, **kwargs):
            return "PREPARED"

        monkeypatch.setattr(c.engine, "dispatch_stock", delayed)
        out = asyncio.run(c.cycle(stock_frame(item=item)))
        assert out["status"] == "PREPARED", out
        q = quote(AT - timedelta(seconds=30), bid=D("500"), ask=D("500.01"))
        assert asyncio.run(dispatch(out["client_id"], q, now=AT)) == "REJECTED"
        with c.engine.journal.read() as db:
            assert (
                db.execute("SELECT count(*) FROM execution_mixed_stock_terminals").fetchone()[0]
                == 0
            )
        assert v.submit_count == 0


def test_native_preparation_cannot_extend_selection_deadline(tmp_path, monkeypatch):
    from datetime import datetime

    with owner(tmp_path) as (c, v, times):
        original = c._pending_evidence

        def later(key, evidence):
            original(key, evidence)
            times[0] = AT + timedelta(seconds=1)

        monkeypatch.setattr(c, "_pending_evidence", later)
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        assert entry.prepared_at == times[0]
        assert entry.approval_expires_at == datetime.fromisoformat(
            out["stock_candidates"][0]["admission"]["approval_expires_at"]
        )
        assert entry.approval_expires_at < entry.prepared_at + timedelta(
            seconds=c.engine.policy.mixed_owner.stocks.approval_lifetime_seconds
        )
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
