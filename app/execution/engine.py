"""Deterministic, fixture-only execution rehearsal; deliberately no LIVE adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_DOWN
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain.models import AccountState, Action, MarketPacket, Position, TradeDecision
from app.execution.fixture import LocalFixtureVenue
from app.execution.journal import ExecutionJournal
from app.execution.models import (
    SHARE_STEP,
    TERMINAL,
    ZERO,
    Intent,
    Ledger,
    Observation,
    OrderState,
    PositionManagement,
    Snapshot,
)
from app.execution.supervision import assess_position
from app.risk.governor import govern
from app.risk.policy import TIERS
from app.robinhood.schedule import XNYSCalendar


class ExecutionBlocked(RuntimeError):
    pass


def _clock(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Execution clock must be timezone-aware")


class ExecutionEngine:
    def __init__(self, path, settings: Settings, *, calendar=None):
        if settings.normalized_mode != "PAPER" or settings.live_enabled:
            raise ValueError("Execution rehearsal requires PAPER with LIVE disabled")
        self.settings = Settings.model_validate(settings.model_dump())
        self.calendar = calendar if calendar is not None else XNYSCalendar()
        self.journal = ExecutionJournal(
            path,
            {
                "capital": str(settings.starting_capital),
                "symbols": settings.initial_symbols,
                "risk_settings": {
                    k: str(getattr(settings, k))
                    for k in (
                        "min_order_notional",
                        "quote_max_age_seconds",
                        "max_daily_entries",
                        "exit_cooldown_minutes",
                    )
                },
                "risk_policy_hash": hashlib.sha256(
                    json.dumps(
                        [(str(bound), asdict(policy)) for bound, policy in TIERS],
                        sort_keys=True,
                        default=str,
                    ).encode()
                ).hexdigest(),
            },
        )
        with self.journal.write() as db:
            interrupted = db.execute(
                "SELECT client_id FROM execution_orders WHERE status='SUBMITTING'"
            ).fetchall()
            if interrupted:
                db.execute("UPDATE execution_orders SET status='UNKNOWN' WHERE status='SUBMITTING'")
                db.execute(
                    "UPDATE execution_control SET halted=1,halt_reason='INTERRUPTED_EXECUTION_ATTEMPT' WHERE id=1"
                )
                # Startup cannot establish acceptance. Keep reservations and require evidence.
                for row in interrupted:
                    self.journal.event(
                        db, datetime.now().astimezone(), "INTERRUPTED_ATTEMPT", {}, row[0]
                    )

    @staticmethod
    def _control(db):
        return db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()

    @staticmethod
    def _fresh(snapshot, now, maximum_age):
        age = (now - snapshot.captured_at).total_seconds()
        return snapshot.complete and 0 <= age <= maximum_age

    def _ready(self, control, now):
        if control["halted"]:
            raise ExecutionBlocked("EXECUTION_HALTED")
        if not control["snapshot_json"] or json.loads(control["issues_json"]):
            raise ExecutionBlocked("RECONCILIATION_REQUIRED")
        snapshot = Snapshot.model_validate_json(control["snapshot_json"])
        if not self._fresh(snapshot, now, self.settings.quote_max_age_seconds):
            raise ExecutionBlocked("STALE_EXECUTION_SNAPSHOT")
        return snapshot

    def _govern(self, decision, packet, state, snapshot, now):
        position = state.position
        if position:
            mark = next(
                (c.quote.bid for c in packet.candidates if c.quote.symbol == position.symbol),
                None,
            )
            if mark is None:
                raise ExecutionBlocked("POSITION_MARK_MISSING")
            position = position.model_copy(update={"current_price": mark})
        equity = state.cash + (position.market_value if position else ZERO)
        account = AccountState(
            equity=equity,
            cash=state.cash,
            buying_power=min(state.cash, snapshot.safe_buying_power),
            high_watermark=max(state.high_watermark, equity),
            realized_pnl=state.realized_pnl - state.fees_paid,
            position=position,
        )
        # Proposal account values cannot grant authority: use reconciled journal truth.
        governed_packet = packet.model_copy(update={"account": account})
        today = now.astimezone(ZoneInfo("America/New_York")).date()
        entries = sum(
            t.astimezone(ZoneInfo("America/New_York")).date() == today for t in state.entry_times
        )
        cooldown = state.last_close_at is not None and now < state.last_close_at + timedelta(
            minutes=self.settings.exit_cooldown_minutes
        )
        risk = govern(
            decision,
            governed_packet,
            self.settings,
            daily_entries=entries,
            in_exit_cooldown=cooldown,
            now=now,
        )
        return risk, governed_packet

    @staticmethod
    def _entry_management(row):
        intent = Intent.model_validate_json(row["intent_json"])
        approval = json.loads(row["approval_json"])
        decision = TradeDecision.model_validate(approval["decision"])
        packet = MarketPacket.model_validate(approval["packet"])
        if (
            intent.side != "BUY"
            or decision.action != Action.OPEN_LONG
            or not approval["risk"]["approved"]
        ):
            raise ValueError("Missing approved entry lineage")
        session = packet.session_context["session_date"] if packet.session_context else None
        if (
            session
            != intent.prepared_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        ):
            raise ValueError("Missing original entry session")
        return PositionManagement(
            entry_client_id=intent.client_id,
            session_date=session,
            horizon=decision.horizon,
            hold_overnight=decision.hold_overnight,
        )

    def _position_management(self, db, state):
        if state.management:
            return state.management
        # Older rehearsal journals already saved complete governor-approved entry inputs.
        # Recover only the most recent actually filled BUY, never infer overnight permission.
        for row in db.execute("SELECT * FROM execution_orders ORDER BY rowid DESC"):
            intent = Intent.model_validate_json(row["intent_json"])
            if (
                intent.side != "BUY"
                or not db.execute(
                    "SELECT 1 FROM execution_fills WHERE client_id=? LIMIT 1", (intent.client_id,)
                ).fetchone()
            ):
                continue
            if (
                intent.symbol != state.position.symbol
                or intent.original_invalidation != state.position.original_invalidation
            ):
                raise ValueError("Entry lineage does not match owned position")
            return self._entry_management(row)
        raise ValueError("No filled entry lineage for owned position")

    def _supervise(self, db, control, state, packet, now):
        if state.position is None:
            return {"status": "FLAT", "exit_reason": None}
        try:
            window = self.calendar.current_window(now)
            calendar_failed = False
        except Exception:  # noqa: BLE001 - failed risk supervision must latch a halt.
            window, calendar_failed = None, True
        try:
            management = self._position_management(db, state)
            updated, quote = assess_position(
                state.position,
                management,
                packet,
                window,
                now,
                self.settings.quote_max_age_seconds,
            )
        except (ValueError, KeyError, ArithmeticError):
            updated, quote = None, None
        issue = updated.supervision_issue if updated else "POSITION_MANAGEMENT_NOT_PROVEN"
        if calendar_failed:
            issue = "CALENDAR_FAILURE"
        if not control["snapshot_json"] or json.loads(control["issues_json"]):
            issue = "RECONCILIATION_REQUIRED"
        elif not self._fresh(
            Snapshot.model_validate_json(control["snapshot_json"]),
            now,
            self.settings.quote_max_age_seconds,
        ):
            issue = "STALE_EXECUTION_SNAPSHOT"
        active = db.execute("SELECT * FROM execution_orders WHERE active_lock=1").fetchone()
        pending_exit = False
        if updated and updated.exit_reason and active:
            pending_exit = Intent.model_validate_json(active["intent_json"]).side == "SELL"
            if not pending_exit:
                issue = "ENTRY_REMAINDER_UNRESOLVED"
        if updated:
            updated = updated.model_copy(update={"supervision_issue": issue})
            changes = {"management": updated}
            if quote is not None and issue is None:
                position = state.position.model_copy(update={"current_price": quote.bid})
                changes.update(
                    position=position,
                    high_watermark=max(state.high_watermark, state.cash + position.market_value),
                )
            state = state.model_copy(update=changes)
            db.execute(
                "UPDATE execution_control SET ledger_json=? WHERE id=1", (state.model_dump_json(),)
            )
        if issue:
            db.execute(
                "UPDATE execution_control SET halted=1,halt_reason=COALESCE(halt_reason,'POSITION_SUPERVISION_BLOCKED') WHERE id=1"
            )
        result = {
            "status": "BLOCKED"
            if issue
            else "EXIT_PENDING"
            if pending_exit
            else "EXIT_REQUIRED"
            if updated.exit_reason
            else "HOLD_POSITION",
            "exit_reason": updated.exit_reason if updated else None,
            "issue": issue,
            "entry_client_id": updated.entry_client_id if updated else None,
            "execution_halted": bool(control["halted"]) or issue is not None,
        }
        self.journal.event(db, now, "POSITION_SUPERVISED", result)
        return result

    def supervise(self, packet: MarketPacket, *, now):
        """Observe owned risk without model judgment, order submission or broker reads."""
        _clock(now)
        packet = MarketPacket.model_validate(packet.model_dump())
        with self.journal.write() as db:
            control = self._control(db)
            return self._supervise(
                db, control, Ledger.model_validate_json(control["ledger_json"]), packet, now
            )

    def prepare_protective_exit(self, packet: MarketPacket, *, now):
        assessment = self.supervise(packet, now=now)
        if assessment["status"] in {"FLAT", "HOLD_POSITION"}:
            return None
        if assessment["status"] == "BLOCKED" or assessment["execution_halted"]:
            raise ExecutionBlocked(assessment.get("issue") or "EXECUTION_HALTED")
        with self.journal.read() as db:
            active = db.execute("SELECT * FROM execution_orders WHERE active_lock=1").fetchone()
            if active:
                intent = Intent.model_validate_json(active["intent_json"])
                if intent.side != "SELL":
                    raise ExecutionBlocked("ENTRY_REMAINDER_UNRESOLVED")
                return intent
            state = Ledger.model_validate_json(self._control(db)["ledger_json"])
            prefix = (
                "protective-" + hashlib.sha256(assessment["entry_client_id"].encode()).hexdigest()
            )
            attempts = sum(
                row[0].startswith(prefix + ":")
                for row in db.execute("SELECT source_key FROM execution_orders")
            )
        decision = TradeDecision(
            action=Action.CLOSE,
            symbol=state.position.symbol,
            confidence=0,
            setup_quality=0,
            thesis="Deterministic protective exit",
            invalidation_reason=assessment["exit_reason"],
            why_now="Persisted position supervision requires an exit",
        )
        # A new suffix is allowed only after the prior order is definitively terminal.
        return self.prepare(prefix + ":" + str(attempts), decision, packet, now=now)

    def prepare(self, source_key: str, decision: TradeDecision, packet: MarketPacket, *, now):
        _clock(now)
        if not source_key.strip() or len(source_key) > 128:
            raise ValueError("A bounded stable decision source key is required")
        # Revalidate even if a caller has used model_copy/model_construct.
        decision = TradeDecision.model_validate(decision.model_dump())
        packet = MarketPacket.model_validate(packet.model_dump())
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "decision": decision.model_dump(mode="json"),
                    "packet": packet.model_dump(mode="json"),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with self.journal.write() as db:
            old = db.execute(
                "SELECT * FROM execution_orders WHERE source_key=?", (source_key,)
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ExecutionBlocked("SOURCE_KEY_CONTENT_CONFLICT")
                return Intent.model_validate_json(old["intent_json"])
            if decision.action == Action.HOLD:
                control = self._control(db)
                state = Ledger.model_validate_json(control["ledger_json"])
                if state.position:
                    self._supervise(db, control, state, packet, now)
                self.journal.event(
                    db,
                    now,
                    "HOLD",
                    {"source_key": source_key, "decision": decision.model_dump(mode="json")},
                )
                return None
            control = self._control(db)
            snapshot = self._ready(control, now)
            if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
                raise ExecutionBlocked("ORDER_ALREADY_IN_FLIGHT")
            window = self.calendar.current_window(now)
            if window is None:
                raise ExecutionBlocked("MARKET_CLOSED")
            if (
                packet.as_of.tzinfo is None
                or not 0
                <= (now - packet.as_of).total_seconds()
                <= self.settings.quote_max_age_seconds
            ):
                raise ExecutionBlocked("INVALID_PACKET_TIME")
            if decision.symbol not in self.settings.initial_symbols:
                raise ExecutionBlocked("SYMBOL_OUTSIDE_CONFIGURED_UNIVERSE")
            state = Ledger.model_validate_json(control["ledger_json"])
            candidate = next(
                (c for c in packet.candidates if c.quote.symbol == decision.symbol), None
            )
            risk, governed_packet = self._govern(decision, packet, state, snapshot, now)
            governed_packet = governed_packet.model_copy(
                update={"session_context": window.context()}
            )
            position = governed_packet.account.position
            if not risk.approved or candidate is None:
                raise ExecutionBlocked(";".join(risk.rejection_reasons) or "NO_APPROVED_ACTION")
            buy = decision.action == Action.OPEN_LONG
            if buy and (
                candidate.quote.bid <= decision.invalidation_price
                or now >= window.closes_at - timedelta(minutes=15)
            ):
                raise ExecutionBlocked("ENTRY_INVALIDATED_OR_NO_FORWARD_SESSION")
            price = candidate.quote.ask if buy else candidate.quote.bid
            quantity = (
                (risk.approved_notional / price).quantize(SHARE_STEP, rounding=ROUND_DOWN)
                if buy
                else position.quantity
            )
            if quantity <= 0 or quantity != quantity.quantize(SHARE_STEP, rounding=ROUND_DOWN):
                raise ExecutionBlocked("UNSUPPORTED_SHARE_PRECISION")
            if buy and quantity * price < self.settings.min_order_notional:
                raise ExecutionBlocked("ROUNDED_NOTIONAL_BELOW_MINIMUM")
            intent = Intent(
                client_id="rehearsal-" + hashlib.sha256(source_key.encode()).hexdigest(),
                source_key=source_key,
                symbol=decision.symbol,
                side="BUY" if buy else "SELL",
                quantity=quantity,
                limit_price=price,
                approved_notional=risk.approved_notional,
                prepared_at=now,
                expires_at=min(
                    candidate.quote.timestamp
                    + timedelta(seconds=self.settings.quote_max_age_seconds),
                    snapshot.captured_at + timedelta(seconds=self.settings.quote_max_age_seconds),
                    window.closes_at,
                ),
                original_invalidation=decision.invalidation_price
                if buy
                else position.original_invalidation,
                thesis=decision.thesis if buy else position.thesis,
            )
            approval = json.dumps(
                {
                    "packet": governed_packet.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                    "risk": risk.model_dump(mode="json"),
                },
                sort_keys=True,
            )
            db.execute(
                "UPDATE execution_control SET ledger_json=? WHERE id=1",
                (
                    state.model_copy(
                        update={"high_watermark": governed_packet.account.high_watermark}
                    ).model_dump_json(),
                ),
            )
            db.execute(
                "INSERT INTO execution_orders(client_id,source_key,fingerprint,intent_json,"
                "approval_json,status,active_lock) VALUES(?,?,?,?,?,'PREPARED',1)",
                (intent.client_id, source_key, fingerprint, intent.model_dump_json(), approval),
            )
            self.journal.event(
                db, now, "PREPARED", {"risk": risk.model_dump(mode="json")}, intent.client_id
            )
            return intent

    def dispatch(self, client_id: str, venue: LocalFixtureVenue, *, now):
        _clock(now)
        # Intentional hard boundary: generic transports and Robinhood clients cannot be attached.
        if type(venue) is not LocalFixtureVenue:
            raise ValueError("Only the built-in local fixture venue is supported")
        with self.journal.write() as db:
            order = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (client_id,)
            ).fetchone()
            if order is None:
                raise ValueError("Unknown execution intent")
            if order["status"] != OrderState.PREPARED:
                return order["status"]  # Never replay any attempted or terminal order.
            intent = Intent.model_validate_json(order["intent_json"])
            if (
                now >= intent.expires_at
                or now < intent.prepared_at
                or self.calendar.current_window(now) is None
            ):
                db.execute(
                    "UPDATE execution_orders SET status='EXPIRED', active_lock=NULL WHERE client_id=?",
                    (client_id,),
                )
                self.journal.event(db, now, "PREPARED_EXPIRED", {}, client_id)
                return OrderState.EXPIRED
            control = self._control(db)
            snapshot = self._ready(control, now)
            state = Ledger.model_validate_json(control["ledger_json"])
            approval = json.loads(order["approval_json"])
            proposed = TradeDecision.model_validate(approval["decision"])
            packet = MarketPacket.model_validate(approval["packet"])
            risk, current_packet = self._govern(proposed, packet, state, snapshot, now)
            window = self.calendar.current_window(now)
            if intent.side == "BUY":
                quote = next(c.quote for c in packet.candidates if c.quote.symbol == intent.symbol)
                entry_valid = (
                    quote.bid > intent.original_invalidation
                    and now < window.closes_at - timedelta(minutes=15)
                )
            else:
                entry_valid = True
            quantity_ok = (
                intent.quantity * intent.limit_price <= risk.approved_notional
                if intent.side == "BUY"
                else current_packet.account.position is not None
                and current_packet.account.position.symbol == intent.symbol
                and current_packet.account.position.quantity == intent.quantity
            )
            if not risk.approved or not quantity_ok or not entry_valid:
                db.execute(
                    "UPDATE execution_orders SET status='REJECTED', active_lock=NULL WHERE client_id=?",
                    (client_id,),
                )
                self.journal.event(
                    db,
                    now,
                    "PRE_DISPATCH_BLOCKED",
                    {"risk": risk.model_dump(mode="json")},
                    client_id,
                )
                return OrderState.REJECTED
            db.execute(
                "UPDATE execution_orders SET status='SUBMITTING',attempted_at=? WHERE client_id=?",
                (now.isoformat(), client_id),
            )
            self.journal.event(db, now, "ATTEMPT_STARTED", {}, client_id)
        # Write-ahead attempt has committed BEFORE the fake venue is called.
        try:
            order_id = venue.accept(intent, now)
            if not isinstance(order_id, str) or not order_id or len(order_id) > 128:
                raise ValueError("Invalid fixture acknowledgment")
            with self.journal.write() as db:
                row = db.execute(
                    "SELECT * FROM execution_orders WHERE client_id=?", (client_id,)
                ).fetchone()
                if row["order_id"] and row["order_id"] != order_id:
                    raise ValueError("Acknowledgment contradicts reconciled order identity")
                if row["status"] in {OrderState.SUBMITTING, OrderState.UNKNOWN}:
                    db.execute(
                        "UPDATE execution_orders SET status='OPEN',order_id=? WHERE client_id=?",
                        (order_id, client_id),
                    )
                    status = OrderState.OPEN
                else:
                    status = row[
                        "status"
                    ]  # Late ack cannot regress a reconciled partial/terminal order.
                self.journal.event(db, now, "ACKNOWLEDGED", {"order_id": order_id}, client_id)
            return status
        except Exception as exc:  # noqa: BLE001 - any failure after an attempt is uncertain.
            with self.journal.write() as db:
                db.execute(
                    "UPDATE execution_orders SET status='UNKNOWN' WHERE client_id=? AND status='SUBMITTING'",
                    (client_id,),
                )
                db.execute(
                    "UPDATE execution_control SET halted=1,halt_reason='UNCERTAIN_ORDER_ATTEMPT' WHERE id=1"
                )
                self.journal.event(
                    db, now, "ATTEMPT_UNCERTAIN", {"error_class": type(exc).__name__}, client_id
                )
            return OrderState.UNKNOWN

    def halt(self, reason: str, *, now):
        _clock(now)
        if not reason.strip() or len(reason) > 300:
            raise ValueError("A bounded halt reason is required")
        with self.journal.write() as db:
            db.execute("UPDATE execution_control SET halted=1,halt_reason=? WHERE id=1", (reason,))
            self.journal.event(db, now, "MANUAL_HALT", {"reason": reason})

    def abandon_prepared(self, client_id: str, reason: str, *, now):
        """Only an unattempted local intent can be abandoned without venue evidence."""
        _clock(now)
        if not reason.strip() or len(reason) > 300:
            raise ValueError("A bounded abandonment reason is required")
        with self.journal.write() as db:
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (client_id,)
            ).fetchone()
            if row is None or row["attempted_at"] or row["status"] != OrderState.PREPARED:
                raise ExecutionBlocked("ATTEMPTED_ORDER_REQUIRES_RECONCILIATION")
            db.execute(
                "UPDATE execution_orders SET status='EXPIRED',active_lock=NULL WHERE client_id=?",
                (client_id,),
            )
            self.journal.event(db, now, "PREPARED_ABANDONED", {"reason": reason}, client_id)

    def resume(self, reason: str, *, now):
        _clock(now)
        if not reason.strip() or len(reason) > 300:
            raise ValueError("A bounded resume reason is required")
        with self.journal.write() as db:
            c = self._control(db)
            if json.loads(c["issues_json"]) or not c["snapshot_json"]:
                raise ExecutionBlocked("RECONCILIATION_REQUIRED")
            snap = Snapshot.model_validate_json(c["snapshot_json"])
            if not self._fresh(snap, now, self.settings.quote_max_age_seconds):
                raise ExecutionBlocked("STALE_EXECUTION_SNAPSHOT")
            if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
                raise ExecutionBlocked("ORDER_ALREADY_IN_FLIGHT")
            state = Ledger.model_validate_json(c["ledger_json"])
            if state.position and (state.management is None or state.management.supervision_issue):
                raise ExecutionBlocked("POSITION_SUPERVISION_REQUIRED")
            db.execute("UPDATE execution_control SET halted=0,halt_reason=NULL WHERE id=1")
            self.journal.event(db, now, "MANUAL_RESUME", {"reason": reason})

    def reconcile(self, snapshot: Snapshot, *, now):
        _clock(now)
        with self.journal.write() as db:
            c = self._control(db)
            issues = []
            try:
                snapshot = Snapshot.model_validate(snapshot.model_dump())
                state, observations, fills = self._reconcile(db, c, snapshot, now, issues)
            except (ValueError, ArithmeticError) as exc:
                issues.append("INVALID_EXECUTION_EVIDENCE")
                self.journal.event(db, now, "INVALID_EVIDENCE", {"error_class": type(exc).__name__})
            if issues:
                issues = sorted(set(issues))
                db.execute(
                    "UPDATE execution_control SET halted=1,halt_reason='RECONCILIATION_BLOCKED',issues_json=? WHERE id=1",
                    (json.dumps(issues),),
                )
                self.journal.event(db, now, "RECONCILIATION_BLOCKED", {"issues": issues})
                return {"reconciled": False, "issues": issues}
            for client_id, obs in observations.items():
                terminal = OrderState(obs.status) in TERMINAL
                db.execute(
                    "UPDATE execution_orders SET order_id=?,status=?,observation_json=?,active_lock=? WHERE client_id=?",
                    (
                        obs.order_id,
                        obs.status,
                        obs.model_dump_json(),
                        None if terminal else 1,
                        client_id,
                    ),
                )
            for client_id, fill in fills:
                db.execute(
                    "INSERT INTO execution_fills VALUES(?,?,?)",
                    (fill.fill_id, client_id, fill.model_dump_json()),
                )
                self.journal.event(
                    db, now, "FILL_RECONCILED", fill.model_dump(mode="json"), client_id
                )
            db.execute(
                "INSERT OR IGNORE INTO execution_snapshots VALUES(?,?)",
                (snapshot.snapshot_id, snapshot.model_dump_json()),
            )
            db.execute(
                "UPDATE execution_control SET ledger_json=?,snapshot_json=?,issues_json='[]' WHERE id=1",
                (state.model_dump_json(), snapshot.model_dump_json()),
            )
            self.journal.event(
                db,
                now,
                "RECONCILED",
                {"snapshot_id": snapshot.snapshot_id, "new_fills": len(fills)},
            )
            return {"reconciled": True, "issues": [], "new_fills": len(fills)}

    def _reconcile(self, db, control, snapshot, now, issues):
        state = Ledger.model_validate_json(control["ledger_json"])
        if not self._fresh(snapshot, now, self.settings.quote_max_age_seconds):
            issues.append("STALE_FUTURE_OR_INCOMPLETE_SNAPSHOT")
        old_snapshot = (
            Snapshot.model_validate_json(control["snapshot_json"])
            if control["snapshot_json"]
            else None
        )
        if old_snapshot and snapshot.captured_at < old_snapshot.captured_at:
            issues.append("SNAPSHOT_TIME_REGRESSION")
        old_payload = db.execute(
            "SELECT payload FROM execution_snapshots WHERE snapshot_id=?", (snapshot.snapshot_id,)
        ).fetchone()
        if old_payload and old_payload[0] != snapshot.model_dump_json():
            issues.append("SNAPSHOT_ID_CONFLICT")
        if snapshot.unsupported_value != ZERO or len(snapshot.positions) > 1:
            issues.append("UNSUPPORTED_PORTFOLIO")
        if snapshot.safe_buying_power > snapshot.cash:
            issues.append("LEVERAGED_BUYING_POWER")
        local = {r["client_id"]: r for r in db.execute("SELECT * FROM execution_orders")}
        observations = {o.client_id: o for o in snapshot.orders}
        if len(observations) != len(snapshot.orders) or len(
            {o.order_id for o in snapshot.orders}
        ) != len(snapshot.orders):
            issues.append("DUPLICATE_ORDER_IDENTITIES")
        known = {r["fill_id"]: r for r in db.execute("SELECT * FROM execution_fills")}
        seen_fills = set()
        new_fills = []
        for client_id, obs in observations.items():
            row = local.get(client_id)
            if row is None:
                issues.append("UNOWNED_ORDER")
                continue
            intent = Intent.model_validate_json(row["intent_json"])
            if not row["attempted_at"]:
                issues.append("UNATTEMPTED_ORDER_AT_VENUE")
                continue
            attempted_at = datetime.fromisoformat(row["attempted_at"])
            if row["order_id"] and row["order_id"] != obs.order_id:
                issues.append("ORDER_ID_MISMATCH")
            if any(
                getattr(intent, k) != getattr(obs, k)
                for k in ("symbol", "side", "quantity", "limit_price")
            ):
                issues.append("ORDER_TERMS_MISMATCH")
            previous = (
                Observation.model_validate_json(row["observation_json"])
                if row["observation_json"]
                else None
            )
            if previous:
                if (
                    previous.updated_at > obs.updated_at
                    or previous.filled_quantity > obs.filled_quantity
                ):
                    issues.append("ORDER_EVIDENCE_REGRESSION")
                if OrderState(previous.status) in TERMINAL and (
                    previous.status != obs.status or previous.fills != obs.fills
                ):
                    issues.append("TERMINAL_ORDER_CHANGED")
            if not attempted_at <= obs.updated_at <= snapshot.captured_at:
                issues.append("INVALID_ORDER_TIME")
            if (
                intent.side == "BUY"
                and sum((f.price * f.quantity + f.fee for f in obs.fills), ZERO)
                > intent.approved_notional
            ):
                issues.append("APPROVED_BUDGET_EXCEEDED")
            for f in obs.fills:
                if f.fill_id in seen_fills:
                    issues.append("DUPLICATE_FILL_IDENTITIES")
                seen_fills.add(f.fill_id)
                if f.quantity != f.quantity.quantize(SHARE_STEP, rounding=ROUND_DOWN):
                    issues.append("UNSUPPORTED_SHARE_PRECISION")
                if not attempted_at <= f.occurred_at <= obs.updated_at:
                    issues.append("INVALID_FILL_TIME")
                if (intent.side == "BUY" and f.price > intent.limit_price) or (
                    intent.side == "SELL" and f.price < intent.limit_price
                ):
                    issues.append("FILL_OUTSIDE_LIMIT")
                old = known.get(f.fill_id)
                if old:
                    if old["client_id"] != client_id or old["payload"] != f.model_dump_json():
                        issues.append("FILL_ID_CONFLICT")
                else:
                    new_fills.append((client_id, f))
        for client_id, row in local.items():
            if row["attempted_at"] and client_id not in observations:
                # Missing from an open-order list is NEVER evidence of cancel/fill/expiry.
                issues.append("ATTEMPTED_ORDER_MISSING")
        if set(known) - seen_fills:
            issues.append("KNOWN_FILLS_MISSING")
        if issues:
            return state, observations, new_fills
        last_fill = max(
            (
                datetime.fromisoformat(json.loads(r["payload"])["occurred_at"])
                for r in known.values()
            ),
            default=None,
        )
        for client_id, fill in sorted(new_fills, key=lambda item: item[1].occurred_at):
            if last_fill and fill.occurred_at < last_fill:
                issues.append("FILL_TIME_REGRESSION")
                break
            intent = Intent.model_validate_json(local[client_id]["intent_json"])
            management = self._entry_management(local[client_id]) if intent.side == "BUY" else None
            state = self._apply_fill(state, intent, fill, management)
        expected = state.position
        actual = snapshot.positions[0] if len(snapshot.positions) == 1 else None
        if state.cash != snapshot.cash:
            issues.append("CASH_MISMATCH")
        if (expected is None) != (actual is None) or (
            expected
            and actual
            and any(
                getattr(expected, k) != getattr(actual, k)
                for k in ("symbol", "quantity", "entry_price")
            )
        ):
            issues.append("POSITION_MISMATCH")
        return state, observations, new_fills

    @staticmethod
    def _apply_fill(state, intent, fill, management=None):
        position = state.position
        updates = {"fees_paid": state.fees_paid + fill.fee}
        if intent.side == "BUY":
            if position and position.symbol != intent.symbol:
                raise ValueError("Multiple positions")
            old_quantity = position.quantity if position else ZERO
            basis = position.quantity * position.entry_price if position else ZERO
            quantity = old_quantity + fill.quantity
            updates["cash"] = state.cash - fill.quantity * fill.price - fill.fee
            updates["position"] = Position(
                symbol=intent.symbol,
                quantity=quantity,
                entry_price=(basis + fill.quantity * fill.price) / quantity,
                current_price=fill.price,
                original_invalidation=intent.original_invalidation,
                thesis=intent.thesis,
                opened_at=position.opened_at if position else fill.occurred_at,
            )
            if position is None:
                updates["entry_times"] = [*state.entry_times, fill.occurred_at]
                if management is None:
                    raise ValueError("Entry management is required")
                updates["management"] = management
        else:
            if (
                not position
                or position.symbol != intent.symbol
                or fill.quantity > position.quantity
            ):
                raise ValueError("Unowned sale or oversell")
            quantity = position.quantity - fill.quantity
            updates["cash"] = state.cash + fill.quantity * fill.price - fill.fee
            updates["realized_pnl"] = state.realized_pnl + fill.quantity * (
                fill.price - position.entry_price
            )
            updates["position"] = (
                position.model_copy(update={"quantity": quantity, "current_price": fill.price})
                if quantity
                else None
            )
            if quantity == ZERO:
                updates["last_close_at"] = fill.occurred_at
                updates["management"] = None
        result = Ledger.model_validate({**state.model_dump(), **updates})
        equity = result.cash + (result.position.market_value if result.position else ZERO)
        return result.model_copy(update={"high_watermark": max(result.high_watermark, equity)})
