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
from app.options.engine import fingerprint
from app.options.operator_inbox import read
from app.options.read_capture import CaptureResult


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
        details['contract_capture_check'] = 'HASH_ONLY_NOT_TERM_VERIFICATION'
        if scope is not None and digest != scope.contract_capture_sha256:
            issues.append('SCOPE_CONTRACT_CAPTURE_HASH_MISMATCH')
    if index_capture is None:
        issues.append('SCOPE_ORIGINAL_INDEX_INPUT_REQUIRED')
    elif scope is not None:
        from app.mixed.scope_sources import map_index
        from app.options.scope_read import validate
        try:
            captured = CaptureResult.model_validate(index_capture.get('result', index_capture))
            rows = captured.scope_observations if captured.scope_requested else captured.observations
            if (captured.operation not in {'SCOPE_INPUT', 'CAPTURE'} or captured.status != 'COMPLETE'
                    or captured.collected_at > now or captured.scope_error_class is not None):
                raise ValueError('Original completed Scope input required')
            validate(rows, captured.started_at, complete=True)
            _, _, mapped = map_index(*rows, scope.session, now=captured.collected_at)
            details['index_mapping_as_of'] = captured.collected_at.isoformat()
            details['index_mapping_issues'] = mapped['issues']
            details['original_completed_bars'] = mapped['session_bars']
            issues.extend(mapped['issues'])
            from app.options.read_mapping import instant
            age = (now - instant(mapped['reference']['source_at'])).total_seconds()
            details['current_index_age_seconds'] = age
            if not 0 <= age <= 30:
                issues.append('SCOPE_RETAINED_INPUT_NOT_CURRENT')
        except (ValueError, TypeError, KeyError, ArithmeticError):
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
