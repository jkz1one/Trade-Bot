"""Strict response lineage/indicator inputs for the isolated PAPER collector only."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.robinhood.gateway import RobinhoodMarketReadGateway
from app.robinhood.read import tool_data

MAX_HISTORY_BARS = 2048


def _timestamp(value):
    if not isinstance(value, str):
        raise TypeError("Historical timestamp required")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Historical timestamp must include a timezone")
    return stamp


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise TypeError("Invalid historical price")
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid historical price") from None
    if not price.is_finite() or price <= 0:
        raise ValueError("Historical prices must be finite and positive")
    return price


def _history(item, arguments):
    if item.get("interval") != arguments["interval"] or item.get("bounds") != arguments["bounds"]:
        raise ValueError("Historical response policy mismatch")
    bars = item.get("bars")
    if not isinstance(bars, list) or not 1 <= len(bars) <= MAX_HISTORY_BARS:
        raise ValueError("Bounded nonempty historical bars required")
    start, end = _timestamp(arguments["start_time"]), _timestamp(arguments["end_time"])
    previous = None
    for bar in bars:
        if not isinstance(bar, dict):
            raise TypeError("Historical bar object required")
        stamp = _timestamp(bar.get("begins_at"))
        if not start <= stamp <= end or (previous is not None and stamp <= previous):
            raise ValueError("Historical bars must be ordered within the requested window")
        previous = stamp
        opening, close, high, low = (
            _price(bar.get(key)) for key in ("open_price", "close_price", "high_price", "low_price")
        )
        if not low <= min(opening, close) <= max(opening, close) <= high:
            raise ValueError("Historical OHLC range is inconsistent")
        volume = bar.get("volume")
        if not (
            (type(volume) is int and volume >= 0)
            or (isinstance(volume, str) and volume.isascii() and volume.isdigit())
        ):
            raise ValueError("Historical volume must be a nonnegative integer")
        if type(bar.get("interpolated")) is not bool:
            raise ValueError("Historical interpolation flag required")


class PaperMarketReadGateway(RobinhoodMarketReadGateway):
    """Existing four-tool firewall plus exact per-request response validation."""

    async def call_safe(self, name, arguments):
        result = await super().call_safe(name, arguments)
        if result.get("isError", result.get("is_error", False)) is not False:
            raise ValueError("Market tool returned an error")
        data = tool_data(result)
        if name == "get_accounts":
            return result  # Existing account selection requires one active eligible account.
        rows = data.get("results")
        symbols = arguments["symbols"]
        if not isinstance(rows, list) or len(rows) != len(symbols):
            raise ValueError("Exact requested market response rows required")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("Market response row object required")
            identity = row.get("quote") if name == "get_equity_quotes" else row
            if not isinstance(identity, dict):
                raise TypeError("Market response identity required")
            symbol = identity.get("symbol")
            if not isinstance(symbol, str) or symbol not in symbols or symbol in seen:
                raise ValueError("Market response has foreign or duplicate symbols")
            seen.add(symbol)
            if name == "get_equity_historicals":
                _history(row, arguments)
        return result
