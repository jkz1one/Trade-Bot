"""Initialize/run/report an isolated fixture PAPER service. Never a deployed SHADOW upgrade."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.domain.models import MarketPacket, utc_now
from app.execution.durable_fixture import DurableFixtureVenue
from app.execution.economics import CostAccounting, CostPolicy
from app.execution.engine import ExecutionEngine
from app.execution.journal import ExecutionJournal
from app.execution.judgment import JudgmentCoordinator, JudgmentLimits
from app.execution.models import ExecutionLimits
from app.execution.quote_feed import DurableQuoteFeed
from app.execution.runtime import PaperRuntime, RuntimeLimits, runtime_lease
from app.execution.supervisor import ExecutionSupervisor, SupervisorLimits


def initialize(
    directory,
    *,
    capital,
    symbols,
    key_file=None,
    total_budget=None,
    daily_budget=None,
    market_oauth_file=None,
):
    if (
        capital <= 0
        or not symbols
        or len(symbols) != len(set(symbols))
        or any(not s.isascii() or not s.isalpha() or not s.isupper() or len(s) > 5 for s in symbols)
    ):
        raise ValueError("Positive capital and an explicit unique equity fixture universe required")
    if key_file is None and (total_budget is not None or daily_budget is not None):
        raise ValueError("Model budgets require explicit model key opt-in")
    policy = CostPolicy(total_budget=total_budget, daily_budget=daily_budget) if key_file else None
    source = None
    if market_oauth_file:
        from app.execution.market_reads import MarketReadPolicy, private_oauth

        source = MarketReadPolicy(oauth_file=str(Path(market_oauth_file).expanduser().absolute()))
        private_oauth(source.oauth_file)
    directory = Path(directory).absolute()
    directory.mkdir(mode=0o700)  # Exclusive, never reuse/reset an existing population.
    settings = Settings(
        _env_file=None,
        mode="PAPER",
        live_enabled=False,
        starting_capital=capital,
        initial_symbols=symbols,
        min_order_notional=1,
        quote_max_age_seconds=90,
        max_daily_entries=8,
        exit_cooldown_minutes=15,
    )
    with runtime_lease(directory / "execution.db"):
        engine = ExecutionEngine(directory / "execution.db", settings)
        engine.journal.enable_restore_fence(now=utc_now())
        venue = DurableFixtureVenue(directory / "venue.db", capital=capital)
        feed = DurableQuoteFeed(
            directory / "quotes.db",
            symbols=symbols,
            source=source.model_dump(mode="json") if source else None,
        )
        supervisor = ExecutionSupervisor(engine, venue, feed)
        judgment = (
            JudgmentCoordinator(CostAccounting(engine, policy), JudgmentLimits())
            if policy
            else None
        )
        runtime = PaperRuntime(supervisor, judgment=judgment, key_file=key_file)
        runtime.enroll()
    return {
        "status": "INITIALIZED",
        "mode": "FIXTURE_PAPER",
        "agent": "openai" if key_file else "stub-hold",
        "network_calls": False,
        "live_enabled": False,
    }


def load(directory):
    """Caller holds the lease before any writable constructor/startup recovery."""
    journal = ExecutionJournal(Path(directory) / "execution.db")
    with journal.read() as db:
        row = db.execute("SELECT policy_json FROM execution_runtime WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Explicit runtime enrollment required")
        policy = json.loads(row[0])
        frozen = json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )
        if frozen != policy["engine"]:
            raise ValueError("Runtime engine policy changed")
        costs_row = db.execute(
            "SELECT policy_json FROM execution_cost_policy WHERE id=1"
        ).fetchone()
    risk = frozen["risk_settings"]
    settings = Settings(
        _env_file=None,
        mode="PAPER",
        live_enabled=False,
        starting_capital=frozen["capital"],
        initial_symbols=frozen["symbols"],
        min_order_notional=risk["min_order_notional"],
        quote_max_age_seconds=int(risk["quote_max_age_seconds"]),
        max_daily_entries=int(risk["max_daily_entries"]),
        exit_cooldown_minutes=int(risk["exit_cooldown_minutes"]),
    )
    engine = ExecutionEngine(
        journal.path, settings, limits=ExecutionLimits.model_validate(frozen["execution_limits"])
    )
    venue = DurableFixtureVenue(policy["supervisor"]["venue_path"])
    feed = DurableQuoteFeed(policy["supervisor"]["feed_path"])
    supervisor = ExecutionSupervisor(
        engine, venue, feed, limits=SupervisorLimits.model_validate(policy["supervisor"]["limits"])
    )
    judgment = (
        JudgmentCoordinator(
            CostAccounting(engine, CostPolicy.model_validate_json(costs_row[0])),
            JudgmentLimits.model_validate(policy["judgment"]["limits"]),
        )
        if policy["agent"] == "openai"
        else None
    )
    runtime = PaperRuntime(
        supervisor,
        limits=RuntimeLimits.model_validate(policy["limits"]),
        judgment=judgment,
        key_file=policy["key_file"],
    )
    with engine.journal.read() as db:
        runtime._state(db)
    return runtime


async def serve(directory):
    with runtime_lease(Path(directory) / "execution.db"):
        runtime = load(directory)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        try:
            return await runtime._serve(stop)
        finally:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(signum)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--directory", required=True)
    init.add_argument("--capital", type=Decimal, required=True)
    init.add_argument("--symbols", nargs="+", required=True)
    init.add_argument("--key-file")
    init.add_argument("--total-budget", type=Decimal)
    init.add_argument("--daily-budget", type=Decimal)
    init.add_argument("--market-oauth-file")
    for command in ("run", "report", "publish", "collect"):
        child = sub.add_parser(command)
        child.add_argument("--directory", required=True)
        if command == "publish":
            child.add_argument("--packet-file", required=True)
            child.add_argument("--sample-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(
                args.directory,
                capital=args.capital,
                symbols=args.symbols,
                key_file=args.key_file,
                total_budget=args.total_budget,
                daily_budget=args.daily_budget,
                market_oauth_file=args.market_oauth_file,
            )
        elif args.command == "run":
            return asyncio.run(serve(args.directory))
        elif args.command == "report":
            result = ExecutionJournal(Path(args.directory) / "execution.db").report()
        elif args.command == "collect":
            from app.execution.market_reads import collect_once

            result = asyncio.run(collect_once(DurableQuoteFeed(Path(args.directory) / "quotes.db")))
        else:
            # Publishing is trusted local fixture input, no fabricated prices/fills.
            with Path(args.packet_file).open("rb") as source:
                raw = source.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError("Fixture packet exceeded its size limit")
            sequence = DurableQuoteFeed(Path(args.directory) / "quotes.db").publish(
                args.sample_id, MarketPacket.model_validate_json(raw)
            )
            result = {"status": "PUBLISHED", "feed_sequence": sequence, "network_calls": False}
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 -- never disclose credentials/raw fixture content
        print(
            json.dumps(
                {"status": "ERROR", "error_class": type(exc).__name__, "live_enabled": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
