"""Versioned credential-free replay with two actual native held plays."""

import asyncio
from datetime import timedelta

import pytest
from test_degen_options import AT, policies
from test_mixed_accounting import changed
from test_mixed_selection import stock_policy
from test_option_runtime import policy
from test_portfolio_controls import owned
from test_portfolio_selection import two_symbols

from app.mixed.observer import MixedObserver
from app.mixed.portfolio_replay import PortfolioReplay, replay
from app.mixed.sources import StockCycleInput
from app.options.coordinator import DegenFrame
from app.options.runtime_models import PortfolioRuntimePacket, RuntimeSettings


def request(tmp_path):
    f = two_symbols()
    setup, selection = policies()
    with owned(tmp_path / "source", at=AT) as (e, _):
        settings = RuntimeSettings(
            limits=e.limits,
            execution=e.policy,
            setup=changed(setup, symbols=("SPY", "QQQ")),
            selection=selection,
            stock_policy=changed(
                stock_policy(), instruments=tuple(x.quote.instrument for x in f.stocks)
            ),
            runtime=policy(
                tmp_path,
                mixed_inputs="mixed-runtime-inputs-v1",
                simulated_fills="mixed-quote-fills-v1",
            ),
        )

    def packet(frame, sequence, at, kind):
        return PortfolioRuntimePacket(
            population_id=settings.limits.population_id,
            sequence=sequence,
            recorded_at=at,
            kind=kind,
            frame=frame,
        )

    at = AT + timedelta(seconds=1)
    held = DegenFrame(
        portfolio_version="portfolio-frame-v2",
        held_stocks=tuple(
            StockCycleInput(quote=changed(x.quote, source_at=at, received_at=at)) for x in f.stocks
        ),
    )
    return PortfolioReplay(
        settings=settings, packets=(packet(f, 1, AT, "CYCLE"), packet(held, 2, at, "MARKET"))
    )


def test_two_play_replay_freezes_actual_receipts_without_changing_originals(tmp_path):
    value = request(tmp_path)
    original = value.model_dump_json()
    directory = tmp_path / "replay"
    result = asyncio.run(replay(directory, value))
    assert result["status"] == "OK", result
    assert result["held_plays"] == 2 and result["fills"] == 2, result
    assert not result["network_calls"] and not result["market_acceptance"]
    assert value.model_dump_json() == original
    view = MixedObserver(
        directory / "options.db",
        value.settings.limits.population_id,
        clock=lambda: value.packets[-1].recorded_at,
    ).report()
    assert len({p["play_id"] for p in view["positions"]}) == 2
    with pytest.raises(ValueError, match="new absolute"):
        asyncio.run(replay(directory, value))
