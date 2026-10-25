"""Synthetic responses checked against the operator-supplied real wire schemas."""

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError as SchemaError
from test_option_admission import inputs

from app.mixed.stock_models import StockInstrument
from app.options import read_mapping as mapping
from app.options.read_gateway import CapturePlan, OptionReadGateway, ReadSample, ReadSchemas

AT = datetime(2026, 10, 23, 13, 30, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def schemas():
    path = ROOT / "tests/fixtures/robinhood_read_schemas.json"
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest()
        == "d370d0a27b371e581b881fabc7a4d3e2fffc31e08e11dbf6deb6474b433dce1f"
    )
    return ReadSchemas.model_validate_json(path.read_bytes())


def call(tool, **arguments):
    return ReadSample(label="test", tool=tool, arguments=arguments)


def envelope(rows):
    return {"isError": False, "structuredContent": {"data": {"results": rows}, "guide": ""}}


def equity(symbol="SPY"):
    return {
        "symbol": symbol,
        "last_trade_price": "600",
        "venue_last_trade_time": AT.isoformat(),
        "last_non_reg_trade_price": None,
        "venue_last_non_reg_trade_time": None,
        "adjusted_previous_close": "598",
        "previous_close": "598",
        "previous_close_date": "2026-10-22",
        "bid_price": "600",
        "ask_price": "600.01",
        "venue_bid_time": AT.isoformat(),
        "venue_ask_time": (AT + timedelta(seconds=1)).isoformat(),
        "has_traded": True,
        "state": "active",
    }


def option():
    return {
        "instrument_id": "contract-one",
        "bid_price": "1",
        "ask_price": "1.01",
        "bid_size": 4,
        "ask_size": 3,
        "break_even_price": "601.01",
        "adjusted_mark_price": "1.005",
        "mark_price": "1.005",
        "high_fill_rate_buy_price": "1.01",
        "low_fill_rate_buy_price": "1",
        "high_fill_rate_sell_price": "1.01",
        "low_fill_rate_sell_price": "1",
        "previous_close_price": "1",
        "previous_close_date": "2026-10-22",
        "implied_volatility": ".3",
        "delta": ".5",
        "gamma": ".1",
        "rho": ".1",
        "theta": "-.04",
        "vega": ".1",
        "open_interest": 1000,
        "volume": 200,
        "chance_of_profit_long": None,
        "chance_of_profit_short": None,
        "updated_at": AT.isoformat(),
    }


def instrument():
    value = inputs("CALL")["quote"].instrument.model_dump()
    value.update(provider="robinhood", instrument_id="contract-one")
    return mapping.OptionInstrument.model_validate(value)


def history():
    c = call(
        "get_equity_historicals",
        symbols=["SPY"],
        start_time=AT.isoformat(),
        end_time=(AT + timedelta(minutes=30)).isoformat(),
        interval="5minute",
        bounds="regular",
        adjustment_type="split",
    )
    bars = [
        {
            "begins_at": (AT + timedelta(minutes=5 * i)).isoformat(),
            "open_price": "600",
            "high_price": "602",
            "low_price": "599",
            "close_price": "601",
            "volume": 100 + i,
            "interpolated": False,
            "session": "reg",
        }
        for i in range(6)
    ]
    return c, envelope(
        [{"symbol": "SPY", "interval": "5minute", "bounds": "regular", "bars": bars}]
    )


def test_exact_reviewed_pin_and_initial_four_call_plan(schemas):
    assert mapping.reviewed_schemas(schemas).sha256 == mapping.SCHEMA_SHA256
    assert (
        not schemas.missing_tools
        and not schemas.missing_input_schemas
        and not schemas.missing_output_schemas
    )
    plan = CapturePlan.model_validate_json(
        (ROOT / "examples/robinhood-initial-read-plan.json").read_bytes()
    )
    gateway = OptionReadGateway(None)
    gateway.schemas = schemas
    assert gateway.validate_plan(plan, schemas) == plan
    assert len(plan.calls) == 4 and not plan.instrument_ids
    assert [c.tool for c in plan.calls] == [
        "get_equity_quotes",
        "get_equity_historicals",
        "get_option_chains",
        "get_option_chains",
    ]
    assert plan.calls[0].arguments["symbols"] == ["SPY", "QQQ"]


def test_equity_mapping_keeps_source_clock_order_and_missing_sizes(schemas):
    raw = envelope([{"quote": equity("QQQ")}, {"quote": equity()}])
    before = copy.deepcopy(raw)
    values = mapping.equity_quotes(
        schemas,
        call("get_equity_quotes", symbols=["SPY", "QQQ"]),
        raw,
        received_at=AT + timedelta(seconds=2),
    )
    assert [q.symbol for q in values] == ["SPY", "QQQ"]
    assert all(
        q.source_at == AT
        and q.entitlement == "UNKNOWN"
        and q.bid_size is None
        and q.ask_size is None
        for q in values
    )
    assert values[0].bid == Decimal(600) and values[0].ask == Decimal("600.01")
    assert raw == before
    # Valid stale source evidence remains old, never restamped as current.
    stale = mapping.equity_quotes(
        schemas,
        call("get_equity_quotes", symbols=["SPY", "QQQ"]),
        raw,
        received_at=AT + timedelta(days=1),
    )
    assert stale[0].source_at == AT


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "extra",
        "null",
        "zero",
        "crossed",
        "future",
        "naive",
        "nan",
        "tool_error",
        "float",
    ],
)
def test_invalid_equity_response_is_unavailable(schemas, damage):
    row = equity()
    raw = envelope([{"quote": row}])
    rows = raw["structuredContent"]["data"]["results"]
    if damage == "missing":
        rows.clear()
    elif damage == "duplicate":
        rows.append({"quote": row})
    elif damage == "extra":
        rows.append({"quote": equity("QQQ")})
    elif damage == "null":
        rows[0]["quote"] = None
    elif damage == "zero":
        row["ask_price"] = "0"
    elif damage == "crossed":
        row["bid_price"] = "601"
    elif damage == "future":
        row["venue_ask_time"] = (AT + timedelta(seconds=10)).isoformat()
    elif damage == "naive":
        row["venue_bid_time"] = "2026-10-23T13:30:00"
    elif damage == "nan":
        row["bid_price"] = "NaN"
    elif damage == "tool_error":
        raw["isError"] = True
    elif damage == "float":
        row["bid_price"] = 600.0
    with pytest.raises((ValueError, SchemaError)):
        mapping.equity_quotes(
            schemas,
            call("get_equity_quotes", symbols=["SPY"]),
            raw,
            received_at=AT + timedelta(seconds=2),
        )


@pytest.mark.parametrize("field,value", [("has_traded", False), ("state", "inactive")])
def test_nontrading_equity_is_not_complete(schemas, field, value):
    row = equity()
    row[field] = value
    assert not mapping.equity_quotes(
        schemas,
        call("get_equity_quotes", symbols=["SPY"]),
        envelope([{"quote": row}]),
        received_at=AT + timedelta(seconds=2),
    )[0].complete


def test_stock_metadata_cannot_be_created_from_equity_quote(schemas):
    c = call("get_equity_quotes", symbols=["SPY"])
    raw = envelope([{"quote": equity()}])
    with pytest.raises(ValueError, match="coverage"):
        mapping.stock_quotes(schemas, c, raw, received_at=AT + timedelta(seconds=2), instruments=())
    i = StockInstrument(
        provider="robinhood",
        instrument_id="reviewed-stock-id",
        symbol="SPY",
        kind="ETF",
        tick=".01",
        metadata_complete=False,
        tradable=False,
    )
    (q,) = mapping.stock_quotes(
        schemas, c, raw, received_at=AT + timedelta(seconds=2), instruments=(i,)
    )
    assert (
        q.instrument == i
        and q.bid_size is None
        and q.ask_size is None
        and q.entitlement == "UNKNOWN"
    )


def test_option_quote_greeks_liquidity_and_original_catalog(schemas):
    c = call("get_option_quotes", instrument_ids=["contract-one"])
    raw = envelope([{"quote": option()}])
    i = instrument()
    (q,) = mapping.option_quotes(
        schemas, c, raw, received_at=AT + timedelta(seconds=2), instruments=(i,)
    )
    assert q.instrument == i and q.source_at == AT and q.ask_size == 3 and q.bid_size == 4
    assert q.entitlement == "UNKNOWN" and q.greeks.provenance == "OBSERVED"
    assert q.greeks.theta == Decimal("-.04") and q.greeks.implied_volatility == Decimal(".3")
    (meta,) = mapping.option_metadata(
        schemas, c, raw, received_at=AT + timedelta(seconds=2), instruments=(i,)
    )
    assert meta.volume == 200 and meta.open_interest == 1000 and meta.delta == Decimal(".5")
    with pytest.raises(ValueError, match="coverage"):
        mapping.option_quotes(
            schemas, c, raw, received_at=AT + timedelta(seconds=2), instruments=()
        )


def test_absent_option_book_and_greeks_do_not_become_mark_or_zero_estimate(schemas):
    row = option()
    row.update(bid_price="0", ask_price="0", delta=None, theta=None, implied_volatility=None)
    (q,) = mapping.option_quotes(
        schemas,
        call("get_option_quotes", instrument_ids=["contract-one"]),
        envelope([{"quote": row}]),
        received_at=AT,
        instruments=(instrument(),),
    )
    assert q.bid is None and q.ask is None and not q.complete
    assert (
        q.greeks.delta is None and q.greeks.theta is None and q.greeks.provenance == "UNAVAILABLE"
    )


@pytest.mark.parametrize(
    "damage",
    [
        "identity",
        "future",
        "negative_size",
        "fractional_size",
        "crossed",
        "negative",
        "nan_delta",
        "wrong_provider",
    ],
)
def test_invalid_option_evidence_rejected(schemas, damage):
    row = option()
    i = instrument()
    if damage == "identity":
        row["instrument_id"] = "other"
    elif damage == "future":
        row["updated_at"] = (AT + timedelta(seconds=1)).isoformat()
    elif damage == "negative_size":
        row["ask_size"] = -1
    elif damage == "fractional_size":
        row["ask_size"] = 1.5
    elif damage == "crossed":
        row["bid_price"] = "2"
    elif damage == "negative":
        row["bid_price"] = "-1"
    elif damage == "nan_delta":
        row["delta"] = "NaN"
    elif damage == "wrong_provider":
        i = i.model_copy(update={"provider": "fixture"})
    with pytest.raises((ValueError, SchemaError)):
        mapping.option_quotes(
            schemas,
            call("get_option_quotes", instrument_ids=["contract-one"]),
            envelope([{"quote": row}]),
            received_at=AT,
            instruments=(i,),
        )


def test_completed_history_preserves_ohlcv_clocks_and_omits_forming_bar(schemas):
    c, raw = history()
    before = copy.deepcopy(raw)
    (h,) = mapping.equity_history(schemas, c, raw, received_at=AT + timedelta(minutes=27))
    assert len(h.bars) == 5 and h.source_at == AT + timedelta(minutes=25)
    assert h.received_at == AT + timedelta(minutes=27) and h.bars[-1].volume == 104
    assert h.complete and h.entitlement == "UNKNOWN" and raw == before


@pytest.mark.parametrize("damage", ["gap", "interpolated", "leading_gap"])
def test_history_gaps_remain_incomplete(schemas, damage):
    c, raw = history()
    bars = raw["structuredContent"]["data"]["results"][0]["bars"]
    if damage == "interpolated":
        bars[2]["interpolated"] = True
    else:
        bars.pop(0 if damage == "leading_gap" else 2)
    (h,) = mapping.equity_history(schemas, c, raw, received_at=AT + timedelta(minutes=30))
    assert not h.complete
    if damage == "interpolated":
        assert h.bars[2].interpolated


@pytest.mark.parametrize(
    "damage",
    [
        "unordered",
        "duplicate",
        "null",
        "session",
        "missing_interpolation",
        "bad_ohlc",
        "future",
        "wrong_interval",
        "missing_symbol",
        "wrong_adjustment",
        "long_range",
    ],
)
def test_invalid_history_never_becomes_complete(schemas, damage):
    c, raw = history()
    data = raw["structuredContent"]["data"]
    row = data["results"][0]
    bars = row["bars"]
    if damage == "unordered":
        bars.reverse()
    elif damage == "duplicate":
        bars[1] = bars[0]
    elif damage == "null":
        bars[0] = None
    elif damage == "session":
        bars[0]["session"] = "pre"
    elif damage == "missing_interpolation":
        del bars[0]["interpolated"]
    elif damage == "bad_ohlc":
        bars[0]["high_price"] = "590"
    elif damage == "future":
        bars[-1]["begins_at"] = (AT + timedelta(hours=1)).isoformat()
    elif damage == "wrong_interval":
        row["interval"] = "minute"
    elif damage == "missing_symbol":
        data["results"] = []
    elif damage == "wrong_adjustment":
        c = c.model_copy(update={"arguments": c.arguments | {"adjustment_type": "none"}})
    elif damage == "long_range":
        c = c.model_copy(
            update={"arguments": c.arguments | {"end_time": (AT + timedelta(days=2)).isoformat()}}
        )
    with pytest.raises((ValueError, SchemaError)):
        mapping.equity_history(schemas, c, raw, received_at=AT + timedelta(minutes=30))


def test_schema_drift_is_not_accepted_even_with_rehashed_metadata(schemas):
    from app.options.read_gateway import schema_digest

    value = schemas.model_dump()
    value["tools"]["get_equity_quotes"]["description"] += " drift"
    value["sha256"] = schema_digest(value["tools"])
    drift = ReadSchemas.model_validate(value)
    with pytest.raises(ValueError, match="Unreviewed"):
        mapping.equity_quotes(
            drift,
            call("get_equity_quotes", symbols=["SPY"]),
            envelope([{"quote": equity()}]),
            received_at=AT + timedelta(seconds=2),
        )
