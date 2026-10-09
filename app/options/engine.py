"""Durable options PAPER lifecycle on the existing journal/restore/ownership foundation."""

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from functools import wraps
from itertools import pairwise
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.execution import economics, restore
from app.execution.economics import UsageEvidence
from app.execution.engine import ExecutionBlocked
from app.execution.journal import ExecutionJournal
from app.execution.runtime import runtime_lease
from app.options.accounting import apply_fill, apply_receipt
from app.options.governor import _fresh, _tick_price, admit_option
from app.options.lifecycle import (
    CALENDAR_SOURCE,
    TERMINAL,
    OptionExecutionPolicy,
    OptionIntent,
    OptionLedger,
    OptionVenueSnapshot,
)
from app.options.models import (
    OptionAccount,
    OptionHolding,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    SessionWindow,
    UnderlyingQuote,
)
from app.options.process import run_option_process
from app.options.venue import DurableOptionVenue, private_path
from app.robinhood.schedule import XNYSCalendar

ZERO = Decimal(0)
OWNER = object()


def clock(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Options execution clock must be timezone-aware")
    return now.astimezone(UTC)


def exact(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=192)):
            return function(*args, **kwargs)

    return wrapped


def fingerprint(value):
    def normalize(item):
        if hasattr(item, "model_dump"):
            return normalize(item.model_dump(warnings=False))
        if isinstance(item, Decimal):
            text = format(item, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text
        if isinstance(item, datetime):
            return clock(item).isoformat()
        if hasattr(item, "isoformat"):
            return item.isoformat()
        if isinstance(item, dict):
            return {k: normalize(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(v) for v in item]
        return item

    return hashlib.sha256(
        json.dumps(normalize(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class OptionJournal(ExecutionJournal):
    schema = "option-paper-execution-v1"
    ledger_type = OptionLedger
    extra_tables = frozenset({"execution_option_decisions", "execution_option_receipts"})

    def report(self, *, now=None):
        with self.read() as db:
            c = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
            return {
                "mode": "OPTIONS_PAPER_FIXTURE",
                "live_enabled": False,
                "network_calls": False,
                "revision": self.revision(db),
                "config": json.loads(c["config_json"]),
                "ledger": json.loads(c["ledger_json"]),
                "halted": bool(c["halted"]),
                "halt_reason": c["halt_reason"],
                "issues": json.loads(c["issues_json"]),
                "restore_fence": restore.status(db, restore.authority_path(self.path)),
                "economics": economics.summary(db, now),
                "alerts": self._alerts(db, 0, 100),
                "orders": [
                    dict(r)
                    for r in db.execute(
                        "SELECT client_id,source_key,status,order_id,attempted_at,active_lock,intent_json FROM execution_orders ORDER BY rowid DESC LIMIT 100"
                    )
                ],
                "decisions": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM execution_option_decisions ORDER BY rowid DESC LIMIT 100"
                    )
                ],
                "events": [
                    {**dict(r), "payload": json.loads(r["payload"])}
                    for r in db.execute(
                        "SELECT * FROM execution_events ORDER BY sequence DESC LIMIT 100"
                    )
                ],
            }


class OptionExecution:
    @classmethod
    @contextmanager
    def open(cls, path, limits, policy, venue, *, now, create=False):
        path = Path(path).expanduser().absolute()
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with runtime_lease(path):
            if create:
                if path.exists() or restore.authority_path(path).exists():
                    raise ValueError("Options enrollment cannot overwrite or adopt existing state")
            else:
                private_path(path)
                private_path(restore.authority_path(path))
            engine = cls(path, limits, policy, venue, now=now, create=create, _owner=OWNER)
            try:
                yield engine
            finally:
                engine._closed = True

    def __init__(self, path, limits, policy, venue, *, now, create=False, _owner=None):
        if _owner is not OWNER or type(venue) is not DurableOptionVenue:
            raise ValueError("Use owned OptionExecution.open with the built-in fixture")
        self._closed = False
        self.limits = OptionLimits.model_validate(limits.model_dump(warnings=False))
        self.policy = OptionExecutionPolicy.model_validate(policy.model_dump(warnings=False))
        if (
            self.limits.session_source != CALENDAR_SOURCE
            or venue.limits != self.limits
            or venue.initial_capital != self.policy.capital
        ):
            raise ValueError("Exact PAPER venue/policy/calendar binding required")
        self.venue = venue
        self.calendar = XNYSCalendar()
        config = {
            "capital": str(self.policy.capital),
            "limits": self.limits.model_dump(mode="json"),
            "policy": self.policy.model_dump(mode="json"),
            "venue_id": venue.venue_id,
            "venue_path": str(venue.path),
        }
        self._config = json.dumps({"schema": OptionJournal.schema, **config}, sort_keys=True)
        self.journal = OptionJournal(path, config)
        now = clock(now)
        with self.journal.write() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_decisions(source_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,inputs_json TEXT NOT NULL,result_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_receipts(receipt_id TEXT PRIMARY KEY,payload TEXT NOT NULL)"
            )
            if self.policy.cost_policy is not None:
                db.execute(
                    "INSERT OR IGNORE INTO execution_cost_policy VALUES(1,?)",
                    (self.policy.cost_policy.model_dump_json(),),
                )
            for row in db.execute(
                "SELECT client_id FROM execution_orders WHERE status='SUBMITTING'"
            ).fetchall():
                db.execute(
                    "UPDATE execution_orders SET status='UNKNOWN' WHERE client_id=?", (row[0],)
                )
                self._halt(db, "INTERRUPTED_OPTION_ATTEMPT", now)
                self.journal.event(db, now, "INTERRUPTED_ATTEMPT", {}, row[0])
        if create:
            self.journal.enable_restore_fence(now=now)

    def _control(self, db):
        if self._closed:
            raise ExecutionBlocked("OPTION_OWNER_CLOSED")
        c = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
        if c["config_json"] != self._config:
            raise ExecutionBlocked("FROZEN_OPTION_CONFIGURATION_CHANGED")
        return c

    def _halt(self, db, reason, now):
        db.execute("UPDATE execution_control SET halted=1,halt_reason=? WHERE id=1", (reason,))
        self.journal.event(db, now, "MANUAL_HALT", {"reason": reason})

    def _session(self, contract, now):
        window = self.calendar.current_window(now)
        if window is None:
            return None
        end = min(window.closes_at, contract.last_trading_at)
        cutoff = min(
            window.closes_at - timedelta(minutes=self.policy.entry_cutoff_minutes),
            end - timedelta(seconds=self.policy.expiry_guard_seconds),
        )
        if cutoff <= window.opens_at:
            return None
        return SessionWindow(
            source=CALENDAR_SOURCE,
            underlying=contract.underlying,
            opens_at=window.opens_at,
            entry_cutoff_at=cutoff,
            closes_at=end,
        )

    def _effective_limits(self):
        # A multi-contract position may need one observed-size close order per
        # contract. Reserve all those order fees before entry, never after loss.
        return OptionLimits.model_validate(
            {
                **self.limits.model_dump(),
                "exit_fee_per_order": ZERO,
                "exit_fee_per_contract": self.limits.exit_fee_per_contract
                + self.limits.exit_fee_per_order,
            }
        )

    @exact
    def _account(self, db, now, *, exclude=None, closing=False):
        c = self._control(db)
        if not c["snapshot_json"] or json.loads(c["issues_json"]):
            raise ExecutionBlocked("OPTION_RECONCILIATION_REQUIRED")
        snap = OptionVenueSnapshot.model_validate_json(c["snapshot_json"])
        ledger = OptionLedger.model_validate_json(c["ledger_json"])
        costs = economics.summary(db, now)
        day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        cost = Decimal(costs["known_cost"])
        daily_cost = Decimal(costs["daily_cost"].get(day, "0"))
        rows = [
            r
            for r in db.execute("SELECT * FROM execution_orders WHERE active_lock=1")
            if r["client_id"] != exclude
        ]
        reserved = ZERO
        if ledger.position is not None and not closing:
            reserved = ledger.position.quantity * (
                self.limits.exit_fee_per_contract + self.limits.exit_fee_per_order
            )
        for row in rows:
            intent = OptionIntent.model_validate_json(row["intent_json"])
            if intent.side == "BUY":
                obs = json.loads(row["observation_json"] or "null")
                paid = sum(
                    (
                        Decimal(f["price"]) * f["quantity"] * intent.instrument.contract.multiplier
                        + Decimal(f["fee"])
                        for f in (obs["fills"] if obs else [])
                    ),
                    ZERO,
                )
                reserved = max(reserved, max(ZERO, intent.approved_full_premium_loss - paid))
        blockers = []
        supervised = db.execute("SELECT * FROM execution_supervisor WHERE id=1").fetchone()
        if (
            supervised is None
            or supervised["status"] != "HEALTHY"
            or not timedelta(0)
            <= now - clock(datetime.fromisoformat(supervised["heartbeat_at"]))
            < timedelta(seconds=self.policy.supervisor_max_age_seconds)
            or json.loads(supervised["result_json"])["snapshot_id"] != snap.snapshot_id
        ):
            blockers.append("OPTION_SUPERVISION_REQUIRED")
        if costs.get("calls_exceeding_bound", 0):
            blockers.append("MODEL_COST_BOUND_EXCEEDED")
        if self.policy.cost_policy is not None and (
            cost >= self.policy.cost_policy.total_budget
            or daily_cost >= self.policy.cost_policy.daily_budget
        ):
            blockers.append("MODEL_COST_BUDGET_EXHAUSTED")
        return OptionAccount(
            account_id=self.limits.account_id,
            population_id=self.limits.population_id,
            snapshot_id=snap.snapshot_id,
            captured_at=snap.captured_at,
            complete=snap.complete,
            reconciled=True,
            cash=ledger.cash,
            settled_cash=ledger.settled_cash,
            reserved_cash=reserved,
            daily_loss_available=max(
                ZERO,
                self.policy.daily_loss_limit + ledger.daily_net_pnl.get(day, ZERO) - daily_cost,
            ),
            total_loss_available=max(
                ZERO, self.policy.total_loss_limit + ledger.realized_pnl - ledger.fees_paid - cost
            ),
            budgets_known=costs["unknown_calls"] == 0,
            position=OptionHolding.model_validate(
                {
                    k: v
                    for k, v in ledger.position.model_dump().items()
                    if k in OptionHolding.model_fields
                }
            )
            if ledger.position
            else None,
            working_orders=len(rows),
            unsupported_exposure=bool(snap.underlying_exposures),
            entry_halted=bool(c["halted"]),
            entry_blockers=tuple(blockers),
        )

    @exact
    def prepare(
        self, source_key, proposal, quote=None, underlying=None, *, now, origin="DETERMINISTIC"
    ):
        now = clock(now)
        proposal = OptionProposal.model_validate(proposal.model_dump(warnings=False))
        quote = OptionQuote.model_validate(quote.model_dump(warnings=False)) if quote else None
        underlying = (
            UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
            if underlying
            else None
        )
        if (
            not isinstance(source_key, str)
            or not source_key.strip()
            or len(source_key) > 128
            or origin not in {"DETERMINISTIC", "MODEL", "PROTECTIVE"}
        ):
            raise ValueError("Bounded source and explicit proposal origin required")
        inputs = {
            "proposal": proposal.model_dump(mode="json"),
            "quote": quote.model_dump(mode="json") if quote else None,
            "underlying": underlying.model_dump(mode="json") if underlying else None,
            "origin": origin,
        }
        digest = fingerprint(
            {"proposal": proposal, "quote": quote, "underlying": underlying, "origin": origin}
        )
        with self.journal.write() as db:
            self._control(db)
            old = db.execute(
                "SELECT * FROM execution_option_decisions WHERE source_key=?", (source_key,)
            ).fetchone()
            if old:
                if old["fingerprint"] != digest:
                    raise ExecutionBlocked("OPTION_SOURCE_IDENTITY_CONFLICT")
                return json.loads(old["result_json"])
            reason = None
            if origin == "MODEL":
                model = db.execute(
                    "SELECT * FROM execution_model_calls WHERE source_key=?", (source_key,)
                ).fetchone()
                if (
                    model is None
                    or model["cost"] is None
                    or model["decision_hash"] != fingerprint(proposal)
                ):
                    reason = "OPTION_MODEL_RECEIPT_REQUIRED"
            try:
                account = (
                    self._account(db, now, closing=proposal.action == "CLOSE")
                    if proposal.action != "HOLD"
                    else None
                )
                session = self._session(proposal.contract, now) if proposal.contract else None
                result = admit_option(
                    proposal, quote, underlying, account, self._effective_limits(), session, now=now
                )
            except (ValueError, ExecutionBlocked) as exc:
                reason = str(exc)
                result = None
            output = {
                "status": "REJECTED",
                "reason": reason,
                "client_id": None,
                "admission": result.model_dump(mode="json") if result else None,
            }
            if reason is None and result.outcome == "HOLD":
                output["status"] = "HOLD"
            elif reason is None and result.outcome == "APPROVED":
                if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
                    output["reason"] = "OPTION_ORDER_ALREADY_IN_FLIGHT"
                else:
                    ledger = OptionLedger.model_validate_json(self._control(db)["ledger_json"])
                    exit_at = min(
                        session.closes_at - timedelta(minutes=self.policy.exit_cutoff_minutes),
                        proposal.contract.last_trading_at
                        - timedelta(seconds=self.policy.expiry_guard_seconds),
                    )
                    stop = (
                        proposal.underlying_invalidation
                        if proposal.action == "OPEN_LONG"
                        else ledger.position.original_underlying_invalidation
                    )
                    intent = OptionIntent(
                        client_id="option-" + uuid4().hex,
                        source_key=source_key,
                        instrument=quote.instrument,
                        side="BUY" if proposal.action == "OPEN_LONG" else "SELL",
                        quantity=result.quantity,
                        limit_price=result.limit_price,
                        approved_entry_debit=result.entry_debit,
                        approved_full_premium_loss=result.full_premium_loss,
                        prepared_at=now,
                        approval_expires_at=result.valid_until,
                        order_expires_at=session.closes_at,
                        exit_at=exit_at
                        if proposal.action == "OPEN_LONG"
                        else ledger.position.exit_at,
                        original_underlying_invalidation=stop,
                        thesis=proposal.thesis,
                    )
                    approval = {
                        **inputs,
                        "admission": result.model_dump(mode="json"),
                        "account": account.model_dump(mode="json"),
                        "effective_limits": self._effective_limits().model_dump(mode="json"),
                    }
                    db.execute(
                        "INSERT INTO execution_orders VALUES(?,?,?,?,?,'PREPARED',1,NULL,NULL,NULL)",
                        (
                            intent.client_id,
                            source_key,
                            digest,
                            intent.model_dump_json(),
                            json.dumps(approval, sort_keys=True),
                        ),
                    )
                    output.update(status="PREPARED", client_id=intent.client_id)
            elif result is not None and reason is None:
                output["reason"] = ";".join(result.reasons)
            db.execute(
                "INSERT INTO execution_option_decisions VALUES(?,?,?,?)",
                (
                    source_key,
                    digest,
                    json.dumps(inputs, sort_keys=True),
                    json.dumps(output, sort_keys=True),
                ),
            )
            self.journal.event(
                db, now, "OPTION_PROPOSAL_RECORDED", {"source_key": source_key, **output}
            )
            return output

    @exact
    def _begin(self, client_id, quote, underlying, now):
        with self.journal.write() as db:
            self._control(db)
            row = db.execute(
                "SELECT * FROM execution_orders WHERE client_id=?", (client_id,)
            ).fetchone()
            if row is None:
                raise ExecutionBlocked("UNKNOWN_OPTION_INTENT")
            if row["status"] != "PREPARED" or row["attempted_at"]:
                return row["status"]
            intent = OptionIntent.model_validate_json(row["intent_json"])
            approval = json.loads(row["approval_json"])
            proposal = OptionProposal.model_validate(approval["proposal"])
            reason = None
            try:
                if now >= intent.approval_expires_at or now < intent.prepared_at:
                    raise ExecutionBlocked("OPTION_APPROVAL_EXPIRED")
                if quote.instrument != intent.instrument:
                    raise ExecutionBlocked("OPTION_INSTRUMENT_MAPPING_CHANGED")
                account = self._account(db, now, exclude=client_id, closing=intent.side == "SELL")
                result = admit_option(
                    proposal,
                    quote,
                    underlying,
                    account,
                    self._effective_limits(),
                    self._session(intent.instrument.contract, now),
                    now=now,
                )
                if result.outcome != "APPROVED" or result.quantity < intent.quantity:
                    raise ExecutionBlocked(
                        "OPTION_FRESH_ADMISSION_REJECTED:" + ";".join(result.reasons)
                    )
                if intent.side == "BUY":
                    caps = min(
                        self.limits.max_entry_debit,
                        self.limits.max_account_exposure,
                        proposal.max_entry_debit or self.limits.max_entry_debit,
                    )
                    loss = min(
                        self.limits.max_full_premium_loss,
                        account.daily_loss_available,
                        account.total_loss_available,
                        account.settled_cash - account.reserved_cash,
                    )
                    if (
                        result.limit_price > intent.limit_price
                        or intent.approved_entry_debit > caps
                        or intent.approved_full_premium_loss > loss
                    ):
                        raise ExecutionBlocked("OPTION_ORIGINAL_PRICE_OR_BUDGET_EXCEEDED")
                elif result.limit_price < intent.limit_price:
                    raise ExecutionBlocked("OPTION_BID_BELOW_FIXED_LIMIT")
            except (ValueError, ExecutionBlocked) as exc:
                reason = str(exc)
            if reason:
                db.execute(
                    "UPDATE execution_orders SET status='REJECTED',active_lock=NULL WHERE client_id=?",
                    (client_id,),
                )
                self.journal.event(
                    db, now, "OPTION_DISPATCH_REJECTED", {"reason": reason}, client_id
                )
                return "REJECTED"
            db.execute(
                "UPDATE execution_orders SET status='SUBMITTING',attempted_at=? WHERE client_id=?",
                (now.isoformat(), client_id),
            )
            self.journal.event(
                db,
                now,
                "OPTION_ATTEMPT_STARTED",
                {
                    "quote": quote.model_dump(mode="json"),
                    "account": account.model_dump(mode="json"),
                },
                client_id,
            )
            return intent

    async def dispatch(self, client_id, quote, underlying=None, *, now):
        admitted_monotonic = time.monotonic()
        now = clock(now)
        quote = OptionQuote.model_validate(quote.model_dump(warnings=False))
        underlying = (
            UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
            if underlying
            else None
        )
        intent = self._begin(client_id, quote, underlying, now)
        if not isinstance(intent, OptionIntent):
            return intent
        try:
            result = await run_option_process(
                self.venue,
                now=now,
                intent=intent,
                timeout_seconds=self.policy.process_timeout_seconds,
                deadline=admitted_monotonic
                + min(
                    self.policy.process_timeout_seconds,
                    (intent.approval_expires_at - now).total_seconds(),
                ),
            )
            with self.journal.write() as db:
                row = db.execute(
                    "SELECT * FROM execution_orders WHERE client_id=?", (client_id,)
                ).fetchone()
                if row["status"] != "SUBMITTING":
                    raise ExecutionBlocked("OPTION_ATTEMPT_STATE_CHANGED")
                db.execute(
                    "UPDATE execution_orders SET status='OPEN',order_id=? WHERE client_id=?",
                    (result.order_id, client_id),
                )
                self.journal.event(
                    db, now, "OPTION_ACKNOWLEDGED", {"order_id": result.order_id}, client_id
                )
            return "OPEN"
        except BaseException as exc:
            with self.journal.write() as db:
                db.execute(
                    "UPDATE execution_orders SET status='UNKNOWN' WHERE client_id=? AND status='SUBMITTING'",
                    (client_id,),
                )
                self._halt(db, "UNCERTAIN_OPTION_ATTEMPT", now)
                self.journal.event(
                    db, now, "ATTEMPT_UNCERTAIN", {"error_class": type(exc).__name__}, client_id
                )
            if not isinstance(exc, Exception):
                raise
            return "UNKNOWN"

    def _epoch(self, db):
        return fingerprint(
            [dict(r) for r in db.execute("SELECT * FROM execution_orders ORDER BY client_id")]
            + [dict(self._control(db))]
        )

    async def reconcile_fixture(self, *, now):
        now = clock(now)
        with self.journal.read() as db:
            self._control(db)
            if db.execute("SELECT 1 FROM execution_orders WHERE status='SUBMITTING'").fetchone():
                return {"reconciled": False, "issues": ["OPTION_SUBMISSION_IN_PROGRESS"]}
            epoch = self._epoch(db)
        try:
            result = await run_option_process(
                self.venue, now=now, timeout_seconds=self.policy.process_timeout_seconds
            )
        except BaseException:
            with self.journal.write() as db:
                self._halt(db, "OPTION_FIXTURE_READ_FAILED", now)
                self.journal.event(db, now, "FIXTURE_READ_FAILED", {})
            raise
        return self.reconcile(result.snapshot, now=now, _epoch=epoch)

    @exact
    def reconcile(self, snapshot, *, now, _epoch=None):
        now = clock(now)
        with self.journal.write() as db:
            c = self._control(db)
            if db.execute("SELECT 1 FROM execution_orders WHERE status='SUBMITTING'").fetchone():
                return {"reconciled": False, "issues": ["OPTION_SUBMISSION_IN_PROGRESS"]}
            if _epoch is not None and self._epoch(db) != _epoch:
                self.journal.event(db, now, "OPTION_READ_SUPERSEDED", {})
                return {"reconciled": False, "issues": ["OPTION_READ_SUPERSEDED"]}
            try:
                snap = OptionVenueSnapshot.model_validate(snapshot.model_dump(warnings=False))
                state, observations, new_fills, new_receipts = self._reconcile(db, c, snap, now)
            except (ValueError, ArithmeticError) as exc:
                reason = str(exc)
                db.execute(
                    "UPDATE execution_control SET halted=1,halt_reason='OPTION_RECONCILIATION_BLOCKED',issues_json=? WHERE id=1",
                    (json.dumps([reason]),),
                )
                self.journal.event(
                    db,
                    now,
                    "RECONCILIATION_BLOCKED",
                    {
                        "issues": [reason],
                        "snapshot": snapshot.model_dump(mode="json", warnings=False),
                    },
                )
                return {"reconciled": False, "issues": [reason]}
            for client_id, obs in observations.items():
                db.execute(
                    "UPDATE execution_orders SET status=?,order_id=?,observation_json=?,active_lock=? WHERE client_id=?",
                    (
                        obs.status,
                        obs.order_id,
                        obs.model_dump_json(),
                        None if obs.status in TERMINAL else 1,
                        client_id,
                    ),
                )
            for client_id, fill in new_fills:
                db.execute(
                    "INSERT INTO execution_fills VALUES(?,?,?)",
                    (fill.fill_id, client_id, fill.model_dump_json()),
                )
            for receipt in new_receipts:
                db.execute(
                    "INSERT INTO execution_option_receipts VALUES(?,?)",
                    (receipt.receipt_id, receipt.model_dump_json()),
                )
            db.execute(
                "INSERT OR IGNORE INTO execution_snapshots VALUES(?,?)",
                (snap.snapshot_id, snap.model_dump_json()),
            )
            db.execute(
                "UPDATE execution_control SET ledger_json=?,snapshot_json=?,issues_json='[]' WHERE id=1",
                (state.model_dump_json(), snap.model_dump_json()),
            )
            self.journal.event(
                db,
                now,
                "OPTION_RECONCILED",
                {
                    "snapshot_id": snap.snapshot_id,
                    "new_fills": len(new_fills),
                    "new_receipts": len(new_receipts),
                },
            )
            return {
                "reconciled": True,
                "new_fills": len(new_fills),
                "new_receipts": len(new_receipts),
                "issues": [],
            }

    def _reconcile(self, db, c, snap, now):
        if (snap.venue_id, snap.account_id, snap.population_id) != (
            self.venue.venue_id,
            self.limits.account_id,
            self.limits.population_id,
        ):
            raise ValueError("OPTION_SNAPSHOT_BINDING_MISMATCH")
        if not snap.complete or not timedelta(0) <= now - snap.captured_at < timedelta(
            seconds=self.limits.account_max_age_seconds
        ):
            raise ValueError("OPTION_SNAPSHOT_STALE_FUTURE_OR_INCOMPLETE")
        if snap.underlying_exposures:
            raise ValueError("UNEXPECTED_UNDERLYING_EXPOSURE")
        old = (
            OptionVenueSnapshot.model_validate_json(c["snapshot_json"])
            if c["snapshot_json"]
            else None
        )
        if old and snap.captured_at < old.captured_at:
            raise ValueError("OPTION_SNAPSHOT_TIME_REGRESSION")
        duplicate = db.execute(
            "SELECT payload FROM execution_snapshots WHERE snapshot_id=?", (snap.snapshot_id,)
        ).fetchone()
        if duplicate and duplicate[0] != snap.model_dump_json():
            raise ValueError("OPTION_SNAPSHOT_ID_CONFLICT")
        rows = {r["client_id"]: r for r in db.execute("SELECT * FROM execution_orders")}
        observations = {o.client_id: o for o in snap.orders}
        if len(observations) != len(snap.orders) or len({o.order_id for o in snap.orders}) != len(
            snap.orders
        ):
            raise ValueError("DUPLICATE_OPTION_ORDER_IDENTITIES")
        known = {r["fill_id"]: r for r in db.execute("SELECT * FROM execution_fills")}
        known_receipts = {
            r["receipt_id"]: r["payload"]
            for r in db.execute("SELECT * FROM execution_option_receipts")
        }
        new_fills = []
        seen = set()
        events = []
        quote_usage = {}
        for client_id, obs in observations.items():
            row = rows.get(client_id)
            if row is None or row["attempted_at"] is None:
                raise ValueError("UNOWNED_OR_UNATTEMPTED_OPTION_ORDER")
            intent = OptionIntent.model_validate_json(row["intent_json"])
            attempted = datetime.fromisoformat(row["attempted_at"])
            if row["order_id"] and row["order_id"] != obs.order_id:
                raise ValueError("OPTION_ORDER_ID_MISMATCH")
            if any(
                getattr(intent, k) != getattr(obs, k)
                for k in ("instrument", "side", "quantity", "limit_price")
            ):
                raise ValueError("OPTION_ORDER_TERMS_MISMATCH")
            if not attempted <= obs.updated_at <= snap.captured_at:
                raise ValueError("OPTION_ORDER_TIME_MISMATCH")
            previous = json.loads(row["observation_json"] or "null")
            if previous and (
                datetime.fromisoformat(previous["updated_at"]) > obs.updated_at
                or previous["filled_quantity"] > obs.filled_quantity
                or (
                    previous["status"] in TERMINAL
                    and (
                        previous["status"] != obs.status
                        or previous["fills"] != obs.model_dump(mode="json")["fills"]
                    )
                )
            ):
                raise ValueError("OPTION_ORDER_EVIDENCE_REGRESSION")
            paid = ZERO
            for index, fill in enumerate(obs.fills):
                if fill.fill_id in seen:
                    raise ValueError("DUPLICATE_OPTION_FILL_ID")
                seen.add(fill.fill_id)
                if (
                    not attempted <= fill.occurred_at <= obs.updated_at
                    or fill.occurred_at >= intent.order_expires_at
                ):
                    raise ValueError("OPTION_FILL_TIME_MISMATCH")
                self._validate_fill(intent, fill, index, quote_usage)
                paid += (
                    fill.quantity * fill.price * intent.instrument.contract.multiplier + fill.fee
                )
                if fill.fill_id in known:
                    if (
                        known[fill.fill_id]["client_id"] != client_id
                        or known[fill.fill_id]["payload"] != fill.model_dump_json()
                    ):
                        raise ValueError("OPTION_FILL_ID_CONFLICT")
                else:
                    new_fills.append((client_id, fill))
                events.append((fill.sequence, fill.occurred_at, "FILL", (client_id, fill)))
            if intent.side == "BUY" and paid > intent.approved_entry_debit:
                raise ValueError("OPTION_APPROVED_DEBIT_EXCEEDED")
        if set(known) - seen or any(
            r["attempted_at"] and k not in observations for k, r in rows.items()
        ):
            raise ValueError("OPTION_ATTEMPT_OR_FILL_HISTORY_MISSING")
        new_receipts = []
        seen_receipts = set()
        for receipt in snap.receipts:
            if receipt.receipt_id in seen_receipts or receipt.occurred_at > snap.captured_at:
                raise ValueError("OPTION_RECEIPT_ID_OR_TIME_CONFLICT")
            seen_receipts.add(receipt.receipt_id)
            if receipt.receipt_id in known_receipts:
                if known_receipts[receipt.receipt_id] != receipt.model_dump_json():
                    raise ValueError("OPTION_RECEIPT_ID_CONFLICT")
            else:
                new_receipts.append(receipt)
            events.append((receipt.sequence, receipt.occurred_at, "RECEIPT", receipt))
        if set(known_receipts) - seen_receipts:
            raise ValueError("OPTION_SETTLEMENT_HISTORY_MISSING")
        ordered = sorted(events, key=lambda e: e[0])
        if [e[0] for e in ordered] != list(range(1, len(ordered) + 1)) or any(
            a[1] > b[1] for a, b in pairwise(ordered)
        ):
            raise ValueError("OPTION_EVENT_SEQUENCE_OR_TIME_CONFLICT")
        # Replay all complete immutable venue receipts from the frozen original
        # capital, then preserve independent management of the same owned lineage.
        state = OptionLedger(cash=self.policy.capital, high_watermark=self.policy.capital)
        for _, _, kind, event in ordered:
            if kind == "FILL":
                client_id, fill = event
                state = apply_fill(
                    state, OptionIntent.model_validate_json(rows[client_id]["intent_json"]), fill
                )
            else:
                state = apply_receipt(state, event)
        if (
            state.cash != snap.cash
            or state.settled_cash != snap.settled_cash
            or (state.position is None) != (snap.position is None)
        ):
            raise ValueError("OPTION_CASH_OR_POSITION_MISMATCH")
        if state.position and (
            state.position.contract != snap.position.contract
            or state.position.quantity != snap.position.quantity
            or state.position.basis != snap.position.basis
            or state.position.lots != snap.position.lots
            or state.position.original_underlying_invalidation
            != snap.position.original_underlying_invalidation
            or state.position.exit_at != snap.position.exit_at
            or state.position.entry_client_id != snap.position.entry_client_id
        ):
            raise ValueError("OPTION_POSITION_TERMS_MISMATCH")
        prior = OptionLedger.model_validate_json(c["ledger_json"])
        if (
            state.position
            and prior.position
            and state.position.entry_client_id == prior.position.entry_client_id
        ):
            state = state.model_copy(
                update={
                    "position": state.position.model_copy(
                        update={
                            k: getattr(prior.position, k)
                            for k in (
                                "tightened_underlying_invalidation",
                                "exit_reason",
                                "exit_required_at",
                                "supervision_issue",
                            )
                        }
                    )
                }
            )
        return state, observations, new_fills, new_receipts

    def _validate_fill(self, intent, fill, index, used):
        q = fill.quote
        if (
            q.instrument != intent.instrument
            or q.source != self.limits.option_source
            or not q.complete
            or q.entitlement != "REALTIME"
            or not _fresh(
                q.source_at,
                q.received_at,
                fill.occurred_at,
                self.limits.quote_max_age_seconds,
                self.limits.max_receive_lag_seconds,
            )
            or q.bid is None
            or q.bid <= 0
            or (q.ask is not None and q.ask < q.bid)
        ):
            raise ValueError("OPTION_FILL_EXECUTABLE_EVIDENCE_INVALID")
        digest = hashlib.sha256(q.model_dump_json().encode()).hexdigest()
        if digest != fill.quote_hash:
            raise ValueError("OPTION_FILL_QUOTE_HASH_MISMATCH")
        canonical = fingerprint(q)
        key = (intent.side, canonical)
        used[key] = used.get(key, 0) + fill.quantity
        raw, size = (q.ask, q.ask_size) if intent.side == "BUY" else (q.bid, q.bid_size)
        if raw is None or used[key] > size:
            raise ValueError("OPTION_FILL_EXCEEDS_OBSERVED_SIZE")
        sign = 1 if intent.side == "BUY" else -1
        expected = _tick_price(
            raw * (1 + sign * self.limits.slippage_bps / 10000),
            intent.instrument.contract,
            ROUND_CEILING if sign == 1 else ROUND_FLOOR,
        )
        per_order, per_contract = (
            (self.limits.entry_fee_per_order, self.limits.entry_fee_per_contract)
            if sign == 1
            else (self.limits.exit_fee_per_order, self.limits.exit_fee_per_contract)
        )
        if (
            fill.price != expected
            or fill.fee != per_contract * fill.quantity + (per_order if index == 0 else 0)
            or (sign == 1 and fill.price > intent.limit_price)
            or (sign == -1 and fill.price < intent.limit_price)
        ):
            raise ValueError("OPTION_FILL_PRICE_OR_FEE_MISMATCH")

    @exact
    def assess(self, quote, underlying, *, now):
        now = clock(now)
        quote = OptionQuote.model_validate(quote.model_dump(warnings=False)) if quote else None
        underlying = (
            UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
            if underlying
            else None
        )
        with self.journal.write() as db:
            c = self._control(db)
            self._account(db, now, closing=True)
            snap = OptionVenueSnapshot.model_validate_json(c["snapshot_json"])
            if (
                not timedelta(0)
                <= now - snap.captured_at
                < timedelta(seconds=self.limits.account_max_age_seconds)
            ):
                raise ExecutionBlocked("OPTION_ACCOUNT_SUPERVISION_STALE")
            ledger = OptionLedger.model_validate_json(c["ledger_json"])
            p = ledger.position
            reason = p.exit_reason if p else None
            issue = None
            if p:
                if now >= p.contract.last_trading_at - timedelta(
                    seconds=self.policy.expiry_guard_seconds
                ):
                    reason = reason or "EXPIRY_GUARD"
                if now >= p.exit_at:
                    reason = reason or "TIME_EXIT"
                underlying_ok = (
                    underlying is not None
                    and underlying.symbol == p.contract.underlying
                    and underlying.source == self.limits.underlying_source
                    and underlying.complete
                    and underlying.entitlement == "REALTIME"
                    and underlying.bid <= underlying.ask
                    and _fresh(
                        underlying.source_at,
                        underlying.received_at,
                        now,
                        self.limits.quote_max_age_seconds,
                        self.limits.max_receive_lag_seconds,
                    )
                )
                quote_ok = (
                    quote is not None
                    and quote.instrument.contract == p.contract
                    and quote.instrument.provider == self.limits.provider
                    and quote.source == self.limits.option_source
                    and quote.complete
                    and quote.entitlement == "REALTIME"
                    and quote.bid is not None
                    and quote.bid > 0
                    and quote.bid_size > 0
                    and (quote.ask is None or quote.ask >= quote.bid)
                    and _fresh(
                        quote.source_at,
                        quote.received_at,
                        now,
                        self.limits.quote_max_age_seconds,
                        self.limits.max_receive_lag_seconds,
                    )
                )
                if underlying_ok and (
                    (
                        p.contract.right == "CALL"
                        and underlying.bid <= p.tightened_underlying_invalidation
                    )
                    or (
                        p.contract.right == "PUT"
                        and underlying.ask >= p.tightened_underlying_invalidation
                    )
                ):
                    reason = reason or "UNDERLYING_INVALIDATION"
                if quote_ok and quote.bid * p.quantity * p.contract.multiplier <= p.basis * (
                    1 - self.policy.premium_catastrophe_fraction
                ):
                    reason = reason or "PREMIUM_CATASTROPHE"
                if not quote_ok:
                    issue = "OPTION_UNPRICED_OR_STALE"
                elif not underlying_ok:
                    issue = "UNDERLYING_UNAVAILABLE_OR_STALE"
                p = p.model_copy(
                    update={
                        "exit_reason": reason,
                        "exit_required_at": p.exit_required_at or (now if reason else None),
                        "supervision_issue": issue,
                    }
                )
                ledger = ledger.model_copy(update={"position": p})
                db.execute(
                    "UPDATE execution_control SET ledger_json=? WHERE id=1",
                    (ledger.model_dump_json(),),
                )
            status = "BLOCKED" if issue else "EXIT_REQUIRED" if reason else "HEALTHY"
            payload = {
                "status": status,
                "exit_reason": reason,
                "issue": issue,
                "entry_client_id": p.entry_client_id if p else None,
                "snapshot_id": snap.snapshot_id,
            }
            db.execute(
                "INSERT INTO execution_supervisor VALUES(1,?,'HEALTHY',NULL,1,?,?,NULL,NULL) ON CONFLICT(id) DO UPDATE SET status=excluded.status,heartbeat_at=excluded.heartbeat_at,result_json=excluded.result_json",
                (
                    self.policy.model_dump_json(),
                    now.isoformat(),
                    json.dumps(payload, sort_keys=True),
                ),
            )
            if issue:
                db.execute("UPDATE execution_supervisor SET status='BLOCKED' WHERE id=1")
                self._halt(db, issue, now)
            self.journal.event(db, now, "POSITION_SUPERVISED", payload)
            return payload

    async def protective_tick(self, quote, underlying, *, now):
        result = await self.reconcile_fixture(now=now)
        if not result["reconciled"]:
            return result
        assessed = self.assess(quote, underlying, now=now)
        if assessed["status"] != "EXIT_REQUIRED":
            return assessed
        with self.journal.read() as db:
            if db.execute("SELECT 1 FROM execution_orders WHERE active_lock=1").fetchone():
                return {"status": "EXIT_BLOCKED", "reason": "OPTION_ORDER_ALREADY_IN_FLIGHT"}
            p = OptionLedger.model_validate_json(self._control(db)["ledger_json"]).position
            entry = OptionIntent.model_validate_json(
                db.execute(
                    "SELECT intent_json FROM execution_orders WHERE client_id=?",
                    (p.entry_client_id,),
                ).fetchone()[0]
            )
            failed_exit = db.execute(
                "SELECT 1 FROM execution_orders WHERE json_extract(intent_json,'$.side')='SELL' AND status IN ('REJECTED','CANCELED','EXPIRED') AND json_extract(intent_json,'$.prepared_at') >= ?",
                (entry.prepared_at.isoformat(),),
            ).fetchone()
            exited = sum(
                json.loads(r[0])["quantity"]
                for r in db.execute(
                    "SELECT payload FROM execution_fills WHERE client_id IN (SELECT client_id FROM execution_orders WHERE json_extract(intent_json,'$.side')='SELL')"
                )
            )
        if failed_exit:
            with self.journal.write() as db:
                self._halt(db, "OPTION_EXIT_REVIEW_REQUIRED", clock(now))
            return {"status": "EXIT_REVIEW_REQUIRED", "reason": "OPTION_EXIT_REVIEW_REQUIRED"}
        proposal = OptionProposal(
            action="CLOSE",
            contract=p.contract,
            thesis="Deterministic protective exit: " + p.exit_reason,
        )
        prepared = self.prepare(
            f"protective:{p.entry_client_id}:{exited}",
            proposal,
            quote,
            None,
            now=now,
            origin="PROTECTIVE",
        )
        if prepared["status"] != "PREPARED":
            return prepared
        status = await self.dispatch(prepared["client_id"], quote, None, now=now)
        return {"status": status, "client_id": prepared["client_id"], "exit_reason": p.exit_reason}

    @exact
    def tighten_invalidation(self, price, quote, underlying, *, now):
        self.assess(quote, underlying, now=now)
        with self.journal.write() as db:
            ledger = OptionLedger.model_validate_json(self._control(db)["ledger_json"])
            p = ledger.position
            if p is None or p.supervision_issue is not None or p.exit_reason is not None:
                raise ExecutionBlocked("OPTION_TIGHTENING_UNAVAILABLE")
            changed = p.model_copy(update={"tightened_underlying_invalidation": price})
            changed = type(p).model_validate(changed.model_dump(warnings=False))
            price = changed.tightened_underlying_invalidation
            if (
                p.contract.right == "CALL"
                and not p.tightened_underlying_invalidation <= price < underlying.bid
            ) or (
                p.contract.right == "PUT"
                and not underlying.ask < price <= p.tightened_underlying_invalidation
            ):
                raise ExecutionBlocked("OPTION_INVALIDATION_CANNOT_WIDEN_OR_CROSS")
            db.execute(
                "UPDATE execution_control SET ledger_json=? WHERE id=1",
                (ledger.model_copy(update={"position": changed}).model_dump_json(),),
            )
            self.journal.event(
                db, clock(now), "OPTION_INVALIDATION_TIGHTENED", {"price": str(price)}
            )

    def resume(self, reason, *, expected_revision, now):
        now = clock(now)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            raise ValueError("A bounded reviewed recovery reason is required")
        with self.journal.write() as db:
            if self.journal.revision(db) != expected_revision:
                raise ExecutionBlocked("OPTION_REVIEW_REVISION_CHANGED")
            account = self._account(db, now)
            if (
                account.entry_blockers
                or account.working_orders
                or not account.budgets_known
                or not timedelta(0)
                <= now - account.captured_at
                < timedelta(seconds=self.limits.account_max_age_seconds)
            ):
                raise ExecutionBlocked("OPTION_RECOVERY_EVIDENCE_REQUIRED")
            db.execute("UPDATE execution_control SET halted=0,halt_reason=NULL WHERE id=1")
            self.journal.event(
                db,
                now,
                "OPTION_REVIEWED_RESUME",
                {"reason": reason, "expected_revision": expected_revision},
            )

    @exact
    def begin_model_attempt(self, source_key, input_hash, *, now):
        now = clock(now)
        policy = self.policy.cost_policy
        if (
            policy is None
            or not isinstance(source_key, str)
            or not source_key.strip()
            or len(source_key) > 128
            or not isinstance(input_hash, str)
            or len(input_hash) != 64
            or any(c not in "0123456789abcdef" for c in input_hash)
        ):
            raise ValueError("Explicit frozen model policy and input hash required")
        with self.journal.write() as db:
            account = self._account(db, now)
            costs = economics.summary(db, now)
            day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            window = self.calendar.current_window(now)
            if (
                account.entry_halted
                or account.entry_blockers
                or not account.budgets_known
                or account.position is not None
                or account.working_orders
                or not timedelta(0)
                <= now - account.captured_at
                < timedelta(seconds=self.limits.account_max_age_seconds)
                or window is None
                or now >= window.closes_at - timedelta(minutes=self.policy.entry_cutoff_minutes)
                or policy.max_call_cost
                > min(
                    account.daily_loss_available,
                    account.total_loss_available,
                    account.settled_cash - account.reserved_cash,
                )
                or Decimal(costs["known_cost"]) + policy.max_call_cost > policy.total_budget
                or Decimal(costs["daily_cost"].get(day, "0")) + policy.max_call_cost
                > policy.daily_budget
            ):
                raise ExecutionBlocked("OPTION_MODEL_ADMISSION_BLOCKED")
            if (
                db.execute(
                    "SELECT 1 FROM execution_model_calls WHERE source_key=?", (source_key,)
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM execution_option_decisions WHERE source_key=?", (source_key,)
                ).fetchone()
            ):
                raise ExecutionBlocked("OPTION_MODEL_SOURCE_ALREADY_ATTEMPTED")
            db.execute(
                "INSERT INTO execution_model_calls VALUES(?,?,?,NULL,NULL,NULL,NULL)",
                (source_key, input_hash, now.isoformat()),
            )
            self.journal.event(
                db,
                now,
                "OPTION_MODEL_ATTEMPT_ADMITTED",
                {"source_key": source_key, "input_hash": input_hash},
            )

    @exact
    def record_model_usage(self, source_key, usage, proposal, *, now):
        usage = UsageEvidence.model_validate(usage.model_dump(warnings=False))
        proposal = OptionProposal.model_validate(proposal.model_dump(warnings=False))
        policy = self.policy.cost_policy
        if policy is None or usage.model != policy.model:
            raise ValueError("Frozen model identity required")
        cost = (
            usage.input_tokens * policy.input_per_million
            + usage.output_tokens * policy.output_per_million
        ) / 1000000
        with self.journal.write() as db:
            self._control(db)
            row = db.execute(
                "SELECT * FROM execution_model_calls WHERE source_key=?", (source_key,)
            ).fetchone()
            if row is None:
                raise ExecutionBlocked("OPTION_MODEL_ATTEMPT_MISSING")
            values = (usage.model_dump_json(), usage.request_id, fingerprint(proposal), str(cost))
            if row["cost"] is not None:
                if (
                    tuple(row[k] for k in ("usage_json", "request_id", "decision_hash", "cost"))
                    != values
                ):
                    raise ExecutionBlocked("OPTION_MODEL_RECEIPT_CONFLICT")
                return cost
            if clock(now) < datetime.fromisoformat(row["started_at"]):
                raise ValueError("Model receipt predates its durable attempt")
            db.execute(
                "UPDATE execution_model_calls SET usage_json=?,request_id=?,decision_hash=?,cost=? WHERE source_key=?",
                (*values, source_key),
            )
            self.journal.event(
                db,
                clock(now),
                "OPTION_MODEL_USAGE_RECORDED",
                {
                    "source_key": source_key,
                    "usage": usage.model_dump(mode="json"),
                    "cost": str(cost),
                },
            )
            if cost > policy.max_call_cost:
                self._halt(db, "MODEL_COST_BOUND_EXCEEDED", clock(now))
            return cost
