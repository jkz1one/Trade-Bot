"""Production PAPER settings through raw mapping, selection and native fills.

Prices/bars and model responses are synthetic. No provider or model service is
called. Only filesystem paths change in the enrolled production configuration.
"""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from test_combined_session_feed import combined
from test_contract_catalog import captures as captures
from test_degen_options import history
from test_option_runtime import enable, step
from test_robinhood_read_mapping import schemas as schemas, envelope, equity, option

from app.execution.economics import UsageEvidence
from app.mixed.continuous_feed import ContinuousFeed
from app.options.engine import fingerprint
from app.options.entry_judgment import result_for
from app.options.entry_reasoning import plan_class
from app.options.read_capture import CaptureResult, policy_digest
from app.options.runtime import read_packet
from app.options.runtime_cli import initialize, existing_runtime
from app.robinhood.schedule import XNYSCalendar


def market_reader(at, policy, *, right='CALL', exit_symbol=None):
    catalog = {i.instrument_id: i for i in policy.candidates}
    strikes = {i.contract.underlying: i.contract.strike for i in policy.candidates[:4]}

    async def capture(capture_policy, *, schemas, plan):
        observations = []
        for call in plan.calls:
            if call.tool == 'get_equity_quotes':
                rows = []
                for symbol in call.arguments['symbols']:
                    price = strikes[symbol] + (D('.8') if right == 'CALL' else D('-.8'))
                    q = equity(symbol) | {'bid_price': str(price), 'ask_price': str(price + D('.01'))}
                    for field in ('venue_bid_time', 'venue_ask_time', 'venue_last_trade_time'):
                        q[field] = at.isoformat()
                    rows.append({'quote': q})
            elif call.tool == 'get_option_quotes':
                rows = []
                for identity in call.arguments['instrument_ids']:
                    instrument = catalog[identity]
                    q = option() | {'instrument_id': identity, 'updated_at': at.isoformat(),
                                    'ask_size': 1,
                                    'delta': '.45' if instrument.contract.right == 'CALL' else '-.45'}
                    if instrument.contract.underlying == exit_symbol:
                        q.update(bid_price='.40', ask_price='.41')
                    rows.append({'quote': q})
            else:
                assert call.label == 'history'
                start = datetime.fromisoformat(call.arguments['start_time'])
                end = datetime.fromisoformat(call.arguments['end_time'])
                rows = []
                for symbol in call.arguments['symbols']:
                    offset = strikes[symbol] - 600
                    bars = [dict(begins_at=(start + timedelta(minutes=5*n)).isoformat(),
                                 open_price=str(b.open + offset), high_price=str(b.high + offset),
                                 low_price=str(b.low + offset), close_price=str(b.close + offset),
                                 volume=b.volume, interpolated=False, session='reg')
                            for n, b in enumerate(history(right).bars)]
                    while len(bars) < int((end-start).total_seconds()) // 300:
                        bars.append(bars[-1] | {'begins_at': (start + timedelta(minutes=5*len(bars))).isoformat()})
                    rows.append(dict(symbol=symbol, interval='5minute', bounds='regular', bars=bars))
            observations.append(dict(label=call.label, tool=call.tool, completed=True,
                                     received_at=(at + timedelta(seconds=1)).isoformat(), raw=envelope(rows)))
        return CaptureResult(request_id='a'*32, policy_sha256=policy_digest(capture_policy),
                             operation='CAPTURE', started_at=at, collected_at=at + timedelta(seconds=1),
                             elapsed_seconds=1, status='COMPLETE', schemas=schemas, plan=plan,
                             observations=observations)
    return capture


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
def test_production_profile_two_options_fill_and_exit_independently(tmp_path, captures, schemas, monkeypatch, right):
    settings, policy = combined(captures)
    key = tmp_path / 'synthetic-key'
    key.write_text('offline-test-never-transmitted')
    key.chmod(0o600)
    feed_dir, owner = tmp_path / 'feed', tmp_path / 'owner'
    settings = type(settings).model_validate(settings.model_dump() | {
        'key_file': str(key),
        'runtime': settings.runtime.model_dump() | {'feed_file': str(feed_dir / 'feed.json')},
    })
    times = [datetime(2026, 10, 28, 14, 0, 26, tzinfo=UTC)]
    initialize(owner, settings, clock=lambda: times[0])
    requests = []

    async def model(request, _secret, *, broad):
        requests.append(request)
        o = request.packet.opportunities[0]
        stop = o.candidate.proposal.underlying_invalidation
        anchor = o.underlying.ask if right == 'CALL' else o.underlying.bid
        target = anchor + 2 * (anchor - stop)
        plan = plan_class(request.packet.policy)(
            decision_id=request.packet.decision_id, packet_hash=fingerprint(request.packet),
            action='ENTER', stock=False, scope=False, candidate_id=o.candidate.candidate_id,
            condition='NOW', underlying_invalidation=stop, underlying_target=target,
            horizon_seconds=600, evidence_ids=o.evidence_ids,
            thesis='Synthetic confirmed breakout', uncertainty='Offline test response',
        )
        return result_for(request, plan=plan, count=100, usage=UsageEvidence(
            request_id=f'synthetic-{len(requests)}', model=settings.execution.cost_policy.model,
            input_tokens=100, output_tokens=20))

    async def unexpected_model(*args, **kwargs):
        raise AssertionError('Unexpected model transport in offline lifecycle')

    monkeypatch.setattr('app.options.position_judgment.run_position_process', unexpected_model)
    monkeypatch.setattr('app.options.entry_judgment.run_entry_process', unexpected_model)
    feed = ContinuousFeed(feed_dir, policy, schemas, create=True)
    try:
        with existing_runtime(owner, clock=lambda: times[0]) as (runtime, _):
            monkeypatch.setattr(runtime.c, '_model_run', model)
            enable(runtime)

            async def deliver(*, cycle=False, exit_symbol=None):
                at = times[0]
                outcome = await feed.tick(now=at, source_settings=settings,
                    window=XNYSCalendar().current_window(at) if cycle else None,
                    reader=market_reader(at, policy, right=right, exit_symbol=exit_symbol))
                assert outcome['status'] == 'DELIVERED', outcome
                times[0] += timedelta(seconds=1)
                await step(runtime)
                return read_packet(feed_dir / 'feed.json')

            packet = asyncio.run(deliver(cycle=True))
            with runtime.c.engine.journal.read() as db:
                decisions = [json.loads(r[0]) for r in db.execute('SELECT result_json FROM execution_option_opportunities')]
            assert len(requests) == 1, decisions
            assert runtime.c.engine.venue.submit_count == 1, decisions
            assert all(h.source_clock_basis == 'COMPLETED_BAR_END' for h in packet.frame.histories)
            times[0] += timedelta(seconds=9)
            asyncio.run(deliver())
            snapshot = runtime.c.engine.venue.snapshot(times[0])
            assert len(snapshot.positions) == 1
            times[0] = times[0].replace(minute=5, second=26)
            asyncio.run(deliver(cycle=True))
            with runtime.c.engine.journal.read() as db:
                decisions = [json.loads(r[0]) for r in db.execute('SELECT result_json FROM execution_option_opportunities')]
            assert len(requests) == 2, decisions
            assert runtime.c.engine.venue.submit_count == 2, decisions
            times[0] += timedelta(seconds=9)
            asyncio.run(deliver())
            snapshot = runtime.c.engine.venue.snapshot(times[0])
            assert len(snapshot.positions) == 2
            assert {p.contract.underlying for p in snapshot.positions.values()} == {'SPY', 'QQQ'}
            peer = {k: p for k, p in snapshot.positions.items() if p.contract.underlying == 'QQQ'}
            times[0] += timedelta(seconds=9)
            asyncio.run(deliver(exit_symbol='SPY'))
            assert runtime.c.engine.venue.submit_count == 3
            times[0] += timedelta(seconds=9)
            asyncio.run(deliver(exit_symbol='SPY'))
            assert runtime.c.engine.venue.snapshot(times[0]).positions == peer
            assert len(requests) == 2  # Mandatory protection needs no extra model call.
            saved = runtime.c.engine.venue.snapshot(times[0])

        # Reopening an interrupted owner retains its actual position and cash,
        # fences entries, and still allows independent mandatory protection.
        with existing_runtime(owner, clock=lambda: times[0]) as (runtime, _):
            assert runtime.c.engine.venue.snapshot(times[0]).positions == peer
            assert runtime.c.engine.venue.snapshot(times[0]).cash == saved.cash
            enable(runtime)
            times[0] += timedelta(seconds=9)
            asyncio.run(deliver(exit_symbol='QQQ'))
            assert runtime.c.engine.venue.submit_count == 4
            times[0] += timedelta(seconds=9)
            asyncio.run(deliver(exit_symbol='QQQ'))
            final = runtime.c.engine.venue.snapshot(times[0])
            assert not final.positions
            with runtime.c.engine.journal.read() as db:
                from test_paper_session_report import module as host_report
                assert host_report.fill_count(db) == (4, 'PORTFOLIO_ORDER_OBSERVATIONS')
                assert db.execute('SELECT COUNT(*) FROM execution_model_calls').fetchone()[0] == 2
            # Re-delivering the same packet cannot duplicate fills or charges.
            asyncio.run(step(runtime))
            assert runtime.c.engine.venue.snapshot(times[0]) == final
        from app.mixed.observer import MixedObserver
        report = MixedObserver(owner / 'options.db', settings.limits.population_id, clock=lambda: times[0]).report()
        assert report['fill_count'] == 4 and not report['positions']
        assert D(report['cash']) == final.cash
    finally:
        feed.close()
