"""Real coordinated loops and local processes with isolated synthetic boundaries.

Synthetic session time advances only at capture boundaries; process deadlines and
loop scheduling use real monotonic time. This is an accelerated integration test,
not a wall-clock soak, a provider latency benchmark, or connected trade evidence.
"""
import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import os
import time
import threading

from fastapi.testclient import TestClient
import pytest

from test_combined_session_feed import combined
from test_contract_catalog import captures as captures
from test_observed_profile_lifecycle import market_reader
from test_option_observer import PASSWORD
from test_robinhood_read_mapping import schemas as schemas
from test_paper_session_report import module as reports

from app.execution.economics import UsageEvidence
from app.mixed import connected_runtime as connected
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.dashboard_reader import create_app
from app.mixed.dashboard_snapshot import DashboardPublisher
from app.mixed.paper_health import evidence
from app.options.engine import fingerprint
from app.options.entry_judgment import result_for
from app.options.entry_reasoning import plan_class
from app.options.runtime_cli import initialize


@pytest.mark.parametrize('read_failure,publication_failure,startup_failure', [(False, False, None), (True, False, None), (False, True, None), (False, False, 'missing'), (False, False, 'pending')])
def test_coordinated_options_lifecycle_restart_publication_and_report(
    tmp_path, captures, schemas, monkeypatch, read_failure, publication_failure, startup_failure
):
    settings, policy = combined(captures)
    owner, feed_dir, dashboard = (tmp_path / p for p in ('owner', 'collector', 'dashboard'))
    key, password = tmp_path / 'synthetic-key', tmp_path / 'password'
    for path, value in ((key, 'offline-never-transmitted'), (password, PASSWORD)):
        path.write_text(value)
        path.chmod(0o600)
    # Separate fixture identity; never create or alter the connected population.
    population = 'offline-system-acceptance'
    raw = settings.model_dump()
    raw['limits']['population_id'] = population
    raw['key_file'] = str(key)
    raw['runtime']['feed_file'] = str(feed_dir / 'feed.json')
    settings = type(settings).model_validate(raw)
    policy = type(policy).model_validate(policy.model_dump() | {'population_id': population})
    now = [datetime(2026, 10, 28, 13, 55, 26, tzinfo=UTC)]
    start = datetime(2026, 10, 28, 14, 0, 26, tzinfo=UTC)
    initialize(owner, settings, clock=lambda: now[0])
    ContinuousFeed(feed_dir, policy, schemas, create=True).close()
    paths = tmp_path / 'policy.json', tmp_path / 'schemas.json'
    for path, value in zip(paths, (policy, schemas)):
        path.write_text(value.model_dump_json())
        path.chmod(0o600)
    # Establish a normally stopped owner through its real startup/shutdown path.
    # Initialization alone is not the reviewed stop used by daily operation.
    with connected.existing_runtime(owner, clock=lambda: now[0]) as (initial, _):
        async def stop_initial():
            stop, ready = asyncio.Event(), asyncio.Event()
            task = asyncio.create_task(initial.run(stop, ready=ready))
            await asyncio.wait_for(ready.wait(), 10)
            stop.set()
            await task
        asyncio.run(stop_initial())
    now[0] = start
    publisher = DashboardPublisher(owner, dashboard, os.getuid(), os.getgid(), create=True,
                                   clock_source=lambda: now[0])
    try:
        publisher.publish()
        binding = publisher.binding
    finally:
        publisher.close()

    inject_publication = threading.Event()
    publish_native = DashboardPublisher.publish
    def broken_publish(self):
        if inject_publication.is_set():
            raise OSError('private synthetic publication failure')
        return publish_native(self)
    monkeypatch.setattr(DashboardPublisher, 'publish', broken_publish)
    models, snapshots, native_times, deliveries = [], [], [], []
    handles, generation, count = {}, [1], [0]
    original_open, original_loop = connected.existing_runtime, ContinuousFeed.run
    from app.options import engine as engine_module
    native_read = engine_module.run_option_process

    async def measured_native(*args, **kwargs):
        before = time.monotonic()
        try:
            return await native_read(*args, **kwargs)
        finally:
            native_times.append(time.monotonic()-before)

    async def model(request, _secret, *, broad):
        models.append(request)
        item = request.packet.opportunities[0]
        stop = item.candidate.proposal.underlying_invalidation
        anchor = item.underlying.ask
        proposal = plan_class(request.packet.policy)(
            decision_id=request.packet.decision_id, packet_hash=fingerprint(request.packet),
            action='ENTER', stock=False, scope=False, candidate_id=item.candidate.candidate_id,
            condition='NOW', underlying_invalidation=stop, underlying_target=anchor+2*(anchor-stop),
            horizon_seconds=600, evidence_ids=item.evidence_ids,
            thesis='Isolated synthetic setup', uncertainty='Fixture response')
        return result_for(request, plan=proposal, count=100, usage=UsageEvidence(
            request_id=f'offline-system-{len(models)}', model=settings.execution.cost_policy.model,
            input_tokens=100, output_tokens=20))

    @contextmanager
    def open_runtime(*args, **kwargs):
        with original_open(*args, **kwargs) as pair:
            handles['runtime'] = pair[0]
            pair[0].c._model_run = model
            yield pair

    async def forbidden(*args, **kwargs):
        pytest.fail('External provider/model boundary reached by offline harness')

    async def offline_loop(self, stop, **kwargs):
        previous = [None]
        async def capture(capture_policy, **request):
            runtime = handles['runtime']
            # Backpressure at the external fixture boundary, without replacing
            # collector/run/tick, runtime/run/tick, supervision or publication.
            async with asyncio.timeout(30):
                if previous[0] is not None:
                    while True:
                        with runtime.c.engine.journal.read() as db:
                            row = runtime._bound(db)
                            ready = row['feed_sequence'] >= previous[0]
                            halted = bool(runtime.c.engine._control(db)['halted'])
                        protection_done = runtime._scope_tick is None or runtime._scope_tick.done()
                        if ready and protection_done and (runtime.task is None or runtime.task.done()) and (
                                count[0] > 1 or not halted):
                            break
                        await asyncio.sleep(.02)
            snap = runtime.c.engine.venue.snapshot(now[0])
            symbols = {p.contract.underlying for p in snap.positions.values()}
            if publication_failure and generation[0] == 1 and len(symbols) == 2:
                inject_publication.set()
                async with asyncio.timeout(12):
                    while getattr(runtime, 'entry_fault', None) is None:
                        assert not stop.is_set()
                        await asyncio.sleep(.02)
                assert runtime.entry_fault == 'CONNECTED_PUBLICATION_FAILED'
                assert not stop.is_set()
                with runtime.c.engine.journal.read() as db:
                    assert runtime.c.engine._control(db)['halted']
            exit_symbol = 'QQQ'  if generation[0] == 2 else 'SPY' if len(models) >= 2 else None
            if (generation[0] == 1 and len(models) == 2 and symbols == {'QQQ'}
                    or generation[0] == 2 and not symbols):
                stop.set()
            at = now[0]
            count[0] += 1
            if count[0] > 65:
                pytest.fail('Integrated lifecycle made no progress')
            if read_failure and count[0] == 3:
                now[0] += timedelta(seconds=10)
                raise TimeoutError('Isolated capture failure')
            result = await market_reader(at+timedelta(seconds=9), policy,
                                         exit_symbol=exit_symbol)(capture_policy, **request)
            result = result.model_copy(update={'started_at': at, 'elapsed_seconds': 10})
            now[0] = result.collected_at
            previous[0] = self.db.execute('SELECT MAX(sequence) FROM attempts').fetchone()[0]
            deliveries.append(previous[0])
            return result
        return await original_loop(self, stop, **kwargs, reader=capture)

    monkeypatch.setattr(connected, 'existing_runtime', open_runtime)
    monkeypatch.setattr(ContinuousFeed, 'run', offline_loop)
    monkeypatch.setattr(engine_module, 'run_option_process', measured_native)
    monkeypatch.setattr('app.options.read_capture._collect_owned', forbidden)
    monkeypatch.setattr('app.options.position_judgment.run_position_process', forbidden)
    monkeypatch.setattr('app.options.entry_judgment.run_entry_process', forbidden)
    args = owner, feed_dir, *paths

    async def session(resume):
        stop = asyncio.Event()
        app = create_app(dashboard, binding, str(password), clock_source=lambda: now[0],
                         allow_degraded=True)
        task = asyncio.create_task(connected.run(*args, stop, clock_source=lambda: now[0],
            snapshot_directory=dashboard, reader_uid=os.getuid(), reader_gid=os.getgid(),
            resume_flat_reviewed_revision=resume, max_feed_recoveries=2 if resume is not None else 0))
        def inspect_dashboard():
            with TestClient(app) as client:
                assert client.get('/api/mixed').status_code == 401
                client.auth = ('trader', PASSWORD)
                r = client.get('/api/mixed')
                if r.status_code == 200:
                    snapshots.append(r.json()['fill_count'])
                else:
                    assert r.status_code == 503  # Advancing replay can outrun a display.
        try:
            async with asyncio.timeout(150):
                while not task.done():
                    await asyncio.to_thread(inspect_dashboard)
                    await asyncio.sleep(.5)
                return await task
        finally:
            stop.set()
            await asyncio.gather(task, return_exceptions=True)

    revision = connected.check(*args, clock_source=lambda: now[0])[0]['owner_state']['owner_revision']
    if publication_failure:
        with pytest.raises(connected.ComponentFailure, match='PUBLISHER') as caught:
            asyncio.run(session(revision))
        assert any(d['component'] == 'PUBLISHER' for d in caught.value.details)
        intermediate = reports.report(tmp_path, start.isoformat(), now[0].isoformat())
        assert intermediate['run_execution']['entry_fills'] == 2
        assert intermediate['run_execution']['exit_fills'] == 1
        assert intermediate['publication_failures']
        assert 'private synthetic' not in json.dumps(intermediate)
        inject_publication.clear()  # Explicit repair in this disposable fixture only.
    else:
        first = asyncio.run(session(revision))
        assert first['status'] == 'STOPPED'
    assert len(models) == 2 and native_times and snapshots
    generation[0] = 2
    if startup_failure:
        damaged = dashboard / ('options.db' if startup_failure == 'missing' else '.pending.db')
        if startup_failure == 'missing':
            damaged.unlink()
        else:
            damaged.write_bytes(b'original failed publication')
        before_display = {p.name: p.read_bytes() for p in dashboard.iterdir() if p.is_file()}
        _, enrolled_settings, _, _, observer = connected.check(*args, clock_source=lambda: now[0])
        reviewed, error = connected.dashboard_preflight(owner, dashboard, os.getuid(), os.getgid(),
            observer, enrolled_settings, clock_source=lambda: now[0])
        assert reviewed['startup_mode'] == 'PROTECTION_ONLY' and reviewed['held_plays'] == 1
        assert error is not None
        with pytest.raises(connected.ComponentFailure, match='PUBLISHER') as failed:
            asyncio.run(session(None))
        assert failed.value.details[0]['stage'] == 'STARTUP'
        assert {p.name: p.read_bytes() for p in dashboard.iterdir() if p.is_file()} == before_display
        # Only this isolated fixture is explicitly repaired after the protected exit.
        if startup_failure == 'pending':
            damaged.unlink()
        repair = DashboardPublisher(owner, dashboard, os.getuid(), os.getgid(), clock_source=lambda: now[0])
        try:
            repair.publish()
        finally:
            repair.close()
    else:
        second = asyncio.run(session(None))
        assert second['status'] == 'STOPPED'
    assert len(models) == 2
    report = reports.report(tmp_path, start.isoformat(), now[0].isoformat())
    freshness = report['entry_freshness']
    assert freshness['status'] == 'OBSERVED' and freshness['measured'] == freshness['reservations'] == 2
    assert all(v['samples'] == 2 for v in freshness['clocks'].values())
    assert report['run_execution'] == dict(status='RECORDED', entry_fills=2, exit_fills=2,
                                         completed_round_trips=2, carry_in_exits=0)
    assert report['account_total_fills'] == 4
    timings = report['runtime_timing']
    assert timings['measured'] and not timings['missing_or_invalid']
    assert {'TICK', 'CYCLE', 'SCAN', 'ENTRY_MODEL', 'ADMISSION', 'DISPATCH', 'NATIVE_SNAPSHOT', 'NATIVE_ACCEPT'} <= set(timings['phases'])
    assert timings['execution_quote_clocks']['quote_age_seconds']['max_seconds'] < 10
    assert timings['native_observed_intervals']['SNAPSHOT']['samples']
    assert all(t['collector_binding'] == 'MATCHED' for t in timings['recent'] if t['packet_sequence'] is not None)
    with __import__('sqlite3').connect(owner / 'options.db') as db:
        traces = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM execution_runtime_timings')]
        for trace in traces:
            if trace['packet_sequence'] is not None:
                original = db.execute('SELECT packet_hash FROM execution_mixed_runtime_inputs WHERE sequence=?',
                                      (trace['packet_sequence'],)).fetchone()
                assert original[0] == trace['packet_sha256']
        assert {t['generation'] for t in traces} >= {2, 3}
    assert report['collection_timing']['measured'] == count[0]
    failed = sum(r['attempts'] for r in report['collection'] if r['status'] == 'FAILED')
    assert failed == int(read_failure)
    # Exercise the actual controller/report boundary against a simulated Docker
    # result. This deliberately short fixture is not a completed daily session.
    from test_paper_daily import Fake, daily
    report.update(run_id='daily-20261028', session_timing={
        'planned_seconds': 3600, 'elapsed_seconds': (now[0]-start).total_seconds()})
    worker_state = {'Status': 'exited', 'ExitCode': 0}
    report['operation'] = reports.operation(report, worker_state)
    backend = Fake()
    backend.item = {'Id':'offline-container', 'State':worker_state}
    backend.reported = report
    controller = {'days':{'2026-10-28':{'run_id':report['run_id'],
        'launch_attempted':True, 'container_id':'offline-container'}}}
    monkeypatch.setattr(daily, 'stamp', lambda: now[0])
    daily.tick(controller, backend, lambda _: None, now[0])
    assert controller['status'] == 'FAILED'
    assert controller['days']['2026-10-28']['done']
    assert controller['days']['2026-10-28']['run_execution'] == report['run_execution']
    health = evidence(controller, report, observed_at=now[0].isoformat(),
                      binding_hash=fingerprint(binding))
    path = dashboard / 'paper-status.json'
    path.write_text(json.dumps(health))
    path.chmod(0o444)
    app = create_app(dashboard, binding, str(password), clock_source=lambda: now[0])
    with TestClient(app) as client:
        client.auth = ('trader', PASSWORD)
        operation = client.get('/desk/operation')
        expected_message = 'Account display failed' if publication_failure or startup_failure else 'worker stopped early'
        assert operation.status_code == 200 and expected_message in operation.text
        account = client.get('/api/mixed').json()
        assert account['fill_count'] == 4 and not account['positions']
        assert account['accounting'] == 'VERIFIED'
    assert not report['provider_calls'] and not report['live_enabled']
    output = os.environ.get('TRADE_BOT_OFFLINE_PROOF')
    if output:
        from pathlib import Path
        evidence_path = Path(output) / (('system-startup-'+startup_failure+'.json') if startup_failure else 'system-with-publisher-failure.json' if publication_failure else 'system-with-read-failure.json' if read_failure else 'system-normal.json')
        evidence_path.write_text(json.dumps({'synthetic': True, 'market_acceptance': False,
            'native_process_calls': len(native_times), 'native_process_max_seconds': max(native_times),
            'dashboard_reads': len(snapshots), 'capture_attempts': count[0], 'report': report}, indent=2))
