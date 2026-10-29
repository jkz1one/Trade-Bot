"""Synthetic context plus retained contract/quote fixtures; no provider calls."""
import copy
from datetime import date

import pytest
from test_contract_catalog import captures as captures
from test_robinhood_read_mapping import equity

from app.mixed.session_capture import collect, contract_plan, plan


def context(captures):
    artifact = copy.deepcopy(captures[0])
    calls = [{"label": "equities", "tool": "get_equity_quotes", "arguments": {"symbols": ["SPY", "QQQ"]}}]
    quotes, listings = [], []
    for symbol, price, observation in zip(("SPY", "QQQ"), ("760", "705"),
                                         captures[0]["result"]["observations"], strict=True):
        q = equity(symbol)
        q.update(bid_price=price, ask_price=str(int(price) + .02))
        quotes.append({"quote": q})
        row = observation["raw"]["structuredContent"]["data"]["instruments"][0]
        listings.append({"chains": [{
            "id": row["chain_id"], "symbol": symbol, "can_open_position": True,
            "cash_component": None, "expiration_dates": ["2026-10-28"],
            "trade_value_multiplier": "100", "underlying_instruments": [],
            "min_ticks": row["min_ticks"], "late_close_state": "enabled",
            "extended_hours_state": "disabled", "settle_on_open": False,
            "sellout_time_to_expiration": 900,
        }]})
        calls.append({"label": symbol.lower() + "-chains", "tool": "get_option_chains",
                      "arguments": {"underlying_symbol": symbol}})
    artifact["result"]["plan"] = plan(calls)
    artifact["result"]["observations"] = [
        {"completed": True, "label": c["label"], "tool": c["tool"],
         "raw": {"isError": False, "structuredContent": {"data": data, "guide": ""}}}
        for c, data in zip(calls, [{"results": quotes}, *listings], strict=True)
    ]
    return artifact


def test_capture_sequence_produces_reviewable_symbol_catalog(captures):
    seen, pauses = [], []
    source = context(captures)

    def reader(name, request):
        seen.append((name, request))
        if name == "context":
            assert request == source["result"]["plan"]
            return source
        artifact = copy.deepcopy(captures[0] if name == "contracts" else captures[int(name[-1])])
        artifact["result"]["plan"] = request
        return artifact

    result = collect(date(2026, 10, 28), reader, pause=pauses.append)
    assert result["status"] == "CATALOG_CAPTURED"
    assert result["provider_tool_calls"] == sum(len(p["calls"]) for _, p in seen) == 8
    assert len(result["option_candidates"]) == 4 and pauses == [5, 5]
    assert not result["trading_ready"] and not result["workers_started"]
    assert [a["strike"] for a in result["anchors"]] == ["760", "705"]
    for c in seen[1][1]["calls"]:
        assert set(c["arguments"]) == {"chain_symbol", "expiration_dates", "strike_price"}


@pytest.mark.parametrize("problem", ["missing_expiry", "duplicate_chain", "crossed", "missing_quote", "partial"])
def test_context_refuses_ambiguous_or_missing_inputs(captures, problem):
    value = context(captures)
    observations = value["result"]["observations"]
    chain = observations[1]["raw"]["structuredContent"]["data"]["chains"][0]
    quotes = observations[0]["raw"]["structuredContent"]["data"]["results"]
    if problem == "missing_expiry":
        chain["expiration_dates"] = []
    elif problem == "duplicate_chain":
        observations[1]["raw"]["structuredContent"]["data"]["chains"].append(copy.deepcopy(chain))
    elif problem == "crossed":
        quotes[0]["quote"]["bid_price"] = "900"
    elif problem == "missing_quote":
        quotes.pop()
    else:
        observations[1]["completed"] = False
    with pytest.raises(ValueError):
        contract_plan(value, date(2026, 10, 28))


@pytest.mark.parametrize("problem", ["empty", "pagination", "wrong_chain", "untradable", "wrong_expiry"])
def test_bad_contract_probe_stops_before_quotes(captures, problem):
    seen = []

    def reader(name, request):
        seen.append(name)
        if name == "context":
            return context(captures)
        value = copy.deepcopy(captures[0])
        value["result"]["plan"] = request
        page = value["result"]["observations"][0]["raw"]["structuredContent"]["data"]
        if problem == "empty":
            page["instruments"] = []
        elif problem == "pagination":
            page["next"] = "more"
        else:
            key, bad = {"wrong_chain": ("chain_id", "different"),
                        "untradable": ("tradability", "untradable"),
                        "wrong_expiry": ("expiration_date", "2026-10-29")}[problem]
            page["instruments"][0][key] = bad
        return value

    with pytest.raises(ValueError):
        collect(date(2026, 10, 28), reader, pause=lambda _: pytest.fail("Unexpected pause"))
    assert seen == ["context", "contracts"]
