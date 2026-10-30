"""Bounded read-only catalog capture; never enroll, start workers or submit orders."""
import argparse
import json
import os
import time
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from app.mixed.contract_catalog import capture as inspect_capture, digest, review
from app.options.operator_inbox import private_directory, read, save
from app.options.read_capture import CaptureResult
from app.options.read_mapping import SCHEMA_SHA256, quote_rows, response

SYMBOLS = ("SPY", "QQQ")


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


def collect(target, capture, *, pause=time.sleep):
    context = capture("context", plan([
        {"label": "equities", "tool": "get_equity_quotes", "arguments": {"symbols": list(SYMBOLS)}},
        *[{"label": s.lower() + "-chains", "tool": "get_option_chains",
           "arguments": {"underlying_symbol": s}} for s in SYMBOLS],
    ]))
    discovery, anchors, chains = contract_plan(context, target)
    contracts = capture("contracts", discovery)
    result, pages = inspect_capture(contracts, "get_option_instruments")
    ids = []
    for call, page in zip(result.plan.calls, pages, strict=True):
        rows = page.get("instruments") or []
        symbol = call.arguments["chain_symbol"]
        if page.get("next") or not 1 <= len(rows) <= 2:
            raise ValueError("Exact-strike probe returned empty, oversized or paginated contracts; inspect saved captures")
        for row in rows:
            if (not row or row["chain_id"] != chains[symbol] or row["chain_symbol"] != symbol
                    or row["expiration_date"] != target.isoformat()
                    or Decimal(row["strike_price"]) != Decimal(call.arguments["strike_price"])
                    or row["state"] != "active" or row["tradability"] != "tradable"
                    or row["type"] not in ("call", "put")
                    or row["underlying_type"] != "equity"
                    or Decimal(row["trade_value_multiplier"]) != 100):
                raise ValueError("Contract differs from advertised chain")
            ids.append(row["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate contract identities")
    quotes = plan([{"label": "options", "tool": "get_option_quotes",
                    "arguments": {"instrument_ids": ids}}], ids)
    samples = []
    for sample in range(1, 4):
        samples.append(capture(f"quotes-{sample}", quotes))
        if sample < 3:
            pause(5)
    reviewed = review(contracts, samples, retain_future_quotes=True)
    return {"status": "CATALOG_CAPTURED", "target_session": target.isoformat(),
            "anchors": anchors, "option_candidates": ids, "context_sha256": digest(context),
            "capture_hashes": reviewed["capture_hashes"],
            "all_fresh_at_capture": all(c["all_fresh_at_capture"] for c in reviewed["contracts"]),
            "future_quote_samples": [{"instrument_id": c["provider_record"]["id"], **q}
                                     for c in reviewed["contracts"] for q in c["samples"]
                                     if q.get("clock_issue")],
            "provider_tool_calls": 8, "workers_started": False, "live_enabled": False,
            "trading_ready": False, "entitlement": "UNKNOWN"}


def main(argv=None):
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
    from app.options.read_cli import main as capture_main

    def capture(name, request):
        request_path, output = directory / (name + "-plan.json"), directory / (name + ".json")
        save(request_path, request)
        code = capture_main(["capture", "--oauth-file", a.oauth_file, "--schemas", a.schemas,
                             "--schema-sha256", SCHEMA_SHA256, "--plan", str(request_path),
                             "--output", str(output)])
        if code:
            raise ValueError("Provider capture failed; preserve original diagnostic")
        return json.loads(read(output, 8 * 1024 * 1024))

    report = collect(target, capture)
    save(directory / "report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
