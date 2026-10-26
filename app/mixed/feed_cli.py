"""Explicit read-only continuous collector. It never opens an execution owner."""

import argparse
import asyncio
import json
import signal
from pathlib import Path

from app.domain.models import utc_now
from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy, held_from_observer
from app.mixed.observer import MixedObserver
from app.options.operator_inbox import read
from app.options.read_gateway import ReadSchemas
from app.robinhood.schedule import XNYSCalendar


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--schemas", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--create", action="store_true")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Explicitly start continuous provider reads; default validates only",
    )
    args = parser.parse_args(argv)
    if any(
        not Path(p).is_absolute() for p in (args.policy, args.schemas, args.journal, args.directory)
    ):
        parser.error("Absolute enrolled paths required")
    policy = FeedPolicy.model_validate_json(read(args.policy, 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(args.schemas, 256 * 1024))
    from app.mixed.connected_check import connection_report
    from app.options.runtime_cli import load

    settings = load(Path(args.journal).parent / "runtime.json")
    report = connection_report(
        settings, policy, schemas, journal=args.journal, directory=args.directory, now=utc_now()
    )
    print(json.dumps(report, sort_keys=True), flush=True)
    if not report["collector_can_start"]:
        return 2
    observer = MixedObserver(args.journal, policy.population_id)
    held_from_observer(observer)
    # Validation does not acquire a credential or open a network transport.
    feed = ContinuousFeed(args.directory, policy, schemas, create=args.create)
    try:
        if not args.run:
            return 0

        async def run():
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
            await feed.run(
                stop,
                clock_source=utc_now,
                held_source=lambda: held_from_observer(observer),
                calendar=XNYSCalendar(),
                source_settings=settings,
            )

        asyncio.run(run())
    finally:
        feed.close()


if __name__ == "__main__":
    raise SystemExit(main())
