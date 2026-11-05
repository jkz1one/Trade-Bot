"""Host-only saved reports scope evidence to one run and exclude private payloads."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "paper_session_report", Path(__file__).parents[1] / "scripts/paper-session-report.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('large', [False, True])
def test_saved_report_scopes_cycles_and_extracts_rejections_without_writes(tmp_path, large):
    owner = tmp_path / "owner/options.db"
    collector = tmp_path / "collector/collector.db"
    owner.parent.mkdir()
    collector.parent.mkdir()
    with sqlite3.connect(owner) as db:
        db.executescript("""
        CREATE TABLE execution_option_runtime_slots(slot,status,reason,started_at,completed_at);
        CREATE TABLE execution_option_opportunities(cycle_key,started_at,status,result_json);
        CREATE TABLE execution_events(kind,occurred_at);
        CREATE TABLE execution_option_runtime(id,status,reason,feed_sequence);
        INSERT INTO execution_option_runtime VALUES(1,'STOPPED','OPTION_RUNTIME_STOPPED',100);
        CREATE TABLE execution_control(id,halted,halt_reason);
        INSERT INTO execution_control VALUES(1,1,'OPTION_RUNTIME_STOPPED');
        CREATE TABLE execution_fills(id);
        """)
        for hour in (17, 18, 19):
            at = f"2026-10-30T{hour}:35:00+00:00"
            db.execute("INSERT INTO execution_option_runtime_slots VALUES(?,'COMPLETE',NULL,?,?)",
                       (hour, at, at))
            evidence = {"status": "HOLD", "reason": "NO_ADMITTED_CONTRACT",
                        "rejections": {"private-instrument-id": ["ENTRY_DEBIT_LIMIT"]},
                        "candidates": [], "thesis": "DO_NOT_EXPOSE_PRIVATE_TEXT",
                        "model_key": "DO_NOT_EXPOSE_PRIVATE_KEY",
                        "scans": [{"symbol": "SPY", "issues": [], "observations": [
                            {"family": "BREAKOUT", "status": "WATCHING", "reasons": ["NO_BREAKOUT"]}]}],
                        "read_plans": [{"exclusions": {"private-id": ["SPREAD_TOO_WIDE"]}}]}
            if large:
                evidence['original_history'] = 'PRIVATE_HISTORY' * 50000
                evidence['scans'][0]['original_history'] = 'PRIVATE_HISTORY' * 50000
                evidence['candidates'] = [{'private_payload': 'PRIVATE_CANDIDATE' * 40000}]
            db.execute("INSERT INTO execution_option_opportunities VALUES(?,?,'COMPLETE',?)",
                       (str(hour), at, json.dumps(evidence)))
            db.execute("INSERT INTO execution_events VALUES('OPTION_REVIEWED_RESUME',?)", (at,))
    with sqlite3.connect(collector) as db:
        db.execute("CREATE TABLE attempts(sequence,started_at,status,packet_json)")
        db.execute("INSERT INTO attempts VALUES(90,'2026-10-30T18:35:01+00:00','DELIVERED',?)",
                   (json.dumps({'kind': 'CYCLE', 'coverage_issues': ['SCOPE_CURRENT_INPUT_UNAVAILABLE'],
                                'frame': {'private': 'DO_NOT_EXPOSE_PRIVATE_FRAME'}}),))
    before = (owner.read_bytes(), collector.read_bytes())
    report = module.report(tmp_path, "2026-10-30T18:30:22.407711551Z", "2026-10-30T18:40:34.899702954Z")
    assert len(report["cycles"]) == len(report["decisions"]) == 1
    assert report["reviewed_entry_resumes"] == 1
    assert report["collection"][0]["attempts"] == 1
    assert report['packet_summary'] == [{'kind': ['CYCLE'], 'coverage_issues': ['SCOPE_CURRENT_INPUT_UNAVAILABLE'],
                                       'packets': 1, 'first_sequence': 90, 'last_sequence': 90}]
    assert report["decisions"][0]["rejections"] == ["ENTRY_DEBIT_LIMIT"]
    assert report['decisions'][0]['evidence_available'] is True
    assert report['decisions'][0]['option_candidates'] == int(large)
    assert report['decisions'][0]['omitted_summary_fields'] == []
    if large:
        assert report['decisions'][0]['evidence_bytes'] > 524288
        assert 'PRIVATE_HISTORY' not in json.dumps(report)
        assert 'PRIVATE_CANDIDATE' not in json.dumps(report)
    assert report["decisions"][0]["contract_exclusions"] == ["SPREAD_TOO_WIDE"]
    assert report["decisions"][0]["scans"][0]["setups"][0]["reasons"] == ["NO_BREAKOUT"]
    assert "DO_NOT_EXPOSE" not in json.dumps(report)
    assert "private-id" not in json.dumps(report)
    assert before == (owner.read_bytes(), collector.read_bytes())
    assert not report["provider_calls"] and not report["state_modified"]


def test_missing_database_is_not_created(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        module.connection(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_portfolio_receipts_are_authoritative_even_with_empty_legacy_tables():
    with sqlite3.connect(':memory:') as db:
        db.executescript('CREATE TABLE execution_fills(id); CREATE TABLE execution_stock_fills(id);'
                         'CREATE TABLE execution_portfolio_orders(observation_json);')
        db.executemany('INSERT INTO execution_portfolio_orders VALUES(?)', [
            (None,), (json.dumps({'fills': []}),),
            (json.dumps({'fills': [{'fill_id': 'one'}, {'fill_id': 'two'}]}),),
            (json.dumps({'fills': [{'fill_id': 'three'}]}),),
        ])
        assert module.fill_count(db) == (3, 'PORTFOLIO_ORDER_OBSERVATIONS')
        db.execute('INSERT INTO execution_fills VALUES(1)')
        assert module.fill_count(db)[0] == 3  # Never double-count a legacy projection.
        db.execute("INSERT INTO execution_portfolio_orders VALUES('{}')")
        with pytest.raises(ValueError, match='FILL_EVIDENCE_UNAVAILABLE'):
            module.fill_count(db)


def test_legacy_mixed_owner_counts_stock_and_option_fills():
    with sqlite3.connect(':memory:') as db:
        db.executescript('CREATE TABLE execution_fills(id); INSERT INTO execution_fills VALUES(1);'
                         'CREATE TABLE execution_stock_fills(id); INSERT INTO execution_stock_fills VALUES(2);')
        assert module.fill_count(db) == (2, 'LEGACY_FILL_TABLES')


def test_reason_extraction_is_bounded_and_does_not_print_prose():
    assert module.codes(["FRESHNESS_FAILED", "private message /some/path", "x" * 1000]) == ["FRESHNESS_FAILED"]
    assert len(module.codes([f"REASON_{i}" for i in range(200)])) == 100
    assert module.codes(['MISSING_QUOTE:private-provider-id', 'SWING_OPTION_QUOTE_UNAVAILABLE:SPY',
                         'private prose:do not print']) == ['MISSING_QUOTE', 'SWING_OPTION_QUOTE_UNAVAILABLE']


@pytest.mark.parametrize('raw,issue', [(None, 'MISSING'), ('invalid', 'INVALID_JSON'),
                                    ('"' + 'x' * module.MAX_DECISION_BYTES + '"', 'TOO_LARGE')])
def test_unavailable_decision_does_not_invent_empty_scan_or_zero_candidates(raw, issue):
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_option_opportunities(cycle_key,result_json)')
        db.execute('INSERT INTO execution_option_opportunities VALUES(?,?)', ('test', raw))
        result = module.decision_evidence(db, 'test')
        assert result['evidence_available'] is False and result['evidence_issue'] == issue
        assert result['option_candidates'] is result['stock_candidates'] is None
        assert 'scans' not in result and 'status' not in result


def test_oversized_summary_field_is_explicit_without_hiding_other_evidence():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_option_opportunities(cycle_key,result_json)')
        db.execute('INSERT INTO execution_option_opportunities VALUES(?,?)', ('test', json.dumps({
            'status': 'HOLD', 'reason': 'NO_ADMITTED_CONTRACT', 'rejections': ['X' * 70000],
            'stock_candidates': [1, 2], 'scans': [{'symbol': 'QQQ', 'observations': [
                {'family': 'SWING', 'status': 'WATCHING', 'reasons': ['NO_BREAKOUT']}]}]})))
        result = module.decision_evidence(db, 'test')
        assert result['status'] == ['HOLD']
        assert result['stock_candidates'] == 2
        assert result['omitted_summary_fields'] == ['$.rejections']
        assert result['scans'][0]['setups'][0]['reasons'] == ['NO_BREAKOUT']


def test_unstarted_or_unrelated_container_never_reads_account(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(module, "report", lambda *a: pytest.fail("Unexpected database read"))
    monkeypatch.setattr("sys.argv", ["report", "--run-id", "test-run"])
    for label, state, reason in [(None, "exited", "NOT_A_CONNECTED_SESSION"),
                                 ("bound", "created", "SESSION_NOT_RUNNING_OR_FINISHED")]:
        monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=json.dumps({"label": label, "state": {"Status": state}})))
        with pytest.raises(ValueError, match=reason):
            module.main()


def test_runtime_failure_report_keeps_timing_without_private_payload():
    with sqlite3.connect(':memory:') as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE execution_events(kind,occurred_at,payload)')
        for at in ('2026-10-30T17:00:00+00:00', '2026-10-30T18:00:00+00:00'):
            db.execute('INSERT INTO execution_events VALUES(?,?,?)', ('FIXTURE_READ_FAILED', at,
                json.dumps({'error_class':'FixtureProcessTimeout','timeout_seconds':5,'elapsed_seconds':5.1,
                            'stderr':'PRIVATE_VALUE','venue':'PRIVATE_PATH'})))
        rows = module.runtime_failures(db, '2026-10-30T17:30:00+00:00', '2026-10-30T18:30:00+00:00')
        assert len(rows) == 1 and rows[0]['elapsed_seconds'] == 5.1
        assert rows[0]['error_class'] == 'FixtureProcessTimeout'
        assert 'PRIVATE' not in json.dumps(rows)


def live_result():
    return {'current_runtime': [{'status': 'RUNNING'}], 'current_control': [{'halted': 0}],
            'runtime_evidence': {'heartbeat': 'FRESH', 'feed': 'FRESH'},
            'accepted_packet': {'kind': ['CYCLE'], 'coverage_issues': ['SCOPE_CURRENT_INPUT_UNAVAILABLE',
                              'SWING_EXACT_CONTRACT_EVIDENCE_UNAVAILABLE']},
            'decisions': [{'evidence_available': True, 'status': ['HOLD'], 'reason': ['NO_ADMITTED_CONTRACT'],
                           'started_at': '2026-11-03T15:05:00+00:00', 'scans': [{'issues': [],
                            'setups': [{'status': ['WATCHING'], 'reasons': ['NO_BREAKOUT']}]}]}]}


@pytest.mark.parametrize('reason', ['SCOPE_PAID_REFRESH_RATE_LIMITED', 'SCOPE_PAID_REFRESH_EXPIRED',
                                  'SCOPE_PAID_REFRESH_FAILED', 'SCOPE_FRESH_EVIDENCE_TIMEOUT'])
def test_paid_scope_input_failure_is_not_waiting_for_a_setup(reason):
    value = live_result()
    value['decisions'][0]['reason'] = [reason]
    current = module.operation(value, {'Status': 'running'})
    assert current['state'] == 'MISSING_INPUTS' and current['reasons'] == [reason]
    assert module.operation(value, {'Status': 'exited', 'ExitCode': 0})['state'] == 'STOPPED'


@pytest.mark.parametrize('mode,expected', [
    ('waiting', 'WAITING_FOR_SETUP'), ('running', 'RUNNING'), ('stale', 'MISSING_INPUTS'),
    ('no_heartbeat', 'MISSING_INPUTS'), ('halted', 'MISSING_INPUTS'), ('history', 'MISSING_INPUTS'),
    ('quote', 'MISSING_INPUTS'), ('failed', 'FAILED'), ('stopped', 'STOPPED'),
    ('container_failed', 'FAILED')])
def test_live_operation_keeps_process_setup_and_family_gaps_distinct(mode, expected):
    value = live_result()
    state = {'Status': 'running'}
    if mode == 'running': value['decisions'] = []
    if mode == 'stale': value['runtime_evidence']['feed'] = 'STALE'
    if mode == 'no_heartbeat': value['runtime_evidence']['heartbeat'] = 'MISSING'
    if mode == 'halted': value['current_control'] = [{'halted': 1, 'halt_reason': 'OPTION_RUNTIME_STOPPED'}]
    if mode == 'history': value['decisions'][0]['scans'][0]['issues'] = ['HISTORY_UNAVAILABLE_DELAYED_OR_STALE']
    if mode == 'quote': value['accepted_packet']['coverage_issues'].append('UNUSABLE_OPTION')
    if mode == 'failed': value['current_runtime'][0] = {'status': 'FAILED', 'reason': 'OPTION_RUNTIME_FAILED'}
    if mode in {'stopped', 'container_failed'}:
        state = {'Status': 'exited', 'ExitCode': 0 if mode == 'stopped' else 2}
        # Current owner may have a different run; historical process status wins.
        value['current_runtime'][0] = {'status': 'RUNNING'}
    result = module.operation(value, state)
    assert result['state'] == expected
    assert result['family_input_issues']['SCOPE'] == ['SCOPE_CURRENT_INPUT_UNAVAILABLE']
    assert result['trading_ready'] is False


def test_runtime_clocks_use_frozen_thresholds_and_keep_original_timestamps():
    from datetime import datetime, timezone
    with sqlite3.connect(':memory:') as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE execution_option_runtime(id,heartbeat_at,feed_recorded_at,config_json)')
        db.execute('INSERT INTO execution_option_runtime VALUES(1,?,?,?)', (
            '2026-11-03T15:00:00+00:00', '2026-11-03T14:59:51+00:00', json.dumps({
                'runtime': {'heartbeat_max_age_seconds': 10, 'feed_max_age_seconds': 20}})))
        result = module.runtime_evidence(db, datetime(2026, 11, 3, 15, 0, 10, tzinfo=timezone.utc))
        assert result['heartbeat'] == 'STALE' and result['feed'] == 'FRESH'
        assert result['heartbeat_at'] == '2026-11-03T15:00:00+00:00'
        assert result['feed_age_seconds'] == 19
        assert module.runtime_evidence(db, datetime(2026, 11, 3, 14, 59, tzinfo=timezone.utc))['feed'] == 'FUTURE'


def test_running_container_uses_current_window_without_wait_or_mutation(monkeypatch, capsys):
    from types import SimpleNamespace
    monkeypatch.setattr('sys.argv', ['report', '--run-id', 'running-test'])
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps({'label': 'bound', 'state': {'Status': 'running',
            'StartedAt': '2026-11-03T15:00:00Z', 'FinishedAt': '0001-01-01T00:00:00Z'}})))
    seen = []
    def report(directory, start, end):
        seen.append((start, end))
        return live_result()
    monkeypatch.setattr(module, 'report', report)
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'CURRENT_SESSION_REPORT'
    assert result['container_exit_code'] is None
    assert result['operation']['state'] == 'WAITING_FOR_SETUP'
    assert seen[0][1] != '0001-01-01T00:00:00Z'


@pytest.mark.parametrize('field,value,reason', [
    ('entry_timely', False, 'ENTRY_RESPONSE_EXPIRED'),
    ('scope_admission_reasons', ['SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED'],
     'SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED')])
def test_expired_or_unchanged_paid_evidence_is_not_a_no_setup_claim(field, value, reason):
    result = live_result()
    result['decisions'][0][field] = value
    current = module.operation(result, {'Status': 'running'})
    assert current['state'] == 'MISSING_INPUTS' and current['reasons'] == [reason]


def test_projected_paid_timing_is_boolean_and_preserves_scope_input_reason():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_option_opportunities(cycle_key,result_json)')
        db.execute('INSERT INTO execution_option_opportunities VALUES(?,?)', ('test', json.dumps({
            'status': 'HOLD', 'entry_timely': False, 'scope_fresh_review': {'admission_review': {
                'reasons': ['SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED'],
                'private': 'DO_NOT_EXPOSE'}}})))
        result = module.decision_evidence(db, 'test')
        assert result['entry_timely'] is False
        assert result['scope_admission_reasons'] == ['SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED']
        assert 'DO_NOT_EXPOSE' not in json.dumps(result)


def test_health_block_is_not_reported_as_waiting_for_a_setup():
    value = live_result()
    value['decisions'][0].update(reason=['ENTRY_HEALTH_BLOCKED'], scans=[])
    result = module.operation(value, {'Status': 'running'})
    assert result['state'] == 'MISSING_INPUTS'
    assert result['reasons'] == ['ENTRY_HEALTH_BLOCKED']


def test_failure_evidence_retains_native_location_without_private_fields():
    result = module.failure_evidence(json.dumps({
        'stage': 'NORMALIZE', 'error_class': 'ValueError', 'message': 'SECRET_MESSAGE',
        'locals': {'token': 'PRIVATE_TOKEN'}, 'frames': [
            {'file': '/private/secret.py', 'line': 1},
            {'file': 'app/../secret.py', 'line': 1},
            {'file': 'app/mixed/continuous_feed.py', 'line': True},
            {'file': 'app/mixed/continuous_feed.py', 'line': 775, 'source': 'PRIVATE_SOURCE'}]}))
    assert result == {'codes': ['NORMALIZE'], 'evidence_available': True,
                      'error_class': 'ValueError',
                      'frames': [{'file': 'app/mixed/continuous_feed.py', 'line': 775}]}
    assert module.failure_evidence(None)['evidence_available'] is False
    assert module.failure_evidence('{broken')['evidence_issue'] == 'INVALID_JSON'
    assert module.failure_evidence('[]')['evidence_available'] is False
    assert 'error_class' not in module.failure_evidence('{"error_class":[]}')


@pytest.mark.parametrize('auth_failure', [False, True])
def test_two_hour_failure_report_preserves_start_and_end_without_writes(tmp_path, auth_failure):
    owner, collector = tmp_path / 'owner/options.db', tmp_path / 'collector/collector.db'
    owner.parent.mkdir()
    collector.parent.mkdir()
    with sqlite3.connect(owner) as db:
        db.executescript('''
        CREATE TABLE execution_option_runtime_slots(slot,status,reason,started_at,completed_at);
        CREATE TABLE execution_option_opportunities(cycle_key,started_at,status,result_json);
        CREATE TABLE execution_events(kind,occurred_at,payload);
        CREATE TABLE execution_option_runtime(id,status,reason,feed_sequence);
        INSERT INTO execution_option_runtime VALUES(1,'STOPPED','OPTION_RUNTIME_STOPPED',472);
        CREATE TABLE execution_control(id,halted,halt_reason);
        INSERT INTO execution_control VALUES(1,1,'OPTION_RUNTIME_STOPPED');
        CREATE TABLE execution_fills(id);
        CREATE TABLE execution_model_calls(started_at,cost);
        ''')
        for n in range(15):
            reason = 'NO_ADMITTED_CONTRACT' if n < 2 else 'ENTRY_HEALTH_BLOCKED'
            at = f'2026-11-03T18:{n:02}:00+00:00'
            db.execute('INSERT INTO execution_option_opportunities VALUES(?,?,?,?)',
                       (str(n), at, 'COMPLETE', json.dumps({'status': 'HOLD', 'reason': reason})))
        db.executemany('INSERT INTO execution_events VALUES(?,?,?)', [
            ('MANUAL_HALT', '2026-11-03T18:02:00+00:00', json.dumps({'reason': 'OPTION_MODEL_COST_UNKNOWN',
                                                                   'message': 'PRIVATE_MESSAGE'})),
            ('MANUAL_HALT', '2026-11-03T19:45:00+00:00', json.dumps({'reason': 'OPTION_RUNTIME_STOPPED'})),
            ('MANUAL_HALT', '2026-11-04T18:00:00+00:00', json.dumps({'reason': 'FOREIGN_DAY'}))])
        db.executemany('INSERT INTO execution_model_calls VALUES(?,?)', [
            ('2026-11-03T18:01:00+00:00', '.001'), ('2026-11-03T18:02:00+00:00', None),
            ('2026-11-02T18:00:00+00:00', None)])
    with sqlite3.connect(collector) as db:
        db.executescript('CREATE TABLE attempts(sequence,started_at,status,packet_json);'
                         'CREATE TABLE attempt_failures(sequence,details_json);')
        for n in range(22):
            at = f'2026-11-03T19:{n:02}:00+00:00'
            db.execute('INSERT INTO attempts VALUES(?,?,?,NULL)', (n, at, 'FAILED'))
            db.execute('INSERT INTO attempt_failures VALUES(?,?)', (n, json.dumps({
                'stage': 'CAPTURE' if n == 0 else 'NORMALIZE', 'error_class': 'ValueError',
                'frames': [{'file': 'app/mixed/continuous_feed.py', 'line': 775}],
                'message': 'PRIVATE_MESSAGE'})))
        db.execute("INSERT INTO attempts VALUES(99,'2026-11-04T19:00:00+00:00','FAILED',NULL)")
        db.execute("INSERT INTO attempt_failures VALUES(99,'{}')")
        if auth_failure:
            db.execute('ALTER TABLE attempts ADD COLUMN raw_json')
            db.execute('UPDATE attempts SET raw_json=? WHERE sequence=21', (json.dumps({
                'status': 'FAILED', 'schemas': None, 'private': 'PRIVATE_TOKEN',
                'failure': {'stage': 'CONNECT', 'causes': [{'error_class': 'ReadAuthorizationRequired'}]}}),))
    before = owner.read_bytes(), collector.read_bytes()
    result = module.report(tmp_path, '2026-11-03T17:45:00Z', '2026-11-03T19:45:24Z')
    assert [r['cycle_key'] for r in result['first_decisions']] == ['0', '1', '2']
    assert [r['cycle_key'] for r in result['decisions']] == ['10', '11', '12', '13', '14']
    assert [r['decisions'] for r in result['decision_reason_counts']] == [2, 13]
    assert [r['reason'] for r in result['halt_history']] == [
        ['OPTION_MODEL_COST_UNKNOWN'], ['OPTION_RUNTIME_STOPPED']]
    assert result['model_calls'] == {'run': {'attempts': 2, 'unsettled': 1},
                                      'account_total': {'attempts': 3, 'unsettled': 2}}
    assert [r['sequence'] for r in result['collector_failures']] == [0, 1, 2, *range(12, 22)]
    assert result['collector_failures'][0]['codes'] == ['CAPTURE']
    assert result['collector_failures'][-1]['frames'][0]['line'] == 775
    assert result['run_issues'] == ['COLLECTOR_FAILURES_RECORDED',
        *(['READ_AUTHORIZATION_REQUIRED_RECORDED'] if auth_failure else []), 'ENTRY_HEALTH_BLOCKED']
    assert module.operation(result, {'Status': 'exited', 'ExitCode': 0})['state'] == 'STOPPED'
    assert 'PRIVATE' not in json.dumps(result) and 'FOREIGN_DAY' not in json.dumps(result)
    assert before == (owner.read_bytes(), collector.read_bytes())


def test_old_failed_capture_reveals_only_bounded_worker_cause():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE attempts(sequence,raw_json)')
        raw = {'status': 'FAILED', 'schemas': None, 'request_id': 'PRIVATE_REQUEST',
               'observations': [{'raw': 'PRIVATE_PROVIDER_DATA'}], 'failure': {
                   'stage': 'CONNECT', 'message': 'PRIVATE_MESSAGE', 'causes': [
                       {'error_class': 'ExceptionGroup'},
                       {'error_class': 'OAuthTokenError', 'message': 'PRIVATE_TOKEN'},
                       {'error_class': 'HTTPStatusError', 'http_status': 401,
                        'oauth_error': 'invalid_grant', 'url': 'PRIVATE_URL'},
                       {'error_class': 'PRIVATE_CLASS', 'http_status': True,
                        'oauth_error': 'PRIVATE_OAUTH'}]}}
        db.execute('INSERT INTO attempts VALUES(1,?)', (json.dumps(raw),))
        result = module.source_capture(db, 1)
        assert result == {'evidence_available': True, 'status': ['FAILED'], 'schemas_present': False,
                          'stage': 'CONNECT', 'truncated': False, 'causes': [
                              {'error_class': 'ExceptionGroup'},
                              {'error_class': 'OAuthTokenError'},
                              {'error_class': 'HTTPStatusError', 'http_status': 401, 'oauth_error': 'invalid_grant'},
                              {'error_class': 'OTHER_ERROR'}]}
        assert 'PRIVATE' not in json.dumps(result)
        db.execute("UPDATE attempts SET raw_json='{broken'")
        assert not module.source_capture(db, 1)['evidence_available']
        assert not module.source_capture(db, 2)['evidence_available']


def test_live_auth_block_is_specific_but_later_delivery_clears_current_diagnosis():
    result = {'runtime_evidence': {'heartbeat': 'FRESH', 'feed': 'STALE'},
              'current_runtime': [{'status': 'BLOCKED'}],
              'collector_failures': [{'sequence': 596, 'source_capture': {
                  'causes': [{'error_class': 'ReadAuthorizationRequired'}]}}],
              'latest_packet': {'sequence': 472}}
    assert module.operation(result, {'Status': 'running'})['reasons'] == ['READ_AUTHORIZATION_REQUIRED']
    result['latest_packet']['sequence'] = 597
    assert module.operation(result, {'Status': 'running'})['reasons'] == ['RUNTIME_FEED_STALE']
    assert module.operation(result, {'Status': 'exited', 'ExitCode': 0})['state'] == 'STOPPED'
