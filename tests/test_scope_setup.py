"""Read-only setup review keeps originals, explicit selection and missing evidence."""
import json
from datetime import date, timedelta

import pytest
from test_contract_catalog import captures as captures
from test_simulation_session import future_catalog
from test_scope_feed import setup
from test_option_scope import AT

from app.mixed.scope_setup import review
from app.mixed.simulation_catalog import proposal
from app.mixed.simulation_profile import configuration
from app.options.engine import fingerprint


def inputs(captures):
    same_day = json.loads(json.dumps(captures).replace('2026-10-28', '2026-10-09'))
    swing = future_catalog(captures)
    _, policy = configuration()
    args = dict(observed_swing_history=True, swing_contracts=swing[0], swing_samples=swing[1:])
    proposed, _ = proposal(policy, same_day[0], same_day[1:], date(2026,10,9), **args)
    ids = [i.instrument_id for i in proposed.candidates if i.contract.expiration == date(2026,10,9)]
    return policy, same_day, args, ids


def test_missing_scope_review_names_inputs_and_does_not_drop_ninth_contract(captures):
    policy, source, args, ids = inputs(captures)
    before = fingerprint([policy, source, args])
    result = review(policy, source[0], source[1:], AT.date(), now=AT, **args)
    assert result['selected_candidates'] == 8 and result['candidate_capacity'] == 8
    assert set(result['issues']) == {'SCOPE_REVIEWED_BINDING_REQUIRED', 'SCOPE_CANDIDATE_SLOT_REQUIRED',
        'SCOPE_ORIGINAL_CONTRACT_CAPTURE_REQUIRED', 'SCOPE_ORIGINAL_INDEX_INPUT_REQUIRED'}
    assert result['omitted_degen_ids'] == [] and not result['explicit_selection']
    assert before == fingerprint([policy, source, args])
    assert not any(result[k] for k in ('state_modified','provider_calls','workers_started','live_enabled','trading_ready'))
    reduced = review(policy, source[0], source[1:], AT.date(), now=AT, candidate_ids=ids[:3], **args)
    assert reduced['selected_candidates'] == 7 and reduced['omitted_degen_ids'] == ids[3:]
    assert reduced['read_budget']['three_polls_plus_refresh_fit_flat']
    assert not reduced['read_budget']['three_polls_plus_refresh_fit_with_extra_held']
    assert len([c for c in reduced['catalog'] if c['family']=='SWING' and c['selected']]) == 4


@pytest.mark.parametrize('damage', ['unknown', 'duplicate', 'one_symbol', 'empty'])
def test_invalid_explicit_selection_cannot_create_policy_or_discard_swing(captures, damage):
    policy, source, args, ids = inputs(captures)
    selection = {'unknown': ['unknown'], 'duplicate': [ids[0],ids[0]],
                 'one_symbol': ids[:1], 'empty': []}[damage]
    with pytest.raises(ValueError, match='Explicit'):
        proposal(policy, source[0], source[1:], AT.date(), candidate_ids=selection, **args)
    checked = review(policy, source[0], source[1:], AT.date(), candidate_ids=selection, now=AT, **args)
    assert 'EXPLICIT_CANDIDATE_SELECTION_INVALID' in checked['issues']
    assert checked['selected_candidates'] == 8


def test_exact_review_and_original_index_mapping_never_claim_term_or_trading_verification(captures):
    policy, source, args, ids = inputs(captures)
    from test_scope_broker_terms import original as original_terms
    _, capture, *_ = setup()
    binding, original = original_terms(captures)
    reviewed = review(policy, source[0], source[1:], AT.date(), candidate_ids=ids[:3],
        binding=binding.model_dump(), contract_capture=original, index_capture=capture.model_dump(), now=AT, **args)
    assert reviewed['issues'] == [] and reviewed['status'] == 'INPUTS_REVIEWED'
    assert reviewed['review']['original_completed_bars'] == 6
    assert reviewed['review']['contract_capture_check'] == 'MATCHED_BROKER_CHAIN_AND_INSTRUMENT'
    assert not reviewed['broker_terms_verified'] and not reviewed['trading_ready']
    proposed, report = proposal(policy, source[0], source[1:], AT.date(), candidate_ids=ids[:3],
                                scope_binding=binding.model_dump(), scope_contract_capture=original, **args)
    assert report["scope_contract_evidence"]["series_root_source"] == "BROKER_CHAIN_SYMBOL"
    assert len(proposed.candidates) == 7 and proposed.scope_binding == binding
    assert report['candidate_selection']['omitted_degen_ids'] == ids[3:]
    stale = review(policy, source[0], source[1:], AT.date(), candidate_ids=ids[:3],
        binding=binding.model_dump(), contract_capture={}, index_capture=capture.model_dump(),
        now=AT+timedelta(minutes=1), **args)
    assert {'SCOPE_CONTRACT_CAPTURE_HASH_MISMATCH','SCOPE_RETAINED_INPUT_NOT_CURRENT'} <= set(stale['issues'])


def test_binding_errors_report_fields_without_echoing_private_values(captures):
    policy, source, args, _ = inputs(captures)
    checked = review(policy, source[0], source[1:], AT.date(), binding={'instrument': 'PRIVATE_KEY'}, now=AT, **args)
    assert 'SCOPE_BINDING_INVALID' in checked['issues']
    assert 'PRIVATE_KEY' not in json.dumps(checked)
    assert any(e['field']=='session' for e in checked['review']['binding_errors'])


def test_scope_review_cli_only_reads_original_files(tmp_path, captures, monkeypatch, capsys):
    from app.mixed import scope_setup
    policy, source, args, ids = inputs(captures)
    def save(name, value):
        path = tmp_path/name
        path.write_text(json.dumps(value)); path.chmod(0o600)
        return str(path)
    flags = ['--policy', save('policy.json', policy.model_dump(mode='json')),
             '--contracts', save('contracts.json', source[0]), '--target-session', '2026-10-09']
    for n, value in enumerate(source[1:]):
        flags += ['--sample', save(f'quote-{n}.json', value)]
    before = {p.name:p.read_bytes() for p in tmp_path.iterdir()}
    monkeypatch.setattr(scope_setup, 'utc_now', lambda: AT)
    scope_setup.main(flags)
    result = json.loads(capsys.readouterr().out)
    assert result['status']=='INPUTS_MISSING' and result['selected_candidates']==4
    assert before == {p.name:p.read_bytes() for p in tmp_path.iterdir()}


def test_original_probe_before_contract_binding_and_session_provenance():
    from datetime import datetime, timezone
    from pathlib import Path
    from app.mixed.scope_setup import inspect_index
    from app.options.read_capture import CaptureResult
    from app.options.read_mapping import instant

    saved = json.loads((Path(__file__).parent / 'fixtures/robinhood_inputs_20261029.json').read_text())
    rows = saved['observations']
    received = instant(rows[-1]['received_at'])
    # Repackage the original responses with a synthetic test transport header.
    probe = CaptureResult(request_id=saved['capture_id'], policy_sha256='a'*64, operation='INPUT_PROBE',
                          status='COMPLETE', started_at=saved['started_at'], collected_at=received,
                          elapsed_seconds=(received-instant(saved['started_at'])).total_seconds(), observations=rows)
    artifact = {'operation': 'input-probe', 'result': probe.model_dump(mode='json')}
    now = datetime(2026,10,30,1,tzinfo=timezone.utc)
    unbound, issues = inspect_index(artifact, None, now)
    assert unbound['captured_unknown_interpolation'] >= 78
    assert unbound['captured_explicit_original'] == 0
    assert 'original_completed_bars' not in unbound and 'SCOPE_RETAINED_INPUT_NOT_CURRENT' in issues
    binding, *_ = setup()
    clocks = {k:getattr(binding.session,k).replace(day=29) for k in
              ('opens_at','entry_starts_at','entry_cutoff_at','protect_at','closes_at')}
    session = binding.session.model_copy(update={**clocks, 'session_date': date(2026,10,29)})
    details, issues = inspect_index(artifact, binding.model_copy(update={'session':session}), now)
    assert details['session_bars'] == details['unknown_session_bars'] == 78
    assert details['original_completed_bars'] == 0
    assert 'SPX_INTERPOLATION_STATUS_UNKNOWN' in issues
