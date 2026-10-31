"""Native collection/binding without opening a writable execution owner."""
import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from test_contract_catalog import captures as captures
from test_robinhood_read_mapping import schemas as schemas
from test_combined_session_feed import combined, reader as market_reader
from test_connected_runtime import digest
from test_swing_bar_mapping_proof import synthetic

from app.execution.runtime import runtime_lease
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.preopen_inputs import prepare
from app.mixed.swing_feed import planned_history, SwingHistoryPolicy
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
        return result.model_copy(update={'plan': plan, 'observations': result.observations + artifact['result']['observations']})
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
