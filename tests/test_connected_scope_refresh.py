"""Reviewed one-shot reads use the existing collector quota and original clocks."""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_option_scope import AT
from test_portfolio_feed import policy
from test_scope_feed import setup
from test_observed_scope_lifecycle import scope_reader
from test_robinhood_read_mapping import schemas as schemas

from app.execution.engine import ExecutionBlocked
from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
from app.mixed.scope_refresh import ConnectedScopeRefresh, validate_ticket
from app.options.engine import fingerprint
from app.options.runtime import read_packet
from app.robinhood.schedule import XNYSCalendar


def fixture(tmp_path, schemas, mode='bounded-paid-refresh-v1'):
    binding, _, _, _, settings = setup()
    binding = type(binding).model_validate(binding.model_dump() | {
        'post_cost_refresh': mode})
    p = FeedPolicy.model_validate(policy().model_dump() | {
        'scope_binding': binding, 'observed_simulation': 'robinhood-observed-v1'})
    settings.limits.population_id = p.population_id
    settings.stock_policy = SimpleNamespace(instruments=p.stocks, swing=None)
    settings.swing_policy = None
    feed = ContinuousFeed(tmp_path / 'feed', p, schemas, create=True)
    bridge = ConnectedScopeRefresh(None, feed, asyncio.Event())
    ticket = dict(cycle_key='synthetic-paid-cycle', play_key=binding.play_key(),
                  binding_sha256=fingerprint(binding), request_hash='a' * 64,
                  requested_at=(AT + timedelta(seconds=1)).isoformat(),
                  valid_until=(AT + timedelta(seconds=5)).isoformat())
    feed.db.execute("INSERT INTO scope_refresh_requests VALUES(?,?,?,'QUEUED',NULL,NULL)",
                    (ticket['cycle_key'], json.dumps(ticket), fingerprint(ticket)))
    feed.db.commit()
    return feed, bridge, binding, settings, ticket


@pytest.mark.parametrize('damage', ['payload', 'expired', 'future', 'foreign_play', 'unreviewed', 'session', 'used'])
def test_invalid_ticket_cannot_bypass_cadence_or_spend_reads(tmp_path, schemas, damage):
    feed, _, binding, _, ticket = fixture(tmp_path, schemas)
    try:
        now = AT + timedelta(seconds=1)
        if damage == 'payload':
            ticket['request_hash'] = 'b' * 64
        elif damage == 'expired':
            now = AT + timedelta(seconds=5)
        elif damage == 'future':
            now = AT
        elif damage == 'foreign_play':
            ticket['play_key'] = 'foreign'
        elif damage == 'unreviewed':
            feed.policy = feed.policy.model_copy(update={
                'scope_binding': binding.model_copy(update={'post_cost_refresh': None})})
        elif damage == 'session':
            now += timedelta(days=1)
        else:
            feed.db.execute("UPDATE scope_refresh_requests SET status='CAPTURING'")
        with pytest.raises(ExecutionBlocked, match='SCOPE_PAID_REFRESH_NOT_CURRENT'):
            validate_ticket(feed, ticket, now)
        assert feed.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0
    finally:
        feed.close()


def test_one_refresh_is_a_market_packet_and_spends_persisted_quota(tmp_path, schemas):
    feed, bridge, binding, settings, ticket = fixture(tmp_path, schemas)
    state = lambda _: {'status': 'WATCHING', 'arming': {'status': 'ARMED'}}
    async def scenario():
        async def tick(at, **kwargs):
            return await feed.tick(now=at, source_settings=settings, scope_state=state,
                reader=scope_reader(at, binding), window=XNYSCalendar().current_window(at), **kwargs)
        first = await tick(AT)
        assert first['status'] == 'DELIVERED'
        before = read_packet(feed.directory / 'feed.json')
        assert (await tick(AT + timedelta(seconds=1)))['status'] == 'RATE_LIMITED'
        future = asyncio.get_running_loop().create_future()
        # Start the actual collector loop first: it reaches its unchanged ten-
        # second sleep. A paid request must wake it within the original lease.
        loop = asyncio.create_task(feed.run(
            bridge.stop, clock_source=lambda: AT + timedelta(seconds=1), held_source=lambda: (),
            calendar=XNYSCalendar(), source_settings=settings, scope_state=state,
            scope_refresh=bridge, reader=scope_reader(AT + timedelta(seconds=1), binding)))
        await asyncio.sleep(.01)
        bridge.pending = (ticket, future)
        bridge.wake.set()
        try:
            result = await asyncio.wait_for(asyncio.shield(future), 2)
        finally:
            bridge.stop.set()
            await loop
        assert result['status'] == 'DELIVERED' and result['sequence'] == first['sequence'] + 1
        after = read_packet(feed.directory / 'feed.json')
        assert after.kind == 'MARKET' and after.action is None
        assert not after.frame.histories and not after.frame.inventories
        assert after.frame.scope.underlying.source_at > before.frame.scope.underlying.source_at
        assert after.frame.scope.frame.histories[0].bars == before.frame.scope.frame.histories[0].bars
        assert feed.db.execute('SELECT SUM(calls) FROM attempts').fetchone()[0] == 12
        with pytest.raises(ExecutionBlocked):
            await tick(AT + timedelta(seconds=2), paid_scope_refresh=ticket)
        assert (await tick(AT + timedelta(seconds=2)))['status'] == 'RATE_LIMITED'
    try:
        asyncio.run(scenario())
        p, directory = feed.policy, feed.directory
        feed.close()
        feed = ContinuousFeed(directory, p, schemas)
        ConnectedScopeRefresh(None, feed, asyncio.Event())
        row = feed.db.execute('SELECT * FROM scope_refresh_requests').fetchone()
        assert row['status'] == 'DELIVERED' and row['capture_sequence'] == 2
        assert feed.db.execute('SELECT SUM(calls) FROM attempts').fetchone()[0] == 12
        with pytest.raises(ExecutionBlocked):
            validate_ticket(feed, ticket, AT + timedelta(seconds=2))
    finally:
        feed.close()


@pytest.mark.parametrize('status', ['QUEUED', 'CAPTURING', 'CANCELLED', 'RATE_LIMITED'])
def test_restart_never_replays_paid_read(tmp_path, schemas, status):
    feed, _, _, _, ticket = fixture(tmp_path, schemas)
    try:
        feed.db.execute('UPDATE scope_refresh_requests SET status=?', (status,))
        feed.db.commit()
        before = feed.db.execute('SELECT payload_json,payload_hash FROM scope_refresh_requests').fetchone()
        p, directory = feed.policy, feed.directory
        feed.close()
        feed = ContinuousFeed(directory, p, schemas)
        ConnectedScopeRefresh(None, feed, asyncio.Event())
        after = feed.db.execute('SELECT * FROM scope_refresh_requests').fetchone()
        assert tuple(before) == (after['payload_json'], after['payload_hash'])
        assert after['status'] == ('INTERRUPTED' if status in {'QUEUED', 'CAPTURING'} else status)
        with pytest.raises(ExecutionBlocked):
            validate_ticket(feed, ticket, AT + timedelta(seconds=1))
        assert feed.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0
    finally:
        feed.close()


@pytest.mark.parametrize('cancel', [False, True])
def test_stop_or_cancel_queued_work_does_not_collect(tmp_path, schemas, cancel):
    feed, bridge, _, _, ticket = fixture(tmp_path, schemas)
    async def scenario():
        future = asyncio.get_running_loop().create_future()
        bridge.pending = (ticket, future)
        if cancel:
            future.cancel()
        else:
            bridge.stop.set()
        async def forbidden(_):
            pytest.fail('Stopped/cancelled request performed a provider read')
        await bridge.collect(forbidden, now=AT + timedelta(seconds=1))
        assert bridge.pending is None and not bridge.wake.is_set()
        assert feed.db.execute('SELECT status FROM scope_refresh_requests').fetchone()[0] == 'CANCELLED'
    try:
        asyncio.run(scenario())
    finally:
        feed.close()


def test_binding_opt_in_preserves_legacy_serialization_and_changes_review_identity():
    binding, *_ = setup()
    original = binding.model_dump()
    assert 'post_cost_refresh' not in original
    changed = type(binding).model_validate(original | {'post_cost_refresh': 'bounded-paid-refresh-v1'})
    assert changed.play_key() != binding.play_key()
    assert type(binding).model_validate(original).play_key() == binding.play_key()
    with pytest.raises(ValueError):
        type(binding).model_validate(original | {'post_cost_refresh': 'unbounded'})


def test_explicit_binding_review_keeps_frozen_transport_and_account(tmp_path, schemas):
    from app.mixed.simulation_profile import configuration
    from app.mixed.price_options_profile import proposal
    from app.mixed.connected_check import connection_report
    from app.mixed.feed_rollover import validate_policy
    settings, base = configuration()
    settings = proposal(settings)[0]
    binding, *_ = setup()
    binding = binding.model_copy(update={'session': binding.session.model_copy(update={
        'source': settings.scope_policy.watch.context.structure.preflight.session_source})})
    settings = type(settings).model_validate(settings.model_dump() | {
        'runtime': settings.runtime.model_dump() | {'feed_file': str(tmp_path / 'feed/feed.json')}})
    original = settings.model_dump_json()
    proposed = FeedPolicy.model_validate(base.model_dump() | {
        'observed_simulation': 'robinhood-observed-v1', 'scope_binding': binding})
    args = dict(journal=tmp_path / 'owner/options.db', directory=tmp_path / 'feed', now=AT)
    assert 'SCOPE_POST_COST_REFRESH_NOT_REVIEWED' in connection_report(settings, proposed, schemas, **args)['entry_blockers']
    reviewed = proposed.model_copy(update={'scope_binding': binding.model_copy(update={
        'post_cost_refresh': 'bounded-paid-refresh-v1'})})
    assert 'SCOPE_POST_COST_REFRESH_NOT_REVIEWED' not in connection_report(settings, reviewed, schemas, **args)['entry_blockers']
    validate_policy(base, reviewed, binding.session.session_date, AT)
    assert settings.model_dump_json() == original
    for field in ('poll_seconds', 'calls_per_minute', 'capture'):
        assert getattr(reviewed, field) == getattr(base, field)
    with pytest.raises(ValueError, match='frozen transport'):
        validate_policy(base, reviewed.model_copy(update={'poll_seconds': 5}), binding.session.session_date, AT)


@pytest.mark.parametrize('mode', ['bounded-paid-refresh-v1', 'paced-paid-refresh-v2'])
def test_actual_loop_pacing_and_one_paid_read_stay_in_frozen_quota(tmp_path, schemas, mode):
    feed, bridge, binding, settings, ticket = fixture(tmp_path, schemas, mode)
    times, starts, paid = [AT], [], []
    async def scenario():
        async def reader(p, **kwargs):
            starts.append(times[0])
            result = await scope_reader(times[0], binding)(p, **kwargs)
            times[0] = result.collected_at
            return result
        async def wait(seconds):
            if len(starts) >= 8:
                bridge.stop.set()
            elif mode == 'paced-paid-refresh-v2' and len(starts) == 3 and not paid:
                ticket.update(requested_at=times[0].isoformat(),
                              valid_until=(times[0] + timedelta(seconds=4)).isoformat())
                feed.db.execute('UPDATE scope_refresh_requests SET payload_json=?,payload_hash=?',
                                (json.dumps(ticket), fingerprint(ticket)))
                feed.db.commit()
                future = asyncio.get_running_loop().create_future()
                paid.append(future)
                bridge.pending = ticket, future
                bridge.wake.set()
            else:
                times[0] += timedelta(seconds=seconds)
            await asyncio.sleep(0)
        bridge.wait = wait
        await feed.run(bridge.stop, clock_source=lambda: times[0], held_source=lambda: (),
                      calendar=XNYSCalendar(), source_settings=settings,
                      scope_state=lambda _: {'status': 'WATCHING', 'arming': {'status': 'ARMED'}},
                      scope_refresh=bridge, reader=reader)
        for at in starts:
            assert sum(6 for t in starts if at - timedelta(minutes=1) < t <= at) <= 24
        gaps = [(b-a).total_seconds() for a,b in zip(starts, starts[1:])]
        if mode == 'paced-paid-refresh-v2':
            assert paid[0].result()['status'] == 'DELIVERED'
            assert starts[:4] == [AT + timedelta(seconds=s) for s in (0,20,40,41)]
            assert max(gaps) <= 20
        else:
            assert max(gaps) > 30  # Reproduces the unpaced quota-starvation gap.
    try:
        asyncio.run(scenario())
        assert feed.policy.calls_per_minute == 24 and feed.policy.poll_seconds == 10
    finally:
        feed.close()


def test_budget_check_counts_failed_reads_and_rechecks_after_restart(tmp_path, schemas):
    from app.mixed.scope_schedule import budget
    feed, _, _, _, _ = fixture(tmp_path, schemas, 'paced-paid-refresh-v2')
    try:
        feed.db.execute("INSERT INTO attempts VALUES(1,?,21,'FAILED',?,NULL,NULL,NULL)",
                        (AT.isoformat(), 'a'*64))
        feed.db.commit()
        p, directory = feed.policy, feed.directory
        feed.close()
        feed = ContinuousFeed(directory, p, schemas)
        assert budget(feed, AT + timedelta(seconds=59), 6) == (False, AT + timedelta(seconds=60))
        assert budget(feed, AT + timedelta(seconds=60), 6)[0]
        assert not budget(feed, AT + timedelta(seconds=60), 25)[0]
    finally:
        feed.close()


def test_underestimated_held_book_cost_does_not_busy_poll(tmp_path, schemas):
    from app.mixed.scope_schedule import budget, wait_seconds
    feed, _, _, _, _ = fixture(tmp_path, schemas, 'paced-paid-refresh-v2')
    try:
        for sequence, seconds in enumerate((0, 20, 21), 1):
            feed.db.execute("INSERT INTO attempts VALUES(?,?,6,'FAILED',?,NULL,NULL,NULL)",
                            (sequence, (AT + timedelta(seconds=seconds)).isoformat(), 'a'*64))
        feed.db.commit()
        now = AT + timedelta(seconds=41)
        assert budget(feed, now, 6)[0] and not budget(feed, now, 7)[0]
        assert wait_seconds(feed, now) == 1
    finally:
        feed.close()
