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
from app.options import judgment
from app.options.degen import DegenHistory, DegenPolicy, scan_degen
from app.options.engine import OptionExecution, clock, fingerprint
from app.options.governor import _fresh
from app.options.lifecycle import OptionIntent, OptionLedger
from app.options.models import OptionProposal, OptionQuote, OptionRecord, UnderlyingQuote
from app.options.selection import (
    ContractReadPlan,
    ContractSelectionPolicy,
    OptionInventory,
    admit_candidates,
    plan_contract_reads,
)


class DegenFrame(OptionRecord):
    histories: tuple[DegenHistory, ...] = Field(default=(), max_length=2)
    inventories: tuple[OptionInventory, ...] = Field(default=(), max_length=2)
    quotes: tuple[OptionQuote, ...] = Field(default=(), max_length=8)
    underlyings: tuple[UnderlyingQuote, ...] = Field(default=(), max_length=2)


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
    ):
        if type(engine) is not OptionExecution or getattr(engine, "_degen_owner", None) is not None:
            raise ValueError("One active built-in options owner is required")
        self.engine, self.clock = engine, clock
        self.policy = DegenPolicy.model_validate(policy.model_dump(warnings=False))
        self.selection = ContractSelectionPolicy.model_validate(
            selection.model_dump(warnings=False)
        )
        if (judgment_limits is None) != (key_file is None):
            raise ValueError("Model limits and private key path must be paired")
        self.judgment_limits = (
            JudgmentLimits.model_validate(judgment_limits.model_dump(warnings=False))
            if judgment_limits is not None
            else None
        )
        self.key_file = Path(key_file) if key_file is not None else None
        if self.key_file is not None and (
            not self.key_file.is_absolute() or engine.policy.cost_policy is None
        ):
            raise ValueError("Model requires absolute private key path and frozen cost policy")
        if (
            not set(self.policy.symbols) <= set(engine.limits.allowed_underlyings)
            or self.selection.max_quote_contracts * len(self.policy.symbols) > 8
        ):
            raise ValueError(
                "Frozen symbols and global quote capacity must fit the execution owner"
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
        engine._degen_owner = self

    def now(self):
        return clock(self.clock())

    def _configuration(self):
        config = {
            "setup": self.policy.model_dump(mode="json"),
            "selection": self.selection.model_dump(mode="json"),
        }
        if self.judgment_limits is not None:
            config["model"] = {
                "configuration": judgment.configuration(
                    self.engine.policy.cost_policy, self.judgment_limits
                ),
                "key_file": str(self.key_file),
            }
        return json.dumps(config, sort_keys=True)

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

    def quote_plan(self, histories, inventories):
        """Local planning performs no provider/model/order operation."""
        at = self.now()
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
        return {
            "purpose": "CANDIDATE_SHORTLIST",
            "instruments": tuple(i for p in plans for i in p.instruments),
            "scans": scans,
            "plans": plans,
        }

    def _finish(self, key, result):
        result = json.loads(json.dumps({"cycle_key": key, **result}, sort_keys=True))
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
            secret = model_key(self.key_file)
        except (OSError, ValueError):
            evidence["reason"] = "PRIVATE_MODEL_KEY_UNAVAILABLE"
            return None, None, at
        packet = judgment.CandidatePacket(
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
                self.engine.policy.cost_policy, self.judgment_limits
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
            result = await judgment.run_candidate_process(request, secret)
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
            time.monotonic() < request.deadline_monotonic
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
        with self.engine.journal.read() as db:
            ledger = self._bound(db)
            held = self._held_instrument(db, ledger)
        matched = [q for q in frame.quotes if q.instrument == held]
        underlying = [q for q in frame.underlyings if held and q.symbol == held.contract.underlying]
        return await self.engine.protective_tick(
            matched[0] if len(matched) == 1 else None,
            underlying[0] if len(underlying) == 1 else None,
            now=self.now(),
        )

    async def cycle(self, frame):
        frame = DegenFrame.model_validate(frame.model_dump(warnings=False))
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
            if ledger.position:
                # Exact owned identity comes from the journal, never a current chain.
                result = await self.supervise(frame.quotes, frame.underlyings)
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
            planned = self.quote_plan(frame.histories, frame.inventories)
            if planned["purpose"] != "CANDIDATE_SHORTLIST":
                return self._finish(key, {"status": "HOLD", "reason": planned["purpose"]})
            expected = {i.instrument_id: i for i in planned["instruments"]}
            quotes = {q.instrument.instrument_id: q for q in frame.quotes}
            underlyings = {q.symbol: q for q in frame.underlyings}
            evidence = {
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
            plans = {p.symbol: p for p in planned["plans"]}
            for scan in planned["scans"]:
                if scan.symbol not in plans:
                    continue
                plan = plans[scan.symbol]
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
            if not candidates:
                hold = OptionProposal(
                    action="HOLD",
                    thesis="Degen: no contract passed completed setup and deterministic admission",
                )
                self.engine.prepare(key, hold, now=self.now())
                return self._finish(
                    key, {"status": "HOLD", "reason": "NO_ADMITTED_CONTRACT", **evidence}
                )
            selected = candidates[0]
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
        except BaseException as exc:
            result = {
                "status": "HOLD",
                "reason": "DEGEN_CYCLE_FAILED",
                "error_class": type(exc).__name__,
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
                "mode": "OPTIONS_PAPER_FIXTURE",
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
