"""Synthetic context plus retained contract/quote fixtures; no provider calls."""
import copy
from datetime import date

import pytest
from test_contract_catalog import captures as captures  # noqa: PLC0414
from test_read_schema_contract import (
    description_schemas as description_schemas,  # noqa: PLC0414
)
from test_read_schema_contract import (
    interval_description_schemas as interval_description_schemas,  # noqa: PLC0414
)
from test_robinhood_read_mapping import equity
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed.session_capture import collect, contract_plan, plan


@pytest.mark.parametrize('updated_description', [False, True])
def test_capture_cli_binds_each_call_to_actual_reviewed_discovery(
        tmp_path, monkeypatch, schemas, description_schemas, updated_description):
    import json
    from datetime import UTC, datetime

    from test_schema_artifact import artifact

    from app.mixed import session_capture
    from app.options import read_cli
    selected = description_schemas if updated_description else schemas
    source = tmp_path / 'discovery.json'
    source.write_text(json.dumps(artifact(selected)))
    source.chmod(0o600)
    output = tmp_path / 'capture'
    output.mkdir(mode=0o700)
    monkeypatch.setattr('app.domain.models.utc_now', lambda: datetime(2026, 11, 4, 22, tzinfo=UTC))
    calls = []
    def capture(args):
        calls.append(args)
        assert args[args.index('--schema-sha256') + 1] == selected.sha256
        assert args[args.index('--schemas') + 1] == str(source)
        Path(args[args.index('--output') + 1]).write_text('{"fixture":true}')
        return 0
    from pathlib import Path
    monkeypatch.setattr(read_cli, 'main', capture)
    def catalog(target, capture):
        assert target == date(2026, 11, 5)
        assert capture('context', {}) == {'fixture': True}
        return {'status': 'CATALOG_CAPTURED', 'fixture': True}
    monkeypatch.setattr(session_capture, 'collect', catalog)
    assert session_capture.main(['--target-session', '2026-11-05', '--directory', str(output),
        '--schemas', str(source), '--oauth-file', '/never-opened']) == 0
    assert len(calls) == 1


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


@pytest.mark.parametrize("future_quote", [False, True])
@pytest.mark.parametrize("new_revision", [False, True])
def test_capture_sequence_produces_reviewable_symbol_catalog(
        captures, future_quote, new_revision, interval_description_schemas):
    if new_revision:
        for artifact in captures:
            artifact["result"]["schemas"] = interval_description_schemas.model_dump(mode="json")
    if future_quote:
        from datetime import datetime, timedelta
        received = datetime.fromisoformat(captures[2]["result"]["collected_at"])
        captures[2]["result"]["observations"][0]["raw"]["structuredContent"]["data"]["results"][0]["quote"]["updated_at"] = (
            received + timedelta(microseconds=545227)
        ).isoformat()
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
    assert bool(result["future_quote_samples"]) is future_quote
    assert result["all_fresh_at_capture"] is not future_quote
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
