"""Completed evidence -> exact shortlist -> owned native PAPER order proof."""

import asyncio
import json
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_admission import NOW, inputs
from test_option_execution import configuration, intent_for, ledger, quote_at, underlying_at

from app.execution.engine import ExecutionBlocked
from app.options.coordinator import DegenCoordinator, DegenFrame
from app.options.degen import DegenBar, DegenHistory, DegenPolicy, scan_degen
from app.options.engine import OptionExecution
from app.options.selection import (
    ContractMetadata,
    ContractSelectionPolicy,
    OptionInventory,
    plan_contract_reads,
)
from app.options.venue import DurableOptionVenue

D = Decimal
AT = NOW.replace(hour=14)
OPEN = AT.replace(hour=13, minute=30)


def policies():
    return DegenPolicy(
        symbols=("SPY",),
        history_source="fixture-bars",
        max_bar_age_seconds=300,
        max_receive_lag_seconds=2,
        volume_lookback=3,
        minimum_volume_ratio="1.05",
        stop_buffer_fraction=".0001",
        maximum_extension_fraction=".0065",
        vwap_separation_fraction=".0022",
        vwap_touch_fraction=".0018",
    ), ContractSelectionPolicy(
        metadata_source="fixture-chain",
        max_inventory_contracts=8,
        max_quote_contracts=4,
        max_metadata_age_seconds=10,
        minimum_abs_delta=".25",
        maximum_abs_delta=".7",
        target_abs_delta=".45",
        maximum_strike_distance_fraction=".02",
        minimum_volume=10,
        minimum_open_interest=100,
    )


def history(right="CALL", *, at=AT):
    values = [
        ("599", "600", "598", "599"),
        ("599", "600", "598", "599"),
        ("599", "600", "598", "599"),
        ("600", "600.3", "599.9", "600.2"),
        ("600.2", "600.5", "600.1", "600.4"),
        ("600.4", "600.9", "600.3", "600.8"),
    ]
    bars = []
    for n, (o, h, l, c) in enumerate(values):
        if right == "PUT":
            o, h, l, c = (D(1200) - D(o), D(1200) - D(l), D(1200) - D(h), D(1200) - D(c))
        bars.append(
            DegenBar(
                begins_at=OPEN + timedelta(minutes=5 * n),
                open=o,
                high=h,
                low=l,
                close=c,
                volume=300 if n == 5 else 100,
                interpolated=False,
            )
        )
    return DegenHistory(
        symbol="SPY",
        source="fixture-bars",
        source_at=at,
        received_at=at,
        entitlement="REALTIME",
        complete=True,
        bars=tuple(bars),
    )


def inventory(right="CALL", *, at=AT):
    instrument = inputs(right)["quote"].instrument
    evidence = {
        "source": "fixture-chain",
        "source_at": at,
        "received_at": at,
        "entitlement": "REALTIME",
        "complete": True,
    }
    metadata = ContractMetadata(
        instrument=instrument,
        delta=".45" if right == "CALL" else "-.45",
        greek_provenance="OBSERVED",
        volume=500,
        open_interest=1000,
        **evidence,
    )
    return OptionInventory(
        request_id="chain-request",
        symbol="SPY",
        expiration=at.date(),
        contracts=(metadata,),
        **evidence,
    )


@contextmanager
def owned_strategy(path, right="CALL"):
    data, limits, policy = configuration(right)
    venue = DurableOptionVenue(path / "venue.db", limits=limits, capital=policy.capital)
    times = [AT]
    with OptionExecution.open(
        path / "options.db", limits, policy, venue, now=AT, create=True
    ) as engine:
        assert engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        engine.assess(None, None, now=AT)
        setup, selection = policies()
        coordinator = DegenCoordinator(
            engine, setup, selection, create=True, clock=lambda: times[0]
        )
        yield coordinator, venue, data, times, limits, policy


def frame(right="CALL"):
    data = inputs(right)
    price = "600.8" if right == "CALL" else "599.2"
    return DegenFrame(
        histories=(history(right),),
        inventories=(inventory(right),),
        quotes=(quote_at(data, AT),),
        underlyings=(underlying_at(data, AT, bid=D(price), ask=D(price) + D(".01")),),
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_completed_break_and_hold_has_volume_and_fifteen_confirmation(tmp_path, right):
    with owned_strategy(tmp_path, right) as (c, _, _, _, _, _):
        scan = scan_degen(history(right), c.policy, c.engine.calendar.current_window(AT), now=AT)
        observed = next(
            s for s in scan.observations if s.family == "ORB_CONTINUATION" and s.right == right
        )
        assert observed.status == "CONFIRMED"
        assert not observed.reasons and scan.volume_ratio == 3
        assert scan.completed_through == scan.higher_timeframe_through == AT
        assert all(s.status != "CONFIRMED" for s in scan.observations if s.right != right)


@pytest.mark.parametrize(
    "damage",
    ["delayed", "incomplete", "stale", "future", "gap", "duplicate", "interpolated", "foreign"],
)
def test_unusable_completed_history_cannot_generate_candidate(tmp_path, damage):
    h = history()
    bars = list(h.bars)
    changes = {}
    if damage == "delayed":
        changes["entitlement"] = "DELAYED"
    if damage == "incomplete":
        changes["complete"] = False
    if damage == "stale":
        changes.update(
            source_at=AT - timedelta(seconds=301), received_at=AT - timedelta(seconds=301)
        )
    if damage == "future":
        bars.append(bars[-1].model_copy(update={"begins_at": AT + timedelta(minutes=5)}))
    if damage == "gap":
        bars.pop(3)
    if damage == "duplicate":
        bars[3] = bars[2]
    if damage == "interpolated":
        bars[3] = bars[3].model_copy(update={"interpolated": True})
    if damage == "foreign":
        bars[0] = bars[0].model_copy(update={"begins_at": OPEN - timedelta(minutes=5)})
    h = h.model_copy(update={"bars": tuple(bars), **changes})
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        scan = scan_degen(h, c.policy, c.engine.calendar.current_window(AT), now=AT)
        assert scan.issues and all(s.status == "BLOCKED" for s in scan.observations)


def test_forming_bar_cannot_vote_or_change_completed_evidence(tmp_path):
    h = history()
    forming = DegenBar(
        begins_at=AT,
        open="601",
        high="900",
        low="500",
        close="899",
        volume=999999999,
        interpolated=False,
    )
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        w = c.engine.calendar.current_window(AT)
        baseline = scan_degen(h, c.policy, w, now=AT)
        with_forming = scan_degen(
            h.model_copy(update={"bars": (*h.bars, forming)}), c.policy, w, now=AT
        )
        assert baseline == with_forming


@pytest.mark.parametrize("value", [True, 100.5, "100", -1])
def test_volume_is_observed_whole_count(value):
    with pytest.raises(ValidationError):
        DegenBar.model_validate({**history().bars[0].model_dump(), "volume": value})


def test_inside_opening_range_is_not_failed_break_or_confirmed_setup(tmp_path):
    h = history()
    h = h.model_copy(
        update={
            "bars": tuple(
                h.bars[0].model_copy(update={"begins_at": OPEN + timedelta(minutes=5 * n)})
                for n in range(6)
            )
        }
    )
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        scan = scan_degen(h, c.policy, c.engine.calendar.current_window(AT), now=AT)
        assert all(s.status == "WATCHING" for s in scan.observations)
        assert all(
            "OBSERVED_FAILED_BREAK_REQUIRED" in s.reasons
            for s in scan.observations
            if s.family == "FAILED_BREAK_REVERSAL"
        )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_observed_failed_break_needs_reclaim_and_continuation(tmp_path, right):
    h = history()
    bars = list(h.bars)
    bars[2] = bars[2].model_copy(update={"close": D("598")})
    bars[4] = bars[4].model_copy(
        update={"open": D("597.7"), "high": D("597.8"), "low": D("597.3"), "close": D("597.5")}
    )
    bars[5] = bars[5].model_copy(
        update={"open": D("597.5"), "high": D("600.1"), "low": D("597.4"), "close": D("600")}
    )
    if right == "PUT":
        bars = [
            b.model_copy(
                update={
                    "open": 1200 - b.open,
                    "high": 1200 - b.low,
                    "low": 1200 - b.high,
                    "close": 1200 - b.close,
                }
            )
            for b in bars
        ]
    h = h.model_copy(update={"bars": tuple(bars)})
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        scan = scan_degen(h, c.policy, c.engine.calendar.current_window(AT), now=AT)
        setup = next(
            s for s in scan.observations if s.family == "FAILED_BREAK_REVERSAL" and s.right == right
        )
        assert setup.status == "CONFIRMED", setup
        assert (
            setup.invalidation < scan.last_close
            if right == "CALL"
            else setup.invalidation > scan.last_close
        )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_vwap_retest_uses_observed_separation_trend_and_favorable_close(tmp_path, right):
    closes = [D(600)] * 15 + [
        D("600.3"),
        D("600.6"),
        D("600.9"),
        D("601.2"),
        D("601.5"),
        D("601.8"),
        D("602.1"),
        D("601.1"),
        D("601.9"),
        D("602"),
    ]
    bars = []
    for n, close in enumerate(closes):
        o, high, low = close - D(".1"), close + D(".1"), close - D(".2")
        if n == 24:
            o, low = D("601"), D("600.6")
        if right == "PUT":
            o, high, low, close = 1200 - o, 1200 - low, 1200 - high, 1200 - close
        bars.append(
            DegenBar(
                begins_at=OPEN + timedelta(minutes=5 * n),
                open=o,
                high=high,
                low=low,
                close=close,
                volume=300 if n == 24 else 100,
                interpolated=False,
            )
        )
    at = OPEN + timedelta(minutes=125)
    h = history().model_copy(update={"bars": tuple(bars), "source_at": at, "received_at": at})
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        scan = scan_degen(h, c.policy, c.engine.calendar.current_window(at), now=at)
        setup = next(
            s for s in scan.observations if s.family == "VWAP_PULLBACK" and s.right == right
        )
        assert setup.status == "CONFIRMED", setup
        # Removing the actual volume confirmation vetoes the otherwise complete setup.
        h = h.model_copy(
            update={"bars": (*h.bars[:-1], h.bars[-1].model_copy(update={"volume": 1}))}
        )
        denied = scan_degen(h, c.policy, c.engine.calendar.current_window(at), now=at)
        observed = next(
            s for s in denied.observations if s.family == "VWAP_PULLBACK" and s.right == right
        )
        assert observed.status == "WATCHING" and "VOLUME_CONFIRMATION_REQUIRED" in observed.reasons


def test_shortlist_is_stable_and_capacity_counts_contracts_not_input_order(tmp_path):
    inv = inventory()
    base = inv.contracts[0]
    items = tuple(
        base.model_copy(
            update={
                "instrument": base.instrument.model_copy(
                    update={
                        "instrument_id": "contract-" + str(n),
                        "contract": base.instrument.contract.model_copy(
                            update={"strike": D(599 + n)}
                        ),
                    }
                )
            }
        )
        for n in range(6)
    )
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        scan = scan_degen(history(), c.policy, c.engine.calendar.current_window(AT), now=AT)
        first = plan_contract_reads(
            scan, inv.model_copy(update={"contracts": items}), c.selection, c.engine.limits, now=AT
        )
        second = plan_contract_reads(
            scan,
            inv.model_copy(update={"contracts": items[::-1]}),
            c.selection,
            c.engine.limits,
            now=AT,
        )
        assert first.instruments == second.instruments and len(first.instruments) == 4
        assert first.instruments[0].contract.strike == 601
        assert len(first.exclusions) == 2


@pytest.mark.parametrize(
    "damage", ["estimated", "missing_oi", "negative_delta", "wrong_root", "duplicate", "stale"]
)
def test_contract_metadata_exclusions_precede_quote_requests(tmp_path, damage):
    inv = inventory()
    item = inv.contracts[0]
    changes = {}
    if damage == "estimated":
        changes["greek_provenance"] = "ESTIMATED"
    if damage == "missing_oi":
        changes["open_interest"] = None
    if damage == "negative_delta":
        changes["delta"] = D("-.45")
    if damage == "wrong_root":
        changes["instrument"] = item.instrument.model_copy(
            update={"contract": item.instrument.contract.model_copy(update={"root": "XYZ"})}
        )
    if damage == "stale":
        changes.update(source_at=AT - timedelta(seconds=11), received_at=AT - timedelta(seconds=11))
    contracts = (item, item) if damage == "duplicate" else (item.model_copy(update=changes),)
    inv = inv.model_copy(update={"contracts": contracts})
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        plan = c.quote_plan((history(),), (inv,))["plans"][0]
        assert not plan.instruments and (plan.exclusions or plan.issues)


def test_missing_chain_and_stale_account_have_explicit_read_plan_reason(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, times, _, _):
        assert c.quote_plan((history(),), ())["plans"][0].issues == ("OPTION_INVENTORY_REQUIRED",)
        times[0] += timedelta(seconds=11)
        assert c.quote_plan((history(),), (inventory(),))["purpose"] == "ENTRY_HEALTH_BLOCKED"


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_candidate_enters_native_paper_once_then_owned_stop_exits(tmp_path, right):
    with owned_strategy(tmp_path, right) as (c, venue, data, times, _, _):
        f = frame(right)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        buy = intent_for(c.engine, result["client_id"])
        assert buy.quantity == 4 and venue.submit_count == 1
        assert asyncio.run(c.cycle(DegenFrame())) == result
        assert venue.submit_count == 1
        venue.fill(buy, buy.quantity, f.quotes[0], AT, fill_id="degen-fill")
        times[0] += timedelta(minutes=5)
        at = times[0]
        stop_price = "599" if right == "CALL" else "601"
        held_quote = quote_at(data, at)
        held_underlying = underlying_at(data, at, bid=D(stop_price), ask=D(stop_price) + D(".01"))
        # The owned identity, not new chain metadata, controls supervision.
        assert c.quote_plan((), ())["instruments"] == (buy.instrument,)
        managed = asyncio.run(
            c.cycle(DegenFrame(quotes=(held_quote,), underlyings=(held_underlying,)))
        )
        assert managed["status"] == "HELD", managed
        assert ledger(c.engine).position is not None
        assert venue.submit_count == 2
        with c.engine.journal.read() as db:
            orders = list(db.execute("SELECT intent_json FROM execution_orders"))
            assert len(orders) == 2
            assert json.loads(orders[1][0])["side"] == "SELL"


@pytest.mark.parametrize(
    "damage", ["missing_quote", "foreign_quote", "wide_spread", "stale_quote", "wrong_underlying"]
)
def test_bad_execution_evidence_is_durable_hold_without_submission(tmp_path, damage):
    f = frame()
    if damage == "missing_quote":
        f = f.model_copy(update={"quotes": ()})
    if damage == "foreign_quote":
        f = f.model_copy(update={"quotes": (quote_at(inputs("PUT"), AT),)})
    if damage == "wide_spread":
        f = f.model_copy(update={"quotes": (f.quotes[0].model_copy(update={"bid": D(".1")}),)})
    if damage == "stale_quote":
        f = f.model_copy(update={"quotes": (quote_at(inputs(), AT - timedelta(seconds=11)),)})
    if damage == "wrong_underlying":
        f = f.model_copy(
            update={"underlyings": (f.underlyings[0].model_copy(update={"symbol": "QQQ"}),)}
        )
    with owned_strategy(tmp_path) as (c, venue, _, _, _, _):
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "HOLD" and venue.submit_count == 0
        assert asyncio.run(c.cycle(frame())) == result
        assert c.report()["cycles"][0]["status"] == "COMPLETE"
        assert venue.submit_count == 0


def test_read_only_report_and_frozen_strategy_reject_retuning(tmp_path, monkeypatch):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):

        def forbidden(*args, **kwargs):
            raise AssertionError("read view performed execution")

        monkeypatch.setattr(c.engine, "reconcile_fixture", forbidden)
        monkeypatch.setattr(c.engine, "dispatch", forbidden)
        assert c.report()["cycles"] == []
        c.policy = c.policy.model_copy(update={"minimum_volume_ratio": D(2)})
        with pytest.raises(ExecutionBlocked, match="FROZEN_DEGEN_STRATEGY_CHANGED"):
            c.report()


def test_interrupted_slot_survives_restart_without_replay_and_keeps_selection(tmp_path):
    with owned_strategy(tmp_path) as (c, venue, _, _, limits, policy):
        key = "degen:" + str(int(AT.timestamp()) // 300)
        with c.engine.journal.write() as db:
            db.execute(
                "INSERT INTO execution_option_opportunities VALUES(?,?,?,?,'STARTED',?)",
                (
                    key,
                    "hash",
                    AT.isoformat(),
                    "{}",
                    json.dumps({"status": "SELECTED", "candidate_id": "retained-proof"}),
                ),
            )
        assert asyncio.run(c.cycle(frame()))["status"] == "IN_PROGRESS"
    with OptionExecution.open(tmp_path / "options.db", limits, policy, venue, now=AT) as engine:
        setup, selection = policies()
        c = DegenCoordinator(engine, setup, selection, clock=lambda: AT)
        result = asyncio.run(c.cycle(frame()))
        assert result["status"] == "INTERRUPTED" and result["candidate_id"] == "retained-proof"
        assert venue.submit_count == 0
        assert c.report()["cycles"][0]["status"] == "INTERRUPTED"


def test_concurrent_requests_claim_only_one_native_submission(tmp_path):
    with owned_strategy(tmp_path) as (c, venue, _, _, _, _):

        async def both():
            return await asyncio.gather(c.cycle(frame()), c.cycle(frame()))

        results = asyncio.run(both())
        assert sorted(r["status"] for r in results) == ["IN_PROGRESS", "OPEN"]
        assert venue.submit_count == 1


def test_cancellation_retains_selected_evidence_and_fixed_intent(tmp_path, monkeypatch):
    with owned_strategy(tmp_path) as (c, venue, _, _, _, _):

        async def canceled(*args, **kwargs):
            raise asyncio.CancelledError

        monkeypatch.setattr(c.engine, "dispatch", canceled)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(c.cycle(frame()))
        report = c.report()["cycles"][0]["result"]
        assert report["reason"] == "DEGEN_CYCLE_INTERRUPTED"
        assert report["candidates"] and report["candidate_id"]
        with c.engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 1
            assert c.engine._control(db)["halted"]
        assert asyncio.run(c.cycle(frame())) == report
        assert venue.submit_count == 0


def test_calendar_closed_and_actual_half_day_cannot_confirm_setup(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        assert "MARKET_CLOSED" in scan_degen(history(), c.policy, None, now=AT).issues
        at = AT.replace(month=11, day=27, hour=18)
        w = c.engine.calendar.current_window(at - timedelta(minutes=1))
        assert w.closes_at == at
        assert "MARKET_CLOSED" in scan_degen(history(), c.policy, w, now=at).issues


def test_fast_supervision_exits_inside_already_claimed_entry_slot(tmp_path):
    with owned_strategy(tmp_path) as (c, venue, data, times, _, _):
        f = frame()
        entered = asyncio.run(c.cycle(f))
        buy = intent_for(c.engine, entered["client_id"])
        venue.fill(buy, buy.quantity, f.quotes[0], AT, fill_id="fast-fill")
        times[0] += timedelta(seconds=1)
        at = times[0]
        assert asyncio.run(c.cycle(DegenFrame())) == entered
        # Entry deduplication must never delay a stop to the next five-minute slot.
        asyncio.run(
            c.supervise(
                (quote_at(data, at),), (underlying_at(data, at, bid=D(599), ask=D("599.01")),)
            )
        )
        assert venue.submit_count == 2
        with c.engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 2
