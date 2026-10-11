"""Pure fixture-fill audit shared by authoritative reconciliation and offline evaluation."""

import hashlib
from decimal import ROUND_CEILING, ROUND_FLOOR

from app.options.engine import fingerprint
from app.options.governor import _fresh, _tick_price


def validate_fill(limits, intent, fill, index, used):
    q = fill.quote
    if (
        q.instrument != intent.instrument
        or q.source != limits.option_source
        or not q.complete
        or q.entitlement != "REALTIME"
        or not _fresh(
            q.source_at,
            q.received_at,
            fill.occurred_at,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
        or q.bid is None
        or q.bid <= 0
        or (q.ask is not None and q.ask < q.bid)
    ):
        raise ValueError("OPTION_FILL_EXECUTABLE_EVIDENCE_INVALID")
    digest = hashlib.sha256(q.model_dump_json().encode()).hexdigest()
    if digest != fill.quote_hash:
        raise ValueError("OPTION_FILL_QUOTE_HASH_MISMATCH")
    canonical = fingerprint(q)
    key = (intent.side, canonical)
    used[key] = used.get(key, 0) + fill.quantity
    raw, size = (q.ask, q.ask_size) if intent.side == "BUY" else (q.bid, q.bid_size)
    if raw is None or used[key] > size:
        raise ValueError("OPTION_FILL_EXCEEDS_OBSERVED_SIZE")
    sign = 1 if intent.side == "BUY" else -1
    expected = _tick_price(
        raw * (1 + sign * limits.slippage_bps / 10000),
        intent.instrument.contract,
        ROUND_CEILING if sign == 1 else ROUND_FLOOR,
    )
    per_order, per_contract = (
        (limits.entry_fee_per_order, limits.entry_fee_per_contract)
        if sign == 1
        else (limits.exit_fee_per_order, limits.exit_fee_per_contract)
    )
    if (
        fill.price != expected
        or fill.fee != per_contract * fill.quantity + (per_order if index == 0 else 0)
        or (sign == 1 and fill.price > intent.limit_price)
        or (sign == -1 and fill.price < intent.limit_price)
    ):
        raise ValueError("OPTION_FILL_PRICE_OR_FEE_MISMATCH")
