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


def test_report_snapshot_keeps_consistency_without_blocking_native_commits(tmp_path):
    path = tmp_path / 'native.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE receipts(value TEXT)')
        db.execute("INSERT INTO receipts VALUES('original')")
    report = module.connection(path)
    copy_path = Path(report.execute('PRAGMA database_list').fetchone()[2])
    try:
        assert report.execute('SELECT value FROM receipts').fetchone()[0] == 'original'
        with sqlite3.connect(path, timeout=.1) as writer:
            writer.execute("INSERT INTO receipts VALUES('later')")
        assert report.execute('SELECT COUNT(*) FROM receipts').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            report.execute("INSERT INTO receipts VALUES('forbidden')")
    finally:
        report.close()
    assert not copy_path.exists() and path.exists()


@pytest.mark.parametrize('limit', ['capacity', 'deadline'])
def test_failed_report_copy_cleans_private_scratch_and_preserves_native(tmp_path, monkeypatch, limit):
    path = tmp_path / 'native.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE receipts(value TEXT)')
        db.execute("INSERT INTO receipts VALUES('original')")
    before = path.read_bytes()
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    monkeypatch.setattr(module.tempfile, 'tempdir', str(scratch))
    monkeypatch.setattr(module, 'MAX_REPORT_SOURCE_BYTES' if limit == 'capacity' else 'REPORT_COPY_SECONDS', 0)
    with pytest.raises((ValueError, TimeoutError), match='REPORT_SOURCE_COPY_'):
        module.connection(path)
    assert not list(scratch.iterdir()) and path.read_bytes() == before


def test_short_report_has_exact_ny_spending_and_preserves_unknown_charges():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_model_calls(started_at,cost)')
        db.execute('CREATE TABLE execution_cost_policy(id,policy_json)')
        db.execute('INSERT INTO execution_cost_policy VALUES(1,?)',
                   (json.dumps({'daily_budget':'1','total_budget':'5','private':'PRIVATE_KEY'}),))
        db.executemany('INSERT INTO execution_model_calls VALUES(?,?)', [
            ('2026-11-05T04:59:00Z','0.1'), ('2026-11-05T05:01:00Z','0.000000001'),
            ('2026-11-05T05:02:00Z',None), ('2026-11-05T05:03:00Z','NaN'),
            ('2026-11-05T05:20:00Z','0.2')])
        before = db.total_changes
        paid = module.spending(db, '2026-11-05T05:00:00Z', '2026-11-05T05:10:00Z')
        assert paid['day']=='2026-11-05' and paid['status']=='INCOMPLETE'
        assert paid['costs']['run']=={'settled_cost':'0.000000001','unknown_calls':2}
        assert paid['costs']['day']['settled_cost']=='0.200000001'
        assert paid['costs']['account_total']['settled_cost']=='0.300000001'
        assert before == db.total_changes
    value = live_result()
    value.update(run_id='paper-example', account_total_fills=0, cycle_count=3,
                 model_spending=paid, private='PRIVATE_KEY', run_issues=['COLLECTOR_FAILURES_RECORDED'])
    value['operation'] = module.operation(value, {'Status':'exited','ExitCode':0})
    text = module.short_report(value)
    assert 'STOPPED' in text and 'Fills (account total): 0' in text
    assert 'run $0.000000001' in text and '/ $1' in text and '/ $5' in text
    assert 'unsettled/invalid calls (account): 2' in text
    assert 'PRIVATE' not in text and len(text)<8192
    assert 'COLLECTOR_FAILURES_RECORDED' in text


def test_short_report_explains_retained_all_skipped_run_and_successful_recoveries():
    value = live_result()
    value.update(decisions=[], decision_count=0, cycle_count=5, flat_feed_recoveries=2,
        reviewed_entry_resumes=3, collection=[{'status':'DELIVERED','attempts':21}, {'status':'FAILED','attempts':6}],
        collector_failures=[{'error_class':'TimeoutError'}],
        cycle_outcomes=[{'status':['SKIPPED'],'reason':['RUNTIME_SLOT_NOT_OBSERVED'],'count':2},
                        {'status':['SKIPPED'],'reason':['OPTION_RUNTIME_FEED_UNAVAILABLE'],'count':3}])
    value['operation'] = module.operation(value, {'Status':'exited','ExitCode':0})
    result = module.short_report(value)
    for expected in ('complete 0; skipped 5', 'OPTION_RUNTIME_FEED_UNAVAILABLE (3)',
                     'Feed recoveries: 2', 'delivered 21; failed 6',
                     'TimeoutError; read phase unavailable', 'DEGEN: no decision recorded; scan not established'):
        assert expected in result
    assert len(result) < 8192
    original = {'stage':'CAPTURE','error_class':'TimeoutError', 'read_progress':{
        'request_id':'a'*32,'stage':'DISCOVER','completed_reads':0,'private':'PRIVATE_TOKEN'}}
    sanitized = module.failure_evidence(json.dumps(original))
    assert sanitized['read_progress'] == {'stage':'DISCOVER','completed_reads':0}
    assert 'PRIVATE_TOKEN' not in json.dumps(sanitized)


def test_inventory_blocker_remains_missing_inputs_even_when_setups_are_watching():
    value = live_result()
    decision = value['decisions'][0]
    decision.update(reason=['NO_ADMITTED_CONTRACT'],
                    contract_exclusions=['NO_CONFIRMED_SETUP', 'INVENTORY_BINDING_COVERAGE_OR_FRESHNESS'])
    result = module.operation(value, {'Status': 'running'})
    assert result['state'] == 'MISSING_INPUTS'
    assert 'INVENTORY_BINDING_COVERAGE_OR_FRESHNESS' in result['reasons']
    value['operation'] = module.operation(value, {'Status': 'exited', 'ExitCode': 0})
    text = module.short_report(value)
    assert 'INVENTORY_BINDING_COVERAGE_OR_FRESHNESS' in text
    assert 'no input blocker reported' not in next(line for line in text.splitlines() if line.startswith('DEGEN:'))
    assert value['operation']['state'] == 'STOPPED'


@pytest.mark.parametrize('reason', ['AUTHORITATIVE_RECONCILIATION_REQUIRED', 'PORTFOLIO_PROTECTION_REQUIRED'])
def test_pre_scan_hold_is_not_a_successful_scan_or_waiting_setup(reason):
    value = live_result()
    value['decisions'][0].update(reason=[reason], scans=[], issues=[])
    value['operation'] = module.operation(value, {'Status': 'running'})
    assert value['operation']['state'] == 'MISSING_INPUTS'
    text = module.short_report(value)
    assert 'last decision did not record a scan' in text
    assert 'with scans 0; without scans 1' in text


def test_short_report_distinguishes_scan_coverage_and_all_retained_timeout_phases():
    value = live_result()
    value['decisions'] = [
        {'status':['HOLD'], 'reason':['AUTHORITATIVE_RECONCILIATION_REQUIRED'], 'scans':[]},
        {'status':['HOLD'], 'reason':['NO_ADMITTED_CONTRACT'], 'evidence_available': True,
         'contract_exclusions':['NO_CONFIRMED_SETUP', 'INVENTORY_BINDING_COVERAGE_OR_FRESHNESS'],
         'scans':[{'symbol':[symbol], 'issues':[], 'setups':[
             {'status':['WATCHING'], 'reasons':['VOLUME_CONFIRMATION_REQUIRED']} for _ in range(6)]}
                  for symbol in ('SPY', 'QQQ')]}]
    value['collector_failures'] = [{'error_class':'TimeoutError', 'read_progress':{'stage':phase}}
                                  for phase in ('SERIALIZE','DISCOVER','SERIALIZE','DISCOVER','CLOSE')]
    value['operation'] = module.operation(value, {'Status':'exited','ExitCode':0})
    text = module.short_report(value)
    for expected in ('with scans 1; without scans 1', 'confirmed 0; watching 12; blocked 0',
                     'VOLUME_CONFIRMATION_REQUIRED (12)', 'CLOSE (1)', 'DISCOVER (2)', 'SERIALIZE (2)'):
        assert expected in text
    assert len(text) < 8192


@pytest.mark.parametrize('clock_damage', [None, 'naive', 'future', 'invalid'])
def test_old_run_inventory_timing_uses_original_clocks_without_private_inputs_or_writes(clock_damage):
    source = '2026-11-06T15:30:10+00:00'
    received = '2026-11-06T15:30:11+00:00'
    evaluated = '2026-11-06T15:30:27+00:00'
    if clock_damage == 'naive': source = '2026-11-06T15:30:10'
    if clock_damage == 'future': source = '2026-11-06T15:30:30+00:00'
    if clock_damage == 'invalid': source = 'PRIVATE_NON_TIMESTAMP'
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_option_opportunities(cycle_key,result_json,inputs_json)')
        db.execute('CREATE TABLE execution_option_strategy(id,policy_json)')
        db.execute('INSERT INTO execution_option_strategy VALUES(1,?)',
                   (json.dumps({'selection':{'max_metadata_age_seconds':10}, 'secret':'PRIVATE_KEY'}),))
        result = {'status':'HOLD','reason':'NO_ADMITTED_CONTRACT',
                  'scans':[{'symbol':'SPY','evaluated_at':evaluated,'issues':[],'observations':[]}],
                  'read_plans':[{'issues':['INVENTORY_BINDING_COVERAGE_OR_FRESHNESS']}]}
        inputs = {'inventories':[{'symbol':'SPY','source_at':source,'received_at':received,
                                  'contracts':[{'instrument_id':'PRIVATE_ID'}]}], 'secret':'PRIVATE_KEY'}
        db.execute('INSERT INTO execution_option_opportunities VALUES(?,?,?)',
                   ('cycle',json.dumps(result),json.dumps(inputs)))
        before = db.total_changes
        saved = module.decision_evidence(db, 'cycle')
        assert db.total_changes == before
    assert 'PRIVATE' not in json.dumps(saved)
    if clock_damage in ('naive', 'invalid'):
        assert saved['inventory_timing'] == []
    else:
        timing, = saved['inventory_timing']
        assert timing['source_at'] == source and timing['evaluated_at'] == evaluated
        assert timing['source_age_seconds'] == (17 if clock_damage is None else -3)
        assert timing['clock_order_valid'] is (clock_damage is None)
        value = live_result()
        value['decisions'] = [saved]
        value['operation'] = module.operation(value, {'Status':'exited','ExitCode':0})
        text = module.short_report(value)
        assert 'limit <10s' in text
        if clock_damage is None:
            assert 'source age 17.000s' in text and 'receive lag 1.000s' in text


@pytest.mark.parametrize('reason', ['SCOPE_REFRESH_READ_BUDGET_UNAVAILABLE','SCOPE_REFRESH_COLLECTOR_BUSY'])
def test_short_report_exposes_scope_budget_rejection_without_overstating_peer_status(reason):
    value = live_result()
    value['decisions'][0]['scope_rejections'] = [reason]
    value['operation'] = module.operation(value, {'Status':'running'})
    text = module.short_report(value)
    assert reason in next(line for line in text.splitlines() if line.startswith('SCOPE:'))
    assert value['operation']['state']=='MISSING_INPUTS'
    assert 'AI spending: unavailable' in text and 'No trading-readiness claim' in text


def test_unknown_or_invalid_cost_clock_is_not_zero_spending():
    with sqlite3.connect(':memory:') as db:
        assert module.spending(db, '', '') == {'status':'UNAVAILABLE'}
        db.execute('CREATE TABLE execution_model_calls(started_at,cost)')
        db.execute("INSERT INTO execution_model_calls VALUES('bad','0.01')")
        assert module.spending(db, '2026-11-05T05:00:00Z','2026-11-05T06:00:00Z')['status']=='UNAVAILABLE'


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


def test_source_clock_round_trip_attribution_with_partial_and_fractional_fills():
    start, end = '2026-11-06T15:00:00+00:00', '2026-11-06T16:00:00+00:00'
    before, after = '2026-11-06T14:59:59Z', '2026-11-06T16:00:01Z'
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_portfolio_orders(play_id,client_id,order_id,observation_json)')
        def add(play, client, *receipts):
            order = 'order-' + client
            fills = [{'fill_id': str(n), 'sequence': n, 'order_id': order, 'occurred_at': at, 'quantity': qty}
                     for n, at, qty in receipts]
            from decimal import Decimal
            obs = {'order_id': order, 'client_id': client, 'side': 'BUY' if client == play else 'SELL',
                   'filled_quantity': str(sum(Decimal(q) for _, _, q in receipts)),
                   'instrument': {'instrument_id': 'same-symbol'}, 'fills': fills}
            db.execute('INSERT INTO execution_portfolio_orders VALUES(?,?,?,?)', (play, client, order, json.dumps(obs)))
        add('old', 'old', (1, before, '1'))
        add('new', 'new', (2, start, '0.1'), (3, start, '0.2'))
        add('old', 'close-old', (4, start, '1'))
        add('partial', 'partial', (5, start, '2'))
        add('partial', 'partial-exit', (6, end, '1'), (9, after, '1'))
        add('new', 'exit-a', (7, end, '0.2'))
        add('new', 'exit-b', (8, '2026-11-06T11:00:00-05:00', '0.1'))
        total, _, run = module.fill_evidence(db, start, end)
        assert total == 9
        assert run == {'status': 'RECORDED', 'entry_fills': 3, 'exit_fills': 4,
                       'completed_round_trips': 1, 'carry_in_exits': 1}
        assert module.fill_evidence(db, start, after)[2]['completed_round_trips'] == 2
        # Overlapping same-symbol plays cannot supply one another's entry or exit.
        db.execute("UPDATE execution_portfolio_orders SET play_id='different' WHERE client_id='exit-b'")
        assert module.fill_evidence(db, start, end)[2]['status'] == 'UNAVAILABLE'


@pytest.mark.parametrize('damage', ['duplicate_receipt', 'wrong_filled_quantity', 'missing_clock', 'wrong_order'])
def test_inconsistent_run_receipts_are_unknown(damage):
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_portfolio_orders(play_id,client_id,order_id,observation_json)')
        fill = {'fill_id': 'id', 'sequence': 1, 'order_id': 'o', 'quantity': 1, 'occurred_at': '2026-11-06T15:00:00Z'}
        obs = {'client_id': 'p', 'order_id': 'o', 'side': 'BUY', 'filled_quantity': 1,
               'instrument': {'instrument_id': 'contract'}, 'fills': [fill]}
        if damage == 'duplicate_receipt':
            obs['fills'].append(fill.copy())
        elif damage == 'wrong_filled_quantity':
            obs['filled_quantity'] = 2
        elif damage == 'missing_clock':
            del fill['occurred_at']
        else:
            fill['order_id'] = 'not-o'
        db.execute('INSERT INTO execution_portfolio_orders VALUES(?,?,?,?)', ('p','p','o',json.dumps(obs)))
        total, _, run = module.fill_evidence(db, '2026-11-06T15:00:00Z', '2026-11-06T16:00:00Z')
        assert total is None
        assert run == {'status': 'UNAVAILABLE', 'reason': 'RUN_FILL_EVIDENCE_INVALID'}
        assert 'Run execution: unavailable' in module.short_report({'run_execution': run})


@pytest.mark.parametrize('worker,exit_code,finish,classification,reason', [
    ('dead', 0, '2026-11-09T15:05:00Z', 'FAILED', 'CONTAINER_DEAD'),
    ('exited', 0, '2026-11-09T15:05:00Z', 'STOPPED', 'SESSION_ENDED_EARLY'),
    ('exited', 1, '2026-11-09T15:10:00Z', 'FAILED', 'CONTAINER_EXIT_NONZERO'),
    ('exited', 0, '2026-11-09T15:10:00Z', 'STOPPED', 'BOUNDED_SESSION_ENDED'),
    ('dead', 1, '0001-01-01T00:00:00Z', 'FAILED', 'CONTAINER_DEAD'),
    ('exited', 0, '0001-01-01T00:00:00Z', 'FAILED', 'SESSION_WINDOW_UNAVAILABLE'),
])
def test_terminal_report_uses_original_container_window_and_duration(
        monkeypatch, capsys, worker, exit_code, finish, classification, reason):
    from types import SimpleNamespace

    cmd = ['python', '-I', '-W', 'error', '-m', 'app.mixed.connected_runtime', 'run',
           '--seconds', '600']
    state = {'Status': worker, 'ExitCode': exit_code, 'StartedAt': '2026-11-09T15:00:00Z',
             'FinishedAt': finish}
    def inspect(*args, **kwargs):
        assert args[0][:2] == ['docker', 'inspect']
        return SimpleNamespace(returncode=0, stdout=json.dumps({'label': 'bound', 'cmd': cmd, 'state': state}))
    def report(directory, start, end):
        assert finish != '0001-01-01T00:00:00Z', 'invalid window must not read account journals'
        assert (start, end) == (state['StartedAt'], finish)
        return live_result()
    monkeypatch.setattr(module.subprocess, 'run', inspect)
    monkeypatch.setattr(module, 'report', report)
    monkeypatch.setattr('sys.argv', ['report', '--run-id', 'daily-20261109'])
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result['operation']['state'] == classification
    assert reason in result['operation']['reasons']
    assert result['operation']['container_running'] is False
    assert result['session_timing']['planned_seconds'] == 600
    if finish.startswith('0001'):
        assert result['session_timing']['elapsed_seconds'] is None
        assert 'SESSION_WINDOW_UNAVAILABLE' in result['run_issues']
        assert result.get('account_total_fills') is None
        text = module.short_report(result)
        assert 'totals are unknown' in text and 'delivered 0' not in text


@pytest.mark.parametrize('tail', [[], ['--seconds'], ['--seconds', '0'], ['--seconds', '86401'],
                                 ['--seconds', '60', '--seconds', '600']])
def test_ambiguous_duration_never_confirms_bounded_completion(tail):
    command = ['python', '-I', '-W', 'error', '-m', 'app.mixed.connected_runtime', 'run', *tail]
    timing = module.session_timing(command, '2026-11-09T15:00:00Z', '2026-11-09T21:00:00Z')
    assert timing == {'planned_seconds': None, 'elapsed_seconds': 21600}
    result = module.operation({'session_timing': timing}, {'Status': 'exited', 'ExitCode': 0})
    assert result['reasons'] == ['SESSION_DURATION_UNVERIFIED']


def test_report_explains_post_model_option_quote_check_without_dumping_market():
    value = live_result()
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE execution_option_opportunities(cycle_key,result_json)')
        raw = {'status': 'HOLD', 'reason': 'OPTION_EXECUTION_MARKET_UNAVAILABLE',
               'blocker': 'CONFLICTING_OPTION_SOURCE_BOOK', 'option_market_sequence': 88}
        db.execute('INSERT INTO execution_option_opportunities VALUES(?,?)', ('test', json.dumps(raw)))
        decision = module.decision_evidence(db, 'test')
        value['decisions'] = [decision]
        value['operation'] = module.operation(value, {'Status': 'running'})
        assert value['operation']['state'] == 'MISSING_INPUTS'
        assert 'Option entry checked feed 88: CONFLICTING_OPTION_SOURCE_BOOK' in module.short_report(value)
        raw.update(reason='ORIGINAL_PRICE_CEILING_EXCEEDED', entry_review={'reasons': ['ORIGINAL_PRICE_CEILING_EXCEEDED']})
        del raw['blocker']
        db.execute('UPDATE execution_option_opportunities SET result_json=?', (json.dumps(raw),))
        value['decisions'] = [module.decision_evidence(db, 'test')]
        assert 'Option entry checked feed 88: ORIGINAL_PRICE_CEILING_EXCEEDED' in module.short_report(value)



def test_expired_scan_lease_reports_missing_timely_input():
    value = live_result()
    value['decisions'] = [{'status': ['HOLD'], 'reason': ['ENTRY_PLAN_EXPIRED_BEFORE_MODEL'],
                           'scans': [{'symbol': ['SPY']}], 'evidence_available': True}]
    operation = module.operation(value, {'Status': 'running'})
    assert operation['state'] == 'MISSING_INPUTS'
    assert operation['reasons'] == ['ENTRY_PLAN_EXPIRED_BEFORE_MODEL']


def test_mixed_scan_family_issues_stay_with_their_own_strategy():
    decision = module.outcome(json.dumps({'status':'HOLD', 'scans': [
        {'version':'degen-completed-bars-v1', 'symbol':'QQQ', 'observations':[]},
        {'version':'swing-next-session-v1', 'symbol':'SPY', 'issues':['SWING_SEED_INVALIDATED'],
         'observations':[]},
    ]}))
    result = live_result()
    result['accepted_packet']['coverage_issues'] = ['SCOPE_CURRENT_INPUT_UNAVAILABLE']
    result['decisions'] = [decision]
    result['operation'] = module.operation(result, {'Status':'exited','ExitCode':2})
    text = module.short_report(result).splitlines()
    assert result['operation']['family_input_issues']['SWING'] == ['SWING_SEED_INVALIDATED']
    assert 'SWING_' not in next(line for line in text if line.startswith('DEGEN:'))
    assert 'SWING: SWING_SEED_INVALIDATED' in text


@pytest.mark.parametrize('payload,expected', [
    ({'status':'UNAVAILABLE', 'live_enabled':False, 'failures':[{'component':'COLLECTOR',
      'error_class':'TimeoutError','private':'credentials', 'frames':[{'file':'app/mixed/continuous_feed.py','line':11}]}]},
     [{'component':'COLLECTOR','error_class':'TimeoutError','frames':[{'file':'app/mixed/continuous_feed.py','line':11}]}]),
    ({'status':'UNAVAILABLE','live_enabled':False,'reason':'CONNECTED_RUNTIME_UNAVAILABLE',
      'failure':{'error_class':'ValueError', 'frames':[{'file':'/private/token','line':20}]}},
     [{'component':'WORKER','error_class':'ValueError','frames':[]}]),
    ({'status':'SESSION_STARTED', 'failures':[{'component':'COLLECTOR'}]}, []),
])
def test_final_log_report_projects_bounded_failure_fields(monkeypatch, payload, expected):
    from types import SimpleNamespace
    def logs(argv, *, stdout, stderr, timeout):
        assert argv == ['docker','logs','--tail','1','a'*64]
        stdout.write(json.dumps(payload).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', logs)
    assert module.terminal_failures('a'*64) == expected
    assert module.terminal_failures('daily-20261109') == []

def test_approved_entry_freshness_uses_original_reservations_and_reports_missing_evidence():
    from datetime import UTC, datetime, timedelta

    first = datetime(2026, 10, 28, 14, tzinfo=UTC)
    end = first + timedelta(hours=1)
    db = sqlite3.connect(':memory:')
    try:
        def measure():
            return module.entry_freshness(db, first.isoformat(), end.isoformat())

        assert measure()['status'] == 'UNAVAILABLE'
        db.execute('CREATE TABLE execution_events(sequence INTEGER PRIMARY KEY,kind TEXT,'
                   'occurred_at TEXT,client_id TEXT,payload TEXT)')
        db.execute('CREATE TABLE execution_portfolio_orders(client_id TEXT PRIMARY KEY,play_id TEXT,'
                   'asset TEXT,intent_json TEXT,approval_json TEXT)')

        def reserve(client, asset, side, at, age):
            ident = {'instrument_id': asset + '-example'}
            intent = {'instrument': ident, 'client_id': client, 'side': side, 'prepared_at': at.isoformat()}
            approval = {'admission': {'outcome': 'APPROVED'}, 'inputs': {
                'proposal': {'action': 'OPEN_LONG' if side == 'BUY' else 'CLOSE'},
                'quote': {'source_at': (at - timedelta(seconds=age)).isoformat(),
                          'received_at': (at - timedelta(seconds=age - 1)).isoformat(),
                          'instrument': ident},
            }}
            db.execute('INSERT INTO execution_portfolio_orders VALUES(?,?,?,?,?)',
                       (client, client if side == 'BUY' else 'previous-play', asset,
                        json.dumps(intent), json.dumps(approval)))
            db.execute('INSERT INTO execution_events VALUES(NULL,?,?,?,?)',
                       ('PORTFOLIO_RESERVED', at.isoformat(), client,
                        json.dumps({'play_id': client if side == 'BUY' else 'previous-play', 'approval': approval})))

        reserve('prior', 'OPTION', 'BUY', first - timedelta(days=1), 99)
        reserve('exit', 'STOCK', 'SELL', first, 59)
        assert measure()['status'] == 'NO_ENTRIES'
        reserve('first', 'STOCK', 'BUY', first, 2)
        reserve('second', 'OPTION', 'BUY', end, 6)
        good = measure()
        assert good['status'] == 'OBSERVED' and good['reservations'] == good['measured'] == 2
        assert good['clocks']['quote_age'] == {
            'samples': 2, 'p50_seconds': 2, 'p95_seconds': 6, 'p99_seconds': 6, 'max_seconds': 6
        }
        assert good['clocks']['receive_lag']['max_seconds'] == 1
        assert good['clocks']['local_age']['max_seconds'] == 5
        db.execute("UPDATE execution_portfolio_orders SET approval_json=json_set(approval_json, "
                   "'$.inputs.quote.source_at', '$.changed') WHERE client_id='second'")
        db.execute("INSERT INTO execution_events VALUES(NULL,'PORTFOLIO_RESERVED',?,'lost','{}')", (first.isoformat(),))
        partial = measure()
        assert (partial['status'], partial['reservations'], partial['measured'],
                partial['missing_or_invalid']) == ('PARTIAL', 3, 1, 2)
        db.execute("INSERT INTO execution_events VALUES(NULL,'PORTFOLIO_RESERVED',?,'first','{}')", (first.isoformat(),))
        assert measure()['measured'] == 0 and measure()['missing_or_invalid'] == 3
    finally:
        db.close()
