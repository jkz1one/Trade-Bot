import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    'paper_soak_host', Path(__file__).resolve().parents[1] / 'scripts/paper-soak-host.py')
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)


@pytest.fixture
def evidence():
    receipt = {'container_id': 'c' * 64, 'name': 'offline', 'image_id': 'sha256:' + 'b' * 64,
               'release': 'a' * 40, 'data': '/separate/new/data', 'application_manifest_sha256': 'd' * 64}
    item = {'Id': receipt['container_id'], 'Name': '/offline', 'Image': receipt['image_id'],
            'RestartCount': 0,
            'Config': {'Image': receipt['image_id'], 'User': '0:0', 'Cmd': host.RUN_ARGS,
                       'Entrypoint': ['python', '-I', '-W', 'error', '/opt/trade-bot/scripts/paper-soak.py'],
                       'Labels': {host.LABEL: 'true',
                       'trade-bot.offline-soak.release': receipt['release']}},
            'State': {'Running': False, 'Status': 'exited', 'ExitCode': 0, 'OOMKilled': False},
            'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True,
                           'NanoCpus': 1000000000, 'Memory': host.MEMORY, 'MemorySwap': host.MEMORY,
                           'PidsLimit': 128, 'RestartPolicy': {'Name': 'no'}, 'Privileged': False,
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true']},
            'Mounts': [{'Type': 'bind', 'RW': True, 'Source': receipt['data'], 'Destination': '/evidence'},
                       {'Type': 'tmpfs', 'Destination': '/tmp'}]}
    summary = {'status': 'PASSED', 'child_exit_code': 0, 'seconds': host.SECONDS, 'seed_mib': 112,
               'application_manifest_sha256': receipt['application_manifest_sha256'],
               'wall_clock_soak': 'OBSERVED'}
    progress = {'status': 'PASSED', 'wall_clock_full_duration': 'OBSERVED',
                'elapsed_seconds': host.SECONDS + 3, 'planned_seconds': host.SECONDS,
                'logical_cpus': 1, 'final_accounting': 'VERIFIED_FLAT', 'children_reaped': True,
                'native_snapshot_failures': 0, 'native_headroom_target_met': True,
                'decision_coverage': {'target_met': True},
                'execution': {'completed_round_trips': 1}}
    return item, receipt, summary, progress


def test_requires_duration_lifecycle_and_container_completion(evidence):
    assert host.classify(*evidence) == ('PASSED', None)


def entry_evidence(evidence):
    item, receipt, summary, progress = evidence
    receipt.update(profile='entry', seconds=335)
    item['Config']['Cmd'] = host.run_args('entry')
    summary.update(seconds=335, wall_clock_soak='NOT_RUN')
    progress.update(planned_seconds=335, elapsed_seconds=337, wall_clock_full_duration='NOT_RUN')
    return evidence


def test_short_host_gate_is_never_a_full_duration_pass(evidence):
    assert host.classify(*entry_evidence(evidence)) == ('ENTRY_GATE_PASSED', None)
    evidence[1]['profile'] = 'duration'
    assert host.classify(*evidence)[0] == 'UNVERIFIED'


@pytest.mark.parametrize('which,key,value', [
    (2, 'seconds', 90), (3, 'elapsed_seconds', 334.9),
    (3, 'decision_coverage', {'target_met': False}),
    (3, 'execution', {'completed_round_trips': 0}),
    (3, 'final_accounting', None), (3, 'wall_clock_full_duration', 'OBSERVED'),
])
def test_short_gate_still_requires_complete_lifecycle_and_coverage(evidence, which, key, value):
    entry_evidence(evidence)[which][key] = value
    assert host.classify(*evidence) == ('INCOMPLETE', 'COMPLETE_ENTRY_GATE_EVIDENCE_REQUIRED')


def test_short_profile_only_changes_duration_not_container_limits():
    args = ('offline', 'a' * 40, 'sha256:' + 'b' * 64, Path('/fresh/data'))
    short, full = host.create_args(*args, profile='entry'), host.create_args(*args)
    index = full.index('--seconds') + 1
    assert short[index] == '335'
    short[index] = full[index]
    assert short == full
    with pytest.raises(ValueError, match='KNOWN_QUALIFICATION_PROFILE'):
        host.start(Path('/absent'), profile='arbitrary')


def test_repeat_profile_preserves_short_limits_and_uses_same_image():
    args = ('offline', 'a' * 40, 'sha256:' + 'b' * 64, Path('/fresh/data'))
    assert host.create_args(*args, profile='entry-repeat') == host.create_args(*args, profile='entry') + ['--repeat-entry']


def series_files(tmp_path, evidence):
    item, receipt, summary, progress = entry_evidence(evidence)
    receipt.update(profile='entry-repeat', seconds=1005, data=str(tmp_path / 'data'))
    item['Mounts'][0]['Source'] = receipt['data']
    item['Config']['Cmd'] = host.run_args('entry-repeat')
    root = tmp_path / 'data/run'
    root.mkdir(parents=True)
    series = {'status': 'PASSED', 'repetitions': 3, 'seconds_each': 335,
              'application_manifest_sha256': receipt['application_manifest_sha256']}
    (root / 'series.json').write_text(json.dumps(series))
    summary['cgroup_memory'] = {'status': 'OBSERVED', 'max_bytes': host.MEMORY, 'peak_bytes': 700000000,
                                'events': {'max': 0, 'oom': 0, 'oom_kill': 0}}
    diagnostic = {'status': 'RECORDED', 'decision_status': 'OPEN', 'stored_status': 'COMPLETE',
                  'clocks': {'deadline': 'original'}, 'cycle_timing': {'status': 'COMPLETE', 'spans': [
                      {'phase': 'NATIVE_ACCEPT_SPAWN', 'status': 'COMPLETE', 'remaining_at_start_seconds': 3},
                      {'phase': 'NATIVE_ACCEPT_TRANSPORT', 'status': 'COMPLETE', 'elapsed_seconds': 1}]}}
    for i in range(1, 4):
        directory = root / f'trial-{i}'
        directory.mkdir()
        for name, value in [('summary.json', summary), ('progress.json', progress), ('entry-diagnostic.json', diagnostic)]:
            (directory / name).write_text(json.dumps(value))
    return item, receipt, root


@pytest.mark.parametrize('defect', [None, 'missing', 'hash', 'elapsed', 'margin', 'oom', 'memory', 'exit', 'running', 'restart', 'isolation'])
def test_repeat_requires_every_original_clock_lifecycle_and_outer_container(tmp_path, evidence, defect):
    item, receipt, root = series_files(tmp_path, evidence)
    if defect in ('missing', 'hash', 'elapsed', 'margin', 'memory'):
        name = {'missing': 'summary.json', 'hash': 'summary.json', 'elapsed': 'progress.json',
                'margin': 'entry-diagnostic.json', 'memory': 'summary.json'}[defect]
        path = root / 'trial-2' / name
        data = json.loads(path.read_text())
        if defect == 'missing':
            path.unlink()
        else:
            if defect == 'hash': data['application_manifest_sha256'] = 'other'
            elif defect == 'elapsed': data['elapsed_seconds'] = 42
            elif defect == 'margin': data['cycle_timing']['spans'][0]['remaining_at_start_seconds'] = 1.3
            elif defect == 'memory': data['cgroup_memory']['events']['max'] = 1
            path.write_text(json.dumps(data))
    elif defect == 'oom': item['State']['OOMKilled'] = True
    elif defect == 'exit': item['State']['ExitCode'] = 1
    elif defect == 'running': item['State']['Running'] = True
    elif defect == 'restart': item['RestartCount'] = 1
    elif defect == 'isolation': item['HostConfig']['NetworkMode'] = 'host'
    result = host.repeat_status(tmp_path, item, receipt)
    assert (result['status'] == 'ENTRY_SERIES_PASSED') == (defect is None)


@pytest.mark.parametrize('budget,elapsed', [(1.3, 1.3), (None, 1), (3, float('nan')), (True, 1), (3, 0)])
def test_entry_margin_rejects_missing_invalid_or_insufficient_budget(tmp_path, evidence, budget, elapsed):
    _, _, root = series_files(tmp_path, evidence)
    diagnostic = json.loads((root / 'trial-1/entry-diagnostic.json').read_text())
    diagnostic['cycle_timing']['spans'][0]['remaining_at_start_seconds'] = budget
    diagnostic['cycle_timing']['spans'][1]['elapsed_seconds'] = elapsed
    assert host.entry_margin(diagnostic)['status'] != 'MET'


def test_running_series_requires_fresh_progress_not_only_a_running_container(tmp_path, evidence):
    item, receipt, root = series_files(tmp_path, evidence)
    item['State']['Running'] = True
    series = json.loads((root / 'series.json').read_text()) | {'active_trial': 2}
    (root / 'series.json').write_text(json.dumps(series))
    path = root / 'trial-2/progress.json'
    os.utime(path, (0, 0))
    assert host.repeat_status(tmp_path, item, receipt)['status'] == 'RUNNING_STALE_PROGRESS'


@pytest.mark.parametrize('which,key,value', [
    (2, 'status', 'RUNNING'), (2, 'status', None), (2, 'child_exit_code', 2),
    (2, 'application_manifest_sha256', 'other'), (2, 'seconds', 335), (2, 'seed_mib', 68),
    (3, 'status', 'RUNNING'), (3, 'wall_clock_full_duration', 'PENDING'),
    (3, 'elapsed_seconds', 599.77), (3, 'elapsed_seconds', float('nan')),
    (3, 'elapsed_seconds', float('inf')), (3, 'elapsed_seconds', True),
    (3, 'final_accounting', 'UNVERIFIED'), (3, 'children_reaped', False),
    (3, 'native_snapshot_failures', 1), (3, 'decision_coverage', {'target_met': False}),
    (3, 'native_headroom_target_met', False),
    (3, 'execution', {'completed_round_trips': 0}), (3, 'logical_cpus', 2),
])
def test_incomplete_receipts_never_become_passes(evidence, which, key, value):
    evidence[which][key] = value
    assert host.classify(*evidence)[0] == 'INCOMPLETE'


@pytest.mark.parametrize('target,key,value', [
    ('State', 'Running', True), ('State', 'ExitCode', 2), ('State', 'OOMKilled', True),
    ('State', 'Status', 'created'), (None, 'RestartCount', 1),
])
def test_container_state_overrules_saved_pass(evidence, target, key, value):
    (evidence[0][target] if target else evidence[0])[key] = value
    assert host.classify(*evidence)[0] != 'PASSED'


@pytest.mark.parametrize('key,value', [
    ('NetworkMode', 'host'), ('NanoCpus', 2000000000), ('Memory', 2 * host.MEMORY),
    ('MemorySwap', -1), ('PidsLimit', 256), ('ReadonlyRootfs', False),
    ('Privileged', True), ('CapAdd', ['SYS_ADMIN']), ('CapDrop', []),
    ('SecurityOpt', []), ('RestartPolicy', {'Name': 'always'}),
])
def test_changed_isolation_is_not_qualified(evidence, key, value):
    evidence[0]['HostConfig'][key] = value
    assert host.classify(*evidence)[0] == 'UNVERIFIED'


def test_mounted_connected_account_or_wrong_image_is_not_qualified(evidence):
    item = evidence[0]
    item['Mounts'].append({'Type': 'bind', 'RW': True, 'Source': '/account', 'Destination': '/owner'})
    assert host.classify(*evidence)[0] == 'UNVERIFIED'
    item['Mounts'].pop()
    item['Image'] = 'other'
    assert host.classify(*evidence)[0] == 'UNVERIFIED'


def test_spawn_has_one_new_output_mount_and_no_credentials_or_account():
    args = host.create_args('offline', 'a' * 40, 'sha256:' + 'b' * 64, Path('/fresh/data'))
    assert args.count('--mount') == 1
    assert args[args.index('--mount') + 1] == 'type=bind,src=/fresh/data,dst=/evidence'
    assert args[args.index('--network') + 1] == 'none'
    assert args[args.index('--memory') + 1] == args[args.index('--memory-swap') + 1] == str(host.MEMORY)
    assert args[args.index('--restart') + 1] == 'no'
    assert args[args.index('--seconds') + 1] == '21480'
    assert '--rm' not in args and '--env-file' not in args and '--privileged' not in args
    assert not any('/var/lib/trade-bot-' in value or '/run/secrets' in value or 'docker.sock' in value
                   for value in args)


@pytest.mark.parametrize('paused,status,reasons,allowed', [
    (False, 'FAILED', ['SESSION_STOPPED_REVIEW_REQUIRED'], True),
    (True, 'WAITING_NEXT_SESSION', [], True),
    (False, 'WAITING_NEXT_SESSION', [], False),
    (False, 'FAILED', ['OTHER_FAILURE'], False),
])
def test_idle_guard_never_changes_schedule(monkeypatch, paused, status, reasons, allowed):
    commands = []
    def command(args):
        commands.append(args)
        return json.dumps({'paused': paused, 'operation': {'status': status, 'reasons': reasons}}) if args[-1] == 'status' else ''
    monkeypatch.setattr(host, 'command', command)
    if allowed:
        host.idle(Path('/checkout'))
    else:
        with pytest.raises(ValueError, match='SCHEDULER'):
            host.idle(Path('/checkout'))
    assert [c[-1] for c in commands] == ['{{.ID}}', '{{.ID}}', 'status']


def test_running_worker_refuses_before_reading_controller(monkeypatch):
    monkeypatch.setattr(host, 'command', lambda args: 'connected-worker')
    with pytest.raises(ValueError, match='WORKER_ALREADY_RUNNING'):
        host.idle(Path('/checkout'))


def test_status_survives_candidate_removal_and_marks_stale_progress(evidence, tmp_path, monkeypatch):
    item, receipt, summary, progress = evidence
    receipt['data'] = str(tmp_path / 'data')
    item['Mounts'][0]['Source'] = receipt['data']
    run = Path(receipt['data']) / 'run'
    run.mkdir(parents=True)
    (tmp_path / 'host.json').write_text(json.dumps(receipt))
    (run / 'summary.json').write_text(json.dumps(summary))
    path = run / 'progress.json'
    path.write_text(json.dumps(progress))
    monkeypatch.setattr(host, 'ROOT', tmp_path / 'removed-candidate')
    monkeypatch.setattr(host, 'command', lambda _: json.dumps([item]))
    before = (tmp_path / 'host.json').read_bytes()
    diagnostic = {'status': 'RECORDED', 'reason': None, 'decision_status': 'OPEN',
                  'clocks': {'deadline': '2026-10-28T14:00:29.848382Z'}}
    (run / 'entry-diagnostic.json').write_text(json.dumps(diagnostic))
    assert host.status(tmp_path)['status'] == 'PASSED'
    assert host.status(tmp_path)['entry_diagnostic'] == diagnostic
    item['State']['Running'] = True
    original = path.read_text()
    path.unlink()
    assert host.status(tmp_path)['status'] == 'RUNNING_AWAITING_PROGRESS'
    path.write_text(original)
    os.utime(path, (1, 1))
    assert host.status(tmp_path)['status'] == 'RUNNING_STALE_PROGRESS'
    item['State'].update(Running=False, ExitCode=137, OOMKilled=True)
    assert host.status(tmp_path)['reason'] == 'CONTAINER_OOM'
    item['State']['OOMKilled'] = False
    item['RestartCount'] = 1
    assert host.status(tmp_path)['reason'] == 'CONTAINER_RESTARTED'
    assert (tmp_path / 'host.json').read_bytes() == before


def saved_report():
    return {'window_start': '2026-10-28T14:00:00+00:00',
            'window_end': '2026-10-28T14:01:00+00:00',
            'runtime_evidence': {'feed': 'FRESH', 'heartbeat': 'FRESH'},
            'current_runtime': [{'status': 'RUNNING', 'feed_sequence': 6}],
            'accepted_packet': {'sequence': 6, 'coverage_issues': ['SCOPE_CURRENT_INPUT_UNAVAILABLE']},
            'cycle_count': 1, 'decision_count': 1,
            'cycle_outcomes': [{'status': ['COMPLETE'], 'reason': [], 'count': 1}],
            'run_execution': {'entry_fills': 1, 'exit_fills': 1, 'completed_round_trips': 1},
            'collection': [{'status': 'DELIVERED', 'attempts': 6}],
            'decision_reason_counts': [], 'run_issues': [], 'runtime_failures': [],
            'publication_failures': [],
            'runtime_timing': {'coverage': {'before_first_commit': 'UNOBSERVABLE'}},
            'unrelated_payload': 'not part of the compact report'}


def test_running_soak_exposes_saved_feed_decisions_and_fills_without_mutation(evidence, tmp_path, monkeypatch):
    item, receipt, summary, progress = evidence
    item['State'].update(Running=True, Status='running')
    summary['status'] = progress['status'] = 'RUNNING'
    progress.pop('execution')
    progress.pop('decision_coverage')
    receipt['data'] = str(tmp_path / 'data')
    item['Mounts'][0]['Source'] = receipt['data']
    run = Path(receipt['data']) / 'run'
    run.mkdir(parents=True)
    files = {tmp_path / 'host.json': receipt, run / 'summary.json': summary,
             run / 'progress.json': progress, run / 'latest-report.json': saved_report()}
    for path, value in files.items():
        path.write_text(json.dumps(value))
    originals = {p: p.read_bytes() for p in files}
    calls = []
    def command(args):
        calls.append(args)
        return json.dumps([item])
    monkeypatch.setattr(host, 'command', command)
    value = host.status(tmp_path)
    assert value['status'] == 'RUNNING'
    report = value['session_report']
    assert report['status'] == 'RECORDED' and report['receipt_freshness'] == 'CURRENT'
    assert report['evidence_clock'] == 'SYNTHETIC_REPORT_WINDOW'
    assert report['runtime_evidence_at_cutoff']['feed'] == 'FRESH'
    assert report['accepted_packet']['sequence'] == 6 and report['decision_count'] == 1
    assert report['run_execution']['completed_round_trips'] == 1
    assert report['timing_coverage']['before_first_commit'] == 'UNOBSERVABLE'
    assert 'unrelated_payload' not in report
    assert value['progress']['decision_coverage'] is None  # No invented due-slot coverage.
    assert value['connected_health'] == 'UNVERIFIED'
    assert calls == [['docker', 'container', 'inspect', receipt['container_id']]]
    assert {p: p.read_bytes() for p in files} == originals


@pytest.mark.parametrize('age,freshness', [(0, 'CURRENT'), (90, 'CURRENT'),
                                        (91, 'STALE'), (-1, 'FUTURE')])
def test_report_receipt_age_is_separate_from_synthetic_feed_age(tmp_path, age, freshness):
    now = datetime(2026, 11, 27, tzinfo=UTC)
    path = tmp_path / 'latest-report.json'
    report = saved_report()
    report['run_execution'] = {'entry_fills': 0, 'exit_fills': 0, 'completed_round_trips': 0}
    path.write_text(json.dumps(report))
    stamp = now.timestamp() - age
    os.utime(path, (stamp, stamp))
    result = host.session_report(tmp_path, now, finished=False)
    assert result['receipt_freshness'] == freshness
    assert result['receipt_age_seconds'] == age
    assert result['runtime_evidence_at_cutoff']['feed'] == 'FRESH'
    assert result['run_execution']['entry_fills'] == 0
    assert result['status'] == 'RECORDED'  # Zero fills does not assert a failure.


def test_final_report_preferred_only_after_exit_and_failures_retained(tmp_path):
    report = saved_report()
    (tmp_path / 'latest-report.json').write_text(json.dumps(report))
    report['runtime_failures'] = [{'error_class': 'FixtureProcessTimeout'}]
    report['run_issues'] = ['FEED_STALE']
    (tmp_path / 'report.json').write_text(json.dumps(report))
    now = datetime.now(UTC)
    assert host.session_report(tmp_path, now, finished=False)['runtime_failures'] == []
    result = host.session_report(tmp_path, now, finished=True)
    assert result['source'] == 'report.json'
    assert result['runtime_failures'] == report['runtime_failures']
    assert result['run_issues'] == ['FEED_STALE']
    (tmp_path / 'report.json').unlink()
    assert host.session_report(tmp_path, now, finished=True)['source'] == 'latest-report.json'


@pytest.mark.parametrize('content', [None, '{', '[]', '{}', '{"window_start": 7}'])
def test_missing_or_malformed_report_remains_unavailable(tmp_path, content):
    if content is not None:
        (tmp_path / 'latest-report.json').write_text(content)
    result = host.session_report(tmp_path, datetime.now(UTC), finished=False)
    assert result['status'] == 'UNAVAILABLE'
    assert 'runtime_evidence_at_cutoff' not in result


@pytest.mark.parametrize('field,value', [('window_start', '2026-10-28T14:00:00'),
                                        ('window_end', '2026-10-27T14:00:00+00:00'),
                                        ('runtime_timing', 'malformed')])
def test_invalid_saved_report_does_not_hide_docker_evidence(tmp_path, field, value):
    report = saved_report()
    report[field] = value
    (tmp_path / 'latest-report.json').write_text(json.dumps(report))
    assert host.session_report(tmp_path, datetime.now(UTC), finished=False)['status'] == 'UNAVAILABLE'


def test_report_reads_the_open_receipt_when_writer_replaces_path(tmp_path, monkeypatch):
    path = tmp_path / 'latest-report.json'
    path.write_text(json.dumps(saved_report()))
    now = datetime(2026, 11, 27, tzinfo=UTC)
    os.utime(path, (now.timestamp() - 100, now.timestamp() - 100))
    original = host.os.fstat
    def replace_after_open(fd):
        stat = original(fd)
        pending = tmp_path / 'latest-report.pending'
        changed = saved_report()
        changed['decision_count'] = 99
        pending.write_text(json.dumps(changed))
        os.utime(pending, (now.timestamp(), now.timestamp()))
        pending.replace(path)
        return stat
    monkeypatch.setattr(host.os, 'fstat', replace_after_open)
    result = host.session_report(tmp_path, now, finished=False)
    assert result['decision_count'] == 1 and result['receipt_freshness'] == 'STALE'
    assert json.loads(path.read_text())['decision_count'] == 99


@pytest.mark.parametrize('profile', ['entry', 'duration'])
@pytest.mark.parametrize('interruption', [None, 'build', 'second-idle', 'start'])
def test_detached_launch_preserves_installed_checkout_and_evidence(tmp_path, monkeypatch, interruption, profile):
    root = tmp_path / 'candidate'
    (root / 'app').mkdir(parents=True)
    (root / 'app/__init__.py').write_text('')
    installed = tmp_path / 'installed'
    installed.mkdir()
    (installed / 'account').write_bytes(b'original account')
    monkeypatch.setattr(host, 'ROOT', root)
    monkeypatch.setattr(host, 'EVIDENCE', tmp_path / 'proof')
    monkeypatch.setattr(host, 'LOCK', tmp_path / 'lock')
    monkeypatch.setattr(host.os, 'geteuid', lambda: 0)
    commands, idle_calls = [], []
    def idle(checkout):
        idle_calls.append(checkout)
        if interruption == 'second-idle' and len(idle_calls) == 2:
            raise ValueError('NEW_WORKER')
    monkeypatch.setattr(host, 'idle', idle)
    def command(args):
        commands.append(args)
        if 'rev-parse' in args:
            return 'a' * 40
        if 'archive' in args:
            Path(args[args.index('-o') + 1]).write_bytes(b'archive')
        if args[:2] == ['docker', 'create']:
            return 'c' * 64
        if args[:2] == ['docker', 'start'] and interruption == 'start':
            raise ValueError('START_FAILED')
        return ''
    monkeypatch.setattr(host, 'command', command)
    def build(args, **kwargs):
        commands.append(args)
        assert kwargs['stdin'].name.endswith('/source.tar')
        Path(args[args.index('--iidfile') + 1]).write_text('sha256:' + 'b' * 64)
        return SimpleNamespace(returncode=1 if interruption == 'build' else 0)
    monkeypatch.setattr(host.subprocess, 'run', build)
    monkeypatch.setattr(host, 'status', lambda _: {'status': 'RUNNING'})
    if interruption:
        with pytest.raises(ValueError):
            host.start(installed, profile=profile)
    else:
        assert host.start(installed, profile=profile)['status'] == 'RUNNING'
    output, = host.EVIDENCE.iterdir()
    receipt = json.loads((output / 'host.json').read_text())
    assert receipt['profile'] == profile and receipt['seconds'] == host.PROFILES[profile]
    assert receipt['status'] == ('START_FAILED' if interruption else 'STARTED')
    assert (output / 'check.py').is_file()
    assert (installed / 'account').read_bytes() == b'original account'
    assert len(idle_calls) == (1 if interruption == 'build' else 2)
    assert not any('systemctl' in c or 'switch' in c or 'resume' in c or 'rm' in c for c in commands)
    archive = next(c for c in commands if 'archive' in c)
    assert tuple(archive[-len(host.BUILD_INPUTS):]) == host.BUILD_INPUTS
    if interruption in ('build', 'second-idle'):
        assert not any(c[:2] == ['docker', 'create'] for c in commands)
    if not interruption:
        original = (output / 'host.json').read_bytes()
        create = next(c for c in commands if c[:2] == ['docker', 'create'])
        assert create[-len(host.RUN_ARGS):] == host.run_args(profile)
        host.start(installed, profile=profile)
        assert len(list(host.EVIDENCE.iterdir())) == 2
        assert (output / 'host.json').read_bytes() == original


def test_missing_final_summary_is_incomplete_not_pass(evidence):
    item, receipt, _, progress = evidence
    assert host.classify(item, receipt, {}, progress)[0] == 'INCOMPLETE'
    assert host.load_optional(Path('/absent/offline-proof')) == {}


def test_short_status_requires_original_decision_diagnostic(evidence, tmp_path, monkeypatch):
    item, receipt, summary, progress = entry_evidence(evidence)
    receipt['data'] = str(tmp_path / 'data')
    item['Mounts'][0]['Source'] = receipt['data']
    run = Path(receipt['data']) / 'run'
    run.mkdir(parents=True)
    for path, value in ((tmp_path / 'host.json', receipt), (run / 'summary.json', summary),
                        (run / 'progress.json', progress)):
        path.write_text(json.dumps(value))
    monkeypatch.setattr(host, 'command', lambda _: json.dumps([item]))
    assert host.status(tmp_path)['reason'] == 'ORIGINAL_ENTRY_DIAGNOSTIC_REQUIRED'
    diagnostic = {'status': 'RECORDED', 'decision_status': 'OPEN', 'stored_status': 'COMPLETE',
                  'cycle_timing': {'status': 'COMPLETE'}, 'clocks': {'deadline': 'original'}}
    path = run / 'entry-diagnostic.json'
    path.write_text(json.dumps(diagnostic))
    assert host.status(tmp_path)['status'] == 'ENTRY_GATE_PASSED'
    diagnostic['decision_status'] = 'HOLD'
    path.write_text(json.dumps(diagnostic))
    assert host.status(tmp_path)['reason'] == 'ORIGINAL_ENTRY_DIAGNOSTIC_REQUIRED'


def retained_journal(evidence, tmp_path, rows=()):
    item, receipt, _, _ = evidence
    receipt['data'] = str(tmp_path / 'data')
    item['Mounts'][0]['Source'] = receipt['data']
    path = tmp_path / 'data/run/owner/options.db'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE execution_events(sequence INTEGER PRIMARY KEY,occurred_at,kind,payload)')
        db.executemany('INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)', rows)
    return path


def test_terminal_publication_event_survives_missing_final_report(evidence, tmp_path, monkeypatch):
    at = '2026-10-28T18:48:00+00:00'
    payload = {'stage': 'RUNNING', 'error_class': 'TimeoutError',
               'frames': [{'file': 'app/mixed/dashboard_snapshot.py', 'line': 372}],
               'message': 'never print arbitrary exception messages'}
    path = retained_journal(evidence, tmp_path, [(at, 'CONNECTED_PUBLICATION_FAILED', json.dumps(payload))])
    item, receipt, summary, progress = evidence
    item['State']['ExitCode'] = 1
    summary['status'] = progress['status'] = 'FAILED'
    progress['failure_evidence'] = [{'phase': 'SHUTDOWN', 'error_class': 'ComponentFailure'}]
    run = path.parent.parent
    files = {tmp_path / 'host.json': receipt, run / 'summary.json': summary,
             run / 'progress.json': progress, run / 'latest-report.json': saved_report()}
    for p, value in files.items():
        p.write_text(json.dumps(value))
    original = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(host, 'ROOT', tmp_path / 'removed-worktree')
    calls = []
    def command(args):
        calls.append(args)
        return json.dumps([item])
    monkeypatch.setattr(host, 'command', command)
    result = host.status(tmp_path)
    assert result['status'] == 'FAILED'
    assert result['session_report']['publication_failures'] == []  # Earlier report missed it.
    incidents = result['retained_incidents']
    assert incidents['status'] == 'STORED_EVENTS_READ' and not incidents['accounting_reverified']
    assert incidents['publication_failures'] == [{'at': at, 'stage': 'RUNNING',
        'error_class': 'TimeoutError', 'frames': payload['frames'], 'evidence_available': True}]
    assert 'never print' not in json.dumps(result)
    assert result['failure_evidence'] == progress['failure_evidence']
    assert calls == [['docker', 'container', 'inspect', receipt['container_id']]]
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()} == original
    # An older saved pass cannot overrule a durable publisher incident either.
    item['State']['ExitCode'] = 0
    summary['status'] = progress['status'] = 'PASSED'
    for p, value in ((run / 'summary.json', summary), (run / 'progress.json', progress)):
        p.write_text(json.dumps(value))
    assert host.status(tmp_path)['reason'] == 'RETAINED_PUBLICATION_FAILURE'


def test_standalone_reader_runs_from_stdin_without_candidate_or_application(evidence, tmp_path):
    path = retained_journal(evidence, tmp_path, [('2026-10-28T18:48:00+00:00',
        'CONNECTED_PUBLICATION_FAILED', '{"error_class":"MemoryError","frames":[]}')])
    item, receipt, summary, progress = evidence
    item['State']['ExitCode'] = 1
    summary['status'] = progress['status'] = 'FAILED'
    run = path.parent.parent
    for p, value in ((tmp_path / 'host.json', receipt), (run / 'summary.json', summary),
                     (run / 'progress.json', progress)):
        p.write_text(json.dumps(value))
    fake = tmp_path / 'docker'
    fake.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps([item])) + ')\n')
    fake.chmod(0o700)
    result = subprocess.run([sys.executable, '-I', '-', 'status', '--evidence', str(tmp_path)],
        input=Path(host.__file__).read_text(), cwd=tmp_path, text=True, capture_output=True,
        env={'PATH': str(tmp_path)}, timeout=5)
    value = json.loads(result.stdout)
    assert result.returncode == 1 and value['status'] == 'FAILED'
    assert value['retained_incidents']['publication_failures'][0]['error_class'] == 'MemoryError'
    assert not value['state_modified'] and not result.stderr


@pytest.mark.parametrize('damage', ['running', 'identity', 'foreign_data', 'symlink',
                                   'missing', 'corrupt', 'wal', 'journal', 'wal_header'])
def test_retained_incident_read_rejects_mutable_or_unbound_journals(evidence, tmp_path, damage):
    path = retained_journal(evidence, tmp_path)
    item, receipt, _, _ = evidence
    if damage == 'running':
        item['State'].update(Running=True, Status='running')
    elif damage == 'identity':
        item['Image'] = 'other'
    elif damage == 'foreign_data':
        receipt['data'] = str(tmp_path / 'elsewhere')
        item['Mounts'][0]['Source'] = receipt['data']
    elif damage == 'symlink':
        path.rename(path.with_name('original.db'))
        path.symlink_to(path.with_name('original.db'))
    elif damage == 'missing':
        path.unlink()
    elif damage == 'corrupt':
        path.write_bytes(b'not sqlite' * 100)
    elif damage in {'wal', 'journal'}:
        Path(str(path) + '-' + damage).write_bytes(b'retain')
    else:
        data = bytearray(path.read_bytes())
        data[18:20] = b'\x02\x02'
        path.write_bytes(data)
    original = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert host.retained_publication_failures(tmp_path, item, receipt)['status'] == 'UNAVAILABLE'
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == original


def test_retained_event_read_bounds_rows_payloads_and_selected_fields(evidence, tmp_path):
    at = '2026-10-28T18:48:00+00:00'
    invalid = ['{', '[]', None, ' ' * 16385, json.dumps({'error_class': [], 'stage': {}})]
    rows = [(at, 'CONNECTED_PUBLICATION_FAILED', value) for value in invalid]
    private = {'error_class': 'OSError', 'frames': [
        {'file': '/private/secrets.py', 'line': 4}, {'file': 'app/../private.py', 'line': 5},
        {'file': 'app/mixed/dashboard_snapshot.py', 'line': True}], 'extra': 'not selected'}
    rows += [(at, 'CONNECTED_PUBLICATION_FAILED', json.dumps(private))] * 7
    rows.append((at, 'OTHER_EVENT', '{"private": "not selected"}'))
    retained_journal(evidence, tmp_path, rows)
    result = host.retained_publication_failures(tmp_path, evidence[0], evidence[1])
    assert result['status'] == 'STORED_EVENTS_READ'
    assert len(result['publication_failures']) == 10
    assert result['publication_failures'][0]['frames'] == []
    assert any(not r['evidence_available'] for r in result['publication_failures'])
    assert 'not selected' not in json.dumps(result) and 'private' not in json.dumps(result)


@pytest.mark.parametrize('events,peak,status', [
    ({'max': 603798, 'oom': 0, 'oom_kill': 0}, host.MEMORY, 'LIMIT_REACHED'),
    ({'max': 1, 'oom': 0, 'oom_kill': 0}, host.MEMORY - 1, 'LIMIT_REACHED'),
    ({'max': 0, 'oom': 0, 'oom_kill': 0}, host.MEMORY - 1, 'NO_LIMIT_EVENT_RECORDED'),
    ({'max': 4, 'oom': 1, 'oom_kill': 0}, host.MEMORY, 'OOM_RECORDED'),
    ({'max': 4, 'oom': 1, 'oom_kill': 1}, host.MEMORY, 'OOM_KILL_RECORDED'),
])
def test_memory_pressure_does_not_conflate_limit_events_oom_or_postexit_usage(events, peak, status):
    result = host.memory_pressure({'status': 'OBSERVED', 'events': events,
        'max_bytes': host.MEMORY, 'peak_bytes': peak, 'current_bytes': 1})
    assert result['status'] == status and result['peak_headroom_bytes'] == host.MEMORY - peak
    assert result['failure_causality'] == 'UNDETERMINED'


@pytest.mark.parametrize('memory', [None, {}, {'status': 'UNAVAILABLE'},
    {'status': 'OBSERVED', 'max_bytes': None, 'peak_bytes': 1, 'events': {}},
    {'status': 'OBSERVED', 'max_bytes': host.MEMORY, 'peak_bytes': 1,
     'events': {'max': True, 'oom': 0, 'oom_kill': 0}}])
def test_missing_memory_counters_do_not_claim_available_capacity(memory):
    assert host.memory_pressure(memory) == {'status': 'UNAVAILABLE'}
