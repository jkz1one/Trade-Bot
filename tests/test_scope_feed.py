"""Pinned Scope reads and current native delivery without synthetic index books."""
import asyncio
import copy
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_scope_sources import synthetic
from test_option_scope import AT

from app.mixed.scope_feed import ScopeFeedBinding, deliver
from app.options.coordinator import DegenFrame
from app.options.degen import DegenHistory
from app.options.models import OptionInstrument
from app.options.read_capture import CaptureResult
from app.options.scope_read import calls, run, validate
from app.options.scope import preflight_scope
from app.options.scope_quality import ScopeQualityPolicy
from app.options.scope_watch import ScopeWatchChoice, ScopeWatchPolicy
from app.options.scope_runtime import validate_packet
from app.options.runtime_models import PortfolioRuntimePacket


def setup():
    rows, f, c, p = synthetic()
    started = AT - timedelta(seconds=1)
    for row, (_, arguments) in zip(rows, calls(rows[1]['arguments']['instrument_ids'][0], started), strict=True):
        row['arguments'] = arguments
    common = dict(source='robinhood-mcp', entitlement='UNKNOWN', simulation_basis=None)
    instrument = OptionInstrument.model_validate(f.metadata.instrument.model_dump() | {'provider': 'robinhood'})
    metadata = f.metadata.model_copy(update=common | {'instrument': instrument})
    quote = f.quote.model_copy(update=common | {'instrument': instrument})
    binding = ScopeFeedBinding(session=f.session, previous_session=c.previous_session, instrument=instrument,
        choice=ScopeWatchChoice(pattern='trap_reversal', parent_pattern='trap_reversal', right='CALL'),
        contract_capture_sha256='a'*64)
    raw = p.model_dump(); pf = raw['context']['structure']['preflight']
    pf.update(provider='robinhood', metadata_source='robinhood-mcp', quote_source='robinhood-mcp', max_history_age_seconds=300)
    for s in (*pf['sources'], *pf['history_sources']):
        s['source'] = 'robinhood-mcp'
    quality = ScopeQualityPolicy.model_validate(raw)
    watch = ScopeWatchPolicy(context=quality.context, quality=quality, max_called_plays_per_session=2)
    settings = SimpleNamespace(limits=SimpleNamespace(mode='PAPER', underlying_source='robinhood-mcp'),
                               scope_policy=SimpleNamespace(watch=watch))
    frame = DegenFrame(portfolio_version='portfolio-frame-v2', quotes=(quote,), histories=tuple(
        DegenHistory.model_validate(h.model_dump() | common) for h in f.histories[1:]))
    cap = CaptureResult(request_id='a'*32, policy_sha256='b'*64, operation='SCOPE_INPUT',
        started_at=started, collected_at=AT, elapsed_seconds=1, status='COMPLETE', observations=list(rows))
    return binding, cap, frame, metadata, settings


def test_native_watch_delivery_arming_cycle_and_no_terminal_replay():
    binding, cap, frame, metadata, settings = setup()
    out, action, issues = deliver(binding, cap, frame, (metadata,), now=AT, settings=settings, sequence=1)
    assert not issues and action.kind == 'CALL'
    assert out.scope.underlying.executable_book is False
    assert 'bid' not in out.scope.underlying.model_dump()
    watched = out.model_copy(update={'histories': ()})
    packet = PortfolioRuntimePacket(population_id='scope-test', sequence=1, recorded_at=AT,
        frame=watched, kind='WATCH', action=action)
    c = SimpleNamespace(scope_policy=settings.scope_policy, engine=SimpleNamespace(limits=SimpleNamespace(
        provider='robinhood', allowed_underlyings=('SPX', 'SPY', 'QQQ'), underlying_source='robinhood-mcp')))
    validate_packet(c, packet)
    different = out.scope.frame.index_reference.model_copy(update={'value': out.scope.underlying.value + 1})
    changed = out.scope.model_copy(update={'frame': out.scope.frame.model_copy(update={'index_reference': different})})
    with pytest.raises(ValueError, match='Conflicting Scope frame'):
        validate_packet(c, packet.model_copy(update={'frame': watched.model_copy(update={'scope': changed})}))
    for record, expected in (({'status': 'WATCHING'}, 'OBSERVE_ARMING'),
                             ({'status': 'WATCHING', 'arming': {'status': 'ARMED'}}, None)):
        out, action, issues = deliver(binding, cap, frame, (metadata,), now=AT, settings=settings, sequence=2, record=record)
        assert not issues and out.scope is not None
        assert (action.kind if action else None) == expected
    out, action, issues = deliver(binding, cap, frame, (metadata,), now=AT, settings=settings,
                                  sequence=3, record={'status': 'INVALIDATED_UNFILLED'})
    assert out.scope is None and action is None


def test_incomplete_spx_keeps_peer_books_and_index_reference_only():
    binding, cap, frame, metadata, settings = setup()
    raw = copy.deepcopy(cap.observations)
    del raw[2]['raw']['structuredContent']['data']['results'][0]['bars'][0]['interpolated']
    cap = cap.model_copy(update={'observations': raw})
    out, action, issues = deliver(binding, cap, frame, (metadata,), now=AT, settings=settings, sequence=1)
    assert 'SPX_INTERPOLATION_STATUS_UNKNOWN' in issues
    assert out.quotes == frame.quotes and out.scope is None and action is None
    assert len(out.held_underlyings) == 1


def test_current_index_can_invalidate_watch_without_replacing_missing_history():
    from app.options.scope_structure import scan_scope_structure
    binding, cap, frame, metadata, settings = setup()
    original, _, _ = deliver(binding, cap, frame, (metadata,), now=AT, settings=settings, sequence=1)
    scan = scan_scope_structure(original.scope.frame, settings.scope_policy.watch.context.structure, now=AT)
    geometry = next(o.geometry for o in scan.observations if o.pattern == binding.choice.pattern and o.right == binding.choice.right)
    record = {'status': 'WATCHING', 'geometry': geometry.model_dump(mode='json'),
              'reviewed_frame': original.scope.frame.model_dump(mode='json'),
              'locked_context': original.scope.context.model_dump(mode='json')}
    rows = copy.deepcopy(cap.observations)
    quote = rows[1]['raw']['structuredContent']['data']['quotes'][0]
    # Match the original index schema; no executable stock price is manufactured.
    quote['value'] = str(geometry.invalidation)
    del rows[2]['raw']['structuredContent']['data']['results'][0]['bars'][0]['interpolated']
    out, action, issues = deliver(binding, cap.model_copy(update={'observations': rows}), frame,
        (metadata,), now=AT, settings=settings, sequence=2, record=record)
    assert action.kind == 'OBSERVE_QUOTE'
    assert 'SPX_INTERPOLATION_STATUS_UNKNOWN' in issues
    assert out.scope.frame.histories == original.scope.frame.histories


def test_completed_history_can_cover_hold_but_not_missing_next_bar():
    binding, cap, frame, metadata, settings = setup()
    from app.mixed.scope_sources import map_index, assemble
    _, history, _ = map_index(*cap.observations, binding.session, now=AT)
    equity = tuple(h.model_copy(update={'source_at': h.bars[-1].ends_at}) for h in frame.histories)
    for seconds in (0, 10, 60, 120, 298):
        now = AT + timedelta(seconds=seconds)
        m, q = metadata.model_copy(update={'source_at': now, 'received_at': now}), frame.quotes[0].model_copy(update={'source_at': now, 'received_at': now})
        supplied, _ = assemble(binding.session, history, equity, m, q, previous_session=binding.previous_session)
        assert not preflight_scope(supplied, settings.scope_policy.watch.context.structure.preflight, now=now).blockers
        stale = supplied.model_copy(update={'quote': frame.quotes[0]})
        if seconds >= 60:
            assert preflight_scope(stale, settings.scope_policy.watch.context.structure.preflight, now=now).blockers
    now = AT + timedelta(minutes=5)
    assert preflight_scope(supplied, settings.scope_policy.watch.context.structure.preflight, now=now).blockers


def test_scope_worker_pins_before_calls_and_rejects_extra_calls(monkeypatch):
    binding, cap, _, _, _ = setup()
    metadata = json.loads((Path(__file__).parent / 'fixtures/robinhood_input_probe_schemas.json').read_text())
    inventory = {'tools': [{'name': k, 'metadata': v} for k,v in metadata.items()]}
    seen = []
    class Client:
        async def call_tool(self, name, arguments):
            seen.append(name)
            return copy.deepcopy(next(r['raw'] for r in cap.observations if r['tool']==name))
    monkeypatch.setattr('app.options.scope_read.utc_now', lambda: AT)
    rows = []
    asyncio.run(run(Client(), inventory, cap.started_at, rows))
    assert seen == ['get_indexes', 'get_index_historicals', 'get_index_quotes']
    validate(rows, cap.started_at, complete=True)
    with pytest.raises(ValueError):
        validate([*rows, rows[0]], cap.started_at)
    damaged = copy.deepcopy(inventory)
    damaged['tools'][0]['metadata']['description'] = 'changed'
    seen.clear()
    # Damage the SPX capability specifically; no provider calls may occur.
    next(t for t in damaged['tools'] if t['name']=='get_indexes')['metadata']['description'] = 'changed'
    with pytest.raises(ValueError):
        asyncio.run(run(Client(), damaged, cap.started_at, []))
    assert not seen


@pytest.mark.parametrize('scope_fault', [None, 'failed', 'identity'])
def test_collector_retains_pinned_reads_counts_quota_and_delivers_native_watch(tmp_path, schemas, scope_fault):
    from test_portfolio_feed import policy
    from test_robinhood_read_mapping import envelope, equity, option
    from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
    from app.options.read_capture import policy_digest
    from app.options.runtime import read_packet
    from app.robinhood.schedule import XNYSCalendar
    binding, cap, frame, metadata, settings = setup()
    feed_policy = FeedPolicy.model_validate(policy().model_dump() | {
        'observed_simulation': 'robinhood-observed-v1', 'scope_binding': binding})
    settings.limits.population_id = feed_policy.population_id
    settings.stock_policy = SimpleNamespace(instruments=feed_policy.stocks, swing=None)
    settings.swing_policy = None
    cap = cap.model_copy(update={'policy_sha256': policy_digest(feed_policy.capture)})
    if scope_fault == 'identity':
        cap.observations[1]['raw']['structuredContent']['data']['quotes'][0]['symbol'] = 'WRONG'
    seen = []
    async def reader(p, *, scope_input=False, schemas=None, plan=None):
        assert scope_input
        seen.append('COMBINED')
        rows = []
        for call in plan.calls:
            if call.tool == 'get_equity_quotes':
                values = []
                for symbol in call.arguments['symbols']:
                    q = equity(symbol)
                    q.update(venue_bid_time=AT.isoformat(), venue_ask_time=AT.isoformat(), venue_last_trade_time=AT.isoformat())
                    values.append({'quote': q})
            elif call.tool == 'get_option_quotes':
                values = [{'quote': option() | {'instrument_id': binding.instrument.instrument_id,
                    'bid_price': '1.00', 'ask_price': '1.05', 'updated_at': AT.isoformat()}}]
            else:
                values = [{'symbol': h.symbol, 'interval': '5minute', 'bounds': 'regular', 'bars': [
                    {'begins_at': b.begins_at.isoformat(), 'open_price': str(b.open), 'high_price': str(b.high),
                     'low_price': str(b.low), 'close_price': str(b.close), 'volume': b.volume,
                     'interpolated': False, 'session': 'reg'} for b in h.bars]} for h in frame.histories]
            rows.append({'label': call.label, 'tool': call.tool, 'completed': True,
                         'raw': envelope(values), 'received_at': (AT + timedelta(seconds=1)).isoformat()})
        return CaptureResult(request_id='b'*32, policy_sha256=policy_digest(p), operation='CAPTURE',
            started_at=cap.started_at, collected_at=AT+timedelta(seconds=1), elapsed_seconds=2, status='COMPLETE',
            plan=plan, schemas=schemas, observations=rows, scope_requested=True, scope_observations=cap.observations,
            scope_error_class='RuntimeError' if scope_fault == 'failed' else None)
    feed = ContinuousFeed(tmp_path / 'feed', feed_policy, schemas, create=True)
    try:
        result = asyncio.run(feed.tick(now=cap.started_at, window=XNYSCalendar().current_window(AT),
            reader=reader, source_settings=settings, scope_state=lambda _: None))
        assert result['status'] == 'DELIVERED'
        packet = read_packet(tmp_path / 'feed/feed.json')
        if scope_fault is None:
            assert packet.kind == 'WATCH', packet.coverage_issues
            assert packet.action.kind == 'CALL' and packet.frame.scope.underlying.executable_book is False
        else:
            assert packet.kind == 'CYCLE' and packet.frame.scope is None
            assert packet.frame.quotes and packet.frame.histories
            assert any(x.startswith('SCOPE_') for x in packet.coverage_issues)
        assert feed.db.execute('SELECT calls FROM attempts').fetchone()[0] == 6
        assert feed.db.execute('SELECT COUNT(*) FROM scope_read_receipts').fetchone()[0] == 1
        assert seen == ['COMBINED']
    finally:
        feed.close()


from test_robinhood_read_mapping import schemas as schemas
