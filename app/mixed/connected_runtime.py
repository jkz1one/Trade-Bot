"""Explicit existing-owner simulation runner. Check is read-only; run starts reads.

No enrollment, automatic resume, balance reset, migration or dashboard replacement.
The native execution gates remain authoritative even when wiring checks pass.
"""

import argparse
import asyncio
import json
import signal
import sqlite3
from pathlib import Path

from app.domain.models import utc_now
from app.mixed.connected_check import connection_report
from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy, held_from_observer
from app.mixed.observer import MixedObserver
from app.options.engine import fingerprint
from app.options.operator_inbox import private_directory, read
from app.options.read_gateway import ReadSchemas
from app.options.runtime_cli import existing_runtime, load, strategy_identity
from app.options.venue import private_path
from app.robinhood.schedule import XNYSCalendar


class ComponentFailure(RuntimeError):
    """A component stopped unexpectedly or exceeded graceful shutdown time."""


def inspect_owner(directory, settings, *, clock_source=utc_now):
    """Reject replay populations before opening writable state or credentials."""
    private_directory(directory)
    private_path(directory / "venue.db")
    observer = MixedObserver(
        directory / "options.db", settings.limits.population_id, clock=clock_source
    )
    with observer.read() as db:
        row = db.execute("SELECT * FROM execution_option_runtime WHERE id=1").fetchone()
        control = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
        if row is None or control is None:
            raise ValueError("Existing native runtime enrollment required")
        if (
            (row["reason"] or "").startswith("FROZEN_")
            or (control["halt_reason"] or "").startswith("FROZEN_")
            or db.execute(
                "SELECT 1 FROM execution_events WHERE kind='PORTFOLIO_REPLAY_STARTED' LIMIT 1"
            ).fetchone()
        ):
            raise ValueError("Frozen offline replay cannot become a connected owner")
        frozen = json.loads(row["config_json"])
        if frozen["runtime"] != settings.runtime.model_dump(mode="json"):
            raise ValueError("Runtime settings differ from the enrolled owner")
        config = json.loads(control["config_json"])
        if config["limits"] != settings.limits.model_dump(mode="json") or config[
            "policy"
        ] != settings.execution.model_dump(mode="json"):
            raise ValueError("Execution settings differ from the enrolled owner")
        strategy = db.execute(
            "SELECT policy_json FROM execution_option_strategy WHERE id=1"
        ).fetchone()
        expected_strategy = json.loads(strategy_identity(settings))
        if (
            strategy is None
            or json.loads(strategy[0]) != expected_strategy
            or frozen["strategy"] != expected_strategy
            or frozen["engine"] != config
        ):
            raise ValueError("Strategy or runtime owner settings differ from enrollment")
        result = {
            "owner_configuration_sha256": fingerprint(frozen),
            "owner_revision": db.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM execution_events"
            ).fetchone()[0],
            "runtime_status": row["status"],
            "runtime_generation": row["generation"],
            "feed_sequence": row["feed_sequence"],
            "entry_halted": bool(control["halted"]),
            "halt_reason": control["halt_reason"],
        }
    # A crash may leave a durable venue fill awaiting journal reconciliation.
    # The owner's first tick runs before the collector requests held coverage.
    return observer, result


def check(directory, feed_directory, policy_file, schemas_file, *, clock_source=utc_now):
    paths = tuple(Path(p) for p in (directory, feed_directory, policy_file, schemas_file))
    if any(not p.is_absolute() for p in paths):
        raise ValueError("Absolute existing-owner and feed paths required")
    directory, feed_directory, policy_file, schemas_file = paths
    settings = load(directory / "runtime.json")
    policy = FeedPolicy.model_validate_json(read(policy_file, 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(schemas_file, 256 * 1024))
    result = connection_report(
        settings,
        policy,
        schemas,
        journal=directory / "options.db",
        directory=feed_directory,
        now=clock_source(),
    )
    if not result["collector_can_start"]:
        raise ValueError("Collector and runtime wiring differ")
    observer, state = inspect_owner(directory, settings, clock_source=clock_source)
    private_directory(feed_directory)
    private_path(feed_directory / "collector.db")
    # Reuse the bounded read-only database reader, without opening the collector
    # lease or performing interrupted-attempt recovery during a check.
    from app.options.observer import OptionObserver

    with OptionObserver(feed_directory / "collector.db", policy.population_id).read() as db:
        from zoneinfo import ZoneInfo

        from app.mixed.feed_rollover import load_rollovers, policy_for, verify_owner

        try:
            rows = load_rollovers(db, policy, schemas)
            verify_owner(rows, state["owner_configuration_sha256"])
        except ValueError:
            raise ValueError("Collector settings differ or rollover evidence is invalid") from None
        target = clock_source().astimezone(ZoneInfo("America/New_York")).date()
        effective = policy_for(policy, rows, target)
        result = connection_report(
            settings,
            effective,
            schemas,
            journal=directory / "options.db",
            directory=feed_directory,
            now=clock_source(),
        )
        result["rollover_sessions"] = [r.target_session.isoformat() for r in rows]
        result["effective_policy_sha256"] = fingerprint(effective)
    result.update(
        version="connected-runtime-check-v1",
        owner_state=state,
        state_modified=False,
        workers_started=False,
        dashboard_journal=str(directory / "options.db"),
        dashboard_population_id=settings.limits.population_id,
    )
    return result, settings, policy, schemas, observer


async def supervise(runtime_run, collector_run, stop, *, shutdown_seconds=30.0):
    """Drain both components before releasing either native ownership lease."""
    if type(stop) is not asyncio.Event or not 0 < shutdown_seconds <= 60:
        raise ValueError("Explicit shutdown event and bounded grace required")
    if stop.is_set():
        return
    unexpected = []

    async def component(name, operation):
        try:
            await operation(stop)
            if not stop.is_set():
                unexpected.append(name)
        finally:
            # Fence native entry immediately, before another scheduled task can
            # act on a component's unexpected return or failure.
            stop.set()

    tasks = {
        "RUNTIME": asyncio.create_task(component("RUNTIME", runtime_run), name="connected-runtime"),
        "COLLECTOR": asyncio.create_task(
            component("COLLECTOR", collector_run), name="connected-collector"
        ),
    }
    waiter = asyncio.create_task(stop.wait(), name="connected-shutdown")
    forced = []
    try:
        await asyncio.wait([*tasks.values(), waiter], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        _, pending = await asyncio.wait(tasks.values(), timeout=shutdown_seconds)
        forced = [name for name, task in tasks.items() if task in pending]
        for task in pending:
            task.cancel()
        # Cancellation must finish provider/model child cleanup before leases close.
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    failures = [name for name, value in zip(tasks, results) if isinstance(value, BaseException)]
    if unexpected or forced or failures:
        raise ComponentFailure(
            "CONNECTED_COMPONENT_STOPPED:" + ",".join(sorted(set(unexpected + forced + failures)))
        )


async def run(directory, feed_directory, policy_file, schemas_file, stop, *, clock_source=utc_now):
    report, settings, policy, schemas, observer = check(
        directory, feed_directory, policy_file, schemas_file, clock_source=clock_source
    )
    if stop.is_set():
        return {"status": "NOT_STARTED", "live_enabled": False}
    # The owner lease and native recovery are acquired before collector recovery.
    # Both must succeed before either asynchronous component can read or trade.
    with existing_runtime(directory, clock=clock_source) as (runtime, enrolled):
        if settings != enrolled:
            raise ValueError("Runtime settings changed during startup")
        # Recheck under the owner lease, including the retained replay event.
        inspect_owner(Path(directory), enrolled, clock_source=clock_source)
        feed = ContinuousFeed(feed_directory, policy, schemas)
        try:
            ready = asyncio.Event()

            async def trade(stop):
                await runtime.run(stop, ready=ready)

            async def collect(stop):
                waits = [asyncio.create_task(ready.wait()), asyncio.create_task(stop.wait())]
                try:
                    await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in waits:
                        task.cancel()
                    await asyncio.gather(*waits, return_exceptions=True)
                if stop.is_set():
                    return
                await feed.run(
                    stop,
                    clock_source=clock_source,
                    held_source=lambda: held_from_observer(observer),
                    calendar=XNYSCalendar(),
                    source_settings=enrolled,
                )

            await supervise(trade, collect, stop)
        finally:
            feed.close()
    return {
        "status": "STOPPED",
        "population_id": settings.limits.population_id,
        "live_enabled": False,
        "entry_blockers": report["entry_blockers"],
        "automatic_resume": False,
    }


async def serve(args):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    timer = loop.call_later(args.seconds, stop.set)
    try:
        return await run(args.directory, args.feed_directory, args.policy, args.schemas, stop)
    finally:
        timer.cancel()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "run"))
    for name in ("directory", "feed-directory", "policy", "schemas"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--seconds", type=int, help="Required run duration, 1..86400 seconds")
    args = parser.parse_args(argv)
    if args.operation == "run" and (args.seconds is None or not 1 <= args.seconds <= 86400):
        parser.error("Explicit bounded run duration required")
    if args.operation == "check" and args.seconds is not None:
        parser.error("Check does not start workers")
    try:
        if args.operation == "check":
            result = check(args.directory, args.feed_directory, args.policy, args.schemas)[0]
        else:
            result = asyncio.run(serve(args))
    except ComponentFailure as exc:
        print(json.dumps({"status": "UNAVAILABLE", "reason": str(exc), "live_enabled": False}))
        return 2
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        # Never echo provider exceptions, private configuration or credentials.
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "CONNECTED_RUNTIME_UNAVAILABLE",
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
