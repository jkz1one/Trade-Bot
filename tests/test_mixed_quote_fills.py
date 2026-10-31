"""Installed native runtime consumes later executable quotes without manual fills."""

import asyncio
from datetime import timedelta
from decimal import Decimal as D

import pytest
from test_mixed_native_owner import changed
from test_mixed_runtime import send
from test_mixed_selection import owner, quote, stock_frame
from test_option_runtime import enable, policy, step

from app.mixed.quote_fills import apply_quote_fills
from app.mixed.sources import StockCycleInput
from app.options.coordinator import DegenFrame
from app.options.runtime import OptionRuntime
from app.options.runtime_models import RuntimePolicy


def start(c, path, enabled=True):
    r = OptionRuntime(
        c,
        policy(
            path,
            mixed_inputs="mixed-runtime-inputs-v1",
            **({"simulated_fills": "mixed-quote-fills-v1"} if enabled else {}),
        ),
        create=True,
    )
    enable(r)
    send(r, stock_frame(), kind="CYCLE")
    asyncio.run(step(r))
    return r


def market(r, times, *, seconds=1, **changes):
    times[0] += timedelta(seconds=seconds)
    send(r, DegenFrame(stocks=(StockCycleInput(quote=quote(times[0], **changes)),)))
    asyncio.run(step(r))


def test_stock_entry_and_independent_exit_fill_from_later_quotes(tmp_path):
    with owner(tmp_path) as (c, v, times):
        r = start(c, tmp_path)
        assert v.snapshot(times[0]).stock_position is None
        assert v.submit_count == 1
        market(r, times)
        assert v.snapshot(times[0]).stock_position is not None
        # A later stop breach creates a native SELL, not an instantaneous invented exit.
        market(r, times, bid=D(599), ask=D("599.01"))
        assert v.submit_count == 2
        assert v.snapshot(times[0]).stock_position is not None
        market(r, times, bid=D(599), ask=D("599.01"))
        snap = v.snapshot(times[0])
        assert snap.stock_position is None
        assert len([f for o in snap.stock_orders for f in o.fills]) == 2
        assert snap.cash != snap.settled_cash  # No invented immediate settlement.
        asyncio.run(step(r))
        assert v.submit_count == 2


@pytest.mark.parametrize("damage", ["same_clock", "delayed", "unknown_size", "over_limit", "stale"])
def test_unexecutable_quote_never_fills(tmp_path, damage):
    with owner(tmp_path) as (c, v, times):
        r = start(c, tmp_path)
        before = times[0]
        changes = {
            "same_clock": {"source_at": before},
            "delayed": {"entitlement": "DELAYED"},
            "unknown_size": {"ask_size": None},
            "over_limit": {"ask": D(650)},
            "stale": {"source_at": before - timedelta(seconds=60)},
        }[damage]
        market(r, times, **changes)
        assert not any(o.fills for o in v.snapshot(times[0]).stock_orders)


def test_repeated_packet_and_receipt_alias_cannot_replenish_source_size(tmp_path):
    with owner(tmp_path) as (c, v, times):
        r = start(c, tmp_path)
        market(r, times, ask_size=D(".1"))
        source = times[0]
        first = v.snapshot(source).stock_orders[0]
        assert first.filled_quantity == D(".1")
        asyncio.run(step(r))
        market(r, times, ask_size=D(".1"), source_at=source)
        assert v.snapshot(times[0]).stock_orders[0].filled_quantity == D(".1")
        market(r, times, ask_size=D(".1"))
        assert v.snapshot(times[0]).stock_orders[0].filled_quantity == D(".2")


@pytest.mark.parametrize("asset", ["STOCK", "OPTION"])
def test_default_runtime_does_not_gain_fill_authority(tmp_path, asset):
    with owner(tmp_path, asset=asset) as (c, v, times):
        r = start(c, tmp_path, enabled=False)
        market(r, times)
        snap = v.snapshot(times[0])
        assert not any(o.fills for o in (*snap.orders, *snap.stock_orders))
        assert "simulated_fills" not in r.policy.model_dump()


def test_unknown_attempt_is_not_replayed_or_filled(tmp_path):
    with owner(tmp_path) as (c, v, times):
        v.fault = "LOST_ACK"
        r = start(c, tmp_path)
        assert v.submit_count == 1
        with c.engine.journal.read() as db:
            assert (
                db.execute("SELECT status FROM execution_stock_orders").fetchone()[0] == "UNKNOWN"
            )
        market(r, times)
        assert not any(o.fills for o in v.snapshot(times[0]).stock_orders)
        with c.engine.journal.read() as db:
            # Existing native reconciliation may resolve the lost acknowledgement;
            # the fill step did not fabricate that acknowledgement or clear its halt.
            assert db.execute("SELECT status FROM execution_stock_orders").fetchone()[0] == "OPEN"
            assert db.execute("SELECT halted FROM execution_control").fetchone()[0]
        assert v.submit_count == 1


def test_option_fills_retain_underlying_and_alias_size_limit(tmp_path):
    with owner(tmp_path, asset="OPTION") as (c, v, times):
        r = start(c, tmp_path)
        base = stock_frame()
        times[0] += timedelta(seconds=1)
        source = times[0]
        q = changed(base.quotes[0], source_at=source, received_at=source, ask_size=1)
        u = changed(base.underlyings[0], source_at=source, received_at=source)
        send(
            r,
            DegenFrame(
                quotes=(q,), underlyings=(u,), stocks=(StockCycleInput(quote=quote(source)),)
            ),
        )
        asyncio.run(step(r))
        first = v.snapshot(source).orders[0]
        assert first.filled_quantity == 1 and first.fills[0].underlying == u
        times[0] += timedelta(seconds=1)
        send(r, DegenFrame(quotes=(changed(q, received_at=times[0]),), underlyings=(u,)))
        asyncio.run(step(r))
        assert v.snapshot(times[0]).orders[0].filled_quantity == 1


def test_conflicting_quote_delivery_halts_without_filling(tmp_path):
    with owner(tmp_path, asset="OPTION") as (c, v, times):
        r = start(c, tmp_path)
        times[0] += timedelta(seconds=1)
        q = changed(stock_frame().quotes[0], source_at=times[0], received_at=times[0])
        send(r, DegenFrame(quotes=(q, changed(q, ask=q.ask + D(".01")))))
        asyncio.run(step(r))
        assert not any(o.fills for o in v.snapshot(times[0]).orders)
        with c.engine.journal.read() as db:
            assert db.execute("SELECT halted FROM execution_control").fetchone()[0]


def test_expired_acknowledged_order_expires_without_synthetic_fill(tmp_path):
    with owner(tmp_path) as (c, v, times):
        r = start(c, tmp_path)
        times[0] = v.snapshot(times[0]).stock_orders[0].intent.order_expires_at
        send(r, DegenFrame())
        asyncio.run(step(r))
        order = v.snapshot(times[0]).stock_orders[0]
        assert order.status == "EXPIRED" and not order.fills


def test_policy_requires_mixed_and_is_frozen(tmp_path):
    with pytest.raises(ValueError, match="mixed runtime"):
        policy(tmp_path, simulated_fills="mixed-quote-fills-v1")
    with owner(tmp_path) as (c, _v, _times):
        r = start(c, tmp_path)
        assert RuntimePolicy.model_validate(r.policy.model_dump()) == r.policy
        # Existing engine binding refuses a second owner; no implicit adoption.
        with pytest.raises(ValueError, match="One runtime"):
            OptionRuntime(c, policy(tmp_path, mixed_inputs="mixed-runtime-inputs-v1"))


def test_unaccepted_packet_cannot_mutate_venue(tmp_path):
    with owner(tmp_path) as (c, v, times):
        r = start(c, tmp_path)
        times[0] += timedelta(seconds=1)
        packet = send(r, DegenFrame(stocks=(StockCycleInput(quote=quote(times[0])),)))
        with pytest.raises(ValueError, match="Validated native delivery"):
            apply_quote_fills(r, packet, times[0])
        assert not any(o.fills for o in v.snapshot(times[0]).stock_orders)
