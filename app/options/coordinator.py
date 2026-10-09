"""Owned deterministic Degen PAPER cycles; model/provider adapters remain separate."""

import json

from pydantic import Field

from app.domain.models import utc_now
from app.execution.engine import ExecutionBlocked
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
    def __init__(self, engine, policy, selection, *, create=False, clock=utc_now):
        if type(engine) is not OptionExecution or getattr(engine, "_degen_owner", None) is not None:
            raise ValueError("One active built-in options owner is required")
        self.engine, self.clock = engine, clock
        self.policy = DegenPolicy.model_validate(policy.model_dump(warnings=False))
        self.selection = ContractSelectionPolicy.model_validate(
            selection.model_dump(warnings=False)
        )
        if (
            not set(self.policy.symbols) <= set(engine.limits.allowed_underlyings)
            or self.selection.max_quote_contracts * len(self.policy.symbols) > 8
        ):
            raise ValueError(
                "Frozen symbols and global quote capacity must fit the execution owner"
            )
        frozen = json.dumps(
            {
                "setup": self.policy.model_dump(mode="json"),
                "selection": self.selection.model_dump(mode="json"),
            },
            sort_keys=True,
        )
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

    def _bound(self, db):
        self.engine._control(db)
        if getattr(self.engine, "_degen_owner", None) is not self:
            raise ExecutionBlocked("DEGEN_OWNER_CHANGED")
        row = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
        current = json.dumps(
            {
                "setup": self.policy.model_dump(mode="json"),
                "selection": self.selection.model_dump(mode="json"),
            },
            sort_keys=True,
        )
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
                selected.proposal,
                quotes[selected.instrument.instrument_id],
                underlyings[selected.symbol],
                now=self.now(),
            )
            if prepared["status"] != "PREPARED":
                return self._finish(
                    key,
                    {
                        "status": "HOLD",
                        "reason": "FRESH_EXECUTION_ADMISSION_REJECTED",
                        "prepared": prepared,
                        **evidence,
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
                "strategy": {
                    "setup": self.policy.model_dump(mode="json"),
                    "selection": self.selection.model_dump(mode="json"),
                },
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
