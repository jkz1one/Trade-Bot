"""Synthetic elapsed-time failures; no provider reads or host evidence."""

import asyncio
from datetime import timedelta

import pytest
from test_degen_options import AT
from test_mixed_accounting import changed
from test_portfolio_controls import owned
from test_portfolio_selection import coordinator, two_symbols
from test_robinhood_read_mapping import schemas as schemas  # noqa: F401


def option_frame():
    frame = two_symbols()
    return changed(frame, stocks=tuple(
        changed(item, quote=changed(item.quote, bid_size=None, ask_size=None))
        for item in frame.stocks
    ))


def test_one_protection_read_reaches_selection_before_original_inventory_expires(tmp_path, monkeypatch):
    with owned(tmp_path, at=AT) as (engine, venue):
        times = [AT]
        frame = option_frame()
        c = coordinator(engine, times, two_symbols())
        original = engine.reconcile_fixture
        reads = []

        async def delayed(*, now):
            reads.append(now)
            times[0] += timedelta(seconds=4)
            return await original(now=times[0])

        monkeypatch.setattr(engine, 'reconcile_fixture', delayed)
        outcome = asyncio.run(c.cycle(frame))
        first = outcome['entries'][0]
        assert 'INVENTORY_BINDING_COVERAGE_OR_FRESHNESS' not in str(first), first
        assert first['status'] == 'OPEN', first
        assert first['mixed_selection']['selected']['asset'] == 'OPTION'
        assert len(reads) == 2  # one per sequential play, including the second-slot review
        assert venue.submit_count >= 1


def test_expired_original_inventory_still_cannot_enter(tmp_path, monkeypatch):
    with owned(tmp_path, at=AT) as (engine, venue):
        times = [AT]
        frame = option_frame()
        c = coordinator(engine, times, two_symbols())
        original = engine.reconcile_fixture

        async def delayed(*, now):
            times[0] += timedelta(seconds=26.297)
            return await original(now=times[0])

        monkeypatch.setattr(engine, 'reconcile_fixture', delayed)
        outcome = asyncio.run(c.cycle(frame))
        assert 'INVENTORY_BINDING_COVERAGE_OR_FRESHNESS' in str(outcome)
        assert venue.submit_count == 0


@pytest.mark.parametrize('with_history', [False, True])
def test_collector_puts_completed_history_before_executable_books(with_history):
    from test_portfolio_feed import policy
    from test_robinhood_read_mapping import instrument
    from app.mixed.continuous_feed import planned
    from app.robinhood.schedule import XNYSCalendar

    p = changed(policy(), candidates=(instrument(),))
    plan, _ = planned(p, (), AT, XNYSCalendar().current_window(AT), cycle=with_history)
    tools = [call.tool for call in plan.calls]
    if with_history:
        assert tools == ['get_equity_historicals', 'get_equity_quotes', 'get_option_quotes']
    else:
        assert tools == ['get_equity_quotes', 'get_option_quotes']


@pytest.mark.parametrize('failed_history', [False, True])
def test_slow_original_history_does_not_age_later_books_or_suppress_protection(
    tmp_path, schemas, monkeypatch, failed_history
):
    from contextlib import asynccontextmanager
    from copy import deepcopy
    from test_connected_cycle_handoff import capture_at
    from test_option_read_capture import request
    from test_portfolio_feed import policy
    from test_robinhood_read_mapping import AT as wire_at, instrument
    from app.mixed.continuous_feed import normalize, planned
    from app.options import read_worker
    from app.robinhood.schedule import XNYSCalendar

    times = [wire_at + timedelta(minutes=30)]
    original_instrument = instrument()
    shift = times[0].date() - original_instrument.contract.expiration
    contract = changed(original_instrument.contract, **{
        key: getattr(original_instrument.contract, key) + shift
        for key in ('expiration', 'last_trading_at', 'expires_at', 'settles_at')
    })
    p = changed(policy(), candidates=(changed(original_instrument, contract=contract),))
    plan, catalog = planned(p, (), times[0], XNYSCalendar().current_window(times[0]), cycle=True)
    original = asyncio.run(capture_at(times[0])(p.capture, schemas=schemas, plan=plan))
    raw = {row['tool']: row['raw'] for row in original.observations}
    calls = []

    class Client:
        async def list_tools(self):
            return list(schemas.tools.values())

        async def call_tool(self, name, arguments):
            calls.append(name)
            if name == 'get_equity_historicals':
                times[0] += timedelta(seconds=20)
                if failed_history:
                    raise ValueError('synthetic private history failure')
            else:
                times[0] += timedelta(milliseconds=100)
            response = deepcopy(raw[name])
            for item in response['structuredContent']['data']['results']:
                if name == 'get_option_quotes':
                    item['quote']['updated_at'] = times[0].isoformat()
                elif name == 'get_equity_quotes':
                    for key in ('venue_bid_time', 'venue_ask_time', 'venue_last_trade_time'):
                        item['quote'][key] = times[0].isoformat()
            return response

    class Connection:
        @asynccontextmanager
        async def client(self):
            yield Client()

    req = request(tmp_path, schemas, plan).model_copy(update={'started_at': times[0]})
    monkeypatch.setattr(read_worker, 'connection', lambda _: Connection())
    monkeypatch.setattr(read_worker, 'utc_now', lambda: times[0])
    result = asyncio.run(read_worker.collect(req))
    assert calls == [call.tool for call in plan.calls]
    assert result.status == ('FAILED' if failed_history else 'COMPLETE')
    packet = normalize(p, schemas, result, catalog, (), sequence=1, now=times[0])
    assert packet.kind == ('MARKET' if failed_history else 'CYCLE')
    assert packet.frame.quotes[0].source_at == times[0]
    if not failed_history:
        assert packet.frame.inventories[0].source_at == times[0]
    assert all((times[0] - q.source_at).total_seconds() <= .1 for q in packet.frame.underlyings)
    if failed_history:
        assert 'INTRADAY_HISTORY_UNAVAILABLE' in packet.coverage_issues
        assert 'synthetic private' not in result.model_dump_json()


def test_changed_protection_epoch_cannot_be_reused(tmp_path):
    with owned(tmp_path, at=AT) as (engine, venue):
        frame = option_frame()
        c = coordinator(engine, [AT], two_symbols())
        asyncio.run(c.supervise(frame.quotes, frame.underlyings, stocks=frame.stocks))
        with engine.journal.read() as db:
            epoch = engine._epoch(db)
        with engine.journal.write() as db:
            engine._halt(db, 'OPERATOR_HALT', AT)
        out = asyncio.run(c._cycle_once(frame, portfolio_slot=0, _protected_epoch=epoch))
        assert out['reason'] == 'PORTFOLIO_PROTECTION_REQUIRED'
        assert venue.submit_count == 0


@pytest.mark.parametrize('change', ['none', 'frame', 'epoch', 'stale_account'])
def test_runtime_handoff_requires_exact_frame_state_and_original_account_age(tmp_path, monkeypatch, change):
    from app.options.engine import fingerprint

    with owned(tmp_path, at=AT) as (engine, venue):
        times = [AT]
        frame = changed(option_frame(), histories=())
        c = coordinator(engine, times, two_symbols())
        asyncio.run(c.supervise(frame.quotes, frame.underlyings, stocks=frame.stocks))
        with engine.journal.read() as db:
            handoff = (engine._epoch(db), fingerprint(frame))
        if change == 'frame':
            frame = changed(frame, underlyings=())
        elif change == 'epoch':
            with engine.journal.write() as db:
                engine._halt(db, 'OPERATOR_HALT', AT)
        elif change == 'stale_account':
            times[0] += timedelta(seconds=engine.limits.account_max_age_seconds)
        original = engine.reconcile_fixture
        reads = []

        async def observed(*, now):
            reads.append(now)
            return await original(now=now)

        monkeypatch.setattr(engine, 'reconcile_fixture', observed)
        asyncio.run(c.cycle(frame, _protected_epoch=handoff))
        assert len(reads) == (0 if change == 'none' else 1)
        assert venue.submit_count == 0


def test_runtime_reuses_protection_then_fills_exits_and_restarts_without_replay(tmp_path, monkeypatch):
    from pathlib import Path
    from test_option_runtime import enable, policy, step
    from app.options.coordinator import DegenCoordinator, DegenFrame
    from app.options.engine import OptionExecution
    from app.options.runtime import OptionRuntime
    from app.options.runtime_models import PortfolioRuntimePacket

    times = [AT]
    sequence = [0]

    def deliver(runtime, frame, kind):
        sequence[0] += 1
        packet = PortfolioRuntimePacket(population_id=runtime.c.engine.limits.population_id,
            sequence=sequence[0], recorded_at=times[0], frame=frame, kind=kind)
        path = Path(runtime.policy.feed_file)
        path.write_text(packet.model_dump_json())
        path.chmod(0o600)
        asyncio.run(step(runtime))

    frame = option_frame()
    with owned(tmp_path, at=AT) as (engine, venue):
        c = coordinator(engine, times, two_symbols())
        r = OptionRuntime(c, policy(tmp_path, mixed_inputs='mixed-runtime-inputs-v1',
                                   simulated_fills='mixed-quote-fills-v1'), create=True)
        enable(r)
        original = engine.reconcile_fixture
        reads = []

        async def delayed(*, now):
            reads.append(now)
            times[0] += timedelta(seconds=4)
            return await original(now=times[0])

        monkeypatch.setattr(engine, 'reconcile_fixture', delayed)
        deliver(r, frame, 'CYCLE')
        assert len(reads) == 2  # first runtime protection + changed second-play state
        snap = venue.snapshot(times[0])
        assert len(snap.orders) == 2 and not snap.stock_orders
        assert venue.submit_count == 2
        with engine.journal.read() as db:
            import json
            saved = [json.loads(row[0]) for row in db.execute(
                'SELECT result_json FROM execution_option_opportunities ORDER BY cycle_key')]
        assert all(value['status'] == 'OPEN' for value in saved)
        assert saved[0]['scans'][0]['evaluated_at'] == (AT + timedelta(seconds=4)).isoformat().replace('+00:00', 'Z')
        monkeypatch.setattr(engine, 'reconcile_fixture', original)

        def market(stop=False):
            return DegenFrame(portfolio_version='portfolio-frame-v2',
                quotes=tuple(changed(q, source_at=times[0], received_at=times[0]) for q in frame.quotes),
                underlyings=tuple(changed(q, source_at=times[0], received_at=times[0],
                    **({'bid': '590', 'ask': '590.01'} if stop else {})) for q in frame.underlyings))

        times[0] += timedelta(seconds=1)
        deliver(r, market(), 'MARKET')
        assert len(venue.snapshot(times[0]).positions) == 2
        times[0] += timedelta(seconds=1)
        deliver(r, market(stop=True), 'MARKET')
        assert venue.submit_count == 4  # autonomous protective exits for both plays
        times[0] += timedelta(seconds=1)
        deliver(r, market(stop=True), 'MARKET')
        before = venue.snapshot(times[0])
        assert not before.positions and all(order.status == 'FILLED' for order in before.orders)
        settings = engine.limits, engine.policy, c.policy, c.selection, c.stock_policy, r.policy

    limits, execution, setup, selection, stocks, runtime_policy = settings
    times[0] += timedelta(seconds=1)
    with OptionExecution.open(tmp_path / 'owner.db', limits, execution, venue, now=times[0]) as engine:
        c = DegenCoordinator(engine, setup, selection, stock_policy=stocks, clock=lambda: times[0])
        r = OptionRuntime(c, runtime_policy)
        enable(r)
        deliver(r, market(stop=True), 'MARKET')
        after = venue.snapshot(times[0])
        assert after.cash == before.cash and after.orders == before.orders and not after.positions
        assert venue.submit_count == 4
