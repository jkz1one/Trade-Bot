"""Original index clocks, tri-state interpolation and the native price-only scan."""
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_scope_price_options import inputs
from test_option_scope import AT

from app.mixed.scope_sources import assemble, map_index
from app.options.degen import DegenHistory
from app.options.scope_quality import ScopeQualityPolicy, scan_scope_quality


def receipts():
    data = json.loads((Path(__file__).parent / 'fixtures/robinhood_inputs_20261029.json').read_text())
    return tuple(copy.deepcopy(next(r for r in data['observations'] if r['tool'] == tool))
                 for tool in ('get_indexes', 'get_index_quotes', 'get_index_historicals'))


def synthetic():
    f, c, p = inputs()
    rows = receipts()
    for r in rows:
        r['attempted_at'] = (AT - timedelta(seconds=1)).isoformat()
        r['received_at'] = AT.isoformat()
    q = rows[1]['raw']['structuredContent']['data']['quotes'][0]
    q.update(venue_timestamp=AT.isoformat(), updated_at=AT.isoformat(), value='102')
    args = rows[2]['arguments']
    args.update(start_time=f.session.opens_at.isoformat(), end_time=AT.isoformat())
    h = rows[2]['raw']['structuredContent']['data']['results'][0]
    h['bars'] = [{
        'begins_at': b.begins_at.isoformat(), 'open_value': str(b.open),
        'high_value': str(b.high), 'low_value': str(b.low), 'close_value': str(b.close),
        'interpolated': False,
    } for b in f.histories[0].bars]
    return rows, f, c, p


def test_original_after_close_capture_preserves_unknowns_and_stale_venue_clock():
    rows = receipts()
    f, _, _ = inputs()
    raw = f.session.model_dump()
    raw['session_date'] = datetime(2026, 10, 29).date()
    for k in ('opens_at', 'entry_starts_at', 'entry_cutoff_at', 'protect_at', 'closes_at'):
        raw[k] = raw[k].replace(day=29)
    session = type(f.session).model_validate(raw)
    ref, history, report = map_index(*rows, session, now=datetime(2026, 10, 30, 1, tzinfo=UTC))
    assert history is None and report['status'] == 'BLOCKED'
    assert 'SPX_INDEX_VALUE_STALE' in report['issues']
    assert 'SPX_INTERPOLATION_STATUS_UNKNOWN' in report['issues']
    assert ref.source_at == datetime(2026, 10, 29, 20, 32, 47, 111440, tzinfo=UTC)
    assert ref.provider_updated_at != ref.original_source_time
    assert not ref.executable_book and not report['volume_available']
    assert 'bid' not in ref.model_dump() and 'ask' not in ref.model_dump()


def test_complete_original_price_history_reaches_native_scope_scan():
    rows, f, c, p = synthetic()
    ref, h, report = map_index(*rows, f.session, now=AT)
    assert report['status'] == 'MAPPED', report
    assert all(b.volume is None and 'volume' not in b.model_dump() for b in h.bars)
    common = dict(source='robinhood-mcp', entitlement='UNKNOWN', simulation_basis=None)
    equities = tuple(DegenHistory.model_validate(x.model_dump() | common) for x in f.histories[1:])
    m, q = f.metadata.model_copy(update=common), f.quote.model_copy(update=common)
    frame, ctx = assemble(f.session, h, equities, m, q, previous_session=c.previous_session)
    raw = p.model_dump()
    pf = raw['context']['structure']['preflight']
    for s in (*pf['sources'], *pf['history_sources']):
        s['source'] = 'robinhood-mcp'
    pf.update(metadata_source='robinhood-mcp', quote_source='robinhood-mcp')
    p = ScopeQualityPolicy.model_validate(raw)
    scan = scan_scope_quality(frame, ctx, p, now=AT)
    assert not scan.issues, scan.issues
    assert scan.context.structure.vwap is None
    assert len(scan.observations) == 8
    assert all(not o.complete_path_proven for o in scan.observations)
    assert not scan.authority and not scan.live_enabled


@pytest.mark.parametrize('damage', ['unknown', 'interpolated', 'gap', 'future_receipt', 'identity', 'clock', 'duplicate'])
def test_mapper_cannot_repair_unusable_inputs(damage):
    rows, f, _, _ = synthetic()
    h = rows[2]['raw']['structuredContent']['data']['results'][0]
    if damage == 'unknown':
        del h['bars'][0]['interpolated']
    elif damage == 'interpolated':
        h['bars'][0]['interpolated'] = True
    elif damage == 'gap':
        del h['bars'][2]
    elif damage == 'duplicate':
        h['bars'].append(h['bars'][-1])
    elif damage == 'future_receipt':
        rows[1]['received_at'] = (AT + timedelta(seconds=1)).isoformat()
    elif damage == 'identity':
        h['symbol'] = 'SPY'
    elif damage == 'clock':
        rows[1]['raw']['structuredContent']['data']['quotes'][0]['venue_timestamp'] = (AT + timedelta(seconds=1)).isoformat()
    if damage in {'unknown', 'interpolated', 'gap'}:
        _, history, report = map_index(*rows, f.session, now=AT)
        assert history is None and report['issues']
    else:
        with pytest.raises(ValueError):
            map_index(*rows, f.session, now=AT)
