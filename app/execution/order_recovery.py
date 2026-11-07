"""Offline reconciliation of a recorded single-leg limit attempt and normalized history.

This input contract belongs to Trade-Bot. A broker reader must establish the
account, completeness, stable identifiers and fill fields before exporting it.
Replay has no dispatch, cancellation, credential or journal-writing interface.
"""
from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from app.options.models import Count, Money, Name, OptionRecord, PositiveCount
from app.execution.models import TERMINAL


class Terms(OptionRecord):
    instrument_id: Name
    side: Literal['BUY', 'SELL']
    quantity: PositiveCount
    limit_price: Money = Field(gt=0)
    order_type: Literal['LIMIT']
    time_in_force: Literal['DAY']
    position_effect: Literal['OPEN', 'CLOSE']

    @model_validator(mode='after')
    def long_option(self):
        if (self.side == 'BUY') != (self.position_effect == 'OPEN'):
            raise ValueError('UNSUPPORTED_OPTION_POSITION_EFFECT')
        return self


class Attempt(Terms):
    client_id: Name
    account_id: Name
    attempted_at: datetime
    order_id: Name | None = None


class Execution(OptionRecord):
    fill_id: Name
    quantity: PositiveCount
    price: Money = Field(gt=0)
    occurred_at: datetime


class HistoryOrder(Terms):
    order_id: Name
    client_id: Name | None = None
    status: Literal['OPEN', 'PARTIAL', 'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED']
    updated_at: datetime
    filled_quantity: Count
    fills: tuple[Execution, ...] = Field(max_length=1000)

    @model_validator(mode='after')
    def check_executions(self):
        quantity = sum(fill.quantity for fill in self.fills)
        if (len({f.fill_id for f in self.fills}) != len(self.fills)
                or quantity != self.filled_quantity or quantity > self.quantity
                or (self.status == 'FILLED') != (quantity == self.quantity)
                or (self.status in {'OPEN', 'REJECTED'} and quantity)
                or (self.status == 'PARTIAL' and quantity == 0)):
            raise ValueError('INCONSISTENT_BROKER_FILL_QUANTITY')
        for fill in self.fills:
            outside_limit = fill.price > self.limit_price if self.side == 'BUY' else fill.price < self.limit_price
            if fill.occurred_at > self.updated_at or outside_limit:
                raise ValueError('INCONSISTENT_BROKER_EXECUTION')
        return self


class History(OptionRecord):
    account_id: Name
    observed_at: datetime
    complete: StrictBool
    orders: tuple[HistoryOrder, ...] = Field(max_length=2000)


class RecoveryCase(OptionRecord):
    version: Literal['option-order-recovery-v1']
    attempt: Attempt
    snapshots: tuple[History, ...] = Field(min_length=1, max_length=256)


def _match(attempt, snapshot, order_id):
    matches = {}
    for order in snapshot.orders:
        if order.order_id != order_id and order.client_id != attempt.client_id:
            continue
        if (order_id is not None and order.order_id != order_id
                or order.client_id is not None and order.client_id != attempt.client_id
                or any(getattr(order, k) != getattr(attempt, k) for k in Terms.model_fields)):
            raise ValueError('ORDER_IDENTITY_CONFLICT')
        if (not attempt.attempted_at <= order.updated_at <= snapshot.observed_at
                or any(f.occurred_at < attempt.attempted_at for f in order.fills)):
            raise ValueError('ORDER_CLOCK_CONFLICT')
        if order.order_id in matches and matches[order.order_id] != order:
            raise ValueError('CONFLICTING_ORDER_COPIES')
        matches[order.order_id] = order
    if len(matches) > 1:
        raise ValueError('AMBIGUOUS_ORDER_IDENTITY')
    return next(iter(matches.values()), None)


def _progress(previous, current):
    old = {f.fill_id: f for f in previous.fills}
    new = {f.fill_id: f for f in current.fills}
    if current.updated_at < previous.updated_at or any(new.get(k) != v for k, v in old.items()):
        raise ValueError('BROKER_HISTORY_REGRESSED')
    changed = current.status != previous.status or old != new
    if changed and (previous.status in TERMINAL or current.updated_at == previous.updated_at):
        raise ValueError('BROKER_ORDER_STATE_CONFLICT')


def recover(case):
    case = RecoveryCase.model_validate(case)
    attempt = case.attempt
    last_time = attempt.attempted_at
    previous = None
    reason = 'ORDER_NOT_OBSERVED'
    last_snapshot = None
    for snapshot in case.snapshots:
        if snapshot.account_id != attempt.account_id:
            reason = 'ACCOUNT_MISMATCH'
            break
        if snapshot.observed_at < last_time:
            reason = 'BROKER_SNAPSHOT_REGRESSED'
            break
        if last_snapshot and snapshot.observed_at == last_time and snapshot != last_snapshot:
            reason = 'CONFLICTING_SIMULTANEOUS_SNAPSHOTS'
            break
        last_snapshot, last_time = snapshot, snapshot.observed_at
        if not snapshot.complete:
            reason = 'ORDER_HISTORY_INCOMPLETE'
            continue
        try:
            current = _match(attempt, snapshot, previous.order_id if previous else attempt.order_id)
            if current is None:
                reason = 'ORDER_NOT_OBSERVED'
                if previous:
                    reason = 'PREVIOUSLY_OBSERVED_ORDER_MISSING'
                    break
                continue
            if previous:
                _progress(previous, current)
        except ValueError as exc:
            reason = str(exc)
            break
        previous, reason = current, None
    return {
        'version': case.version, 'status': 'UNRESOLVED' if reason else 'MATCHED',
        'reason': reason, 'last_verified_status': previous.status if previous else None,
        'last_verified_filled_quantity': previous.filled_quantity if previous else None,
        'last_verified_fill_count': len(previous.fills) if previous else None,
        'terminal_confirmed': reason is None and previous.status in TERMINAL,
        'resubmit': False, 'provider_calls': False, 'state_modified': False, 'live_enabled': False,
    }


def verify_recovered_option(intent, row, observation, snapshot):
    """Apply the same exact match to an uncertain order during native PAPER reconciliation."""
    def terms(value):
        return dict(instrument_id=value.instrument.instrument_id, side=value.side,
                    quantity=value.quantity, limit_price=value.limit_price,
                    order_type='LIMIT', time_in_force='DAY', position_effect='OPEN' if value.side == 'BUY' else 'CLOSE')
    attempt = Attempt(**terms(intent), account_id=snapshot.account_id, client_id=intent.client_id,
                      order_id=row['order_id'], attempted_at=row['attempted_at'])
    order = HistoryOrder(**terms(observation), order_id=observation.order_id,
                         client_id=observation.client_id, status=observation.status,
                         updated_at=observation.updated_at, filled_quantity=observation.filled_quantity,
                         fills=tuple(Execution(**f.model_dump(include=set(Execution.model_fields)))
                                     for f in observation.fills))
    history = History(account_id=snapshot.account_id, observed_at=snapshot.captured_at,
                      complete=snapshot.complete, orders=(order,))
    if _match(attempt, history, attempt.order_id) is None:
        raise ValueError('PORTFOLIO_UNMATCHED_OPTION_ATTEMPT')
