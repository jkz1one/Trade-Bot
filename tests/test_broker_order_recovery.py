"""Replay normalized broker history without transmitting, mutating, or guessing an identity."""
import copy
import json
import sys

import pytest

from app.execution.order_recovery import recover

T0, T1, T2 = (f'2026-11-06T15:0{i}:00Z' for i in range(3))
TERMS = dict(instrument_id='exact-option', side='BUY', quantity=2, limit_price='1.00',
             order_type='LIMIT', time_in_force='DAY', position_effect='OPEN')
ATTEMPT = {**TERMS, 'account_id': 'private-account', 'client_id': 'private-client', 'attempted_at': T0}


def order(status='PARTIAL', *, at=T1):
    fills = [{'fill_id': 'a', 'quantity': 1, 'price': '.95', 'occurred_at': T1}]
    if status == 'FILLED':
        fills.append({'fill_id': 'b', 'quantity': 1, 'price': '1.00', 'occurred_at': T2})
    if status in {'OPEN', 'REJECTED'}:
        fills = []
    return {**TERMS, 'order_id': 'private-order', 'client_id': 'private-client', 'updated_at': at,
            'status': status, 'filled_quantity': len(fills), 'fills': fills}


def history(*orders, at=T1, complete=True):
    return {'account_id': 'private-account', 'observed_at': at, 'complete': complete, 'orders': list(orders)}


def case(*snapshots, attempt=None):
    return {'version': 'option-order-recovery-v1', 'attempt': attempt or ATTEMPT, 'snapshots': snapshots}


@pytest.mark.parametrize('terminal', ['FILLED', 'CANCELED', 'EXPIRED'])
def test_exact_recovery_across_disconnect_and_restart(terminal):
    partial = order()
    final = order(terminal, at=T2)
    final['client_id'] = None  # earlier bound broker ID survives the missing echo
    evidence = case(history(complete=False, at=T0), history(partial, copy.deepcopy(partial)),
                    history(final, at=T2))
    result = recover(evidence)
    assert result == recover(json.loads(json.dumps(evidence)))
    assert result['terminal_confirmed'] and result['last_verified_status'] == terminal
    assert result['last_verified_filled_quantity'] == (2 if terminal == 'FILLED' else 1)
    assert result['resubmit'] is result['live_enabled'] is result['state_modified'] is False


@pytest.mark.parametrize('failure', ['empty', 'lookalike', 'conflicting_ids', 'ambiguous', 'wrong_account',
                                     'wrong_contract', 'incomplete', 'future', 'filled_before_attempt'])
def test_uncertainty_never_grants_a_retry(failure):
    r = order()
    snapshot = history(r)
    if failure == 'empty':
        snapshot['orders'] = []
    elif failure == 'lookalike':
        r['client_id'] = None
    elif failure == 'conflicting_ids':
        r['client_id'] = 'another-client'
    elif failure == 'ambiguous':
        snapshot['orders'].append({**r, 'order_id': 'another-order'})
    elif failure == 'wrong_account':
        snapshot['account_id'] = 'another-account'
    elif failure == 'wrong_contract':
        r['instrument_id'] = 'neighboring-strike'
    elif failure == 'incomplete':
        snapshot['complete'] = False
    elif failure == 'future':
        r['updated_at'] = T2
    else:
        r['fills'][0]['occurred_at'] = '2026-11-06T14:59:59Z'
    attempt = {**ATTEMPT, 'order_id':r['order_id']} if failure == 'conflicting_ids' else ATTEMPT
    result = recover(case(snapshot, attempt=attempt))
    assert result['status'] == 'UNRESOLVED' and result['last_verified_filled_quantity'] is None
    assert not result['terminal_confirmed'] and not result['resubmit']


@pytest.mark.parametrize('failure', ['missing', 'rewritten_fill', 'dropped_fill', 'terminal_changed', 'same_clock'])
def test_regressions_preserve_prior_confirmed_partial(failure):
    first = order('CANCELED' if failure == 'terminal_changed' else 'PARTIAL')
    second = order('FILLED', at=T2)
    if failure == 'rewritten_fill':
        second['fills'][0]['price'] = '.90'
    elif failure == 'dropped_fill':
        second = order('OPEN', at=T2)
    elif failure == 'same_clock':
        second['updated_at'] = T1
        second['fills'][1]['occurred_at'] = T1
    update = history(at=T2) if failure == 'missing' else history(second, at=T2)
    result = recover(case(history(first), update))
    assert result['status'] == 'UNRESOLVED' and result['last_verified_fill_count'] == 1
    assert not result['terminal_confirmed'] and not result['resubmit']


def test_private_cli_replay_emits_only_counts_and_never_opens_broker(tmp_path, monkeypatch, capsys):
    from app.robinhood import cli
    path = tmp_path / 'case.json'
    raw = json.dumps(case(history(order('CANCELED'))))
    path.write_text(raw)
    path.chmod(0o600)
    monkeypatch.setattr(cli, 'Settings', lambda: pytest.fail('opened settings'))
    monkeypatch.setattr(sys, 'argv', ['cli', 'order-recovery-report', '--case', str(path)])
    with pytest.raises(SystemExit) as finished:
        cli.main()
    output = capsys.readouterr().out
    assert finished.value.code == 0 and json.loads(output)['terminal_confirmed']
    assert 'private-' not in output and path.read_text() == raw
    bad = case(history(order()))
    bad['snapshots'][0]['orders'][0]['filled_quantity'] = 0
    path.write_text(json.dumps(bad))
    with pytest.raises(SystemExit) as finished:
        cli.main()
    assert finished.value.code == 2 and json.loads(capsys.readouterr().out)['status'] == 'INVALID_EVIDENCE'
