"""Pure proposal for the explicitly chosen PAPER price/options strategy variants.

This never updates an enrolled account. Frozen strategy upgrades require a
separate reviewed migration; merely replacing runtime.json remains invalid.
"""
from copy import deepcopy

from app.options.engine import fingerprint
from app.options.runtime_models import RuntimeSettings
from app.options.scope import PRICE_GROUPS

BASIS = 'robinhood-price-options-v1'


def proposal(settings):
    settings = RuntimeSettings.model_validate(settings.model_dump())
    if settings.limits.mode != 'PAPER':
        raise ValueError('Price/options variants require PAPER settings')
    if settings.stock_policy is None or settings.swing_policy is None or settings.scope_policy is None:
        raise ValueError('Existing mixed Swing and Scope enrollment required')
    value = settings.model_dump()
    if value.get('swing_policy') is not None:
        if value['swing_policy'].get('carry') is not None or value['swing_policy']['holding_policy'] != 'SESSION_CLOSE':
            raise ValueError('Cannot silently remove an existing Swing carry policy')
        value['swing_policy']['input_basis'] = BASIS
    if value.get('stock_policy', {}).get('swing') is not None:
        value['stock_policy']['swing']['input_basis'] = BASIS
    if value.get('scope_policy') is not None:
        watch = value['scope_policy']['watch']
        context = deepcopy(watch['context'])
        preflight = context['structure']['preflight']
        preflight['input_basis'] = BASIS
        preflight['session_source'] = 'robinhood-reviewed-index-session'
        preflight['max_history_age_seconds'] = 300
        if watch.get('arming') is not None:
            watch['arming']['max_sample_gap_seconds'] = 30
            watch['arming']['sampling_basis'] = BASIS
        preflight['sources'] = [dict(s, source='robinhood-mcp') for s in preflight['sources'] if s['kind'] in PRICE_GROUPS]
        preflight['history_sources'] = [dict(s, source='robinhood-mcp') for s in preflight['history_sources']]
        # No unobserved calendar or contract source is made available here.
        watch['context'] = context
        if watch.get('quality') is not None:
            watch['quality']['context'] = deepcopy(context)
            watch['quality']['structural_path'] = 'completed-spx-plateaus-v2'
        if watch.get('contract') is not None:
            watch['contract']['quality']['context'] = deepcopy(context)
            watch['contract']['quality']['structural_path'] = 'completed-spx-plateaus-v2'
    proposed = RuntimeSettings.model_validate(value)
    # Account identity, risk limits, costs, execution and worker settings are identical.
    excluded = {'swing_policy', 'stock_policy', 'scope_policy'}
    if settings.model_dump(exclude=excluded) != proposed.model_dump(exclude=excluded):
        raise ValueError('Strategy proposal changed owner or execution configuration')
    return proposed, {
        'version': 'paper-price-options-proposal-v1', 'input_basis': BASIS,
        'original_settings_sha256': fingerprint(settings), 'settings_sha256': fingerprint(proposed),
        'account_id': settings.limits.account_id, 'population_id': settings.limits.population_id,
        'catalyst_coverage': 'NOT_USED_BY_THIS_VARIANT_NOT_CLEAR',
        'scope_context': 'PRICE_AND_OPTIONS_ONLY', 'live_enabled': False,
        'state_modified': False, 'workers_started': False, 'trading_ready': False,
        'remaining': ['Apply reviewed existing-owner amendment', 'Enroll reviewed session inputs',
                      'Complete original market inputs', 'Native market-hours lifecycle acceptance'],
    }
