"""Durable normalized delivery from the fixed read gateway, separate from trading.

Unknown entitlement, missing executable sizes and unreviewed contracts stay blocked.
This module never imports a model worker or submits an order.
"""

import asyncio
import fcntl
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import Field, model_validator

from app.mixed.carry import SwingCarryIntent
from app.mixed.sources import StockCycleInput
from app.mixed.stock_models import StockInstrument
from app.mixed.swing_feed import SwingHistoryPolicy
from app.options.coordinator import DegenFrame
from app.options.engine import clock, fingerprint
from app.options.models import Name, OptionInstrument, OptionRecord
from app.options.read_capture import CapturePolicy, CaptureResult, collect
from app.options.read_gateway import CapturePlan, ReadSample
from app.options.read_mapping import (
    equity_history,
    equity_quotes,
    option_metadata,
    option_quotes,
    reviewed_schemas,
    stock_quotes,
)
from app.options.runtime_models import PortfolioRuntimePacket
from app.options.selection import OptionInventory


class FeedPolicy(OptionRecord):
    version: Literal["portfolio-continuous-feed-v2"] = "portfolio-continuous-feed-v2"
    population_id: Name
    stocks: tuple[StockInstrument, ...] = Field(min_length=1, max_length=2)
    candidates: tuple[OptionInstrument, ...] = Field(default=(), max_length=6)
    poll_seconds: int = Field(default=10, strict=True, ge=5, le=30)
    calls_per_minute: int = Field(default=24, strict=True, ge=1, le=120)
    capture: CapturePolicy
    swing_history: SwingHistoryPolicy | None = Field(default=None, exclude_if=lambda v: v is None)

    carry_intents: tuple[SwingCarryIntent, ...] = Field(
        default=(), max_length=32, exclude_if=lambda v: not v
    )

    @model_validator(mode="after")
    def carry_schedule(self):
        sessions = tuple(i.target_session for i in self.carry_intents)
        if len(set(sessions)) != len(sessions) or (sessions and self.swing_history is None):
            raise ValueError("Unique carry sessions and explicit Swing history enrollment required")
        return self


def carry_intent_for(policy, target):
    return next((i for i in policy.carry_intents if i.target_session == target), None)


def planned(policy, held, now, window, *, cycle):
    """Deduplicate held/candidate contracts and shared equity reads before spending quota."""
    symbols = tuple(i.symbol for i in policy.stocks)
    if len(set(symbols)) != len(symbols) or not set(symbols) <= {"SPY", "QQQ"}:
        raise ValueError("Reviewed equity feed universe required")
    if any(i.provider != "robinhood" for i in (*policy.stocks, *policy.candidates, *held)):
        raise ValueError("Reviewed Robinhood instrument identities required")
    stock_ids = {i.instrument_id: i for i in policy.stocks}
    options = {i.instrument_id: i for i in policy.candidates if now < i.contract.last_trading_at}
    for i in held:
        if isinstance(i, StockInstrument):
            if stock_ids.get(i.instrument_id) != i:
                raise ValueError("Held stock missing from reviewed feed universe")
        else:
            if i.contract.underlying not in symbols:
                # Keep supported peers updating. The normalized envelope records
                # this exact held contract as unavailable; no quote is invented.
                continue
            if i.instrument_id in options and options[i.instrument_id] != i:
                raise ValueError("Held option metadata conflicts with reviewed catalog")
            options[i.instrument_id] = i
    if len(options) > 8:
        raise ValueError("Held plus candidate read capacity exceeded")
    calls = [
        ReadSample(label="equities", tool="get_equity_quotes", arguments={"symbols": list(symbols)})
    ]
    if options:
        calls.append(
            ReadSample(
                label="options",
                tool="get_option_quotes",
                arguments={"instrument_ids": sorted(options)},
            )
        )
    if cycle and window is not None:
        end = now - timedelta(seconds=now.timestamp() % 300)
        if end > window.opens_at:
            calls.append(
                ReadSample(
                    label="history",
                    tool="get_equity_historicals",
                    arguments={
                        "symbols": list(symbols),
                        "start_time": window.opens_at.isoformat(),
                        "end_time": end.isoformat(),
                        "interval": "5minute",
                        "bounds": "regular",
                        "adjustment_type": "split",
                    },
                )
            )
    return CapturePlan(
        purpose="SCHEMA_MAPPING_EVIDENCE",
        symbols=symbols,
        instrument_ids=tuple(sorted(options)),
        calls=tuple(calls),
    ), tuple(options.values())


def normalize(
    policy,
    schemas,
    captured,
    catalog,
    held,
    *,
    sequence,
    now,
    history_issues=(),
    source_settings=None,
    swing_sources=None,
    swing_evidence=None,
):
    """A successful transport never upgrades unknown data into execution authority."""
    captured = CaptureResult.model_validate(captured.model_dump())
    if (
        captured.schemas is None
        or captured.schemas.sha256 != schemas.sha256
        or captured.plan is None
    ):
        raise ValueError("Original schema-bound capture required")
    if not captured.started_at <= captured.collected_at <= now:
        raise ValueError("Original capture clocks required")
    quotes, underlyings, stocks, histories, metadata = (), (), (), (), ()
    issues = list(history_issues)
    optional = tuple(
        c
        for c in captured.plan.calls
        if c.tool == "get_equity_historicals"
        and (
            (c.label == "history" and c.arguments.get("interval") == "5minute")
            or (
                policy.swing_history is not None
                and c.label.startswith("swing-")
                and c.arguments.get("interval") in {"day", "hour"}
            )
        )
    )
    if (
        len(captured.observations) > len(captured.plan.calls)
        or (
            captured.status == "COMPLETE" and len(captured.observations) != len(captured.plan.calls)
        )
        or (captured.status == "FAILED" and not optional)
    ):
        raise ValueError("Complete required market-read coverage required")
    optional_failed = False

    def unavailable(call):
        issue = (
            "INTRADAY_HISTORY_UNAVAILABLE"
            if call.label == "history"
            else "SWING_HISTORY_UNAVAILABLE"
        )
        if issue not in issues:
            issues.append(issue)

    for index, call in enumerate(captured.plan.calls):
        receipt = captured.observations[index] if index < len(captured.observations) else None
        if receipt is None and captured.status == "FAILED" and call in optional:
            optional_failed = True
            unavailable(call)
            continue
        if (
            receipt is None
            or receipt.get("label") != call.label
            or receipt.get("tool") != call.tool
        ):
            raise ValueError("Original read receipt coverage changed")
        if receipt.get("completed") is not True:
            if captured.status == "FAILED" and call in optional:
                optional_failed = True
                unavailable(call)
                continue
            raise ValueError("Required original market read incomplete")
        args = (schemas, call, receipt["raw"])
        if call.tool == "get_equity_quotes":
            for one, raw in available_quotes(*args, issues=issues):
                try:
                    u = equity_quotes(schemas, one, raw, received_at=captured.collected_at)
                    s = stock_quotes(
                        schemas,
                        one,
                        raw,
                        received_at=captured.collected_at,
                        instruments=tuple(
                            i for i in policy.stocks if i.symbol in one.arguments["symbols"]
                        ),
                    )
                    underlyings += u
                    stocks += s
                except (ValueError, TypeError, ArithmeticError):
                    issues.append("UNUSABLE_EQUITY:" + one.arguments["symbols"][0])
        elif call.tool == "get_option_quotes":
            for one, raw in available_quotes(*args, issues=issues):
                items = tuple(
                    i for i in catalog if i.instrument_id in one.arguments["instrument_ids"]
                )
                try:
                    q = option_quotes(
                        schemas, one, raw, received_at=captured.collected_at, instruments=items
                    )
                    m = option_metadata(
                        schemas, one, raw, received_at=captured.collected_at, instruments=items
                    )
                    quotes += q
                    metadata += m
                except (ValueError, TypeError, ArithmeticError):
                    issues.append("UNUSABLE_OPTION:" + one.arguments["instrument_ids"][0])
        elif call.tool == "get_equity_historicals":
            if call.label.startswith("swing-") and policy.swing_history is not None:
                # This original capture is separately normalized into the durable
                # pre-open cache. It is not a current intraday strategy frame.
                continue
            try:
                histories = equity_history(*args, received_at=captured.collected_at)
            except (ValueError, TypeError, ArithmeticError, SchemaError):
                if call not in optional:
                    raise
                unavailable(call)
        else:
            raise ValueError("Only reviewed normalized mappings may deliver runtime inputs")
    if captured.status == "FAILED" and not optional_failed:
        issues.append("CAPTURE_INCOMPLETE")
    held_ids = {i.instrument_id for i in held}
    candidate_ids = {i.instrument_id for i in policy.candidates}
    candidate_quotes = tuple(q for q in quotes if q.instrument.instrument_id in candidate_ids)
    held_quotes = tuple(
        q
        for q in quotes
        if q.instrument.instrument_id in held_ids
        and q.instrument.instrument_id not in candidate_ids
    )
    inventories = []
    for symbol in (i.symbol for i in policy.stocks):
        items = tuple(
            m
            for m in metadata
            if m.instrument.instrument_id in candidate_ids
            and m.instrument.contract.underlying == symbol
            and m.instrument.contract.expiration
            == now.astimezone(ZoneInfo("America/New_York")).date()
        )
        if items:
            inventories.append(
                OptionInventory(
                    request_id=captured.request_id,
                    symbol=symbol,
                    expiration=items[0].instrument.contract.expiration,
                    source=items[0].source,
                    source_at=min(m.source_at for m in items),
                    received_at=captured.collected_at,
                    entitlement="UNKNOWN",
                    complete=all(m.complete for m in items),
                    contracts=items,
                )
            )
    frame = DegenFrame(
        portfolio_version="portfolio-frame-v2",
        stocks=tuple(StockCycleInput(quote=q) for q in stocks),
        quotes=candidate_quotes,
        held_quotes=held_quotes,
        underlyings=underlyings,
        histories=histories,
        inventories=tuple(inventories),
    )
    if source_settings is not None:
        if (
            source_settings.limits.population_id != policy.population_id
            or source_settings.stock_policy is None
            or source_settings.stock_policy.instruments != policy.stocks
        ):
            raise ValueError("Matching runtime owner and stock universe required")
        if (
            source_settings.stock_policy.swing is not None
            or source_settings.swing_policy is not None
        ):
            from app.mixed.swing_binding import policy_from_settings
            from app.mixed.swing_delivery import assemble

            frame, missing = assemble(
                frame,
                swing_sources,
                policy_from_settings(
                    source_settings,
                    policy.candidates,
                    carry_intent_for(policy, now.astimezone(ZoneInfo("America/New_York")).date()),
                ),
                metadata,
                swing_evidence,
                now=now,
            )
            issues.extend(missing)
        if source_settings.scope_policy is not None and frame.scope is None:
            issues.append("SCOPE_CURRENT_INPUT_UNAVAILABLE")
    elif swing_sources is not None or swing_evidence is not None:
        raise ValueError("Swing delivery requires enrolled runtime settings")
    cycle = bool(histories) and len(stocks) == len(policy.stocks) and not issues
    if not cycle:
        frame = market_frame(frame)
    packet = PortfolioRuntimePacket(
        population_id=policy.population_id,
        sequence=sequence,
        recorded_at=now,
        kind="CYCLE" if cycle else "MARKET",
        coverage_issues=tuple(issues)
        + tuple(
            "UNREVIEWED_HELD_MAPPING:" + i.instrument_id
            for i in held
            if isinstance(i, OptionInstrument)
            and i.contract.underlying not in {s.symbol for s in policy.stocks}
        ),
        frame=frame,
    )
    return bounded_delivery(packet)


def market_frame(frame):
    """Keep all protection books while removing CYCLE-only strategy context."""
    return DegenFrame.model_validate(
        frame.model_dump()
        | {
            "histories": (),
            "inventories": (),
            "swing": (),
            "swing_batches": (),
            "stocks": tuple(StockCycleInput(quote=s.quote) for s in frame.stocks),
        }
    )


def bounded_delivery(packet):
    """Oversized strategy context must not make held-market delivery unreadable."""
    from app.options.runtime import MAX_PACKET_BYTES

    if len(packet.model_dump_json().encode()) <= MAX_PACKET_BYTES:
        return packet
    packet = PortfolioRuntimePacket.model_validate(
        packet.model_dump()
        | {
            "kind": "MARKET",
            "frame": market_frame(packet.frame),
            "coverage_issues": (*packet.coverage_issues, "RUNTIME_STRATEGY_PACKET_CAPACITY"),
        }
    )
    if len(packet.model_dump_json().encode()) > MAX_PACKET_BYTES:
        raise ValueError("Market evidence exceeds runtime packet capacity")
    return packet


def available_quotes(schemas, call, raw, *, issues):
    """Validate the complete wire response, then map only exact available subjects.

    Missing data is recorded separately. Extra/duplicate identities are rejected.
    The original unmodified batch response stays in the durable capture receipt.
    """
    from app.options.read_mapping import response

    _, data = response(schemas, call, raw, call.tool)
    field, key = (
        ("symbols", "symbol")
        if call.tool == "get_equity_quotes"
        else ("instrument_ids", "instrument_id")
    )
    expected = call.arguments[field]
    found = {}
    for row in data["results"] or []:
        if not isinstance(row, dict) or not isinstance(row.get("quote"), dict):
            continue
        identity = row["quote"][key]
        if identity not in expected or identity in found:
            raise ValueError("Unexpected or duplicate batched quote")
        found[identity] = row
    result = []
    for identity in expected:
        if identity not in found:
            issues.append("MISSING_QUOTE:" + identity)
            continue
        one = ReadSample(label=call.label, tool=call.tool, arguments={field: [identity]})
        sliced = {
            **raw,
            "structuredContent": {
                **raw["structuredContent"],
                "data": {**data, "results": [found[identity]]},
            },
        }
        result.append((one, sliced))
    return result


class ContinuousFeed:
    """One collector lease, persisted quotas/sequences, atomic file delivery and recovery."""

    def __init__(self, directory, policy, schemas, *, create=False):
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise ValueError("Absolute dedicated feed directory required")
        self.policy = FeedPolicy.model_validate(policy.model_dump())
        self.schemas = reviewed_schemas(schemas)
        if create:
            self.directory.mkdir(mode=0o700)
        from app.options.operator_inbox import private_directory

        private_directory(self.directory)
        self.lock = os.open(
            self.directory / "collector.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            database = self.directory / "collector.db"
            if create == database.exists():
                raise ValueError("Explicit new or existing feed enrollment required")
            if create:
                fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            self.db = sqlite3.connect(database)
            self.db.row_factory = sqlite3.Row
            frozen = fingerprint({"policy": self.policy, "schemas": self.schemas})
            if create:
                self.db.executescript(
                    "CREATE TABLE control(id INTEGER PRIMARY KEY,configuration TEXT NOT NULL); CREATE TABLE attempts(sequence INTEGER PRIMARY KEY,started_at TEXT NOT NULL,calls INTEGER NOT NULL,status TEXT NOT NULL,request_hash TEXT NOT NULL,raw_json TEXT,packet_json TEXT,packet_hash TEXT);"
                )
                self.db.execute("INSERT INTO control VALUES(1,?)", (frozen,))
                if self.policy.swing_history is not None:
                    self.db.execute(
                        "CREATE TABLE swing_history(target_session TEXT PRIMARY KEY,attempt_sequence INTEGER NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL)"
                    )
                    self.db.execute(
                        "CREATE TABLE swing_read_budget(sequence INTEGER PRIMARY KEY,calls INTEGER NOT NULL)"
                    )
            from app.mixed.feed_rollover import load_rollovers

            self.rollovers = load_rollovers(self.db, self.policy, self.schemas)
            self.db.execute("UPDATE attempts SET status='INTERRUPTED' WHERE status='STARTED'")
            self.db.commit()
            self.recover()
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            os.close(self.lock)
            raise

    def close(self):
        self.db.close()
        os.close(self.lock)

    def policy_for(self, target):
        from app.mixed.feed_rollover import policy_for

        return policy_for(self.policy, self.rollovers, target)

    def swing_snapshot(self, target):
        """Revalidate cached native histories against the retained original capture."""
        if self.policy.swing_history is None:
            raise ValueError("Swing history collection not enrolled")
        row = self.db.execute(
            "SELECT * FROM swing_history WHERE target_session=?", (target.isoformat(),)
        ).fetchone()
        if row is None:
            return None
        from app.mixed.swing_feed import SwingHistorySnapshot, snapshot
        from app.options.read_capture import policy_digest

        value = SwingHistorySnapshot.model_validate_json(row["payload_json"])
        attempt = self.db.execute(
            "SELECT * FROM attempts WHERE sequence=?", (row["attempt_sequence"],)
        ).fetchone()
        if attempt is None or attempt["raw_json"] is None:
            raise ValueError("Original Swing capture missing")
        captured = CaptureResult.model_validate_json(attempt["raw_json"])
        if (
            value.target_session != target
            or fingerprint(value) != row["payload_hash"]
            or captured.policy_sha256 != policy_digest(self.policy.capture)
            or captured.schemas != self.schemas
            or captured.plan is None
            or fingerprint(captured.plan) != attempt["request_hash"]
            or value
            != snapshot(
                self.policy.swing_history,
                tuple(i.symbol for i in self.policy.stocks),
                self.schemas,
                captured,
            )
        ):
            raise ValueError("Stored Swing history binding changed")
        return value

    def recover(self):
        row = self.db.execute(
            "SELECT * FROM attempts WHERE packet_json IS NOT NULL ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row:
            packet = PortfolioRuntimePacket.model_validate_json(row["packet_json"])
            if fingerprint(packet) != row["packet_hash"]:
                raise ValueError("Retained normalized feed changed")
            self.publish(packet)

    def publish(self, packet):
        destination = self.directory / "feed.json"
        if destination.exists():
            from app.options.runtime import read_packet

            previous = read_packet(destination)
            row = self.db.execute(
                "SELECT packet_hash FROM attempts WHERE sequence=?", (previous.sequence,)
            ).fetchone()
            if (
                row is None
                or fingerprint(previous) != row[0]
                or previous.sequence > packet.sequence
            ):
                raise ValueError("Feed file is not an owned delivered prefix")
        temporary = self.directory / (".delivery-" + str(packet.sequence))
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(packet.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        from app.options.operator_inbox import sync_directory

        sync_directory(self.directory)

    async def tick(
        self,
        *,
        now,
        held=(),
        window=None,
        reader=collect,
        source_settings=None,
        swing_evidence=None,
    ):
        now = clock(now)
        last = self.db.execute("SELECT * FROM attempts ORDER BY sequence DESC LIMIT 1").fetchone()
        from datetime import datetime

        if last:
            if last["status"] == "STARTED":
                return {"status": "CAPTURE_IN_PROGRESS"}
            if last["status"] == "NORMALIZED":
                self.recover()
            previous = datetime.fromisoformat(last["started_at"])
            if now < previous:
                raise ValueError("Collector clock regressed")
            if (now - previous).total_seconds() < self.policy.poll_seconds:
                return {"status": "RATE_LIMITED"}
        slot = int(now.timestamp()) // 300
        cycle = (
            last is None
            or int(datetime.fromisoformat(last["started_at"]).timestamp()) // 300 != slot
        )
        target_day = now.astimezone(ZoneInfo("America/New_York")).date()
        effective = self.policy_for(target_day)
        plan, catalog = planned(effective, held, now, window, cycle=cycle)
        used = self.db.execute(
            "SELECT COALESCE(SUM(calls),0) FROM attempts WHERE started_at>?",
            ((now - timedelta(minutes=1)).isoformat(),),
        ).fetchone()[0]
        if used + len(plan.calls) > self.policy.calls_per_minute:
            return {"status": "RATE_LIMITED"}
        history_calls = ()
        if self.policy.swing_history is not None:
            from app.mixed.swing_feed import planned_history

            target, proposed = planned_history(
                self.policy.swing_history, tuple(i.symbol for i in self.policy.stocks), now
            )
            history_used = self.db.execute(
                "SELECT COALESCE(SUM(b.calls),0) FROM swing_read_budget b JOIN attempts a USING(sequence) WHERE a.started_at>?",
                ((now - timedelta(minutes=1)).isoformat(),),
            ).fetchone()[0]
            # Reserve equity + held-option books at every poll, plus one intraday
            # history cycle at the open. Failed backfills spend their budget too,
            # including after restart, and cannot consume the quote reserve.
            quote_reserve = (
                2 * ((60 + self.policy.poll_seconds - 1) // self.policy.poll_seconds) + 1
            )
            if (
                target is not None
                and self.swing_snapshot(target) is None
                and used + len(plan.calls) + len(proposed) <= self.policy.calls_per_minute
                and history_used + len(proposed) <= self.policy.calls_per_minute - quote_reserve
            ):
                history_calls = proposed
                plan = CapturePlan.model_validate(
                    {**plan.model_dump(), "calls": (*plan.calls, *history_calls)}
                )
        sequence = (last["sequence"] if last else 0) + 1
        self.db.execute(
            "INSERT INTO attempts VALUES(?,?,?,'STARTED',?,NULL,NULL,NULL)",
            (sequence, now.isoformat(), len(plan.calls), fingerprint(plan)),
        )
        if history_calls:
            self.db.execute(
                "INSERT INTO swing_read_budget VALUES(?,?)", (sequence, len(history_calls))
            )
        self.db.commit()
        try:
            captured = await reader(self.policy.capture, schemas=self.schemas, plan=plan)
            self.db.execute(
                "UPDATE attempts SET raw_json=? WHERE sequence=?",
                (captured.model_dump_json(), sequence),
            )
            self.db.commit()
            from app.options.read_capture import policy_digest

            if (
                captured.plan != plan
                or captured.policy_sha256 != policy_digest(self.policy.capture)
                or captured.started_at < now
            ):
                raise ValueError("Collector response plan changed")
            swing, history_issues = None, ()
            if history_calls:
                from app.mixed.swing_feed import snapshot

                try:
                    swing = snapshot(
                        self.policy.swing_history,
                        tuple(i.symbol for i in self.policy.stocks),
                        self.schemas,
                        captured,
                    )
                except (ValueError, TypeError, ArithmeticError, SchemaError):
                    # Unavailable history must not discard usable held quotes.
                    history_issues = ("SWING_HISTORY_UNAVAILABLE",)
            bound = None
            if source_settings is not None and self.policy.swing_history is not None:
                bound = self.load_swing_sources(
                    source_settings,
                    captured.collected_at.astimezone(ZoneInfo("America/New_York")).date(),
                    now=captured.collected_at,
                )
            if captured.collected_at.astimezone(ZoneInfo("America/New_York")).date() != target_day:
                history_issues = (*history_issues, "SESSION_BOUNDARY_DURING_CAPTURE")
            packet = normalize(
                effective,
                self.schemas,
                captured,
                catalog,
                held,
                sequence=sequence,
                now=captured.collected_at,
                history_issues=history_issues,
                source_settings=source_settings,
                swing_sources=bound,
                swing_evidence=swing_evidence,
            )

            def quotes(frame):
                return {
                    q.instrument.instrument_id: q
                    for q in (
                        *frame.quotes,
                        *frame.held_quotes,
                        *(s.quote for s in frame.stocks),
                    )
                }

            unchecked = quotes(packet.frame)
            # Missing deliveries never erase a subject's last original source
            # clock. Walk retained envelopes until each current subject is found.
            for prior in self.db.execute(
                "SELECT packet_json,packet_hash FROM attempts WHERE packet_json IS NOT NULL ORDER BY sequence DESC"
            ):
                if not unchecked:
                    break
                previous = PortfolioRuntimePacket.model_validate_json(prior[0])
                if fingerprint(previous) != prior[1]:
                    raise ValueError("Retained normalized feed changed")
                for identity, old in quotes(previous.frame).items():
                    q = unchecked.pop(identity, None)
                    if q is not None and (
                        q.source_at < old.source_at
                        or (
                            q.source_at == old.source_at
                            and q.model_dump(exclude={"received_at"})
                            != old.model_dump(exclude={"received_at"})
                        )
                    ):
                        raise ValueError("Source evidence regressed or changed at the same clock")
            self.db.execute(
                "UPDATE attempts SET status='NORMALIZED',packet_json=?,packet_hash=? WHERE sequence=?",
                (packet.model_dump_json(), fingerprint(packet), sequence),
            )
            if swing is not None:
                self.db.execute(
                    "INSERT INTO swing_history VALUES(?,?,?,?)",
                    (
                        swing.target_session.isoformat(),
                        sequence,
                        swing.model_dump_json(),
                        fingerprint(swing),
                    ),
                )
            self.db.commit()
            self.publish(packet)
            self.db.execute("UPDATE attempts SET status='DELIVERED' WHERE sequence=?", (sequence,))
            self.db.commit()
            return {
                "status": "DELIVERED",
                "sequence": sequence,
                "entitlement": "UNKNOWN",
                "stock_sizes": "MISSING",
            }
        except (OSError, ValueError, TypeError, SchemaError):
            self.db.execute(
                "UPDATE attempts SET status='FAILED' WHERE sequence=? AND status='STARTED'",
                (sequence,),
            )
            self.db.commit()
            return {"status": "FAILED", "sequence": sequence}

    def load_swing_sources(self, settings, target, *, now):
        """Read and rebuild the full typed original, without inserting or refreshing it."""
        from app.mixed.swing_binding import BoundSwingSources, bind_sources, policy_from_settings
        from app.options.runtime_models import RuntimeSettings

        settings = RuntimeSettings.model_validate(settings.model_dump())
        if (
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='swing_source_bindings'"
            ).fetchone()
            is None
        ):
            return None
        row = self.db.execute(
            "SELECT * FROM swing_source_bindings WHERE target_session=?", (target.isoformat(),)
        ).fetchone()
        if row is None:
            return None
        history = self.swing_snapshot(target)
        if history is None:
            raise ValueError("Original Swing history missing")
        bound = BoundSwingSources.model_validate_json(row["payload_json"])
        effective = self.policy_for(target)
        policy = policy_from_settings(
            settings, effective.candidates, carry_intent_for(effective, target)
        )
        if (
            bound.created_at > clock(now)
            or bound.target_session != target
            or fingerprint(bound) != row["payload_hash"]
            or bound != bind_sources(history, policy, created_at=bound.created_at)
        ):
            raise ValueError("Original Swing binding changed")
        return bound

    def bind_swing_sources(self, settings, *, now):
        """Create once or verify an existing session's source-binding receipt.

        This is derived collector evidence, separate from native execution state.
        Blocked receipts are retained too; neither restart nor later prices can
        rewrite the original preparation time or upgrade unknown entitlement.
        """
        from zoneinfo import ZoneInfo

        from app.mixed.swing_binding import bind_sources, policy_from_settings
        from app.options.runtime_models import RuntimeSettings

        settings = RuntimeSettings.model_validate(settings.model_dump())
        if settings.stock_policy is None or (
            settings.stock_policy.swing is None and settings.swing_policy is None
        ):
            return None
        if (
            self.policy.swing_history is None
            or settings.limits.population_id != self.policy.population_id
            or settings.stock_policy.instruments != self.policy.stocks
        ):
            raise ValueError("Matching owner and Swing history enrollment required")
        now = clock(now)
        from app.robinhood.schedule import XNYSCalendar

        cal = XNYSCalendar().calendar
        day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        target = cal.date_to_session(day, direction="next")
        if now >= cal.session_close(target).to_pydatetime():
            target = cal.next_session(target)
        history = self.swing_snapshot(target.date())
        if history is None:
            return {
                "status": "BLOCKED",
                "blockers": ["SWING_PREOPEN_HISTORY_UNAVAILABLE"],
                "target_session": target.date().isoformat(),
                "trading_ready": False,
            }
        effective = self.policy_for(target.date())
        policy = policy_from_settings(
            settings, effective.candidates, carry_intent_for(effective, target.date())
        )
        # Additive, derived evidence only. Existing history enrollment and raw
        # captures are untouched; no execution or fixture database is migrated.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS swing_source_bindings(target_session TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL)"
        )
        bound = self.load_swing_sources(settings, target.date(), now=now)
        if bound is None:
            bound = bind_sources(history, policy, created_at=now)
            self.db.execute(
                "INSERT INTO swing_source_bindings VALUES(?,?,?)",
                (target.date().isoformat(), bound.model_dump_json(), fingerprint(bound)),
            )
            self.db.commit()
        return {
            "status": bound.status,
            "blockers": list(bound.blockers),
            "target_session": bound.target_session.isoformat(),
            "created_at": bound.created_at.isoformat(),
            "binding_hash": fingerprint(bound),
            "stock_sources": len(bound.stocks),
            "option_seeds": len(bound.seeds),
            "option_batches": len(bound.batches),
            "trading_ready": False,
        }

    async def run(self, stop, *, clock_source, held_source, calendar, source_settings=None):
        while not stop.is_set():
            now = clock(clock_source())
            await self.tick(
                now=now,
                held=held_source(),
                window=calendar.current_window(now),
                source_settings=source_settings,
            )
            if source_settings is not None and self.policy.swing_history is not None:
                self.bind_swing_sources(source_settings, now=clock_source())
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.policy.poll_seconds)
            except TimeoutError:
                pass


def held_from_observer(observer):
    """Read exact current holdings and pending entries; no dependency on candidate lists."""
    report = observer.report(limit=100)
    if report.get("schema") != "mixed-portfolio-observer-v2" or report.get("status") != "OK":
        raise ValueError("Stored portfolio ownership unavailable")
    originals = [p["entry"] for p in report["positions"]]
    originals.extend(
        o["intent"] for o in report["orders"] if o["unresolved"] and o["intent"]["side"] == "BUY"
    )
    found = {}
    for entry in originals:
        raw = entry["instrument"]
        cls = OptionInstrument if "contract" in raw else StockInstrument
        i = cls.model_validate(raw)
        if i.instrument_id in found and found[i.instrument_id] != i:
            raise ValueError("Stored portfolio instrument conflict")
        found[i.instrument_id] = i
    return tuple(found.values())
