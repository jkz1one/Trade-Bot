"""Native timeout/recovery integration; no provider, model, or brokerage calls."""
import asyncio
import json
from datetime import timedelta

import pytest
from test_connected_runtime import enrolled, state
from test_portfolio_feed import reader
from test_robinhood_read_mapping import AT, schemas as schemas  # noqa: F401

from app.mixed.connected_runtime import FlatFeedRecovery, run
from app.mixed.continuous_feed import ContinuousFeed
from app.options.runtime_cli import existing_runtime


@pytest.mark.parametrize('maximum', [0, 1, 3])
def test_native_feed_outages_require_advancing_sources_and_stop_at_reviewed_cap(tmp_path, schemas, maximum):
    args, _, policy = enrolled(tmp_path, schemas)
    at = [AT + timedelta(seconds=10)]

    async def scenario(runtime, feed):
        runtime.running = True
        recovery = FlatFeedRecovery(maximum, 0, AT)
        for outage in range(maximum + 1):
            # A real missing/stale feed tick latches the native account halt.
            at[0] += timedelta(seconds=40)
            await runtime.tick()
            assert state(args[0])[1]['halt_reason'] == 'OPTION_RUNTIME_FEED_UNAVAILABLE'
            assert not recovery.observe(runtime, at[0])
            async def deliver(*, source_shift):
                result = await feed.tick(now=at[0], reader=reader(at[0], [], source_shift=source_shift))
                assert result['status'] == 'DELIVERED', result
                at[0] += timedelta(seconds=2)
                await runtime.tick()
            shift = int((at[0] - AT).total_seconds())
            await deliver(source_shift=shift)
            assert not recovery.observe(runtime, at[0])  # One packet never resumes.
            assert not recovery.observe(runtime, at[0])  # Re-reading it is not progress.
            at[0] += timedelta(seconds=10)
            await deliver(source_shift=shift)  # New receipt, unchanged original source.
            assert not recovery.observe(runtime, at[0])
            at[0] += timedelta(seconds=10)
            await deliver(source_shift=int((at[0] - AT).total_seconds()))
            assert not recovery.observe(runtime, at[0])  # Stale sample reset the two-packet proof.
            at[0] += timedelta(seconds=10)
            await deliver(source_shift=int((at[0] - AT).total_seconds()))
            resumed = recovery.observe(runtime, at[0])
            assert resumed is (outage < maximum)
            assert bool(state(args[0])[1]['halted']) is (outage >= maximum)
        assert recovery.used == maximum
        with runtime.c.engine.journal.read() as db:
            events = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM execution_events WHERE kind='OPTION_REVIEWED_RESUME'")]
            assert len(events) == maximum
            assert all(r['reason'] == 'CONNECTED_FLAT_FEED_RECOVERY' for r in events)
            assert db.execute('SELECT COUNT(*) FROM execution_model_calls').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM execution_portfolio_orders').fetchone()[0] == 0

    with existing_runtime(args[0], clock=lambda: at[0]) as (runtime, _):
        feed = ContinuousFeed(args[1], policy, schemas)
        try:
            asyncio.run(scenario(runtime, feed))
        finally:
            feed.close()


@pytest.mark.parametrize('damage', ['manual', 'manual_same_reason', 'unknown_cost', 'stale_account', 'old_halt', 'generation', 'heartbeat', 'feed', 'next_day', 'other_halt_overwritten', 'operator_feed_halt'])
def test_recovery_cannot_clear_other_halts_or_incomplete_account_evidence(tmp_path, schemas, damage):
    args, _, policy = enrolled(tmp_path, schemas)
    at = [AT + timedelta(seconds=10)]

    async def scenario(runtime, feed):
        runtime.running = True
        await runtime.tick()
        recovery = FlatFeedRecovery(1, 0, AT if damage != 'old_halt' else at[0] + timedelta(seconds=1))
        recovery.observe(runtime, at[0])
        for n in range(2):
            at[0] += timedelta(seconds=10)
            result = await feed.tick(now=at[0], reader=reader(at[0], [], source_shift=int((at[0] - AT).total_seconds())))
            assert result['status'] == 'DELIVERED'
            at[0] += timedelta(seconds=2)
            await runtime.tick()
            if n == 0:
                assert not recovery.observe(runtime, at[0])
        engine = runtime.c.engine
        with engine.journal.write() as db:
            if damage == 'other_halt_overwritten':
                engine._halt(db, 'OPERATOR_HALT', at[0])
                engine._halt(db, 'OPTION_RUNTIME_FEED_UNAVAILABLE', at[0])
                db.execute("UPDATE execution_option_runtime SET status='BLOCKED',reason='OPTION_RUNTIME_FEED_UNAVAILABLE'")
            elif damage == 'operator_feed_halt':
                engine._halt(db, 'OPTION_RUNTIME_FEED_UNAVAILABLE', at[0])
                engine.journal.event(db, at[0], 'OPTIONS_OPERATOR_COMMAND',
                                     {'command': {'action': 'HALT'}, 'result': {'status': 'APPLIED'}})
                db.execute("UPDATE execution_option_runtime SET status='BLOCKED',reason='OPTION_RUNTIME_FEED_UNAVAILABLE'")
            elif damage == 'manual':
                engine._halt(db, 'OPERATOR_HALT', at[0])
            elif damage == 'manual_same_reason':
                engine._halt(db, 'OPTION_RUNTIME_FEED_UNAVAILABLE', at[0])
            elif damage in {'heartbeat', 'feed'}:
                field = 'heartbeat_at' if damage == 'heartbeat' else 'feed_recorded_at'
                db.execute('UPDATE execution_option_runtime SET ' + field + '=?', ((at[0]-timedelta(minutes=1)).isoformat(),))
            elif damage == 'next_day':
                at[0] += timedelta(days=1)
            elif damage == 'unknown_cost':
                db.execute("INSERT INTO execution_model_calls(source_key,packet_hash,started_at) VALUES('unknown',?,?)",
                           ('a'*64, at[0].isoformat()))
            elif damage == 'stale_account':
                db.execute("UPDATE execution_control SET issues_json='[\"UNRECONCILED\"]'")
            elif damage == 'generation':
                db.execute('UPDATE execution_option_runtime SET generation=generation+1')
        if damage == 'generation':
            with pytest.raises(ValueError, match='generations'):
                recovery.observe(runtime, at[0])
        else:
            assert not recovery.observe(runtime, at[0])
        if damage in {'other_halt_overwritten', 'operator_feed_halt'}:
            assert recovery.fenced
            for _ in range(2):
                at[0] += timedelta(seconds=10)
                await feed.tick(now=at[0], reader=reader(at[0], [], source_shift=int((at[0]-AT).total_seconds())))
                at[0] += timedelta(seconds=2)
                await runtime.tick()
                assert not recovery.observe(runtime, at[0])
        assert state(args[0])[1]['halted'] and recovery.used == 0

    with existing_runtime(args[0], clock=lambda: at[0]) as (runtime, _):
        feed = ContinuousFeed(args[1], policy, schemas)
        try:
            asyncio.run(scenario(runtime, feed))
        finally:
            feed.close()


@pytest.mark.parametrize('maximum', [-1, 4, True, 1])
def test_allowance_requires_valid_explicit_review_before_opening_owner(tmp_path, maximum):
    with pytest.raises(ValueError, match='reviewed'):
        asyncio.run(run(tmp_path/'absent', tmp_path/'feed', tmp_path/'policy', tmp_path/'schemas',
                        asyncio.Event(), max_feed_recoveries=maximum))
    assert not list(tmp_path.iterdir())


def test_reviewed_runner_recovers_one_outage_then_stops_and_restart_stays_halted(tmp_path, schemas, monkeypatch):
    args, _, _ = enrolled(tmp_path, schemas)
    at = [AT + timedelta(seconds=10)]
    with existing_runtime(args[0], clock=lambda: at[0]) as (runtime, _):
        with runtime.c.engine.journal.write() as db:
            runtime.c.engine._halt(db, 'OPTION_RUNTIME_STOPPED', at[0])
            db.execute("UPDATE execution_option_runtime SET status='STOPPED',reason='OPTION_RUNTIME_STOPPED'")
            revision = runtime.c.engine.journal.revision(db)

    phases, observations = [], []
    original_observe = FlatFeedRecovery.observe
    def observed(self, runtime, now):
        result = original_observe(self, runtime, now)
        with runtime.c.engine.journal.read() as db:
            row = runtime._bound(db)
            value = (self.halt, self.first, self.used, row['status'], row['reason'],
                     runtime.c.engine._control(db)['issues_json'])
        if not observations or observations[-1] != value:
            observations.append(value)
        return result
    monkeypatch.setattr(FlatFeedRecovery, 'observe', observed)
    async def wait_for(predicate):
        async with asyncio.timeout(8):
            while not predicate():
                await asyncio.sleep(.02)

    async def fixture_collect(self, stop, *, clock_source, held_source, calendar, source_settings=None):
        async def deliver():
            result = await self.tick(now=at[0], reader=reader(at[0], [], source_shift=int((at[0]-AT).total_seconds())))
            assert result['status'] == 'DELIVERED', result
            at[0] += timedelta(seconds=2)
            await wait_for(lambda: state(args[0])[0]['feed_sequence'] == result['sequence']
                           and state(args[0])[0]['status'] == 'RUNNING')
        phases.append('startup delivery')
        await deliver()
        phases.append('startup resume')
        await wait_for(lambda: not state(args[0])[1]['halted'])  # Reviewed startup, separate from cap.
        phases.append('outage')
        at[0] += timedelta(seconds=40)
        await wait_for(lambda: state(args[0])[0]['status'] == 'BLOCKED')
        await asyncio.sleep(.3)  # Allow the real recovery monitor to observe native BLOCKED state.
        for _ in range(2):
            phases.append('recovery delivery')
            # Keep the actual native heartbeat advancing between quote polls.
            # A single 12-second clock jump would fabricate a heartbeat outage
            # under this fixture's unchanged ten-second heartbeat bound.
            for _ in range(2):
                at[0] += timedelta(seconds=5)
                await wait_for(lambda: state(args[0])[0]['heartbeat_at'] == at[0].isoformat())
            await deliver()
            await asyncio.sleep(.3)
        phases.append('recovery resume')
        await wait_for(lambda: not state(args[0])[1]['halted'])
        stop.set()

    monkeypatch.setattr(ContinuousFeed, 'run', fixture_collect)
    from app.mixed.connected_runtime import ComponentFailure
    try:
        result = asyncio.run(run(*args, asyncio.Event(), clock_source=lambda: at[0],
            resume_flat_reviewed_revision=revision, max_feed_recoveries=1))
    except ComponentFailure as exc:
        pytest.fail(str((phases, exc.details, observations)))
    assert result['feed_recoveries'] == 1 and result['max_feed_recoveries'] == 1
    assert result['automatic_resume'] is True
    assert state(args[0])[0]['status'] == 'STOPPED'
    assert state(args[0])[1]['halt_reason'] == 'OPTION_RUNTIME_STOPPED'
    with existing_runtime(args[0], clock=lambda: at[0]) as (runtime, _):
        assert not FlatFeedRecovery(1, state(args[0])[0]['generation'], at[0]).observe(runtime, at[0])
        assert state(args[0])[1]['halt_reason'] == 'OPTION_RUNTIME_STOPPED'


@pytest.mark.parametrize('held', [False, True])
def test_native_pending_orders_and_held_positions_cannot_be_resumed(tmp_path, held):
    from types import SimpleNamespace
    from test_portfolio_controls import owned, open_pair, stock
    from test_mixed_native_owner import NOW
    from test_degen_options import frame
    from app.options.coordinator import DegenFrame
    from app.options.runtime_models import RuntimePolicy

    with owned(tmp_path, at=NOW) as (engine, venue):
        if held:
            open_pair(engine, venue)
        else:
            proposal, quote = stock('SPY')
            assert engine.prepare_stock('pending', proposal, quote, now=NOW)['status'] == 'PREPARED'
        at = NOW + timedelta(seconds=2)
        with engine.journal.write() as db:
            engine._halt(db, 'OPTION_RUNTIME_FEED_UNAVAILABLE', at)
        row = {'generation': 1, 'status': 'BLOCKED', 'reason': 'OPTION_RUNTIME_FEED_UNAVAILABLE', 'feed_sequence': 0}
        runtime = SimpleNamespace(c=SimpleNamespace(engine=engine, policy=SimpleNamespace(symbols=('SPY',))),
                                  policy=RuntimePolicy(feed_file='/unused/feed', tick_seconds=.2,
                                                       heartbeat_max_age_seconds=20, feed_max_age_seconds=30),
                                  _bound=lambda db: row)
        recovery = FlatFeedRecovery(1, 1, NOW)
        assert not recovery.observe(runtime, at)
        with engine.journal.read() as db:
            before = engine.journal.revision(db)
        for sequence in (1, 2):
            at += timedelta(seconds=1)
            assert engine.reconcile(venue.snapshot(at), now=at)['reconciled']
            underlying = frame().underlyings[0].model_copy(update={'source_at': at, 'received_at': at})
            row.update(status='RUNNING', reason=None, feed_sequence=sequence, heartbeat_at=at.isoformat(),
                       feed_recorded_at=at.isoformat(), frame_json=DegenFrame(underlyings=(underlying,)).model_dump_json())
            assert not recovery.observe(runtime, at)
        with engine.journal.read() as db:
            assert engine._control(db)['halted']
            assert db.execute("SELECT COUNT(*) FROM execution_events WHERE kind='OPTION_REVIEWED_RESUME' AND sequence>?", (before,)).fetchone()[0] == 0
        assert recovery.used == 0
