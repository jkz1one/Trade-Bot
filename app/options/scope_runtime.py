"""Delivered Scope runtime evidence and durable, single-consumption watch instructions."""

import asyncio
import json
from types import SimpleNamespace

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.runtime_models import (
    MixedRuntimePacket,
    PortfolioRuntimePacket,
    ScopeRuntimePacket,
)
from app.options.scope_market_tape import ScopeTapePolicy, validate_scope_event
from app.options.scope_replay import ScopeReplayStep, _perform


def enrollment(coordinator, policy):
    if (coordinator.scope_policy is not None) != (policy.scope_inputs is not None):
        raise ValueError("Matching Scope runtime/coordinator enrollment required")


def validate_packet(c, packet):
    if not isinstance(packet, ScopeRuntimePacket):
        raise ValueError("Explicit Scope runtime packet required")  # noqa: TRY004
    if len({q.instrument.instrument_id for q in packet.frame.quotes}) != len(
        packet.frame.quotes
    ) or len({u.symbol for u in packet.frame.underlyings}) != len(packet.frame.underlyings):
        raise ValueError("Unique runtime quote identities required")
    item = packet.frame.scope
    if item is None:
        return
    if item.frame.session is None:
        raise ValueError("Original reviewed Scope session required")
    header = SimpleNamespace(
        scope=ScopeTapePolicy(watch=c.scope_policy.watch, session=item.frame.session),
        limits=c.engine.limits,
    )
    validate_scope_event(header, packet)


def protection(frame):
    if frame.portfolio_version is not None:
        from app.mixed.quote_fills import _unique

        quotes = (*frame.quotes, *frame.held_quotes)
        underlyings = (*frame.underlyings, *frame.held_underlyings)
        if frame.scope is not None:
            quotes += (frame.scope.frame.quote,) if frame.scope.frame.quote is not None else ()
            underlyings += (frame.scope.underlying,)
        return tuple(_unique(quotes, lambda q: q.instrument.instrument_id).values()), tuple(
            _unique(underlyings, lambda q: q.symbol).values()
        )
    if frame.scope is None:
        return frame.quotes, frame.underlyings
    quotes = {q.instrument.instrument_id: q for q in frame.quotes}
    underlyings = {u.symbol: u for u in frame.underlyings}
    if frame.scope is not None:
        if frame.scope.frame.quote is not None:
            q = frame.scope.frame.quote
            quotes[q.instrument.instrument_id] = q
        u = frame.scope.underlying
        underlyings[u.symbol] = u
    return tuple(quotes.values()), tuple(underlyings.values())


class ScopeRuntimeInputs:
    def __init__(self, runtime):
        self.r = runtime
        self.latest = None
        with self.r.c.engine.journal.write() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_scope_runtime_inputs("
                "sequence INTEGER PRIMARY KEY,packet_hash TEXT NOT NULL,packet_json TEXT NOT NULL,"
                "accepted_at TEXT NOT NULL,action_key TEXT UNIQUE,status TEXT NOT NULL,"
                "result_json TEXT)"
            )
            pending = db.execute(
                "SELECT 1 FROM execution_option_scope_runtime_inputs WHERE status='PENDING'"
            ).fetchone()
            if pending:
                self.r.c.engine._halt(db, "SCOPE_RUNTIME_ACTION_INTERRUPTED", self.r.c.now())
                db.execute(
                    "UPDATE execution_option_scope_runtime_inputs SET status='INTERRUPTED' "
                    "WHERE status='PENDING'"
                )

    def accept(self, packet, at):
        """Persist the receipt before any suspension; never replay a lost prefix."""
        validate_packet(self.r.c, packet)
        digest = fingerprint(packet)
        with self.r.c.engine.journal.write() as db:
            state = self.r._bound(db)
            item = packet.frame.scope
            if item is not None:
                watch = db.execute(
                    "SELECT record_json FROM execution_option_scope_watches WHERE play_key=?",
                    (item.play_key,),
                ).fetchone()
                if watch is not None:
                    from app.options.scope import ScopeSession

                    original = ScopeSession.model_validate(
                        json.loads(watch[0])["locked_frame"]["session"]
                    )
                    if item.frame.session != original:
                        raise ValueError("Scope runtime changed the original session or deadlines")
            prior = db.execute(
                "SELECT * FROM execution_option_scope_runtime_inputs WHERE sequence=?",
                (packet.sequence,),
            ).fetchone()
            if prior:
                if prior["packet_hash"] != digest or prior["status"] in {"PENDING", "INTERRUPTED"}:
                    raise ValueError("Scope runtime input changed or was interrupted")
            else:
                if packet.sequence <= state["feed_sequence"] or (
                    self.r.c.engine.portfolio_policy is None
                    and packet.sequence != state["feed_sequence"] + 1
                ):
                    raise ValueError("Scope runtime input sequence gap")
                if (
                    packet.action
                    and db.execute(
                        "SELECT 1 FROM execution_option_scope_runtime_inputs WHERE action_key=?",
                        (packet.action.key,),
                    ).fetchone()
                ):
                    raise ValueError("Scope runtime watch action key reused")
                db.execute(
                    "INSERT INTO execution_option_scope_runtime_inputs VALUES(?,?,?,?,?,?,NULL)",
                    (
                        packet.sequence,
                        digest,
                        packet.model_dump_json(),
                        at.isoformat(),
                        packet.action.key if packet.action else None,
                        "PENDING" if packet.action else "OBSERVED",
                    ),
                )
                db.execute(
                    "UPDATE execution_option_runtime SET feed_sequence=?,frame_hash=?,"
                    "frame_json=?,feed_recorded_at=? WHERE id=1",
                    (
                        packet.sequence,
                        digest,
                        packet.frame.model_dump_json(),
                        packet.recorded_at.isoformat(),
                    ),
                )
        self.latest = packet

    def apply(self, packet, issue):
        if packet.action is None:
            return
        c, action = self.r.c, packet.action
        with c.engine.journal.read() as db:
            row = db.execute(
                "SELECT * FROM execution_option_scope_runtime_inputs WHERE sequence=?",
                (packet.sequence,),
            ).fetchone()
            if row["status"] != "PENDING":
                return
            revision = c.engine.journal.revision(db)
        now = c.now()
        item = packet.frame.scope
        step = ScopeReplayStep(
            key=action.key,
            kind=action.kind,
            at=now,
            play_key=action.play_key,
            choice=action.choice,
            frame=item.frame if item and action.kind != "OBSERVE_QUOTE" else None,
            context=item.context if item and action.kind in {"CALL", "OBSERVE_ARMING"} else None,
            underlying=item.underlying if item and action.kind == "OBSERVE_QUOTE" else None,
        )
        try:
            if issue or not self.r.running or (self.r.stop and self.r.stop.is_set()):
                raise ExecutionBlocked(issue or "OPTION_RUNTIME_STOP_REQUESTED")
            if (
                not 0
                <= (now - packet.recorded_at).total_seconds()
                < self.r.policy.feed_max_age_seconds
            ):
                raise ExecutionBlocked("SCOPE_RUNTIME_RECEIPT_EXPIRED")
            receipt = _perform(c.scope_book, step, revision)
            result = {"status": "RECORDED", "receipt": receipt}
        except ExecutionBlocked as exc:
            result = {"status": "REJECTED", "reason": str(exc)}
        result.update(expected_revision=revision, step=step.model_dump(mode="json"))
        with c.engine.journal.write() as db:
            self.r._bound(db)
            db.execute(
                "UPDATE execution_option_scope_runtime_inputs SET status=?,result_json=? "
                "WHERE sequence=? AND status='PENDING'",
                (result["status"], json.dumps(result, sort_keys=True), packet.sequence),
            )

    def expire(self):
        """Original unfilled watch cutoffs advance even when the feed is absent."""
        from datetime import datetime

        c, now = self.r.c, self.r.c.now()
        with c.engine.journal.read() as db:
            rows = db.execute(
                "SELECT record_json FROM execution_option_scope_watches WHERE active_lock=1"
            ).fetchall()
        for row in rows:
            record = json.loads(row[0])
            cutoff = datetime.fromisoformat(record["locked_frame"]["session"]["entry_cutoff_at"])
            if record.get("native_client_id") or now < cutoff:
                continue
            with c.engine.journal.read() as db:
                revision = c.engine.journal.revision(db)
            c.scope_book.advance(
                "runtime-expire:"
                + fingerprint({"play": record["play_key"], "cutoff": cutoff.isoformat()}),
                record["play_key"],
                expected_revision=revision,
                now=now,
            )

    async def fresh(self, play_key):
        """Only delivered evidence, never a reread that skips a pending watch action."""
        pending = self.r._scope_tick
        while pending is not None:
            if not await asyncio.shield(pending):
                raise ExecutionBlocked("SCOPE_RUNTIME_PROTECTION_TICK_INCOMPLETE")
            if self.r._scope_tick is pending:
                break
            pending = self.r._scope_tick
        packet = self.latest
        if (
            packet is None
            or packet.frame.scope is None
            or packet.frame.scope.play_key != play_key
            or not self.r.running
            or (self.r.stop and self.r.stop.is_set())
            or not 0
            <= (self.r.c.now() - packet.recorded_at).total_seconds()
            < self.r.policy.feed_max_age_seconds
        ):
            raise ExecutionBlocked("FRESH_DELIVERED_SCOPE_RUNTIME_INPUT_REQUIRED")
        with self.r.c.engine.journal.read() as db:
            state = self.r._bound(db)
            row = db.execute(
                "SELECT status,packet_hash FROM execution_option_scope_runtime_inputs WHERE sequence=?",
                (packet.sequence,),
            ).fetchone()
            if (
                state["status"] != "RUNNING"
                or state["feed_sequence"] != packet.sequence
                or row is None
                or row["status"] not in {"OBSERVED", "RECORDED"}
                or row["packet_hash"] != fingerprint(packet)
                or self.r.c.engine._control(db)["halted"]
            ):
                raise ExecutionBlocked("DELIVERED_SCOPE_RUNTIME_RECEIPT_NOT_READY")
        return packet.frame.scope


def stored_inputs(db, now):
    """Reconstruct portable runtime delivery/action links without any runtime authority."""
    from datetime import datetime

    from app.options.models import OptionLimits
    from app.options.scope_arbitration import configuration

    config = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    limits = OptionLimits.model_validate(config["limits"])
    c = SimpleNamespace(scope_policy=configuration(db), engine=SimpleNamespace(limits=limits))
    packet_type = ScopeRuntimePacket
    if config["policy"].get("mixed_owner") is not None:
        runtime = json.loads(
            db.execute("SELECT config_json FROM execution_option_runtime WHERE id=1").fetchone()[0]
        )
        if runtime["runtime"].get("mixed_inputs") != "mixed-runtime-inputs-v1":
            raise ValueError("Stored mixed Scope runtime enrollment required")
        packet_type = MixedRuntimePacket
    portfolio = bool((config["policy"].get("mixed_owner") or {}).get("portfolio"))
    if portfolio:
        packet_type = PortfolioRuntimePacket
    from app.mixed.runtime import delivery_sequence_valid

    statuses, actions, previous_at, previous_sequence = {}, [], None, 0
    for row in db.execute("SELECT * FROM execution_option_scope_runtime_inputs ORDER BY sequence"):
        packet = packet_type.model_validate_json(row["packet_json"])
        validate_packet(c, packet)
        accepted = datetime.fromisoformat(row["accepted_at"])
        if (
            row["sequence"] != packet.sequence
            or not delivery_sequence_valid(
                db, packet.sequence, previous_sequence, portfolio=portfolio
            )
            or packet.population_id != limits.population_id
            or fingerprint(packet) != row["packet_hash"]
            or not packet.recorded_at <= accepted <= now
            or (previous_at is not None and packet.recorded_at < previous_at)
            or row["action_key"] != (packet.action.key if packet.action else None)
            or row["status"] not in {"OBSERVED", "PENDING", "INTERRUPTED", "RECORDED", "REJECTED"}
            or (packet.action is None) != (row["status"] == "OBSERVED")
        ):
            raise ValueError("Scope runtime delivery binding changed")
        previous_at = packet.recorded_at
        previous_sequence = packet.sequence
        status = row["status"]
        statuses[status] = statuses.get(status, 0) + 1
        if status in {"RECORDED", "REJECTED"}:
            result = json.loads(row["result_json"])
            step = ScopeReplayStep.model_validate(result["step"])
            a, item = packet.action, packet.frame.scope
            if (
                result["status"] != status
                or not accepted <= step.at <= now
                or (step.key, step.kind, step.play_key, step.choice)
                != (a.key, a.kind, a.play_key, a.choice)
                or step.frame != (item.frame if item and a.kind != "OBSERVE_QUOTE" else None)
                or step.context
                != (item.context if item and a.kind in {"CALL", "OBSERVE_ARMING"} else None)
                or step.underlying
                != (item.underlying if item and a.kind == "OBSERVE_QUOTE" else None)
            ):
                raise ValueError("Scope runtime action binding changed")
            if status == "RECORDED":
                native = db.execute(
                    "SELECT result_json,request_hash FROM execution_option_scope_watch_actions WHERE action_key=?",
                    (a.key,),
                ).fetchone()
                from app.options.scope_watch import _Action

                request = {
                    "kind": step.kind,
                    "action": _Action(key=step.key, expected_revision=result["expected_revision"]),
                    "now": step.at,
                }
                if step.kind == "CALL":
                    request.update(choice=step.choice, frame=step.frame, context=step.context)
                else:
                    request["play_key"] = step.play_key
                    if step.kind == "OBSERVE_QUOTE":
                        request["underlying"] = step.underlying
                    else:
                        request["frame"] = step.frame
                        if step.kind == "OBSERVE_ARMING":
                            request["context"] = step.context
                if (
                    native is None
                    or json.loads(native[0]) != result["receipt"]
                    or fingerprint(request) != native[1]
                ):
                    raise ValueError("Scope runtime native receipt changed")
            actions.append({"sequence": packet.sequence, "key": a.key, "status": status})
        elif row["result_json"] is not None:
            raise ValueError("Uncompleted Scope runtime input has a result")
    return {"statuses": statuses, "actions": actions, "execution_authority": False}
