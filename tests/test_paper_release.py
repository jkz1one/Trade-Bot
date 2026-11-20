"""One candidate handoff keeps the timer stopped through activation and rollback."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('paper_release_test', Path(__file__).parents[1]/'scripts/paper-release.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def setup(tmp_path, monkeypatch, failure=None):
    installed = tmp_path/'installed'
    installed.mkdir()
    home = tmp_path/'daily'
    home.mkdir()
    units = tmp_path/'units'
    units.mkdir()
    config = {'release': 'a'*40, 'image_id': 'old-image', 'max_feed_recoveries': 2}
    (home/'config.json').write_text(json.dumps(config))
    (home/'state.json').write_text('{"attention":"SESSION_STOPPED_REVIEW_REQUIRED","days":{"2026-11-20":{"failures":3}}}')
    for name, body in m.daily.units(installed).items():
        (units/name).write_text(body)
    monkeypatch.setattr(m.daily, 'HOME', home)
    monkeypatch.setattr(m.daily, 'UNIT_HOME', units)
    monkeypatch.setattr(m.daily, 'private', lambda *a: None)
    monkeypatch.setattr(m.daily.host, 'no_active_session', lambda: None)
    calls = []
    heads = {str(installed): 'a'*40, str(m.ROOT): 'b'*40}
    def git(root, *args):
        calls.append(('git', *args))
        if args[:2] == ('status', '--porcelain'):
            return 'dirty' if failure == 'dirty' else ''
        if args[:2] == ('rev-parse', 'HEAD'):
            return heads[str(root)]
        if args[:2] == ('switch', '--detach'):
            heads[str(root)] = args[2]
        return ''
    monkeypatch.setattr(m, 'git', git)
    def command(args, **kwargs):
        calls.append(tuple(args))
        if args[:2] == ['systemctl', 'show']:
            return SimpleNamespace(returncode=0, stdout='active' if failure == 'busy' else 'inactive')
        return SimpleNamespace(returncode=0, stdout='')
    monkeypatch.setattr(m, 'command', command)
    ticks = iter(range(0, 1000, 31))
    monkeypatch.setattr(m.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(m.time, 'sleep', lambda s: None)
    owner = {'runtime_status': 'STOPPED', 'halt_reason': 'OPTION_RUNTIME_STOPPED', 'owner_revision': 8765}
    def structured(root, script, args, expected, **kwargs):
        calls.append((script, *args))
        if args[0] == 'build':
            return {'status': 'IMAGE_BUILT', 'image_id': 'new-image'}
        if args[0] == 'daily-info':
            return {'status': 'DAILY_INFO', 'start_blockers': ['BLOCKED'] if failure == 'owner' else [],
                    'owner_state': owner, 'automatic_catalog_blockers': [], 'live_enabled': False, 'target_session': '2026-11-23',
                    'swing_history_enrolled': True, 'swing_expiration': '2026-11-27'}
        if args[0] == 'capture-session':
            if failure == 'capture':
                raise m.ReleaseStageFailed({'step': 'capture-session', 'failure': {'stage': 'VALIDATE_PLAN'}})
            return {'status': 'CATALOG_CAPTURED', 'provider_tool_calls': 8}
        if args[0] == 'recover-snapshot':
            return {'status': 'PUBLISHED', 'source_modified': False, 'held_plays': 0}
        if args[0] == 'install':
            assert args == ['install', '--keep-timer-stopped']
            (home/'config.json').write_text(json.dumps(dict(config, release='b'*40, image_id='new-image')))
            return {'status': 'DAILY_SCHEDULE_INSTALLED', 'release': 'b'*40, 'image_id': 'new-image'}
        if args[0] == 'update-reader':
            if failure in {'reader', 'rollback'} and (heads[str(installed)] == 'b'*40 or failure == 'rollback'):
                raise m.ReleaseStageFailed({'step': 'update-reader'})
            return {'status': 'DASHBOARD_READER_UPDATED'}
        raise AssertionError(args)
    monkeypatch.setattr(m, 'structured', structured)
    return installed, home, calls, heads, config


@pytest.mark.parametrize('deploy', [False, True])
def test_candidate_qualifies_before_install_and_never_resumes_or_changes_daily_state(tmp_path, monkeypatch, deploy):
    checkout, home, calls, heads, _ = setup(tmp_path, monkeypatch)
    before = (home/'state.json').read_bytes()
    result = m.execute(checkout, deploy=deploy, output=tmp_path/'proof')
    assert result['status'] == ('RELEASE_INSTALLED' if deploy else 'CANDIDATE_QUALIFIED')
    assert len([c for c in calls if c[:2] == ('connected-session-host.py', 'capture-session')]) == 2
    assert (home/'state.json').read_bytes() == before
    assert calls[-1] == ('systemctl', 'start', m.TIMER)
    assert not any('resume' in c or 'run' in c or 'enroll-session' in c for c in calls)
    if deploy:
        assert calls.index(('git', 'switch', '--detach', 'b'*40)) > calls.index(('connected-session-host.py', 'recover-snapshot'))
    else:
        assert heads[str(checkout)] == 'a'*40


@pytest.mark.parametrize('failure', ['capture', 'owner', 'busy', 'reader', 'rollback'])
def test_failed_handoff_stops_before_install_or_rolls_back_before_timer_restart(tmp_path, monkeypatch, failure):
    checkout, home, calls, heads, config = setup(tmp_path, monkeypatch, failure)
    before = (home/'state.json').read_bytes()
    result = m.execute(checkout, deploy=True, output=tmp_path/'proof')
    expected = 'ROLLBACK_FAILED' if failure == 'rollback' else 'ROLLED_BACK' if failure == 'reader' else 'FAILED'
    assert result['status'] == expected
    assert heads[str(checkout)] == 'a'*40
    assert json.loads((home/'config.json').read_text()) == config
    assert (home/'state.json').read_bytes() == before
    if failure == 'rollback':
        assert ('systemctl', 'start', m.TIMER) not in calls
    else:
        assert calls[-1] == ('systemctl', 'start', m.TIMER)
    if failure == 'capture':
        assert result['last_failure']['failure']['stage'] == 'VALIDATE_PLAN'
    if failure in {'capture', 'owner', 'busy'}:
        assert not any(c[:2] == ('git', 'switch') for c in calls)


def test_dirty_checkout_never_stops_timer(tmp_path, monkeypatch):
    checkout, _, calls, _, _ = setup(tmp_path, monkeypatch, 'dirty')
    with pytest.raises(ValueError, match='CLEAN_RELEASE'):
        m.execute(checkout, deploy=True, output=tmp_path/'proof')
    assert not any(c[0] == 'systemctl' for c in calls)


def test_zero_exit_controller_busy_is_not_success(monkeypatch):
    monkeypatch.setattr(m, 'command', lambda *a, **k: SimpleNamespace(returncode=0,
        stdout='{"status":"CONTROLLER_BUSY"}', stderr=''))
    with pytest.raises(m.ReleaseStageFailed):
        m.structured(m.ROOT, 'paper-daily.py', ['install'], {'DAILY_SCHEDULE_INSTALLED'})


def test_structured_failure_on_stderr_retains_capture_cause_without_raw_errors(monkeypatch):
    failure = {'status': 'CAPTURE_FAILED', 'exit_code': 1,
               'failure': {'stage': 'VALIDATE_PLAN', 'error_classes': ['SchemaContractChanged'],
                           'completed_reads': 0, 'private': 'DO_NOT_EXPORT'}}
    monkeypatch.setattr(m, 'command', lambda *a, **k: SimpleNamespace(returncode=1,
        stdout='', stderr='PRIVATE STDERR\n' + json.dumps(failure)))
    with pytest.raises(m.ReleaseStageFailed) as caught:
        m.structured(m.ROOT, 'connected-session-host.py', ['capture-session'], {'CATALOG_CAPTURED'})
    assert caught.value.detail['failure']['error_classes'] == ['SchemaContractChanged']
    assert 'PRIVATE' not in str(caught.value.detail) and 'DO_NOT_EXPORT' not in str(caught.value.detail)
