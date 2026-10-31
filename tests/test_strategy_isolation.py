"""Absent Swing is explicit and cannot create partial or synthetic Swing candidates."""
import asyncio

import pytest
from test_option_scope_arbitration import shared
from app.options.coordinator import DegenFrame


def test_unavailable_swing_still_evaluates_other_native_families(tmp_path):
    with shared(tmp_path, priority=("SWING", "DEGEN", "SCOPE"), portfolio=True) as (c, v, _, frame):
        frame = DegenFrame.model_validate(frame.model_dump() | {
            "swing": (), "swing_batches": (), "swing_unavailable": True,
        })
        result = asyncio.run(c._cycle_once(frame, portfolio_slot=0))
        assert result["status"] == "OPEN", result
        assert result["scope_arbitration"]["selected"]["family"] == "DEGEN"
        assert all(x["family"] != "SWING" for x in result["scope_arbitration"]["choices"])
        assert v.submit_count == 1


def test_unavailable_marker_cannot_hide_supplied_swing_or_legacy_frame(tmp_path):
    with shared(tmp_path, priority=("SWING", "DEGEN", "SCOPE"), portfolio=True) as (_, _, _, frame):
        with pytest.raises(ValueError, match="empty portfolio Swing"):
            DegenFrame.model_validate(frame.model_dump() | {"swing_unavailable": True})
        with pytest.raises(ValueError, match="empty portfolio Swing"):
            DegenFrame.model_validate({"swing_unavailable": True})


def test_stock_degen_survives_absent_swing_without_inventing_clearance(tmp_path):
    from test_degen_options import frame, policies, AT
    from test_mixed_selection import source_fixture, stock_policy
    from test_mixed_native_owner import settings
    from app.mixed.sources import StockCycleInput, candidates
    from app.robinhood.schedule import XNYSCalendar

    _, swing, supplied, _ = source_fixture()
    item = StockCycleInput(quote=supplied.quote)
    structure, _ = policies()
    _, execution = settings()
    found, rejected, terminals = candidates(
        item, frame().histories[0], structure, stock_policy(swing=swing),
        execution, XNYSCalendar(), now=AT, swing_unavailable=True,
    )
    assert found and all(c.proposal.family == "DEGEN" for c in found)
    assert rejected["SWING"] == ("SWING_INPUT_UNAVAILABLE",)
    assert not terminals
    with pytest.raises(ValueError, match="STOCK_COMPLETE_SWING_SOURCE_REQUIRED"):
        candidates(item, frame().histories[0], structure, stock_policy(swing=swing),
                   execution, XNYSCalendar(), now=AT)


def test_stock_entry_revalidates_without_unavailable_swing(tmp_path):
    from test_degen_options import AT, policies
    from test_mixed_selection import source_fixture, stock_frame, stock_policy
    from test_portfolio_controls import owned, get_intent
    from app.options.coordinator import DegenCoordinator

    _, swing, _, _ = source_fixture()
    with owned(tmp_path, at=AT) as (engine, venue):
        setup, selection = policies()
        c = DegenCoordinator(engine, setup, selection,
                             stock_policy=stock_policy(swing=swing),
                             create=True, clock=lambda: AT)
        frame = DegenFrame.model_validate(stock_frame().model_dump() | {
            "portfolio_version": "portfolio-frame-v2", "swing_unavailable": True,
        })
        out = asyncio.run(c.cycle(frame))
        first = out["entries"][0]
        assert first["status"] == "OPEN", first
        assert get_intent(engine, first["client_id"]).family == "DEGEN"
        assert venue.submit_count == 1
