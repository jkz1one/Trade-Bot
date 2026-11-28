"""Bounded read-only catalog capture; never enroll, start workers or submit orders."""
import argparse
import copy
import json
import os
import time
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from app.mixed.contract_catalog import capture as inspect_capture, digest, review
from app.options.operator_inbox import private_directory, read, save
from app.options.read_capture import CaptureResult
from app.options.read_mapping import quote_rows, response
from app.options.schema_artifact import load_reviewed_schemas

SYMBOLS = ("SPY", "QQQ")
MAX_STRIKE_PAGES = 4
MAX_STRIKES_PER_PAGE = 256
PUBLIC_REASONS = frozenset({
    'CONTRACT_PROBE_INVALID', 'STRIKE_LISTING_INVALID', 'STRIKE_LISTING_EMPTY',
    'STRIKE_LISTING_PAGE_LIMIT', 'STRIKE_LISTING_CURSOR_REPEATED',
    'SELECTED_CONTRACT_UNAVAILABLE', 'CATALOG_VALIDATION_FAILED',
})


class ProviderCaptureFailed(ValueError):
    """The read CLI has already saved and printed the original safe failure."""


def plan(calls, ids=()):
    return {"purpose": "SCHEMA_MAPPING_EVIDENCE", "symbols": list(SYMBOLS),
            "instrument_ids": list(ids), "calls": calls}


def contract_plan(context, target):
    """Choose one whole-dollar strike per symbol from observed bid/ask midpoint.

    This is a bounded candidate probe, not a complete chain scan or trade signal.
    Source clocks are retained; the runtime must fetch and accept fresh evidence.
    """
    result = CaptureResult.model_validate(context["result"])
    if context.get("status") != "COMPLETE" or result.status != "COMPLETE":
        raise ValueError("Completed context capture required")
    expected = [("equities", "get_equity_quotes"),
                ("spy-chains", "get_option_chains"), ("qqq-chains", "get_option_chains")]
    if [(c.label, c.tool) for c in result.plan.calls] != expected:
        raise ValueError("Exact context calls required")
    data = []
    for call, receipt in zip(result.plan.calls, result.observations, strict=True):
        if receipt.get("completed") is not True or receipt.get("label") != call.label or receipt.get("tool") != call.tool:
            raise ValueError("Completed context receipts required")
        data.append(response(result.schemas, call, receipt["raw"], call.tool)[1])
    quotes = quote_rows(data[0], list(SYMBOLS), "symbol")
    calls, anchors, chains = [], [], {}
    for symbol, quote, listing in zip(SYMBOLS, quotes, data[1:], strict=True):
        available = [c for c in (listing.get("chains") or []) if c
                     and c["symbol"] == symbol and c["can_open_position"]
                     and target.isoformat() in (c["expiration_dates"] or [])
                     and Decimal(c["trade_value_multiplier"]) == 100
                     and c["cash_component"] in (None, "0", "0.0000")]
        if len(available) != 1:
            raise ValueError("Exactly one eligible advertised chain per symbol required")
        bid, ask = Decimal(quote["bid_price"]), Decimal(quote["ask_price"])
        if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
            raise ValueError("Positive uncrossed underlying book required for strike probe")
        strike = ((bid + ask) / 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        calls.append({"label": symbol.lower() + "-contracts", "tool": "get_option_instruments",
                      "arguments": {"chain_symbol": symbol, "expiration_dates": target.isoformat(),
                                    "strike_price": format(strike, ".4f")}})
        anchors.append({"symbol": symbol, "bid": str(bid), "ask": str(ask),
                        "strike": str(strike), "received_at": result.collected_at.isoformat(),
                        "bid_source_at": quote["venue_bid_time"], "ask_source_at": quote["venue_ask_time"]})
        chains[symbol] = available[0]["id"]
    return plan(calls), anchors, chains


def checked_contract(row, symbol, target, chain, *, strike=None, right=None):
    if (not row or row['chain_id'] != chain or row['chain_symbol'] != symbol
            or row['expiration_date'] != target.isoformat()
            or row['state'] != 'active' or row['tradability'] != 'tradable'
            or row['type'] not in ('call', 'put')
            or (right is not None and row['type'] != right)
            or row['underlying_type'] != 'equity'
            or Decimal(row['trade_value_multiplier']) != 100):
        raise ValueError('STRIKE_LISTING_INVALID')
    value = Decimal(row['strike_price'])
    if not value.is_finite() or value <= 0 or (strike is not None and value != strike):
        raise ValueError('STRIKE_LISTING_INVALID')
    return value


def listed_strike(symbol, target, chain, midpoint, capture):
    """Choose from a complete bounded provider listing, never infer a strike grid."""
    cursor, cursors, identities, strikes, hashes = None, set(), set(), set(), []
    for page_number in range(1, MAX_STRIKE_PAGES + 1):
        arguments = {'chain_id': chain, 'expiration_dates': target.isoformat(),
                     'type': 'call', 'state': 'active', 'tradability': 'tradable'}
        if cursor is not None:
            arguments['cursor'] = cursor
        request = plan([{'label': symbol.lower() + '-listed-strikes',
                         'tool': 'get_option_instruments', 'arguments': arguments}])
        artifact = capture(f'{symbol.lower()}-strikes-{page_number}', request)
        result, pages = inspect_capture(artifact, 'get_option_instruments')
        if result.plan.model_dump(mode='json') != request or len(pages) != 1:
            raise ValueError('STRIKE_LISTING_INVALID')
        rows = pages[0].get('instruments') or []
        if len(rows) > MAX_STRIKES_PER_PAGE:
            raise ValueError('STRIKE_LISTING_INVALID')
        for row in rows:
            strike = checked_contract(row, symbol, target, chain, right='call')
            if row['id'] in identities:
                raise ValueError('STRIKE_LISTING_INVALID')
            identities.add(row['id'])
            strikes.add(strike)
        hashes.append(digest(artifact))
        cursor = pages[0].get('next')
        if not cursor:
            if not strikes:
                raise ValueError('STRIKE_LISTING_EMPTY')
            # Stable lower-strike tie break; later quote/admission rules are unchanged.
            return min(strikes, key=lambda s: (abs(s-midpoint), s)), hashes
        if cursor in cursors:
            raise ValueError('STRIKE_LISTING_CURSOR_REPEATED')
        cursors.add(cursor)
    raise ValueError('STRIKE_LISTING_PAGE_LIMIT')


def collect(target, capture, *, pause=time.sleep, retain_contracts=lambda value: None,
            progress=lambda stage: None):
    provider_calls = 0
    def read_capture(name, request):
        nonlocal provider_calls
        provider_calls += len(request['calls'])
        return capture(name, request)

    context = read_capture("context", plan([
        {"label": "equities", "tool": "get_equity_quotes", "arguments": {"symbols": list(SYMBOLS)}},
        *[{"label": s.lower() + "-chains", "tool": "get_option_chains",
           "arguments": {"underlying_symbol": s}} for s in SYMBOLS],
    ]))
    progress('CONTEXT_REVIEW')
    discovery, anchors, chains = contract_plan(context, target)
    contracts = read_capture("contracts-probe", discovery)
    probe_hash = digest(contracts)
    progress('CONTRACT_PROBE')
    result, pages = inspect_capture(contracts, "get_option_instruments")
    if result.plan.model_dump(mode='json') != discovery:
        raise ValueError('CONTRACT_PROBE_INVALID')
    empty = []
    for call, page in zip(result.plan.calls, pages, strict=True):
        rows = page.get('instruments') or []
        if page.get('next') or len(rows) > 2:
            raise ValueError('CONTRACT_PROBE_INVALID')
        symbol = call.arguments['chain_symbol']
        for row in rows:
            checked_contract(row, symbol, target, chains[symbol], strike=Decimal(call.arguments['strike_price']))
        if not rows:
            empty.append(symbol)
    listing_hashes = []
    if empty:
        progress('STRIKE_DISCOVERY')
        discovery = copy.deepcopy(discovery)
        for anchor, call in zip(anchors, discovery['calls'], strict=True):
            if anchor['symbol'] not in empty:
                continue
            symbol = anchor['symbol']
            midpoint = (Decimal(anchor['bid']) + Decimal(anchor['ask'])) / 2
            strike, hashes = listed_strike(symbol, target, chains[symbol], midpoint, read_capture)
            listing_hashes.extend(hashes)
            anchor.update(probe_strike=anchor['strike'], strike=str(strike), selection='LISTED_NEAREST')
            call['arguments']['strike_price'] = format(strike, '.4f')
        contracts = read_capture('contracts-selected', discovery)
        result, pages = inspect_capture(contracts, 'get_option_instruments')
        if result.plan.model_dump(mode='json') != discovery:
            raise ValueError('CONTRACT_PROBE_INVALID')
    progress('CONTRACT_REVIEW')
    ids = []
    for call, page in zip(result.plan.calls, pages, strict=True):
        rows = page.get("instruments") or []
        symbol = call.arguments["chain_symbol"]
        if page.get("next") or not 1 <= len(rows) <= 2:
            raise ValueError('SELECTED_CONTRACT_UNAVAILABLE')
        for row in rows:
            checked_contract(row, symbol, target, chains[symbol], strike=Decimal(call.arguments['strike_price']))
            ids.append(row["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate contract identities")
    retain_contracts(contracts)  # Exact original artifact, copied under the stable consumer filename.
    quotes = plan([{"label": "options", "tool": "get_option_quotes",
                    "arguments": {"instrument_ids": ids}}], ids)
    samples = []
    for sample in range(1, 4):
        samples.append(read_capture(f"quotes-{sample}", quotes))
        if sample < 3:
            pause(5)
    progress('QUOTE_REVIEW')
    reviewed = review(contracts, samples, retain_future_quotes=True)
    return {"status": "CATALOG_CAPTURED", "target_session": target.isoformat(),
            "anchors": anchors, "option_candidates": ids, "context_sha256": digest(context),
            "capture_hashes": reviewed["capture_hashes"],
            "probe_capture_sha256": probe_hash, "listing_capture_hashes": listing_hashes,
            "all_fresh_at_capture": all(c["all_fresh_at_capture"] for c in reviewed["contracts"]),
            "future_quote_samples": [{"instrument_id": c["provider_record"]["id"], **q}
                                     for c in reviewed["contracts"] for q in c["samples"]
                                     if q.get("clock_issue")],
            "provider_tool_calls": provider_calls, "workers_started": False, "live_enabled": False,
            "trading_ready": False, "entitlement": "UNKNOWN"}


def _main(argv, state):
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("target-session", "directory", "schemas", "oauth-file"):
        p.add_argument("--" + key, required=True)
    a = p.parse_args(argv)
    os.umask(0o077)
    target = date.fromisoformat(a.target_session)
    from zoneinfo import ZoneInfo
    from app.domain.models import utc_now
    from app.robinhood.schedule import XNYSCalendar

    now = utc_now()
    calendar = XNYSCalendar().calendar
    if (not 0 <= (target - now.astimezone(ZoneInfo("America/New_York")).date()).days <= 60
            or not calendar.is_session(target.isoformat())
            or now >= calendar.session_close(target.isoformat()).to_pydatetime()):
        raise ValueError("Current or future unclosed session within sixty days required")
    directory = Path(a.directory)
    private_directory(directory)
    if any(directory.iterdir()):
        raise ValueError("Empty private capture directory required; preserve existing evidence")
    state['directory'] = directory
    from app.options.read_cli import main as capture_main
    schemas = load_reviewed_schemas(a.schemas)

    def capture(name, request):
        request_path, output = directory / (name + "-plan.json"), directory / (name + ".json")
        save(request_path, request)
        code = capture_main(["capture", "--oauth-file", a.oauth_file, "--schemas", a.schemas,
                             "--schema-sha256", schemas.sha256, "--plan", str(request_path),
                             "--output", str(output)])
        if code:
            raise ProviderCaptureFailed()
        return json.loads(read(output, 8 * 1024 * 1024))

    report = collect(target, capture,
                     retain_contracts=lambda value: save(directory / 'contracts.json', value),
                     progress=lambda stage: state.update(stage=stage))
    state['stage'] = 'CAPTURE_ARTIFACT_WRITE'
    save(directory / "report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0


def main(argv=None):
    state = {'stage': 'SESSION_SETUP'}
    try:
        return _main(argv, state)
    except ProviderCaptureFailed:
        return 1  # Keep the original child failure; do not replace it with a generic wrapper.
    except Exception as exc:  # noqa: BLE001 -- no provider text, arguments or credentials
        report = {'status': 'FAILED', 'live_enabled': False,
                  'reason': str(exc) if type(exc) is ValueError and str(exc) in PUBLIC_REASONS else 'CATALOG_VALIDATION_FAILED',
                  'failure': {'stage': state['stage'], 'causes': [{'error_class': type(exc).__name__}]}}
        if 'directory' in state:
            try:
                save(state['directory'] / 'failure.json', report)
            except OSError:
                pass
        print(json.dumps(report, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
