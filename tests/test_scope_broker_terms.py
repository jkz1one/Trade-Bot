"""Synthetic exact SPXW subjects using retained Robinhood wire schemas."""
import copy

import pytest

from app.mixed.scope_terms import contract_evidence, contract_plan
from app.options.engine import fingerprint
from app.options.read_gateway import CapturePlan
from test_contract_catalog import captures as captures
from test_option_scope import AT
from test_scope_feed import setup
from test_session_capture import context


def original(captures):
    binding, *_ = setup()
    artifact = copy.deepcopy(captures[0])
    result = artifact['result']
    first = result['observations'][0]
    row = first['raw']['structuredContent']['data']['instruments'][0].copy()
    c = binding.instrument.contract
    row.update(id='99bfcee1-0541-456b-87ce-33cdffeac9a7', chain_symbol='SPX', underlying_type='index', type=c.right.lower(),
               strike_price=str(c.strike), expiration_date=c.expiration.isoformat(),
               trade_value_multiplier='100', state='active', tradability='tradable',
               min_ticks={'cutoff_price': '3', 'below_tick': str(c.tick_below_three),
                          'above_tick': str(c.tick_at_or_above_three)},
               sellout_datetime=binding.session.protect_at.isoformat())
    plan = contract_plan(row['id'])
    chain = context(captures)['result']['observations'][1]['raw']['structuredContent']['data']['chains'][0]
    chain.update(id=row['chain_id'], symbol='SPXW', expiration_dates=[c.expiration.isoformat()])
    result.update(started_at=AT.isoformat(), collected_at=AT.isoformat(), plan=plan.model_dump(mode='json'),
                  observations=[dict(label=call.label, tool=call.tool, completed=True,
                      attempted_at=AT.isoformat(), received_at=AT.isoformat(), output_schema_validated=True,
                      raw={'isError': False, 'structuredContent': {'data': data, 'guide': ''}})
                      for call, data in zip(plan.calls, [{'chains':[chain]}, {'instruments':[row], 'next': ''}], strict=True)])
    binding = binding.model_copy(update={'instrument': binding.instrument.model_copy(update={'instrument_id': row['id']}),
                                        'contract_capture_sha256': fingerprint(artifact),
                                        'post_cost_refresh':'paced-paid-refresh-v2'})
    return binding, artifact


@pytest.mark.parametrize('bad', ['wrong_chain', 'am', 'etf', 'wrong_id', 'wrong_strike', 'wrong_right',
                                 'pagination', 'late_sellout_protection', 'wrong_ticks', 'wrong_clock'])
def test_matching_hash_cannot_hide_wrong_broker_terms(captures, bad):
    binding, artifact = original(captures)
    receipts = artifact['result']['observations']
    chain = receipts[0]['raw']['structuredContent']['data']['chains'][0]
    page = receipts[1]['raw']['structuredContent']['data']
    row = page['instruments'][0]
    if bad == 'wrong_chain':
        chain['id'] = 'unrelated'
    elif bad == 'am':
        chain['settle_on_open'] = True
    elif bad == 'etf':
        row['underlying_type'] = 'equity'
    elif bad == 'wrong_id':
        row['id'] = 'other'
    elif bad == 'wrong_strike':
        row['strike_price'] = '99999'
    elif bad == 'wrong_right':
        row['type'] = 'put'
    elif bad == 'pagination':
        page['next'] = 'unfinished'
    elif bad == 'late_sellout_protection':
        row['sellout_datetime'] = binding.session.opens_at.isoformat()
    elif bad == 'wrong_ticks':
        row['min_ticks']['above_tick'] = '100'
    else:
        receipts[-1]['received_at'] = '2099-01-01T00:00:00Z'
    bound = binding.model_copy(update={'contract_capture_sha256': fingerprint(artifact)})
    with pytest.raises(ValueError, match='^SCOPE_'):
        contract_evidence(bound, artifact, AT)


def test_spx_plan_cannot_request_unrelated_tools(captures):
    binding, artifact = original(captures)
    checked = contract_evidence(binding, artifact, AT)
    assert checked['series_root_source'] == 'BROKER_CHAIN_SYMBOL'
    assert checked['documented_product_terms']['settlement_session'] == 'PM'
    data = artifact['result']['plan']
    data['calls'][0].update(tool='get_equity_quotes', arguments={'symbols':['SPY']})
    with pytest.raises(ValueError):
        CapturePlan.model_validate(data)


def test_generic_spx_chain_keeps_root_review_explicit(captures):
    binding, artifact = original(captures)
    artifact['result']['observations'][0]['raw']['structuredContent']['data']['chains'][0]['symbol'] = 'SPX'
    binding = binding.model_copy(update={'contract_capture_sha256': fingerprint(artifact)})
    assert contract_evidence(binding, artifact, AT)['series_root_source'] == 'REVIEWED_BINDING'


def test_normal_read_cli_creates_replayable_two_read_artifact(tmp_path, captures, monkeypatch, capsys):
    import json
    from app.options import read_cli
    from app.options.read_capture import CaptureResult
    from test_schema_artifact import artifact as discovery
    from test_option_read_capture import oauth

    tmp_path.chmod(0o700)
    binding, sample = original(captures)
    retained = CaptureResult.model_validate(sample['result'])
    source = tmp_path / 'discovery.json'
    source.write_text(json.dumps(discovery(retained.schemas)))
    source.chmod(0o600)
    async def fake_collect(policy, *, plan, schemas, **kwargs):
        assert plan == retained.plan and schemas.sha256 == retained.schemas.sha256
        return retained
    monkeypatch.setattr(read_cli, 'collect', fake_collect)
    out = tmp_path / 'captured.json'
    assert read_cli.main(['capture','--schemas',str(source),'--schema-sha256',retained.schemas.sha256,
                          '--scope-contract-id',binding.instrument.instrument_id,'--oauth-file', str(oauth(tmp_path)),
                          '--output', str(out)]) == 0
    assert json.loads(capsys.readouterr().out)['completed_reads'] == 2
    evidence = json.loads(out.read_text())
    binding = binding.model_copy(update={'contract_capture_sha256': fingerprint(evidence)})
    assert contract_evidence(binding, evidence, AT)['contract_capture_check'] == 'MATCHED_BROKER_CHAIN_AND_INSTRUMENT'
