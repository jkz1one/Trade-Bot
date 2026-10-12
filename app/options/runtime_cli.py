"""Installed create-only enrollment and continuous local options PAPER runner."""

import argparse
import asyncio
import json
import os
import signal
from pathlib import Path

from app.domain.models import utc_now
from app.execution.runtime import model_key
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution
from app.options.runtime import OptionRuntime, read_private
from app.options.runtime_models import RuntimeSettings
from app.options.venue import DurableOptionVenue


def load(path):
    if not Path(path).is_absolute():
        raise ValueError("Explicit absolute settings path required")
    return RuntimeSettings.model_validate_json(read_private(path))


def _save(path, settings):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(settings.model_dump_json())
        stream.flush()
        os.fsync(stream.fileno())


def _coordinator(engine, settings, create, clock):
    return DegenCoordinator(
        engine,
        settings.setup,
        settings.selection,
        create=create,
        judgment_limits=settings.judgment_limits,
        key_file=settings.key_file,
        entry_policy=settings.entry_policy,
        position_policy=settings.position_policy,
        clock=clock,
    )


def initialize(directory, settings, *, clock=utc_now):
    settings = RuntimeSettings.model_validate(settings.model_dump())
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Explicit absolute new population directory required")
    if settings.key_file:
        model_key(Path(settings.key_file))
    directory.mkdir(mode=0o700)
    _save(directory / "runtime.json", settings)
    venue = DurableOptionVenue(
        directory / "venue.db",
        limits=settings.limits,
        capital=settings.execution.capital,
    )
    at = clock()
    with OptionExecution.open(
        directory / "options.db",
        settings.limits,
        settings.execution,
        venue,
        now=at,
        create=True,
    ) as engine:
        if not engine.reconcile(venue.snapshot(at), now=at)["reconciled"]:
            raise ValueError("Initial fixture reconciliation failed")
        engine.assess(None, None, now=at)
        coordinator = _coordinator(engine, settings, True, clock)
        OptionRuntime(coordinator, settings.runtime, create=True)
    return {
        "status": "ENROLLED",
        "mode": "OPTIONS_PAPER_FIXTURE",
        "live_enabled": False,
        "network_calls": False,
    }


async def run(directory, stop, *, clock=utc_now):
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Explicit absolute existing population directory required")
    settings = load(directory / "runtime.json")
    venue = DurableOptionVenue(directory / "venue.db")
    with OptionExecution.open(
        directory / "options.db",
        settings.limits,
        settings.execution,
        venue,
        now=clock(),
    ) as engine:
        coordinator = _coordinator(engine, settings, False, clock)
        runtime = OptionRuntime(coordinator, settings.runtime)
        await runtime.run(stop)
    return {
        "status": "STOPPED",
        "mode": "OPTIONS_PAPER_FIXTURE",
        "live_enabled": False,
        "model_enabled": settings.key_file is not None,
    }


async def _serve(directory, seconds):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    timer = loop.call_later(seconds, stop.set) if seconds is not None else None
    try:
        return await run(directory, stop)
    finally:
        if timer:
            timer.cancel()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    enroll = commands.add_parser("init")
    enroll.add_argument("--directory", required=True)
    enroll.add_argument("--settings", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--directory", required=True)
    runner.add_argument("--seconds", type=int)
    args = parser.parse_args(argv)
    try:
        if args.operation == "init":
            result = initialize(Path(args.directory), load(args.settings))
        else:
            if args.seconds is not None and not 1 <= args.seconds <= 86400:
                raise ValueError("Bounded fixture run duration required")
            result = asyncio.run(_serve(Path(args.directory), args.seconds))
    except (OSError, ValueError, RuntimeError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "OPTIONS_RUNTIME_UNAVAILABLE",
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
