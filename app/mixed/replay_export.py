"""Fixed portable native mixed evidence, reconstructed without an executable owner."""

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.mixed.accounting import reconstruct
from app.mixed.loss_export import export_losses
from app.mixed.native_outcome import costed, stock_outcome
from app.mixed.native_store import TRIGGERS, history, verify, verify_order
from app.mixed.selection import configuration
from app.mixed.stock_models import StockPosition
from app.options.attribution import order_attribution
from app.options.engine import clock, exact, fingerprint
from app.options.lifecycle import OptionExecutionPolicy, OptionLedger, OptionVenueSnapshot
from app.options.models import OptionLimits
from app.options.position_outcome import native_position_outcome
from app.options.scope_execution_export import MAX_BYTES
from app.options.scope_execution_export import SCHEMA as OPTION_SCHEMA

SCHEMA = OPTION_SCHEMA | {
    "execution_mixed_control": "id policy_json opened_at position_json protection_json",
    "execution_stock_orders": OPTION_SCHEMA["execution_orders"],
    "execution_stock_fills": OPTION_SCHEMA["execution_fills"],
    "execution_stock_decisions": OPTION_SCHEMA["execution_option_decisions"],
    "execution_mixed_stock_sources": "session symbol source_hash source_json",
    "execution_mixed_stock_terminals": "source_hash family evidence_json",
    "execution_option_runtime": "id config_json status heartbeat_at feed_sequence frame_hash frame_json reason generation session_json feed_recorded_at",
    "execution_mixed_runtime_inputs": "sequence packet_hash packet_json accepted_at status",
}
REQUIRED = {
    "execution_control",
    "execution_orders",
    "execution_fills",
    "execution_events",
    "execution_model_calls",
    "execution_option_decisions",
    "execution_option_receipts",
    "execution_option_opportunities",
    "execution_option_strategy",
    "execution_option_loss_control",
    "execution_option_loss_outcomes",
    "execution_mixed_control",
    "execution_stock_orders",
    "execution_stock_fills",
    "execution_stock_decisions",
    "execution_mixed_stock_sources",
    "execution_mixed_stock_terminals",
}


def native_snapshot_coverage(db, snapshot):
    """Every retained attempt and fill belongs to the complete native snapshot."""
    all_fills = set()
    for orders, fills, observations in (
        ("execution_orders", "execution_fills", snapshot.orders),
        ("execution_stock_orders", "execution_stock_fills", snapshot.stock_orders),
    ):
        rows = {r["client_id"]: r for r in db.execute("SELECT * FROM " + orders)}
        observed = {o.client_id: o for o in observations}
        if len(observed) != len(observations) or set(observed) != {
            key for key, row in rows.items() if row["attempted_at"] is not None
        }:
            raise ValueError("Complete native mixed attempt coverage required")
        expected = {}
        for key, observation in observed.items():
            row = rows[key]
            intent = json.loads(row["intent_json"])
            attempted = datetime.fromisoformat(row["attempted_at"])
            if (
                json.loads(row["observation_json"] or "null") != observation.model_dump(mode="json")
                or row["status"] != observation.status
                or row["order_id"] != observation.order_id
                or not datetime.fromisoformat(intent["prepared_at"])
                <= attempted
                < datetime.fromisoformat(intent["approval_expires_at"])
                or not attempted <= observation.updated_at <= snapshot.captured_at
            ):
                raise ValueError("Native mixed snapshot differs from its retained attempt")
            for fill in observation.fills:
                if fill.fill_id in all_fills:
                    raise ValueError("Duplicate native mixed fill identity")
                all_fills.add(fill.fill_id)
                expected[fill.fill_id] = (key, fill.model_dump(mode="json"))
        stored = {
            row["fill_id"]: (row["client_id"], json.loads(row["payload"]))
            for row in db.execute("SELECT * FROM " + fills)
        }
        if stored != expected or any(
            row["observation_json"] is not None and key not in observed for key, row in rows.items()
        ):
            raise ValueError("Complete native mixed fill coverage required")


def option_holding(db, expected, actual, snapshot, limits):
    # Cash/fills reconstruct the original holding. Retained native protection can
    # tighten or latch an exit without changing those immutable economic terms.
    mutable = {
        "tightened_underlying_invalidation",
        "trade_floor",
        "premium_trail",
        "target_exit_stage",
        "exit_reason",
        "exit_required_at",
        "supervision_issue",
    }
    for observed in (actual, snapshot):
        if (expected is None) != (observed is None) or (
            expected is not None
            and expected.model_dump(exclude=mutable) != observed.model_dump(exclude=mutable)
        ):
            raise ValueError("Mixed held option differs from original fills and terms")
        if observed is not None and observed.entry_underlying_reference is not None:
            from app.options.entry_reference import stored_reference

            stored_reference(db, observed, limits)


@exact
def report(db, now):
    control = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
    config = json.loads(control["config_json"])
    policy = OptionExecutionPolicy.model_validate(config["policy"])
    limits = OptionLimits.model_validate(config["limits"])
    if (
        config["schema"] != "option-paper-execution-v1"
        or policy.mixed_owner is None
        or Decimal(config["capital"]) != policy.capital
        or configuration(db) is None
    ):
        raise ValueError("Complete native mixed export enrollment required")
    strategy = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy").fetchone()[0]
    )
    if policy.mixed_owner.reasoning is not None:
        from app.mixed.replay_enrollment import validate_stored

        validate_stored(strategy)
    engine = SimpleNamespace(
        policy=policy,
        limits=limits,
        venue=SimpleNamespace(venue_id=config["venue_id"]),
        _control=lambda connection: connection.execute(
            "SELECT * FROM execution_control WHERE id=1"
        ).fetchone(),
    )
    mixed = verify(engine, db)
    snapshot = OptionVenueSnapshot.model_validate_json(control["snapshot_json"])
    if (
        snapshot.captured_at != now
        or not snapshot.complete
        or snapshot.account_id != limits.account_id
        or snapshot.population_id != limits.population_id
        or snapshot.venue_id != config["venue_id"]
    ):
        raise ValueError("Exact native closing snapshot required")
    native_snapshot_coverage(db, snapshot)
    option_rows = db.execute("SELECT * FROM execution_orders ORDER BY rowid").fetchall()
    stock_rows = db.execute("SELECT * FROM execution_stock_orders ORDER BY rowid").fetchall()
    attrs = [order_attribution(db, row) for row in option_rows]
    intents = [verify_order(db, row) for row in stock_rows]
    outcomes = [stock_outcome(engine, db, i.client_id) for i in intents if i.side == "BUY"]
    for row in option_rows:
        if json.loads(row["intent_json"])["side"] == "BUY":
            outcome = native_position_outcome(db, row["client_id"], limits.population_id)
            outcomes.append(
                costed(db, policy, outcome) if policy.mixed_owner.reasoning is None else outcome
            )
    captured = history(engine, db, as_of=now)
    projected = reconstruct(captured)
    ledger = OptionLedger.model_validate_json(control["ledger_json"])
    option_holding(db, projected.ledger.position, ledger.position, snapshot.position, limits)
    if (
        projected.ledger.model_dump(exclude={"version", "stock_position", "position"})
        != ledger.model_dump(exclude={"version", "position"})
        or projected.ledger.stock_position
        != (
            StockPosition.model_validate_json(mixed["position_json"])
            if mixed["position_json"]
            else None
        )
        or projected.ledger.stock_position != snapshot.stock_position
        or projected.ledger.cash != snapshot.cash
        or projected.ledger.settled_cash != snapshot.settled_cash
    ):
        raise ValueError("Native mixed history, snapshot and closing ledger disagree")
    events = db.execute("SELECT * FROM execution_events ORDER BY sequence").fetchall()
    if any(clock(datetime.fromisoformat(e["occurred_at"])) > now for e in events):
        raise ValueError("Mixed export includes future evidence")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    extra = {}
    if policy.scope_arbitration is not None:
        from app.options.scope_observer import stored_scope

        extra["scope"] = stored_scope(db, tables, limits, now, json.loads, owner_policy=policy)
    if "execution_mixed_runtime_inputs" in tables:
        from app.mixed.runtime import stored_inputs

        extra["runtime"] = stored_inputs(db, now)
    risk = export_losses(db, policy.loss_control, outcomes, events, boundary=now)
    reasons = []
    if ledger.position is not None or projected.ledger.stock_position is not None:
        reasons.append("OPEN_POSITION")
    if captured.reservations:
        reasons.append("ORDER_UNRESOLVED")
    if projected.unknown_cost_ids:
        reasons.append("COST_UNKNOWN")
    if any(Decimal(str(o["entry_quantity"])) and o["status"] != "COMPLETE" for o in outcomes):
        reasons.append("POSITION_OUTCOME_INCOMPLETE")
    value = {
        "population_id": limits.population_id,
        "account_id": limits.account_id,
        "status": "INCOMPLETE_ACCOUNTING" if reasons else "COMPLETE_FLAT_ACCOUNTING",
        "ledger": projected.ledger.model_copy(update={"position": ledger.position}).model_dump(
            mode="json"
        ),
        "history_hash": fingerprint(captured),
        "reservations": [r.model_dump(mode="json") for r in captured.reservations],
        "costs": [c.model_dump(mode="json") for c in captured.costs],
        "known_cost": str(projected.known_cost),
        "unknown_cost_ids": list(projected.unknown_cost_ids),
        "execution_fees": str(projected.ledger.fees_paid),
        "outcomes": outcomes,
        "option_orders": attrs,
        "stock_orders": [i.model_dump(mode="json") for i in intents],
        "loss_control": risk,
        "net_after_all_costs": None
        if reasons
        else str(projected.ledger.cash - policy.capital - projected.known_cost),
        "reasons": reasons,
        **extra,
        "execution_authority": False,
        "live_enabled": False,
    }
    # Native attribution contains tuples. Freeze JSON values at the export
    # boundary so disk/network round trips preserve the exact portable report.
    return json.loads(json.dumps(value, allow_nan=False))


def export_mixed_execution(journal, *, now):
    now = clock(now)
    with journal.read() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED <= tables:
            raise ValueError("Complete mixed native tables required")
        evidence = {}
        for table, names in SCHEMA.items():
            if table in tables:
                rows = db.execute(
                    f"SELECT {','.join(names.split())} FROM {table} ORDER BY rowid LIMIT 20001"
                ).fetchall()
                if len(rows) > 20000:
                    raise ValueError("Mixed export row capacity exceeded")
                evidence[table] = [list(r) for r in rows]
        value = {
            "version": "mixed-native-export-v1",
            "as_of": now.isoformat(),
            "evidence": evidence,
            "report": report(db, now),
        }
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("Mixed export byte capacity exceeded")
    return value | {"export_hash": fingerprint(value)}


def verify_mixed_execution_export(value, expected_export_hash):
    if (
        len(json.dumps(value, allow_nan=False).encode()) > MAX_BYTES
        or set(value) != {"version", "as_of", "evidence", "report", "export_hash"}
        or value["version"] != "mixed-native-export-v1"
        or value["export_hash"] != expected_export_hash
        or fingerprint({k: v for k, v in value.items() if k != "export_hash"})
        != expected_export_hash
        or not REQUIRED <= set(value["evidence"]) <= set(SCHEMA)
    ):
        raise ValueError("Complete independently bound mixed export required")
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for table, rows in value["evidence"].items():
            names = SCHEMA[table].split()
            if (
                not isinstance(rows, list)
                or len(rows) > 20000
                or any(
                    not isinstance(r, list)
                    or len(r) != len(names)
                    or any(
                        v is not None and (isinstance(v, bool) or not isinstance(v, (str, int)))
                        for v in r
                    )
                    for r in rows
                )
            ):
                raise ValueError("Fixed mixed export row schema required")
            composite = {
                "execution_option_swing_seeds": "session,symbol",
                "execution_option_swing_batches": "session,symbol",
                "execution_mixed_stock_sources": "session,symbol",
                "execution_mixed_stock_terminals": "source_hash,family",
            }
            cols = [
                name
                + (
                    " INTEGER"
                    if name
                    in {"id", "sequence", "active_lock", "halted", "feed_sequence", "generation"}
                    else " TEXT"
                )
                + (" PRIMARY KEY" if index == 0 and table not in composite else "")
                + (" CHECK(id=1)" if name == "id" else "")
                for index, name in enumerate(names)
            ]
            if table in composite:
                cols.append("PRIMARY KEY(" + composite[table] + ")")
            db.execute(f"CREATE TABLE {table} ({','.join(cols)})")
            db.executemany(f"INSERT INTO {table} VALUES({','.join('?' for _ in names)})", rows)
        # Trusted fixed definitions only; no exported SQL or restore authority.
        for sql in TRIGGERS.values():
            db.execute(sql)
        actual = report(db, clock(datetime.fromisoformat(value["as_of"])))
        if actual != value["report"]:
            raise ValueError("Mixed portable report differs from reconstructed native evidence")
        return actual
    finally:
        db.close()
