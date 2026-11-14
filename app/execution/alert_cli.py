"""Independent alert service for an explicitly enrolled isolated PAPER journal."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal

from app.execution.alert_worker import private_token
from app.execution.alerts import (
    AlertAlreadyRunning,
    AlertDelivery,
    alert_delivery_lease,
)
from app.execution.engine import ExecutionEngine


async def _serve_owned(delivery, stop):
    # A cancelled embedding caller cannot release the lease before child reaping.
    work = asyncio.create_task(delivery._run_owned(stop))
    try:
        await asyncio.shield(work)
    except asyncio.CancelledError:
        stop.set()
        work.cancel()
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                continue
        if not work.cancelled():
            work.result()
        raise


async def serve(journal):
    with alert_delivery_lease(journal) as path:
        delivery = AlertDelivery.attach_existing(ExecutionEngine.attach_existing(path))
        private_token(delivery.token_file)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            for signum in previous:
                loop.add_signal_handler(signum, stop.set)
            # Native shutdown drains the bounded current attempt, then starts no more.
            await _serve_owned(delivery, stop)
        finally:
            for signum, handler in previous.items():
                loop.remove_signal_handler(signum)
                signal.signal(signum, handler)
    return {"status": "STOPPED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "once", "report"):
        child = commands.add_parser(command)
        child.add_argument("--journal", required=True)
        if command == "report":
            child.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = asyncio.run(serve(args.journal))
        elif args.command == "once":
            # Own the lease before any attachment; match the library's BUSY result.
            try:
                with alert_delivery_lease(args.journal) as path:
                    delivery = AlertDelivery.attach_existing(ExecutionEngine.attach_existing(path))
                    private_token(delivery.token_file)
                    result = asyncio.run(delivery._deliver_owned())
            except AlertAlreadyRunning:
                result = {"status": "BUSY"}
        else:
            delivery = AlertDelivery.attach_existing(ExecutionEngine.attach_existing(args.journal))
            result = {**delivery.report(limit=args.limit), "network_calls": False}
        print(json.dumps({**result, "mode": "FIXTURE_PAPER", "live_enabled": False}, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 -- no credential, path or endpoint details
        print(
            json.dumps(
                {"status": "ERROR", "error_class": type(exc).__name__, "live_enabled": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
