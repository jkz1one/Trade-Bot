"""Installed create-only enrollment and continuous local options PAPER runner."""

import argparse
import asyncio
import json
import os
import signal
from contextlib import contextmanager
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


async def _unbound_scope_refresh(_play):
    raise ValueError("Scope runtime must bind its delivered input reader before use")


async def _unbound_stock_refresh(_instrument):
    raise ValueError("Mixed runtime must bind its delivered stock reader before use")


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
        swing_policy=settings.swing_policy,
        scope_policy=settings.scope_policy,
        stock_policy=settings.stock_policy,
        stock_refresh=_unbound_stock_refresh
        if settings.stock_policy and settings.stock_policy.paid_selection
        else None,
        scope_refresh=(
            _unbound_scope_refresh
            if settings.scope_policy is not None
            and settings.scope_policy.version == "shared-scope-entry-v1"
            else None
        ),
        clock=clock,
    )


def initialize(directory, settings, *, clock=utc_now):
    settings = RuntimeSettings.model_validate(settings.model_dump())
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Explicit absolute new population directory required")
    if settings.key_file:
        model_key(Path(settings.key_file))
    operator_key = None
    if settings.runtime.operator_key_file:
        from app.execution.control_api import _secret

        operator_hex = _secret(settings.runtime.operator_key_file)
        if settings.key_file and operator_hex == model_key(Path(settings.key_file)).lower():
            raise ValueError("Operator and model secrets must be separate")
        operator_key = bytes.fromhex(operator_hex)
    directory.mkdir(mode=0o700)
    _save(directory / "runtime.json", settings)
    portfolio = None
    if settings.execution.mixed_owner and settings.execution.mixed_owner.portfolio:
        from types import SimpleNamespace

        from app.mixed.portfolio_execution import policy as portfolio_policy

        portfolio = portfolio_policy(
            SimpleNamespace(policy=settings.execution, limits=settings.limits, _closed=False)
        )
    venue = DurableOptionVenue(
        directory / "venue.db",
        limits=settings.limits,
        capital=settings.execution.capital,
        portfolio_policy=portfolio,
        **(
            {"stock_limits": settings.execution.mixed_owner.stocks}
            if settings.execution.mixed_owner
            else {}
        ),
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
        if engine.portfolio_policy is None:
            engine.assess(None, None, now=at)
        coordinator = _coordinator(engine, settings, True, clock)
        if operator_key is not None:
            from app.options.operator import OptionsControl

            (directory / "operator-inbox").mkdir(mode=0o700)
            (directory / "operator-receipts").mkdir(mode=0o700)
            OptionsControl.enroll(engine, operator_key, now=at)
        OptionRuntime(coordinator, settings.runtime, create=True)
    return {
        "status": "ENROLLED",
        "mode": "MIXED_PAPER_FIXTURE" if settings.stock_policy else "OPTIONS_PAPER_FIXTURE",
        "live_enabled": False,
        "network_calls": False,
    }


@contextmanager
def existing_runtime(directory, *, clock=utc_now):
    """Reopen the native owner and retain its lease through all runtime cleanup."""
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
        yield runtime, settings


async def run(directory, stop, *, clock=utc_now):
    with existing_runtime(directory, clock=clock) as (runtime, settings):
        await runtime.run(stop)
    return {
        "status": "STOPPED",
        "mode": "MIXED_PAPER_FIXTURE" if settings.stock_policy else "OPTIONS_PAPER_FIXTURE",
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
    commands.add_parser("release")
    enroll = commands.add_parser("init")
    enroll.add_argument("--directory", required=True)
    enroll.add_argument("--settings", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--directory", required=True)
    runner.add_argument("--seconds", type=int)
    args = parser.parse_args(argv)
    try:
        if args.operation == "release":
            from app.options.release_identity import inspect_release

            result = inspect_release().model_dump(mode="json")
        elif args.operation == "init":
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
    return 2 if args.operation == "release" and result["status"] != "VERIFIED_FILES" else 0


if __name__ == "__main__":
    raise SystemExit(main())
