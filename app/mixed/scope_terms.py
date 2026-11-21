"""Cross-check a reviewed SPXW binding against exchange terms and original broker rows."""
from decimal import Decimal
from jsonschema.exceptions import ValidationError as SchemaError

from app.options.engine import fingerprint
from app.options.read_capture import CaptureResult
from app.options.read_gateway import CapturePlan
from app.options.read_mapping import instant, response

SPECIFICATION = 'https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications'
WEEKLYS = 'https://www.cboe.com/tradable_products/sp_500/spx_weekly_options/specifications'


class ScopeTermError(ValueError):
    """A public, bounded reason for an original contract mismatch."""


def contract_plan(instrument_id):
    return CapturePlan.model_validate({
        'purpose': 'SCHEMA_MAPPING_EVIDENCE', 'symbols': ['SPX'], 'instrument_ids': [instrument_id],
        'calls': [{'tool': 'get_option_chains', 'label': 'spx-chains', 'arguments': {'underlying_symbol': 'SPX'}},
                  {'tool': 'get_option_instruments', 'label': 'scope-contract', 'arguments': {'ids': instrument_id}}],
    })


def contract_evidence(binding, artifact, now):
    if fingerprint(artifact) != binding.contract_capture_sha256:
        raise ScopeTermError('SCOPE_CONTRACT_CAPTURE_HASH_MISMATCH')
    if not isinstance(artifact, dict) or artifact.get('operation') != 'capture':
        raise ScopeTermError('SCOPE_ORIGINAL_BROKER_ROWS_REQUIRED')
    try:
        return _compare(binding, artifact, now)
    except ScopeTermError:
        raise
    except (SchemaError, KeyError, TypeError, ArithmeticError, AttributeError, ValueError):
        raise ScopeTermError('SCOPE_CONTRACT_CAPTURE_INVALID') from None


def _compare(binding, artifact, now):
    result = CaptureResult.model_validate(artifact['result'])
    instrument = binding.instrument
    contract = instrument.contract
    if (contract.underlying_market != 'US_INDEX' or contract.deliverable_kind != 'CASH'
            or contract.deliverable_units != 0):
        raise ScopeTermError('SCOPE_DOCUMENTED_DELIVERABLE_MISMATCH')
    expected = contract_plan(instrument.instrument_id)
    if (artifact.get('status') != 'COMPLETE' or artifact.get('execution_authority') is not False
            or result.operation != 'CAPTURE'
            or result.status != 'COMPLETE' or result.schemas is None or result.plan is None
            or result.plan.symbols != expected.symbols or result.plan.instrument_ids != expected.instrument_ids
            or result.scope_requested or len(result.observations) != 2
            or not result.started_at <= result.collected_at <= now):
        raise ScopeTermError('SCOPE_CONTRACT_CAPTURE_INVALID')
    payloads = []
    previous = result.started_at
    for call, receipt in zip(result.plan.calls, result.observations, strict=True):
        if (receipt.get('tool') != call.tool or receipt.get('label') != call.label
                or receipt.get('completed') is not True or receipt.get('output_schema_validated') is not True
                or not previous <= instant(receipt['attempted_at']) <= instant(receipt['received_at']) <= result.collected_at):
            raise ScopeTermError('SCOPE_CONTRACT_CAPTURE_INVALID')
        previous = instant(receipt['received_at'])
        payloads.append(response(result.schemas, call, receipt['raw'], call.tool)[1])
    chains, contracts = payloads
    rows = contracts['instruments']
    if contracts.get('next') or not isinstance(rows, list) or len(rows) != 1:
        raise ScopeTermError('SCOPE_INSTRUMENT_COVERAGE_INVALID')
    row = rows[0]
    if (row['id'] != instrument.instrument_id or row['chain_symbol'] not in {'SPX', 'SPXW'}
            or row['underlying_type'] != 'index' or row['type'] != contract.right.lower()
            or Decimal(row['strike_price']) != contract.strike or row['expiration_date'] != contract.expiration.isoformat()
            or Decimal(row['trade_value_multiplier']) != contract.multiplier
            or row['state'] != 'active' or row['tradability'] != 'tradable'):
        raise ScopeTermError('SCOPE_INSTRUMENT_TERMS_MISMATCH')
    parents = [c for c in chains['chains'] if c['id'] == row['chain_id']]
    if len(parents) != 1:
        raise ScopeTermError('SCOPE_CHAIN_IDENTITY_MISMATCH')
    chain = parents[0]
    if (chain['symbol'] not in {'SPX', 'SPXW'} or chain['settle_on_open'] is not False
            or chain['underlying_instruments'] != [] or chain['can_open_position'] is not True
            or (chain['cash_component'] is not None and Decimal(chain['cash_component']) != 0)
            or Decimal(chain['trade_value_multiplier']) != contract.multiplier
            or row['expiration_date'] not in chain['expiration_dates']):
        raise ScopeTermError('SCOPE_CHAIN_TERMS_MISMATCH')
    ticks = row['min_ticks']
    cutoff, below, above = (Decimal(ticks[k]) for k in ('cutoff_price', 'below_tick', 'above_tick'))
    if (cutoff not in (0, 3) and below != above
            or contract.tick_below_three != (above if cutoff == 0 else below)
            or contract.tick_at_or_above_three != above):
        raise ScopeTermError('SCOPE_CONTRACT_TICKS_MISMATCH')
    sellout = instant(row['sellout_datetime'])
    if sellout < binding.session.protect_at:
        raise ScopeTermError('SCOPE_BROKER_SELLOUT_BEFORE_PROTECTION')
    return {'contract_capture_check': 'MATCHED_BROKER_CHAIN_AND_INSTRUMENT',
            'capture_as_of': result.collected_at.isoformat(), 'broker_sellout_at': sellout.isoformat(),
            'series_root_source': 'BROKER_CHAIN_SYMBOL' if chain['symbol'] == 'SPXW' else 'REVIEWED_BINDING',
            'documented_product_terms': {'root': 'SPXW', 'exercise_style': 'EUROPEAN',
                                         'settlement': 'CASH', 'settlement_session': 'PM', 'multiplier': 100},
            'specification_sources': [SPECIFICATION, WEEKLYS]}
