"""Offline synthetic local-only timings, excluding preparation and audit IO."""

import json
from datetime import timedelta
from statistics import median
from time import perf_counter_ns

from test_event_assessment import P
from test_event_option_volatility import NOW, earnings, quote, req, snap

from app.events.assessment import assess, prepare
from app.events.option_volatility import prepare_option_volatility, review_option_volatility


def run(iterations=250):
    results = []
    for count, workload in ((0, "empty"), (250, "dense"), (10000, "dense"), (10000, "expired")):
        at = NOW - timedelta(days=2) if workload == "expired" else NOW
        events = tuple(
            earnings(event_id=f"synthetic-{i}", starts_at=at, ends_at=at) for i in range(count)
        )
        snapshot, request, option = snap(events=events), req(), quote()
        start = perf_counter_ns()
        risk = prepare(snapshot, P)
        view = prepare_option_volatility(risk)
        preparation = (perf_counter_ns() - start) / 1_000_000
        for combined in (False, True):
            values = []
            for i in range(iterations + 10):
                start = perf_counter_ns()
                if combined:
                    assess(risk, request)
                review_option_volatility(view, request, option)
                duration = (perf_counter_ns() - start) / 1_000_000
                if i >= 10:
                    values.append(duration)
            values.sort()
            results.append(
                {
                    "events": count,
                    "workload": workload,
                    "includes_base_assessment": combined,
                    "iterations": iterations,
                    "background_prepare_ms": preparation,
                    "p50_ms": median(values),
                    "p95_ms": values[int(0.95 * (iterations - 1))],
                    "p99_ms": values[int(0.99 * (iterations - 1))],
                    "max_ms": max(values),
                }
            )
    return {
        "kind": "OFFLINE_SYNTHETIC_LOCAL_LATENCY",
        "target_ms": 5,
        "target_is_provisional": True,
        "host_acceptance": False,
        "source_to_detection_delay": "NOT_MEASURED_NO_PROVIDER",
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
