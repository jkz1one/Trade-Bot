"""Original Robinhood SPX observations for the explicit price/options Scope variant.

Index values remain non-executable references. No bid/ask, volume, interpolation
flags, calendar attestation or SPXW contract terms are inferred from them.
"""
from datetime import timedelta


from app.options.degen import DegenHistory
from app.options.engine import fingerprint
from app.options.input_probe import PINS, index_id
from app.options.models import IndexReference
from app.options.read_gateway import MAX_SAMPLE_BYTES, encoded
from app.options.read_mapping import instant
from app.options.scope import PRICE_GROUPS, ScopeEvidence, ScopeHistory, ScopePreflightInput, ScopePriceBar, ScopeSession
from app.options.scope_context import ScopeContextInput
from app.options.scope_structure import structure_payload_hashes



def receipt_data(receipt, tool):
    if (receipt.get("tool") != tool or receipt.get("metadata_sha256") != PINS[tool]
            or receipt.get("completed") is not True
            or receipt.get("output_schema_validated") is not True):
        raise ValueError("Completed schema-pinned original SPX receipt required")
    attempted, received = instant(receipt["attempted_at"]), instant(receipt["received_at"])
    raw = receipt.get("raw")
    if (received < attempted or not isinstance(raw, dict)
            or len(encoded(raw)) > MAX_SAMPLE_BYTES or raw.get("isError", False) is not False):
        raise ValueError("Bounded ordered SPX receipt required")
    data = raw.get("structuredContent", {}).get("data")
    if not isinstance(data, dict) or data.get("restricted"):
        raise ValueError("Unrestricted structured SPX data required")
    return data, received


def map_index(identity_receipt, quote_receipt, history_receipt, session, *, now):
    """Return exact native history only when every completed session bar is original.

    The source's nullable interpolation flag is tri-state: omission is unknown.
    Retained original receipt hashes cover all rows, including unused overnight rows.
    """
    session = ScopeSession.model_validate(session.model_dump())
    now = instant(now)
    identity_data, identity_received = receipt_data(identity_receipt, "get_indexes")
    identity = index_id(identity_data)
    if identity is None or identity_receipt["arguments"] != {"symbols": "SPX"}:
        raise ValueError("Exact non-halted SPX identity required")
    qdata, qr = receipt_data(quote_receipt, "get_index_quotes")
    hdata, hr = receipt_data(history_receipt, "get_index_historicals")
    if not identity_received <= min(qr, hr) <= max(qr, hr) <= now:
        raise ValueError("SPX observations were not yet received")
    if quote_receipt["arguments"] != {"instrument_ids": [identity]}:
        raise ValueError("Exact SPX quote request required")
    args = history_receipt["arguments"]
    if (set(args) != {"instrument_ids", "interval", "start_time", "end_time"}
            or args["instrument_ids"] != [identity] or args["interval"] != "5minute"
            or not instant(args["start_time"]) < instant(args["end_time"]) <= hr
            or instant(args["end_time"]) - instant(args["start_time"]) > timedelta(days=1)):
        raise ValueError("Bounded exact SPX five-minute request required")
    quotes, histories = qdata.get("quotes"), hdata.get("results")
    if (not isinstance(quotes, list) or len(quotes) != 1
            or not isinstance(histories, list) or len(histories) != 1
            or any(not isinstance(row, dict) or row.get("symbol") != "SPX"
                   or row.get("instrument_id") != identity for row in (*quotes, *histories))):
        raise ValueError("Exact SPX result identity and coverage required")
    q, h = quotes[0], histories[0]
    if h.get("interval") != "5minute":
        raise ValueError("Exact SPX history interval required")
    source = instant(q["venue_timestamp"])
    if source > qr:
        raise ValueError("SPX venue clock follows receipt")
    reference = IndexReference(instrument_id=identity, value=q["value"], source_at=source,
        original_source_time=q["venue_timestamp"], received_at=qr,
        provider_updated_at=q.get("updated_at"), receipt_sha256=fingerprint(quote_receipt))
    issues = []
    if not 0 <= (now - source).total_seconds() <= 30:
        issues.append("SPX_INDEX_VALUE_STALE")
    count = int((min(now, session.closes_at) - session.opens_at).total_seconds() // 300)
    if not 5 <= count <= 96:
        issues.append("SPX_COMPLETED_SESSION_WINDOW_REQUIRED")
    rows = h.get("bars")
    if not isinstance(rows, list) or len(rows) > 400:
        raise ValueError("Bounded original SPX bars required")
    all_starts = [instant(b["begins_at"]) for b in rows]
    if all_starts != sorted(set(all_starts)):
        raise ValueError("Original SPX bars duplicated or reordered")
    selected = [b for b, at in zip(rows, all_starts, strict=True)
                if session.opens_at <= at < min(now, session.closes_at)
                and at + timedelta(minutes=5) <= min(now, hr, instant(args["end_time"]))]
    expected = [session.opens_at + timedelta(minutes=5*n) for n in range(max(0, count))]
    if [instant(b["begins_at"]) for b in selected] != expected:
        issues.append("SPX_COMPLETED_HISTORY_GAP")
    if any(b.get("interpolated") is True for b in selected):
        issues.append("SPX_INTERPOLATED_HISTORY")
    if any(b.get("interpolated") is not True and b.get("interpolated") is not False for b in selected):
        issues.append("SPX_INTERPOLATION_STATUS_UNKNOWN")
    history = None
    if not issues:
        bars = tuple(ScopePriceBar(begins_at=b["begins_at"], open=b["open_value"],
            high=b["high_value"], low=b["low_value"], close=b["close_value"],
            interpolated=b["interpolated"]) for b in selected)
        history = ScopeHistory(symbol="SPX", source="robinhood-mcp", source_at=bars[-1].ends_at,
            received_at=hr, entitlement="UNKNOWN", complete=True, bars=bars,
            simulation_basis="ROBINHOOD_OBSERVED_V1")
    return reference, history, {
        "version": "robinhood-scope-source-mapping-v1", "issues": sorted(set(issues)),
        "status": "MAPPED" if history is not None else "BLOCKED",
        "reference": reference.model_dump(mode="json"), "session_bars": len(selected),
        "capture_hashes": [fingerprint(r) for r in (identity_receipt, quote_receipt, history_receipt)],
        "entitlement": "UNKNOWN", "volume_available": False,
        "trading_ready": False, "live_enabled": False,
    }


def assemble(session, index_history, equity_histories, metadata, quote, *, previous_session, index_reference=None):
    """Join mapped originals for native price/options scans, with exact payload hashes.

    This does not create a Scope watch or turn an index reference into a quote.
    The caller supplies reviewed calendar and contract terms; they cannot be
    inferred from a chain symbol or the index's last value.
    """
    from app.mixed.observed_simulation import annotate
    session = ScopeSession.model_validate(session.model_dump())
    index_history = ScopeHistory.model_validate(index_history.model_dump())
    equities = tuple(DegenHistory.model_validate(h.model_dump()) for h in equity_histories)
    if index_history.symbol != "SPX" or len(equities) != 2 or {h.symbol for h in equities} != {"SPY", "QQQ"}:
        raise ValueError("One original SPX, SPY and QQQ history required")
    histories = (index_history, *(ScopeHistory.model_validate({
        k: v for k, v in annotate(h).model_dump().items() if k != "adjustment"
    }) for h in equities))
    frame = ScopePreflightInput(session=session, histories=histories, evidence=(), index_reference=index_reference,
                               metadata=annotate(metadata), quote=annotate(quote))
    hashes = structure_payload_hashes(frame)
    hashes["provider_readiness"] = fingerprint({"histories": histories, "metadata": frame.metadata, "quote": frame.quote})
    hashes["spxw_contracts"] = fingerprint({"metadata": frame.metadata, "quote": frame.quote})
    # Each attestation retains the clocks of its own payload. Completed history
    # is distinct from the current option book; assembly never creates a tick.
    items = (*histories, frame.metadata, frame.quote)
    if any(e is None or e.source != "robinhood-mcp" or not e.complete
           or e.entitlement != "UNKNOWN" or e.simulation_basis != "ROBINHOOD_OBSERVED_V1" for e in items):
        raise ValueError("Explicit complete observed Robinhood inputs required")
    groups = {"technical_structure": (histories[0],), "cross_market_agreement": histories,
              "provider_readiness": (frame.metadata, frame.quote),
              "spxw_contracts": (frame.metadata, frame.quote)}
    evidence = tuple(ScopeEvidence(kind=kind, payload_hash=hashes[kind], status="AVAILABLE",
        source="robinhood-mcp", source_at=min(e.source_at for e in groups[kind]),
        received_at=max(e.received_at for e in groups[kind]), entitlement="UNKNOWN", complete=True,
        simulation_basis="ROBINHOOD_OBSERVED_V1") for kind in PRICE_GROUPS)
    frame = ScopePreflightInput.model_validate(frame.model_dump() | {"evidence": evidence})
    context = ScopeContextInput(previous_session=previous_session, dealer=None, moves=None,
                               flow=None, news=None, events=None, prior=None)
    return frame, context
