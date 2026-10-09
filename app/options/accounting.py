"""Exact whole-lot PAPER accounting. Settlement receipts are distinct from trades."""

from decimal import Context, Decimal, localcontext
from zoneinfo import ZoneInfo

from app.options.lifecycle import OptionLedger, OptionLot, OptionPosition

ZERO = Decimal(0)


def consume_lots(position, quantity):
    if not 0 < quantity <= position.quantity:
        raise ValueError("Unowned sale or invalid contract allocation")
    remaining, removed, lots = quantity, ZERO, []
    for lot in position.lots:
        take = min(lot.quantity, remaining)
        removed += take * lot.price * position.contract.multiplier
        remaining -= take
        if lot.quantity > take:
            lots.append(lot.model_copy(update={"quantity": lot.quantity - take}))
    return tuple(lots), removed


def apply_fill(ledger, intent, fill):
    with localcontext(Context(prec=192)):
        position = ledger.position
        premium = fill.quantity * fill.price * intent.instrument.contract.multiplier
        gross = ZERO
        if intent.side == "BUY":
            if position and (
                position.entry_client_id != intent.client_id
                or position.contract != intent.instrument.contract
            ):
                raise ValueError("A new buy cannot add to an owned position")
            lots = (
                (*position.lots, OptionLot(quantity=fill.quantity, price=fill.price))
                if position
                else (OptionLot(quantity=fill.quantity, price=fill.price),)
            )
            if position:
                position = position.model_copy(
                    update={"lots": lots, "quantity": position.quantity + fill.quantity}
                )
            else:
                position = OptionPosition(
                    contract=intent.instrument.contract,
                    quantity=fill.quantity,
                    original_underlying_invalidation=intent.original_underlying_invalidation,
                    tightened_underlying_invalidation=intent.original_underlying_invalidation,
                    entry_client_id=intent.client_id,
                    lots=lots,
                    exit_at=intent.exit_at,
                )
            cash = ledger.cash - premium - fill.fee
            settled = ledger.settled_cash - premium - fill.fee
        else:
            if position is None or position.contract != intent.instrument.contract:
                raise ValueError("No exact option position to sell")
            lots, basis = consume_lots(position, fill.quantity)
            gross = premium - basis
            delta = premium - fill.fee
            cash = ledger.cash + delta
            # Sale credits remain unsettled until an explicit authoritative receipt.
            settled = ledger.settled_cash + min(ZERO, delta)
            position = (
                position.model_copy(
                    update={"lots": lots, "quantity": position.quantity - fill.quantity}
                )
                if lots
                else None
            )
        day = fill.occurred_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        return OptionLedger.model_validate(
            {
                **ledger.model_dump(),
                "cash": cash,
                "settled_cash": settled,
                "position": position,
                "realized_pnl": ledger.realized_pnl + gross,
                "fees_paid": ledger.fees_paid + fill.fee,
                "daily_net_pnl": {
                    **ledger.daily_net_pnl,
                    day: ledger.daily_net_pnl.get(day, ZERO) + gross - fill.fee,
                },
                "high_watermark": max(ledger.high_watermark, cash if position is None else ZERO),
            }
        )


def apply_receipt(ledger, receipt):
    with localcontext(Context(prec=192)):
        if receipt.kind == "FUNDS_SETTLED":
            if (
                receipt.contract is not None
                or receipt.quantity
                or not ZERO < receipt.cash_change <= ledger.cash - ledger.settled_cash
            ):
                raise ValueError("Invalid settled-funds receipt")
            return OptionLedger.model_validate(
                {**ledger.model_dump(), "settled_cash": ledger.settled_cash + receipt.cash_change}
            )
        position = ledger.position
        if (
            position is None
            or receipt.contract != position.contract
            or receipt.quantity != position.quantity
        ):
            raise ValueError("Settlement must bind the exact complete owned position")
        contract = position.contract
        if receipt.kind == "PHYSICAL_EXERCISE":
            raise ValueError("UNEXPECTED_UNDERLYING_EXPOSURE")
        if receipt.settlement_value is None:
            raise ValueError("Authoritative settlement value required")
        intrinsic = max(
            ZERO,
            (receipt.settlement_value - contract.strike)
            if contract.right == "CALL"
            else (contract.strike - receipt.settlement_value),
        )
        if receipt.kind == "EXPIRED_WORTHLESS":
            if (
                intrinsic != 0
                or receipt.cash_change != 0
                or receipt.occurred_at < contract.expires_at
            ):
                raise ValueError("Invalid authoritative worthless-expiry receipt")
        elif (
            contract.settlement != "CASH"
            or receipt.occurred_at < contract.settles_at
            or receipt.cash_change != intrinsic * contract.multiplier * receipt.quantity
        ):
            raise ValueError("Invalid exact cash-settlement receipt")
        pnl = receipt.cash_change - position.basis
        day = receipt.occurred_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        cash = ledger.cash + receipt.cash_change
        return OptionLedger.model_validate(
            {
                **ledger.model_dump(),
                "cash": cash,
                "settled_cash": ledger.settled_cash + receipt.cash_change,
                "position": None,
                "realized_pnl": ledger.realized_pnl + pnl,
                "daily_net_pnl": {
                    **ledger.daily_net_pnl,
                    day: ledger.daily_net_pnl.get(day, ZERO) + pnl,
                },
                "high_watermark": max(ledger.high_watermark, cash),
            }
        )
