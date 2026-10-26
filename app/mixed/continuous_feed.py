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

from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import Field

from app.mixed.sources import StockCycleInput
from app.mixed.stock_models import StockInstrument
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


def planned(policy, held, now, window, *, cycle):
    """Deduplicate held/candidate contracts and shared equity reads before spending quota."""
    symbols = tuple(i.symbol for i in policy.stocks)
    if len(set(symbols)) != len(symbols) or not set(symbols) <= {"SPY", "QQQ"}:
        raise ValueError("Reviewed equity feed universe required")
    if any(i.provider != "robinhood" for i in (*policy.stocks, *policy.candidates, *held)):
        raise ValueError("Reviewed Robinhood instrument identities required")
    stock_ids = {i.instrument_id: i for i in policy.stocks}
    options = {i.instrument_id: i for i in policy.candidates}
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


def normalize(policy, schemas, captured, catalog, held, *, sequence, now):
    """A successful transport never upgrades unknown data into execution authority."""
    captured = CaptureResult.model_validate(captured.model_dump())
    if (
        captured.status != "COMPLETE"
        or captured.schemas is None
        or captured.schemas.sha256 != schemas.sha256
        or captured.plan is None
    ):
        raise ValueError("Complete original schema-bound capture required")
    if not captured.started_at <= captured.collected_at <= now:
        raise ValueError("Original capture clocks required")
    quotes, underlyings, stocks, histories, metadata = (), (), (), (), ()
    issues = []
    for call, receipt in zip(captured.plan.calls, captured.observations, strict=True):
        if (
            receipt.get("label") != call.label
            or receipt.get("tool") != call.tool
            or receipt.get("completed") is not True
        ):
            raise ValueError("Original read receipt coverage changed")
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
            histories = equity_history(*args, received_at=captured.collected_at)
        else:
            raise ValueError("Only reviewed normalized mappings may deliver runtime inputs")
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
        )
        expiries = {m.instrument.contract.expiration for m in items}
        if len(expiries) > 1:
            raise ValueError("One reviewed candidate expiry per underlying required")
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
    cycle = bool(histories) and len(stocks) == len(policy.stocks) and not issues
    return PortfolioRuntimePacket(
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
        frame=DegenFrame(
            portfolio_version="portfolio-frame-v2",
            stocks=tuple(StockCycleInput(quote=q) for q in stocks),
            quotes=candidate_quotes,
            held_quotes=held_quotes,
            underlyings=underlyings,
            histories=histories if cycle else (),
            inventories=tuple(inventories) if cycle else (),
        ),
    )


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
            if (
                self.db.execute("SELECT configuration FROM control WHERE id=1").fetchone()[0]
                != frozen
            ):
                raise ValueError("Frozen feed configuration changed")
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

    async def tick(self, *, now, held=(), window=None, reader=collect):
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
        plan, catalog = planned(self.policy, held, now, window, cycle=cycle)
        used = self.db.execute(
            "SELECT COALESCE(SUM(calls),0) FROM attempts WHERE started_at>?",
            ((now - timedelta(minutes=1)).isoformat(),),
        ).fetchone()[0]
        if used + len(plan.calls) > self.policy.calls_per_minute:
            return {"status": "RATE_LIMITED"}
        sequence = (last["sequence"] if last else 0) + 1
        self.db.execute(
            "INSERT INTO attempts VALUES(?,?,?,'STARTED',?,NULL,NULL,NULL)",
            (sequence, now.isoformat(), len(plan.calls), fingerprint(plan)),
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
            packet = normalize(
                self.policy,
                self.schemas,
                captured,
                catalog,
                held,
                sequence=sequence,
                now=captured.collected_at,
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

    async def run(self, stop, *, clock_source, held_source, calendar):
        while not stop.is_set():
            now = clock(clock_source())
            await self.tick(now=now, held=held_source(), window=calendar.current_window(now))
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
