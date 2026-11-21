"""Synthetic context plus retained contract/quote fixtures; no provider calls."""
import copy
import json
from decimal import Decimal
from pathlib import Path
from datetime import date

import pytest
from test_contract_catalog import captures as captures  # noqa: PLC0414
from test_read_schema_contract import (
    bar_limit_schemas as bar_limit_schemas,  # noqa: PLC0414
    date_and_chain_schemas as date_and_chain_schemas,  # noqa: PLC0414
    future_description_schemas as future_description_schemas,  # noqa: PLC0414
)
from test_read_schema_contract import (
    description_schemas as description_schemas,  # noqa: PLC0414
)
from test_read_schema_contract import (
    interval_description_schemas as interval_description_schemas,  # noqa: PLC0414
)
from test_robinhood_read_mapping import equity
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed.session_capture import collect, contract_plan, plan, listed_strike, MAX_STRIKE_PAGES


@pytest.mark.parametrize('updated_description', [False, True])
def test_capture_cli_binds_each_call_to_actual_reviewed_discovery(
        tmp_path, monkeypatch, schemas, description_schemas, updated_description):
    import json
    from datetime import UTC, datetime

    from test_schema_artifact import artifact

    from app.mixed import session_capture
    from app.options import read_cli
    selected = description_schemas if updated_description else schemas
    source = tmp_path / 'discovery.json'
    source.write_text(json.dumps(artifact(selected)))
    source.chmod(0o600)
    output = tmp_path / 'capture'
    output.mkdir(mode=0o700)
    monkeypatch.setattr('app.domain.models.utc_now', lambda: datetime(2026, 11, 4, 22, tzinfo=UTC))
    calls = []
    def capture(args):
        calls.append(args)
        assert args[args.index('--schema-sha256') + 1] == selected.sha256
        assert args[args.index('--schemas') + 1] == str(source)
        Path(args[args.index('--output') + 1]).write_text('{"fixture":true}')
        return 0
    from pathlib import Path
    monkeypatch.setattr(read_cli, 'main', capture)
    def catalog(target, capture, **kwargs):
        assert target == date(2026, 11, 5)
        assert capture('context', {}) == {'fixture': True}
        return {'status': 'CATALOG_CAPTURED', 'fixture': True}
    monkeypatch.setattr(session_capture, 'collect', catalog)
    assert session_capture.main(['--target-session', '2026-11-05', '--directory', str(output),
        '--schemas', str(source), '--oauth-file', '/never-opened']) == 0
    assert len(calls) == 1


def context(captures):
    artifact = copy.deepcopy(captures[0])
    calls = [{"label": "equities", "tool": "get_equity_quotes", "arguments": {"symbols": ["SPY", "QQQ"]}}]
    quotes, listings = [], []
    for symbol, price, observation in zip(("SPY", "QQQ"), ("760", "705"),
                                         captures[0]["result"]["observations"], strict=True):
        q = equity(symbol)
        q.update(bid_price=price, ask_price=str(int(price) + .02))
        quotes.append({"quote": q})
        row = observation["raw"]["structuredContent"]["data"]["instruments"][0]
        listings.append({"chains": [{
            "id": row["chain_id"], "symbol": symbol, "can_open_position": True,
            "cash_component": None, "expiration_dates": ["2026-10-28"],
            "trade_value_multiplier": "100", "underlying_instruments": [],
            "min_ticks": row["min_ticks"], "late_close_state": "enabled",
            "extended_hours_state": "disabled", "settle_on_open": False,
            "sellout_time_to_expiration": 900,
        }]})
        calls.append({"label": symbol.lower() + "-chains", "tool": "get_option_chains",
                      "arguments": {"underlying_symbol": symbol}})
    artifact["result"]["plan"] = plan(calls)
    artifact["result"]["observations"] = [
        {"completed": True, "label": c["label"], "tool": c["tool"],
         "raw": {"isError": False, "structuredContent": {"data": data, "guide": ""}}}
        for c, data in zip(calls, [{"results": quotes}, *listings], strict=True)
    ]
    return artifact


@pytest.mark.parametrize("future_quote", [False, True])
@pytest.mark.parametrize("revision", [None, "interval_description_schemas", "date_and_chain_schemas",
                                      "bar_limit_schemas", "future_description_schemas"])
def test_capture_sequence_produces_reviewable_symbol_catalog(
        captures, future_quote, revision, request):
    if revision:
        observed = request.getfixturevalue(revision)
        for artifact in captures:
            artifact["result"]["schemas"] = observed.model_dump(mode="json")
    if future_quote:
        from datetime import datetime, timedelta
        received = datetime.fromisoformat(captures[2]["result"]["collected_at"])
        captures[2]["result"]["observations"][0]["raw"]["structuredContent"]["data"]["results"][0]["quote"]["updated_at"] = (
            received + timedelta(microseconds=545227)
        ).isoformat()
    seen, pauses = [], []
    source = context(captures)

    def reader(name, request):
        seen.append((name, request))
        if name == "context":
            assert request == source["result"]["plan"]
            return source
        artifact = copy.deepcopy(captures[0] if name == "contracts-probe" else captures[int(name[-1])])
        artifact["result"]["plan"] = request
        return artifact

    result = collect(date(2026, 10, 28), reader, pause=pauses.append)
    assert result["status"] == "CATALOG_CAPTURED"
    assert result["provider_tool_calls"] == sum(len(p["calls"]) for _, p in seen) == 8
    assert len(result["option_candidates"]) == 4 and pauses == [5, 5]
    assert not result["trading_ready"] and not result["workers_started"]
    assert bool(result["future_quote_samples"]) is future_quote
    assert result["all_fresh_at_capture"] is not future_quote
    assert [a["strike"] for a in result["anchors"]] == ["760", "705"]
    for c in seen[1][1]["calls"]:
        assert set(c["arguments"]) == {"chain_symbol", "expiration_dates", "strike_price"}


@pytest.mark.parametrize("problem", ["missing_expiry", "duplicate_chain", "crossed", "missing_quote", "partial"])
def test_context_refuses_ambiguous_or_missing_inputs(captures, problem):
    value = context(captures)
    observations = value["result"]["observations"]
    chain = observations[1]["raw"]["structuredContent"]["data"]["chains"][0]
    quotes = observations[0]["raw"]["structuredContent"]["data"]["results"]
    if problem == "missing_expiry":
        chain["expiration_dates"] = []
    elif problem == "duplicate_chain":
        observations[1]["raw"]["structuredContent"]["data"]["chains"].append(copy.deepcopy(chain))
    elif problem == "crossed":
        quotes[0]["quote"]["bid_price"] = "900"
    elif problem == "missing_quote":
        quotes.pop()
    else:
        observations[1]["completed"] = False
    with pytest.raises(ValueError):
        contract_plan(value, date(2026, 10, 28))


@pytest.mark.parametrize("problem", ["empty", "pagination", "wrong_chain", "untradable", "wrong_expiry"])
def test_bad_contract_probe_stops_before_quotes(captures, problem):
    seen = []

    def reader(name, request):
        seen.append(name)
        if name == "context":
            return context(captures)
        value = copy.deepcopy(captures[0])
        value["result"]["plan"] = request
        page = value["result"]["observations"][0]["raw"]["structuredContent"]["data"]
        if problem == "empty":
            page["instruments"] = []
        elif problem == "pagination":
            page["next"] = "more"
        else:
            key, bad = {"wrong_chain": ("chain_id", "different"),
                        "untradable": ("tradability", "untradable"),
                        "wrong_expiry": ("expiration_date", "2026-10-29")}[problem]
            page["instruments"][0][key] = bad
        return value

    with pytest.raises(ValueError):
        collect(date(2026, 10, 28), reader, pause=lambda _: pytest.fail("Unexpected pause"))
    assert seen[:2] == ["context", "contracts-probe"]
    assert not any(name.startswith('quotes') for name in seen)


def fallback_reader(captures, *, damage=None, empty_symbols=('SPY', 'QQQ')):
    """Synthetic sparse strike grid: both rounded probes are empty on the incident path."""
    seen, artifacts = [], {}
    def reader(name, request):
        seen.append((name, copy.deepcopy(request)))
        if name == 'context':
            result = context(captures)
        elif name.startswith('quotes'):
            result = copy.deepcopy(captures[int(name[-1])])
        else:
            result = copy.deepcopy(captures[0])
            records = {s: copy.deepcopy(o) for s, o in zip(('SPY', 'QQQ'), result['result']['observations'])}
            observations = []
            for call in request['calls']:
                symbol = call['label'].split('-')[0].upper()
                observation = records[symbol]
                observation.update(label=call['label'], tool=call['tool'])
                page = observation['raw']['structuredContent']['data']
                if name == 'contracts-probe' and symbol in empty_symbols:
                    page['instruments'] = []
                elif '-strikes-' in name:
                    row = next(r for r in page['instruments'] if r['type'] == 'call')
                    row['strike_price'] = '760.5' if symbol == 'SPY' else '705.5'
                    page['instruments'] = [row]
                    if damage == 'empty':
                        page['instruments'] = []
                    elif damage == 'wrong_chain':
                        row['chain_id'] = 'different'
                    elif damage == 'wrong_expiry':
                        row['expiration_date'] = '2026-10-29'
                    elif damage == 'wrong_right':
                        row['type'] = 'put'
                    elif damage == 'untradable':
                        row['tradability'] = 'untradable'
                    elif damage == 'duplicate':
                        page['instruments'] *= 2
                    elif damage == 'oversized':
                        page['instruments'] *= 257
                    elif damage in ('paginated', 'page_limit', 'cursor_loop'):
                        n = int(name.rsplit('-', 1)[1])
                        row['id'] = f'00000000-0000-4000-8000-{n:012d}'
                        if n == 1 or damage != 'paginated':
                            page['next'] = 'first' if damage == 'cursor_loop' else f'page-{n}'
                        else:
                            page.pop('next', None)
                        if n == 1:
                            row['strike_price'] = '750' if symbol == 'SPY' else '695'
                elif name == 'contracts-selected':
                    for row in page['instruments']:
                        row['strike_price'] = call['arguments']['strike_price']
                    if damage == 'selected_empty':
                        page['instruments'] = []
                observations.append(observation)
            result['result']['observations'] = observations
        result['result']['plan'] = copy.deepcopy(request)
        artifacts[name] = copy.deepcopy(result)
        return result
    return reader, seen, artifacts


@pytest.mark.parametrize('empty_symbols', [('SPY', 'QQQ'), ('SPY',)])
@pytest.mark.parametrize('pagination', [False, True])
def test_sparse_listed_strikes_preserve_original_evidence_and_catalog_bounds(captures, empty_symbols, pagination):
    from app.mixed.contract_catalog import review, digest
    reader, seen, artifacts = fallback_reader(captures, damage='paginated' if pagination else None,
                                               empty_symbols=empty_symbols)
    saved = []
    result = collect(date(2026, 10, 28), reader, pause=lambda _: None, retain_contracts=saved.append)
    assert result['status'] == 'CATALOG_CAPTURED' and len(result['option_candidates']) == 4
    assert result['provider_tool_calls'] == 10 + len(empty_symbols) * (2 if pagination else 1)
    assert result['provider_tool_calls'] == sum(len(p['calls']) for _, p in seen)
    assert result['probe_capture_sha256'] == digest(artifacts['contracts-probe'])
    assert saved == [artifacts['contracts-selected']]
    assert result['capture_hashes'][0] == digest(saved[0])
    assert len(result['listing_capture_hashes']) == len(empty_symbols) * (2 if pagination else 1)
    for anchor in result['anchors']:
        if anchor['symbol'] in empty_symbols:
            assert anchor['selection'] == 'LISTED_NEAREST'
            assert Decimal(anchor['strike']) == Decimal(anchor['probe_strike']) + Decimal('.5')
    terms = review(saved[0], [artifacts[f'quotes-{n}'] for n in range(1, 4)])
    assert len(terms['contracts']) == 4
    assert not result['trading_ready'] and not result['workers_started']
    if pagination:
        assert next(p for n, p in seen if n == 'spy-strikes-2')['calls'][0]['arguments']['cursor'] == 'page-1'


@pytest.mark.parametrize('damage', ['empty', 'wrong_chain', 'wrong_expiry', 'wrong_right', 'untradable',
                                  'duplicate', 'oversized', 'page_limit', 'cursor_loop', 'selected_empty'])
def test_incomplete_or_inconsistent_listings_never_produce_quote_requests(captures, damage):
    reader, seen, _ = fallback_reader(captures, damage=damage)
    with pytest.raises(ValueError):
        collect(date(2026, 10, 28), reader, pause=lambda _: pytest.fail('Unexpected quote pause'))
    assert not any(name.startswith('quotes') for name, _ in seen)
    assert len([name for name, _ in seen if '-strikes-' in name]) <= MAX_STRIKE_PAGES


@pytest.mark.parametrize('fallback', [False, True])
def test_capture_cli_saves_exact_selected_artifact_for_existing_consumers(tmp_path, monkeypatch, captures, schemas, fallback):
    from datetime import UTC, datetime
    from test_schema_artifact import artifact
    from app.mixed import session_capture
    from app.options import read_cli
    source = tmp_path/'discovery.json'
    source.write_text(json.dumps(artifact(schemas)))
    source.chmod(0o600)
    output = tmp_path/'capture'
    output.mkdir(mode=0o700)
    monkeypatch.setattr('app.domain.models.utc_now', lambda: datetime(2026, 10, 27, 22, tzinfo=UTC))
    reader, _, originals = fallback_reader(captures, empty_symbols=('SPY', 'QQQ') if fallback else ())
    def capture(args):
        target = Path(args[args.index('--output')+1])
        request = json.loads(Path(args[args.index('--plan')+1]).read_text())
        target.write_text(json.dumps(reader(target.stem, request)))
        target.chmod(0o600)
        return 0
    monkeypatch.setattr(read_cli, 'main', capture)
    original_collect = session_capture.collect
    monkeypatch.setattr(session_capture, 'collect', lambda *a, **kw: original_collect(*a, **kw, pause=lambda _: None))
    assert session_capture.main(['--target-session', '2026-10-28', '--directory', str(output),
                                '--schemas', str(source), '--oauth-file', '/never-opened']) == 0
    assert json.loads((output/'contracts.json').read_text()) == originals['contracts-selected' if fallback else 'contracts-probe']
    assert json.loads((output/'contracts-probe.json').read_text()) == originals['contracts-probe']
    assert json.loads((output/'report.json').read_text())['provider_tool_calls'] == (12 if fallback else 8)


@pytest.mark.parametrize('provider', [False, True])
def test_local_failure_is_retained_without_overwriting_provider_failure(tmp_path, monkeypatch, capsys, provider):
    from app.mixed import session_capture
    folder = tmp_path/'capture'
    folder.mkdir(mode=0o700)
    def run(argv, state):
        state.update(stage='STRIKE_DISCOVERY', directory=folder)
        if provider:
            print(json.dumps({'status':'FAILED', 'failure':{'stage':'CONNECT', 'causes':[{'error_class':'ConnectTimeout'}]}}))
            raise session_capture.ProviderCaptureFailed()
        raise ValueError('STRIKE_LISTING_EMPTY')
    monkeypatch.setattr(session_capture, '_main', run)
    assert session_capture.main([]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['failure']['stage'] == ('CONNECT' if provider else 'STRIKE_DISCOVERY')
    if not provider:
        assert report['reason'] == 'STRIKE_LISTING_EMPTY'
        assert json.loads((folder/'failure.json').read_text()) == report


def test_local_exception_text_is_not_in_public_capture_failure(tmp_path, monkeypatch, capsys):
    from app.mixed import session_capture
    def run(argv, state):
        state['stage'] = 'QUOTE_REVIEW'
        raise ValueError('PRIVATE PROVIDER RESPONSE')
    monkeypatch.setattr(session_capture, '_main', run)
    assert session_capture.main([]) == 1
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['reason'] == 'CATALOG_VALIDATION_FAILED'
