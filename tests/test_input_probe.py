"""Evidence probes cannot widen the connected simulator's read capability."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from contextlib import asynccontextmanager

import pytest

from app.options import input_probe as probe, read_capture, read_worker, read_cli
from app.options.capability_inventory import build
from app.options.read_gateway import READ_TOOLS
from test_option_read_capture import metadata, oauth, request

AT = datetime(2026, 10, 30, 0, 1, tzinfo=timezone.utc)
ID = '11111111-1111-4111-8111-111111111111'
TOOLS = json.loads((Path(__file__).parent / 'fixtures/robinhood_input_probe_schemas.json').read_text())


def payloads():
    return {
        'get_equity_price_book': {'books': [
            {'symbol': 'SPY', 'updated_at': AT.isoformat(), 'bids': [{'price': '700.01', 'quantity': 20}],
             'asks': [{'price': '700.02', 'quantity': 10}]},
        ], 'errors': [{'symbol': 'QQQ', 'error': 'Market closed'}]},
        'get_earnings_calendar': {'results': []},
        'get_indexes': {'indexes': [{'id': ID, 'symbol': 'SPX', 'name': 'S&P 500',
            'current_value': '7000.01', 'trade_halted': False, 'updated_at': AT.isoformat()}]},
        'get_index_quotes': {'quotes': [{'instrument_id': ID, 'symbol': 'SPX', 'value': '7000.01',
            'state': 'active', 'updated_at': AT.isoformat(), 'venue_timestamp': AT.isoformat()}]},
        'get_index_historicals': {'results': [{'instrument_id': ID, 'symbol': 'SPX',
            'interval': '5minute', 'bars': [{'begins_at': AT.isoformat(), 'open_value': '7000',
                'close_value': '7000.01', 'low_value': '6999', 'high_value': '7001', 'interpolated': False}]}]},
    }


class Client:
    def __init__(self):
        self.calls = []
        self.tools = metadata() + list(deepcopy(TOOLS).values())
        self.data = payloads()

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        value = self.data[name]
        if isinstance(value, Exception):
            raise value
        return {'structuredContent': {'data': value, 'guide': 'schema evidence'}}


def run(client):
    observations = []
    report = asyncio.run(probe.run(client, build(client.tools, READ_TOOLS), AT, observations))
    return report, observations


def test_original_metadata_pins_and_fixed_read_only_sequence():
    client = Client()
    report, rows = run(client)
    assert client.calls == probe.initial_calls(AT) + probe.followup_calls(ID, AT)
    assert report['completed_reads'] == 5
    assert report['stock_books'][0]['best_bid']['quantity'] == 20
    assert report['stock_book_errors'] == ['QQQ']
    assert report['index_histories'][0]['bars'] == 1
    assert not report['earnings_is_complete_catalyst_coverage']
    assert not report['trading_ready'] and not report['runtime_policy_changed']
    assert not report['account_tradability_probed']
    assert client.calls[1][1]['start_date'] == '2026-10-29'  # Eastern date, not UTC date.
    assert all(row['output_schema_validated'] for row in rows)
    assert not (set(probe.PINS) & READ_TOOLS)


@pytest.mark.parametrize('name', list(probe.PINS))
def test_any_changed_pin_prevents_all_market_calls(name):
    client = Client()
    next(t for t in client.tools if t['name'] == name)['description'] += ' changed'
    with pytest.raises(ValueError, match='changed'):
        run(client)
    assert not client.calls


@pytest.mark.parametrize('mode', ['restricted', 'missing', 'duplicate', 'wrong_symbol', 'bad_id', 'halted'])
def test_ambiguous_unavailable_or_restricted_index_is_never_followed(mode):
    client = Client()
    data = client.data['get_indexes']
    if mode == 'restricted':
        data['restricted'] = [{'instrument_id': ID, 'symbol': 'SPX', 'message': 'Unavailable through this channel'}]
    elif mode == 'missing':
        data['indexes'] = []
    elif mode == 'duplicate':
        data['indexes'] *= 2
    elif mode == 'wrong_symbol':
        data['indexes'][0]['symbol'] = 'SPY'
    elif mode == 'bad_id':
        data['indexes'][0]['id'] = 'not-an-id'
    else:
        data['indexes'][0]['trade_halted'] = True
    report, rows = run(client)
    assert len(client.calls) == 3
    assert not report['spx_identity_resolved']
    if mode == 'restricted':
        assert report['restricted'][0]['message'] == 'Unavailable through this channel'


def test_restriction_in_quote_stops_history_without_retry():
    client = Client()
    client.data['get_index_quotes'] = {'quotes': [], 'restricted': [
        {'symbol': 'SPX', 'instrument_id': ID, 'message': 'Restricted index'}]}
    report, rows = run(client)
    assert len(client.calls) == 4 and not report['index_histories']
    assert report['restricted'][0]['tool'] == 'get_index_quotes'


def test_failed_book_does_not_hide_independent_earnings_and_index_evidence():
    client = Client()
    client.data['get_equity_price_book'] = ValueError('PRIVATE-TOKEN-DO-NOT-PRINT')
    report, rows = run(client)
    assert report['completed_reads'] == 4 and report['status'] == 'PARTIAL_CAPTURE'
    assert report['index_histories'][0]['bars'] == 1
    assert 'PRIVATE-TOKEN' not in json.dumps(rows)


def test_invalid_structured_output_retains_failure_not_false_success():
    client = Client()
    client.data['get_earnings_calendar'] = {'wrong': []}
    report, rows = run(client)
    assert not rows[1]['completed'] and report['status'] == 'PARTIAL_CAPTURE'


def test_parent_rejects_injected_tools_arguments_and_unbound_ids():
    _, rows = run(Client())
    for index, field, value in [(0, 'tool', 'get_accounts'), (0, 'arguments', {'symbols':['AAPL']}),
                                (3, 'arguments', {'instrument_ids':['different']})]:
        changed = deepcopy(rows)
        changed[index][field] = value
        with pytest.raises(ValueError):
            probe.validate_observations(changed, AT)


def connected(client, monkeypatch):
    @asynccontextmanager
    async def context():
        yield client
    class Connection:
        client = staticmethod(context)
    monkeypatch.setattr(read_worker, 'connection', lambda _: Connection())


def test_worker_probe_is_explicit_and_retains_private_original_payloads(tmp_path, monkeypatch):
    client = Client()
    connected(client, monkeypatch)
    req = request(tmp_path).model_copy(update={'operation':'INPUT_PROBE', 'started_at':AT})
    result = asyncio.run(read_worker.collect(req))
    assert result.status == 'COMPLETE' and result.inventory is None
    assert result.input_probe['completed_reads'] == 5
    assert result.observations[0]['raw']['structuredContent']['data']['books']
    assert set(result.schemas.tools) == READ_TOOLS
    assert all(name in probe.PINS for name, _ in client.calls)


def test_worker_partial_capture_is_failed_with_safe_report(tmp_path, monkeypatch):
    client = Client()
    client.data['get_earnings_calendar'] = ValueError('PRIVATE')
    connected(client, monkeypatch)
    req = request(tmp_path).model_copy(update={'operation':'INPUT_PROBE', 'started_at':AT})
    result = asyncio.run(read_worker.collect(req))
    assert result.status == 'FAILED' and result.error_class == 'InputProbeIncomplete'
    assert result.input_probe['completed_reads'] == 4
    assert 'PRIVATE' not in result.model_dump_json()


def test_probe_cannot_mix_with_inventory_or_user_selected_plan(tmp_path):
    req = request(tmp_path).model_dump()
    req['operation'] = 'INPUT_PROBE'
    req['include_inventory'] = True
    with pytest.raises(ValueError):
        read_capture.CaptureRequest.model_validate(req)
    req['include_inventory'] = False
    req['schemas'] = {'bad': 'schema'}
    with pytest.raises(ValueError):
        read_capture.CaptureRequest.model_validate(req)


def test_native_isolated_probe_and_cli_keep_originals_private(tmp_path, monkeypatch, capsys):
    from test_option_read_capture import native_connection_script, intercept_native

    tmp_path.chmod(0o700)
    script = native_connection_script(tmp_path)
    text = script.read_text().replace(repr(json.dumps(metadata())),
                                     repr(json.dumps(metadata() + list(TOOLS.values()))))
    text = text.replace("return {'isError':False,'structuredContent':{'rows':[]}}",
                        "return {'structuredContent':{'data':json.loads(" +
                        repr(json.dumps(payloads())) + ")[name],'guide':'fixture'}}")
    script.write_text(text)
    children = intercept_native(monkeypatch, script)
    destination = tmp_path / 'probe.json'
    assert read_cli.main(['input-probe', '--oauth-file', str(oauth(tmp_path)),
                          '--output', str(destination), '--timeout-seconds', '10']) == 0
    artifact = json.loads(destination.read_text())
    assert artifact['operation'] == 'input-probe'
    assert artifact['result']['operation'] == 'INPUT_PROBE'
    assert len(artifact['result']['observations']) == 5
    assert artifact['result']['input_probe']['completed_reads'] == 5
    assert artifact['result']['schemas']['sha256']
    assert destination.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert 'PRIVATE-TOKEN' not in output and 'structuredContent' not in output
    assert all(child.returncode == 0 for child in children)


def test_missing_reviewed_tool_fails_before_first_call():
    client = Client()
    client.tools = [t for t in client.tools if t['name'] != 'get_index_historicals']
    with pytest.raises(ValueError, match='missing'):
        run(client)
    assert not client.calls


def test_parent_rejects_truncated_success_and_extra_followup_after_restriction():
    _, rows = run(Client())
    with pytest.raises(ValueError, match='coverage'):
        probe.validate_observations(rows[:3], AT, complete=True)
    with pytest.raises(ValueError, match='coverage'):
        probe.validate_observations([], AT, complete=True)
    rows[3]['raw']['structuredContent']['data']['restricted'] = [
        {'instrument_id': ID, 'symbol': 'SPX', 'message': 'Unavailable'}]
    with pytest.raises(ValueError, match='coverage'):
        probe.validate_observations(rows, AT)


def test_oversized_provider_result_is_partial_not_an_unbounded_export():
    client = Client()
    client.data['get_earnings_calendar'] = {'results': [], 'oversize': 'x' * (129 * 1024)}
    report, rows = run(client)
    assert report['status'] == 'PARTIAL_CAPTURE'
    assert not rows[1]['completed'] and 'raw' not in rows[1]


def test_optional_interpolation_flag_is_unknown_not_false():
    client = Client()
    bars = client.data['get_index_historicals']['results'][0]['bars']
    bars.append(deepcopy(bars[0]) | {'interpolated': True})
    missing = deepcopy(bars[0])
    del missing['interpolated']
    bars.append(missing)
    report, rows = run(client)
    assert rows[-1]['completed']  # Omission is valid under the original provider schema.
    history = report['index_histories'][0]
    assert history['bars'] == 3
    assert history['interpolated_bars'] == 1
    assert history['noninterpolated_bars'] == 1
    assert history['interpolation_unknown_bars'] == 1
    assert not report['trading_ready']


def test_offline_report_recovers_failed_summary_without_auth_or_overwrite(tmp_path, monkeypatch, capsys):
    client = Client()
    client.data['get_equity_price_book'] = ValueError('PRIVATE')
    del client.data['get_index_historicals']['results'][0]['bars'][0]['interpolated']
    connected(client, monkeypatch)
    original_summary = probe.summary
    def broken_summary(rows):
        raise KeyError('interpolated')
    monkeypatch.setattr(probe, 'summary', broken_summary)
    req = request(tmp_path).model_copy(update={'operation':'INPUT_PROBE', 'started_at':AT})
    result = asyncio.run(read_worker.collect(req))
    assert result.status == 'FAILED' and result.input_probe is None
    assert sum(r['completed'] for r in result.observations) == 4
    source = tmp_path / 'probe.json'
    source.write_text(json.dumps({'operation':'input-probe', 'status':'FAILED',
                                 'result':result.model_dump(mode='json')}))
    source.chmod(0o600)
    before = source.read_bytes()
    monkeypatch.setattr(probe, 'summary', original_summary)
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline replay opened auth or started capture')
    monkeypatch.setattr(read_cli, 'private_oauth', forbidden)
    monkeypatch.setattr(read_cli, 'collect', forbidden)
    assert read_cli.main(['input-probe-report', '--source', str(source)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['original_capture_status'] == 'FAILED'
    assert output['original_error_class'] == 'KeyError'
    assert output['input_probe']['status'] == 'PARTIAL_CAPTURE'
    assert output['input_probe']['index_histories'][0]['interpolation_unknown_bars'] == 1
    assert not output['provider_reads'] and not output['credentials_opened']
    assert not output['state_modified'] and source.read_bytes() == before


def test_offline_report_rejects_missing_or_wrong_artifact(tmp_path, capsys):
    source = tmp_path / 'wrong.json'
    source.write_text('{}')
    source.chmod(0o600)
    assert read_cli.main(['input-probe-report', '--source', str(source)]) == 1
    assert json.loads(capsys.readouterr().out)['reason'] == 'SAVED_PROBE_REPORT_UNAVAILABLE'


def test_original_host_capture_recovers_four_reads_and_unknown_history_flags():
    from app.options.read_gateway import _validator
    evidence = json.loads((Path(__file__).parent / 'fixtures/robinhood_inputs_20261029.json').read_text())
    rows = evidence['observations']
    probe.validate_observations(rows, datetime.fromisoformat(evidence['started_at']))
    for row in rows:
        if row['completed']:
            _validator(TOOLS[row['tool']]['outputSchema']).validate(row['raw']['structuredContent'])
    report = probe.summary(rows)
    assert report['completed_reads'] == 4 and report['status'] == 'PARTIAL_CAPTURE'
    assert report['spx_identity_resolved'] and not report['restricted']
    assert report['index_quotes'][0]['instrument_id'] == '432fbbb8-b82c-454a-852d-eb85382c7066'
    assert report['index_quotes'][0]['value'] == '7720.39'
    history = report['index_histories'][0]
    assert (history['bars'], history['interpolated_bars'], history['noninterpolated_bars'],
            history['interpolation_unknown_bars']) == (288, 204, 0, 84)
    assert all(b['bid_levels'] == b['ask_levels'] == 0 for b in report['stock_books'])
    assert report['earnings_status'] == 'UNAVAILABLE' and report['earnings_events'] is None
    assert report['read_failures'][0]['response_issue'] == 'UNCLASSIFIED_FAILURE'
    assert not report['trading_ready']


@pytest.mark.parametrize('raw,category,retained', [
    ({'isError': True, 'content': [{'type':'text', 'text':'PRIVATE-PROVIDER-ERROR'}]}, 'PROVIDER_TOOL_ERROR', True),
    ({'isError':'false'}, 'MALFORMED_MCP_RESPONSE', True),
    ({'content': []}, 'STRUCTURED_OUTPUT_MISSING', True),
    ({'structuredContent':{'data':{}, 'guide':'PRIVATE'}}, 'OUTPUT_SCHEMA_MISMATCH', True),
    ({'oversized':'x'*(129*1024)}, 'RESPONSE_TOO_LARGE', False),
])
def test_response_rejection_categories_and_private_payload_retention(raw, category, retained):
    row = {'tool':'get_earnings_calendar', 'completed':False}
    with pytest.raises(Exception):
        probe.check_response(raw, TOOLS['get_earnings_calendar'], row, [row])
    assert row['response_issue'] == category
    assert isinstance(row['response_bytes'], int)
    assert ('rejected_raw' in row) == retained
    report = probe.summary([row])
    assert report['earnings_events'] is None
    assert 'PRIVATE' not in json.dumps(report)
    assert 'rejected_raw' not in json.dumps(report)


def test_aggregate_bound_and_non_json_response_never_store_unbounded_raw():
    row = {'tool':'get_earnings_calendar', 'completed':False}
    with pytest.raises(ValueError):
        probe.check_response({'ok':1}, TOOLS['get_earnings_calendar'], row, [{'padding':'x'*probe.MAX_PROBE_OBSERVATIONS_BYTES}])
    assert row['response_issue'] == 'AGGREGATE_RESPONSE_TOO_LARGE' and 'rejected_raw' not in row
    row = {'tool':'get_earnings_calendar', 'completed':False}
    with pytest.raises(ValueError):
        probe.check_response({'bad':float('nan')}, TOOLS['get_earnings_calendar'], row, [row])
    assert row['response_issue'] == 'NON_JSON_RESPONSE' and 'rejected_raw' not in row


def test_captured_empty_calendar_is_distinct_from_failed_or_null_calendar():
    client = Client()
    report, _ = run(client)
    assert report['earnings_events'] == 0 and report['earnings_status'] == 'CAPTURED'
    client.data['get_earnings_calendar'] = {'results':None}
    report, _ = run(client)
    assert report['earnings_events'] is None and report['earnings_status'] == 'UNAVAILABLE'
    assert not report['earnings_is_complete_catalyst_coverage']


def test_new_probe_uses_one_day_without_filter_or_expanding_response_bounds():
    from app.options.read_gateway import MAX_SAMPLE_BYTES
    client = Client()
    report, rows = run(client)
    assert rows[1]['arguments'] == {'start_date':'2026-10-29', 'days':1}
    assert report['earnings_window'] == rows[1]['arguments']
    assert MAX_SAMPLE_BYTES == 128 * 1024
    assert len(client.calls) == 5
    assert not report['earnings_is_complete_catalyst_coverage']


def test_large_book_probe_preserves_original_within_existing_process_envelope(tmp_path, monkeypatch):
    from app.options.read_gateway import encoded, MAX_SAMPLE_BYTES
    client = Client()
    original = client.call_tool
    retained = []

    async def large_book(name, arguments):
        raw = await original(name, arguments)
        if name == 'get_equity_price_book':
            raw['content'] = [{'type': 'text', 'text': 'x' * 484000}]
            assert MAX_SAMPLE_BYTES < len(encoded(raw)) < probe.MAX_BOOK_PROBE_BYTES
            retained.append(deepcopy(raw))
        return raw

    client.call_tool = large_book
    connected(client, monkeypatch)
    req = request(tmp_path).model_copy(update={'operation': 'INPUT_PROBE', 'started_at': AT})
    result = asyncio.run(read_worker.collect(req))
    assert result.status == 'COMPLETE'
    assert result.observations[0]['raw'] == retained[0]
    assert result.input_probe['completed_reads'] == 5
    assert not result.input_probe['trading_ready']
    assert len(result.model_dump_json().encode()) < read_capture.MAX_RESPONSE_BYTES
    assert MAX_SAMPLE_BYTES == 128 * 1024


def test_book_probe_remains_bounded_and_does_not_expand_other_tools():
    for tool, limit in [('get_equity_price_book', probe.MAX_BOOK_PROBE_BYTES),
                        ('get_earnings_calendar', 128 * 1024)]:
        row = {'tool': tool, 'completed': False}
        with pytest.raises(probe.InputProbeResponseError):
            probe.check_response({'padding': 'x' * limit}, TOOLS[tool], row, [row])
        assert row['response_issue'] == 'RESPONSE_TOO_LARGE'
        assert 'raw' not in row and 'rejected_raw' not in row


def test_legacy_seven_day_evidence_replays_but_cannot_satisfy_new_request():
    evidence = json.loads((Path(__file__).parent / 'fixtures/robinhood_inputs_20261029.json').read_text())
    rows = evidence['observations']; at = datetime.fromisoformat(evidence['started_at'])
    probe.validate_observations(rows, at)
    assert probe.summary(rows)['earnings_window']['days'] == 7
    with pytest.raises(ValueError, match='binding'):
        probe.validate_observations(rows, at, expected_calendar_days=1)
    changed = deepcopy(rows)
    changed[1]['arguments']['days'] = 3
    with pytest.raises(ValueError, match='reviewed'):
        probe.validate_observations(changed, at)
    changed[1]['arguments']['days'] = True
    with pytest.raises(ValueError, match='reviewed'):
        probe.validate_observations(changed, at)
