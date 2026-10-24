"""Explicit delivered mixed runtime evidence; no provider or model authority."""

import asyncio
import json
from datetime import datetime

from app.execution.engine import ExecutionBlocked
from app.mixed.sources import StockSwingSource, geometry
from app.options.engine import exact, fingerprint
from app.options.governor import _fresh
from app.options.runtime_models import MixedRuntimePacket


def enrollment(c, policy):
    if (c.engine.policy.mixed_owner is not None) != (policy.mixed_inputs is not None) or (
        (c.stock_policy is not None) != (policy.mixed_inputs is not None)
    ):
        raise ValueError("Mixed runtime requires complete explicit enrollment")


def validate_packet(c, packet):
    if not isinstance(packet, MixedRuntimePacket):
        raise ValueError("Explicit mixed runtime packet required")  # noqa: TRY004
    if c.scope_policy is None and (packet.frame.scope is not None or packet.action is not None):
        raise ValueError("Scope inputs require explicit native Scope enrollment")
    instruments = c.stock_policy.instruments
    quotes = [x.quote for x in packet.frame.stocks]
    if len({q.instrument.instrument_id for q in quotes}) != len(quotes) or any(
        q.instrument not in instruments for q in quotes
    ):
        raise ValueError("Exact unique frozen stock identities required")
    if packet.kind == "CYCLE" and {q.instrument.instrument_id for q in quotes} != {
        i.instrument_id for i in instruments
    }:
        raise ValueError("Complete mixed cycle stock coverage required")
    limits = c.engine.policy.mixed_owner.stocks
    for value in (
        *packet.frame.histories,
        *packet.frame.inventories,
        *packet.frame.quotes,
        *packet.frame.underlyings,
    ):
        if not value.source_at <= value.received_at <= packet.recorded_at:
            raise ValueError("Mixed inputs must be available at recorded delivery")
        if hasattr(value, "bars") and any(b.ends_at > value.source_at for b in value.bars):
            raise ValueError("Mixed inputs require completed recorded bars")
    for item in packet.frame.stocks:
        q = item.quote
        if (
            q.source != limits.quote_source
            or not q.source_at <= q.received_at <= packet.recorded_at
        ):
            raise ValueError("Available original stock quote clocks required")
        if item.swing is not None:
            if c.stock_policy.swing is None or item.swing.instrument != q.instrument:
                raise ValueError("Original enrolled stock source required")
            if item.swing.created_at > packet.recorded_at:
                raise ValueError("Stock source unavailable at delivery")
        if (
            item.catalyst is not None
            and not item.catalyst.source_at <= item.catalyst.received_at <= packet.recorded_at
        ):
            raise ValueError("Stock catalyst unavailable at delivery")


@exact
def observe_quotes(c, quotes):
    """Retire locked unfilled stock sources on delivered executable observations."""
    if c.stock_policy.swing is None or not quotes:
        return
    from app.mixed.selection import retire

    at = c.now()
    window = c.engine.calendar.current_window(at)
    if window is None:
        return
    limits = c.engine.policy.mixed_owner.stocks
    with c.engine.journal.write() as db:
        c._bound(db)
        for q in quotes:
            if (
                q.instrument not in c.stock_policy.instruments
                or q.source != limits.quote_source
                or not q.complete
                or q.entitlement != "REALTIME"
                or not _fresh(
                    q.source_at,
                    q.received_at,
                    at,
                    limits.quote_max_age_seconds,
                    limits.max_receive_lag_seconds,
                )
            ):
                continue
            row = db.execute(
                "SELECT source_hash,source_json FROM execution_mixed_stock_sources WHERE session=? AND symbol=?",
                (window.session_date, q.instrument.symbol),
            ).fetchone()
            if row is None:
                continue
            source = StockSwingSource.model_validate_json(row["source_json"])
            if fingerprint(source) != row["source_hash"] or source.instrument != q.instrument:
                raise ExecutionBlocked("STOCK_ORIGINAL_SOURCE_CHANGED")
            for family in c.stock_policy.swing.families:
                reference, stop, reasons = geometry(source, family, c.stock_policy.swing)
                if not reasons and (q.bid <= stop or q.bid >= 2 * reference - stop):
                    retire(
                        c.engine,
                        db,
                        row["source_hash"],
                        family,
                        "INVALIDATED" if q.bid <= stop else "TARGET_CONSUMED",
                        q.model_dump(mode="json"),
                        at,
                    )


class MixedRuntimeInputs:
    def __init__(self, runtime):
        self.r = runtime
        self.latest = None
        with runtime.c.engine.journal.write() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_mixed_runtime_inputs(sequence INTEGER PRIMARY KEY,packet_hash TEXT NOT NULL,packet_json TEXT NOT NULL,accepted_at TEXT NOT NULL,status TEXT NOT NULL)"
            )
            if db.execute(
                "SELECT 1 FROM execution_mixed_runtime_inputs WHERE status='ACCEPTED'"
            ).fetchone():
                runtime.c.engine._halt(db, "MIXED_RUNTIME_DELIVERY_INTERRUPTED", runtime.c.now())
                db.execute(
                    "UPDATE execution_mixed_runtime_inputs SET status='INTERRUPTED' WHERE status='ACCEPTED'"
                )

    def accept(self, packet, at):
        validate_packet(self.r.c, packet)
        digest = fingerprint(packet)
        with self.r.c.engine.journal.write() as db:
            self.r._bound(db)
            prior = db.execute(
                "SELECT packet_hash,status FROM execution_mixed_runtime_inputs WHERE sequence=?",
                (packet.sequence,),
            ).fetchone()
            if prior is not None:
                if prior["packet_hash"] != digest or prior["status"] != "DELIVERED":
                    raise ValueError("Mixed runtime delivery changed or interrupted")
            else:
                previous = (
                    db.execute(
                        "SELECT MAX(sequence) FROM execution_mixed_runtime_inputs"
                    ).fetchone()[0]
                    or 0
                )
                if packet.sequence != previous + 1:
                    raise ValueError("Mixed runtime delivery sequence gap")
                db.execute(
                    "INSERT INTO execution_mixed_runtime_inputs VALUES(?,?,?,?,'ACCEPTED')",
                    (packet.sequence, digest, packet.model_dump_json(), at.isoformat()),
                )
        self.latest = packet

    def complete(self, packet, issue):
        with self.r.c.engine.journal.write() as db:
            state = self.r._bound(db)
            if state["feed_sequence"] != packet.sequence or state["frame_hash"] != fingerprint(
                packet
            ):
                raise ExecutionBlocked("MIXED_RUNTIME_DELIVERY_SUPERSEDED")
            db.execute(
                "UPDATE execution_mixed_runtime_inputs SET status=? WHERE sequence=? AND status='ACCEPTED'",
                ("BLOCKED" if issue else "DELIVERED", packet.sequence),
            )

    async def fresh(self, instrument):
        pending = self.r._scope_tick
        while pending is not None:
            if not await asyncio.shield(pending):
                raise ExecutionBlocked("MIXED_RUNTIME_PROTECTION_TICK_INCOMPLETE")
            if self.r._scope_tick is pending:
                break
            pending = self.r._scope_tick
        packet = self.latest
        if (
            packet is None
            or not self.r.running
            or (self.r.stop and self.r.stop.is_set())
            or not 0
            <= (self.r.c.now() - packet.recorded_at).total_seconds()
            < self.r.policy.feed_max_age_seconds
        ):
            raise ExecutionBlocked("FRESH_DELIVERED_STOCK_INPUT_REQUIRED")
        with self.r.c.engine.journal.read() as db:
            state = self.r._bound(db)
            row = db.execute(
                "SELECT packet_hash,status FROM execution_mixed_runtime_inputs WHERE sequence=?",
                (packet.sequence,),
            ).fetchone()
            if (
                state["status"] != "RUNNING"
                or state["feed_sequence"] != packet.sequence
                or row is None
                or row["status"] != "DELIVERED"
                or row["packet_hash"] != fingerprint(packet)
                or self.r.c.engine._control(db)["halted"]
            ):
                raise ExecutionBlocked("DELIVERED_STOCK_RECEIPT_NOT_READY")
            if packet.action is not None:
                scope = db.execute(
                    "SELECT status FROM execution_option_scope_runtime_inputs WHERE sequence=?",
                    (packet.sequence,),
                ).fetchone()
                if scope is None or scope[0] != "RECORDED":
                    raise ExecutionBlocked("SCOPE_ACTION_NOT_COMPLETED")
        quotes = [x.quote for x in packet.frame.stocks if x.quote.instrument == instrument]
        if len(quotes) != 1:
            raise ExecutionBlocked("EXACT_DELIVERED_STOCK_QUOTE_REQUIRED")
        return quotes[0]


def stored_inputs(db, now):
    """Verify the complete delivered prefix without feed, runtime or order authority."""
    from types import SimpleNamespace

    from app.mixed.selection import configuration
    from app.options.lifecycle import OptionExecutionPolicy

    config = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    c = SimpleNamespace(
        stock_policy=configuration(db),
        engine=SimpleNamespace(policy=OptionExecutionPolicy.model_validate(config["policy"])),
        scope_policy=None,
    )
    from app.options.scope_arbitration import configuration as scope_configuration

    if c.engine.policy.scope_arbitration is not None:
        c.scope_policy = scope_configuration(db)
    state = db.execute("SELECT * FROM execution_option_runtime WHERE id=1").fetchone()
    if (
        state is None
        or c.stock_policy is None
        or c.engine.policy.mixed_owner is None
        or json.loads(state["config_json"])["runtime"].get("mixed_inputs")
        != "mixed-runtime-inputs-v1"
    ):
        raise ValueError("Frozen mixed runtime delivery enrollment required")
    statuses, last = {}, None
    for sequence, row in enumerate(
        db.execute("SELECT * FROM execution_mixed_runtime_inputs ORDER BY sequence"), 1
    ):
        packet = MixedRuntimePacket.model_validate_json(row["packet_json"])
        validate_packet(c, packet)
        accepted = datetime.fromisoformat(row["accepted_at"])
        if (
            row["sequence"] != sequence
            or packet.sequence != sequence
            or packet.population_id != config["limits"]["population_id"]
            or fingerprint(packet) != row["packet_hash"]
            or not packet.recorded_at <= accepted <= now
            or (last and packet.recorded_at < last.recorded_at)
            or row["status"] not in {"ACCEPTED", "DELIVERED", "BLOCKED", "INTERRUPTED"}
        ):
            raise ValueError("Mixed runtime delivery evidence changed")
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        last = packet
    if last is not None:
        delivered = state["feed_sequence"]
        if delivered != last.sequence and not (
            delivered + 1 == last.sequence and row["status"] in {"ACCEPTED", "INTERRUPTED"}
        ):
            raise ValueError("Mixed runtime delivery prefix changed")
        delivered_row = db.execute(
            "SELECT packet_hash FROM execution_mixed_runtime_inputs WHERE sequence=?", (delivered,)
        ).fetchone()
        if delivered and (delivered_row is None or delivered_row[0] != state["frame_hash"]):
            raise ValueError("Mixed runtime delivered hash changed")
    return {
        "statuses": statuses,
        "latest_sequence": last.sequence if last else 0,
        "execution_authority": False,
    }
