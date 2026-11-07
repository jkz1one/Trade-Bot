"""Fill-bound underlying reference for explicitly enrolled native target protection."""

from decimal import Context, Decimal, localcontext
from fractions import Fraction

from pydantic import TypeAdapter, ValidationError

from app.options.engine import fingerprint
from app.options.lifecycle import EntryUnderlyingReference, EntryUnderlyingSample, OptionFill
from app.options.models import Money

MONEY = TypeAdapter(Money)


def append_reference(previous, intent, fill):
    """Accounting invokes this only for verified BUY fills; never for scale receipts."""
    u = fill.underlying
    sample = EntryUnderlyingSample(
        fill_id=fill.fill_id,
        fill_hash=fingerprint(fill),
        quantity=fill.quantity,
        reference=(u.ask if intent.instrument.contract.right == "CALL" else u.bid) if u else None,
    )
    return EntryUnderlyingReference(
        entry_quantity=intent.quantity,
        samples=(*(previous.samples if previous else ()), sample),
    )


def review_reference(position):
    """Exact quantity weighting, rounded toward tighter protection at 12 decimals."""
    state = position.entry_underlying_reference
    if state is None:
        return None
    filled = sum(s.quantity for s in state.samples)
    observed = sum(s.quantity for s in state.samples if s.reference is not None)
    reasons = []
    if filled != state.entry_quantity:
        reasons.append("ENTRY_FILL_INCOMPLETE")
    if observed != filled:
        reasons.append("ENTRY_UNDERLYING_MISSING")
    sign = 1 if position.contract.right == "CALL" else -1
    original = position.original_underlying_invalidation
    target = position.target_exit_schedule.steps[0].underlying_price
    if any(
        s.reference is not None
        and not (original < s.reference < target if sign == 1 else original > s.reference > target)
        for s in state.samples
    ):
        reasons.append("ENTRY_REFERENCE_OUTSIDE_GEOMETRY")
    reference = None
    if not reasons:
        value = sum(Fraction(s.reference) * s.quantity for s in state.samples) / filled
        scaled = value * 10**12
        units = (
            -(-scaled.numerator // scaled.denominator)
            if sign == 1
            else scaled.numerator // scaled.denominator
        )
        try:
            with localcontext(Context(prec=192)):
                reference = MONEY.validate_python((Decimal(units) / 10**12).normalize())
        except (ArithmeticError, ValidationError):
            reasons.append("ENTRY_REFERENCE_NUMERIC_RANGE")
    return {
        "version": state.version,
        "status": "READY" if not reasons else "BLOCKED",
        "reference": str(reference) if reference is not None else None,
        "entry_quantity": state.entry_quantity,
        "filled_quantity": filled,
        "observed_quantity": observed,
        "evidence_hash": fingerprint(state),
        "reasons": reasons,
        "authority": False,
    }


def stored_reference(db, position, limits):
    """Verify the saved basis against original fills without refreshing or writing."""
    if position.entry_underlying_reference is None:
        return None
    from app.options.fill_evidence import validate_fill
    from app.options.lifecycle import OptionIntent, OptionObservation

    row = db.execute(
        "SELECT intent_json,observation_json FROM execution_orders WHERE client_id=?",
        (position.entry_client_id,),
    ).fetchone()
    if row is None or row[1] is None:
        raise ValueError("ENTRY_REFERENCE_RECEIPTS_MISSING")
    intent = OptionIntent.model_validate_json(row[0])
    observation = OptionObservation.model_validate_json(row[1])
    fills = tuple(
        OptionFill.model_validate_json(r[0])
        for r in db.execute(
            "SELECT payload FROM execution_fills WHERE client_id=? ORDER BY json_extract(payload,'$.sequence') LIMIT 1001",
            (position.entry_client_id,),
        )
    )
    if (
        intent.side != "BUY"
        or intent.target_exit_schedule != position.target_exit_schedule
        or intent.instrument.contract != position.contract
        or intent.original_underlying_invalidation != position.original_underlying_invalidation
        or fills != observation.fills
        or not fills
    ):
        raise ValueError("ENTRY_REFERENCE_RECEIPTS_CHANGED")
    state, used = None, {}
    for index, fill in enumerate(fills):
        validate_fill(limits, intent, fill, index, used)
        state = append_reference(state, intent, fill)
    if state != position.entry_underlying_reference:
        raise ValueError("ENTRY_REFERENCE_BASIS_CHANGED")
    return review_reference(position)
