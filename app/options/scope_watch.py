"""Durable unfilled Scope watches. No proposal, fill, P&L or order authority."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution, clock, fingerprint
from app.options.governor import admit_option
from app.options.models import Name, OptionProposal, OptionRecord, SessionWindow, UnderlyingQuote
from app.options.scope import ScopePreflightInput
from app.options.scope_admission import ScopeAdmissionPolicy
from app.options.scope_context import (
    ContextPattern,
    ScopeContextInput,
    ScopeContextPolicy,
    scan_scope_context,
)
from app.options.scope_contract import ScopeContractPolicy, scan_scope_contract
from app.options.scope_quality import ScopeQualityPolicy, scan_scope_quality
from app.options.scope_structure import ScopePattern, scan_scope_structure


class ScopeDirectionResetPolicy(OptionRecord):
    version: Literal["scope-watch-direction-reset-v1"] = "scope-watch-direction-reset-v1"
    cooldown_seconds: int = Field(strict=True, ge=600, le=3600)
    confirmation_bars: int = Field(strict=True, ge=2, le=5)


class ScopeArmingPolicy(OptionRecord):
    version: Literal["scope-sampled-arming-v1"] = "scope-sampled-arming-v1"
    confirmation_hold_seconds: int = Field(strict=True, ge=60, le=600)
    max_sample_gap_seconds: int = Field(strict=True, ge=1, le=10)


class ScopeWatchPolicy(OptionRecord):
    version: Literal["scope-unfilled-watch-v1"] = "scope-unfilled-watch-v1"
    context: ScopeContextPolicy
    max_called_plays_per_session: int = Field(strict=True, ge=1, le=2)
    direction_reset: ScopeDirectionResetPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    quality: ScopeQualityPolicy | None = Field(default=None, exclude_if=lambda value: value is None)

    arming: ScopeArmingPolicy | None = Field(default=None, exclude_if=lambda value: value is None)

    contract: ScopeContractPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    admission: ScopeAdmissionPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def matching_quality_context(self):
        if self.quality is not None and self.quality.context != self.context:
            raise ValueError("Scope watch and quality context policies must match")
        if self.arming is not None and self.quality is None:
            raise ValueError("Scope arming requires frozen quality review")
        if self.contract is not None and self.contract.quality != self.quality:
            raise ValueError("Scope contract and watch quality policies must match")
        if self.admission is not None and (self.arming is None or self.contract is None):
            raise ValueError("Scope admission requires frozen arming and contract policies")
        return self


class ScopeWatchChoice(OptionRecord):
    pattern: ScopePattern | ContextPattern
    parent_pattern: ScopePattern
    right: Literal["CALL", "PUT"]


class _Action(OptionRecord):
    key: Name
    expected_revision: int = Field(strict=True, ge=0)


class ScopeWatchBook:
    """Opt-in research state inside one lifetime-owned, restore-fenced journal.

    This version refuses any native order/model/decision history. Linking watches
    to execution and settling full-cost outcomes requires a later frozen version.
    """

    def __init__(self, engine, policy, *, now, create=False):
        if type(engine) is not OptionExecution:
            raise ValueError("Built-in owned OptionExecution required")
        self.engine = engine
        self.policy = ScopeWatchPolicy.model_validate(policy.model_dump(warnings=False))
        preflight = self.policy.context.structure.preflight
        if (
            "SPX" not in engine.limits.allowed_underlyings
            or preflight.provider != engine.limits.provider
            or preflight.quote_source != engine.limits.option_source
        ):
            raise ExecutionBlocked("SCOPE_WATCH_OWNER_IDENTITY_MISMATCH")
        self._config = self.policy.model_dump_json()
        now = clock(now)
        with engine.journal.write() as db:
            engine._control(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_scope_watch_policy "
                "(id INTEGER PRIMARY KEY CHECK(id=1), config_json TEXT NOT NULL, "
                "last_action_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_scope_watches "
                "(play_key TEXT PRIMARY KEY, session_date TEXT NOT NULL, "
                "active_lock INTEGER UNIQUE CHECK(active_lock=1), record_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_scope_watch_actions "
                "(action_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, result_json TEXT NOT NULL)"
            )
            row = db.execute("SELECT * FROM execution_option_scope_watch_policy").fetchone()
            if row is None:
                if not create:
                    raise ExecutionBlocked("SCOPE_WATCH_NOT_ENROLLED")
                self._untraded(db)
                self._ready(db, now)
                db.execute(
                    "INSERT INTO execution_option_scope_watch_policy VALUES(1,?,?)",
                    (self._config, now.isoformat()),
                )
                engine.journal.event(db, now, "SCOPE_WATCH_ENROLLED", json.loads(self._config))
            elif create or row["config_json"] != self._config:
                raise ExecutionBlocked("FROZEN_SCOPE_WATCH_POLICY_MISMATCH")

    def _untraded(self, db):
        for table in (
            "execution_orders",
            "execution_model_calls",
            "execution_option_decisions",
            "execution_option_opportunities",
            "execution_option_runtime",
        ):
            if (
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            ):
                raise ExecutionBlocked("SCOPE_WATCH_EXECUTION_LINK_NOT_IMPLEMENTED")

    def _ready(self, db, now):
        account = self.engine._account(db, now)
        if (
            not account.complete
            or not account.reconciled
            or account.entry_halted
            or account.entry_blockers
            or account.position is not None
            or account.working_orders
            or account.unsupported_exposure
            or not account.budgets_known
            or account.daily_loss_available <= 0
            or account.total_loss_available <= 0
            or account.settled_cash <= 0
            or not 0
            <= (now - account.captured_at).total_seconds()
            < self.engine.limits.account_max_age_seconds
        ):
            raise ExecutionBlocked("SCOPE_WATCH_OWNER_NOT_READY")

    def _begin(self, db, action, request, now):
        self.engine._control(db)
        config = db.execute("SELECT * FROM execution_option_scope_watch_policy").fetchone()
        if (
            config is None
            or config["config_json"] != self._config
            or self.policy.model_dump_json() != self._config
        ):
            raise ExecutionBlocked("FROZEN_SCOPE_WATCH_POLICY_MISMATCH")
        digest = fingerprint(request)
        prior = db.execute(
            "SELECT * FROM execution_option_scope_watch_actions WHERE action_key=?", (action.key,)
        ).fetchone()
        if prior:
            if prior["request_hash"] != digest:
                raise ExecutionBlocked("SCOPE_WATCH_ACTION_CONFLICT")
            return digest, json.loads(prior["result_json"])
        if action.expected_revision != self.engine.journal.revision(db):
            raise ExecutionBlocked("SCOPE_WATCH_REVISION_CHANGED")
        if now < datetime.fromisoformat(config["last_action_at"]):
            raise ExecutionBlocked("SCOPE_WATCH_CLOCK_REWOUND")
        self._untraded(db)
        return digest, None

    def _finish(self, db, action, digest, record, now):
        self.engine.journal.event(
            db, now, "SCOPE_WATCH_ACTION", {"action_key": action.key, "record": record}
        )
        result = {
            "revision": self.engine.journal.revision(db),
            "record": record,
            "authority": False,
            "live_enabled": False,
        }
        db.execute(
            "INSERT INTO execution_option_scope_watch_actions VALUES(?,?,?)",
            (action.key, digest, json.dumps(result, sort_keys=True)),
        )
        db.execute(
            "UPDATE execution_option_scope_watch_policy SET last_action_at=? WHERE id=1",
            (now.isoformat(),),
        )
        return result

    def call(self, key, choice, frame, context, *, expected_revision, now):
        """Lock one detected alternative as WATCHING; even never-filled calls count."""
        now = clock(now)
        action = _Action(key=key, expected_revision=expected_revision)
        choice = ScopeWatchChoice.model_validate(choice.model_dump(warnings=False))
        frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
        context = ScopeContextInput.model_validate(context.model_dump(warnings=False))
        request = {
            "kind": "CALL",
            "action": action,
            "choice": choice,
            "frame": frame,
            "context": context,
            "now": now,
        }
        with self.engine.journal.write() as db:
            digest, prior = self._begin(db, action, request, now)
            if prior is not None:
                return prior
            self._ready(db, now)
            if db.execute(
                "SELECT 1 FROM execution_option_scope_watches WHERE active_lock=1"
            ).fetchone():
                raise ExecutionBlocked("SCOPE_WATCH_ALREADY_ACTIVE")
            scan = scan_scope_context(frame, context, self.policy.context, now=now)
            selected = [
                o
                for o in scan.observations
                if all(getattr(o, k) == v for k, v in choice.model_dump().items())
            ]
            if (
                scan.issues
                or len(selected) != 1
                or selected[0].status != "DETECTED"
                or selected[0].geometry is None
            ):
                raise ExecutionBlocked("SCOPE_WATCH_CONTEXT_NOT_DETECTED")
            quality_scan = None
            if self.policy.quality is not None:
                quality_scan = scan_scope_quality(frame, context, self.policy.quality, now=now)
                reviewed = [o for o in quality_scan.observations if o.observation == selected[0]]
                if quality_scan.issues or len(reviewed) != 1 or not reviewed[0].passed:
                    raise ExecutionBlocked("SCOPE_WATCH_QUALITY_BLOCKED")
            contract_scan = None
            if self.policy.contract is not None:
                contract_scan = scan_scope_contract(frame, context, self.policy.contract, now=now)
                if not self._contract_passed(contract_scan, choice.model_dump()):
                    raise ExecutionBlocked("SCOPE_WATCH_CONTRACT_BLOCKED")
            session = frame.session.session_date.isoformat()
            previous = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT record_json FROM execution_option_scope_watches WHERE session_date=?",
                    (session,),
                )
            ]
            if len(previous) >= self.policy.max_called_plays_per_session:
                raise ExecutionBlocked("SCOPE_WATCH_DAILY_CALL_LIMIT")
            for p in previous:
                before = ScopePreflightInput.model_validate(p["reviewed_frame"])
                if frame.session != before.session:
                    raise ExecutionBlocked("SCOPE_WATCH_LOCKED_SESSION_CHANGED")
                self._history_prefix(before, frame)
            for p in previous:
                if p["choice"]["right"] != choice.right:
                    self._review_flip(p, selected[0], frame, now)
            if any(
                scan.structure.completed_through.isoformat() <= p["reviewed_through"]
                for p in previous
            ):
                raise ExecutionBlocked("SCOPE_WATCH_FRESH_COMPLETED_BAR_REQUIRED")
            record = {
                "play_key": key,
                "session_date": session,
                "called_at": now.isoformat(),
                "choice": choice.model_dump(mode="json"),
                "status": "WATCHING",
                "locked_frame": frame.model_dump(mode="json"),
                "locked_context": context.model_dump(mode="json"),
                "locked_scan": scan.model_dump(mode="json"),
                "geometry": selected[0].geometry.model_dump(mode="json"),
                "reviewed_frame": frame.model_dump(mode="json"),
                "reviewed_through": scan.structure.completed_through.isoformat(),
                "terminal_at": None,
                "terminal_bar_ends_at": None,
            }
            if contract_scan is not None:
                record["locked_contract_scan"] = contract_scan.model_dump(mode="json")
            if quality_scan is not None:
                record["locked_quality_scan"] = quality_scan.model_dump(mode="json")
            db.execute(
                "INSERT INTO execution_option_scope_watches VALUES(?,?,1,?)",
                (key, session, json.dumps(record, sort_keys=True)),
            )
            return self._finish(db, action, digest, record, now)

    @staticmethod
    def _contract_passed(scan, choice):
        selected = [
            o for o in scan.observations if all(getattr(o, k) == v for k, v in choice.items())
        ]
        return not scan.issues and len(selected) == 1 and selected[0].passed

    def _review_flip(self, previous, selected, frame, now):
        policy = self.policy.direction_reset
        if policy is None:
            raise ExecutionBlocked("SCOPE_WATCH_DIRECTION_RESET_NOT_IMPLEMENTED")
        neutral = previous.get("neutral_reset")
        if neutral is None:
            raise ExecutionBlocked("SCOPE_WATCH_NEUTRAL_RESET_REQUIRED")
        at = datetime.fromisoformat(neutral["recorded_at"])
        if now < at + timedelta(seconds=policy.cooldown_seconds):
            raise ExecutionBlocked("SCOPE_WATCH_DIRECTION_COOLDOWN")
        if selected.strategy_class != "REVERSAL":
            raise ExecutionBlocked("SCOPE_WATCH_FRESH_REVERSAL_REQUIRED")
        bars = next(h.bars for h in frame.histories if h.symbol == "SPX")
        if len([b for b in bars if b.begins_at >= at]) < policy.confirmation_bars:
            raise ExecutionBlocked("SCOPE_WATCH_POST_RESET_BARS_REQUIRED")

    def neutralize(self, key, play_key, frame, *, expected_revision, now):
        """Record a distinct neutral state after an observed unfilled invalidation.

        Neutral is a software direction state, not an inferred neutral price zone.
        It neither refunds a call nor changes the original terminal classification.
        """
        now = clock(now)
        action = _Action(key=key, expected_revision=expected_revision)
        play_key = _Action(key=play_key, expected_revision=0).key
        frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
        request = {
            "kind": "NEUTRALIZE",
            "action": action,
            "play_key": play_key,
            "frame": frame,
            "now": now,
        }
        with self.engine.journal.write() as db:
            digest, prior = self._begin(db, action, request, now)
            if prior is not None:
                return prior
            if self.policy.direction_reset is None:
                raise ExecutionBlocked("SCOPE_WATCH_DIRECTION_RESET_NOT_IMPLEMENTED")
            if db.execute(
                "SELECT 1 FROM execution_option_scope_watches WHERE active_lock=1"
            ).fetchone():
                raise ExecutionBlocked("SCOPE_WATCH_ALREADY_ACTIVE")
            row = db.execute(
                "SELECT record_json FROM execution_option_scope_watches WHERE play_key=?",
                (play_key,),
            ).fetchone()
            if row is None:
                raise ExecutionBlocked("SCOPE_WATCH_INVALIDATED_PLAY_REQUIRED")
            record = json.loads(row[0])
            if (
                record["status"] != "INVALIDATED_UNFILLED"
                or record.get("neutral_reset") is not None
            ):
                raise ExecutionBlocked("SCOPE_WATCH_INVALIDATED_PLAY_REQUIRED")
            if any(
                json.loads(r[0])["called_at"] > record["called_at"]
                for r in db.execute(
                    "SELECT record_json FROM execution_option_scope_watches WHERE session_date=?",
                    (record["session_date"],),
                )
            ):
                raise ExecutionBlocked("SCOPE_WATCH_LATEST_PLAY_REQUIRED")
            old = ScopePreflightInput.model_validate(record["reviewed_frame"])
            if (
                frame.session != old.session
                or frame.metadata is None
                or frame.metadata.instrument != old.metadata.instrument
            ):
                raise ExecutionBlocked("SCOPE_WATCH_LOCKED_IDENTITY_CHANGED")
            scan = scan_scope_structure(frame, self.policy.context.structure, now=now)
            if scan.issues:
                raise ExecutionBlocked("SCOPE_WATCH_REVIEW_COVERAGE_BLOCKED")
            self._history_prefix(old, frame)
            # A bar already complete when invalidation was processed cannot be a reset.
            if scan.completed_through <= datetime.fromisoformat(record["terminal_at"]):
                raise ExecutionBlocked("SCOPE_WATCH_FRESH_COMPLETED_BAR_REQUIRED")
            record["neutral_reset"] = {
                "recorded_at": now.isoformat(),
                "frame": frame.model_dump(mode="json"),
                "scan": scan.model_dump(mode="json"),
            }
            record["reviewed_frame"] = frame.model_dump(mode="json")
            record["reviewed_through"] = scan.completed_through.isoformat()
            db.execute(
                "UPDATE execution_option_scope_watches SET record_json=? WHERE play_key=?",
                (json.dumps(record, sort_keys=True), play_key),
            )
            return self._finish(db, action, digest, record, now)

    def advance(self, key, play_key, *, expected_revision, now, frame=None):
        """Expire at the locked cutoff or review all newly completed bars in order.

        No caller-supplied status, outcome, P&L, fill or replacement geometry.
        Expiry needs no fresh market data and remains available during a halt.
        """
        now = clock(now)
        action = _Action(key=key, expected_revision=expected_revision)
        play_key = _Action(key=play_key, expected_revision=0).key
        if frame is not None:
            frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
        request = {
            "kind": "ADVANCE",
            "action": action,
            "play_key": play_key,
            "frame": frame,
            "now": now,
        }
        with self.engine.journal.write() as db:
            digest, prior = self._begin(db, action, request, now)
            if prior is not None:
                return prior
            row = db.execute(
                "SELECT * FROM execution_option_scope_watches WHERE play_key=?", (play_key,)
            ).fetchone()
            if row is None or row["active_lock"] != 1:
                raise ExecutionBlocked("SCOPE_WATCH_NOT_ACTIVE")
            record = json.loads(row["record_json"])
            locked = ScopePreflightInput.model_validate(record["locked_frame"])
            if now >= locked.session.entry_cutoff_at:
                record["status"] = "EXPIRED_UNFILLED"
            else:
                if frame is None:
                    raise ExecutionBlocked("SCOPE_WATCH_FRESH_FRAME_REQUIRED")
                if (
                    frame.session != locked.session
                    or frame.metadata is None
                    or frame.metadata.instrument != locked.metadata.instrument
                ):
                    raise ExecutionBlocked("SCOPE_WATCH_LOCKED_IDENTITY_CHANGED")
                scan = scan_scope_structure(frame, self.policy.context.structure, now=now)
                if scan.issues:
                    raise ExecutionBlocked("SCOPE_WATCH_REVIEW_COVERAGE_BLOCKED")
                old = ScopePreflightInput.model_validate(record["reviewed_frame"])
                self._history_prefix(old, frame)
                if scan.completed_through.isoformat() <= record["reviewed_through"]:
                    raise ExecutionBlocked("SCOPE_WATCH_FRESH_COMPLETED_BAR_REQUIRED")
                self._review_price_bars(record, old, frame, scan.completed_through, now)
            if self.policy.arming is not None:
                record["arming"] = self._arming_reset(record, now, "WATCH_ADVANCED")
            active = record["status"] == "WATCHING"
            if not active:
                record["terminal_at"] = now.isoformat()
            db.execute(
                "UPDATE execution_option_scope_watches SET active_lock=?, record_json=? WHERE play_key=?",
                (1 if active else None, json.dumps(record, sort_keys=True), play_key),
            )
            return self._finish(db, action, digest, record, now)

    @staticmethod
    def _review_price_bars(record, old, frame, completed_through, now):
        previous = {h.symbol: h for h in old.histories}
        from app.options.scope_structure import ScopeGeometry

        geometry = ScopeGeometry.model_validate(record["geometry"])
        bars = next(h.bars for h in frame.histories if h.symbol == "SPX")
        for bar in bars[len(previous["SPX"].bars) :]:
            invalid = (
                bar.low <= geometry.invalidation
                if geometry.right == "CALL"
                else bar.high >= geometry.invalidation
            )
            consumed = (
                bar.high >= geometry.target_two
                if geometry.right == "CALL"
                else bar.low <= geometry.target_two
            )
            if invalid or consumed:
                record["status"] = (
                    "INVALIDATED_UNFILLED" if invalid else "OBJECTIVE_CONSUMED_UNFILLED"
                )
                record["terminal_bar_ends_at"] = bar.ends_at.isoformat()
                break
        record["reviewed_frame"] = frame.model_dump(mode="json")
        record["reviewed_through"] = completed_through.isoformat()
        if record["status"] != "WATCHING":
            record["terminal_at"] = now.isoformat()

    @staticmethod
    def _arming_reset(record, now, reason):
        return {
            "status": "RESET",
            "evaluated_at": now.isoformat(),
            "started_at": None,
            "sample_count": 0,
            "valid_until": None,
            "source_clocks": record.get("arming", {}).get("source_clocks", {}),
            "reasons": [reason],
            "authority": False,
            "live_enabled": False,
        }

    def observe_arming(self, key, play_key, *, expected_revision, now, frame=None, context=None):
        """Persist a sampled research hold, never an executable entry permission.

        Missing, stale or failing evidence commits a reset. Newly completed bars
        cross the original price guards before any hold can continue.
        """
        now = clock(now)
        action = _Action(key=key, expected_revision=expected_revision)
        play_key = _Action(key=play_key, expected_revision=0).key
        if frame is not None:
            frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
        if context is not None:
            context = ScopeContextInput.model_validate(context.model_dump(warnings=False))
        request = {
            "kind": "OBSERVE_ARMING",
            "action": action,
            "play_key": play_key,
            "frame": frame,
            "context": context,
            "now": now,
        }
        with self.engine.journal.write() as db:
            digest, prior = self._begin(db, action, request, now)
            if prior is not None:
                return prior
            if self.policy.arming is None:
                raise ExecutionBlocked("SCOPE_WATCH_ARMING_NOT_ENROLLED")
            row = db.execute(
                "SELECT * FROM execution_option_scope_watches WHERE play_key=?", (play_key,)
            ).fetchone()
            if row is None or row["active_lock"] != 1:
                raise ExecutionBlocked("SCOPE_WATCH_NOT_ACTIVE")
            record = json.loads(row["record_json"])
            result = self._arming_reset(record, now, "FRESH_EVIDENCE_REQUIRED")
            # Keep full failed inputs too; action receipts/events provide the audit history.
            result["frame"] = frame.model_dump(mode="json") if frame is not None else None
            result["context"] = context.model_dump(mode="json") if context is not None else None
            try:
                self._ready(db, now)
                self._review_arming(record, result, frame, context, now)
            except ExecutionBlocked as exc:
                result["reasons"] = [str(exc)]
            record["arming"] = result
            db.execute(
                "UPDATE execution_option_scope_watches SET active_lock=?, record_json=? WHERE play_key=?",
                (
                    1 if record["status"] == "WATCHING" else None,
                    json.dumps(record, sort_keys=True),
                    play_key,
                ),
            )
            return self._finish(db, action, digest, record, now)

    def review_admission(
        self, key, play_key, *, expected_revision, now, frame=None, context=None, underlying=None
    ):
        """Atomically refresh the hold and store common-governor sizing, without dispatch.

        Account evidence comes only from this journal's owner. The caller cannot
        supply balances, a replacement stop, quantity or a generic equity calendar.
        """
        now = clock(now)
        action = _Action(key=key, expected_revision=expected_revision)
        play_key = _Action(key=play_key, expected_revision=0).key
        if frame is not None:
            frame = ScopePreflightInput.model_validate(frame.model_dump(warnings=False))
        if context is not None:
            context = ScopeContextInput.model_validate(context.model_dump(warnings=False))
        if underlying is not None:
            underlying = UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
        request = {
            "kind": "REVIEW_ADMISSION",
            "action": action,
            "play_key": play_key,
            "frame": frame,
            "context": context,
            "underlying": underlying,
            "now": now,
        }
        with self.engine.journal.write() as db:
            digest, prior = self._begin(db, action, request, now)
            if prior is not None:
                return prior
            if self.policy.admission is None:
                raise ExecutionBlocked("SCOPE_WATCH_ADMISSION_NOT_ENROLLED")
            row = db.execute(
                "SELECT * FROM execution_option_scope_watches WHERE play_key=?", (play_key,)
            ).fetchone()
            if row is None or row["active_lock"] != 1:
                raise ExecutionBlocked("SCOPE_WATCH_NOT_ACTIVE")
            record = json.loads(row["record_json"])
            sample = self._arming_reset(record, now, "FRESH_EVIDENCE_REQUIRED")
            sample["frame"] = frame.model_dump(mode="json") if frame is not None else None
            sample["context"] = context.model_dump(mode="json") if context is not None else None
            review = {
                "evaluated_at": now.isoformat(),
                "account": None,
                "limits": self.engine.limits.model_dump(mode="json"),
                "effective_limits": self.engine._effective_limits().model_dump(mode="json"),
                "owner_session": None,
                "index_session": record["locked_frame"]["session"],
                "underlying": underlying.model_dump(mode="json")
                if underlying is not None
                else None,
                "proposal": None,
                "session": None,
                "admission": None,
                "eligible": False,
                "reasons": [],
                "authority": False,
                "live_enabled": False,
            }
            try:
                account = self.engine._account(db, now)
                review["account"] = account.model_dump(mode="json")
                self._ready(db, now)
                self._review_arming(record, sample, frame, context, now)
                if sample["status"] != "ARMED":
                    review["reasons"] = ["SCOPE_WATCH_ARMING_HOLD_REQUIRED"]
                else:
                    geometry = record["geometry"]
                    if underlying is not None and (
                        underlying.ask >= Decimal(geometry["target_one"])
                        if record["choice"]["right"] == "CALL"
                        else underlying.bid <= Decimal(geometry["target_one"])
                    ):
                        raise ExecutionBlocked("SCOPE_CURRENT_FIRST_OBJECTIVE_CONSUMED")
                    locked = ScopePreflightInput.model_validate(record["locked_frame"])
                    proposal = OptionProposal(
                        action="OPEN_LONG",
                        contract=locked.metadata.instrument.contract,
                        underlying_invalidation=geometry["invalidation"],
                        max_entry_debit=self.policy.admission.max_entry_debit,
                        thesis="Scope locked " + record["choice"]["pattern"],
                    )
                    owner_session = self.engine._session(proposal.contract, now)
                    if owner_session is None:
                        raise ExecutionBlocked("SCOPE_OWNER_SESSION_UNAVAILABLE")
                    review["owner_session"] = owner_session.model_dump(mode="json")
                    opens = max(owner_session.opens_at, locked.session.entry_starts_at)
                    cutoff = min(owner_session.entry_cutoff_at, locked.session.entry_cutoff_at)
                    closes = min(owner_session.closes_at, locked.session.protect_at)
                    if not opens < cutoff <= closes:
                        raise ExecutionBlocked("SCOPE_SESSION_INTERSECTION_EMPTY")
                    session = SessionWindow(
                        source=owner_session.source,
                        underlying="SPX",
                        opens_at=opens,
                        entry_cutoff_at=cutoff,
                        closes_at=closes,
                    )
                    admission = admit_option(
                        proposal,
                        frame.quote,
                        underlying,
                        account,
                        self.engine._effective_limits(),
                        session,
                        now=now,
                    )
                    if admission.valid_until is not None:
                        admission = admission.model_copy(
                            update={
                                "valid_until": min(
                                    admission.valid_until,
                                    datetime.fromisoformat(sample["valid_until"]),
                                )
                            }
                        )
                    review.update(
                        {
                            "proposal": proposal.model_dump(mode="json"),
                            "session": session.model_dump(mode="json"),
                            "admission": admission.model_dump(mode="json"),
                            "eligible": admission.outcome == "APPROVED",
                            "reasons": list(admission.reasons),
                        }
                    )
                    if admission.outcome != "APPROVED":
                        sample.update(
                            self._arming_reset(record, now, "SCOPE_ACCOUNT_ADMISSION_REJECTED")
                        )
            except ExecutionBlocked as exc:
                # Failed fresh evidence cannot leave an armed sample behind.
                sample.update(self._arming_reset(record, now, str(exc)))
                review["reasons"] = [str(exc)]
            record["arming"] = sample
            record["admission_review"] = review
            db.execute(
                "UPDATE execution_option_scope_watches SET active_lock=?, record_json=? WHERE play_key=?",
                (
                    1 if record["status"] == "WATCHING" else None,
                    json.dumps(record, sort_keys=True),
                    play_key,
                ),
            )
            return self._finish(db, action, digest, record, now)

    def _review_arming(self, record, result, frame, context, now):
        old = ScopePreflightInput.model_validate(record["reviewed_frame"])
        if now >= old.session.entry_cutoff_at:
            raise ExecutionBlocked("SCOPE_WATCH_ENTRY_CUTOFF")
        if frame is None or context is None:
            raise ExecutionBlocked("SCOPE_WATCH_FRESH_EVIDENCE_REQUIRED")
        if (
            frame.session != old.session
            or frame.metadata is None
            or frame.metadata.instrument != old.metadata.instrument
        ):
            raise ExecutionBlocked("SCOPE_WATCH_LOCKED_IDENTITY_CHANGED")
        scan = scan_scope_quality(frame, context, self.policy.quality, now=now)
        result["quality_scan"] = scan.model_dump(mode="json")
        if scan.issues:
            raise ExecutionBlocked("SCOPE_WATCH_QUALITY_BLOCKED")
        self._history_prefix(old, frame)
        self._review_price_bars(record, old, frame, scan.context.structure.completed_through, now)
        if record["status"] != "WATCHING":
            raise ExecutionBlocked("SCOPE_WATCH_PRICE_TERMINATED")
        selected = [
            o
            for o in scan.observations
            if all(getattr(o.observation, k) == v for k, v in record["choice"].items())
        ]
        if len(selected) != 1 or not selected[0].passed:
            raise ExecutionBlocked("SCOPE_WATCH_QUALITY_BLOCKED")
        locked_choice = next(
            o
            for o in record["locked_scan"]["observations"]
            if all(o[k] == v for k, v in record["choice"].items())
        )
        if selected[0].observation.matched_level != (
            None
            if locked_choice["matched_level"] is None
            else Decimal(locked_choice["matched_level"])
        ):
            raise ExecutionBlocked("SCOPE_WATCH_LOCKED_ANCHOR_CHANGED")
        locked_context = ScopeContextInput.model_validate(record["locked_context"])
        if (
            context.previous_session != locked_context.previous_session
            or context.prior != locked_context.prior
        ):
            raise ExecutionBlocked("SCOPE_WATCH_PRIOR_HISTORY_CHANGED")
        if selected[0].observation.geometry.model_dump(mode="json") != record["geometry"]:
            raise ExecutionBlocked("SCOPE_WATCH_LOCKED_GEOMETRY_CHANGED")
        if self.policy.contract is not None:
            contract_scan = scan_scope_contract(frame, context, self.policy.contract, now=now)
            result["contract_scan"] = contract_scan.model_dump(mode="json")
            if not self._contract_passed(contract_scan, record["choice"]):
                raise ExecutionBlocked("SCOPE_WATCH_CONTRACT_BLOCKED")
        # Every current stream must advance its source clock. Receipt-only refresh
        # and repeated completed bars cannot stand in for new provider observations.
        items = {"group:" + e.kind: e for e in frame.evidence}
        items.update({"history:" + h.symbol: h for h in frame.histories})
        items.update({"metadata": frame.metadata, "quote": frame.quote})
        items.update(
            {
                "context:" + k: getattr(context, k)
                for k in ("dealer", "moves", "flow", "news", "events")
            }
        )
        clocks = {k: item.source_at.isoformat() for k, item in items.items()}
        before = record.get("arming", {})
        watermark = before.get("source_clocks", {})
        if any(
            k in watermark and datetime.fromisoformat(v) <= datetime.fromisoformat(watermark[k])
            for k, v in clocks.items()
        ):
            raise ExecutionBlocked("SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED")
        gap = timedelta(seconds=self.policy.arming.max_sample_gap_seconds)
        preflight = self.policy.context.structure.preflight
        ages = {"group:" + source.kind: source.max_age_seconds for source in preflight.sources}
        ages.update(
            {"history:" + h.symbol: preflight.max_history_age_seconds for h in frame.histories}
        )
        ages.update(
            {
                "metadata": preflight.max_contract_age_seconds,
                "quote": preflight.max_contract_age_seconds,
            }
        )
        # Limit sampling to genuinely current observations even if a source's
        # normal coverage policy permits much older data.
        if any(now - item.source_at > gap for item in items.values()):
            raise ExecutionBlocked("SCOPE_WATCH_ARMING_SAMPLE_TOO_OLD")
        started = now
        count = 1
        if (
            before.get("status") in ("HOLDING", "ARMED")
            and now > datetime.fromisoformat(before["evaluated_at"])
            and now <= datetime.fromisoformat(before["valid_until"])
        ):
            started = datetime.fromisoformat(before["started_at"])
            count = before["sample_count"] + 1
        valid_until = min(
            now + gap,
            old.session.entry_cutoff_at,
            *(item.source_at + gap for item in items.values()),
            *(items[k].source_at + timedelta(seconds=age) for k, age in ages.items()),
            context.flow.valid_through,
            context.news.valid_through,
            context.events.valid_through,
        )
        if valid_until <= now:
            raise ExecutionBlocked("SCOPE_WATCH_ARMING_SAMPLE_TOO_OLD")
        result.update(
            {
                "status": "ARMED"
                if now - started >= timedelta(seconds=self.policy.arming.confirmation_hold_seconds)
                else "HOLDING",
                "evaluated_at": now.isoformat(),
                "started_at": started.isoformat(),
                "sample_count": count,
                "valid_until": valid_until.isoformat(),
                "source_clocks": clocks,
                "reasons": [],
            }
        )

    @staticmethod
    def _history_prefix(old, frame):
        previous = {h.symbol: h for h in old.histories}
        for history in frame.histories:
            before = previous[history.symbol].bars
            if history.bars[: len(before)] != before:
                raise ExecutionBlocked("SCOPE_WATCH_HISTORY_REWRITTEN")

    def snapshot(self):
        """Stored-only projection; it never expires or evaluates a watch on read."""
        with self.engine.journal.read() as db:
            self.engine._control(db)
            return {
                "revision": self.engine.journal.revision(db),
                "policy": json.loads(self._config),
                "watches": [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT record_json FROM execution_option_scope_watches ORDER BY session_date,play_key"
                    )
                ],
                "authority": False,
                "live_enabled": False,
            }
