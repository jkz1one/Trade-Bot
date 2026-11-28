"""Publication-only replay preserves the retained source and deployment controls."""

import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_combined_session_feed import combined
from test_contract_catalog import captures
from test_dashboard_snapshot import owner
from test_paper_soak_host import evidence as evidence  # noqa: PLC0414

SPEC = importlib.util.spec_from_file_location('paper_publisher_replay',
    Path(__file__).resolve().parents[1] / 'scripts/paper-publisher-replay.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def offline_owner(tmp_path):
    settings, _ = combined(captures.__wrapped__())
    raw = settings.model_dump()
    raw['limits']['population_id'] = 'offline-duration-capacity-v1'
    key = tmp_path / 'synthetic-model-key'
    key.write_text('offline-test-placeholder')
    key.chmod(0o600)
    raw['key_file'] = str(key)
    settings = type(settings).model_validate(raw)
    return owner(tmp_path, value=SimpleNamespace(settings=settings))[0]


def test_real_single_publication_keeps_original_owner_files(tmp_path, monkeypatch):
    from app.mixed import dashboard_snapshot
    source = offline_owner(tmp_path)
    before = probe.source_identity(source)
    def forbidden(*args, **kwargs):
        raise AssertionError('No trading, provider or credential work in this replay')
    monkeypatch.setattr('app.options.runtime_cli.existing_runtime', forbidden)
    monkeypatch.setattr('app.options.read_capture.collect', forbidden)
    monkeypatch.setattr('app.options.coordinator.model_key', forbidden)
    output = tmp_path / 'replay'
    original = dashboard_snapshot.copy_display_tables
    result = probe.replay(source, output)
    assert result['status'] == 'STATIC_PUBLICATION_PASSED' and result['calls'] == 1
    assert result['publication']['status'] == 'PUBLISHED'
    assert result['source_identity_before'] == before == probe.source_identity(source)
    assert not result['source_modified'] and not result['execution_authority']
    assert not result['credentials_opened'] and not result['provider_calls']
    assert result['connected_health'] == 'UNVERIFIED'
    assert set(result['phases']) == {'COPY_SOURCE', 'PROJECT_DISPLAY'}
    assert dashboard_snapshot.copy_display_tables is original
    assert json.loads((output / 'result.json').read_text()) == result


def test_exact_display_cap_error_is_recorded_without_raising_limit(tmp_path):
    source = offline_owner(tmp_path)
    with sqlite3.connect(source / 'options.db') as db:
        # Deliberate isolated capacity probe; not invented account or trading evidence.
        db.execute('CREATE TABLE execution_capacity_probe(id INTEGER PRIMARY KEY,payload TEXT)')
        db.executemany('INSERT INTO execution_capacity_probe VALUES(?,?)',
                      ((n, str(n).ljust(256*1024, 'x')) for n in range(270)))
    before = probe.source_identity(source)
    result = probe.replay(source, tmp_path / 'replay')
    assert result['status'] == 'PUBLICATION_FAILED'
    assert result['stage'] == 'PROJECT_DISPLAY'
    assert result['last_projection_table'] == 'execution_capacity_probe'
    assert result['failure']['error_class'] == 'OperationalError'
    assert result['failure']['sqlite_errorname'] == 'SQLITE_FULL'
    assert result['failure']['sqlite_errorcode'] == sqlite3.SQLITE_FULL
    assert result['display_limit_bytes'] == 64 * 1024**2
    assert probe.source_identity(source) == before and not result['source_modified']


def test_interrupted_sql_keeps_its_error_code(tmp_path, monkeypatch):
    from app.mixed import dashboard_snapshot
    source = offline_owner(tmp_path)
    original = dashboard_snapshot.copy_display_tables
    def interrupt(db):
        # Simulate a deadline interrupt during the real projection SQL.
        db.set_progress_handler(lambda: 1, 1)
        return original(db)
    monkeypatch.setattr(dashboard_snapshot, 'copy_display_tables', interrupt)
    before = probe.source_identity(source)
    result = probe.replay(source, tmp_path / 'replay')
    assert result['status'] == 'PUBLICATION_FAILED' and result['stage'] == 'PROJECT_DISPLAY'
    assert result['failure']['sqlite_errorcode'] == sqlite3.SQLITE_INTERRUPT
    assert result['failure']['sqlite_errorname'] == 'SQLITE_INTERRUPT'
    assert probe.source_identity(source) == before and not result['source_modified']
    assert dashboard_snapshot.copy_display_tables is interrupt


@pytest.mark.parametrize('damage', ['foreign_population', 'extra_file', 'symlink',
                                   'file_symlink', 'hardlink', 'existing_output'])
def test_child_refuses_unqualified_sources_and_existing_outputs(tmp_path, damage):
    source = offline_owner(tmp_path)
    output = tmp_path / 'replay'
    if damage == 'foreign_population':
        path = source / 'runtime.json'
        value = json.loads(path.read_text())
        value['limits']['population_id'] = 'connected-simulation-1000-v1'
        path.write_text(json.dumps(value))
    elif damage == 'extra_file':
        (source / 'unexpected-secret').write_text('never read')
    elif damage == 'symlink':
        alias = tmp_path / 'alias'
        alias.symlink_to(source, target_is_directory=True)
        source = alias
    elif damage == 'file_symlink':
        path = source / 'venue.db'
        moved = tmp_path / 'retained-venue.db'
        path.rename(moved)
        path.symlink_to(moved)
    elif damage == 'hardlink':
        (tmp_path / 'linked-venue.db').hardlink_to(source / 'venue.db')
    else:
        output.mkdir()
        (output / 'preserved').write_text('original')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        probe.replay(source, output)
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_replay_container_keeps_limits_and_mounts_only_source_readonly(evidence):
    host = probe.launcher()
    receipt = evidence[1]
    args = probe.create_args(host, 'new-probe', receipt, Path('/retained/owner'),
                             Path('/new/data'), Path('/new/probe.py'))
    for key, value in {'--network': 'none', '--cpus': '1', '--memory': str(host.MEMORY),
                       '--memory-swap': str(host.MEMORY), '--pids-limit': '128',
                       '--restart': 'no', '--cap-drop': 'ALL', '--entrypoint': 'python'}.items():
        assert args[args.index(key) + 1] == value
    assert '--read-only' in args and '--privileged' not in args
    mounts = [args[i+1] for i, part in enumerate(args) if part == '--mount']
    assert mounts == ['type=bind,src=/new/data,dst=/evidence',
                      'type=bind,src=/retained/owner,dst=/source,readonly',
                      'type=bind,src=/new/probe.py,dst=/probe.py,readonly']
    assert args[-8:] == ['-W', 'error', '/probe.py', 'child', '--source', '/source',
                        '--output', '/evidence/replay']


@pytest.mark.parametrize('timeout', [False, True])
def test_host_uses_existing_image_and_never_controls_old_worker_or_scheduler(
    evidence, tmp_path, monkeypatch, timeout
):
    host = probe.launcher()
    root = tmp_path / 'proofs'
    saved = root / 'retained'
    source = saved / 'data/run/owner'
    source.mkdir(parents=True)
    for name in probe.OWNER_FILES:
        (source / name).write_bytes(b'original-' + name.encode())
    item, receipt, _, _ = evidence
    receipt['data'] = str(saved / 'data')
    item['Mounts'][0]['Source'] = receipt['data']
    (saved / 'host.json').write_text(json.dumps(receipt))
    original = {p: p.read_bytes() for p in saved.rglob('*') if p.is_file()}
    installed = tmp_path / 'installed'
    installed.mkdir()
    calls = []
    new_id = 'e' * 64
    def command(args):
        calls.append(args)
        if args[:3] == ['docker', 'container', 'inspect']:
            return json.dumps([item] if args[-1] == receipt['container_id'] else [
                {'State': {'Status': 'exited', 'Running': False, 'ExitCode': 0}, 'RestartCount': 0}])
        if args[:2] == ['docker', 'create']:
            return new_id
        if args[:2] == ['docker', 'stop']:
            assert args[-1] == new_id
            return new_id
        raise AssertionError(args)
    def run(args, **kwargs):
        assert args == ['docker', 'start', '--attach', new_id]
        if timeout:
            raise subprocess.TimeoutExpired(args, 45)
        out = next(root.glob('trade-bot-publisher-replay-*')) / 'data/replay'
        out.mkdir()
        (out / 'result.json').write_text('{"status":"STATIC_PUBLICATION_PASSED"}')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(host, 'EVIDENCE', root)
    monkeypatch.setattr(host, 'LOCK', tmp_path / 'lock')
    monkeypatch.setattr(host, 'command', command)
    monkeypatch.setattr(host, 'idle', lambda path: calls.append(['idle', str(path)]))
    monkeypatch.setattr(probe, 'launcher', lambda: host)
    monkeypatch.setattr(probe.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(probe.subprocess, 'run', run)
    result = probe.start(saved, installed)
    assert result['status'] == ('REPLAY_DEADLINE' if timeout else 'REPLAY_RECORDED')
    assert result['image_id'] == receipt['image_id']
    assert {p: p.read_bytes() for p in saved.rglob('*') if p.is_file()} == original
    assert list(installed.iterdir()) == []
    assert not any(c[0] in {'systemctl', 'git'} or c[:2] == ['docker', 'build'] for c in calls)
    assert (Path(result['evidence_directory']) / 'probe.py').read_bytes() == Path(probe.__file__).read_bytes()


@pytest.mark.parametrize('damage', ['running', 'image', 'mount', 'receipt', 'extra_file', 'busy'])
def test_host_refuses_active_or_foreign_evidence_before_creating_anything(
    evidence, tmp_path, monkeypatch, damage
):
    host = probe.launcher()
    root = tmp_path / 'proofs'
    saved = root / 'retained'
    source = saved / 'data/run/owner'
    source.mkdir(parents=True)
    for name in probe.OWNER_FILES:
        (source / name).write_bytes(b'original-' + name.encode())
    item, receipt, _, _ = evidence
    receipt['data'] = str(saved / 'data')
    item['Mounts'][0]['Source'] = receipt['data']
    if damage == 'running':
        item['State'].update(Running=True, Status='running')
    elif damage == 'image':
        item['Image'] = 'sha256:' + 'f' * 64
    elif damage == 'mount':
        item['Mounts'].append({'Type': 'bind', 'Source': '/credentials',
                               'Destination': '/credentials', 'RW': False})
    elif damage == 'receipt':
        receipt['data'] = item['Mounts'][0]['Source'] = str(tmp_path / 'foreign')
    elif damage == 'extra_file':
        (source / 'options.db-wal').write_text('retained WAL')
    (saved / 'host.json').write_text(json.dumps(receipt))
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    installed = tmp_path / 'installed'
    installed.mkdir()
    calls = []
    def command(args):
        calls.append(args)
        assert args == ['docker', 'container', 'inspect', receipt['container_id']]
        return json.dumps([item])
    def idle(_):
        assert damage == 'busy'
        raise ValueError('SCHEDULER_NOT_PAUSED_OR_REVIEW_HELD')
    monkeypatch.setattr(host, 'EVIDENCE', root)
    monkeypatch.setattr(host, 'LOCK', tmp_path / 'lock')
    monkeypatch.setattr(host, 'command', command)
    monkeypatch.setattr(host, 'idle', idle)
    monkeypatch.setattr(probe, 'launcher', lambda: host)
    monkeypatch.setattr(probe.os, 'geteuid', lambda: 0)
    with pytest.raises(ValueError):
        probe.start(saved, installed)
    assert len(calls) == 1
    assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    assert list(installed.iterdir()) == []
