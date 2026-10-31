"""Schema-pinned additional market evidence; never a runtime feed or order capability."""

import hashlib
import time
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.models import utc_now
from app.options.read_gateway import MAX_SAMPLE_BYTES, _validator, encoded

# Reviewed from the operator's October 29 metadata capture, not inferred tool names.
PINS = {
    "get_equity_price_book": "dd684f320f2cb770b9df02d9930ad0af80d0510e94ded703bd8e04b52a02a760",
    "get_earnings_calendar": "847030468e36a4e253757079040089e987603322e0113eeaf643cf6010b42e27",
    "get_indexes": "4d78ecf97aa1d7da25f4ac88accecb03172b7c6a0409024557404fbfe18be522",
    "get_index_quotes": "60847e57a5c786b13a561ffacbf4831e4e35bb0ff026a52c86fe9d11bc248da7",
    "get_index_historicals": "592e766f6cd419ee95c33009ab2b8f281958ba0c6bc777e52e76f2423fe382fd",
}

# Diagnostic-only book payload observed at 484,845 bytes during market hours.
# Keep the original response intact; ordinary/runtime reads retain their 128 KiB
# cap. Reserve space inside the existing 768 KiB capture / 1 MiB process envelope.
MAX_BOOK_PROBE_BYTES = 512 * 1024
MAX_PROBE_OBSERVATIONS_BYTES = 704 * 1024


class InputProbeIncomplete(RuntimeError):
    pass


class InputProbeResponseError(ValueError):
    """Fixed public category only; provider contents stay in private evidence."""


def check_response(raw, metadata, row, observations):
    """Retain bounded rejected payloads and distinguish rejection from transport failure."""
    row["response_issue"] = "NON_JSON_RESPONSE"
    size = len(encoded(raw))
    row["response_bytes"] = size
    limit = MAX_BOOK_PROBE_BYTES if row.get("tool") == "get_equity_price_book" else MAX_SAMPLE_BYTES
    if size > limit:
        row["response_issue"] = "RESPONSE_TOO_LARGE"
        raise InputProbeResponseError
    if len(encoded(observations)) + size > MAX_PROBE_OBSERVATIONS_BYTES:
        row["response_issue"] = "AGGREGATE_RESPONSE_TOO_LARGE"
        raise InputProbeResponseError
    # Only private evidence retains rejected content; never print it in the report.
    row["rejected_raw"] = raw
    row["response_issue"] = "MALFORMED_MCP_RESPONSE"
    if not isinstance(raw, dict) or type(raw.get("isError", False)) is not bool:
        raise InputProbeResponseError
    if raw.get("isError", False):
        row["response_issue"] = "PROVIDER_TOOL_ERROR"
        raise InputProbeResponseError
    if not isinstance(raw.get("structuredContent"), dict):
        row["response_issue"] = "STRUCTURED_OUTPUT_MISSING"
        raise InputProbeResponseError
    row["response_issue"] = "OUTPUT_SCHEMA_MISMATCH"
    _validator(metadata["outputSchema"]).validate(raw["structuredContent"])
    del row["rejected_raw"]
    del row["response_issue"]


def initial_calls(at, *, calendar_days=1):
    if type(calendar_days) is not int or calendar_days not in (1, 7):
        raise ValueError("Only current one-day or historical seven-day probe windows are reviewed")
    return [
        ("get_equity_price_book", {"symbols": ["SPY", "QQQ"]}),
        ("get_earnings_calendar", {
            "start_date": at.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
            "days": calendar_days,
        }),
        ("get_indexes", {"symbols": "SPX"}),
    ]


def index_id(data):
    # Restrictions are final for this probe: no alternate symbols, proxies or retries.
    if data.get("restricted"):
        return None
    rows = data.get("indexes") or []
    if len(rows) != 1 or not rows[0] or rows[0].get("symbol") != "SPX":
        return None
    row = rows[0]
    if row.get("trade_halted") is not False:
        return None
    identity = row.get("id")
    try:
        return identity if str(UUID(identity)) == identity else None
    except (ValueError, TypeError, AttributeError):
        return None


def followup_calls(identity, at):
    return [
        ("get_index_quotes", {"instrument_ids": [identity]}),
        ("get_index_historicals", {
            "instrument_ids": [identity], "interval": "5minute",
            "start_time": (at - timedelta(days=1)).isoformat(), "end_time": at.isoformat(),
        }),
    ]


def schemas(inventory):
    result = {}
    for name, pin in PINS.items():
        matches = [t for t in inventory["tools"] if t["name"] == name]
        if len(matches) != 1:
            raise ValueError("Reviewed input capability missing or duplicated")
        metadata = matches[0].get("metadata")
        if (not isinstance(metadata, dict)
                or hashlib.sha256(encoded(metadata)).hexdigest() != pin
                or metadata.get("annotations", {}).get("readOnlyHint") is not True):
            raise ValueError("Reviewed input capability changed or omitted")
        _validator(metadata["inputSchema"])
        _validator(metadata["outputSchema"])
        result[name] = metadata
    return result


def data_of(row):
    return row["raw"]["structuredContent"]["data"] if row.get("completed") else {}


def validate_observations(rows, at, *, complete=False, expected_calendar_days=None):
    """Parent rechecks the exact bounded call sequence and arguments."""
    if len(rows) > 5:
        raise ValueError("Input probe exceeds fixed call bound")
    # Offline reports can replay the original seven-day probe. New workers/parents
    # explicitly require one day; arbitrary windows and filters remain rejected.
    days = expected_calendar_days
    if days is None:
        days = rows[1].get("arguments", {}).get("days") if len(rows) >= 2 else 1
    expected = initial_calls(at, calendar_days=days)
    if len(rows) >= 3:
        identity = index_id(data_of(rows[2]))
        if identity is None and len(rows) > 3:
            raise ValueError("Index follow-up requires an unambiguous unrestricted SPX ID")
        if identity is not None:
            expected += followup_calls(identity, at)
        if len(rows) >= 4 and data_of(rows[3]).get("restricted"):
            expected = expected[:4]
    if len(rows) > len(expected) or (complete and len(rows) != len(expected)):
        raise ValueError("Input probe call coverage mismatch")
    for row, (name, arguments) in zip(rows, expected, strict=False):
        if (row.get("tool") != name or row.get("arguments") != arguments
                or row.get("metadata_sha256") != PINS[name]
                or type(row.get("completed")) is not bool
                or (complete and not row["completed"])):
            raise ValueError("Input probe call binding mismatch")


async def run(client, inventory, at, observations):
    reviewed = schemas(inventory)  # All five pins checked before any market call.
    calls = initial_calls(at)
    for name, arguments in calls:
        _validator(reviewed[name]["inputSchema"]).validate(arguments)

    async def capture(name, arguments):
        from app.options.read_capture import failure_evidence

        if name not in PINS or len(observations) >= 5:
            raise ValueError("Outside fixed input probe")
        _validator(reviewed[name]["inputSchema"]).validate(arguments)
        row = {"tool": name, "arguments": arguments, "completed": False,
               "attempted_at": utc_now().isoformat(), "metadata_sha256": PINS[name],
               "response_issue": "CLIENT_CALL_FAILED"}
        observations.append(row)
        tick = time.monotonic()
        try:
            raw = await client.call_tool(name, arguments)
            check_response(raw, reviewed[name], row, observations)
            row.update(raw=raw, completed=True, output_schema_validated=True)
        except Exception as exc:  # bounded diagnostics, no arbitrary provider exception text
            row["failure"] = failure_evidence(exc, "MARKET_READ").model_dump(mode="json")
        finally:
            row["received_at"] = utc_now().isoformat()
            row["elapsed_seconds"] = time.monotonic() - tick
        return data_of(row)

    for name, arguments in calls:
        await capture(name, arguments)
    identity = index_id(data_of(observations[2]))
    if identity:
        quotes, history = followup_calls(identity, at)
        quote_data = await capture(*quotes)
        if not quote_data.get("restricted"):
            await capture(*history)
    validate_observations(observations, at, expected_calendar_days=1)
    return summary(observations)


def summary(rows):
    from app.options.earnings_mapping import map_calendar, mapping_summary

    by_name = {r["tool"]: r for r in rows}
    books = data_of(by_name.get("get_equity_price_book", {}))
    earnings = data_of(by_name.get("get_earnings_calendar", {}))
    indexes = data_of(by_name.get("get_indexes", {}))
    quotes = data_of(by_name.get("get_index_quotes", {}))
    history = data_of(by_name.get("get_index_historicals", {}))
    try:
        mapped = mapping_summary(map_calendar(by_name.get("get_earnings_calendar", {})))
    except (ValueError, KeyError, TypeError):
        mapped = {"status": "MAPPING_UNAVAILABLE", "trading_ready": False,
                  "complete_catalyst_coverage": False}
    # Raw market responses remain in the private artifact. No promotion to native inputs.
    return {
        "version": "remaining-input-probe-v1", "trading_ready": False,
        "execution_authority": False, "live_enabled": False,
        "runtime_policy_changed": False, "entitlement": "UNKNOWN",
        "status": "CAPTURED_FOR_MAPPING" if all(r["completed"] for r in rows) else "PARTIAL_CAPTURE",
        "attempted_reads": len(rows), "completed_reads": sum(r["completed"] for r in rows),
        "stock_books": [{"symbol": b["symbol"], "snapshot_at": b["updated_at"],
                         "bid_levels": len(b.get("bids") or []),
                         "ask_levels": len(b.get("asks") or []),
                         "best_bid": (b.get("bids") or [None])[0],
                         "best_ask": (b.get("asks") or [None])[0]}
                        for b in books.get("books") or [] if b],
        "stock_book_errors": [e["symbol"] for e in books.get("errors") or []],
        "earnings_status": ("CAPTURED" if by_name.get("get_earnings_calendar", {}).get("completed")
                            and earnings.get("results") is not None else "UNAVAILABLE"),
        "earnings_events": (len(earnings["results"]) if earnings.get("results") is not None else None),
        "earnings_window": {k: by_name.get("get_earnings_calendar", {}).get("arguments", {}).get(k)
                            for k in ("start_date", "days")},
        "earnings_is_complete_catalyst_coverage": False,
        "earnings_mapping": mapped,
        "spx_identity_resolved": index_id(indexes) is not None,
        "index_quotes": [{k: q[k] for k in ("instrument_id", "symbol", "value", "venue_timestamp")}
                         for q in quotes.get("quotes") or [] if q],
        "index_histories": [{"instrument_id": h["instrument_id"], "symbol": h["symbol"],
                             "bars": len(h.get("bars") or []),
                             "interpolated_bars": sum(b.get("interpolated") is True for b in h.get("bars") or [] if b),
                             "noninterpolated_bars": sum(b.get("interpolated") is False for b in h.get("bars") or [] if b),
                             "interpolation_unknown_bars": sum(b.get("interpolated") is None for b in h.get("bars") or [] if b)}
                            for h in history.get("results") or [] if h],
        "restricted": [{"tool": name, "symbol": r["symbol"],
                        "message": r.get("message", "Index history restricted")}
                       for name, data in (("get_indexes", indexes), ("get_index_quotes", quotes),
                                          ("get_index_historicals", history))
                       for r in data.get("restricted") or [] if r],
        "account_tradability_probed": False,
        "read_failures": [{"tool": r["tool"],
                           "response_issue": r.get("response_issue", "UNCLASSIFIED_FAILURE"),
                           "response_bytes": r.get("response_bytes"),
                           "failure": r.get("failure")}
                          for r in rows if not r["completed"]],
        "remaining": ["Validate original payload identity, clocks and coverage",
                      "Map supported evidence into explicit reviewed runtime policy",
                      "Complete Swing catalyst and Scope context coverage"],
    }
