"""Replay retained native collector attempts without a provider or writable owner."""
import asyncio
import sqlite3
from datetime import timedelta

import pytest
from test_combined_session_feed import reader as market_reader
from test_connected_runtime import digest
from test_contract_catalog import captures as captures  # noqa: PLC0414
from test_preopen_inputs import AT, enrolled
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_bar_mapping_proof import synthetic

from app.mixed.preopen_inputs import prepare
from app.mixed.preopen_replay import report
from app.options.read_gateway import CapturePlan


@pytest.mark.parametrize('damage', ['none', 'missing', 'interpolation', 'wrong_binding'])
def test_saved_preopen_reports_each_series_without_new_reads(tmp_path, captures, schemas, monkeypatch, damage):
    args = enrolled(tmp_path, captures, schemas)
    _, _, artifact = synthetic(schemas, at=AT)
    if damage == 'missing':
        artifact['result']['observations'][0]['raw']['structuredContent']['data']['results'][0]['bars'].pop()
    if damage == 'interpolation':
        artifact['result']['observations'][0]['raw']['structuredContent']['data']['results'][0]['bars'][-1]['interpolated'] = True
    times = [AT]
    async def reader(cp, *, schemas, plan):
        market = CapturePlan.model_validate(plan.model_dump() | {
            'calls': tuple(c for c in plan.calls if not c.label.startswith('swing-'))})
        result = await market_reader(AT)(cp, schemas=schemas, plan=market)
        times[0] = AT + timedelta(seconds=2)
        return result.model_copy(update={'plan': plan,
            'schemas': schemas.model_copy(update={'captured_at': AT + timedelta(seconds=1)}),
            'observations': result.observations + artifact['result']['observations']})
    prepared = asyncio.run(prepare(*args, AT.date(), clock_source=lambda: times[0], reader=reader))
    sequence = prepared['collection']['sequence']
    if damage == 'wrong_binding':
        with sqlite3.connect(args[1] / 'collector.db') as db:
            db.execute('UPDATE attempts SET request_hash=? WHERE sequence=?', ('0' * 64, sequence))
    before = digest(tmp_path)
    def forbidden(*a, **k):
        raise AssertionError('Replay opened writable collector or provider')
    monkeypatch.setattr('app.mixed.continuous_feed.ContinuousFeed.__init__', forbidden)
    monkeypatch.setattr('app.options.read_capture.collect', forbidden)
    if damage == 'wrong_binding':
        with pytest.raises(ValueError, match='binding mismatch'):
            report(args[1], args[2], args[3], sequence)
    else:
        result = report(args[1], args[2], args[3], sequence)
        assert result['history_mapped'] == (damage == 'none')
        assert result['capture_schema_discovered_at'] != result['enrolled_schema_discovered_at']
        assert len(result['histories']) == 4
        assert all(x['status'] == 'MAPPED' for x in result['histories'][1:])
        assert result['provider_calls'] is result['state_modified'] is result['live_enabled'] is False
        if damage == 'missing':
            issue = result['histories'][0]['diagnostic']
            assert issue['reason'] == 'SOURCE_COVERAGE_MISMATCH'
            assert issue['expected_bars'] == 56 and issue['observed_bars'] == 55
            assert issue['missing_bars'] == 1 and issue['unexpected_bars'] == issue['duplicate_bars'] == 0
            assert len(issue['missing_begins_at']) == 1
            assert prepared['collection']['history_preparation']['diagnostic'] == issue
        if damage == 'interpolation':
            assert result['histories'][0]['diagnostic']['reason'] == 'INTERPOLATED_BAR'
    assert digest(tmp_path) == before
