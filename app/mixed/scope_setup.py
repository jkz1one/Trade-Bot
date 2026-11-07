"""Read-only Scope setup review. Never invent terms, select contracts or enroll."""
import argparse
import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.domain.models import utc_now
from app.mixed.continuous_feed import FeedPolicy
from app.mixed.scope_feed import ScopeFeedBinding
from app.mixed.simulation_catalog import proposal
from app.mixed.scope_terms import contract_evidence
from app.options.engine import fingerprint
from app.options.operator_inbox import read
from app.options.read_capture import CaptureResult


def inspect_index(artifact, scope, now):
    from app.mixed.scope_sources import map_index, receipt_data
    from app.options.input_probe import index_id, validate_observations
    from app.options.read_mapping import instant
    from app.options.scope_read import TOOLS, validate

    captured = CaptureResult.model_validate(artifact.get('result', artifact))
    if (not captured.started_at <= captured.collected_at <= now
            or captured.status != 'COMPLETE' or captured.scope_error_class is not None):
        raise ValueError('Incomplete index capture')
    if captured.operation == 'INPUT_PROBE':
        validate_observations(captured.observations, captured.started_at)
        rows = [r for r in captured.observations if r['tool'] in TOOLS]
    elif captured.operation == 'SCOPE_INPUT':
        rows = captured.observations
    elif captured.operation == 'CAPTURE' and captured.scope_requested:
        rows = captured.scope_observations
    else:
        raise ValueError('Original index receipts required')
    validate(rows, captured.started_at, complete=True)
    if [r['tool'] for r in rows] != list(TOOLS):
        raise ValueError('Index receipt order mismatch')
    (ids, ir), (quotes, qr), (history, hr) = [receipt_data(row, tool) for row, tool in zip(rows, TOOLS, strict=True)]
    identity = index_id(ids)
    q, = quotes['quotes']
    h, = history['results']
    if (identity is None or not ir <= min(qr, hr) <= max(qr, hr) <= captured.collected_at
            or any(r['symbol'] != 'SPX' or r['instrument_id'] != identity for r in (q, h))
            or h['interval'] != '5minute' or instant(q['venue_timestamp']) > qr
            or not isinstance(h['bars'], list) or len(h['bars']) > 400):
        raise ValueError('Index coverage mismatch')
    bars = h['bars']
    if any(not isinstance(b, dict) for b in bars):
        raise ValueError('Invalid index bars')
    details = {'index_mapping_as_of': captured.collected_at.isoformat(),
               'captured_bars': len(bars),
               'captured_explicit_original': sum(b.get('interpolated') is False for b in bars),
               'captured_unknown_interpolation': sum(b.get('interpolated') is not True and b.get('interpolated') is not False for b in bars),
               'current_index_age_seconds': (now - instant(q['venue_timestamp'])).total_seconds()}
    issues = []
    if scope is not None:
        _, _, mapped = map_index(*rows, scope.session, now=captured.collected_at)
        details.update(index_mapping_issues=mapped['issues'], original_completed_bars=mapped['original_bars'],
                       session_bars=mapped['session_bars'], unknown_session_bars=mapped['unknown_interpolation_bars'])
        issues.extend(mapped['issues'])
    if not 0 <= details['current_index_age_seconds'] <= 30:
        issues.append('SCOPE_RETAINED_INPUT_NOT_CURRENT')
    return details, issues


def review(policy, contracts, samples, target, *, binding=None, contract_capture=None,
           index_capture=None, candidate_ids=None, observed_swing_history=False,
           swing_contracts=None, swing_samples=None, now=None):
    now = now or utc_now()
    issues, details = [], {}
    args = dict(observed_swing_history=observed_swing_history,
                swing_contracts=swing_contracts, swing_samples=swing_samples)
    # Always show the original choices, even if the requested subset is invalid.
    catalog, _ = proposal(policy, contracts, samples, target, **args)
    selected = catalog
    if candidate_ids is not None:
        try:
            selected, _ = proposal(policy, contracts, samples, target, candidate_ids=candidate_ids, **args)
        except ValueError:
            issues.append('EXPLICIT_CANDIDATE_SELECTION_INVALID')
    selected_ids = {i.instrument_id for i in selected.candidates}
    choices = [{'id': i.instrument_id, 'symbol': i.contract.underlying, 'right': i.contract.right,
                'expiration': i.contract.expiration.isoformat(), 'strike': str(i.contract.strike),
                'family': 'DEGEN' if i.contract.expiration == target else 'SWING',
                'selected': i.instrument_id in selected_ids} for i in catalog.candidates]
    if len(selected.candidates) > 7:
        issues.append('SCOPE_CANDIDATE_SLOT_REQUIRED')
    scope = None
    if binding is None:
        issues.append('SCOPE_REVIEWED_BINDING_REQUIRED')
        details['binding_required_fields'] = ['session', 'previous_session', 'instrument',
                                              'choice', 'contract_capture_sha256', 'post_cost_refresh']
    else:
        try:
            scope = ScopeFeedBinding.model_validate(binding)
        except ValidationError as exc:
            issues.append('SCOPE_BINDING_INVALID')
            details['binding_errors'] = [{'field': '.'.join(map(str, e['loc'])) or 'binding',
                                          'kind': e['type']} for e in exc.errors()[:32]]
    if scope is not None:
        if scope.session.session_date != target:
            issues.append('SCOPE_SESSION_DATE_MISMATCH')
        if scope.instrument.instrument_id in selected_ids:
            issues.append('SCOPE_CONTRACT_ID_CONFLICT')
        if scope.post_cost_refresh != 'paced-paid-refresh-v2':
            issues.append('SCOPE_PACED_REFRESH_NOT_REVIEWED')
        details['binding_sha256'] = fingerprint(scope)
        details['play_key'] = scope.play_key()
    if contract_capture is None:
        issues.append('SCOPE_ORIGINAL_CONTRACT_CAPTURE_REQUIRED')
    else:
        digest = fingerprint(contract_capture)
        details['contract_capture_sha256'] = digest
        if scope is not None:
            try:
                details.update(contract_evidence(scope, contract_capture, now))
            except ValueError as exc:
                issues.append(str(exc))
    if index_capture is None:
        issues.append('SCOPE_ORIGINAL_INDEX_INPUT_REQUIRED')
    else:
        try:
            index_details, index_issues = inspect_index(index_capture, scope, now)
            details.update(index_details)
            issues.extend(index_issues)
        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
            issues.append('SCOPE_ORIGINAL_INDEX_INPUT_INVALID')
    if now.astimezone(ZoneInfo('America/New_York')).date() > target:
        issues.append('TARGET_SESSION_EXPIRED')
    # Worst regular-session plan: equity books + history + three SPX reads,
    # plus one option call per eight distinct candidate/held contracts.
    flat_calls = 5 + (len(selected.candidates) + 1 + 7) // 8
    held_calls = 5 + (len(selected.candidates) + 2 + 7) // 8
    return {'version': 'scope-setup-review-v1', 'target_session': target.isoformat(),
            'status': 'INPUTS_MISSING' if issues else 'INPUTS_REVIEWED',
            'issues': sorted(set(issues)), 'catalog': choices,
            'candidate_capacity': 8, 'selected_candidates': len(selected.candidates),
            'scope_slots_required': 1, 'explicit_selection': candidate_ids is not None,
            'selected_degen_ids': [c['id'] for c in choices if c['selected'] and c['family']=='DEGEN'],
            'omitted_degen_ids': [c['id'] for c in choices if not c['selected']],
            'read_budget': {'calls_per_minute': policy.calls_per_minute,
                'ordinary_start_spacing_seconds': max(20, policy.poll_seconds),
                'calls_per_capture_flat': flat_calls, 'calls_with_one_extra_held_contract': held_calls,
                'three_polls_plus_refresh_fit_flat': 4*flat_calls <= policy.calls_per_minute,
                'three_polls_plus_refresh_fit_with_extra_held': 4*held_calls <= policy.calls_per_minute,
                'holdings_inspected': False, 'runtime_budget_recheck_required': True},
            'review': details, 'broker_terms_verified': False,
            'remaining': ['Inspect exact original SPXW terms against the reviewed binding',
                          'Native calendar/pattern/quote/history acceptance',
                          'Exact session-policy review and enrollment', 'Connected lifecycle'],
            'state_modified': False, 'provider_calls': False, 'model_calls': 0,
            'workers_started': False, 'live_enabled': False, 'trading_ready': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('policy', 'contracts', 'target-session'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--sample', action='append', required=True)
    p.add_argument('--candidate-id', action='append')
    p.add_argument('--observed-swing-history', action='store_true')
    for name in ('swing-capture-directory', 'scope-binding', 'scope-contract-capture', 'scope-input'):
        p.add_argument('--'+name)
    a = p.parse_args(argv)
    load = lambda path: json.loads(read(Path(path), 8 * 1024 * 1024))
    result = review(FeedPolicy.model_validate(load(a.policy)), load(a.contracts),
        [load(path) for path in a.sample], date.fromisoformat(a.target_session),
        binding=load(a.scope_binding) if a.scope_binding else None,
        contract_capture=load(a.scope_contract_capture) if a.scope_contract_capture else None,
        index_capture=load(a.scope_input) if a.scope_input else None, candidate_ids=a.candidate_id,
        observed_swing_history=a.observed_swing_history,
        swing_contracts=load(Path(a.swing_capture_directory)/'contracts.json') if a.swing_capture_directory else None,
        swing_samples=[load(Path(a.swing_capture_directory)/f'quotes-{n}.json') for n in (1,2,3)] if a.swing_capture_directory else None)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
