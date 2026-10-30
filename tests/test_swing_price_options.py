"""Price/options-only Swing requires explicit policy and never invents CLEAR."""
import pytest
from pydantic import ValidationError
from test_swing_delivery import fixture
from test_option_entry_coordination import policies

from app.mixed.price_options_profile import proposal
from app.mixed.simulation_profile import configuration
from app.mixed.swing_delivery import SwingCycleEvidence, assemble
from app.options.degen import scan_degen
from app.options.engine import fingerprint
from app.options.swing import SwingInput, SwingPolicy, scan_swing
from app.options.swing_batch import batch_seeds, family_policy
from app.robinhood.schedule import XNYSCalendar


def test_explicit_price_only_delivery_and_native_scan_preserve_absence():
    f, bound, binding, metadata, evidence, now = fixture()
    p = binding.option_policy.model_copy(update={'input_basis': 'robinhood-price-options-v1'})
    sp = binding.stock_policy.model_copy(update={'input_basis': 'robinhood-price-options-v1'})
    binding = binding.model_copy(update={'option_policy': p, 'stock_policy': sp})
    # Synthetic binding to the explicitly different policy; production binds originals again.
    bound = bound.model_copy(update={'policy_hash': fingerprint(binding)})
    result, issues = assemble(f, bound, binding, metadata, SwingCycleEvidence(), now=now)
    assert not issues
    assert result.swing_batches[0].catalyst is None and result.stocks[0].catalyst is None
    assert result.swing_batches[0].seed == bound.batches[0]
    cal = XNYSCalendar()
    setup, _ = policies()
    h = result.histories[0]
    intraday = scan_degen(h, setup, cal.current_window(now), now=now)
    child = batch_seeds(bound.batches[0], p, cal, ('SPY',))[0]
    item = SwingInput(seed=child, metadata=metadata[0], catalyst=None)
    scan = scan_swing(item, family_policy(child, p), intraday, h, cal, ('SPY',), now=now, receive_lag=5)
    assert scan.input_basis == 'robinhood-price-options-v1' and scan.catalyst is None
    assert 'SWING_CATALYST_CLEARANCE_REQUIRED' not in scan.observations[0].reasons
    old = p.model_copy(update={'input_basis': None})
    denied = scan_swing(item, family_policy(child, old), intraday, h, cal, ('SPY',), now=now, receive_lag=5)
    assert 'SWING_CATALYST_CLEARANCE_REQUIRED' in denied.observations[0].reasons
    _, errors = assemble(f, bound, binding, metadata, evidence, now=now)
    assert any('CATALYST_MUST_BE_ABSENT' in x for x in errors)


def test_strategy_proposal_keeps_existing_owner_and_risk_configuration():
    settings, _ = configuration()
    original = settings.model_dump_json()
    new, report = proposal(settings)
    assert settings.model_dump_json() == original
    assert new.limits == settings.limits and new.execution == settings.execution
    assert new.runtime == settings.runtime and new.entry_policy == settings.entry_policy
    assert new.swing_policy.input_basis == 'robinhood-price-options-v1'
    assert new.stock_policy.swing.input_basis == new.swing_policy.input_basis
    assert new.scope_policy.watch.context.structure.preflight.input_basis == new.swing_policy.input_basis
    assert not report['state_modified'] and not report['trading_ready']
    assert report['catalyst_coverage'] == 'NOT_USED_BY_THIS_VARIANT_NOT_CLEAR'
    assert new.scope_policy.watch.quality.arm_score == settings.scope_policy.watch.quality.arm_score


def test_price_only_swing_cannot_acquire_overnight_carry():
    p = configuration()[0].swing_policy.model_dump() | {
        'input_basis': 'robinhood-price-options-v1', 'holding_policy': 'BOUNDED_CARRY_V1'}
    with pytest.raises(ValidationError, match='intraday PAPER'):
        SwingPolicy.model_validate(p)


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
def test_price_only_swing_reaches_native_order_and_independent_exit(tmp_path, monkeypatch, right):
    import asyncio
    from decimal import Decimal
    import test_option_shared_strategy as native
    from test_option_execution import intent_for

    old = native.swing_policy
    monkeypatch.setattr(native, 'swing_policy', lambda **changes: old(input_basis='robinhood-price-options-v1', **changes))
    with native.owner(tmp_path, right) as (c, venue, times):
        item = native.swing_input(right).model_copy(update={'catalyst': None})
        f = native.shared_frame(right, item=item)
        out = asyncio.run(c.cycle(f))
        assert out['status'] == 'OPEN', out
        intent = intent_for(c.engine, out['client_id'])
        assert intent.instrument == item.seed.instrument
        assert intent.exit_at <= native.AT.replace(hour=19, minute=45)
        venue.fill(intent, intent.quantity, f.quotes[1], times[0], fill_id='price-only-fill')
        assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])['reconciled']
        barrier = Decimal(590 if right == 'CALL' else 610)
        u = f.underlyings[0].model_copy(update={'bid': barrier, 'ask': barrier})
        exit_result = asyncio.run(c.supervise((f.quotes[1],), (u,)))
        assert exit_result['status'] == 'OPEN', exit_result
        assert c.engine.assess(f.quotes[1], u, now=times[0])['exit_reason'] == 'UNDERLYING_INVALIDATION'
