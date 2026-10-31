"""Native whole-trade floor arithmetic keeps fills, fees, uncertainty and authority distinct."""

import asyncio
import json
import shutil
from decimal import Decimal, localcontext

import pytest
from test_option_admission import NOW
from test_option_execution import intent_for, ledger, owned, quote_at
from test_option_partial_close import close, fill
from test_option_position_coordination import (
    enter_position,
    management_frame,
    model,
    owned_manager,
)
from test_option_target_exits import POLICY, enter_targets, schedule, tick

from app.options.observer import OptionObserver
from app.options.trade_floor import native_trade_floor

D = Decimal


def read(engine, buy):
    with engine.journal.read() as db:
        return native_trade_floor(db, buy.client_id, engine.limits.population_id)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("stage", [0, 1, 2, 3])
def test_native_targets_and_actual_sales_keep_original_basis_and_every_fee(tmp_path, right, stage):
    with owned(tmp_path, right, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data, plan=schedule(right, quantities=(1, 1, 1)))
        for n in range(1, stage + 1):
            result = tick(engine, data, stage=n)
            sell = intent_for(engine, result["client_id"])
            assert sell.quantity == 1
            fill(engine, venue, sell, data["quote"])
        result = read(engine, buy)
        assert result["status"] == "READY", result
        assert result["stored_target_stage"] == stage
        assert result["remaining_quantity"] == 4 - stage
        evidence = result["evidence"]
        assert D(evidence["entry_premium"]) == D(404)
        assert D(evidence["exit_premium"]) == D(97) * stage
        assert D(evidence["execution_fees"]) == D("3.60") + D("1.65") * stage
        assert D(result["reserved_future_exit_fees"]) == D("1.65") * (4 - stage)
        for floor, fraction in zip(
            result["reference_floors"], (D(0), D(".10"), D(".25")), strict=True
        ):
            required = D(404) * (1 + fraction) + D("10.20") - D(97) * stage
            assert D(floor["required_remaining_gross_proceeds"]) == required
            price = D(floor["minimum_exit_fill_price"])
            assert price * (4 - stage) * 100 >= required
            assert (price - D(".01")) * (4 - stage) * 100 < required
        assert result["reached_target_floor"] == (
            result["reference_floors"][stage - 1] if stage else None
        )
        assert evidence["net_after_known_execution_and_model_costs"] is None
        assert not any(
            result[k]
            for k in (
                "execution_authority",
                "execution_ready",
                "live_enabled",
                "data_host_costs_included",
            )
        )
        assert venue.submit_count == stage + 1


def test_touch_without_sale_never_invents_realized_proceeds(tmp_path):
    from test_option_target_exits import at_target

    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data)
        engine.assess(data["quote"], at_target(data, 2), now=NOW)
        result = read(engine, buy)
        assert result["status"] == "READY" and result["stored_target_stage"] == 2
        assert result["evidence"]["exit_quantity"] == 0
        assert D(result["reached_target_floor"]["required_remaining_gross_proceeds"]) == D("454.60")
        assert venue.submit_count == 1


@pytest.mark.parametrize("terminal", [False, True])
def test_partial_entry_never_resizes_original_floor(tmp_path, terminal):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data, quantity=2)
        if terminal:
            venue.record_terminal(buy.client_id, "CANCELED", NOW)
            assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        result = read(engine, buy)
        assert result["status"] == "INCOMPLETE" and not result["reference_floors"]
        assert "COMPLETE_ORIGINAL_ENTRY_REQUIRED" in result["reasons"]
        assert result["remaining_quantity"] == 2
        assert result["evidence"]["entry_quantity"] == 2


def test_working_scale_withholds_floor_until_terminal_reconciliation(tmp_path):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data)
        sell = intent_for(engine, tick(engine, data)["client_id"])
        venue.fill(sell, 1, data["quote"], NOW, fill_id="partial-scale")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        result = read(engine, buy)
        assert "UNRESOLVED_POSITION_ORDER" in result["reasons"]
        assert result["reached_target_floor"] is None and not result["reference_floors"]
        assert result["evidence"]["exit_quantity"] == 1
        venue.record_terminal(sell.client_id, "CANCELED", NOW)
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        assert read(engine, buy)["status"] == "READY"
        assert venue.submit_count == 2


def test_profitable_sales_can_cover_floor_without_negative_prices(tmp_path):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data)
        q = quote_at(data, bid=D(3), ask=D("3.01"))
        sell = intent_for(engine, tick(engine, data, q=q)["client_id"])
        fill(engine, venue, sell, q)
        result = read(engine, buy)
        assert all(f["covered_by_recorded_sales"] for f in result["reference_floors"])
        assert all(D(f["minimum_exit_fill_price"]) == 0 for f in result["reference_floors"])
        assert result["evidence"]["outcome"] is None  # The runner is still owned.


def test_weighted_original_fills_and_decimal_context_are_exact(tmp_path):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data, quantity=1)
        venue.fill(buy, 3, quote_at(data, ask=D(".99")), NOW, fill_id="entry-rest")
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        expected = read(engine, buy)
        with localcontext() as context:
            context.prec = 4
            assert read(engine, buy) == expected
        assert D(expected["evidence"]["entry_premium"]) == D(401)
        assert D(expected["reference_floors"][0]["required_remaining_gross_proceeds"]) == D(
            "411.20"
        )


def test_minimum_fill_prices_round_up_across_contract_tick_tiers(tmp_path):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        contract = data["proposal"].contract.model_copy(
            update={"tick_below_three": D(".05"), "tick_at_or_above_three": D(".10")}
        )
        data["proposal"] = data["proposal"].model_copy(update={"contract": contract})
        data["quote"] = data["quote"].model_copy(
            update={
                "instrument": data["quote"].instrument.model_copy(update={"contract": contract})
            }
        )
        buy = enter_targets(engine, venue, data, plan=schedule(quantities=(1, 1, 1)))
        for stage in (1, 2, 3):
            q = quote_at(data, bid=D(".56"), ask=D(".57"))
            sell = intent_for(engine, tick(engine, data, stage=stage, q=q)["client_id"])
            fill(engine, venue, sell, q)
        result = read(engine, buy)
        assert result["status"] == "READY", result
        assert D(result["evidence"]["entry_premium"]) == D(420)
        assert [D(f["minimum_exit_fill_price"]) for f in result["reference_floors"]] == [
            D("2.70"),
            D("3.10"),
            D("3.80"),
        ]


@pytest.mark.parametrize("unknown", [False, True])
def test_native_entry_and_non_order_management_charges_raise_or_withhold_floor(
    tmp_path, monkeypatch, unknown
):
    with owned_manager(tmp_path, partial_closes="whole-contract-v1") as (c, venue, times):
        buy = enter_position(c, venue, times, monkeypatch)
        frame = management_frame()
        q, u = frame.quotes[0], frame.underlyings[0]
        assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
        c.engine.assess(q, u, now=times[0])
        prepared = c.engine.prepare("scale", close(buy, 1), q, u, now=times[0])
        sell = intent_for(c.engine, prepared["client_id"])
        assert asyncio.run(c.engine.dispatch(sell.client_id, q, u, now=times[0])) == "OPEN"
        fill(c.engine, venue, sell, q, times[0])
        before = read(c.engine, buy)
        assert before["remaining_quantity"] == buy.quantity - 1
        assert before["evidence"]["exit_quantity"] == 1
        assert before["status"] == "READY" and before["stored_target_stage"] is None
        assert before["reached_target_floor"] is None  # No inferred target enrollment.

        def change(request, result):
            return result.model_copy(update={"usage": None, "error": "TimeoutError"})

        model(monkeypatch, c, action="MAINTAIN", changes=change if unknown else None)
        asyncio.run(c.cycle(frame))
        after = read(c.engine, buy)
        assert {call["role"] for call in after["evidence"]["model_calls"]} == {
            "ENTRY",
            "MANAGEMENT",
        }
        assert venue.submit_count == 2
        if unknown:
            assert "POSITION_MODEL_COST_UNKNOWN" in after["reasons"]
            assert after["reference_floors"] == []
        else:
            assert after["status"] == "READY"
            assert D(after["evidence"]["known_model_cost"]) == D(".00030")
            for a, b in zip(after["reference_floors"], before["reference_floors"], strict=True):
                assert D(a["required_remaining_gross_proceeds"]) - D(
                    b["required_remaining_gross_proceeds"]
                ) == D(".00015")


def test_unallocated_cost_retained_and_blocks_floor(tmp_path, monkeypatch):
    with owned_manager(tmp_path) as (c, venue, times):
        buy = enter_position(c, venue, times, monkeypatch)
        with c.engine.journal.write() as db:
            db.execute(
                "INSERT INTO execution_model_calls SELECT 'unallocated',packet_hash,started_at,usage_json,NULL,decision_hash,cost FROM execution_model_calls LIMIT 1"
            )
        result = read(c.engine, buy)
        assert "ACCOUNT_MODEL_COST_LINK_UNPROVEN" in result["reasons"]
        assert result["evidence"]["unallocated_account_calls"]
        assert not result["reference_floors"]


def test_observer_reads_detached_snapshot_without_owner_or_mutation(tmp_path):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data)
        expected = read(engine, buy)
        path, population = engine.journal.path, engine.limits.population_id
    copy = tmp_path / "detached.db"
    shutil.copy2(path, copy)
    before = copy.read_bytes()
    assert OptionObserver(copy, population).trade_floor(buy.client_id) == expected
    assert copy.read_bytes() == before
    with pytest.raises(ValueError, match="population"):
        OptionObserver(copy, "foreign").trade_floor(buy.client_id)
    with pytest.raises(ValueError, match="entry"):
        OptionObserver(copy, population).trade_floor("missing")
    with pytest.raises(ValueError):
        OptionObserver(copy, population).trade_floor("bad\nidentity")


def test_changed_frozen_schedule_is_not_reinterpreted_as_a_valid_floor(tmp_path):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data)
        with engine.journal.write() as db:
            p = ledger(engine).model_dump(mode="json")
            p["position"]["target_exit_schedule"]["steps"][0]["quantity"] = 1
            db.execute("UPDATE execution_control SET ledger_json=?", (json.dumps(p),))
        with pytest.raises(ValueError, match="frozen target schedule"):
            read(engine, buy)


def test_closed_entry_has_no_runner_floor(tmp_path):
    with owned(tmp_path, **POLICY) as (engine, venue, data):
        buy = enter_targets(engine, venue, data, plan=schedule(quantities=(4,)))
        sell = intent_for(engine, tick(engine, data)["client_id"])
        fill(engine, venue, sell, data["quote"])
        result = read(engine, buy)
        assert "EXACT_ENTRY_NOT_CURRENTLY_OWNED" in result["reasons"]
        assert not result["reference_floors"] and result["remaining_quantity"] == 0
        assert result["evidence"]["status"] == "COMPLETE"


def test_independent_owner_sales_do_not_change_other_floor(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    with (
        owned(tmp_path / "a", **POLICY) as (a, av, ad),
        owned(tmp_path / "b", **POLICY) as (b, bv, bd),
    ):
        ab, bb = enter_targets(a, av, ad), enter_targets(b, bv, bd)
        before = read(b, bb)
        sell = intent_for(a, tick(a, ad)["client_id"])
        fill(a, av, sell, ad["quote"])
        assert read(b, bb) == before
        assert read(a, ab)["remaining_quantity"] == 2
        assert read(b, bb)["remaining_quantity"] == 4
