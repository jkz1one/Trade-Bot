"""Pure, tool-less long-option admission. It cannot reserve, submit or cancel orders."""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext

from app.options.models import (
    OptionAccount,
    OptionAdmission,
    OptionContract,
    OptionHolding,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    SessionWindow,
    UnderlyingQuote,
)

ONE = Decimal(1)


def _fresh(source_at, received_at, now, age, lag):
    return (
        source_at <= received_at <= now
        and now - source_at < timedelta(seconds=age)
        and received_at - source_at <= timedelta(seconds=lag)
    )


def _supported(contract: OptionContract):
    if contract.adjusted or contract.multiplier != 100:
        return False
    if contract.tick_below_three not in {Decimal(".01"), Decimal(".05"), Decimal(".10")}:
        return False
    if contract.tick_at_or_above_three not in {Decimal(".01"), Decimal(".05"), Decimal(".10")}:
        return False
    if contract.underlying_kind == "INDEX":
        return (
            contract.settlement == "CASH"
            and contract.underlying_market == "US_INDEX"
            and contract.deliverable_kind == "CASH"
            and contract.deliverable_units == 0
            and contract.exercise_style == "EUROPEAN"
        )
    return (
        contract.settlement == "PHYSICAL"
        and contract.underlying_market == "US_LISTED"
        and contract.deliverable_kind == "SHARES"
        and contract.deliverable_units == 100
        and contract.exercise_style == "AMERICAN"
        and contract.settlement_session == "PM"
    )


def _tick_price(price, contract, rounding):
    tick = contract.tick_below_three if price < 3 else contract.tick_at_or_above_three
    rounded = (price / tick).to_integral_value(rounding=rounding) * tick
    # Rounding across $3 must satisfy the destination tier too.
    tick = contract.tick_below_three if rounded < 3 else contract.tick_at_or_above_three
    return (rounded / tick).to_integral_value(rounding=rounding) * tick


def admit_option(
    proposal: OptionProposal,
    quote: OptionQuote | None,
    underlying: UnderlyingQuote | None,
    account: OptionAccount,
    limits: OptionLimits,
    session: SessionWindow | None,
    *,
    now: datetime,
) -> OptionAdmission:
    """Revalidate even frozen model_copy inputs. Malformed evidence raises before approval.

    Caller must persist inputs/results and re-admit at dispatch in M2. No database,
    network, model, brokerage, credential or Settings dependency is used here.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Admission clock must be timezone-aware")
    now = now.astimezone(UTC)
    proposal = OptionProposal.model_validate(proposal.model_dump(warnings=False))
    # HOLD needs no account, quote, entitlement or provider work.
    if proposal.action == "HOLD":
        return OptionAdmission(outcome="HOLD", action="HOLD", approved_at=now)
    account = OptionAccount.model_validate(account.model_dump(warnings=False))
    limits = OptionLimits.model_validate(limits.model_dump(warnings=False))
    quote = (
        OptionQuote.model_validate(quote.model_dump(warnings=False)) if quote is not None else None
    )
    underlying = (
        UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
        if underlying is not None and proposal.action == "OPEN_LONG"
        else None
    )
    session = (
        SessionWindow.model_validate(session.model_dump(warnings=False))
        if session is not None
        else None
    )
    contract = proposal.contract
    assert contract is not None
    reasons = []

    def reject(*additional):
        return OptionAdmission(
            outcome="REJECTED",
            action=proposal.action,
            contract_id=contract.contract_id,
            reasons=tuple(dict.fromkeys([*reasons, *additional])),
            approved_at=now,
        )

    if account.account_id != limits.account_id or account.population_id != limits.population_id:
        reasons.append("ACCOUNT_POPULATION_MISMATCH")
    if not account.complete or not account.reconciled:
        reasons.append("ACCOUNT_NOT_RECONCILED")
    if (
        not timedelta(0)
        <= now - account.captured_at
        < timedelta(seconds=limits.account_max_age_seconds)
    ):
        reasons.append("STALE_OR_FUTURE_ACCOUNT")
    if account.unsupported_exposure:
        reasons.append("UNSUPPORTED_ACCOUNT_EXPOSURE")
    if account.working_orders:
        reasons.append("UNRESOLVED_ORDER")
    if contract.underlying not in limits.allowed_underlyings:
        reasons.append("UNDERLYING_NOT_ALLOWED")
    if not _supported(contract):
        reasons.append("UNSUPPORTED_CONTRACT_METADATA")
    if now >= contract.last_trading_at:
        reasons.append("CONTRACT_TRADING_ENDED")
    if session is None:
        reasons.append("SESSION_EVIDENCE_MISSING")
    elif (
        session.source != limits.session_source
        or session.underlying != contract.underlying
        or not session.opens_at <= now < min(session.closes_at, contract.last_trading_at)
    ):
        reasons.append("INVALID_OR_CLOSED_SESSION")
    if quote is None:
        return reject("OPTION_QUOTE_MISSING")
    if quote.instrument.contract != contract:
        reasons.append("EXACT_CONTRACT_MISMATCH")
    if quote.instrument.provider != limits.provider or quote.source != limits.option_source:
        reasons.append("OPTION_SOURCE_MISMATCH")
    if not quote.instrument.metadata_complete or not quote.instrument.option_tradable:
        reasons.append("OPTION_METADATA_OR_TRADABILITY")
    if not quote.complete or quote.entitlement != "REALTIME":
        reasons.append("OPTION_COVERAGE_OR_ENTITLEMENT")
    if not _fresh(
        quote.source_at,
        quote.received_at,
        now,
        limits.quote_max_age_seconds,
        limits.max_receive_lag_seconds,
    ):
        reasons.append("INVALID_OPTION_QUOTE_TIME")
    if (
        quote.bid is None
        or quote.bid <= 0
        or (quote.ask is not None and quote.ask < quote.bid)
        or (proposal.action == "OPEN_LONG" and quote.ask is None)
    ):
        reasons.append("INVALID_OR_MISSING_EXECUTABLE_QUOTE")

    if proposal.action == "CLOSE":
        position = account.position
        if not isinstance(position, OptionHolding) or position.contract != contract:
            reasons.append("NO_EXACT_OWNED_OPTION")
        if quote.bid_size == 0:
            reasons.append("NO_EXECUTABLE_BID_SIZE")
        if reasons:
            return reject()
        assert isinstance(position, OptionHolding) and quote.bid is not None
        # Entry halts, exhausted budgets and broken thesis evidence cannot veto
        # a funded, owned close. Exact contract/account/executable evidence still can.
        with localcontext(Context(prec=_precision(quote, limits, account))):
            price = _tick_price(
                quote.bid * (ONE - limits.slippage_bps / 10_000), contract, ROUND_FLOOR
            )
            quantity = min(position.quantity, quote.bid_size)
            fees = limits.exit_fee_per_order + quantity * limits.exit_fee_per_contract
            proceeds = quantity * price * contract.multiplier - fees
            if price <= 0 or proceeds < -(account.settled_cash - account.reserved_cash):
                return reject("CLOSE_NOT_CASH_CONSERVING")
            return OptionAdmission(
                outcome="APPROVED",
                action="CLOSE",
                contract_id=contract.contract_id,
                quantity=quantity,
                limit_price=price,
                minimum_exit_cash_change=proceeds,
                approved_at=now,
                valid_until=_deadline(now, quote, account, limits, session, contract),
            )

    if account.position is not None:
        reasons.append("POSITION_ALREADY_OPEN_NO_ADDS")
    if account.entry_halted:
        reasons.append("ENTRY_HALTED")
    reasons.extend(account.entry_blockers)
    if not account.budgets_known:
        reasons.append("UNKNOWN_COST_OR_LOSS_BUDGET")
    if session is not None and now >= session.entry_cutoff_at:
        reasons.append("ENTRY_CUTOFF")
    if quote.ask_size == 0:
        reasons.append("NO_EXECUTABLE_ASK_SIZE")
    if underlying is None:
        reasons.append("UNDERLYING_EVIDENCE_MISSING")
    else:
        if (
            underlying.symbol != contract.underlying
            or underlying.source != limits.underlying_source
        ):
            reasons.append("UNDERLYING_SOURCE_OR_SYMBOL_MISMATCH")
        if underlying.bid < limits.minimum_underlying_price:
            reasons.append("UNDERLYING_BELOW_PRICE_FLOOR")
        if not underlying.complete or underlying.entitlement != "REALTIME":
            reasons.append("UNDERLYING_COVERAGE_OR_ENTITLEMENT")
        if (
            not _fresh(
                underlying.source_at,
                underlying.received_at,
                now,
                limits.quote_max_age_seconds,
                limits.max_receive_lag_seconds,
            )
            or underlying.bid > underlying.ask
        ):
            reasons.append("INVALID_UNDERLYING_QUOTE")
        if abs(underlying.source_at - quote.source_at) > timedelta(seconds=limits.max_sync_seconds):
            reasons.append("UNSYNCHRONIZED_EVIDENCE")
        stop = proposal.underlying_invalidation
        assert stop is not None
        if (contract.right == "CALL" and stop >= underlying.bid) or (
            contract.right == "PUT" and stop <= underlying.ask
        ):
            reasons.append("INVALID_UNDERLYING_INVALIDATION")
    if reasons:
        return reject()
    assert quote.ask is not None and quote.bid is not None
    with localcontext(Context(prec=_precision(proposal, quote, limits, account))):
        if (quote.ask - quote.bid) > limits.max_spread_fraction * quote.ask:
            return reject("OPTION_SPREAD_TOO_WIDE")
        price = _tick_price(
            quote.ask * (ONE + limits.slippage_bps / 10_000), contract, ROUND_CEILING
        )
        entry_unit = price * contract.multiplier + limits.entry_fee_per_contract
        loss_unit = entry_unit + limits.exit_fee_per_contract
        fixed_loss_fees = limits.entry_fee_per_order + limits.exit_fee_per_order
        debit_cap = min(limits.max_entry_debit, limits.max_account_exposure)
        if proposal.max_entry_debit is not None:
            debit_cap = min(debit_cap, proposal.max_entry_debit)
        loss_cap = min(
            limits.max_full_premium_loss,
            account.daily_loss_available,
            account.total_loss_available,
            account.settled_cash - account.reserved_cash,
        )
        # Floor each independent cap. A modeled stop never increases these budgets.
        quantity = min(
            limits.max_contracts,
            quote.ask_size,
            _whole_quantity(debit_cap - limits.entry_fee_per_order, entry_unit),
            _whole_quantity(loss_cap - fixed_loss_fees, loss_unit),
        )
        if quantity <= 0:
            return reject("ONE_CONTRACT_EXCEEDS_FUNDS_OR_LIMITS")
        entry_debit = quantity * entry_unit + limits.entry_fee_per_order
        exit_fees = quantity * limits.exit_fee_per_contract + limits.exit_fee_per_order
        return OptionAdmission(
            outcome="APPROVED",
            action="OPEN_LONG",
            contract_id=contract.contract_id,
            quantity=quantity,
            limit_price=price,
            entry_debit=entry_debit,
            full_premium_loss=entry_debit + exit_fees,
            reserved_exit_fees=exit_fees,
            approved_at=now,
            valid_until=_deadline(now, quote, account, limits, session, contract, underlying),
        )


def _precision(*models):
    # Enough exact precision for every supplied Decimal's coefficient and exponent,
    # including very near integer sizing boundaries. Do not inherit caller rounding.
    def decimals(value):
        if isinstance(value, Decimal):
            yield len(value.as_tuple().digits) + abs(value.as_tuple().exponent)
        elif isinstance(value, dict):
            for item in value.values():
                yield from decimals(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from decimals(item)

    return max(64, sum(n for model in models for n in decimals(model.model_dump())) + 32)


def _whole_quantity(budget, unit_cost):
    # Rational integer division cannot round a just-unaffordable contract upward.
    numerator, denominator = budget.as_integer_ratio()
    unit_numerator, unit_denominator = unit_cost.as_integer_ratio()
    return numerator * unit_denominator // (denominator * unit_numerator)


def _deadline(now, quote, account, limits, session, contract, underlying=None):
    assert session is not None
    dates = [
        now + timedelta(seconds=limits.approval_lifetime_seconds),
        quote.source_at + timedelta(seconds=limits.quote_max_age_seconds),
        account.captured_at + timedelta(seconds=limits.account_max_age_seconds),
        session.closes_at,
        contract.last_trading_at,
    ]
    if underlying is not None:
        dates.extend(
            [
                underlying.source_at + timedelta(seconds=limits.quote_max_age_seconds),
                session.entry_cutoff_at,
            ]
        )
    return min(dates)
