"""A transient feed fault must not spend an otherwise unclaimed current slot."""
import asyncio
from datetime import datetime, timedelta

import pytest
from test_connected_runtime import enrolled, state
from test_portfolio_feed import reader
from test_robinhood_read_mapping import AT, schemas as schemas  # noqa: F401

from app.mixed.connected_runtime import FlatFeedRecovery, resume_flat
from app.mixed.continuous_feed import ContinuousFeed
from app.options.runtime_cli import existing_runtime
from app.robinhood.schedule import XNYSCalendar


def capture_at(at):
    """Synthetic complete five-minute originals; never used as host evidence."""
    from test_robinhood_read_mapping import envelope, history
    base = reader(at, [], source_shift=int((at-AT).total_seconds()))
    async def capture(*args, **kwargs):
        result = await base(*args, **kwargs)
        template = history()[1]['structuredContent']['data']['results'][0]['bars'][0]
        for call, row in zip(result.plan.calls, result.observations):
            if call.tool == 'get_equity_historicals':
                start, end = (datetime.fromisoformat(call.arguments[k]) for k in ('start_time','end_time'))
                row['raw'] = envelope([{'symbol':s,'interval':'5minute','bounds':'regular',
                    'bars':[dict(template,begins_at=(start+timedelta(minutes=5*n)).isoformat())
                            for n in range(int((end-start).total_seconds())//300)]}
                    for s in call.arguments['symbols']])
            elif call.tool == 'get_option_quotes':
                for item in row['raw']['structuredContent']['data']['results']:
                    item['quote']['updated_at'] = at.isoformat()
        return result
    return capture


def test_native_startup_and_mid_slot_recovery_deliver_fresh_cycle_once(tmp_path, schemas):
    args, _, policy = enrolled(tmp_path, schemas)
    at = [AT + timedelta(minutes=30)]
    with existing_runtime(args[0], clock=lambda: at[0]) as (runtime, _):
        feed = ContinuousFeed(args[1], policy, schemas)
        feed.cycle_needed = runtime.needs_cycle
        async def delivered():
            outcome = await feed.tick(now=at[0], window=XNYSCalendar().current_window(at[0]), reader=capture_at(at[0]))
            assert outcome['status'] == 'DELIVERED', outcome
            outcome['kind'] = feed.db.execute("SELECT json_extract(packet_json,'$.kind') FROM attempts WHERE sequence=?",
                                              (outcome['sequence'],)).fetchone()[0]
            at[0] += timedelta(seconds=2)
            await runtime.tick()
            if runtime.task:
                await runtime.task
            return outcome
        async def exercise():
            runtime.running = True
            await runtime.tick()  # First-tick readiness precedes collection.
            with runtime.c.engine.journal.read() as db:
                assert db.execute('SELECT status FROM execution_option_runtime_slots ORDER BY slot DESC LIMIT 1').fetchone()[0] == 'WAITING_FOR_FEED'
            assert (await delivered())['kind'] == 'MARKET'
            resume_flat(runtime.c.engine, at[0], fresh_startup_feed=True)
            at[0] += timedelta(seconds=10)
            assert (await delivered())['kind'] == 'CYCLE'
            await runtime.tick()
            with runtime.c.engine.journal.read() as db:
                assert db.execute('SELECT COUNT(*) FROM execution_option_opportunities').fetchone()[0] == 1
            # Later window: outage first, two real advancing accepted MARKET
            # packets, bounded native recovery, then fresh original CYCLE inputs.
            at[0] = AT + timedelta(minutes=35)
            await runtime.tick()
            recovery = FlatFeedRecovery(1, 0, AT)
            assert not recovery.observe(runtime, at[0])
            for n in range(2):
                assert (await delivered())['kind'] == 'MARKET'
                assert recovery.observe(runtime, at[0]) is (n == 1)
                at[0] += timedelta(seconds=10)
            assert recovery.used == 1
            assert (await delivered())['kind'] == 'CYCLE'
            await runtime.tick()
            with runtime.c.engine.journal.read() as db:
                assert db.execute('SELECT COUNT(*) FROM execution_option_opportunities').fetchone()[0] == 2
                assert db.execute("SELECT COUNT(*) FROM execution_option_runtime_slots WHERE status='COMPLETE'").fetchone()[0] == 2
                assert db.execute('SELECT COUNT(*) FROM execution_model_calls').fetchone()[0] == 0
                assert db.execute('SELECT COUNT(*) FROM execution_portfolio_orders').fetchone()[0] == 0
            at[0] += timedelta(seconds=10)
            assert (await delivered())['kind'] == 'MARKET'
        try:
            asyncio.run(exercise())
        finally:
            feed.close()


def test_strategy_attempt_cap_survives_restart_without_counting_market_polls(tmp_path, schemas):
    args, _, policy = enrolled(tmp_path, schemas)
    feed = ContinuousFeed(args[1], policy, schemas)
    at = [AT + timedelta(minutes=30)]
    async def poll(wanted, fail=False):
        feed.cycle_needed = lambda _: wanted
        async def failed(*args, **kwargs):
            raise TimeoutError('synthetic original timeout')
        result = await feed.tick(now=at[0], window=XNYSCalendar().current_window(at[0]),
                                 reader=failed if fail else capture_at(at[0]))
        if result['status'] == 'DELIVERED':
            result['kind'] = feed.db.execute("SELECT json_extract(packet_json,'$.kind') FROM attempts WHERE sequence=?",
                                             (result['sequence'],)).fetchone()[0]
        at[0] += timedelta(seconds=10)
        return result
    try:
        for _ in range(4):
            assert asyncio.run(poll(False))['kind'] == 'MARKET'
        assert asyncio.run(poll(True, fail=True))['status'] == 'FAILED'
        for _ in range(2):
            assert asyncio.run(poll(True))['kind'] == 'CYCLE'
        feed.close()
        feed = ContinuousFeed(args[1], policy, schemas)
        assert asyncio.run(poll(True))['kind'] == 'MARKET'
        assert feed.db.execute('SELECT SUM(requested) FROM cycle_requests').fetchone()[0] == 3
    finally:
        feed.close()


@pytest.mark.parametrize('status', ['COMPLETE', 'SKIPPED', 'INTERRUPTED', 'STARTED'])
def test_terminal_or_started_slots_never_request_or_replay_strategy(tmp_path, schemas, status):
    args, _, policy = enrolled(tmp_path, schemas)
    at = [AT]
    with existing_runtime(args[0], clock=lambda: at[0]) as (runtime, _):
        runtime.running = True
        with runtime.c.engine.journal.write() as db:
            db.execute("UPDATE execution_option_runtime SET status='RUNNING',reason=NULL")
            db.execute('INSERT INTO execution_option_runtime_slots VALUES(?,?,?,?,?,?)',
                       (int(AT.timestamp())//300, AT.date().isoformat(), status, None, AT.isoformat(), AT.isoformat()))
        assert not runtime.needs_cycle(AT)
        feed = ContinuousFeed(args[1], policy, schemas)
        try:
            asyncio.run(feed.tick(now=AT, reader=reader(AT, [])))
            at[0] += timedelta(seconds=2)
            asyncio.run(runtime.tick())
            assert runtime.task is None
            with runtime.c.engine.journal.read() as db:
                assert db.execute('SELECT COUNT(*) FROM execution_option_opportunities').fetchone()[0] == 0
        finally:
            feed.close()


def test_waiting_slot_expires_without_replaying_in_next_window(tmp_path, schemas):
    args, _, policy = enrolled(tmp_path, schemas)
    at = [AT]
    with existing_runtime(args[0], clock=lambda: at[0]) as (runtime, _):
        runtime.running = True
        asyncio.run(runtime.tick())
        at[0] += timedelta(minutes=5)
        asyncio.run(runtime.tick())
        with runtime.c.engine.journal.read() as db:
            rows = db.execute('SELECT slot,status FROM execution_option_runtime_slots WHERE slot>=? ORDER BY slot',
                              (int(AT.timestamp())//300,)).fetchall()
            assert [r['status'] for r in rows] == ['SKIPPED', 'WAITING_FOR_FEED']
        assert state(args[0])[1]['halted']
