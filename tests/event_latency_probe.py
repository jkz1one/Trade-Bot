"""Offline synthetic capacity probe. Never imports fixtures into operational evidence."""

import json
import platform
from datetime import timedelta
from statistics import median
from time import perf_counter_ns

from test_event_assessment import AT, P, event, request, snapshot

from app.events.assessment import assess, prepare


def run(iterations=250):
    results = []
    for count, workload in ((0, "spread"), (250, "spread"), (10000, "spread"), (10000, "dense")):
        events = tuple(
            event(
                event_id=f"fixture-{i}",
                starts_at=AT + timedelta(minutes=i if workload == "spread" else 0),
                ends_at=AT + timedelta(minutes=i if workload == "spread" else 0),
            )
            for i in range(count)
        )
        s, r = snapshot(events=events), request()
        started = perf_counter_ns()
        view = prepare(s, P)
        compile_ms = (perf_counter_ns() - started) / 1_000_000
        for _ in range(10):
            assess(view, r)
        durations = []
        for _ in range(iterations):
            started = perf_counter_ns()
            assess(view, r)
            durations.append((perf_counter_ns() - started) / 1_000_000)
        values = sorted(durations)
        results.append(
            {
                "events": count,
                "workload": workload,
                "iterations": iterations,
                "prepare_ms": compile_ms,
                "p50_ms": median(values),
                "p95_ms": values[int(0.95 * (iterations - 1))],
                "p99_ms": values[int(0.99 * (iterations - 1))],
                "max_ms": max(values),
            }
        )
    return {
        "kind": "OFFLINE_SYNTHETIC_LATENCY",
        "python": platform.python_version(),
        "provisional_target_ms": 5,
        "host_acceptance": False,
        "source_to_detection": "NOT_PROVIDER_MEASURED; separate native audit fields tested",
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
