"""Shared UTC clock and canonical identity for native PAPER evidence."""
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal


def clock(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Options execution clock must be timezone-aware")
    return now.astimezone(UTC)


def fingerprint(value):
    def normalize(item):
        # Native Scope receipts contain large nested JSON records. Preserve their
        # exact canonical bytes without repeated model/date introspection on every
        # primitive. Subclasses retain the original normalization path below.
        kind = type(item)
        if item is None or kind in (str, int, float, bool):
            return item
        if kind is dict:
            return {k: normalize(v) for k, v in item.items()}
        if kind in (list, tuple):
            return [normalize(v) for v in item]
        if hasattr(item, "model_dump"):
            return normalize(item.model_dump(warnings=False))
        if isinstance(item, Decimal):
            text = format(item, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text
        if isinstance(item, datetime):
            return clock(item).isoformat()
        if hasattr(item, "isoformat"):
            return item.isoformat()
        if isinstance(item, dict):
            return {k: normalize(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(v) for v in item]
        return item

    return hashlib.sha256(
        json.dumps(normalize(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
