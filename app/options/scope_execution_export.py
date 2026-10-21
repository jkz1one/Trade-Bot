"""Portable, read-only Scope native evidence and full-cost accounting reconstruction."""

import json
import sqlite3
from datetime import datetime
from decimal import Decimal

from app.execution import economics
from app.options.attribution import order_attribution
from app.options.engine import clock, exact, fingerprint
from app.options.lifecycle import OptionExecutionPolicy, OptionIntent, OptionLedger
from app.options.loss_evidence import export_loss_control
from app.options.models import OptionLimits
from app.options.position_outcome import _settlement_links, native_position_outcome
from app.options.scope_observer import stored_scope

# Fixed schema only. No exported SQL, filenames, operator credentials or owner restore authority.
SCHEMA = {
    "execution_control": "id config_json ledger_json halted halt_reason snapshot_json issues_json",
    "execution_orders": "client_id source_key fingerprint intent_json approval_json status active_lock order_id attempted_at observation_json",
    "execution_fills": "fill_id client_id payload",
    "execution_events": "sequence occurred_at kind client_id payload",
    "execution_model_calls": "source_key packet_hash started_at usage_json request_id decision_hash cost",
    "execution_cost_policy": "id policy_json",
    "execution_judgment_policy": "id policy_json blocked_reason",
    "execution_commands": "command_id fingerprint result_json",
    "execution_option_decisions": "source_key fingerprint inputs_json result_json",
    "execution_option_receipts": "receipt_id payload",
    "execution_option_opportunities": "cycle_key fingerprint started_at inputs_json status result_json",
    "execution_option_strategy": "id policy_json",
    "execution_option_swing_seeds": "session symbol seed_hash seed_json",
    "execution_option_swing_terminals": "seed_hash terminal_json",
    "execution_option_loss_control": "id policy_json state_json",
    "execution_option_loss_outcomes": "entry_client_id outcome_hash record_json",
    "execution_option_scope_watch_policy": "id config_json last_action_at",
    "execution_option_scope_watches": "play_key session_date active_lock record_json",
    "execution_option_scope_watch_actions": "action_key request_hash result_json",
    "execution_option_scope_entries": "play_key client_id receipt_json",
    "execution_option_scope_runtime_inputs": "sequence packet_hash packet_json accepted_at action_key status result_json",
}
MAX_BYTES = 128 * 1024 * 1024


def _cost(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("Explicit nonnegative Scope cost required")
    value = Decimal(value)
    if not value.is_finite() or value < 0:
        raise ValueError("Explicit nonnegative Scope cost required")
    return value


@exact
def _report(db, now, data_cost, host_cost):
    from app.options.lifecycle import OptionReceipt

    config = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    limits = OptionLimits.model_validate(config["limits"])
    policy = OptionExecutionPolicy.model_validate(config["policy"])
    if (
        config["schema"] != "option-paper-execution-v1"
        or Decimal(config["capital"]) != policy.capital
    ):
        raise ValueError("Frozen Scope owner configuration mismatch")
    if policy.scope_execution != "scope-native-v1":
        raise ValueError("Native Scope export requires frozen enrollment")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    scope = stored_scope(db, tables, limits, now, json.loads, owner_policy=policy)
    runtime = {}
    if "execution_option_scope_runtime_inputs" in tables:
        from app.options.scope_runtime import stored_inputs

        runtime["scope_runtime"] = stored_inputs(db, now)
    orders = db.execute("SELECT * FROM execution_orders ORDER BY rowid").fetchall()
    attrs = [order_attribution(db, r) for r in orders]
    buys = [OptionIntent.model_validate_json(r["intent_json"]) for r in orders]
    buys = [i for i in buys if i.side == "BUY"]
    shared = policy.scope_arbitration is not None
    if shared:
        from app.options.scope_arbitration import configuration

        families = set(configuration(db).family_priority)
    else:
        families = {"SCOPE"}
    if any(i.entry_lineage is None or i.entry_lineage.family not in families for i in buys):
        raise ValueError("Scope export contains an unrelated entry")
    if {i.client_id for i in buys if i.entry_lineage.family == "SCOPE"} != {
        r[0] for r in db.execute("SELECT client_id FROM execution_option_scope_entries")
    }:
        raise ValueError("Scope native entry coverage mismatch")
    outcomes = [native_position_outcome(db, i.client_id, limits.population_id) for i in buys]
    # Reconstruct the complete cash/fee/settlement ledger even if no entry filled.
    receipts = [
        OptionReceipt.model_validate_json(r[0])
        for r in db.execute("SELECT payload FROM execution_option_receipts")
    ]
    _settlement_links(db, orders, receipts, policy)
    events = db.execute("SELECT * FROM execution_events ORDER BY sequence").fetchall()
    if any(clock(datetime.fromisoformat(e["occurred_at"])) > now for e in events):
        raise ValueError("Scope export contains future evidence")
    risk = export_loss_control(db, policy.loss_control, limits.population_id, events, boundary=now)
    ledger = OptionLedger.model_validate_json(
        db.execute("SELECT ledger_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    if ledger.position is not None:
        from app.options.entry_reference import stored_reference
        from app.options.lifecycle import OptionVenueSnapshot

        buy = next((i for i in buys if i.client_id == ledger.position.entry_client_id), None)
        snapshot = OptionVenueSnapshot.model_validate_json(
            db.execute("SELECT snapshot_json FROM execution_control WHERE id=1").fetchone()[0]
        )
        frozen = (
            "contract",
            "exit_at",
            "original_underlying_invalidation",
            "entry_time_protection",
            "entry_premium_protection",
            "target_exit_schedule",
            "entry_protection",
            "swing_carry",
        )
        for position in (ledger.position, snapshot.position):
            if (
                buy is None
                or position is None
                or any(
                    getattr(position, name)
                    != (buy.instrument.contract if name == "contract" else getattr(buy, name))
                    for name in frozen
                )
                or (
                    buy.entry_lineage.family == "SCOPE"
                    and position.entry_underlying_reference is None
                )
            ):
                raise ValueError("Scope held protection differs from original entry")
            if position.entry_underlying_reference is not None:
                stored_reference(db, position, limits)
    costs = economics.summary(db, now)
    reasons = []
    if ledger.position is not None:
        reasons.append("OPEN_POSITION")
    if any(r["active_lock"] is not None for r in orders):
        reasons.append("ORDER_UNRESOLVED")
    # A terminal never-filled call is not a completed trade or a loss.
    if any(o["entry_quantity"] and o["status"] != "COMPLETE" for o in outcomes):
        reasons.append("POSITION_OUTCOME_INCOMPLETE")
    if costs["unknown_calls"]:
        reasons.append("MODEL_COST_UNKNOWN")
    if data_cost is None:
        reasons.append("DATA_COST_UNKNOWN")
    if host_cost is None:
        reasons.append("HOST_COST_UNKNOWN")
    known = Decimal(costs["known_cost"])
    net = None if reasons else ledger.cash - policy.capital - known - data_cost - host_cost
    return {
        **({"shared_families": sorted(families)} if shared else {}),
        "population_id": limits.population_id,
        "account_id": limits.account_id,
        "status": "INCOMPLETE" if reasons else "COMPLETE_FLAT_ACCOUNTING",
        "scope": scope,
        "orders": attrs,
        "outcomes": outcomes,
        "loss_control": risk.model_dump(mode="json"),
        "ledger": ledger.model_dump(mode="json"),
        "model_costs": costs,
        **runtime,
        "execution_fees": str(ledger.fees_paid),
        "data_cost": str(data_cost) if data_cost is not None else None,
        "host_cost": str(host_cost) if host_cost is not None else None,
        "net_after_all_costs": str(net) if net is not None else None,
        "reasons": reasons,
        "execution_authority": False,
        "live_enabled": False,
    }


def export_scope_execution(journal, *, now, data_cost=None, host_cost=None):
    """Capture one owned snapshot; absent operating costs keep the net result unknown."""
    now, data_cost, host_cost = clock(now), _cost(data_cost), _cost(host_cost)
    with journal.read() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        evidence = {}
        for table, names in SCHEMA.items():
            if table not in tables:
                continue
            rows = db.execute(
                f"SELECT {','.join(names.split())} FROM {table} ORDER BY rowid LIMIT 20001"
            ).fetchall()
            if len(rows) > 20000:
                raise ValueError("Scope export row capacity exceeded")
            evidence[table] = [list(r) for r in rows]
        report = _report(db, now, data_cost, host_cost)
    value = {
        "version": "shared-scope-native-export-v1"
        if "shared_families" in report
        else "scope-native-export-v1",
        "as_of": now.isoformat(),
        "evidence": evidence,
        "report": report,
    }
    if len(json.dumps(value).encode()) > MAX_BYTES:
        raise ValueError("Scope export byte capacity exceeded")
    return value | {"export_hash": fingerprint(value)}


def verify_scope_execution_export(value, expected_export_hash):
    """Reconstruct frozen native accounting in memory, with no owner, venue or network.

    The expected hash must be retained independently. This verifies recorded evidence,
    not provider authenticity, historical signatures or strategy profitability.
    """
    raw = json.dumps(value, allow_nan=False)
    if len(raw.encode()) > MAX_BYTES or set(value) != {
        "version",
        "as_of",
        "evidence",
        "report",
        "export_hash",
    }:
        raise ValueError("Bounded Scope native export required")
    body = {k: v for k, v in value.items() if k != "export_hash"}
    if (
        value["version"] not in {"scope-native-export-v1", "shared-scope-native-export-v1"}
        or value["export_hash"] != expected_export_hash
        or fingerprint(body) != expected_export_hash
    ):
        raise ValueError("Scope native export differs from retained hash")
    if not set(value["evidence"]) <= set(SCHEMA):
        raise ValueError("Unknown Scope evidence table")
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        for table, rows in value["evidence"].items():
            names = SCHEMA[table].split()
            cols = [
                n
                + (" INTEGER" if n in {"id", "sequence", "active_lock", "halted"} else " TEXT")
                + (" PRIMARY KEY" if i == 0 and table != "execution_option_swing_seeds" else "")
                for i, n in enumerate(names)
            ]
            if table == "execution_option_swing_seeds":
                cols.append("PRIMARY KEY(session,symbol)")
            db.execute(f"CREATE TABLE {table} ({','.join(cols)})")
            if (
                not isinstance(rows, list)
                or len(rows) > 20000
                or any(
                    not isinstance(r, list)
                    or len(r) != len(names)
                    or any(type(v) not in {str, int, type(None)} for v in r)
                    for r in rows
                )
            ):
                raise ValueError("Bounded Scope evidence rows required")
            db.executemany(f"INSERT INTO {table} VALUES({','.join('?' for _ in names)})", rows)
        report = _report(
            db,
            clock(datetime.fromisoformat(value["as_of"])),
            _cost(value["report"]["data_cost"]),
            _cost(value["report"]["host_cost"]),
        )
        if (value["version"] == "shared-scope-native-export-v1") != ("shared_families" in report):
            raise ValueError("Shared Scope export enrollment mismatch")
        if fingerprint(report) != fingerprint(value["report"]):
            raise ValueError("Scope native accounting reconstruction differs")
    return {
        "status": "VERIFIED_NATIVE_ACCOUNTING",
        "export_hash": expected_export_hash,
        "accounting_status": report["status"],
        "net_after_all_costs": report["net_after_all_costs"],
        "execution_authority": False,
        "live_enabled": False,
    }
