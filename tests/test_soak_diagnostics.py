import json
import sqlite3
from datetime import timedelta

import pytest
from soak_diagnostics import entry_diagnostic, resource_window, resources
from soak_restore_profile import OpeningRestoreProfile
from soak_worker import BASE


def test_rejected_original_quote_clocks_and_phase_costs_are_retained_without_writes(tmp_path):
    path = tmp_path / 'options.db'
    key = 'degen:5977320:portfolio:0'
    quote = {'source_at': '2026-10-28T14:00:19.848382Z',
             'received_at': '2026-10-28T14:00:20.848382Z'}
    deadline = '2026-10-28T14:00:29.848382Z'
    packet = {'cycle_key': key, 'as_of': '2026-10-28T14:00:27.463707Z', 'valid_until': deadline,
              'account': {'captured_at': '2026-10-28T14:00:24.014596Z'},
              'limits': {'quote_max_age_seconds': 10, 'account_max_age_seconds': 20},
              'opportunities': [{'quote': quote, 'candidate': {'admission': {'valid_until': deadline}}}]}
    evidence = {'entry_request': {'packet': packet}, 'status': 'HOLD',
                'entry_completed_at': '2026-10-28T14:00:29.512833+00:00',
                'entry_review_at': '2026-10-28T14:00:30.471192+00:00',
                'reason': 'ORIGINAL_PLAN_DEADLINE_EXPIRED'}
    timing = {'kind': 'CYCLE', 'slot': 5977320, 'status': 'COMPLETE',
              'spans': [{'phase': 'ENTRY_MODEL_SETTLEMENT', 'elapsed_seconds': .934584}]}
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE execution_option_opportunities(cycle_key,started_at,status,result_json)')
        db.execute('CREATE TABLE execution_runtime_timings(id,started_at,payload_json)')
        db.execute('INSERT INTO execution_option_opportunities VALUES(?,?,?,?)',
                   (key, '2026-10-28T14:00:25.541753+00:00', 'COMPLETE', json.dumps(evidence)))
        db.execute('INSERT INTO execution_runtime_timings VALUES(1,?,?)',
                   ('2026-10-28T14:00:25.461144+00:00', json.dumps(timing)))
    before = path.read_bytes()
    profile = OpeningRestoreProfile(BASE, [100.])
    profile.spans = [(129.5, 130.4, .7, True, 'settlement')]
    result = entry_diagnostic(path, key, profile)
    assert result['status'] == 'RECORDED' and result['decision_status'] == 'HOLD'
    assert result['reason'] == 'ORIGINAL_PLAN_DEADLINE_EXPIRED'
    assert result['clocks']['options'][0] == {**quote, 'admission_deadline': deadline}
    assert result['clocks']['review_at'] == evidence['entry_review_at']
    assert result['cycle_timing']['spans'] == timing['spans']
    assert result['restore_to_review']['owner_thread_calls'] == {'settlement': 1}
    assert result['restore_to_review']['window_seconds'] == 10.62281
    assert path.read_bytes() == before
    assert entry_diagnostic(path, 'another-cycle')['status'] == 'PENDING'


def test_missing_diagnostics_do_not_invent_resource_health_or_create_database(tmp_path):
    path = tmp_path / 'absent.db'
    assert entry_diagnostic(path, None)['status'] == 'PENDING'
    assert entry_diagnostic(path, 'fixture')['status'] == 'UNAVAILABLE'
    assert not path.exists()
    sample = resources(tmp_path)
    assert all(sample[k]['status'] == 'UNAVAILABLE' for k in ('cpu', 'io', 'memory'))


def test_cpu_quota_throttling_and_io_counter_window(tmp_path):
    (tmp_path / 'cpu.max').write_text('100000 100000')
    (tmp_path / 'cpu.stat').write_text('usage_usec 500\nnr_periods 3\nnr_throttled 1\nthrottled_usec 200')
    (tmp_path / 'io.stat').write_text('8:0 rbytes=100 wbytes=200 rios=1 wios=2')
    start = resources(tmp_path)
    (tmp_path / 'cpu.stat').write_text('usage_usec 1500\nnr_periods 5\nnr_throttled 2\nthrottled_usec 600')
    (tmp_path / 'io.stat').write_text('8:0 rbytes=300 wbytes=500 rios=2 wios=4')
    end = resources(tmp_path)
    window = resource_window(start, end)
    assert end['cpu']['quota_usec'] == end['cpu']['period_usec'] == 100000
    assert window['cpu']['counters'] == {'usage_usec': 1000, 'nr_periods': 2,
                                       'nr_throttled': 1, 'throttled_usec': 400}
    assert window['io']['devices']['8:0']['counters']['wbytes'] == 300
    assert window['start'] == start and window['end'] == end
    assert resource_window(end, start)['cpu']['status'] == 'UNAVAILABLE'
    (tmp_path / 'cpu.max').write_text('200000 100000')
    (tmp_path / 'io.stat').write_text('8:1 wbytes=400')
    changed = resource_window(start, resources(tmp_path))
    assert changed['cpu']['status'] == changed['io']['status'] == 'UNAVAILABLE'


@pytest.mark.parametrize('raw', ['0 100000', '-1 100000', 'invalid', '100000 0'])
def test_invalid_cpu_limit_is_explicitly_unavailable(tmp_path, raw):
    (tmp_path / 'cpu.max').write_text(raw)
    assert resources(tmp_path)['cpu']['status'] == 'UNAVAILABLE'


def test_failed_decision_profile_refuses_truncated_or_retimed_window():
    profile = OpeningRestoreProfile(BASE, [100.])
    profile.first_omitted = 120
    assert profile.original_window(BASE, BASE + timedelta(seconds=30))['status'] == 'UNMEASURED'
    assert profile.original_window(BASE - timedelta(seconds=1), BASE)['status'] == 'UNMEASURED'
