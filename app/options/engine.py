"""Durable options PAPER lifecycle on the existing journal/restore/ownership foundation."""

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, localcontext
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
from app.options.governor import admit_option
from app.options.lifecycle import (
    CALENDAR_SOURCE,
    TERMINAL,
    EntryPremiumProtection,
    EntryProtection,
    OptionExecutionPolicy,
    OptionIntent,
    OptionLedger,
    OptionVenueSnapshot,
    PositionExitProtection,
    TargetExitSchedule,
)
from app.options.models import (
    OptionAccount,
    OptionAdmission,
    OptionHolding,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    SessionWindow,
    UnderlyingQuote,
)
from app.options.process import run_option_process
from app.options.protection import assess_position, verify_premium_binding
from app.options.venue import DurableOptionVenue, private_path
from app.robinhood.schedule import XNYSCalendar

ZERO = Decimal(0)
OWNER = object()


class EntryModelBlocked(ExecutionBlocked):
    """An expected entry-risk pause, with no admitted model call or global halt."""


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
    extra_tables = frozenset(
        {
            "execution_option_loss_control",
            "execution_option_loss_outcomes",
            "execution_option_decisions",
            "execution_option_receipts",
            "execution_option_progress",
            "execution_option_health",
            "execution_option_strategy",
            "execution_option_opportunities",
            "execution_option_runtime",
            "execution_option_runtime_slots",
            "execution_option_swing_seeds",
            "execution_option_swing_terminals",
            "execution_option_scope_watch_policy",
            "execution_option_scope_watches",
            "execution_option_scope_watch_actions",
        }
    )

    @staticmethod
    def _loss_state(db):
        from app.options.loss_control import stored_state

        return stored_state(db)

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
                "loss_control": self._loss_state(db),
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
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_progress(entry_client_id TEXT PRIMARY KEY,payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_health(entry_client_id TEXT PRIMARY KEY,payload TEXT NOT NULL)"
            )
            if self.policy.loss_control is not None:
                from app.options.loss_control import enroll

                enroll(self, db, now, create=create)
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

    def refresh_loss_control(self, *, now):
        from app.options.loss_control import refresh

        with self.journal.write() as db:
            self._control(db)
            return refresh(self, db, clock(now))

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
        from app.options.runtime_state import entry_reasons

        blockers.extend(entry_reasons(db, now))
        runtime = getattr(self, "_option_runtime", None)
        if runtime is not None and runtime.stop is not None and runtime.stop.is_set():
            blockers.append("OPTION_RUNTIME_STOP_REQUESTED")
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
        self,
        source_key,
        proposal,
        quote=None,
        underlying=None,
        *,
        now,
        origin="DETERMINISTIC",
        ceiling=None,
        entry_request=None,
        entry_result=None,
        target_exit_schedule=None,
        target_exit_stage=None,
        entry_premium_protection=None,
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
        if (entry_request is None) != (entry_result is None) or (
            entry_request is not None and (origin != "MODEL" or ceiling is not None)
        ):
            raise ValueError("Full paired model entry receipt required without a separate ceiling")
        inputs = {
            "proposal": proposal.model_dump(mode="json"),
            "quote": quote.model_dump(mode="json") if quote else None,
            "underlying": underlying.model_dump(mode="json") if underlying else None,
            "origin": origin,
        }
        bound_inputs = {
            "proposal": proposal,
            "quote": quote,
            "underlying": underlying,
            "origin": origin,
        }
        health_policy = self.policy.health_management if proposal.action == "OPEN_LONG" else None
        if health_policy is not None:
            inputs["health_management"] = bound_inputs["health_management"] = health_policy
        floor_policy = self.policy.trade_floor if proposal.action == "OPEN_LONG" else None
        if floor_policy is not None:
            inputs["trade_floor"] = bound_inputs["trade_floor"] = floor_policy
        trail_policy = self.policy.premium_trail if proposal.action == "OPEN_LONG" else None
        if trail_policy is not None:
            inputs["premium_trail"] = bound_inputs["premium_trail"] = trail_policy
        if target_exit_schedule is not None:
            target_exit_schedule = TargetExitSchedule.model_validate(
                target_exit_schedule.model_dump(warnings=False)
            )
            inputs["target_exit_schedule"] = target_exit_schedule.model_dump(mode="json")
            bound_inputs["target_exit_schedule"] = target_exit_schedule
        if entry_premium_protection is not None:
            entry_premium_protection = EntryPremiumProtection.model_validate(
                entry_premium_protection.model_dump(warnings=False)
            )
            inputs["entry_premium_protection"] = entry_premium_protection.model_dump(mode="json")
            bound_inputs["entry_premium_protection"] = entry_premium_protection
        if target_exit_stage is not None:
            inputs["target_exit_stage"] = bound_inputs["target_exit_stage"] = target_exit_stage
        if entry_request is not None:
            from app.options.entry_judgment import EntryRequest, EntryResult

            entry_request = EntryRequest.model_validate(entry_request.model_dump(warnings=False))
            entry_result = EntryResult.model_validate(entry_result.model_dump(warnings=False))
            for key, value in (("entry_request", entry_request), ("entry_result", entry_result)):
                inputs[key] = value.model_dump(mode="json")
                bound_inputs[key] = value
        if ceiling is not None:
            ceiling = OptionAdmission.model_validate(ceiling.model_dump(warnings=False))
            inputs["ceiling"] = ceiling.model_dump(mode="json")
            bound_inputs["ceiling"] = ceiling
        digest = fingerprint(bound_inputs)
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
            entry_review = None
            lineage = None
            strategy_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_option_strategy'"
            ).fetchone()
            strategy = (
                db.execute(
                    "SELECT policy_json FROM execution_option_strategy WHERE id=1"
                ).fetchone()
                if strategy_table
                else None
            )
            if (
                proposal.action == "OPEN_LONG"
                and strategy
                and "entry_model" in json.loads(strategy[0])
                and entry_request is None
            ):
                reason = "FULL_ENTRY_PLAN_REQUIRED"
            if origin == "MODEL":
                model = db.execute(
                    "SELECT * FROM execution_model_calls WHERE source_key=?", (source_key,)
                ).fetchone()
                if (
                    model is None
                    or model["cost"] is None
                    or model["decision_hash"]
                    != fingerprint(entry_result.plan if entry_result is not None else proposal)
                ):
                    reason = "OPTION_MODEL_RECEIPT_REQUIRED"
            try:
                from app.options.scope_admission import reject_unlinked_scope_entry
                from app.options.shared_strategy import review_shared_entry

                reject_unlinked_scope_entry(db, proposal)
                from app.options.loss_control import guard_entry

                guard_entry(self, db, proposal, now, source_key=source_key, quote=quote)
                review_shared_entry(self, db, source_key, proposal, quote, underlying, now)
                if proposal.action == "OPEN_LONG" and quote is not None:
                    from app.options.entry_lineage import selected_lineage

                    lineage = selected_lineage(db, source_key, quote.instrument)
                account = (
                    self._account(db, now, closing=proposal.action == "CLOSE")
                    if proposal.action != "HOLD"
                    else None
                )
                session = self._session(proposal.contract, now) if proposal.contract else None
                if entry_request is not None:
                    from app.options.entry_coordination import review_for_execution

                    entry_review = review_for_execution(
                        self, db, source_key, entry_request, entry_result, quote, underlying, now
                    )
                    if entry_review.outcome != "ELIGIBLE" or entry_review.proposal != proposal:
                        raise ExecutionBlocked(
                            "OPTION_ENTRY_PLAN_REJECTED:" + ";".join(entry_review.reasons)
                        )
                    result = entry_review.admission
                else:
                    result = admit_option(
                        proposal,
                        quote,
                        underlying,
                        account,
                        self._effective_limits(),
                        session,
                        now=now,
                    )
                if result.outcome == "APPROVED" and proposal.close_quantity is not None:
                    self._review_partial_close(db, proposal, quote, underlying, now, origin)
                if target_exit_schedule is not None:
                    if (
                        self.policy.target_exits is None
                        or origin != "DETERMINISTIC"
                        or proposal.action != "OPEN_LONG"
                        or entry_request is not None
                    ):
                        raise ExecutionBlocked("OPTION_TARGET_ENTRY_NOT_ENROLLED")
                    if target_exit_schedule.has_stops and self.policy.target_stops is None:
                        raise ExecutionBlocked("OPTION_TARGET_STOPS_NOT_ENROLLED")
                    if result.outcome == "APPROVED":
                        if target_exit_schedule.entry_quantity != result.quantity:
                            raise ExecutionBlocked("OPTION_TARGET_ENTRY_QUANTITY_CHANGED")
                        target_exit_schedule.check_direction(
                            proposal.contract.right,
                            underlying.ask if proposal.contract.right == "CALL" else underlying.bid,
                        )
                        target_exit_schedule.check_stops(
                            proposal.contract.right, proposal.underlying_invalidation
                        )
                if target_exit_stage is not None:
                    from app.options.target_exits import review_close

                    review_close(self, db, proposal, target_exit_stage, origin)
                if entry_premium_protection is not None:
                    if (
                        self.policy.entry_premium_protection is None
                        or origin != "DETERMINISTIC"
                        or proposal.action != "OPEN_LONG"
                        or entry_request is not None
                    ):
                        raise ExecutionBlocked("OPTION_ENTRY_PREMIUM_NOT_ENROLLED")
                    if (
                        entry_premium_protection.maximum_loss_fraction
                        > self.policy.premium_catastrophe_fraction
                    ):
                        raise ExecutionBlocked("OPTION_ENTRY_PREMIUM_CANNOT_WIDEN")
            except (ValueError, ExecutionBlocked) as exc:
                reason = str(exc)
                result = None
            if ceiling is not None:
                if (
                    ceiling.outcome != "APPROVED"
                    or ceiling.action != "OPEN_LONG"
                    or proposal.action != "OPEN_LONG"
                    or proposal.contract is None
                    or ceiling.contract_id != proposal.contract.contract_id
                    or ceiling.valid_until is None
                    or not ceiling.approved_at <= now < ceiling.valid_until
                    or min(
                        ceiling.quantity,
                        ceiling.limit_price,
                        ceiling.entry_debit,
                        ceiling.full_premium_loss,
                    )
                    <= 0
                ):
                    reason = "OPTION_ORIGINAL_ADMISSION_REQUIRED"
                elif result is not None and result.outcome == "APPROVED":
                    if any(
                        getattr(result, field) > getattr(ceiling, field)
                        for field in ("quantity", "limit_price", "entry_debit", "full_premium_loss")
                    ):
                        reason = "OPTION_ORIGINAL_ADMISSION_CEILING_EXCEEDED"
                    else:
                        result = result.model_copy(
                            update={"valid_until": min(result.valid_until, ceiling.valid_until)}
                        )
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
                    protection = None
                    if entry_review is not None:
                        exit_at = min(exit_at, entry_review.exit_by)
                        protection = EntryProtection(
                            packet_hash=entry_review.packet_hash,
                            plan_hash=fingerprint(entry_review.plan),
                            underlying_target=entry_review.plan.underlying_target,
                            exit_by=entry_review.exit_by,
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
                        order_expires_at=min(session.closes_at, exit_at)
                        if protection
                        else session.closes_at,
                        exit_at=exit_at
                        if proposal.action == "OPEN_LONG"
                        else ledger.position.exit_at,
                        original_underlying_invalidation=stop,
                        thesis=proposal.thesis,
                        entry_protection=protection,
                        entry_lineage=lineage,
                        closing_entry_client_id=ledger.position.entry_client_id
                        if proposal.action == "CLOSE"
                        else None,
                        requested_close_quantity=proposal.close_quantity,
                        target_exit_schedule=target_exit_schedule,
                        target_exit_stage=target_exit_stage,
                        entry_premium_protection=entry_premium_protection,
                        premium_trail=trail_policy,
                        trade_floor=floor_policy,
                        health_management=health_policy,
                    )
                    approval = {
                        **inputs,
                        "admission": result.model_dump(mode="json"),
                        "account": account.model_dump(mode="json"),
                        "effective_limits": self._effective_limits().model_dump(mode="json"),
                    }
                    if lineage is not None:
                        approval["entry_lineage"] = lineage.model_dump(mode="json")
                    if intent.closing_entry_client_id is not None:
                        approval["closing_entry_client_id"] = intent.closing_entry_client_id
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
                from app.options.entry_lineage import verified_lineage
                from app.options.target_exits import review_close, verify_binding

                verified_lineage(db, intent, approval)
                verify_binding(intent, approval)
                verify_premium_binding(intent, approval)
                from app.options.health_management import verify_binding as verify_health
                from app.options.premium_trail import verify_binding as verify_trail
                from app.options.trade_floor import verify_binding as verify_floor

                verify_health(intent, approval)
                if (
                    intent.side == "BUY"
                    and intent.health_management != self.policy.health_management
                ):
                    raise ExecutionBlocked("OPTION_HEALTH_POLICY_NOT_ENROLLED")
                verify_floor(intent, approval)
                if intent.side == "BUY" and intent.trade_floor != self.policy.trade_floor:
                    raise ExecutionBlocked("OPTION_TRADE_FLOOR_NOT_ENROLLED")
                verify_trail(intent, approval)
                if intent.side == "BUY" and intent.premium_trail != self.policy.premium_trail:
                    raise ExecutionBlocked("OPTION_PREMIUM_TRAIL_NOT_ENROLLED")
                if intent.entry_premium_protection is not None and (
                    self.policy.entry_premium_protection is None
                    or intent.entry_premium_protection.maximum_loss_fraction
                    > self.policy.premium_catastrophe_fraction
                ):
                    raise ExecutionBlocked("OPTION_ENTRY_PREMIUM_CANNOT_WIDEN")
                if intent.target_exit_schedule is not None:
                    if self.policy.target_exits is None:
                        raise ExecutionBlocked("OPTION_TARGET_NOT_ENROLLED")
                    if intent.target_exit_schedule.has_stops and self.policy.target_stops is None:
                        raise ExecutionBlocked("OPTION_TARGET_STOPS_NOT_ENROLLED")
                    if underlying is None:
                        raise ExecutionBlocked("OPTION_TARGET_UNDERLYING_REQUIRED")
                    intent.target_exit_schedule.check_direction(
                        intent.instrument.contract.right,
                        underlying.ask
                        if intent.instrument.contract.right == "CALL"
                        else underlying.bid,
                    )
                if intent.target_exit_stage is not None:
                    review_close(
                        self, db, proposal, intent.target_exit_stage, approval.get("origin")
                    )
                if intent.requested_close_quantity != proposal.close_quantity or (
                    intent.requested_close_quantity is not None
                    and approval["admission"]["quantity"] != intent.quantity
                ):
                    raise ExecutionBlocked("OPTION_CLOSE_QUANTITY_CHANGED")
                if (
                    intent.closing_entry_client_id is not None
                    or "closing_entry_client_id" in approval
                ):
                    held = OptionLedger.model_validate_json(
                        self._control(db)["ledger_json"]
                    ).position
                    if (
                        held is None
                        or intent.closing_entry_client_id != held.entry_client_id
                        or approval.get("closing_entry_client_id") != intent.closing_entry_client_id
                    ):
                        raise ExecutionBlocked("OPTION_CLOSING_ENTRY_CHANGED")
                if now >= intent.approval_expires_at or now < intent.prepared_at:
                    raise ExecutionBlocked("OPTION_APPROVAL_EXPIRED")
                if quote.instrument != intent.instrument:
                    raise ExecutionBlocked("OPTION_INSTRUMENT_MAPPING_CHANGED")
                if (intent.entry_protection is None) != ("entry_request" not in approval):
                    raise ExecutionBlocked("OPTION_ENTRY_PROTECTION_MISSING")
                from app.options.scope_admission import reject_unlinked_scope_entry
                from app.options.shared_strategy import review_shared_entry

                reject_unlinked_scope_entry(db, proposal)
                from app.options.loss_control import guard_entry

                guard_entry(
                    self,
                    db,
                    proposal,
                    now,
                    exclude=client_id,
                    source_key=intent.source_key,
                    quote=quote,
                )
                review_shared_entry(self, db, intent.source_key, proposal, quote, underlying, now)
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
                if result.outcome == "APPROVED" and proposal.close_quantity is not None:
                    self._review_partial_close(
                        db, proposal, quote, underlying, now, approval.get("origin")
                    )
                management = intent.position_protection is not None
                if management != (approval.get("origin") == "POSITION_MODEL"):
                    raise ExecutionBlocked("POSITION_PROTECTION_MISSING")
                if management != ("position_request" in approval) or management != (
                    "position_result" in approval
                ):
                    raise ExecutionBlocked("FULL_POSITION_RECEIPT_REQUIRED")
                if management:
                    from app.options.position_coordination import review_for_execution
                    from app.options.position_judgment import PositionRequest, PositionResult

                    review = review_for_execution(
                        self,
                        db,
                        intent.source_key,
                        PositionRequest.model_validate(approval["position_request"]),
                        PositionResult.model_validate(approval["position_result"]),
                        quote,
                        underlying,
                        now,
                        exclude=client_id,
                    )
                    if (
                        review.outcome != "ELIGIBLE"
                        or review.proposal != proposal
                        or review.plan.action != "EXIT_ALL"
                    ):
                        raise ExecutionBlocked(
                            "POSITION_DISPATCH_REJECTED:" + ";".join(review.reasons)
                        )
                    expected = PositionExitProtection(
                        packet_hash=review.packet_hash,
                        plan_hash=fingerprint(review.plan),
                        entry_client_id=review.plan.entry_client_id,
                        position_revision=review.plan.position_revision,
                    )
                    if intent.position_protection != expected:
                        raise ExecutionBlocked("POSITION_PROTECTION_CHANGED")
                    result = review.admission
                if intent.entry_protection is not None:
                    from app.options.entry_coordination import review_for_execution
                    from app.options.entry_judgment import EntryRequest, EntryResult

                    review = review_for_execution(
                        self,
                        db,
                        intent.source_key,
                        EntryRequest.model_validate(approval["entry_request"]),
                        EntryResult.model_validate(approval["entry_result"]),
                        quote,
                        underlying,
                        now,
                        exclude=client_id,
                    )
                    if review.outcome != "ELIGIBLE" or review.proposal != proposal:
                        raise ExecutionBlocked(
                            "OPTION_ENTRY_DISPATCH_REJECTED:" + ";".join(review.reasons)
                        )
                    expected = EntryProtection(
                        packet_hash=review.packet_hash,
                        plan_hash=fingerprint(review.plan),
                        underlying_target=review.plan.underlying_target,
                        exit_by=review.exit_by,
                    )
                    if expected != intent.entry_protection or intent.exit_at > review.exit_by:
                        raise ExecutionBlocked("OPTION_ENTRY_PROTECTION_CHANGED")
                    result = review.admission
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
        from app.options.premium_trail import terms as trail_terms
        from app.options.trade_floor import terms as floor_terms

        if state.position and (
            state.position.contract != snap.position.contract
            or state.position.quantity != snap.position.quantity
            or state.position.basis != snap.position.basis
            or state.position.lots != snap.position.lots
            or state.position.original_underlying_invalidation
            != snap.position.original_underlying_invalidation
            or state.position.exit_at != snap.position.exit_at
            or state.position.entry_client_id != snap.position.entry_client_id
            or state.position.entry_protection != snap.position.entry_protection
            or state.position.entry_premium_protection != snap.position.entry_premium_protection
            or state.position.target_exit_schedule != snap.position.target_exit_schedule
            or floor_terms(state.position) != floor_terms(snap.position)
            or trail_terms(state.position) != trail_terms(snap.position)
        ):
            raise ValueError("OPTION_POSITION_TERMS_MISMATCH")
        prior = OptionLedger.model_validate_json(c["ledger_json"])
        if (
            state.position
            and prior.position
            and state.position.entry_client_id == prior.position.entry_client_id
        ):
            if floor_terms(prior.position) != floor_terms(state.position):
                raise ValueError("OPTION_TRADE_FLOOR_ENROLLMENT_CHANGED")
            trail = state.position.premium_trail
            prior_trail = prior.position.premium_trail
            if prior_trail is not None and prior_trail.entry_basis is not None:
                if trail_terms(prior.position) != trail_terms(state.position):
                    raise ValueError("OPTION_PREMIUM_TRAIL_BASIS_CHANGED")
                trail = prior_trail
            state = state.model_copy(
                update={
                    "position": state.position.model_copy(
                        update={
                            "premium_trail": trail,
                            **{
                                k: getattr(prior.position, k)
                                for k in (
                                    "tightened_underlying_invalidation",
                                    "exit_reason",
                                    "exit_required_at",
                                    "supervision_issue",
                                    "target_exit_stage",
                                    "trade_floor",
                                )
                            },
                        }
                    )
                }
            )
        return state, observations, new_fills, new_receipts

    def _validate_fill(self, intent, fill, index, used):
        from app.options.fill_evidence import validate_fill

        validate_fill(self.limits, intent, fill, index, used)

    def _assess_owned(self, db, ledger, quote, underlying, now):
        """Refresh enrolled cash protection inside the caller's audited write transaction."""
        p = assess_position(ledger.position, quote, underlying, self.limits, self.policy, now=now)
        if p.trade_floor is not None and p.target_exit_stage:
            from app.options.trade_floor import refresh

            # The verified native reader must see the newly latched target stage.
            db.execute(
                "UPDATE execution_control SET ledger_json=? WHERE id=1",
                (ledger.model_copy(update={"position": p}).model_dump_json(),),
            )
            p = refresh(db, p, self.limits.population_id)
            p = assess_position(p, quote, underlying, self.limits, self.policy, now=now)
        from app.options.progress_health import record

        progress = record(self, db, p, quote, underlying, now)
        if self.policy.health_management is not None:
            from app.options.health_management import assess

            p = assess(self, db, p, quote, underlying, progress, now)
        return p

    def _review_partial_close(self, db, proposal, quote, underlying, now, origin):
        """An explicit scale-out cannot postpone a freshly observed mandatory full exit."""
        if self.policy.partial_closes is None:
            raise ExecutionBlocked("OPTION_PARTIAL_CLOSE_NOT_ENROLLED")
        if origin != "DETERMINISTIC":
            raise ExecutionBlocked("OPTION_PARTIAL_CLOSE_DETERMINISTIC_ONLY")
        ledger = OptionLedger.model_validate_json(self._control(db)["ledger_json"])
        position = ledger.position
        # Common admission has already verified exact ownership and the requested cap.
        if proposal.close_quantity == position.quantity:
            return
        assessed = self._assess_owned(db, ledger, quote, underlying, now)
        if assessed != position:
            db.execute(
                "UPDATE execution_control SET ledger_json=? WHERE id=1",
                (ledger.model_copy(update={"position": assessed}).model_dump_json(),),
            )
            self.journal.event(
                db,
                now,
                "OPTION_PARTIAL_CLOSE_PROTECTION_REVIEW",
                {
                    "entry_client_id": position.entry_client_id,
                    "position": assessed.model_dump(mode="json"),
                },
            )
        if assessed.exit_reason is not None:
            raise ExecutionBlocked("OPTION_PARTIAL_CLOSE_FULL_EXIT_REQUIRED")
        if assessed.supervision_issue is not None:
            raise ExecutionBlocked("OPTION_PARTIAL_CLOSE_FRESH_PROTECTION_REQUIRED")
        from app.options.trade_floor import blocked

        if blocked(assessed):
            raise ExecutionBlocked("OPTION_TRADE_FLOOR_EVIDENCE_REQUIRED")
        from app.options.health_management import blocked as health_blocked

        if health_blocked(self, db, assessed):
            raise ExecutionBlocked("OPTION_HEALTH_EVIDENCE_REQUIRED")

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
                p = self._assess_owned(db, ledger, quote, underlying, now)
                reason, issue = p.exit_reason, p.supervision_issue
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
                **(
                    {"trade_floor": p.trade_floor.model_dump(mode="json")}
                    if p and p.trade_floor
                    else {}
                ),
                **(
                    {"premium_trail": p.premium_trail.model_dump(mode="json")}
                    if p and p.premium_trail is not None
                    else {}
                ),
                **(
                    {"target_exit_stage": p.target_exit_stage}
                    if p and p.target_exit_schedule is not None
                    else {}
                ),
                **(
                    {"target_stop_price": str(p.tightened_underlying_invalidation)}
                    if p and p.target_exit_schedule is not None and p.target_exit_schedule.has_stops
                    else {}
                ),
            }
            if p and self.policy.health_management is not None:
                from app.options.health_management import stored

                payload["health_management"] = stored(db, p.entry_client_id)
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
        if assessed["status"] == "HEALTHY" and self.policy.target_exits is not None:
            if assessed.get("health_management", {}).get("status") == "INCOMPLETE":
                return {**assessed, "status": "HEALTH_MANAGEMENT_BLOCKED"}
            if set(assessed.get("trade_floor", {}).get("reasons", ())) - {
                "UNRESOLVED_POSITION_ORDER"
            }:
                return {**assessed, "status": "TRADE_FLOOR_BLOCKED"}
            from app.options.target_exits import tick

            return await tick(self, quote, underlying, now=now, assessed=assessed)
        if assessed["status"] != "EXIT_REQUIRED":
            return assessed
        with self.journal.write() as db:
            p = OptionLedger.model_validate_json(self._control(db)["ledger_json"]).position
            active = db.execute("SELECT * FROM execution_orders WHERE active_lock=1").fetchone()
            if active:
                pending = OptionIntent.model_validate_json(active["intent_json"])
                if (
                    active["status"] == "PREPARED"
                    and active["attempted_at"] is None
                    and pending.closing_entry_client_id == p.entry_client_id
                    and pending.requested_close_quantity is not None
                    and pending.requested_close_quantity < p.quantity
                ):
                    # This intent never left the journal. No broker cancellation or
                    # replay of an attempted/unknown order is permitted here.
                    db.execute(
                        "UPDATE execution_orders SET status='REJECTED',active_lock=NULL WHERE client_id=?",
                        (pending.client_id,),
                    )
                    self.journal.event(
                        db,
                        clock(now),
                        "OPTION_PARTIAL_CLOSE_SUPERSEDED",
                        {"reason": p.exit_reason, "entry_client_id": p.entry_client_id},
                        client_id=pending.client_id,
                    )
                else:
                    return {"status": "EXIT_BLOCKED", "reason": "OPTION_ORDER_ALREADY_IN_FLIGHT"}
            entry = OptionIntent.model_validate_json(
                db.execute(
                    "SELECT intent_json FROM execution_orders WHERE client_id=?",
                    (p.entry_client_id,),
                ).fetchone()[0]
            )
            failed_exit = db.execute(
                "SELECT 1 FROM execution_orders WHERE json_extract(intent_json,'$.side')='SELL' AND status IN ('REJECTED','CANCELED','EXPIRED') AND json_extract(intent_json,'$.prepared_at') >= ? AND (attempted_at IS NOT NULL OR json_extract(intent_json,'$.requested_close_quantity') IS NULL)",
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
            self._resume(db, reason, expected_revision=expected_revision, now=now)

    def _resume(self, db, reason, *, expected_revision, now):
        """Same revision/recovery gate inside an authenticated command transaction."""
        if self.journal.revision(db) != expected_revision:
            raise ExecutionBlocked("OPTION_REVIEW_REVISION_CHANGED")
        account = self._account(db, now)
        if (
            account.entry_blockers
            or account.working_orders
            or not account.budgets_known
            or db.execute(
                "SELECT 1 FROM execution_model_calls WHERE cost IS NULL LIMIT 1"
            ).fetchone()
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
    def begin_model_attempt(self, source_key, input_hash, *, now, position_request=None):
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
        blocked = None
        with self.journal.write() as db:
            if position_request is None and self.policy.loss_control is not None:
                from app.options.loss_control import model_family_reasons, refresh

                state = refresh(self, db, now)
                reasons = list(state["reasons"]) or model_family_reasons(
                    self, db, source_key, state
                )
                if reasons:
                    blocked = ";".join(reasons)
                    self.journal.event(
                        db,
                        now,
                        "OPTION_ENTRY_MODEL_RISK_PAUSED",
                        {
                            "source_key": source_key,
                            "input_hash": input_hash,
                            "reasons": reasons,
                        },
                    )
            if blocked is None:
                self._admit_model_attempt(db, source_key, input_hash, now, position_request)
        # Raise after committing recognition/cooldown and the pause receipt. A
        # blocked attempt creates no unknown-cost row and cannot call a worker.
        if blocked is not None:
            raise EntryModelBlocked(blocked)

    def _admit_model_attempt(self, db, source_key, input_hash, now, position_request):
        policy = self.policy.cost_policy
        if position_request is not None:
            from app.options.position_coordination import validate_admission

            validate_admission(self, db, source_key, position_request, input_hash, now)
        account = self._account(db, now)
        costs = economics.summary(db, now)
        day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        window = self.calendar.current_window(now)
        if (
            account.entry_halted
            or account.entry_blockers
            or not account.budgets_known
            or (account.position is not None and position_request is None)
            or account.working_orders
            or not timedelta(0)
            <= now - account.captured_at
            < timedelta(seconds=self.limits.account_max_age_seconds)
            or window is None
            or (
                position_request is None
                and now >= window.closes_at - timedelta(minutes=self.policy.entry_cutoff_minutes)
            )
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
        proposal = OptionProposal.model_validate(proposal.model_dump(warnings=False))
        return self._record_model_usage(source_key, usage, proposal, now=now)

    def record_entry_usage(self, source_key, usage, plan, *, now):
        from app.options.entry_reasoning import EntryPlan

        plan = EntryPlan.model_validate(plan.model_dump(warnings=False))
        return self._record_model_usage(source_key, usage, plan, now=now)

    def record_position_usage(self, source_key, usage, plan, *, now):
        from app.options.position_reasoning import PositionPlan

        plan = PositionPlan.model_validate(plan.model_dump(warnings=False))
        return self._record_model_usage(source_key, usage, plan, now=now)

    @exact
    def _record_model_usage(self, source_key, usage, proposal, *, now):
        usage = UsageEvidence.model_validate(usage.model_dump(warnings=False))
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
