"""Real shared deterministic selection and versioned runtime delivery, fully offline."""

import asyncio
from datetime import timedelta
from pathlib import Path

from test_degen_options import AT, policies
from test_mixed_accounting import changed
from test_mixed_selection import stock_frame, stock_policy
from test_option_runtime import enable, policy, step
from test_portfolio_controls import get_intent, owned

from app.mixed.sources import StockCycleInput
from app.options.coordinator import DegenCoordinator, DegenFrame
from app.options.runtime import OptionRuntime
from app.options.runtime_models import PortfolioRuntimePacket


def two_symbols():
    f = stock_frame()
    first = f.quotes[0].instrument
    second = changed(
        first,
        instrument_id=first.instrument_id + "-qqq",
        contract=changed(first.contract, underlying="QQQ", root="QQQ"),
    )
    stock = changed(f.stocks[0].quote.instrument, symbol="QQQ", instrument_id="stock-qqq")
    metadata = changed(f.inventories[0].contracts[0], instrument=second)
    return changed(
        f,
        portfolio_version="portfolio-frame-v2",
        histories=(*f.histories, changed(f.histories[0], symbol="QQQ")),
        inventories=(
            *f.inventories,
            changed(f.inventories[0], symbol="QQQ", contracts=(metadata,)),
        ),
        quotes=(*f.quotes, changed(f.quotes[0], instrument=second)),
        underlyings=(*f.underlyings, changed(f.underlyings[0], symbol="QQQ")),
        stocks=(*f.stocks, StockCycleInput(quote=changed(f.stocks[0].quote, instrument=stock))),
    )


def coordinator(e, times, frame):
    setup, selection = policies()
    setup = changed(setup, symbols=("SPY", "QQQ"))
    sp = changed(stock_policy(), instruments=tuple(x.quote.instrument for x in frame.stocks))
    return DegenCoordinator(
        e, setup, selection, stock_policy=sp, create=True, clock=lambda: times[0]
    )


def test_sequential_selection_reserves_both_slots_and_retry_never_submits_again(tmp_path):
    with owned(tmp_path, at=AT) as (e, v):
        f = two_symbols()
        c = coordinator(e, [AT], f)
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "COMPLETE", out
        assert [r["status"] for r in out["entries"]] == ["OPEN", "OPEN"], out
        assert {get_intent(e, r["client_id"]).instrument.symbol for r in out["entries"]} == {
            "SPY",
            "QQQ",
        }
        assert any(
            "DUPLICATE_EXPOSURE" in str(reasons)
            for reasons in out["entries"][1]["stock_rejections"].values()
        )
        assert v.submit_count == 2
        again = asyncio.run(c.cycle(f))
        assert again["reason"] == "PLAY_CAPACITY"
        assert v.submit_count == 2
        plan = c.quote_plan(f.histories, f.inventories)
        assert len(plan["held_instruments"]) == 2


def test_runtime_fills_both_then_keeps_held_only_delivery_and_source_clocks(tmp_path):
    with owned(tmp_path, at=AT) as (e, v):
        f = two_symbols()
        times = [AT]
        c = coordinator(e, times, f)
        r = OptionRuntime(
            c,
            policy(
                tmp_path,
                mixed_inputs="mixed-runtime-inputs-v1",
                simulated_fills="mixed-quote-fills-v1",
            ),
            create=True,
        )
        enable(r)

        def deliver(frame, kind, sequence):
            packet = PortfolioRuntimePacket(
                population_id=e.limits.population_id,
                sequence=sequence,
                recorded_at=times[0],
                frame=frame,
                kind=kind,
            )
            path = Path(r.policy.feed_file)
            path.write_text(packet.model_dump_json())
            path.chmod(0o600)
            asyncio.run(step(r))

        deliver(f, "CYCLE", 1)
        assert v.submit_count == 2
        times[0] += timedelta(seconds=1)
        held = DegenFrame(
            portfolio_version="portfolio-frame-v2",
            held_stocks=tuple(
                StockCycleInput(quote=changed(x.quote, source_at=times[0], received_at=times[0]))
                for x in f.stocks
            ),
        )
        deliver(held, "MARKET", 3)
        assert len(v.snapshot(times[0]).positions) == 2
        before = v.snapshot(times[0])
        deliver(held, "MARKET", 3)
        after = v.snapshot(times[0])
        assert before.cash == after.cash and before.positions == after.positions
        assert [o.fills for o in before.stock_orders] == [o.fills for o in after.stock_orders]
        from app.mixed.runtime import stored_inputs

        with e.journal.read() as db:
            assert stored_inputs(db, times[0])["latest_sequence"] == 3
            assert (
                db.execute(
                    "SELECT count(*) FROM execution_events WHERE kind='PORTFOLIO_FEED_GAP'"
                ).fetchone()[0]
                == 1
            )
