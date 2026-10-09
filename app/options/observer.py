"""Bounded stored options evidence. No owner, recovery, venue or provider attachment."""

import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from decimal import Context, Decimal, localcontext
from pathlib import Path
from urllib.parse import quote

from pydantic import TypeAdapter

from app.domain.models import utc_now
from app.options.coordinator import DegenFrame
from app.options.engine import clock
from app.options.governor import _fresh
from app.options.judgment import CandidateChoice
from app.options.lifecycle import (
    OptionExecutionPolicy,
    OptionFill,
    OptionIntent,
    OptionLedger,
    OptionReceipt,
    OptionVenueSnapshot,
)
from app.options.models import Name, OptionLimits
from app.options.selection import DegenCandidate

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_REPORT_BYTES = 1024 * 1024
MAX_MODEL_ROWS = 10000
READ_SECONDS = 2
REQUIRED = frozenset(
    {
        "execution_control",
        "execution_events",
        "execution_orders",
        "execution_fills",
        "execution_model_calls",
        "execution_supervisor",
        "execution_alerts",
        "execution_option_decisions",
        "execution_option_receipts",
    }
)


def _json(raw):
    if not isinstance(raw, str) or len(raw.encode()) > MAX_RECORD_BYTES:
        raise ValueError("Bounded stored JSON required")
    return json.loads(raw)


def _private(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 0 < info.st_size <= MAX_DATABASE_BYTES
    ):
        raise ValueError("Private bounded owned database required")
    return info.st_dev, info.st_ino


def _age(stamp, now):
    return (now - clock(stamp)).total_seconds() if stamp is not None else None


def _health(stamp, now, maximum):
    age = _age(stamp, now)
    return (
        "MISSING"
        if age is None
        else "FUTURE"
        if age < 0
        else "STALE"
        if age >= maximum
        else "FRESH"
    )


def _contract(contract):
    return contract.model_dump(mode="json") | {"contract_id": contract.contract_id}


class OptionObserver:
    def __init__(self, journal, population_id, *, clock=utc_now):
        self.path = Path(journal)
        if not self.path.is_absolute():
            raise ValueError("Explicit absolute journal path required")
        self.population_id = TypeAdapter(Name).validate_python(population_id)
        self.clock = clock

    @contextmanager
    def read(self):
        identity = _private(self.path)
        db = sqlite3.connect(
            "file:" + quote(str(self.path)) + "?mode=ro", uri=True, timeout=READ_SECONDS
        )
        db.row_factory = sqlite3.Row
        deadline = time.monotonic() + READ_SECONDS
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("BEGIN")
            if _private(self.path) != identity:
                raise ValueError("Database identity changed")
            yield db
            if _private(self.path) != identity or time.monotonic() >= deadline:
                raise ValueError("Database identity/deadline changed")
        finally:
            db.close()

    def report(self, *, limit=25, before=None, family="ALL"):
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (before is not None and (type(before) is not int or before < 1))
            or family not in {"ALL", "DEGEN", "SWING", "SCOPE"}
        ):
            raise ValueError("Bounded observer page required")
        now = clock(self.clock())
        base = {
            "version": "option-stored-observer-v1",
            "mode": "OPTIONS_PAPER_FIXTURE",
            "live_enabled": False,
            "execution_authority": False,
            "network_calls": False,
            "observed_at": now.isoformat(),
            "population_id": self.population_id,
        }
        try:
            with self.read() as db, localcontext(Context(prec=192)):
                data = self._snapshot(db, now, limit, before, family)
            result = base | data
            if len(json.dumps(result).encode()) > MAX_REPORT_BYTES:
                raise ValueError("Observer response capacity exceeded")
            return result
        except FileNotFoundError:
            return base | {"status": "EMPTY", "reason": "DATABASE_NOT_CREATED"}
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, ArithmeticError):
            return base | {"status": "UNAVAILABLE", "reason": "STORED_EVIDENCE_UNAVAILABLE"}

    def _snapshot(self, db, now, limit, before, family):
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED <= tables:
            raise ValueError("Existing options schema required")
        c = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
        config = _json(c["config_json"])
        if config["schema"] != "option-paper-execution-v1":
            raise ValueError("Separate options population required")
        limits = OptionLimits.model_validate(config["limits"])
        policy = OptionExecutionPolicy.model_validate(config["policy"])
        if limits.population_id != self.population_id:
            raise ValueError("Frozen population identity mismatch")
        ledger = OptionLedger.model_validate(_json(c["ledger_json"]))
        snapshot = (
            OptionVenueSnapshot.model_validate(_json(c["snapshot_json"]))
            if c["snapshot_json"]
            else None
        )
        issues = _json(c["issues_json"])
        if (
            not isinstance(issues, list)
            or len(issues) > 100
            or any(not isinstance(i, str) or len(i) > 500 for i in issues)
        ):
            raise ValueError("Bounded stored issues required")
        if snapshot and (
            snapshot.population_id != self.population_id or snapshot.account_id != limits.account_id
        ):
            raise ValueError("Snapshot identity mismatch")
        revision = db.execute("SELECT COALESCE(MAX(sequence),0) FROM execution_events").fetchone()[
            0
        ]
        active = db.execute("SELECT COUNT(*) FROM execution_orders WHERE active_lock=1").fetchone()[
            0
        ]
        orders = self._orders(db)
        model = self._costs(db, policy)
        account_health = _health(
            snapshot.captured_at if snapshot else None, now, limits.account_max_age_seconds
        )
        supervision = db.execute("SELECT * FROM execution_supervisor WHERE id=1").fetchone()
        heartbeat = None
        retained_status = "MISSING"
        if supervision:
            from datetime import datetime

            heartbeat = (
                clock(datetime.fromisoformat(supervision["heartbeat_at"]))
                if supervision["heartbeat_at"]
                else None
            )
            retained_status = supervision["status"]
        supervision_health = _health(heartbeat, now, policy.supervisor_max_age_seconds)
        supervised = (
            _json(supervision["result_json"])
            if supervision and supervision["result_json"]
            else None
        )
        if supervised and (not snapshot or supervised.get("snapshot_id") != snapshot.snapshot_id):
            supervision_health = "SNAPSHOT_MISMATCH"
        strategy = None
        if "execution_option_strategy" in tables:
            row = db.execute(
                "SELECT policy_json FROM execution_option_strategy WHERE id=1"
            ).fetchone()
            strategy = _json(row[0]) if row else None
        opportunities, page, counts, frames = self._opportunities(db, tables, limit, before, family)
        position = self._position(db, ledger, frames, limits, now)
        blockers = list(issues)
        if c["halted"]:
            blockers.append("ENTRY_HALTED")
        if account_health != "FRESH":
            blockers.append("ACCOUNT_" + account_health)
        if snapshot is None or not snapshot.complete:
            blockers.append("ACCOUNT_INCOMPLETE")
        if supervision_health != "FRESH" or retained_status != "HEALTHY":
            blockers.append("SUPERVISION_NOT_FRESH_HEALTHY")
        if active:
            blockers.append("ORDER_UNRESOLVED")
        if model["unknown_calls"]:
            blockers.append("MODEL_COST_UNKNOWN")
        if snapshot and snapshot.underlying_exposures:
            blockers.append("UNSUPPORTED_EXPOSURE")
        if ledger.position:
            blockers.append("POSITION_ALREADY_OWNED")
        alerts = [
            dict(r)
            for r in db.execute(
                "SELECT a.event_sequence,a.acknowledged_at,e.occurred_at,e.kind FROM execution_alerts a JOIN execution_events e ON e.sequence=a.event_sequence ORDER BY a.event_sequence DESC LIMIT 10"
            )
        ]
        unacked = db.execute(
            "SELECT COUNT(*) FROM execution_alerts WHERE acknowledged_at IS NULL"
        ).fetchone()[0]
        position_value = position["gross_bid_mark"] if position else "0"
        equity = None if position_value is None else ledger.cash + Decimal(position_value)
        after_model = (
            equity - Decimal(model["known_cost"])
            if equity is not None and model["unknown_calls"] == 0
            else None
        )
        if (
            active
            or issues
            or account_health != "FRESH"
            or snapshot is None
            or not snapshot.complete
            or snapshot.underlying_exposures
        ):
            equity = after_model = None
        fills = []
        for row in db.execute(
            "SELECT f.client_id,f.payload,o.intent_json FROM execution_fills f JOIN execution_orders o ON o.client_id=f.client_id ORDER BY f.rowid DESC LIMIT 100"
        ):
            fill = OptionFill.model_validate(_json(row["payload"]))
            intent = OptionIntent.model_validate(_json(row["intent_json"]))
            fills.append(
                {
                    "fill_id": fill.fill_id,
                    "client_id": row["client_id"],
                    "side": intent.side,
                    "contract": _contract(intent.instrument.contract),
                    "quantity": fill.quantity,
                    "price": str(fill.price),
                    "fee": str(fill.fee),
                    "occurred_at": fill.occurred_at.isoformat(),
                }
            )
        receipts = []
        for row in db.execute(
            "SELECT payload FROM execution_option_receipts ORDER BY rowid DESC LIMIT 25"
        ):
            receipt = OptionReceipt.model_validate(_json(row[0]))
            receipts.append(
                {
                    "kind": receipt.kind,
                    "occurred_at": receipt.occurred_at.isoformat(),
                    "quantity": receipt.quantity,
                    "cash_change": str(receipt.cash_change),
                    "contract": _contract(receipt.contract) if receipt.contract else None,
                }
            )
        return {
            "status": "OK",
            "revision": revision,
            "release": None,
            "restore_authority": "NOT_CHECKED_BY_OBSERVER",
            "worker_status": "NOT_RECORDED",
            "session_status": "NOT_RECORDED",
            "account": {
                "health": account_health,
                "captured_at": snapshot.captured_at.isoformat() if snapshot else None,
                "age_seconds": _age(snapshot.captured_at if snapshot else None, now),
                "cash": str(ledger.cash),
                "settled_cash": str(ledger.settled_cash),
                "position_state": "OWNED"
                if ledger.position
                else "PENDING_OR_UNKNOWN"
                if active
                else "FLAT"
                if not blockers
                else "NO_OWNED_POSITION_RECORDED",
            },
            "supervision": {
                "freshness": supervision_health,
                "recorded_status": retained_status,
                "heartbeat_at": heartbeat.isoformat() if heartbeat else None,
                "age_seconds": _age(heartbeat, now),
                "assessment": {
                    key: supervised.get(key) for key in ("status", "exit_reason", "issue")
                }
                if supervised
                else None,
            },
            "entry": {
                "halted": bool(c["halted"]),
                "halt_reason": c["halt_reason"],
                "recorded_blockers": list(dict.fromkeys(blockers)),
                "approval": "NOT_GRANTED_BY_OBSERVER",
            },
            "model": model,
            "economics": {
                "initial_capital": str(policy.capital),
                "realized_price_pnl": str(ledger.realized_pnl),
                "venue_fees_paid": str(ledger.fees_paid),
                "equity_before_exit_costs": str(equity) if equity is not None else None,
                "equity_after_known_model_cost_before_exit_costs": str(after_model)
                if after_model is not None
                else None,
                "data_cost": None,
                "host_cost": None,
                "all_costs_known": False,
                "spy_return": None,
                "comparison_status": "MATCHED_COHORT_BENCHMARK_NOT_IMPLEMENTED",
            },
            "strategy": {
                "status": "ENROLLED" if strategy else "NOT_ENROLLED",
                "setup_version": strategy["setup"].get("version") if strategy else None,
                "selection_version": strategy["selection"].get("version") if strategy else None,
                "model_enabled": bool(strategy and strategy.get("model")),
                "symbols": strategy["setup"].get("symbols", []) if strategy else [],
                "families": {
                    "DEGEN": "ENROLLED" if strategy else "NOT_ENROLLED",
                    "SWING": "NOT_IMPLEMENTED",
                    "SCOPE": "NOT_IMPLEMENTED",
                },
            },
            "position": position,
            "orders": orders,
            "active_orders": active,
            "opportunities": opportunities,
            "page": page,
            "cycle_counts": counts,
            "scheduler_coverage": "NOT_AUDITED",
            "fills": fills,
            "receipts": receipts,
            "alerts": {
                "unacknowledged": unacked,
                "delivery": "NOT_VERIFIED_FOR_OPTIONS",
                "recent": alerts,
            },
        }

    @staticmethod
    def _orders(db):
        result = []
        for row in db.execute("SELECT rowid,* FROM execution_orders ORDER BY rowid DESC LIMIT 100"):
            intent = OptionIntent.model_validate(_json(row["intent_json"]))
            result.append(
                {
                    "id": row["rowid"],
                    "client_id": intent.client_id,
                    "contract": _contract(intent.instrument.contract),
                    "side": intent.side,
                    "quantity": intent.quantity,
                    "limit_price": str(intent.limit_price),
                    "status": row["status"],
                    "unresolved": row["active_lock"] == 1,
                    "prepared_at": intent.prepared_at.isoformat(),
                    "attempted_at": row["attempted_at"],
                    "approval_expires_at": intent.approval_expires_at.isoformat(),
                }
            )
        return result

    @staticmethod
    def _costs(db, policy):
        rows = db.execute(
            "SELECT cost,usage_json FROM execution_model_calls LIMIT ?", (MAX_MODEL_ROWS + 1,)
        ).fetchall()
        if len(rows) > MAX_MODEL_ROWS or (rows and policy.cost_policy is None):
            raise ValueError("Model evidence capacity/policy mismatch")
        known, unknown, input_tokens, output_tokens = Decimal(0), 0, 0, 0
        for row in rows:
            if row["cost"] is None:
                unknown += 1
                continue
            from app.execution.economics import UsageEvidence

            usage = UsageEvidence.model_validate(_json(row["usage_json"]))
            amount = Decimal(row["cost"])
            expected = (
                usage.input_tokens * policy.cost_policy.input_per_million
                + usage.output_tokens * policy.cost_policy.output_per_million
            ) / 1000000
            if (
                usage.model != policy.cost_policy.model
                or not amount.is_finite()
                or amount != expected
            ):
                raise ValueError("Incoherent stored cost receipt")
            known += amount
            input_tokens += usage.input_tokens
            output_tokens += usage.output_tokens
        return {
            "enabled": policy.cost_policy is not None,
            "model": policy.cost_policy.model if policy.cost_policy else None,
            "known_cost": str(known),
            "unknown_calls": unknown,
            "attempts": len(rows),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_status": "UNKNOWN"
            if unknown
            else "CONFIGURED_ESTIMATE"
            if policy.cost_policy
            else "NOT_CONFIGURED",
        }

    @staticmethod
    def _opportunities(db, tables, limit, before, family):
        empty = (
            [],
            {
                "limit": limit,
                "before": before,
                "has_older": False,
                "next_before": None,
                "family": family,
            },
            {},
            [],
        )
        if "execution_option_opportunities" not in tables:
            return empty
        counts = {
            r[0]: r[1]
            for r in db.execute(
                "SELECT status,COUNT(*) FROM execution_option_opportunities GROUP BY status"
            )
        }
        # Market evidence is current across navigation; a historical page cannot replace it.
        frames = [
            DegenFrame.model_validate(_json(r[0]))
            for r in db.execute(
                "SELECT inputs_json FROM execution_option_opportunities ORDER BY rowid DESC LIMIT 100"
            )
        ]
        if family in {"SWING", "SCOPE"}:
            return empty[:2] + (counts, frames)
        rows = db.execute(
            "SELECT rowid,* FROM execution_option_opportunities WHERE (? IS NULL OR rowid<?) ORDER BY rowid DESC LIMIT ?",
            (before, before, limit + 1),
        ).fetchall()
        has_older = len(rows) > limit
        output = []
        for row in rows[:limit]:
            data = _json(row["result_json"]) if row["result_json"] else {}
            raw_candidates = data.get("candidates", [])
            if not isinstance(raw_candidates, list) or len(raw_candidates) > 24:
                raise ValueError("Stored candidate bound exceeded")
            candidates = [DegenCandidate.model_validate(c) for c in raw_candidates]
            raw_choice = data.get("model_result", {}).get("choice")
            choice = (
                CandidateChoice.model_validate(raw_choice).model_dump(mode="json")
                if raw_choice
                else None
            )
            selected = data.get("candidate_id")
            output.append(
                {
                    "id": row["rowid"],
                    "family": "DEGEN",
                    "cycle_key": row["cycle_key"],
                    "started_at": row["started_at"],
                    "storage_status": row["status"],
                    "status": data.get("status", "IN_PROGRESS"),
                    "reason": data.get("reason"),
                    "candidate_id": selected,
                    "client_id": data.get("client_id"),
                    "candidates": [
                        {
                            "candidate_id": c.candidate_id,
                            "setup": c.family,
                            "contract": _contract(c.instrument.contract),
                            "outcome": c.admission.outcome,
                            "quantity_ceiling": c.admission.quantity,
                            "limit_ceiling": str(c.admission.limit_price),
                            "full_premium_ceiling": str(c.admission.full_premium_loss),
                            "approved_until": c.admission.valid_until.isoformat()
                            if c.admission.valid_until
                            else None,
                        }
                        for c in candidates
                    ],
                    "model_choice": choice,
                    "error_class": data.get("error_class") or data.get("model_error_class"),
                }
            )
        return (
            output,
            {
                "limit": limit,
                "before": before,
                "has_older": has_older,
                "next_before": output[-1]["id"] if has_older else None,
                "family": family,
            },
            counts,
            frames,
        )

    @staticmethod
    def _position(db, ledger, frames, limits, now):
        p = ledger.position
        if p is None:
            return None
        row = db.execute(
            "SELECT intent_json FROM execution_orders WHERE client_id=?", (p.entry_client_id,)
        ).fetchone()
        entry = OptionIntent.model_validate(_json(row[0]))
        if entry.instrument.contract != p.contract:
            raise ValueError("Owned position/entry identity mismatch")

        def same_id(q):
            return (
                q.instrument.provider == entry.instrument.provider
                and q.instrument.instrument_id == entry.instrument.instrument_id
            )

        quotes = [q for f in frames for q in f.quotes if same_id(q)]
        # A fresh protective decision may be newer than an entry-cycle frame.
        from app.options.models import OptionQuote

        for row in db.execute(
            "SELECT inputs_json FROM execution_option_decisions ORDER BY rowid DESC LIMIT 100"
        ):
            data = _json(row[0])
            if data.get("quote"):
                q = OptionQuote.model_validate(data["quote"])
                if same_id(q):
                    quotes.append(q)
        q = max(quotes, key=lambda q: q.received_at) if quotes else None
        conflict = q is not None and any(
            other.received_at == q.received_at and other != q for other in quotes
        )
        fresh = q is not None and _fresh(
            q.source_at,
            q.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
        usable = bool(
            fresh
            and not conflict
            and q.complete
            and q.entitlement == "REALTIME"
            and q.source == limits.option_source
            and q.instrument.provider == limits.provider
            and q.instrument == entry.instrument
            and q.instrument.metadata_complete
            and q.instrument.option_tradable
            and q.bid is not None
            and q.bid > 0
            and q.bid_size >= p.quantity
            and (q.ask is None or q.ask >= q.bid)
        )
        underlyings = [
            u for f in frames for u in f.underlyings if u.symbol == p.contract.underlying
        ]
        underlying = max(underlyings, key=lambda u: u.received_at) if underlyings else None
        return {
            "contract": _contract(p.contract),
            "quantity": p.quantity,
            "cost_basis": str(p.basis),
            "original_invalidation": str(p.original_underlying_invalidation),
            "tightened_invalidation": str(p.tightened_underlying_invalidation),
            "exit_at": p.exit_at.isoformat(),
            "exit_reason": p.exit_reason,
            "exit_required_at": p.exit_required_at.isoformat() if p.exit_required_at else None,
            "supervision_issue": p.supervision_issue,
            "thesis": entry.thesis,
            "quote_status": "USABLE_STORED_BID"
            if usable
            else "CONFLICTING"
            if conflict
            else "MISSING"
            if q is None
            else "STALE_OR_INVALID",
            "quote": q.model_dump(mode="json") if q else None,
            "quote_age_seconds": _age(q.source_at, now) if q else None,
            "underlying": underlying.model_dump(mode="json") if underlying else None,
            "underlying_age_seconds": _age(underlying.source_at, now) if underlying else None,
            "gross_bid_mark": str(q.bid * p.quantity * p.contract.multiplier) if usable else None,
            "mark_note": "Stored bid evidence only; no fill, exit costs or execution approval",
        }
