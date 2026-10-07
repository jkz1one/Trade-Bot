"""Run a saved, deterministic fixture rehearsal without broker/model connections."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.domain.models import AccountState, Candidate, MarketPacket, Quote, TradeDecision
from app.execution.durable_fixture import DurableFixtureVenue
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from app.execution.journal import ExecutionJournal
from app.execution.models import ExecutionLimits
from app.execution.operator import OperatorCommand, OperatorControl, sign_command


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


def _reserve_file(path):
    # Exclusive local file creation; run before launching any fixture child.
    with path.open("xb"):
        path.chmod(0o600)


def run_rehearsal(path):
    path = Path(path)
    # Reserve a new private file exclusively. No resets, migrations, or experiment import.
    _reserve_file(path)
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


async def run_deadline_rehearsal(path):
    """Lost acknowledgment with independent durable venue evidence and bounded children."""
    path = Path(path)
    _reserve_file(path)
    venue = DurableFixtureVenue(
        str(path) + ".venue.db", capital=Decimal(10), fault="STALL_AFTER_ACCEPT"
    )
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
    limits = ExecutionLimits(
        max_entry_notional=10,
        max_position_notional=10,
        total_loss_limit=10,
        daily_loss_limit=10,
        process_timeout_seconds=2,
    )
    at = datetime(2026, 10, 6, 15, tzinfo=UTC)
    engine = ExecutionEngine(path, settings, limits=limits)
    # Initial read is fault-free; the configured fault applies only to local acceptance.
    _require((await engine.reconcile_fixture(venue, now=at))["reconciled"])
    entry = engine.prepare("deadline-entry", _decision(), _packet(at), now=at)
    _require(
        await engine.dispatch_async(entry.client_id, venue, now=at, packet=_packet(at)) == "UNKNOWN"
    )
    _require(venue.submit_count == 1 and engine.journal.report()["halted"])
    venue = DurableFixtureVenue(venue.path)
    engine = ExecutionEngine(path, settings, limits=limits)
    _require(await engine.dispatch_async(entry.client_id, venue, now=at) == "UNKNOWN")
    _require(venue.submit_count == 1)
    _require((await engine.reconcile_fixture(venue, now=at))["reconciled"])
    at += timedelta(seconds=1)
    half = (entry.quantity / 2).quantize(Decimal(".00000001"))
    venue.fill(entry.client_id, half, Decimal(10), at, fill_id="deadline-partial")
    venue.terminal(entry.client_id, "CANCELED", at)
    _require((await engine.reconcile_fixture(venue, now=at))["new_fills"] == 1)
    p = _packet(at)
    p.candidates[0].quote.bid = Decimal("9.4")
    p.candidates[0].quote.ask = Decimal("9.41")
    _require(engine.supervise(p, now=at)["exit_reason"] == "INVALIDATION")
    engine.resume("complete fixture evidence and current stop supervision", now=at)
    exit_intent = engine.prepare_protective_exit(p, now=at)
    _require(await engine.dispatch_async(exit_intent.client_id, venue, now=at, packet=p) == "OPEN")
    venue.fill(exit_intent.client_id, half, exit_intent.limit_price, at, fill_id="deadline-exit")
    _require((await engine.reconcile_fixture(venue, now=at))["new_fills"] == 1)
    report = engine.journal.report()
    _require(venue.submit_count == 2 and report["ledger"]["position"] is None)
    report.update(
        status="OK",
        measurement_note="Durable fake venue and scripted quotes; deadline/recovery verification, never broker execution or trading performance.",
    )
    return report


def run_operator_rehearsal(path):
    path = Path(path)
    _reserve_file(path)
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    engine = ExecutionEngine(path, settings)
    venue = LocalFixtureVenue(Decimal(10))
    at = datetime(2026, 10, 6, 15, tzinfo=UTC)
    _require(engine.reconcile(venue.snapshot(at), now=at)["reconciled"])
    key = secrets.token_bytes(32)  # Ephemeral fixture capability, never printed/persisted.
    OperatorControl.enroll(engine, key, now=at)
    operator = OperatorControl(engine, key)

    def request(action, **targets):
        review = operator.review()
        command = OperatorCommand(
            journal_id=operator.journal_id,
            command_id="fixture-command-" + secrets.token_hex(8),
            actor="offline-operator",
            action=action,
            reason="Verified local fixture evidence",
            expected_revision=review["revision"],
            issued_at=at,
            expires_at=at + timedelta(minutes=1),
            **targets,
        )
        signature = sign_command(command, key)
        result = operator.apply(command, signature, now=at)
        _require(operator.apply(command, signature, now=at)["replayed"])
        return result

    intent = engine.prepare("operator-entry", _decision(), _packet(at), now=at)
    venue.lose_next_ack = True
    _require(engine.dispatch(intent.client_id, venue, now=at, packet=_packet(at)) == "UNKNOWN")
    _require(request("RESUME")["status"] == "REJECTED")
    for alert in engine.journal.alerts():
        _require(
            request("ACK_ALERT", alert_sequence=alert["event_sequence"])["status"] == "APPLIED"
        )
    _require(engine.journal.report()["halted"])  # Acknowledgment cannot clear risk.
    engine = ExecutionEngine(path, settings)
    operator = OperatorControl(engine, key)
    venue.terminal(intent.client_id, "CANCELED", at)
    _require(engine.reconcile(venue.snapshot(at), now=at)["reconciled"])
    _require(request("RESUME")["status"] == "APPLIED")
    _require(venue.submit_count == 1)
    report = engine.journal.report()
    report.update(
        status="OK",
        measurement_note="Authenticated offline fixture recovery; no API, broker fills or deployed controls.",
    )
    return report


def run_recovery_rehearsal(path):
    """Exclusive offline stores, retired keys and deliberately restored stale fixture bytes."""
    path = Path(path)
    _reserve_file(path)
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    engine = ExecutionEngine(path, settings)
    at = datetime(2026, 10, 6, 15, tzinfo=UTC)
    venue = LocalFixtureVenue(Decimal(10))
    _require(engine.reconcile(venue.snapshot(at), now=at)["reconciled"])
    _require(engine.journal.enable_restore_fence(now=at)["status"] == "VERIFIED")
    keys = [secrets.token_bytes(32) for _ in range(3)]
    OperatorControl.enroll(engine, keys[0], now=at)
    operator = OperatorControl(engine, keys[0])

    def request(action, key, **targets):
        envelope = OperatorCommand(
            journal_id=operator.journal_id,
            command_id="recovery-" + secrets.token_hex(8),
            actor="offline-operator",
            action=action,
            reason="Reviewed offline recovery proof",
            credential_generation=operator.credential_generation,
            expected_revision=operator.review()["revision"],
            issued_at=at,
            expires_at=at + timedelta(minutes=1),
            **targets,
        )
        return operator.apply(envelope, sign_command(envelope, key), now=at)

    intent = engine.prepare("recovery-entry", _decision(), _packet(at), now=at)
    older = path.read_bytes()
    venue.lose_next_ack = True
    _require(engine.dispatch(intent.client_id, venue, now=at, packet=_packet(at)) == "UNKNOWN")
    _require(
        request("ROTATE_KEY", keys[0], replacement_fingerprint=hashlib.sha256(keys[1]).hexdigest())[
            "status"
        ]
        == "APPLIED"
    )
    operator = OperatorControl(engine, keys[1])
    _require(request("REVOKE_KEY", keys[1])["status"] == "APPLIED")
    _require(
        OperatorControl.recover_revoked(engine, keys[2], "New fixture capability", now=at) == 4
    )
    operator = OperatorControl(engine, keys[2])
    _require(request("RESUME", keys[2])["status"] == "REJECTED")
    venue.terminal(intent.client_id, "CANCELED", at)
    _require(engine.reconcile(venue.snapshot(at), now=at)["reconciled"])
    _require(request("RESUME", keys[2])["status"] == "APPLIED")
    current = path.read_bytes()
    try:
        # This is a controlled proof on the brand-new fixture file only. There is
        # no reset/rebind command to advance authority from a restored journal.
        path.write_bytes(older)
        _require(ExecutionJournal(path).report()["restore_fence"]["status"] == "BLOCKED")
        try:
            engine.dispatch(intent.client_id, venue, now=at, packet=_packet(at))
        except ValueError as exc:
            _require(str(exc) == "RESTORED_OR_CHANGED_EXECUTION_JOURNAL")
        else:
            raise RuntimeError("Restored fixture unexpectedly dispatched")
    finally:
        path.write_bytes(current)  # Exact current fixture bytes, no authority rewrite.
    report = engine.journal.report()
    _require(report["restore_fence"]["status"] == "VERIFIED" and venue.submit_count == 1)
    report.update(
        status="OK",
        restored_journal_blocked=True,
        measurement_note="Offline credential/restore proof only. Retained authority detects journal-only rollback; rolling back both files is not detectable.",
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["run", "deadline-run", "operator-run", "recovery-run", "report"]
    )
    parser.add_argument("--db", default="execution-rehearsal.db")
    args = parser.parse_args(argv)
    try:
        report = (
            run_rehearsal(args.db)
            if args.command == "run"
            else asyncio.run(run_deadline_rehearsal(args.db))
            if args.command == "deadline-run"
            else run_operator_rehearsal(args.db)
            if args.command == "operator-run"
            else run_recovery_rehearsal(args.db)
            if args.command == "recovery-run"
            else ExecutionJournal(args.db).report()
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
