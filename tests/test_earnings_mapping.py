"""Company calendars retain partial coverage, duplicates and original decimal values."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from app.options.earnings_mapping import map_calendar, mapping_summary, digest
from app.options import read_cli
from app.options.read_capture import CaptureResult
from app.options.input_probe import PINS, initial_calls

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/robinhood_earnings_20261029.json').read_text())


def receipt():
    return deepcopy(FIXTURE['receipt'])


def set_rows(row, rows):
    row['raw']['structuredContent']['data']['results'] = rows
    # Tests of transformed semantic edge cases use only the modified structured payload.
    row['raw'].pop('content', None)
    return row


def test_original_provider_calendar_preserves_334_rows_and_conflicting_identity():
    source = receipt(); before = deepcopy(source)
    mapped = map_calendar(source); report = mapping_summary(mapped)
    assert source == before
    assert report['record_count'] == 334 and report['unique_company_quarters'] == 333
    assert report['reported_records'] == 309 and report['actual_eps_missing_records'] == 25
    assert report['issue_counts'] == {'CONFLICTING_EVENT_IDENTITY':2,
                                      'REPORT_DATE_TENTATIVE':19, 'REPORT_TIMING_UNKNOWN':3}
    assert mapped['provider_updated_at'] is None and mapped['entitlement'] == 'UNKNOWN'
    assert not mapped['complete_catalyst_coverage'] and not mapped['trading_ready']
    assert mapped['window_start'] == '2026-10-29' and mapped['window_end_exclusive'] == '2026-10-30'
    tte = [r for r in mapped['records'] if r['observation']['symbol'] == 'TTE']
    assert len(tte) == 2 and {r['observation']['report']['timing'] for r in tte} == {None,'am'}
    assert all('CONFLICTING_EVENT_IDENTITY' in r['issues'] for r in tte)
    raw = source['raw']['structuredContent']['data']['results']
    assert all(r['original_row_sha256'] == digest(raw[r['ordinal']]) for r in mapped['records'])
    assert mapped['records'][0]['observation']['eps']['actual'] == '0.580000'
    assert not any(r['observation']['symbol'] in ('SPY','QQQ') for r in mapped['records'])
    assert 'CLEAR' not in json.dumps(mapped)


def test_empty_null_and_failed_calendar_remain_distinct():
    row = receipt()
    empty = map_calendar(set_rows(row, []))
    assert empty['status'] == 'MAPPED' and mapping_summary(empty)['record_count'] == 0
    assert not empty['complete_catalyst_coverage']
    null = map_calendar(set_rows(row, None))
    assert null['status'] == 'UNAVAILABLE' and mapping_summary(null)['record_count'] is None
    row['completed'] = False; row.pop('raw')
    failed = map_calendar(row)
    assert failed['issues'] == ['EARNINGS_CAPTURE_FAILED'] and failed['records'] == []


def test_missing_dates_unknown_timing_and_out_of_window_are_explicit():
    source = receipt(); base = source['raw']['structuredContent']['data']['results'][0]
    rows = [deepcopy(base) for _ in range(3)]
    rows[0]['report'] = None
    rows[1]['report']['date'] = '2026-10-30'
    rows[1]['report']['timing'] = 'unspecified'
    rows[2]['report']['date'] = None
    result = map_calendar(set_rows(source, rows + [None]))
    assert 'NULL_EARNINGS_ROW' in result['issues']
    assert 'REPORT_DATE_UNAVAILABLE' in result['issues']
    assert 'REPORT_OUTSIDE_REQUESTED_WINDOW' in result['issues']
    assert 'REPORT_TIMING_UNKNOWN' in result['issues']
    assert len(result['records']) == 4 and not result['trading_ready']


def test_exact_duplicate_is_preserved_separately_from_conflicting_duplicate():
    source = receipt(); row = source['raw']['structuredContent']['data']['results'][0]
    result = map_calendar(set_rows(source, [row,deepcopy(row)]))
    assert len(result['records']) == 2
    assert all('REPEATED_EVENT_IDENTITY' in r['issues'] for r in result['records'])
    assert 'CONFLICTING_EVENT_IDENTITY' not in result['issues']


@pytest.mark.parametrize('field,value', [('metadata_sha256','0'*64), ('completed','true'),
                                         ('output_schema_validated',False)])
def test_unreviewed_or_unvalidated_receipt_cannot_become_mapped(field,value):
    row=receipt();row[field]=value
    if field == 'completed':
        assert map_calendar(row)['status'] == 'UNAVAILABLE'
    else:
        with pytest.raises(ValueError):map_calendar(row)


@pytest.mark.parametrize('fault',['float_eps','nan_eps','bad_quarter','bool_verified','reversed_clock','filtered_window'])
def test_invalid_precision_identity_or_source_binding_rejected(fault):
    row=receipt(); item=row['raw']['structuredContent']['data']['results'][0]
    if fault == 'float_eps':item['eps']['actual']=0.58
    elif fault == 'nan_eps':item['eps']['actual']='NaN'
    elif fault == 'bad_quarter':item['quarter']=5
    elif fault == 'bool_verified':item['report']['verified']='true'
    elif fault == 'reversed_clock':row['received_at']='2000-01-01T00:00:00+00:00'
    else:row['arguments']['filter']='high_market_cap'
    with pytest.raises(ValueError):map_calendar(row)


def test_offline_export_is_create_only_private_and_never_opens_auth(tmp_path,monkeypatch,capsys):
    tmp_path.chmod(0o700)
    at=datetime.fromisoformat(FIXTURE['started_at'])
    calls=initial_calls(at)
    rows=[{'tool':n,'arguments':a,'metadata_sha256':PINS[n],'completed':False} for n,a in calls]
    rows[1]=receipt()
    result=CaptureResult(request_id='a'*32, policy_sha256='b'*64, operation='INPUT_PROBE',
                         started_at=at,collected_at=at+timedelta(seconds=10),elapsed_seconds=10,
                         status='FAILED',error_class='InputProbeIncomplete',observations=rows)
    source=tmp_path/'probe.json';source.write_text(json.dumps({'operation':'input-probe',
        'result':result.model_dump(mode='json')}));source.chmod(0o600)
    before=source.read_bytes(); output=tmp_path/'earnings.json'
    def forbidden(*args,**kwargs):raise AssertionError('Network/auth in offline mapping')
    monkeypatch.setattr(read_cli,'private_oauth',forbidden)
    monkeypatch.setattr(read_cli,'collect',forbidden)
    assert read_cli.main(['export-earnings','--source',str(source),'--output',str(output)])==0
    report=json.loads(capsys.readouterr().out)
    assert report['mapping']['record_count']==334 and not report['provider_reads']
    assert output.stat().st_mode & 0o777 == 0o600 and source.read_bytes()==before
    saved=output.read_bytes(); assert len(json.loads(saved)['records'])==334
    assert read_cli.main(['export-earnings','--source',str(source),'--output',str(output)])==1
    assert output.read_bytes()==saved
