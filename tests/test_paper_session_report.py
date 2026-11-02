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


def test_running_or_unrelated_container_never_reads_account(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(module, "report", lambda *a: pytest.fail("Unexpected database read"))
    monkeypatch.setattr("sys.argv", ["report", "--run-id", "test-run"])
    for label, state, reason in [(None, "exited", "NOT_A_CONNECTED_SESSION"),
                                 ("bound", "running", "SESSION_NOT_FINISHED")]:
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
