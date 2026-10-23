"""Owned Degen PAPER cycles with optional bounded selection and independent exits."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from app.domain.models import utc_now
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.execution.runtime import model_key
from app.mixed.sources import StockCycleInput, StockSelectionPolicy
from app.options import judgment
from app.options.degen import DegenHistory, DegenPolicy, scan_degen
from app.options.engine import EntryModelBlocked, OptionExecution, clock, fingerprint
from app.options.governor import _fresh
from app.options.lifecycle import OptionIntent, OptionLedger
from app.options.models import OptionProposal, OptionQuote, OptionRecord, UnderlyingQuote
from app.options.scope_arbitration import ScopeCycleInput, SharedScopePolicy
from app.options.selection import (
    ContractReadPlan,
    ContractSelectionPolicy,
    OptionInventory,
    admit_candidates,
    plan_contract_reads,
)
from app.options.swing import SwingInput, SwingPolicy
from app.options.swing_batch import SwingBatchInput


class DegenFrame(OptionRecord):
    stocks: tuple[StockCycleInput, ...] = Field(
        default=(), max_length=2, exclude_if=lambda v: not v
    )
    histories: tuple[DegenHistory, ...] = Field(default=(), max_length=2)
    inventories: tuple[OptionInventory, ...] = Field(default=(), max_length=2)
    quotes: tuple[OptionQuote, ...] = Field(default=(), max_length=8)
    underlyings: tuple[UnderlyingQuote, ...] = Field(default=(), max_length=2)
    scope: ScopeCycleInput | None = Field(default=None, exclude_if=lambda v: v is None)
    swing: tuple[SwingInput, ...] = Field(default=(), max_length=2, exclude_if=lambda v: not v)
    swing_batches: tuple[SwingBatchInput, ...] = Field(
        default=(), max_length=2, exclude_if=lambda v: not v
    )


class DegenCoordinator:
    def __init__(
        self,
        engine,
        policy,
        selection,
        *,
        create=False,
        clock=utc_now,
        judgment_limits=None,
        key_file=None,
        entry_policy=None,
        replay_model=None,
        position_policy=None,
        swing_policy=None,
        scope_policy=None,
        scope_replay=None,
        scope_refresh=None,
        stock_policy=None,
        stock_refresh=None,
    ):
        if type(engine) is not OptionExecution or getattr(engine, "_degen_owner", None) is not None:
            raise ValueError("One active built-in options owner is required")
        self.stock_refresh = stock_refresh
        mixed_paid = (
            engine.policy.mixed_owner is not None
            and engine.policy.mixed_owner.reasoning is not None
        )
        if engine.policy.mixed_owner is not None:
            if not mixed_paid and any(
                x is not None
                for x in (
                    judgment_limits,
                    key_file,
                    entry_policy,
                    replay_model,
                    position_policy,
                    scope_replay,
                    stock_refresh,
                )
            ):
                raise ValueError("Mixed paid/replay contracts are not enrolled")
            if mixed_paid and (
                stock_policy is None
                or stock_policy.paid_selection != engine.policy.mixed_owner.reasoning
                or entry_policy is None
                or entry_policy.mixed_selection != engine.policy.mixed_owner.reasoning
                or judgment_limits is None
                or key_file is None
                or not callable(stock_refresh)
                or any(x is not None for x in (replay_model, scope_replay))
                or (position_policy is not None and position_policy.mixed_management is None)
            ):
                raise ValueError(
                    "Mixed paid entry requires full frozen contracts and fresh stock reader; replay not enrolled"
                )
        elif stock_refresh is not None or (
            entry_policy is not None and entry_policy.mixed_selection is not None
        ):
            raise ValueError("Mixed reasoning requires native mixed ownership")
        self.stock_policy = (
            StockSelectionPolicy.model_validate(stock_policy.model_dump(warnings=False))
            if stock_policy is not None
            else None
        )
        if self.stock_policy is not None:
            if (self.stock_policy.paid_selection is not None) != mixed_paid:
                raise ValueError("Matching frozen stock paid selection required")
            if engine.policy.mixed_owner is None or tuple(
                i.symbol for i in self.stock_policy.instruments
            ) != tuple(policy.symbols):
                raise ValueError("Matching native mixed owner and exact stock universe required")
            if any(
                i.provider != engine.policy.mixed_owner.stocks.provider
                for i in self.stock_policy.instruments
            ):
                raise ValueError("Stock instrument provider must match the native owner")
            if (
                scope_policy is not None
                and self.stock_policy.family_priority != scope_policy.family_priority
            ):
                raise ValueError(
                    "One original family priority across stocks/options/Scope required"
                )
            if (
                swing_policy is not None
                and tuple(f for f in self.stock_policy.family_priority if f != "SCOPE")
                != swing_policy.family_priority
            ):
                raise ValueError("One original Degen/Swing family priority required")
        self.engine, self.clock = engine, clock
        self.scope_policy = (
            SharedScopePolicy.model_validate(scope_policy.model_dump(warnings=False))
            if scope_policy is not None
            else None
        )
        if (scope_policy is not None) != (engine.policy.scope_arbitration is not None):
            raise ValueError("Shared Scope requires matching owner/coordinator enrollment")
        self.scope_refresh = scope_refresh
        self.scope_replay = None
        if scope_replay is not None:
            from app.options.scope_replay_enrollment import validate_adapter

            self.scope_replay = validate_adapter(scope_replay, replay_model)
            if self.scope_policy is None or self.scope_policy.version != "shared-scope-entry-v1":
                raise ValueError("Scope tape replay requires explicit shared AI enrollment")
        if self.scope_policy is not None:
            if self.scope_policy.version != engine.policy.scope_arbitration:
                raise ValueError("Matching shared Scope versions required")
            if self.scope_policy.version == "shared-scope-selection-v1" and any(
                x is not None
                for x in (judgment_limits, key_file, entry_policy, replay_model, position_policy)
            ):
                raise ValueError("Shared Scope v1 is deterministic only")
            if self.scope_policy.version == "shared-scope-entry-v1" and (
                judgment_limits is None
                or (key_file is None if self.scope_replay is None else key_file is not None)
                or entry_policy is None
                or entry_policy.scope_selection is None
                or (replay_model is not None and self.scope_replay is None)
                or not callable(scope_refresh)
            ):
                raise ValueError(
                    "Shared Scope AI requires full entry configuration and fresh input reader"
                )
            if (swing_policy is not None) != ("SWING" in self.scope_policy.family_priority):
                raise ValueError("Shared Scope priority must cover exactly enrolled families")
            if not set(self.scope_policy.family_priority) <= {
                p.family for p in engine.policy.loss_control.families
            }:
                raise ValueError("Shared Scope requires all enrolled family loss policies")
        self.policy = DegenPolicy.model_validate(policy.model_dump(warnings=False))
        self.selection = ContractSelectionPolicy.model_validate(
            selection.model_dump(warnings=False)
        )
        from app.options.replay_model import ReplayModel

        if replay_model is not None and (
            (type(replay_model) is not ReplayModel and self.scope_replay is None)
            or key_file is not None
            or judgment_limits is None
            or engine.policy.cost_policy is None
            or (replay_model.script.arm in {"C", "D"} or self.scope_replay is not None)
            != (entry_policy is not None)
        ):
            raise ValueError("Explicit isolated scripted model configuration required")
        self.swing_policy = (
            SwingPolicy.model_validate(swing_policy.model_dump(warnings=False))
            if swing_policy is not None
            else None
        )
        if self.swing_policy is not None and (
            replay_model is None and judgment_limits is not None and entry_policy is None
        ):
            raise ValueError("Shared families require native full-entry AI or model-off comparison")
        self.replay_model = replay_model
        self._replay_quotes, self._replay_underlyings = {}, {}
        if replay_model is None and (judgment_limits is None) != (key_file is None):
            raise ValueError("Model limits and private key path must be paired")
        self.judgment_limits = (
            JudgmentLimits.model_validate(judgment_limits.model_dump(warnings=False))
            if judgment_limits is not None
            else None
        )
        self.key_file = Path(key_file) if key_file is not None else None
        from app.options.entry_reasoning import EntryReasoningPolicy

        self.entry_policy = (
            EntryReasoningPolicy.model_validate(entry_policy.model_dump(warnings=False))
            if entry_policy is not None
            else None
        )
        if (
            engine.policy.loss_control is not None
            and engine.policy.loss_control.entry_cost_attribution is not None
            and (self.entry_policy is None or replay_model is not None)
        ):
            raise ValueError("Later-entry attribution requires native full-entry enrollment")
        if self.entry_policy is not None and (
            self.entry_policy.scope_selection == "scope-fixed-shortlist-v1"
        ) != (self.scope_replay is not None and replay_model.script.arm == "B"):
            raise ValueError("Scope shortlist requires its exact isolated B enrollment")
        if (
            self.entry_policy is not None
            and self.entry_policy.scope_selection is not None
            and (self.scope_policy is None or self.scope_policy.version != "shared-scope-entry-v1")
        ):
            raise ValueError("Scope reasoning requires shared AI owner enrollment")
        if scope_refresh is not None and (
            self.scope_policy is None or self.scope_policy.version != "shared-scope-entry-v1"
        ):
            raise ValueError("Scope refresh requires shared AI owner enrollment")
        from app.options.position_reasoning import PositionReasoningPolicy

        self.position_policy = (
            PositionReasoningPolicy.model_validate(position_policy.model_dump(warnings=False))
            if position_policy is not None
            else None
        )
        if (
            self.position_policy is not None
            and (self.position_policy.mixed_management is not None) != mixed_paid
        ):
            raise ValueError("Matching mixed management enrollment required")
        if self.position_policy is not None and (
            (self.scope_policy is not None) != (self.position_policy.scope_management is not None)
        ):
            raise ValueError("Shared Scope management requires explicit matching enrollment")
        if self.position_policy is not None and (
            self.entry_policy is None
            or (replay_model is not None and replay_model.script.arm != "D")
        ):
            raise ValueError("Management requires a separate native full-entry cohort")
        if replay_model is not None and (replay_model.script.arm == "D") != (
            self.position_policy is not None
        ):
            raise ValueError("Arm D requires explicit management policy")
        self._position_quotes, self._position_underlyings = (), ()
        if self.entry_policy is not None and self.judgment_limits is None:
            raise ValueError("Broader entry reasoning requires explicit model configuration")
        if self.key_file is not None and (
            not self.key_file.is_absolute() or engine.policy.cost_policy is None
        ):
            raise ValueError("Model requires absolute private key path and frozen cost policy")
        if (
            not set(self.policy.symbols) <= set(engine.limits.allowed_underlyings)
            or (
                self.selection.max_quote_contracts
                + (
                    2
                    if self.swing_policy and self.swing_policy.family_batch
                    else 1
                    if self.swing_policy
                    else 0
                )
            )
            * len(self.policy.symbols)
            + (
                1
                if self.swing_policy and self.swing_policy.family_batch and self.scope_policy
                else 0
            )
            > 8
        ):
            raise ValueError(
                "Frozen symbols and global quote capacity must fit the execution owner"
            )
        carrying = self.swing_policy is not None and self.swing_policy.carry is not None
        if carrying != (engine.policy.swing_carry is not None):
            raise ValueError("Matching frozen Swing carry owner and strategy required")
        if (
            carrying
            and self.entry_policy is not None
            and self.entry_policy.max_carry_horizon_seconds is None
        ):
            raise ValueError("Carry entry AI requires its explicit horizon contract")
        if (
            carrying
            and self.position_policy is not None
            and self.position_policy.swing_carry is None
        ):
            raise ValueError("Carry management requires its explicit context contract")
        from app.options.scope_carry import validate_enrollment

        validate_enrollment(
            engine.policy,
            self.scope_policy,
            self.swing_policy,
            self.entry_policy,
            self.position_policy,
            replay=replay_model is not None or scope_replay is not None,
            replay_enrollment=self.scope_replay,
        )
        frozen = self._configuration()
        self._frozen = frozen
        with engine.journal.write() as db:
            engine._control(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_strategy(id INTEGER PRIMARY KEY CHECK(id=1),policy_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_option_opportunities(cycle_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,started_at TEXT NOT NULL,inputs_json TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT)"
            )
            row = db.execute(
                "SELECT policy_json FROM execution_option_strategy WHERE id=1"
            ).fetchone()
            if row is None:
                if (
                    not create
                    or db.execute(
                        "SELECT 1 FROM execution_orders UNION ALL SELECT 1 FROM execution_model_calls UNION ALL SELECT 1 FROM execution_option_decisions LIMIT 1"
                    ).fetchone()
                ):
                    raise ExecutionBlocked("NEW_UNTRADED_STRATEGY_POPULATION_REQUIRED")
                if (
                    engine.policy.mixed_owner is not None
                    and db.execute(
                        "SELECT 1 FROM execution_stock_orders UNION ALL SELECT 1 FROM execution_stock_decisions LIMIT 1"
                    ).fetchone()
                ):
                    raise ExecutionBlocked("NEW_UNTRADED_STOCK_STRATEGY_REQUIRED")
                account = engine._account(db, self.now())
                if (
                    account.position is not None
                    or account.entry_halted
                    or account.entry_blockers
                    or not account.budgets_known
                    or not _fresh(
                        account.captured_at,
                        account.captured_at,
                        self.now(),
                        engine.limits.account_max_age_seconds,
                        engine.limits.max_receive_lag_seconds,
                    )
                ):
                    raise ExecutionBlocked("HEALTHY_EMPTY_STRATEGY_POPULATION_REQUIRED")
                db.execute("INSERT INTO execution_option_strategy VALUES(1,?)", (frozen,))
                engine.journal.event(db, self.now(), "DEGEN_STRATEGY_ENROLLED", json.loads(frozen))
            elif create or row[0] != frozen:
                raise ExecutionBlocked("FROZEN_DEGEN_STRATEGY_CANNOT_CHANGE_OR_REENROLL")
            if self.stock_policy is not None:
                from app.mixed.selection import tables

                tables(db, create=create)
            if self.swing_policy is not None:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS execution_option_swing_seeds("
                    "session TEXT NOT NULL,symbol TEXT NOT NULL,seed_hash TEXT NOT NULL,"
                    "seed_json TEXT NOT NULL,PRIMARY KEY(session,symbol))"
                )
                if self.swing_policy.family_batch is not None:
                    from app.options.swing_batch import create_tables

                    create_tables(db)
                if self.swing_policy.unfilled_lifecycle is not None:
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS execution_option_swing_terminals("
                        "seed_hash TEXT PRIMARY KEY,terminal_json TEXT NOT NULL)"
                    )
            for pending in db.execute(
                "SELECT cycle_key,result_json FROM execution_option_opportunities WHERE status='STARTED'"
            ).fetchall():
                result = {
                    **(json.loads(pending[1]) if pending[1] else {}),
                    "status": "INTERRUPTED",
                    "reason": "DEGEN_CYCLE_INTERRUPTED",
                    "cycle_key": pending[0],
                }
                db.execute(
                    "UPDATE execution_option_opportunities SET status='INTERRUPTED',result_json=? WHERE cycle_key=?",
                    (json.dumps(result, sort_keys=True), pending[0]),
                )
                engine._halt(db, "DEGEN_CYCLE_INTERRUPTED", self.now())
        if self.scope_policy is not None:
            from app.options.scope_watch import ScopeWatchBook

            self.scope_book = ScopeWatchBook(
                engine, self.scope_policy.watch, now=self.now(), create=create
            )
        engine._degen_owner = self

    def now(self):
        return clock(self.clock())

    def _configuration(self):
        config = {
            "setup": self.policy.model_dump(mode="json"),
            "selection": self.selection.model_dump(mode="json"),
        }
        if self.stock_policy is not None:
            config["stocks"] = self.stock_policy.model_dump(mode="json")
        if self.scope_policy is not None:
            config["scope"] = self.scope_policy.model_dump(mode="json")
        if self.swing_policy is not None:
            config["swing"] = self.swing_policy.model_dump(mode="json")
        if self.judgment_limits is not None:
            config["model"] = {
                "configuration": judgment.configuration(
                    self.engine.policy.cost_policy,
                    self.judgment_limits,
                    shared=self.swing_policy is not None and self.entry_policy is None,
                ),
                "key_file": str(self.key_file),
            }
        if self.replay_model is not None:
            config["replay_model"] = self.replay_model.configuration()
        if self.scope_replay is not None:
            config["scope_replay"] = self.scope_replay.model_dump(mode="json")
        if self.entry_policy is not None:
            from app.options.entry_judgment import configuration

            config["entry_model"] = configuration(
                self.engine.policy.cost_policy, self.judgment_limits, self.entry_policy
            ).model_dump(mode="json")
        if self.position_policy is not None:
            from app.options.position_judgment import configuration

            config["position_model"] = configuration(
                self.engine.policy.cost_policy, self.judgment_limits, self.position_policy
            ).model_dump(mode="json")
        return json.dumps(config, sort_keys=True)

    def _execution_market(self, quotes, underlyings):
        # Only the explicit fixture scheduler updates these current-prefix caches.
        if self.replay_model is not None:
            return quotes | self._replay_quotes, underlyings | self._replay_underlyings
        return quotes, underlyings

    def _model_secret(self):
        return None if self.replay_model is not None else model_key(self.key_file)

    async def _model_run(self, request, secret, *, broad=False):
        if self.replay_model is not None:
            return await self.replay_model.run(request)
        if broad:
            from app.options.entry_judgment import run_entry_process

            return await run_entry_process(request, secret)
        return await judgment.run_candidate_process(request, secret)

    def _model_timely(self, request, started, completed):
        if self.scope_replay is not None:
            # Only explicitly enrolled, tool-less tape responses use virtual elapsed
            # time. Keep the original request duration and native packet deadline.
            elapsed = (completed - started).total_seconds()
            return (
                0
                <= elapsed
                < min(
                    request.deadline_monotonic - request.started_monotonic,
                    self.judgment_limits.process_timeout_seconds,
                )
            )
        return time.monotonic() < request.deadline_monotonic and (
            self.replay_model is None
            or (completed - started).total_seconds() < self.judgment_limits.process_timeout_seconds
        )

    def _bound(self, db):
        self.engine._control(db)
        if getattr(self.engine, "_degen_owner", None) is not self:
            raise ExecutionBlocked("DEGEN_OWNER_CHANGED")
        row = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
        current = self._configuration()
        if row is None or row[0] != self._frozen or current != self._frozen:
            raise ExecutionBlocked("FROZEN_DEGEN_STRATEGY_CHANGED")
        return OptionLedger.model_validate_json(self.engine._control(db)["ledger_json"])

    def _held_instrument(self, db, ledger):
        if ledger.position:
            client = ledger.position.entry_client_id
            row = db.execute(
                "SELECT intent_json FROM execution_orders WHERE client_id=?", (client,)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT intent_json FROM execution_orders WHERE active_lock=1"
            ).fetchone()
        return OptionIntent.model_validate_json(row[0]).instrument if row else None

    def quote_plan(self, histories, inventories, swing=(), *, swing_batches=()):
        """Local planning performs no provider/model/order operation."""
        at = self.now()
        if swing_batches and (self.swing_policy is None or self.swing_policy.family_batch is None):
            raise ValueError("Swing batches require explicit new-population enrollment")
        if swing and self.swing_policy is not None and self.swing_policy.family_batch is not None:
            raise ValueError("Complete original Swing batches required")
        if swing and self.swing_policy is None:
            raise ValueError("Swing requires explicit new-population enrollment")
        with self.engine.journal.read() as db:
            ledger = self._bound(db)
            held = self._held_instrument(db, ledger)
            if held:
                return {
                    "purpose": "HELD_OR_PENDING_CONTRACT",
                    "instruments": (held,),
                    "scans": (),
                    "plans": (),
                }
            account = self.engine._account(db, at)
        if (
            account.entry_halted
            or account.entry_blockers
            or not account.budgets_known
            or not _fresh(
                account.captured_at,
                account.captured_at,
                at,
                self.engine.limits.account_max_age_seconds,
                self.engine.limits.max_receive_lag_seconds,
            )
        ):
            return {"purpose": "ENTRY_HEALTH_BLOCKED", "instruments": (), "scans": (), "plans": ()}
        histories = tuple(
            DegenHistory.model_validate(h.model_dump(warnings=False)) for h in histories
        )
        inventories = tuple(
            OptionInventory.model_validate(i.model_dump(warnings=False)) for i in inventories
        )
        by_symbol = {h.symbol: h for h in histories}
        inventory = {i.symbol: i for i in inventories}
        if (
            len(by_symbol) != len(histories)
            or set(by_symbol) != set(self.policy.symbols)
            or len(inventory) != len(inventories)
            or not set(inventory) <= set(self.policy.symbols)
        ):
            raise ValueError("Exact frozen history universe and unique scoped inventories required")
        window = self.engine.calendar.current_window(at)
        scans = tuple(
            scan_degen(by_symbol[s], self.policy, window, now=at) for s in self.policy.symbols
        )
        plans = tuple(
            plan_contract_reads(
                scan, inventory[scan.symbol], self.selection, self.engine.limits, now=at
            )
            if scan.symbol in inventory
            else ContractReadPlan(
                symbol=scan.symbol,
                evaluated_at=at,
                instruments=(),
                exclusions={},
                issues=(
                    "OPTION_INVENTORY_REQUIRED"
                    if any(s.status == "CONFIRMED" for s in scan.observations)
                    else "NO_CONFIRMED_SETUP",
                ),
            )
            for scan in scans
        )
        if self.swing_policy is not None:
            from app.options.shared_strategy import swing_plans

            if self.swing_policy.family_batch is not None:
                from app.options.swing_batch import expand_batches

                swing = expand_batches(
                    swing_batches, self.swing_policy, self.engine.calendar, self.policy.symbols, at
                )
            additional_scans, additional_plans = swing_plans(self, swing, by_symbol, scans, at)
            if self.swing_policy.family_priority[0] == "SWING":
                scans, plans = additional_scans + scans, additional_plans + plans
            else:
                scans, plans = scans + additional_scans, plans + additional_plans
        instruments = tuple(i for p in plans for i in p.instruments)
        if self.swing_policy and self.swing_policy.family_batch:
            from app.options.swing_batch import unique_instruments

            instruments = unique_instruments(plans)
        return {
            "purpose": "CANDIDATE_SHORTLIST",
            "instruments": instruments,
            "scans": scans,
            "plans": plans,
        }

    def _family_evidence(self):
        if self.scope_policy is not None:
            return {
                "families": [
                    f for f in ("DEGEN", "SWING", "SCOPE") if f in self.scope_policy.family_priority
                ]
            }
        return {"families": ["DEGEN", "SWING"]} if self.swing_policy else {}

    def _finish(self, key, result):
        result = json.loads(
            json.dumps(
                {
                    "cycle_key": key,
                    **self._family_evidence(),
                    **result,
                },
                sort_keys=True,
            )
        )
        with self.engine.journal.write() as db:
            self._bound(db)
            previous = db.execute(
                "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
            ).fetchone()
            result = {**(json.loads(previous[0]) if previous and previous[0] else {}), **result}
            db.execute(
                "UPDATE execution_option_opportunities SET status='COMPLETE',result_json=? WHERE cycle_key=?",
                (json.dumps(result, sort_keys=True), key),
            )
            self.engine.journal.event(db, self.now(), "DEGEN_CYCLE_COMPLETED", result)
        return result

    def _pending_evidence(self, key, evidence):
        with self.engine.journal.write() as db:
            self._bound(db)
            db.execute(
                "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                (json.dumps(evidence, sort_keys=True), key),
            )

    def _model_halt(self, reason, at):
        with self.engine.journal.write() as db:
            self._bound(db)
            self.engine._halt(db, reason, at)

    async def _choose(self, key, candidates, scans, account, evidence):
        at = self.now()
        try:
            secret = self._model_secret()
        except (OSError, ValueError):
            evidence["reason"] = "PRIVATE_MODEL_KEY_UNAVAILABLE"
            return None, None, at
        packet_type = (
            judgment.JointCandidatePacket
            if self.swing_policy and self.swing_policy.family_batch
            else judgment.SharedCandidatePacket
            if self.swing_policy
            else judgment.CandidatePacket
        )
        if self.swing_policy and self.swing_policy.family_batch:
            from app.options.swing_batch import scan_matches

            scans = tuple(s for s in scans if any(scan_matches(s, c) for c in candidates))
        packet = packet_type(
            cycle_key=key,
            as_of=at,
            candidates=tuple(candidates),
            scans=scans,
            account=account,
            limits=self.engine._effective_limits(),
        )
        remaining = min(
            self.judgment_limits.process_timeout_seconds,
            min((c.admission.valid_until - at).total_seconds() for c in candidates),
            (int(at.timestamp()) // 300 + 1) * 300 - at.timestamp(),
        )
        if remaining <= 0 or key != "degen:" + str(int(at.timestamp()) // 300):
            evidence["reason"] = "ORIGINAL_CANDIDATE_LEASE_EXPIRED"
            return None, None, at
        request = judgment.CandidateRequest(
            request_id=uuid4().hex,
            model=self.engine.policy.cost_policy.model,
            packet=packet,
            limits=self.judgment_limits,
            configuration=judgment.configuration(
                self.engine.policy.cost_policy,
                self.judgment_limits,
                shared=self.swing_policy is not None,
            ),
            parent_pid=os.getpid(),
            deadline_monotonic=time.monotonic() + remaining,
        )
        if len(request.model_dump_json().encode()) > judgment.MAX_REQUEST_BYTES:
            evidence["reason"] = "MODEL_PACKET_CAPACITY_EXCEEDED"
            return None, None, at
        evidence["model_request"] = request.model_dump(mode="json")
        evidence["model_input_hash"] = fingerprint(judgment.request_content(request))
        self._pending_evidence(key, {**evidence, "status": "MODEL_PENDING"})
        self.engine.begin_model_attempt(key, evidence["model_input_hash"], now=at)
        try:
            result = await self._model_run(request, secret)
            result = judgment.CandidateResult.model_validate(result.model_dump(warnings=False))
            evidence["model_result"] = result.model_dump(mode="json")
            self._pending_evidence(key, evidence)
            if (
                result.request_id != request.request_id
                or result.packet_hash != fingerprint(packet)
                or result.configuration_hash != fingerprint(request.configuration)
            ):
                raise ValueError("Model result lineage mismatch")
        except Exception as exc:  # noqa: BLE001 -- retain unknown attempt, never retry
            evidence["model_error_class"] = type(exc).__name__
            evidence["reason"] = "OPTION_MODEL_COST_UNKNOWN"
            self._pending_evidence(key, evidence)
            self._model_halt(evidence["reason"], self.now())
            return None, None, self.now()
        completed = self.now()
        if result.usage is None or result.usage.model != request.model or completed < at:
            evidence["reason"] = "OPTION_MODEL_COST_UNKNOWN"
            self._model_halt(evidence["reason"], completed)
            return None, None, completed
        coherent = (
            result.counted_input_tokens == result.usage.input_tokens
            and result.usage.input_tokens <= self.judgment_limits.max_input_tokens
            and result.usage.output_tokens <= self.judgment_limits.max_output_tokens
        )
        selected = next(
            (c for c in candidates if c.candidate_id == result.choice.candidate_id), None
        )
        timely = (
            self._model_timely(request, at, completed)
            and key == "degen:" + str(int(completed.timestamp()) // 300)
            and selected is not None
            and completed < selected.admission.valid_until
        )
        if result.error is not None or not coherent or not timely:
            selected = None
        proposal = (
            selected.proposal.model_copy(update={"thesis": result.choice.thesis})
            if selected
            else OptionProposal(action="HOLD", thesis=result.choice.thesis)
        )
        self.engine.record_model_usage(key, result.usage, proposal, now=completed)
        if not coherent or (
            result.choice.action == "SELECT"
            and not any(c.candidate_id == result.choice.candidate_id for c in candidates)
        ):
            self._model_halt("OPTION_MODEL_EVIDENCE_REJECTED", completed)
        evidence["reason"] = (
            "MODEL_SELECTED_ADMITTED_CANDIDATE" if selected else "MODEL_HOLD_OR_REJECTED"
        )
        return selected, proposal, completed

    async def supervise(self, quotes=(), underlyings=()):
        """Fast owned-position management, independent of the five-minute entry claim."""
        frame = DegenFrame(quotes=quotes, underlyings=underlyings)
        from app.options.swing_lifecycle import observe_quotes

        observe_quotes(self, frame.underlyings)
        with self.engine.journal.read() as db:
            ledger = self._bound(db)
            held = self._held_instrument(db, ledger)
        matched = [q for q in frame.quotes if q.instrument == held]
        underlying = [q for q in frame.underlyings if held and q.symbol == held.contract.underlying]
        if self.position_policy is not None:
            self._position_quotes = tuple(matched) if len(matched) == 1 else ()
            self._position_underlyings = tuple(underlying) if len(underlying) == 1 else ()
        return await self.engine.protective_tick(
            matched[0] if len(matched) == 1 else None,
            underlying[0] if len(underlying) == 1 else None,
            now=self.now(),
        )

    async def cycle(self, frame):
        frame = DegenFrame.model_validate(frame.model_dump(warnings=False))
        if frame.stocks and self.stock_policy is None:
            raise ValueError("Stock frames require explicit mixed selection enrollment")
        if frame.swing_batches and (
            self.swing_policy is None or self.swing_policy.family_batch is None
        ):
            raise ValueError("Swing batches require explicit frozen enrollment")
        if frame.swing and self.swing_policy and self.swing_policy.family_batch:
            raise ValueError("Joint Swing accepts only complete original batches")
        if frame.scope is not None and self.scope_policy is None:
            raise ValueError("Scope frames require explicit shared enrollment")
        at = self.now()
        # One durable attempt per actual five-minute clock slot, including HOLD,
        # failed inputs and interruption. Repeated calls do not read the venue.
        key = "degen:" + str(int(at.timestamp()) // 300)
        digest = fingerprint(frame)
        with self.engine.journal.write() as db:
            self._bound(db)
            previous = db.execute(
                "SELECT * FROM execution_option_opportunities WHERE cycle_key=?", (key,)
            ).fetchone()
            if previous:
                return (
                    json.loads(previous["result_json"])
                    if previous["status"] != "STARTED" and previous["result_json"]
                    else {
                        "cycle_key": key,
                        "status": "IN_PROGRESS",
                        "reason": "CYCLE_ALREADY_ATTEMPTED",
                    }
                )
            db.execute(
                "INSERT INTO execution_option_opportunities VALUES(?,?,?,?,'STARTED',NULL)",
                (key, digest, at.isoformat(), frame.model_dump_json()),
            )
            self.engine.journal.event(
                db, at, "DEGEN_CYCLE_STARTED", {"cycle_key": key, "input_hash": digest}
            )
        try:
            reconciled = await self.engine.reconcile_fixture(now=at)
            if not reconciled["reconciled"]:
                return self._finish(
                    key,
                    {
                        "status": "HOLD",
                        "reason": "AUTHORITATIVE_RECONCILIATION_REQUIRED",
                        "issues": reconciled["issues"],
                    },
                )
            at = self.now()
            with self.engine.journal.read() as db:
                ledger = self._bound(db)
                held = self._held_instrument(db, ledger)
            if self.stock_policy is not None:
                from app.mixed.native_store import position as stock_position
                from app.mixed.native_store import unresolved as stock_unresolved

                with self.engine.journal.read() as db:
                    stock = stock_position(self.engine, db)
                    pending_stock = stock_unresolved(db)
                if stock is not None:
                    supplied = [
                        x.quote for x in frame.stocks if x.quote.instrument == stock.instrument
                    ]
                    quote = supplied[0] if len(supplied) == 1 else None
                    managed = await self.engine.protective_stock_tick(quote, now=at)
                    if self.position_policy is not None and managed.get("status") == "HEALTHY":
                        from app.mixed.position import run

                        return await run(self, key, frame)
                    return self._finish(
                        key,
                        {
                            "status": "HELD",
                            "selected_asset": "STOCK",
                            "management": managed,
                            "entry_allowed": False,
                        },
                    )
                if pending_stock:
                    return self._finish(key, {"status": "HOLD", "reason": "STOCK_ORDER_UNRESOLVED"})
            if ledger.position:
                # Exact owned identity comes from the journal, never a current chain.
                if (
                    self.scope_policy is not None
                    and held.contract.underlying == "SPX"
                    and frame.scope is not None
                ):
                    result = await self.supervise(
                        (frame.scope.frame.quote,), (frame.scope.underlying,)
                    )
                else:
                    result = await self.supervise(frame.quotes, frame.underlyings)
                if self.position_policy is not None and result.get("status") == "HEALTHY":
                    from app.options.position_coordination import run_position_cycle

                    return await run_position_cycle(self, key, frame)
                return self._finish(
                    key, {"status": "HELD", "management": result, "entry_allowed": False}
                )
            if held:
                return self._finish(
                    key,
                    {
                        "status": "HOLD",
                        "reason": "ORDER_UNRESOLVED",
                        "instrument_id": held.instrument_id,
                    },
                )
            self.engine.assess(None, None, now=at)
            if frame.swing_batches and (
                self.swing_policy is None or self.swing_policy.family_batch is None
            ):
                raise ValueError("Swing batches require explicit enrollment")
            if self.swing_policy is not None:
                from app.options.shared_strategy import lock_seeds

                if self.swing_policy.family_batch is not None:
                    from app.options.swing_batch import lock_batches

                    if frame.swing:
                        raise ValueError("Complete original Swing batches required")
                    lock_batches(self, frame.swing_batches)
                else:
                    if frame.swing_batches:
                        raise ValueError("Swing batches require explicit enrollment")
                    lock_seeds(self, frame.swing)
                from app.options.swing_lifecycle import observe_quotes

                observe_quotes(self, frame.underlyings)
            planned = self.quote_plan(
                frame.histories, frame.inventories, frame.swing, swing_batches=frame.swing_batches
            )
            if self.swing_policy and self.swing_policy.unfilled_lifecycle is not None:
                from app.options.swing_lifecycle import retain_scans

                retain_scans(self, planned["scans"])
            if planned["purpose"] != "CANDIDATE_SHORTLIST":
                return self._finish(key, {"status": "HOLD", "reason": planned["purpose"]})
            expected = {i.instrument_id: i for i in planned["instruments"]}
            quotes = {q.instrument.instrument_id: q for q in frame.quotes}
            underlyings = {q.symbol: q for q in frame.underlyings}
            evidence = {
                **(
                    {"swing_batch_version": self.swing_policy.family_batch}
                    if self.swing_policy and self.swing_policy.family_batch
                    else {}
                ),
                **self._family_evidence(),
                "scans": [s.model_dump(mode="json") for s in planned["scans"]],
                "read_plans": [p.model_dump(mode="json") for p in planned["plans"]],
            }
            if (
                len(expected) != len(planned["instruments"])
                or len(quotes) != len(frame.quotes)
                or set(quotes) != set(expected)
                or any(quotes[k].instrument != i for k, i in expected.items())
                or len(underlyings) != len(frame.underlyings)
                or set(underlyings) != set(self.policy.symbols)
            ):
                return self._finish(
                    key,
                    {
                        "status": "HOLD",
                        "reason": "EXACT_REQUESTED_QUOTE_COVERAGE_REQUIRED",
                        **evidence,
                    },
                )
            with self.engine.journal.read() as db:
                account = self.engine._account(db, self.now())
            candidates, rejections = [], {}
            for scan, plan in zip(planned["scans"], planned["plans"], strict=True):
                matched = tuple(quotes[i.instrument_id] for i in plan.instruments)
                session = (
                    self.engine._session(plan.instruments[0].contract, self.now())
                    if plan.instruments
                    else None
                )
                accepted, rejected = admit_candidates(
                    scan,
                    plan,
                    matched,
                    underlyings[scan.symbol],
                    account,
                    self.engine._effective_limits(),
                    session,
                    now=planned["scans"][0].evaluated_at,
                )
                candidates.extend(accepted)
                rejections.update(rejected)
            evidence.update(
                candidates=[c.model_dump(mode="json") for c in candidates], rejections=rejections
            )
            if self.swing_policy and self.swing_policy.family_batch and len(candidates) > 24:
                return self._finish(
                    key,
                    {
                        **evidence,
                        "candidates": [],
                        "candidate_capacity_rejected": len(candidates),
                        "status": "HOLD",
                        "reason": "JOINT_CANDIDATE_CAPACITY_EXCEEDED",
                    },
                )
            shared_choice = None
            if self.stock_policy is not None:
                from app.mixed.selection import collect as collect_stocks

                collect_stocks(self, key, frame, evidence)
            if self.scope_policy is not None:
                from app.options.scope_arbitration import collect, execute_scope

                shared_choice = collect(self, key, frame, evidence)
                if (
                    self.stock_policy is None
                    and self.scope_policy.version == "shared-scope-entry-v1"
                    and (candidates or evidence.get("scope_candidate"))
                ):
                    from app.options.entry_coordination import run_entry_cycle

                    return await run_entry_cycle(
                        self,
                        key,
                        candidates,
                        planned["scans"],
                        account,
                        quotes,
                        underlyings,
                        evidence,
                    )
                if (
                    self.stock_policy is None
                    and shared_choice
                    and shared_choice["family"] == "SCOPE"
                ):
                    return await execute_scope(self, key, frame, evidence)
            if self.stock_policy is not None:
                from app.mixed.selection import execute_stock, select

                shared_choice = select(self, key, evidence)
                if self.stock_policy.paid_selection is not None and (
                    candidates
                    or evidence.get("stock_candidates")
                    or evidence.get("scope_candidate")
                ):
                    from app.options.entry_coordination import run_entry_cycle

                    return await run_entry_cycle(
                        self,
                        key,
                        candidates,
                        planned["scans"],
                        account,
                        quotes,
                        underlyings,
                        evidence,
                    )
                if shared_choice and shared_choice["asset"] == "STOCK":
                    return await execute_stock(self, key, frame, evidence, shared_choice)
                if shared_choice and shared_choice["family"] == "SCOPE":
                    return await execute_scope(self, key, frame, evidence)
            if not candidates:
                hold = OptionProposal(
                    action="HOLD",
                    thesis="Degen: no contract passed completed setup and deterministic admission",
                )
                self.engine.prepare(key, hold, now=self.now())
                return self._finish(
                    key, {"status": "HOLD", "reason": "NO_ADMITTED_CONTRACT", **evidence}
                )
            selected = (
                next(c for c in candidates if c.candidate_id == shared_choice["candidate_id"])
                if shared_choice
                else candidates[0]
            )
            if self.entry_policy is not None:
                from app.options.entry_coordination import run_entry_cycle

                return await run_entry_cycle(
                    self, key, candidates, planned["scans"], account, quotes, underlyings, evidence
                )
            proposal, prepare_at, origin = selected.proposal, self.now(), "DETERMINISTIC"
            if self.judgment_limits is not None:
                selected, proposal, prepare_at = await self._choose(
                    key, candidates, planned["scans"], account, evidence
                )
                origin = "MODEL"
                if selected is None:
                    if proposal is not None:
                        self.engine.prepare(key, proposal, now=prepare_at, origin=origin)
                    return self._finish(key, {**evidence, "status": "HOLD"})
            with self.engine.journal.write() as db:
                self._bound(db)
                db.execute(
                    "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                    (
                        json.dumps(
                            {
                                "status": "SELECTED",
                                "candidate_id": selected.candidate_id,
                                **evidence,
                            },
                            sort_keys=True,
                        ),
                        key,
                    ),
                )
            quotes, underlyings = self._execution_market(quotes, underlyings)
            prepared = self.engine.prepare(
                key,
                proposal,
                quotes[selected.instrument.instrument_id],
                underlyings[selected.symbol],
                now=self.now(),
                origin=origin,
                ceiling=selected.admission if self.judgment_limits is not None else None,
            )
            if prepared["status"] != "PREPARED":
                return self._finish(
                    key,
                    {
                        **evidence,
                        "status": "HOLD",
                        "reason": "FRESH_EXECUTION_ADMISSION_REJECTED",
                        "prepared": prepared,
                    },
                )
            status = await self.engine.dispatch(
                prepared["client_id"],
                quotes[selected.instrument.instrument_id],
                underlyings[selected.symbol],
                now=self.now(),
            )
            return self._finish(
                key,
                {
                    "status": status,
                    "client_id": prepared["client_id"],
                    "candidate_id": selected.candidate_id,
                    **evidence,
                },
            )
        except EntryModelBlocked as exc:
            return self._finish(
                key,
                {"status": "HOLD", "reason": "ENTRY_MODEL_RISK_PAUSE", "blocker": str(exc)},
            )
        except BaseException as exc:
            result = {
                "status": "HOLD",
                "reason": "DEGEN_CYCLE_FAILED",
                "error_class": type(exc).__name__,
                **({"blocker": str(exc)} if isinstance(exc, ExecutionBlocked) else {}),
            }
            if not isinstance(exc, Exception):
                result["reason"] = "DEGEN_CYCLE_INTERRUPTED"
            with self.engine.journal.write() as db:
                self._bound(db)
                self.engine._halt(db, result["reason"], self.now())
            finished = self._finish(key, result)
            if not isinstance(exc, Exception):
                raise
            return finished

    def report(self):
        """Stored evidence only. No collector, model, supervision or order call."""
        with self.engine.journal.read() as db:
            self._bound(db)
            return {
                "mode": "MIXED_PAPER_FIXTURE"
                if self.stock_policy is not None
                else "OPTIONS_PAPER_FIXTURE",
                "live_enabled": False,
                "strategy": json.loads(self._frozen),
                "cycles": [
                    {
                        **dict(r),
                        "inputs": json.loads(r["inputs_json"]),
                        "result": json.loads(r["result_json"]) if r["result_json"] else None,
                    }
                    for r in db.execute(
                        "SELECT * FROM execution_option_opportunities ORDER BY started_at DESC LIMIT 100"
                    )
                ],
            }
