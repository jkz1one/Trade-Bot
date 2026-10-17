"""Observed Greek pressure diagnostics, without management or execution authority."""

from datetime import timedelta
from decimal import Decimal

from app.options.engine import clock, exact, fingerprint
from app.options.governor import _fresh
from app.options.models import OptionLimits, OptionQuote

SOURCE_COMMIT = "f9eaf2c1b5d13dca287ee7138126883065b00395"
D = Decimal


def _usable(quote, limits, at, prefix, reasons):
    if quote is None:
        reasons.add(prefix + "_QUOTE_MISSING")
        return False
    if (
        quote.instrument.provider != limits.provider
        or quote.source != limits.option_source
        or not quote.instrument.metadata_complete
        or not quote.instrument.option_tradable
        or not quote.complete
        or quote.entitlement != "REALTIME"
        or quote.bid is None
        or quote.bid <= 0
        or quote.bid_size == 0
        or (quote.ask is not None and quote.ask < quote.bid)
        or not _fresh(
            quote.source_at,
            quote.received_at,
            at,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        reasons.add(prefix + "_QUOTE_UNUSABLE")
        return False
    g = quote.greeks
    if g is None:
        reasons.add(prefix + "_GREEKS_MISSING")
        return False
    if (
        g.source != limits.option_source
        or not g.complete
        or g.entitlement != "REALTIME"
        or g.provenance != "OBSERVED"
        or g.received_at > quote.received_at
        or abs(g.source_at - quote.source_at) > timedelta(seconds=limits.max_sync_seconds)
        or not _fresh(
            g.source_at,
            g.received_at,
            at,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        reasons.add(prefix + "_GREEKS_UNUSABLE")
        return False
    return True


def _delta(g, right, prefix, reasons, *, baseline=False):
    value = g.delta
    if value is None or (baseline and value == 0):
        reasons.add(prefix + "_DELTA_MISSING_OR_ZERO")
        return None
    if (right == "CALL" and value < 0) or (right == "PUT" and value > 0):
        reasons.add(prefix + "_DELTA_WRONG_SIGN")
        return None
    return abs(value)


def _iv(g, prefix, reasons, *, baseline=False):
    value = g.implied_volatility
    if value is None or (baseline and value == 0):
        reasons.add(prefix + "_IV_MISSING_OR_ZERO")
        return None
    return value


def _display(value):
    # Display rounding cannot change an exact threshold decision.
    return str(value.quantize(D(".000001"))) if value is not None else None


@exact
def review_greek_pressure(entry_quote, current_quote, limits, *, entry_at, now):
    """Compare exact supplied observations. READY means evidence, never trade health.

    The caller binds the baseline to the original approved entry, not a later
    replacement. No option pricing model, provider, account or order is invoked.
    """
    entry_at, now = clock(entry_at), clock(now)
    if entry_at > now:
        raise ValueError("Greek review cannot precede entry")
    limits = OptionLimits.model_validate(limits.model_dump(warnings=False))
    entry, current = (
        OptionQuote.model_validate(q.model_dump(warnings=False)) if q is not None else None
        for q in (entry_quote, current_quote)
    )
    reasons = set()
    entry_ok = _usable(entry, limits, entry_at, "ENTRY", reasons)
    current_ok = _usable(current, limits, now, "CURRENT", reasons)
    if entry and current and entry.instrument != current.instrument:
        reasons.add("EXACT_ENTRY_INSTRUMENT_REQUIRED")
        current_ok = False
    if current and (
        current.source_at < entry_at
        or (entry and current.received_at < entry.received_at)
        or (current.greeks and current.greeks.source_at < entry_at)
    ):
        reasons.add("CURRENT_EVIDENCE_PRECEDES_ENTRY")
        current_ok = False
    daily = hourly = iv_change = delta_change = None
    signals = dict.fromkeys(
        ("theta_pressure", "iv_warning", "iv_severe", "delta_warning", "delta_severe")
    )
    base_delta = (
        _delta(entry.greeks, entry.instrument.contract.right, "ENTRY", reasons, baseline=True)
        if entry_ok
        else None
    )
    base_iv = _iv(entry.greeks, "ENTRY", reasons, baseline=True) if entry_ok else None
    if current_ok:
        g = current.greeks
        if g.theta is None:
            reasons.add("CURRENT_THETA_MISSING")
        else:
            daily = abs(g.theta) * 100 / current.bid
            hourly = daily / D("6.5")
            signals["theta_pressure"] = abs(g.theta) * 100 >= current.bid * D("6.5") * 6
        delta = _delta(g, current.instrument.contract.right, "CURRENT", reasons)
        iv = _iv(g, "CURRENT", reasons)
        if base_delta is not None and delta is not None:
            delta_change = (delta / base_delta - 1) * 100
            signals["delta_warning"] = delta <= base_delta * D(".80")
            signals["delta_severe"] = delta <= base_delta * D(".65")
        if base_iv is not None and iv is not None:
            iv_change = (iv / base_iv - 1) * 100
            signals["iv_warning"] = iv <= base_iv * D(".85")
            signals["iv_severe"] = iv <= base_iv * D(".75")
    return {
        "version": "observed-greek-pressure-v1",
        "source_commit": SOURCE_COMMIT,
        "status": "INCOMPLETE" if reasons else "READY",
        "evaluated_at": now.isoformat(),
        "entry_at": entry_at.isoformat(),
        "entry_quote_hash": fingerprint(entry) if entry else None,
        "current_quote_hash": fingerprint(current) if current else None,
        "entry_greeks": entry.greeks.model_dump(mode="json") if entry and entry.greeks else None,
        "current_greeks": current.greeks.model_dump(mode="json")
        if current and current.greeks
        else None,
        "theta_pct_per_day": _display(daily),
        "reference_hourly_theta_pct": _display(hourly),
        "iv_change_pct": _display(iv_change),
        "absolute_delta_change_pct": _display(delta_change),
        "signals": signals,
        "known_warning_count": sum(
            signals[k] is True for k in ("theta_pressure", "iv_warning", "delta_warning")
        ),
        "reasons": sorted(reasons),
        "execution_authority": False,
        "live_enabled": False,
        "note": "Observed Greek diagnostics only; hourly theta uses the source's fixed 6.5-hour heuristic, not a decay forecast or complete trade-health decision.",
    }
