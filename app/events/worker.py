"""Background-only collection. Do not attach this to the trading supervisor task group."""

from datetime import UTC, datetime
from time import perf_counter_ns


def collect_once(store, adapter, *, clock=lambda: datetime.now(UTC)):
    """One bounded provider attempt; every failure is retained and old events survive.

    Run in an independent process. A blocked provider or filesystem can then only
    delay event publication. This function has no engine/model/venue reference.
    Independent source processes may retry a busy publication lock on a later tick.
    """
    started = clock()
    tick = perf_counter_ns()
    raw = None
    try:
        raw = adapter.fetch()
        received = clock()
        payload = adapter.parse(raw, received)
        status, error = "COLLECTED", None
    except Exception as exc:  # noqa: BLE001 - isolate and audit arbitrary provider failures
        received = clock()
        status, error = "UNAVAILABLE", type(exc).__name__
        payload = {
            "coverage": [
                adapter.spec.coverage(
                    received, "UNAVAILABLE", ("COLLECTION_FAILED", error)
                ).model_dump(mode="json")
            ]
        }
    # Never retain credential-bearing provider errors or exception messages.
    secret = getattr(adapter, "api_key", None)
    if raw and secret:
        raw = raw.replace(secret, "[REDACTED]")
    record = {
        "kind": "COLLECTION",
        "source": adapter.spec.source,
        "source_version": adapter.spec.source_version,
        "started_at": started.isoformat(),
        "received_at": received.isoformat(),
        "status": status,
        "error_class": error,
        "collection_ms": (perf_counter_ns() - tick) / 1_000_000,
        "raw": raw,
        **payload,
    }
    store.retain(record)
    snapshot = store.publish(now=clock())
    return {"status": status, "sequence": snapshot.sequence, "source": adapter.spec.source}
