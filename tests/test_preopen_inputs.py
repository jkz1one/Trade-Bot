"""Native collection/binding without opening a writable execution owner."""
import asyncio
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from test_combined_session_feed import combined
from test_combined_session_feed import reader as market_reader
from test_connected_runtime import digest
from test_contract_catalog import captures as captures  # noqa: PLC0414
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_bar_mapping_proof import synthetic

from app.execution.runtime import runtime_lease
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.preopen_inputs import prepare
from app.mixed.swing_feed import SwingHistoryPolicy, planned_history
from app.options.read_gateway import CapturePlan
from app.options.runtime_cli import initialize

AT = datetime(2026, 10, 28, 12, tzinfo=UTC)


def enrolled(tmp_path, captures, schemas):
    settings, policy = combined(captures)
    key = tmp_path / 'key'
    key.write_text('synthetic-unopened-after-enrollment')
    key.chmod(0o600)
    owner, feed = tmp_path / 'owner', tmp_path / 'feed'
    settings = type(settings).model_validate(settings.model_dump() | {
        'key_file': str(key), 'runtime': settings.runtime.model_dump() | {'feed_file': str(feed / 'feed.json')}})
    initialize(owner, settings, clock=lambda: AT)
    ContinuousFeed(feed, policy, schemas, create=True).close()
    paths = (tmp_path / 'policy.json', tmp_path / 'schemas.json')
    for path, value in zip(paths, (policy, schemas)):
        path.write_text(value.model_dump_json()); path.chmod(0o600)
    key.unlink()  # No model secret is available to the pre-open operation.
    return (owner, feed, *paths)


@pytest.mark.parametrize('damaged', [False, True])
def test_preopen_preserves_owner_and_retains_original_history(tmp_path, captures, schemas, damaged):
    args = enrolled(tmp_path, captures, schemas)
    before = digest(args[0])
    _, _, artifact = synthetic(schemas, at=AT)
    if damaged:
        artifact['result']['observations'][0]['raw']['structuredContent']['data']['results'][0]['bars'][-1]['interpolated'] = True
    calls = []
    times = [AT]
    async def reader(cp, *, schemas, plan):
        calls.append(plan)
        market = CapturePlan.model_validate(plan.model_dump() | {'calls': tuple(c for c in plan.calls if not c.label.startswith('swing-'))})
        result = await market_reader(AT)(cp, schemas=schemas, plan=market)
        times[0] = AT + timedelta(seconds=2)
        return result.model_copy(update={'plan': plan,
            'schemas': schemas.model_copy(update={'captured_at': AT + timedelta(seconds=1)}),
            'observations': result.observations + artifact['result']['observations']})
    result = asyncio.run(prepare(*args, AT.date(), clock_source=lambda: times[0], reader=reader))
    assert len(calls) == 1
    assert result['collection']['status'] == 'DELIVERED', result
    assert result['owner_modified'] is False and result['model_calls'] == result['orders_submitted'] == 0
    assert digest(args[0]) == before
    if damaged:
        assert result['status'] == 'PREOPEN_INPUTS_BLOCKED'
        assert 'SWING_PREOPEN_HISTORY_UNAVAILABLE' in result['swing_binding']['blockers']
        assert result['collection']['history_preparation']['diagnostic']['reason'] == 'INTERPOLATED_BAR'
    else:
        assert result['swing_binding']['status'] == 'PREPARED', result
        async def forbidden(*a, **k): raise AssertionError('Repeated source binding read provider')
        repeated = asyncio.run(prepare(*args, AT.date(), clock_source=lambda: AT + timedelta(seconds=10), reader=forbidden))
        assert repeated['collection']['status'] == 'RETAINED_HISTORY'
        assert repeated['swing_binding'] == result['swing_binding']
        assert digest(args[0]) == before


def test_active_owner_and_wrong_target_refuse_before_provider(tmp_path, captures, schemas):
    args = enrolled(tmp_path, captures, schemas)
    async def forbidden(*a, **k): raise AssertionError('Provider called')
    with runtime_lease(args[0] / 'options.db'), pytest.raises(BlockingIOError):
        asyncio.run(prepare(*args, AT.date(), clock_source=lambda: AT, reader=forbidden))
    with pytest.raises(ValueError, match='PREOPEN_TARGET_WINDOW_REQUIRED'):
        asyncio.run(prepare(*args, date(2026, 10, 29), clock_source=lambda: AT, reader=forbidden))


def test_weekend_date_keys_include_friday_without_future_bounds():
    now = datetime(2026, 10, 31, 12, tzinfo=UTC)
    policy = SwingHistoryPolicy(bar_mapping='utc-day-halfhour-v1')
    target, calls = planned_history(policy, ('SPY', 'QQQ'), now)
    assert target == date(2026, 11, 2)
    assert len(calls) == 4
    for call in calls:
        assert datetime.fromisoformat(call.arguments['end_time']) <= now
        if call.arguments['interval'] == 'day':
            assert call.arguments['end_time'] == '2026-10-31T00:00:00+00:00'
    assert planned_history(policy, ('SPY',), datetime(2026, 10, 30, 22, tzinfo=UTC)) == (None, ())


@pytest.mark.parametrize('failure', ['mapping', 'clock'])
@pytest.mark.parametrize('damage', ['none', 'interpolation', 'binding', 'receipt', 'missing'])
def test_install_saved_history_without_accepting_packet_or_reading_provider(
        tmp_path, captures, schemas, monkeypatch, failure, damage):
    args = enrolled(tmp_path, captures, schemas)
    before_owner = digest(args[0])
    _, _, artifact = synthetic(schemas, at=AT)

    async def reader(cp, *, schemas, plan):
        market = CapturePlan.model_validate(plan.model_dump() | {
            'calls': tuple(c for c in plan.calls if not c.label.startswith('swing-'))})
        result = await market_reader(AT)(cp, schemas=schemas, plan=market)
        return result.model_copy(update={'plan': plan,
            'schemas': schemas.model_copy(update={'captured_at': AT + timedelta(seconds=1)}),
            'observations': result.observations + artifact['result']['observations']})

    def old_failure(*a, **k):
        raise ValueError('Earlier mapping or unrelated packet rejection')

    with monkeypatch.context() as patch:
        patch.setattr('app.mixed.swing_feed.snapshot', old_failure)
        first = asyncio.run(prepare(*args, AT.date(), clock_source=lambda: AT, reader=reader))
    if failure == 'clock':
        async def changed_book(cp, *, schemas, plan):
            result = await reader(cp, schemas=schemas, plan=plan)
            result = result.model_copy(deep=True)
            for observation in result.observations:
                observation['received_at'] = (AT + timedelta(seconds=21)).isoformat()
            receipt = next(x for x in result.observations if x['tool'] == 'get_option_quotes')
            receipt['raw']['structuredContent']['data']['results'][0]['quote']['bid_size'] += 1
            return result.model_copy(update={'started_at': AT + timedelta(seconds=20),
                                             'collected_at': AT + timedelta(seconds=21)})
        first = asyncio.run(prepare(*args, AT.date(), clock_source=lambda: AT + timedelta(seconds=20),
                                    reader=changed_book))
        assert first['collection']['failure']['stage'] == 'SOURCE_CLOCK_CHECK'
    sequence = first['collection']['sequence']
    assert first['status'] == 'PREOPEN_INPUTS_BLOCKED'
    assert first['collection']['status'] == ('DELIVERED' if failure == 'mapping' else 'FAILED')
    with sqlite3.connect(args[1] / 'collector.db') as db:
        if damage == 'binding':
            db.execute('UPDATE attempts SET request_hash=? WHERE sequence=?', ('0' * 64, sequence))
        elif damage in ('interpolation', 'receipt'):
            raw = json.loads(db.execute('SELECT raw_json FROM attempts WHERE sequence=?', (sequence,)).fetchone()[0])
            receipt = next(x for x in raw['observations'] if x['label'].startswith('swing-'))
            if damage == 'receipt':
                receipt['label'] = 'wrong-source'
            else:
                receipt['raw']['structuredContent']['data']['results'][0]['bars'][-1]['interpolated'] = True
            db.execute('UPDATE attempts SET raw_json=? WHERE sequence=?', (json.dumps(raw), sequence))
        attempts = db.execute('SELECT * FROM attempts').fetchall()
    feed_file = args[1] / 'feed.json'
    original_packet = feed_file.read_bytes() if feed_file.exists() else None

    async def forbidden(*a, **k):
        raise AssertionError('Saved history must not read provider')

    def install():
        return asyncio.run(prepare(*args, AT.date(), sequence=sequence if damage != 'missing' else 999,
                                  clock_source=lambda: AT + timedelta(seconds=30), reader=forbidden))

    if damage == 'none':
        accepted = install()
        assert accepted['status'] == 'PREOPEN_INPUTS_PREPARED', accepted
        assert accepted['collection']['status'] == 'SAVED_HISTORY_INSTALLED'
        assert accepted['collection']['provider_calls'] is False
        repeated = install()
        assert repeated['collection']['status'] == 'RETAINED_HISTORY'
        assert repeated['swing_binding'] == accepted['swing_binding']
        with pytest.raises(ValueError, match='SAVED_HISTORY_SESSION_MISMATCH'):
            asyncio.run(prepare(*args, date(2026, 10, 29), sequence=sequence,
                                clock_source=lambda: AT + timedelta(days=1), reader=forbidden))
    else:
        with pytest.raises(ValueError):
            install()
    with sqlite3.connect(args[1] / 'collector.db') as db:
        assert db.execute('SELECT * FROM attempts').fetchall() == attempts
        assert db.execute('SELECT COUNT(*) FROM swing_history').fetchone()[0] == (damage == 'none')
    assert (feed_file.read_bytes() if feed_file.exists() else None) == original_packet
    assert digest(args[0]) == before_owner
