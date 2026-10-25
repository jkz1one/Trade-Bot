"""Offline mappings for the reviewed Robinhood wire contract, without feed authority.

Raw receipts remain the evidence source. These functions perform no reads and
do not infer entitlement, executable share sizes or missing contract metadata.
"""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

from app.mixed.stock_models import StockInstrument, StockQuote
from app.options.degen import DegenBar, DegenHistory
from app.options.models import (
    OptionGreekObservation,
    OptionInstrument,
    OptionQuote,
    UnderlyingQuote,
)
from app.options.read_gateway import (
    MAX_SAMPLE_BYTES,
    OptionReadGateway,
    ReadSample,
    ReadSchemas,
    _validator,
    encoded,
)

SCHEMA_SHA256 = "d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15"
SOURCE = "robinhood-mcp"


def instant(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Explicit timezone-aware observation clock required")
    return value.astimezone(UTC)


def reviewed_schemas(schemas):
    schemas = ReadSchemas.model_validate(schemas.model_dump(warnings=False))
    if schemas.sha256 != SCHEMA_SHA256:
        raise ValueError("Unreviewed Robinhood wire contract")
    return schemas


def response(schemas, call, raw, tool):
    schemas = reviewed_schemas(schemas)
    call = ReadSample.model_validate(call.model_dump(warnings=False))
    if call.tool != tool:
        raise ValueError("Wrong read tool for mapping")
    gateway = OptionReadGateway(None)
    gateway.schemas = schemas
    gateway._validate_call(call)
    if (
        not isinstance(raw, dict)
        or len(encoded(raw)) > MAX_SAMPLE_BYTES
        or not isinstance(raw.get("isError", False), bool)
        or raw.get("isError", False)
        or not isinstance(raw.get("structuredContent"), dict)
    ):
        raise ValueError("Successful bounded structured read required")
    _validator(schemas.tools[tool]["outputSchema"]).validate(raw["structuredContent"])
    return call, raw["structuredContent"]["data"]


def exact_rows(rows, expected, key):
    if not isinstance(expected, list) or not 1 <= len(expected) <= 8:
        raise ValueError("Bounded exact subjects required")
    if len(set(expected)) != len(expected) or not isinstance(rows, list):
        raise ValueError("Unique exact subjects and non-null rows required")
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Null observation")  # noqa: TRY004 -- unavailable wire evidence
        identity = key(row)
        if identity not in expected or identity in found:
            raise ValueError("Unexpected or duplicate subject")
        found[identity] = row
    if set(found) != set(expected):
        raise ValueError("Incomplete subject coverage")
    return [found[identity] for identity in expected]


def quote_rows(data, expected, key):
    rows = data["results"]
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("quote"), dict) for row in rows
    ):
        raise ValueError("Every requested quote must be available")
    # Official closes/marks never substitute for executable bid/ask observations.
    return exact_rows([row["quote"] for row in rows], expected, lambda row: row[key])


def equity_quotes(schemas, call, raw, *, received_at):
    call, data = response(schemas, call, raw, "get_equity_quotes")
    received = instant(received_at)
    result = []
    for row in quote_rows(data, call.arguments["symbols"], "symbol"):
        bid_at, ask_at = instant(row["venue_bid_time"]), instant(row["venue_ask_time"])
        if max(bid_at, ask_at) > received:
            raise ValueError("Source quote cannot follow receipt")
        quote = UnderlyingQuote(
            symbol=row["symbol"],
            source=SOURCE,
            source_at=min(bid_at, ask_at),
            received_at=received,
            entitlement="UNKNOWN",
            complete=row["has_traded"] and row["state"] == "active",
            bid=row["bid_price"],
            ask=row["ask_price"],
        )
        if quote.bid > quote.ask:
            raise ValueError("Crossed equity quote")
        result.append(quote)
    return tuple(result)


def stock_quotes(schemas, call, raw, *, received_at, instruments):
    quotes = equity_quotes(schemas, call, raw, received_at=received_at)
    catalog = exact_rows(
        [
            StockInstrument.model_validate(i.model_dump(warnings=False)).model_dump()
            for i in instruments
        ],
        [q.symbol for q in quotes],
        lambda item: item["symbol"],
    )
    result = []
    for quote, item in zip(quotes, catalog):
        instrument = StockInstrument.model_validate(item)
        if instrument.provider != "robinhood":
            raise ValueError("Reviewed Robinhood stock identity required")
        result.append(
            StockQuote(
                **quote.model_dump(exclude={"symbol", "bid_size", "ask_size"}),
                instrument=instrument,
                bid_size=None,
                ask_size=None,
            )
        )
    return tuple(result)


def option_quotes(schemas, call, raw, *, received_at, instruments):
    call, data = response(schemas, call, raw, "get_option_quotes")
    received = instant(received_at)
    expected = call.arguments["instrument_ids"]
    rows = quote_rows(data, expected, "instrument_id")
    catalog = exact_rows(
        [
            OptionInstrument.model_validate(i.model_dump(warnings=False)).model_dump()
            for i in instruments
        ],
        expected,
        lambda item: item["instrument_id"],
    )
    result = []
    for row, item in zip(rows, catalog):
        instrument = OptionInstrument.model_validate(item)
        if instrument.provider != "robinhood":
            raise ValueError("Reviewed Robinhood option identity required")
        source_at = instant(row["updated_at"])
        if source_at > received:
            raise ValueError("Source quote cannot follow receipt")
        evidence = {
            "source": SOURCE,
            "source_at": source_at,
            "received_at": received,
            "entitlement": "UNKNOWN",
            "instrument": instrument,
        }
        values = {name: row[name] for name in ("delta", "theta", "implied_volatility")}
        greeks = OptionGreekObservation(
            **evidence,
            **values,
            complete=all(v is not None for v in values.values()),
            provenance="OBSERVED" if any(v is not None for v in values.values()) else "UNAVAILABLE",
            theta_unit="USD_PER_SHARE_PER_DAY",
            volatility_unit="DECIMAL_FRACTION",
        )
        # Parse first so malformed/negative/NaN numbers cannot be treated as absence.
        from app.options.models import _decimal

        bid, ask = _decimal(row["bid_price"]), _decimal(row["ask_price"])
        if bid < 0 or ask < 0 or (ask and bid > ask):
            raise ValueError("Invalid option book")
        result.append(
            OptionQuote(
                **evidence,
                complete=bool(bid and ask),
                bid=bid or None,
                ask=ask or None,
                bid_size=row["bid_size"],
                ask_size=row["ask_size"],
                greeks=greeks,
            )
        )
    return tuple(result)


def option_metadata(schemas, call, raw, *, received_at, instruments):
    from app.options.selection import ContractMetadata

    quotes = option_quotes(schemas, call, raw, received_at=received_at, instruments=instruments)
    _, data = response(schemas, call, raw, "get_option_quotes")
    rows = quote_rows(data, call.arguments["instrument_ids"], "instrument_id")
    return tuple(
        ContractMetadata(
            instrument=q.instrument,
            source=q.source,
            source_at=q.source_at,
            received_at=q.received_at,
            entitlement=q.entitlement,
            complete=q.complete,
            delta=q.greeks.delta,
            greek_provenance="OBSERVED" if q.greeks.delta is not None else "UNAVAILABLE",
            volume=row["volume"],
            open_interest=row["open_interest"],
        )
        for q, row in zip(quotes, rows)
    )


def equity_history(schemas, call, raw, *, received_at):
    call, data = response(schemas, call, raw, "get_equity_historicals")
    args = call.arguments
    if (
        (args.get("interval"), args.get("bounds"), args.get("adjustment_type"))
        != ("5minute", "regular", "split")
        or "end_time" not in args
        or data.get("not_found")
    ):
        raise ValueError("Explicit split-adjusted regular five-minute history required")
    start, end, received = (
        instant(args["start_time"]),
        instant(args["end_time"]),
        instant(received_at),
    )
    if not timedelta(0) < end - start <= timedelta(hours=8):
        raise ValueError("Bounded intraday history window required")
    if any(at.timestamp() % 300 for at in (start, end)):
        raise ValueError("Five-minute aligned history bounds required")
    result = []
    for row in exact_rows(data["results"], args["symbols"], lambda row: row["symbol"]):
        if (
            row["interval"] != "5minute"
            or row["bounds"] != "regular"
            or not isinstance(row["bars"], list)
        ):
            raise ValueError("History interval, bounds or bars unavailable")
        if not 1 <= len(row["bars"]) <= 96:
            raise ValueError("Bounded nonempty history required")
        bars, previous = [], None
        for value in row["bars"]:
            if (
                not isinstance(value, dict)
                or value.get("session") != "reg"
                or "interpolated" not in value
            ):
                raise ValueError("Explicit original session/interpolation evidence required")
            bar = DegenBar(
                begins_at=instant(value["begins_at"]),
                open=value["open_price"],
                high=value["high_price"],
                low=value["low_price"],
                close=value["close_price"],
                volume=value["volume"],
                interpolated=value["interpolated"],
            )
            if (
                not start <= bar.begins_at < end
                or bar.begins_at > received
                or bar.begins_at.timestamp() % 300
            ):
                raise ValueError("Bar outside original aligned request/receipt clocks")
            if previous is not None and bar.begins_at <= previous:
                raise ValueError("Duplicate or unordered bars")
            previous = bar.begins_at
            if bar.ends_at <= min(end, received):
                bars.append(bar)
        if not bars:
            raise ValueError("No completed observed bars")
        through = min(end, received)
        through -= timedelta(seconds=through.timestamp() % 300)
        complete = (
            bars[0].begins_at == start
            and bars[-1].ends_at == through
            and all(not b.interpolated for b in bars)
            and all(a.ends_at == b.begins_at for a, b in pairwise(bars))
        )
        result.append(
            DegenHistory(
                symbol=row["symbol"],
                source=SOURCE,
                source_at=bars[-1].ends_at,
                received_at=received,
                entitlement="UNKNOWN",
                complete=complete,
                bars=tuple(bars),
            )
        )
    return tuple(result)
