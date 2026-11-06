"""Offline daily operation, at-most-once launch, and failure/restart boundaries."""
import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.mixed.daily_plan import inspect, schedule
from test_connected_runtime import digest, enrolled
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: F401

spec = importlib.util.spec_from_file_location('paper_daily_test', Path(__file__).parents[1] / 'scripts/paper-daily.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


def dt(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize('now,target,start,close,expiry', [
    ('2026-11-06T22:00:00', '2026-11-09', '2026-11-09T15:00:00+00:00', '2026-11-09T21:00:00+00:00', '2026-11-20'),
    ('2026-11-07T16:00:00', '2026-11-09', '2026-11-09T15:00:00+00:00', '2026-11-09T21:00:00+00:00', '2026-11-20'),
    ('2026-11-26T14:00:00', '2026-11-27', '2026-11-27T15:00:00+00:00', '2026-11-27T18:00:00+00:00', '2026-12-04'),
    ('2026-10-30T13:00:00', '2026-10-30', '2026-10-30T14:00:00+00:00', '2026-10-30T20:00:00+00:00', '2026-11-06'),
])
def test_calendar(now, target, start, close, expiry):
    result = schedule(dt(now))
    assert (result['target_session'], result['start_at'], result['close_at'], result['swing_expiration']) == (target, start, close, expiry)


def test_info_has_no_credentials_or_mutations(tmp_path, schemas, monkeypatch):
    args, _, _ = enrolled(tmp_path, schemas)
    before = digest(tmp_path)
    monkeypatch.setattr('app.mixed.connected_runtime.existing_runtime', lambda *a, **k: pytest.fail('owner write'))
    result = inspect(*args, now=AT)
    assert result['status'] == 'DAILY_INFO'
    assert result['live_enabled'] is False and result['provider_calls'] is False
    assert result['receipt'] is None
    assert 'DAILY_PROFILE_MISMATCH' in result['start_blockers']  # Replay fixture is never enabled.
    assert digest(tmp_path) == before


def test_verified_rollover_reconstructs_receipt_without_reenrollment(tmp_path, schemas):
    from test_feed_rollover import prepared, review, apply
    from app.options.engine import fingerprint

    args, _, _, policy = prepared(tmp_path, schemas)
    reviewed = review(args)
    apply(args, reviewed)
    before = digest(tmp_path)
    result = inspect(*args[:4], now=dt('2026-10-26T13:00:00'))
    assert result['receipt']['policy_sha256'] == fingerprint(policy)
    assert result['receipt']['session_review_sha256'] == reviewed['review_sha256']
    assert result['receipt']['target_session'] == '2026-10-26'
    assert digest(tmp_path) == before


class Fake:
    def __init__(self):
        self.config = {'image_id': 'pinned'}
        self.plan = {**schedule(dt('2026-11-09T14:00:00')),
                     'start_blockers': [], 'automatic_catalog_blockers': [],
                     'swing_history_enrolled': True, 'receipt': None, 'last_runtime_started_at': None}
        self.on = True
        self.calls = []
        self.item = None
        self.running = []
        self.error = None
        self.reported = {'operation': {'state': 'WAITING_FOR_SETUP', 'reasons': ['NO_CONFIRMED_SETUP']},
                         'account_total_fills': 0}

    def enabled(self):
        return self.on

    def verify(self):
        self.calls.append('verify')
        if self.error == 'verify':
            raise ValueError('SCHEDULE_RELEASE_CHANGED_REINSTALL_REQUIRED')

    def active(self):
        return self.running

    def info(self):
        self.calls.append('info')
        return self.plan

    def invoke(self, args):
        self.calls.append(args)
        if self.error == 'capture':
            raise RuntimeError('capture failed')
        return {'evidence_directory': '/original/' + args[-1]}

    def prepare(self, day, info):
        self.calls.append('prepare')
        self.plan['receipt'] = {'target_session': info['target_session'], 'policy_sha256': 'a' * 64,
                                'live_enabled': False}
        if self.error == 'after_enroll':
            raise RuntimeError('receipt save interrupted')

    def preopen(self, target):
        self.calls.append('preopen')
        return {'status': 'PREOPEN_INPUTS_BLOCKED', 'reason': 'INTERPOLATED_BAR'}

    def launch(self, day, info, now):
        self.calls.append('launch')
        self.item = {'Id': 'b' * 64, 'State': {'Status': 'running', 'ExitCode': 0}}
        if self.error == 'after_launch':
            raise RuntimeError('connection lost')
        return {'container_id': self.item['Id']}

    def container(self, run_id, *, image_id=None):
        return self.item

    def stop(self, run_id, identity, *, image_id=None):
        assert identity == self.item['Id']
        self.calls.append(('stop', run_id, identity))
        self.item['State']['Status'] = 'exited'

    def report(self, run_id):
        self.calls.append('report')
        return self.reported


def advance(state, backend, now='2026-11-09T14:00:00'):
    saved = []
    daily.tick(state, backend, lambda s: saved.append(copy.deepcopy(s)), dt(now))
    return saved


def ready(backend):
    backend.plan['receipt'] = {'target_session': '2026-11-09', 'policy_sha256': 'a' * 64, 'live_enabled': False}


def test_full_daily_preparation_start_monitor_finish_and_next_session():
    f, state = Fake(), {}
    for _ in range(3):
        saved = advance(state, f)
        assert saved[0]['days']['2026-11-09']['failures'] == 1
    assert f.calls.count('prepare') == 1
    assert [c[-1] for c in f.calls if isinstance(c, list)] == ['2026-11-09', '2026-11-20']
    advance(state, f)
    assert state['days']['2026-11-09']['preopen']['reason'] == 'INTERPOLATED_BAR'
    advance(state, f)
    assert f.calls.count('preopen') == 1
    assert state['status'] == 'READY'
    saved = advance(state, f, '2026-11-09T15:00:00')
    assert saved[-1]['days']['2026-11-09']['launch_attempted'] is True
    advance(state, f, '2026-11-09T15:01:00')
    assert state['status'] == 'WAITING_FOR_SETUP'
    assert f.calls.count('launch') == 1
    f.item['State']['Status'] = 'exited'
    f.reported['operation'] = {'state': 'STOPPED', 'reasons': ['BOUNDED_SESSION_ENDED']}
    advance(state, f, '2026-11-09T20:59:00')
    assert state['days']['2026-11-09']['done']
    f.plan.update(schedule(dt('2026-11-09T22:00:00')), receipt=None)
    advance(state, f, '2026-11-09T22:00:00')
    assert state['status'] == 'WAITING_NEXT_SESSION'
    assert state['schedule']['target_session'] == '2026-11-10'


def test_existing_monday_enrollment_reused_without_capture_or_enroll():
    f, state = Fake(), {}
    ready(f)
    advance(state, f, '2026-11-09T15:00:00')
    assert f.calls == ['verify', 'info', 'launch']


@pytest.mark.parametrize('error', ['after_enroll', 'after_launch'])
def test_lost_response_adopts_durable_enrollment_or_container(error):
    f, state = Fake(), {}
    f.error = error
    if error == 'after_enroll':
        advance(state, f)
        advance(state, f)
        with pytest.raises(RuntimeError):
            advance(state, f)
        f.error = None
        advance(state, f, '2026-11-09T15:00:00')
        assert f.calls.count('prepare') == 1
    else:
        ready(f)
        with pytest.raises(RuntimeError):
            advance(state, f, '2026-11-09T15:00:00')
        f.error = None
        advance(state, f, '2026-11-09T15:01:00')
    assert f.calls.count('launch') == 1


def test_retry_reservations_survive_restart_and_bound_capture_failure():
    f, state = Fake(), {}
    f.error = 'capture'
    for count in range(1, 4):
        with pytest.raises(RuntimeError):
            advance(state, f)
        state = copy.deepcopy(state)
        assert state['days']['2026-11-09']['failures'] == count
    advance(state, f)
    assert state['reasons'][0] == 'PREPARATION_RETRY_LIMIT'
    assert len([c for c in f.calls if isinstance(c, list)]) == 3


@pytest.mark.parametrize('blocker', ['EXISTING_HOLDINGS_OR_UNRESOLVED_ORDERS', 'MODEL_COST_OR_EVIDENCE_UNRESOLVED',
    'MODEL_TOTAL_BUDGET_EXHAUSTED', 'OWNER_NOT_NORMALLY_STOPPED', 'OWNER_HALT_REQUIRES_REVIEW'])
def test_owner_blockers_prevent_mutation(blocker):
    f, state = Fake(), {}
    f.plan['start_blockers'] = [blocker]
    advance(state, f)
    assert state['status'] == 'MISSING_INPUTS' and state['reasons'] == [blocker]
    assert f.calls == ['verify', 'info']


def test_scope_or_carry_requires_exact_binding_without_silent_drop():
    f, state = Fake(), {}
    f.plan['automatic_catalog_blockers'] = ['EXACT_SESSION_BINDINGS_REQUIRED']
    advance(state, f)
    assert state['reasons'] == ['EXACT_SESSION_BINDINGS_REQUIRED']
    ready(f)
    advance(state, f, '2026-11-09T15:00:00')
    assert 'launch' in f.calls


def test_no_manual_worker_interference_or_second_run_after_manual_session():
    f, state = Fake(), {}
    f.running = ['trade-bot-connected-manual']
    advance(state, f)
    assert f.calls == ['verify']
    assert state['reasons'] == ['EXISTING_MANUAL_WORKER']
    f.running = []
    f.plan['last_runtime_started_at'] = '2026-11-09T15:00:00+00:00'
    advance(state, f, '2026-11-09T16:00:00')
    assert state['reasons'] == ['SESSION_ALREADY_RUN_TODAY']
    assert 'launch' not in f.calls


@pytest.mark.parametrize('when,reason', [('2026-11-09T20:46:00', 'TOO_LATE_TO_START')])
def test_no_late_launch(when, reason):
    f, state = Fake(), {}
    ready(f)
    advance(state, f, when)
    assert state['reasons'] == [reason]


def test_no_after_hours_preparation_and_cached_wait():
    f, state = Fake(), {}
    f.plan.update(schedule(dt('2026-11-06T22:00:00')))
    advance(state, f, '2026-11-06T22:00:00')
    advance(state, f, '2026-11-07T22:00:00')
    assert state['status'] == 'WAITING_NEXT_SESSION'
    assert f.calls.count('info') == 1
    assert 'launch' not in f.calls


@pytest.mark.parametrize('kind', ['pause', 'close'])
def test_exact_identity_stop_and_no_restart(kind):
    f, state = Fake(), {}
    ready(f)
    advance(state, f, '2026-11-09T15:00:00')
    f.on = kind != 'pause'
    advance(state, f, '2026-11-09T21:00:00' if kind == 'close' else '2026-11-09T15:01:00')
    assert f.calls[-1] == ('stop', 'daily-20261109', 'b' * 64)
    advance(state, f, '2026-11-09T21:01:00')
    advance(state, f, '2026-11-09T21:02:00')
    assert f.calls.count('launch') == 1
    assert state['status'] == ('PAUSED' if kind == 'pause' else 'FAILED')


def test_uncertain_launch_never_retried_even_on_next_date():
    f, state = Fake(), {}
    ready(f)
    advance(state, f, '2026-11-09T15:00:00')
    f.item = None
    advance(state, f, '2026-11-09T15:01:00')
    assert state['status'] == 'FAILED'
    f.plan.update(schedule(dt('2026-11-10T15:00:00')))
    advance(state, f, '2026-11-10T15:00:00')
    assert state['reasons'] == ['LAUNCH_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY']
    assert f.calls.count('launch') == 1


def test_replaced_container_never_stopped():
    f, state = Fake(), {}
    ready(f)
    advance(state, f, '2026-11-09T15:00:00')
    f.item['Id'] = 'c' * 64
    f.on = False
    with pytest.raises(ValueError, match='IDENTITY_CHANGED'):
        advance(state, f, '2026-11-09T15:01:00')
    assert not any(isinstance(c, tuple) for c in f.calls)


def test_release_change_blocks_all_preparation():
    f, state = Fake(), {}
    f.error = 'verify'
    with pytest.raises(ValueError, match='RELEASE_CHANGED'):
        advance(state, f)
    assert f.calls == ['verify']


def test_units_survive_disconnect_use_calendar_and_have_no_worker_restart():
    units = daily.units(Path('/opt/trade-bot-dashboard'))
    assert 'OnCalendar=*-*-* *:*:00' in units[daily.UNIT + '.timer']
    assert 'Persistent=true' in units[daily.UNIT + '.timer']
    assert 'Type=oneshot' in units[daily.UNIT + '.service']
    assert 'Restart=' not in units[daily.UNIT + '.service']
    with pytest.raises(ValueError):
        daily.units(Path('/opt/inject\nUnit=bad'))


def test_backend_launch_has_close_bound_and_same_prepared_policy(monkeypatch, tmp_path):
    calls = []
    backend = daily.Backend({'max_feed_recoveries': 2}, tmp_path)
    monkeypatch.setattr(daily, 'stamp', lambda: dt('2026-11-09T15:00:02'))
    def invoke(args):
        calls.append(args)
        if args[0] == 'review-run':
            return {'degen_option_configuration_ready': True, 'live_enabled': False,
                    'binding': {'policy_sha256': 'a' * 64, 'max_feed_recoveries': 2},
                    'review_sha256': 'd' * 64}
        return {'container_id': 'b' * 64}
    monkeypatch.setattr(backend, 'invoke', invoke)
    result = backend.launch({'run_id': 'daily-20261109', 'receipt': {
        'target_session': '2026-11-09', 'policy_sha256': 'a' * 64}},
        schedule(dt('2026-11-09T15:00:00')), dt('2026-11-09T15:00:00'))
    assert result['container_id'] == 'b' * 64
    assert calls[-1] == ['run', '--run-id', 'daily-20261109', '--seconds', '21480',
                         '--resume-flat', '--max-feed-recoveries', '2', '--expected-review', 'd' * 64]
    monkeypatch.setattr(daily, 'stamp', lambda: dt('2026-11-09T15:02:01'))
    with pytest.raises(ValueError, match='WINDOW_EXPIRED'):
        backend.launch({'run_id': 'daily-20261109', 'receipt': {
            'target_session': '2026-11-09', 'policy_sha256': 'a' * 64}},
            schedule(dt('2026-11-09T15:00:00')), dt('2026-11-09T15:00:00'))


def test_atomic_state_retains_pause_across_install(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(daily, 'HOME', tmp_path)
    unit_home = tmp_path / 'units'
    unit_home.mkdir()
    monkeypatch.setattr(daily, 'UNIT_HOME', unit_home)
    monkeypatch.setattr(daily.host, 'no_active_session', lambda: None)
    monkeypatch.setattr(daily.host, 'image', lambda release: 'sha256:' + 'b' * 64)
    monkeypatch.setattr(daily.host.h, 'command', lambda args: SimpleNamespace(stdout='a' * 40 if args[1] == 'rev-parse' else ''))
    monkeypatch.setattr(daily.Backend, 'info', lambda self: {**Fake().plan, 'start_blockers': []})
    monkeypatch.setattr(daily.Backend, 'enabled', lambda self: not (tmp_path / 'paused.json').exists())
    commands = []
    monkeypatch.setattr(daily.subprocess, 'run', lambda args, **k: commands.append(args))
    daily.save(tmp_path / 'paused.json', {'requested_at': 'before upgrade'})
    first = daily.install()
    second = daily.install()
    assert first['paused'] and second['paused'] and second['updated']
    assert daily.read(tmp_path / 'paused.json')['requested_at'] == 'before upgrade'
    assert commands[-1] == ['systemctl', 'enable', '--now', daily.UNIT + '.timer']
    (unit_home / (daily.UNIT + '.timer')).write_text('foreign unit')
    with pytest.raises(ValueError, match='UNMANAGED'):
        daily.install()


def test_daily_info_host_uses_installed_image_readonly_without_auth(monkeypatch):
    seen = []
    monkeypatch.setattr(daily.host, 'image', lambda release: 'pinned-image')
    monkeypatch.setattr(daily.host, 'bundle', lambda image: seen.append(('bundle', image)))
    monkeypatch.setattr(daily.host, 'config_mounts', lambda **k: ['readonly-state'])
    monkeypatch.setattr(daily.host, 'execute', lambda *args: seen.append(args) or {'status': 'DAILY_INFO'})
    result = daily.host.run(SimpleNamespace(operation='daily-info'), 'a' * 40)
    assert result['status'] == 'DAILY_INFO'
    assert seen[-1] == ('pinned-image', 'app.mixed.daily_plan', [
        '--directory', '/state/owner', '--feed-directory', '/state/collector',
        '--policy', '/state/config/policy.json', '--schemas', '/state/config/schemas.json'], ['readonly-state'])


def test_explicit_resume_preserves_same_day_launch_guard(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(daily, 'HOME', tmp_path)
    daily.save(tmp_path / 'config.json', {'release': 'a' * 40})
    daily.save(tmp_path / 'paused.json', {'requested_at': 'earlier'})
    daily.save(tmp_path / 'state.json', {'attention': 'SESSION_STOPPED_REVIEW_REQUIRED',
               'days': {'2026-11-09': {'launch_attempted': True, 'done': True}}})
    monkeypatch.setattr(daily.Backend, 'verify', lambda self: None)
    monkeypatch.setattr(daily.Backend, 'active', lambda self: [])
    monkeypatch.setattr(daily.Backend, 'info', lambda self: {'start_blockers': ['OWNER_HALT_REQUIRES_REVIEW']})
    with pytest.raises(ValueError, match='NORMALLY_STOPPED'):
        daily.main(['resume'])
    assert (tmp_path / 'paused.json').exists()
    monkeypatch.setattr(daily.Backend, 'info', lambda self: {'start_blockers': []})
    assert daily.main(['resume'])['automatic_failure_retry'] is False
    saved = daily.read(tmp_path / 'state.json')
    assert 'attention' not in saved and saved['days']['2026-11-09']['done']
    assert not (tmp_path / 'paused.json').exists()


def test_pause_during_launch_stops_exact_worker_before_lock_release(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(daily, 'HOME', tmp_path)
    daily.save(tmp_path / 'config.json', {'release': 'a' * 40})
    fake = Fake()
    monkeypatch.setattr(daily, 'Backend', lambda config: fake)
    def launching(state, backend, persist, now):
        state['days'] = {'2026-11-09': {'run_id': 'daily-20261109', 'launch_attempted': True, 'container_id': 'b' * 64}}
        fake.item = {'Id': 'b' * 64, 'State': {'Status': 'running'}}
        fake.on = False
        daily.status(state, 'RUNNING')
    monkeypatch.setattr(daily, 'tick', launching)
    daily.main(['tick'])
    assert fake.calls[-1] == ('stop', 'daily-20261109', 'b' * 64)


def test_stop_remains_available_with_changed_checkout_and_rejects_replaced_worker(monkeypatch, tmp_path):
    backend = daily.Backend({'image_id': 'pinned'}, tmp_path)
    item = {'Id': 'b' * 64, 'Image': 'pinned', 'Config': {'Labels': {daily.host.LABEL: 'true'}}}
    monkeypatch.setattr(daily.host.h, 'container', lambda *a, **k: item)
    calls = []
    monkeypatch.setattr(daily.host.h, 'docker', lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(backend, 'verify', lambda: pytest.fail('stop must not require unchanged checkout'))
    backend.stop('daily-20261109', 'b' * 64)
    assert calls == [(('stop', '--time', '45', 'b' * 64), {'timeout': 55})]
    item['Id'] = 'c' * 64
    with pytest.raises(ValueError, match='IDENTITY_CHANGED'):
        backend.stop('daily-20261109', 'b' * 64)
    item.update(Id='b' * 64, Image='different-image')
    with pytest.raises(ValueError, match='IDENTITY_CHANGED'):
        backend.stop('daily-20261109', 'b' * 64)
    assert len(calls) == 1


def test_real_production_profile_daily_check_keeps_owner_and_budgets(tmp_path, schemas):
    from app.mixed.simulation_profile import configuration
    from app.mixed.continuous_feed import ContinuousFeed
    from app.options.runtime_cli import initialize

    settings, policy = configuration()
    feed, owner = tmp_path / 'feed', tmp_path / 'owner'
    key = tmp_path / 'synthetic-model-key'
    key.write_text('offline-not-transmitted')
    key.chmod(0o600)
    settings = type(settings).model_validate(settings.model_dump() | {
        'key_file': str(key),
        'runtime': settings.runtime.model_dump() | {'feed_file': str(feed / 'feed.json')}})
    initialize(owner, settings, clock=lambda: AT)
    ContinuousFeed(feed, policy, schemas, create=True).close()
    policy_file, schemas_file = tmp_path / 'policy.json', tmp_path / 'schemas.json'
    for path, value in ((policy_file, policy), (schemas_file, schemas)):
        path.write_text(value.model_dump_json())
        path.chmod(0o600)
    before = digest(tmp_path)
    result = inspect(owner, feed, policy_file, schemas_file, now=AT)
    assert 'DAILY_PROFILE_MISMATCH' not in result['start_blockers']
    assert 'EXISTING_HOLDINGS_OR_UNRESOLVED_ORDERS' not in result['start_blockers']
    assert 'MODEL_COST_OR_EVIDENCE_UNRESOLVED' not in result['start_blockers']
    assert result['swing_history_enrolled']
    assert result['automatic_catalog_blockers'] == []
    assert digest(tmp_path) == before


def test_previous_run_image_binding_survives_schedule_upgrade(monkeypatch, tmp_path):
    backend = daily.Backend({'image_id': 'new-image'}, tmp_path)
    item = {'Id': 'b' * 64, 'Image': 'previous-image', 'Config': {'Labels': {daily.host.LABEL: 'true'}},
            'State': {'Status': 'exited', 'ExitCode': 0}}
    monkeypatch.setattr(daily.host.h, 'container', lambda *a, **k: item)
    monkeypatch.setattr(backend, 'report', lambda run_id: {
        'operation': {'state': 'STOPPED', 'reasons': ['BOUNDED_SESSION_ENDED']}, 'account_total_fills': 2})
    state = {'days': {'2026-11-09': {'run_id': 'daily-20261109', 'launch_attempted': True,
                                    'image_id': 'previous-image', 'container_id': 'b' * 64}}}
    advance(state, backend, '2026-11-09T21:00:00')
    assert state['days']['2026-11-09']['done']
    assert state['days']['2026-11-09']['fills'] == 2
    assert state['status'] == 'STOPPED'
