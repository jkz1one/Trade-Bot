import importlib.util
import json
import os
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
    assert host.status(tmp_path)['status'] == 'PASSED'
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


@pytest.mark.parametrize('interruption', [None, 'build', 'second-idle', 'start'])
def test_detached_launch_preserves_installed_checkout_and_evidence(tmp_path, monkeypatch, interruption):
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
            host.start(installed)
    else:
        assert host.start(installed)['status'] == 'RUNNING'
    output, = host.EVIDENCE.iterdir()
    receipt = json.loads((output / 'host.json').read_text())
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
        host.start(installed)
        assert len(list(host.EVIDENCE.iterdir())) == 2
        assert (output / 'host.json').read_bytes() == original


def test_missing_final_summary_is_incomplete_not_pass(evidence):
    item, receipt, _, progress = evidence
    assert host.classify(item, receipt, {}, progress)[0] == 'INCOMPLETE'
    assert host.load_optional(Path('/absent/offline-proof')) == {}
