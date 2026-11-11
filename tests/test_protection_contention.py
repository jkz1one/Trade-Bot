"""Synthetic contention uses actual history, publication and native owner paths."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

import pytest
from test_robinhood_read_mapping import schemas as schemas
from test_swing_binding import connected
from test_swing_feed import PREOPEN, reader

from app.mixed.continuous_feed import ContinuousFeed
from app.mixed import dashboard_snapshot as display


def test_history_planning_yields_and_excludes_overlapping_capture(tmp_path, schemas, monkeypatch):
    from app.mixed import swing_feed
    settings, policy = connected(tmp_path)
    feed = ContinuousFeed(tmp_path / 'collector', policy, schemas, create=True)
    entered, release = threading.Event(), threading.Event()
    original = swing_feed.planned_history
    def delayed(*args, **kwargs):
        entered.set()
        if not release.wait(2):
            raise TimeoutError('history blocked the loop')
        return original(*args, **kwargs)
    monkeypatch.setattr(swing_feed, 'planned_history', delayed)
    async def exercise():
        task = asyncio.create_task(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert not task.done(), 'History work blocked the event loop'
            assert await feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])) == {'status': 'CAPTURE_IN_PROGRESS'}
        finally:
            release.set()
            await task
        assert feed.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1
        bound = await feed.bind_swing_sources_async(settings, now=PREOPEN+timedelta(seconds=2))
        assert bound == feed.bind_swing_sources(settings, now=PREOPEN+timedelta(seconds=3))
        feed.db.execute("UPDATE attempts SET request_hash=?", ('0'*64,))
        feed.db.commit()
        with pytest.raises(ValueError, match='Stored Swing history binding changed'):
            await feed.bind_swing_sources_async(settings, now=PREOPEN+timedelta(seconds=4))
    try:
        asyncio.run(exercise())
    finally:
        release.set()
        feed.close()


def test_display_projection_releases_native_read_lock(tmp_path, monkeypatch):
    from test_dashboard_snapshot import owner, publisher
    from test_degen_options import AT
    source, _ = owner(tmp_path, positions=True)
    p = publisher(source, tmp_path / 'dashboard')
    entered, release = threading.Event(), threading.Event()
    original = display.copy_display_tables
    def delayed(db):
        db.execute('SELECT MAX(sequence) FROM owner.execution_events').fetchone()
        entered.set()
        assert release.wait(3)
        return original(db)
    monkeypatch.setattr(display, 'copy_display_tables', delayed)
    async def exercise():
        task = asyncio.create_task(asyncio.to_thread(p.publish))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            # A real journal commit must finish while projection is still paused.
            with sqlite3.connect(source / 'options.db', timeout=.1) as db:
                db.execute('INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)',
                           (AT.isoformat(), 'CONCURRENT_NATIVE_COMMIT', '{}'))
            assert not task.done()
        finally:
            release.set()
            await task
    try:
        asyncio.run(exercise())
        with sqlite3.connect(tmp_path / 'dashboard/options.db') as db:
            assert not db.execute("SELECT 1 FROM execution_events WHERE kind='CONCURRENT_NATIVE_COMMIT'").fetchone()
        assert not list((tmp_path / 'dashboard').glob('.source-*'))
    finally:
        release.set()
        p.close()


def test_source_copy_limit_retains_prior_display_and_original_journal(tmp_path, monkeypatch):
    from test_dashboard_snapshot import owner, publisher
    from test_connected_runtime import digest
    source, _ = owner(tmp_path)
    destination = tmp_path / 'dashboard'
    p = publisher(source, destination)
    try:
        p.publish()
        original, published = digest(source), (destination / 'options.db').read_bytes()
        monkeypatch.setattr(display, 'MAX_SOURCE_COPY_BYTES', 1)
        with pytest.raises(ValueError, match='Diagnostic source copy'):
            p.publish()
        assert digest(source) == original and (destination / 'options.db').read_bytes() == published
        assert (destination / '.pending.db').exists()
        assert not list(destination.glob('.source-*'))
    finally:
        p.close()


@pytest.mark.parametrize('failure', [False, True])
def test_cancelled_history_drains_before_lease_release(tmp_path, schemas, monkeypatch, failure):
    settings, policy = connected(tmp_path)
    feed = ContinuousFeed(tmp_path / 'collector', policy, schemas, create=True)
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original = ContinuousFeed.swing_snapshot
    def delayed(self, *args):
        entered.set()
        assert release.wait(3)
        try:
            if failure:
                raise ValueError('synthetic history error')
            return original(self, *args)
        finally:
            done.set()
    monkeypatch.setattr(ContinuousFeed, 'swing_snapshot', delayed)
    async def exercise():
        task = asyncio.create_task(feed.history_read('swing_snapshot', PREOPEN.date()))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(.01)
            assert not task.done() and not done.is_set()
            with pytest.raises(BlockingIOError):
                ContinuousFeed(tmp_path / 'collector', policy, schemas)
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert done.is_set()
    try:
        asyncio.run(exercise())
    finally:
        release.set()
        feed.close()


def test_owned_exit_during_history_model_and_failed_display(tmp_path, schemas, monkeypatch):
    from types import SimpleNamespace
    from decimal import Decimal
    from test_mixed_entry import owner
    from test_mixed_runtime import runtime
    from test_mixed_selection import quote, stock_frame
    from test_mixed_native_owner import changed
    from test_option_runtime import step
    from test_option_position_coordination import management_frame
    from test_degen_options import AT
    from app.execution.economics import UsageEvidence
    from app.mixed.connected_runtime import publication_fault, publish_async
    from app.mixed.portfolio_store import intent
    from app.mixed.sources import StockCycleInput
    from app.options import position_judgment as j
    from app.options.coordinator import DegenFrame
    from app.options.runtime_models import PortfolioRuntimePacket, RuntimeSettings
    from test_paper_session_report import module as reports

    owner_dir = tmp_path / 'owner'
    owner_dir.mkdir(mode=0o700)
    history_settings, history_policy = connected(tmp_path)
    feed = ContinuousFeed(tmp_path / 'collector', history_policy, schemas, create=True)
    asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])))
    feed.bind_swing_sources(history_settings, now=PREOPEN+timedelta(seconds=2))
    history_entered, history_release = threading.Event(), threading.Event()
    display_entered, display_release = threading.Event(), threading.Event()
    history_original = ContinuousFeed.swing_snapshot
    def slow_history(self, *args):
        history_entered.set()
        assert history_release.wait(15)
        return history_original(self, *args)
    monkeypatch.setattr(ContinuousFeed, 'swing_snapshot', slow_history)
    def failed_projection(db):
        db.execute('SELECT MAX(sequence) FROM owner.execution_events').fetchone()
        display_entered.set()
        assert display_release.wait(15)
        raise OSError('synthetic display failure')
    monkeypatch.setattr(display, 'copy_display_tables', failed_projection)
    try:
        with owner(owner_dir, monkeypatch, management=True, portfolio=True,
                   journal_name='options.db') as (c, venue, times, _):
            r = runtime(c, owner_dir)
            settings = RuntimeSettings(limits=c.engine.limits, execution=c.engine.policy,
                setup=c.policy, selection=c.selection, stock_policy=c.stock_policy,
                entry_policy=c.entry_policy, position_policy=c.position_policy,
                judgment_limits=c.judgment_limits, key_file=str(c.key_file), runtime=r.policy)
            path = owner_dir / 'runtime.json'
            path.write_text(settings.model_dump_json())
            path.chmod(0o600)
            sequence = [0]
            def send(frame, kind='MARKET'):
                sequence[0] += 1
                p = PortfolioRuntimePacket(sequence=sequence[0], kind=kind, recorded_at=times[0],
                    population_id=c.engine.limits.population_id,
                    frame=changed(frame, portfolio_version='portfolio-frame-v2'))
                path = Path(r.policy.feed_file)
                path.write_text(p.model_dump_json())
                path.chmod(0o600)
            async def exercise():
                send(stock_frame(), 'CYCLE')
                await step(r)
                with c.engine.journal.read() as db:
                    entry = intent(db.execute('SELECT * FROM execution_portfolio_orders').fetchone())
                times[0] += timedelta(seconds=1)
                venue.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id='stress-entry')
                assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])['reconciled']
                times[0] = AT + timedelta(minutes=5)
                started, finish = asyncio.Event(), asyncio.Event()
                async def delayed(request, _secret):
                    started.set()
                    await finish.wait()
                    return j.result_for(request, plan=j.maintain(request.packet), count=100,
                        usage=UsageEvidence(request_id='stress-management', model=request.configuration.costs.model,
                                            input_tokens=100, output_tokens=20))
                monkeypatch.setattr(j, 'run_position_process', delayed)
                send(changed(management_frame(), stocks=(StockCycleInput(quote=quote(times[0])),)), 'CYCLE')
                await r.tick()
                await asyncio.wait_for(started.wait(), 10)
                p = display.DashboardPublisher(owner_dir, tmp_path / 'dashboard', os.getuid(), os.getgid(),
                                               create=True, clock_source=lambda: times[0])
                history_task = asyncio.create_task(feed.bind_swing_sources_async(history_settings,
                    now=PREOPEN+timedelta(seconds=5)))
                display_task = asyncio.create_task(publish_async(p))
                report_db = reports.connection(owner_dir / 'options.db')
                report_db.execute('SELECT COUNT(*) FROM execution_events').fetchone()
                started_at = time.monotonic()
                try:
                    assert await asyncio.to_thread(history_entered.wait, 2)
                    assert await asyncio.to_thread(display_entered.wait, 2)
                    times[0] += timedelta(seconds=1)
                    send(DegenFrame(stocks=(StockCycleInput(quote=quote(times[0], bid=Decimal(599), ask=Decimal('599.01'))),)))
                    await r.tick()
                    elapsed = time.monotonic() - started_at
                    assert venue.submit_count == 2 and elapsed < 5
                    assert not r.task.done() and not history_task.done() and not display_task.done()
                    display_release.set()
                    with pytest.raises(OSError):
                        await display_task
                    recovery = SimpleNamespace(fenced=False)
                    publication_fault(r, recovery, OSError('synthetic failed projection'), now=times[0], stage='RUNNING')
                    assert recovery.fenced and not r.task.done()
                    # Finish the already-submitted protective exit before advice/history return.
                    with c.engine.journal.read() as db:
                        exit_order = intent(db.execute("SELECT * FROM execution_portfolio_orders WHERE json_extract(intent_json,'$.side')='SELL'").fetchone())
                    times[0] += timedelta(seconds=1)
                    venue.fill_stock(exit_order, exit_order.quantity, quote(times[0], bid=Decimal(599), ask=Decimal('599.01')),
                                     times[0], fill_id='stress-exit')
                    send(DegenFrame(stocks=(StockCycleInput(quote=quote(times[0])),)))
                    await r.tick()
                finally:
                    history_release.set()
                    display_release.set()
                    finish.set()
                    await asyncio.gather(history_task, display_task, r.task, return_exceptions=True)
                    report_db.close()
                    p.close()
                assert venue.submit_count == 2
                with c.engine.journal.read() as db:
                    assert db.execute('SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NULL').fetchone()[0] == 0
                    assert db.execute('SELECT COUNT(*) FROM execution_model_calls').fetchone()[0] == 2
                    result = reports.runtime_timing_evidence(db, AT.isoformat(), times[0].isoformat())
                    assert result['coverage']['models']['matched'] == 2
                    assert result['coverage']['models']['without_matched_trace'] == 0
                from app.mixed.observer import MixedObserver
                view = MixedObserver(owner_dir / 'options.db', settings.limits.population_id,
                                     clock=lambda: times[0], native_journal=True).report(limit=100)
                assert view['status'] == 'OK' and view['accounting'] == 'VERIFIED' and not view['positions']
                assert (tmp_path / 'dashboard/.pending.db').exists()
                assert not list((tmp_path / 'dashboard').glob('.source-*'))
                output = os.environ.get('TRADE_BOT_OFFLINE_PROOF')
                if output:
                    (Path(output) / 'combined-contention.json').write_text(json.dumps({
                        'synthetic': True, 'provider_calls': False, 'model_service_calls': False,
                        'exit_submitted_while_all_waiting': True, 'exit_seconds': elapsed,
                        'report_snapshot_open_during_exit': True,
                        'native_submissions': venue.submit_count, 'accounting': view['accounting'],
                        'held_positions': len(view['positions']), 'runtime_timing': result}, indent=2))
            asyncio.run(exercise())
    finally:
        history_release.set()
        display_release.set()
        feed.close()
