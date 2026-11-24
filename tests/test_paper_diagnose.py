"""The operator diagnostic is read-only and does not need a worker to explain failure."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import pytest

spec = importlib.util.spec_from_file_location('paper_diagnose_test', Path(__file__).parents[1]/'scripts/paper-diagnose.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def setup(tmp_path, monkeypatch, *, launched=False):
    daily = module.daily
    monkeypatch.setattr(daily, 'HOME', tmp_path)
    monkeypatch.setattr(daily, 'private', lambda *args: None)
    (tmp_path/'config.json').write_text(json.dumps({'release': 'a'*40, 'image_id': 'image'}))
    (tmp_path/'state.json').write_text(json.dumps({'status': 'MISSING_INPUTS',
        'reasons': ['PREPARATION_RETRY_LIMIT'], 'schedule': {'target_session': '2026-11-20'},
        'days': {'2026-11-20': {'last_error': 'StepFailed', 'failures': 3, 'launch_attempted': launched}}}))
    monkeypatch.setattr(daily.Backend, 'container', lambda *a, **k: None)
    for name in ('invoke', 'report', 'stop', 'prepare', 'launch'):
        monkeypatch.setattr(daily.Backend, name, lambda *a, **k: pytest.fail('diagnostic mutation'))
    monkeypatch.setattr(module, 'evidence_changes', lambda path: {'changes': ['fixture']})


def test_missing_worker_reads_original_capture_failure_without_changing_state(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    calls = []
    def runner(args):
        calls.append(args)
        assert args[0] == 'journalctl'
        raw = {'step': 'capture-session', 'report': {'status': 'CAPTURE_FAILED',
             'evidence_directory': '/root/trade-bot-options-proof-example',
             'failure': {'stage': 'VALIDATE_PLAN', 'completed_reads': 0,
                         'error_classes': ['SchemaContractChanged']}}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(raw))
    result = module.diagnose('2026-11-20', runner=runner)
    assert result['worker_exists'] is False and result['launch_attempted'] is False
    assert result['last_failure']['failure']['error_classes'] == ['SchemaContractChanged']
    assert result['schema_changes'] == {'changes': ['fixture']}
    assert result['state_modified'] is False and result['provider_calls'] is False
    assert len(calls) == 1 and before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_live_worker_report_is_current_and_docker_failure_is_not_missing(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, launched=True)
    monkeypatch.setattr(module.daily.Backend, 'container', lambda *a, **k: {
        'Id': 'worker', 'Image': 'image', 'RestartCount': 0,
        'State': {'Status': 'running', 'Running': True, 'StartedAt': '2026-11-20T15:00:00Z'}})
    def runner(args):
        if args[0] == 'journalctl':
            return SimpleNamespace(returncode=0, stdout='')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'run_id': 'daily-20261120',
            'operation': {'last_decision_at': '2026-11-20T15:29:00Z'},
            'runtime_evidence': {'feed': 'FRESH'}}))
    result = module.diagnose('2026-11-20', runner=runner, now=datetime(2026,11,20,15,30,tzinfo=timezone.utc))
    assert result['worker']['elapsed_seconds'] == 1800
    assert result['session']['runtime_evidence']['feed'] == 'FRESH'
    def unavailable(*a, **k):
        raise RuntimeError('private')
    monkeypatch.setattr(module.daily.Backend, 'container', unavailable)
    result = module.diagnose('2026-11-20', runner=runner)
    assert 'worker_exists' not in result and result['status'] == 'DIAGNOSTIC_PARTIAL'
    assert 'private' not in str(result)


def test_display_receipt_uses_immutable_copy_without_claiming_account_validation(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(module.daily.host, 'EXPORTS', tmp_path)
    folder = tmp_path/'connected-price-options-v1'
    folder.mkdir()
    path = folder/'options.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE dashboard_snapshot (id INTEGER, payload TEXT)')
        db.execute('INSERT INTO dashboard_snapshot VALUES(1,?)', (json.dumps({'published_at': '2026-11-20T15:00:00Z'}),))
        db.execute('CREATE TABLE execution_option_runtime (id INTEGER, status TEXT)')
        db.execute("INSERT INTO execution_option_runtime VALUES(1,'STOPPED')")
    before = path.read_bytes()
    result = module.display_receipt(datetime(2026,11,20,15,30,tzinfo=timezone.utc))
    assert result['age_seconds'] == 1800 and result['stored_runtime'] == 'STOPPED'
    assert result['accounting_reverified'] is False
    assert path.read_bytes() == before and sorted(p.name for p in folder.iterdir()) == ['options.db']


def test_legacy_capture_compares_actual_packaged_contract_without_provider_values(tmp_path, monkeypatch):
    baseline = json.loads((module.ROOT/'app/options/read_contract.json').read_text())
    baseline['get_equity_historicals']['outputSchema']['properties']['data']['properties']['notice'] = {
        'type': 'string', 'description': 'PRIVATE PROVIDER TEXT'}
    (tmp_path/'context.json').write_text(json.dumps({'result': {'schemas': {'tools': baseline}}}))
    monkeypatch.setattr(module, 'Path', lambda path: tmp_path)
    monkeypatch.setattr(module.daily, 'private', lambda *a: None)
    result = module.evidence_changes('/root/trade-bot-options-proof-example')
    assert result['changes'] == [{'change': 'ADDED', 'path': [
        'get_equity_historicals', 'outputSchema', 'properties', 'data', 'properties', 'notice']}]
    assert 'PRIVATE PROVIDER TEXT' not in str(result)
    assert module.evidence_changes('/etc/private') is None


def test_failed_worker_keeps_feed_causes_and_native_timing_not_just_old_controller_error(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, launched=True)
    monkeypatch.setattr(module.daily.Backend, 'container', lambda *a, **k: {
        'Id': 'worker', 'Image': 'image', 'RestartCount': 0,
        'State': {'Status': 'exited', 'Running': False, 'ExitCode': 2,
                  'StartedAt': '2026-11-20T15:00:00Z', 'FinishedAt': '2026-11-20T18:00:00Z'}})
    fields = {
        'collector_failures': [{'sequence': 8, 'error_class': 'TimeoutError',
                                'read_progress': {'stage': 'CONNECT', 'completed_reads': 0}}],
        'collection_timing': {'status': 'OBSERVED', 'attempts': 344, 'measured': 344},
        'runtime_failures': [{'error_class': 'FixtureProcessTimeout', 'operation': 'snapshot',
                              'option_process': {'parent_phase': 'SPAWN'}}],
        'runtime_timing': {'scheduler_delay': {'max_seconds': 5.5},
                           'native_spawn_budget': {'NATIVE_SNAPSHOT_SPAWN': {'min_seconds': 4.99}}},
    }
    calls = []
    def runner(args):
        calls.append(args[0])
        if args[0] == 'journalctl':
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                'step': 'daily-info', 'report': {'status': 'UNAVAILABLE', 'reason': 'DAILY_INFO_UNAVAILABLE'}}))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'run_id': 'daily-20261120', **fields}))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = module.diagnose('2026-11-20', runner=runner)
    assert result['status'] == 'DIAGNOSTIC_RECORDED'
    assert result['worker']['elapsed_seconds'] == 10800
    assert result['last_failure']['step'] == 'daily-info'
    for name, evidence in fields.items():
        assert result['session'][name] == evidence
    assert calls == ['journalctl', 'python3']
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
