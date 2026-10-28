"""Explicit observed-quote simulation; original entitlement remains UNKNOWN."""
from pydantic import BaseModel

from app.options.models import Evidence

BASIS = "ROBINHOOD_OBSERVED_V1"
MARKET_TYPES = {
    "OptionQuote", "UnderlyingQuote", "OptionGreekObservation", "ContractMetadata",
    "OptionInventory", "DegenHistory", "StockQuote",
}


def annotate(value):
    """Copy supported market observations only; never synthesize terms or sizes."""
    if isinstance(value, tuple):
        return tuple(annotate(item) for item in value)
    if not isinstance(value, BaseModel):
        return value
    fields = {name: annotate(getattr(value, name)) for name in type(value).model_fields}
    if isinstance(value, Evidence) and type(value).__name__ in MARKET_TYPES:
        if value.source == "robinhood-mcp" and value.entitlement == "UNKNOWN":
            fields["simulation_basis"] = BASIS
    return type(value).model_validate(fields)
