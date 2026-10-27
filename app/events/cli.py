"""Explicit event evidence operations; never starts a trading worker or enables enforcement."""

import argparse
import json
from datetime import UTC, date, datetime, time
from pathlib import Path

from app.events.adapters import (
    BEA_URL,
    BLS_URL,
    CboeDailyAdapter,
    FinnhubEarningsAdapter,
    ICalendarAdapter,
    SourceSpec,
    TradingEconomicsAdapter,
    sessions,
)
from app.events.assessment import assess, prepare
from app.events.consumer import ObserverBatch, consume_once
from app.events.models import Policy, Request, Snapshot
from app.events.store import EventStore
from app.events.worker import collect_once
from app.options.operator_inbox import read


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("policy", "init", "collect-once", "sessions", "assess", "export", "observe-once"),
    )
    parser.add_argument("--directory")
    parser.add_argument("--population")
    parser.add_argument("--policy")
    parser.add_argument("--source", choices=("bls", "bea", "te", "finnhub", "vix"))
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--symbol")
    parser.add_argument("--key-file")
    parser.add_argument("--request")
    parser.add_argument("--snapshot-binding")
    parser.add_argument("--observer-batch")
    args = parser.parse_args(argv)
    if args.operation == "policy":
        print(Policy().model_dump_json(indent=2))
        return 0
    if not all((args.directory, args.population, args.policy)):
        parser.error("Explicit evidence directory, existing population and policy file required")
    try:
        policy = Policy.model_validate_json(Path(args.policy).read_bytes())
        store = EventStore(args.directory, args.population, policy, create=args.operation == "init")
        now = datetime.now(UTC)
        if args.operation == "init":
            result = {"status": "EVENT_AUDIT_CREATED", "workers_started": False}
        elif args.operation == "export":
            result = store.export()
        elif args.operation == "observe-once":
            if not args.snapshot_binding:
                raise ValueError("Exact native publisher binding file required")
            binding = json.loads(read(Path(args.snapshot_binding)))
            batch = (
                ObserverBatch.model_validate_json(read(Path(args.observer_batch), 4 * 1024 * 1024))
                if args.observer_batch
                else ObserverBatch()
            )
            result = consume_once(store, binding, recorded_at=now, batch=batch)
        elif args.operation in {"collect-once", "sessions"}:
            if args.start is None or args.end is None or args.start >= args.end:
                raise ValueError("Explicit ordered collection interval required")
            if args.operation == "sessions":
                store.retain(
                    {"kind": "LOCAL_CALENDAR", **sessions(args.start, args.end, received_at=now)}
                )
                result = {"sequence": store.publish(now=now).sequence}
            else:
                if args.source is None:
                    raise ValueError("Explicit source required")
                dataset = {
                    "bls": "macro.bls",
                    "bea": "macro.bea",
                    "te": "macro.us.high_impact",
                    "finnhub": "company.earnings",
                    "vix": "volatility.daily",
                }[args.source]
                spec = SourceSpec(
                    args.source,
                    args.source + "-adapter-v1",
                    dataset,
                    datetime.combine(args.start, time(), UTC),
                    datetime.combine(args.end, time(), UTC),
                    (args.symbol,) if args.source == "finnhub" and args.symbol else (),
                )
                key = read(Path(args.key_file), 4096).decode().strip() if args.key_file else None
                adapter = (
                    ICalendarAdapter(spec, BLS_URL if args.source == "bls" else BEA_URL)
                    if args.source in {"bls", "bea"}
                    else TradingEconomicsAdapter(spec, key)
                    if args.source == "te"
                    else FinnhubEarningsAdapter(spec, key)
                    if args.source == "finnhub"
                    else CboeDailyAdapter(spec)
                )
                result = collect_once(store, adapter)
        else:
            request = Request.model_validate_json(Path(args.request).read_bytes())
            snapshot = Snapshot.model_validate_json(
                read(store.directory / "risk.json", 16 * 1024 * 1024)
            )
            result = assess(prepare(snapshot, policy), request).model_dump(mode="json")
        print(json.dumps(result, sort_keys=True))
        return 2 if result.get("status") == "UNAVAILABLE" else 0
    except (ValueError, OSError, TypeError):
        print(json.dumps({"status": "EVENT_OPERATION_UNAVAILABLE", "authority": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
