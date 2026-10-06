"""Run a saved, deterministic fixture rehearsal without broker/model connections."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.domain.models import AccountState, Candidate, MarketPacket, Quote, TradeDecision
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.journal import ExecutionJournal


def _packet(at, *, exiting=False):
    return MarketPacket(
        as_of=at,
        account=AccountState(cash=10, buying_power=10, equity=10, high_watermark=10),
        candidates=[
            Candidate(
                quote=Quote(
                    symbol="SPY",
                    timestamp=at,
                    bid=Decimal(11) if exiting else Decimal("9.99"),
                    ask=Decimal("11.01") if exiting else Decimal(10),
                    last=Decimal(10),
                ),
                atr_fraction=Decimal(".01"),
                realized_vol_fraction=Decimal(".01"),
            )
        ],
    )


def _decision(*, exiting=False):
    return TradeDecision(
        action="CLOSE" if exiting else "OPEN_LONG",
        symbol="SPY",
        confidence=0.8,
        setup_quality=0.8,
        desired_exposure_fraction=1,
        invalidation_price=Decimal("9.50"),
        thesis="Offline execution fixture",
        invalidation_reason="Fixture invalidation",
        why_now="Rehearsal",
    )


def _require(value):
    if not value:
        raise RuntimeError("Execution fixture verification failed")


def run_rehearsal(path):
    path = Path(path)
    # Reserve a new private file exclusively. No resets, migrations, or experiment import.
    with path.open("xb"):
        path.chmod(0o600)
    settings = Settings(
        _env_file=None,
        mode="PAPER",
        live_enabled=False,
        starting_capital=10,
        initial_symbols=["SPY"],
        min_order_notional=1,
        quote_max_age_seconds=90,
        max_daily_entries=8,
        exit_cooldown_minutes=15,
    )
    at = datetime(2026, 10, 6, 15, tzinfo=UTC)
    engine = ExecutionEngine(path, settings)
    venue = LocalFixtureVenue(Decimal(10))
    _require(engine.reconcile(venue.snapshot(at), now=at)["reconciled"])
    intent = engine.prepare("fixture-entry", _decision(), _packet(at), now=at)
    venue.lose_next_ack = True
    _require(engine.dispatch(intent.client_id, venue, now=at, packet=_packet(at)) == "UNKNOWN")
    engine = ExecutionEngine(path, settings)  # Persistent state across restart.
    _require(engine.dispatch(intent.client_id, venue, now=at) == "UNKNOWN")
    _require(venue.submit_count == 1)
    at += timedelta(seconds=1)
    half = (intent.quantity / 2).quantize(Decimal(".00000001"))
    venue.fill(intent.client_id, half, Decimal(10), at, fill_id="fixture-buy-partial")
    snap = venue.snapshot(at)
    _require(engine.reconcile(snap, now=at)["new_fills"] == 1)
    _require(engine.reconcile(snap, now=at)["new_fills"] == 0)
    try:
        engine.resume("cannot release an open remainder", now=at)
    except ExecutionBlocked:
        pass
    else:
        raise RuntimeError("Rehearsal unexpectedly resumed with an active order")
    venue.terminal(intent.client_id, "CANCELED", at)  # Local fixture outcome, no broker action.
    _require(engine.reconcile(venue.snapshot(at), now=at)["reconciled"])
    engine.resume("verified fixture partial fill and canceled remainder", now=at)
    exit_intent = engine.prepare(
        "fixture-exit", _decision(exiting=True), _packet(at, exiting=True), now=at
    )
    _require(
        engine.dispatch(exit_intent.client_id, venue, now=at, packet=_packet(at, exiting=True))
        == "OPEN"
    )
    venue.fill(exit_intent.client_id, half, Decimal(11), at, fill_id="fixture-sell")
    _require(engine.reconcile(venue.snapshot(at), now=at)["reconciled"])
    _require(venue.submit_count == 2)
    report = engine.journal.report()
    report["status"] = "OK"
    report["measurement_note"] = (
        "Scripted fixture outcomes test execution safety; not trading performance or broker capability proof."
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "report"])
    parser.add_argument("--db", default="execution-rehearsal.db")
    args = parser.parse_args(argv)
    try:
        report = (
            run_rehearsal(args.db) if args.command == "run" else ExecutionJournal(args.db).report()
        )
        print(json.dumps(report, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                    "network_calls": False,
                    "live_enabled": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
