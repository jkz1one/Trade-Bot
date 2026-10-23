"""Mixed journal evidence on one existing native owner and restore fence."""

import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.execution.engine import ExecutionBlocked
from app.mixed.models import (
    CashHistory,
    CostRecord,
    MixedPolicy,
    OptionTrade,
    Reservation,
    Settlement,
    StockTrade,
)
from app.mixed.native_models import StockProtection
from app.mixed.stock_models import StockIntent, StockObservation, StockPosition
from app.options.engine import clock, fingerprint
from app.options.lifecycle import (
    TERMINAL,
    OptionIntent,
    OptionLedger,
    OptionObservation,
    OptionVenueSnapshot,
)

ZERO = Decimal(0)
TABLES = frozenset(
    {
        "execution_mixed_control",
        "execution_stock_orders",
        "execution_stock_fills",
        "execution_stock_decisions",
    }
)
TRIGGERS = {}
for own, other in (("stock", "orders"), ("option", "stock_orders")):
    table = "execution_stock_orders" if own == "stock" else "execution_orders"
    other_table = "execution_" + other
    for action in ("INSERT", "UPDATE"):
        name = "mixed_" + own + "_" + action.lower()
        TRIGGERS[name] = (
            f"CREATE TRIGGER {name} BEFORE {action} ON {table} "
            f"WHEN NEW.active_lock=1 AND EXISTS(SELECT 1 FROM {other_table} WHERE active_lock=1) "
            "BEGIN SELECT RAISE(ABORT,'MIXED_ORDER_ALREADY_IN_FLIGHT'); END"
        )


def enroll(engine, db, now, *, create):
    if engine.policy.mixed_owner is None:
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_mixed_control'"
        ).fetchone():
            raise ExecutionBlocked("MIXED_OWNER_NOT_ENROLLED")
        return
    if create:
        db.execute(
            "CREATE TABLE execution_mixed_control(id INTEGER PRIMARY KEY CHECK(id=1),policy_json TEXT NOT NULL,opened_at TEXT NOT NULL,position_json TEXT,protection_json TEXT)"
        )
        db.execute(
            "CREATE TABLE execution_stock_orders(client_id TEXT PRIMARY KEY,source_key TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,intent_json TEXT NOT NULL,approval_json TEXT NOT NULL,status TEXT NOT NULL,active_lock INTEGER UNIQUE,order_id TEXT UNIQUE,attempted_at TEXT,observation_json TEXT)"
        )
        db.execute(
            "CREATE TABLE execution_stock_fills(fill_id TEXT PRIMARY KEY,client_id TEXT NOT NULL REFERENCES execution_stock_orders(client_id),payload TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE execution_stock_decisions(source_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,inputs_json TEXT NOT NULL,result_json TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO execution_mixed_control VALUES(1,?,?,NULL,NULL)",
            (engine.policy.mixed_owner.model_dump_json(), now.isoformat()),
        )
        for sql in TRIGGERS.values():
            db.execute(sql)
        engine.journal.event(
            db, now, "MIXED_OWNER_ENROLLED", engine.policy.mixed_owner.model_dump(mode="json")
        )
    verify(engine, db)
    for row in db.execute(
        "SELECT client_id FROM execution_stock_orders WHERE status='SUBMITTING'"
    ).fetchall():
        db.execute(
            "UPDATE execution_stock_orders SET status='UNKNOWN' WHERE client_id=?", (row[0],)
        )
        engine._halt(db, "INTERRUPTED_STOCK_ATTEMPT", now)
        engine.journal.event(db, now, "INTERRUPTED_ATTEMPT", {}, row[0])


def verify(engine, db):
    row = db.execute("SELECT * FROM execution_mixed_control WHERE id=1").fetchone()
    if row is None or row["policy_json"] != engine.policy.mixed_owner.model_dump_json():
        raise ExecutionBlocked("FROZEN_MIXED_OWNER_CHANGED")
    saved = {
        r["name"]: r["sql"]
        for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")
    }
    if any(saved.get(k) != v for k, v in TRIGGERS.items()):
        raise ExecutionBlocked("MIXED_ORDER_LOCK_CHANGED")
    return row


def position(engine, db):
    row = verify(engine, db)
    return StockPosition.model_validate_json(row["position_json"]) if row["position_json"] else None


def protection(engine, db):
    row = verify(engine, db)
    return (
        StockProtection.model_validate_json(row["protection_json"])
        if row["protection_json"]
        else None
    )


def unresolved(db, *, submitting=False):
    return (
        db.execute(
            "SELECT 1 FROM execution_stock_orders WHERE "
            + ("status='SUBMITTING'" if submitting else "active_lock=1")
        ).fetchone()
        is not None
    )


def allocations(engine, db, at):
    opened = clock(datetime.fromisoformat(verify(engine, db)["opened_at"]))
    zone = ZoneInfo("America/New_York")
    start, end = opened.astimezone(zone).date(), at.astimezone(zone).date()
    if not 0 <= (end - start).days <= 366:
        raise ValueError("MIXED_ALLOCATION_HORIZON")
    p = engine.policy.mixed_owner
    values = (
        ("DATA", p.daily_data_cost),
        ("HOST", p.daily_host_cost),
        ("OPERATING", p.daily_operating_cost),
    )
    return tuple(
        CostRecord(
            cost_id=f"mixed:{day}:{kind}",
            kind=kind,
            occurred_at=max(opened, datetime.combine(day, time.min, zone)),
            amount=amount,
            evidence_hash=fingerprint(p),
        )
        for day in (start + timedelta(days=i) for i in range((end - start).days + 1))
        for kind, amount in values
    )


def history(engine, db, *, as_of=None, exclude=None):
    c = engine._control(db)
    if not c["snapshot_json"] or json.loads(c["issues_json"]):
        raise ExecutionBlocked("MIXED_RECONCILIATION_REQUIRED")
    snap = OptionVenueSnapshot.model_validate_json(c["snapshot_json"])
    captured = as_of or snap.captured_at
    events = []
    reservations = []
    for table, model, observation, event_type in (
        ("execution_orders", OptionIntent, OptionObservation, OptionTrade),
        ("execution_stock_orders", StockIntent, StockObservation, StockTrade),
    ):
        for row in db.execute("SELECT * FROM " + table):
            intent = model.model_validate_json(row["intent_json"])
            obs = (
                observation.model_validate_json(row["observation_json"])
                if row["observation_json"]
                else None
            )
            events.extend(
                event_type(
                    intent=intent,
                    attempted_at=clock(datetime.fromisoformat(row["attempted_at"])),
                    fill=f,
                )
                for f in (obs.fills if obs else ())
            )
            if row["active_lock"] == 1 and intent.client_id != exclude:
                reservations.append(Reservation(intent=intent, status=row["status"]))
    events.extend(Settlement(receipt=r) for r in snap.receipts)
    p = MixedPolicy(
        capital=engine.policy.capital,
        daily_loss_limit=engine.policy.daily_loss_limit,
        total_loss_limit=engine.policy.total_loss_limit,
        options=engine.limits,
        stocks=engine.policy.mixed_owner.stocks,
    )
    return CashHistory(
        account_id=engine.limits.account_id,
        population_id=engine.limits.population_id,
        venue_id=engine.venue.venue_id,
        policy=p,
        opened_at=datetime.fromisoformat(verify(engine, db)["opened_at"]),
        captured_at=captured,
        events=tuple(events),
        reservations=tuple(reservations),
        costs=allocations(engine, db, captured),
    )


def project_account(engine, db, account, now, *, exclude=None, closing=False):
    from app.mixed.governor import option_account

    h = history(engine, db, as_of=now, exclude=exclude)
    projected = option_account(h, reconciled=True, entry_halted=account.entry_halted)
    original = OptionLedger.model_validate_json(engine._control(db)["ledger_json"])
    if (projected.cash, projected.settled_cash) != (original.cash, original.settled_cash):
        raise ExecutionBlocked("MIXED_COMMON_CASH_MISMATCH")
    unbound = db.execute("SELECT 1 FROM execution_model_calls LIMIT 1").fetchone() is not None
    if unbound:
        projected = projected.model_copy(
            update={
                "budgets_known": False,
                "daily_loss_available": ZERO,
                "total_loss_available": ZERO,
                "entry_blockers": (*projected.entry_blockers, "MIXED_PAID_CONTRACT_NOT_ENROLLED"),
            }
        )
    return account.model_copy(
        update={
            "reserved_cash": ZERO if closing and not h.reservations else projected.reserved_cash,
            "daily_loss_available": projected.daily_loss_available,
            "total_loss_available": projected.total_loss_available,
            "budgets_known": projected.budgets_known,
            "position": projected.position,
            "working_orders": projected.working_orders,
            "entry_blockers": tuple(
                dict.fromkeys(
                    (
                        *account.entry_blockers,
                        *(
                            r
                            for r in projected.entry_blockers
                            if r not in {"MIXED_POSITION_OWNED", "MIXED_ORDER_UNRESOLVED"}
                        ),
                    )
                )
            ),
        }
    )


def verify_order(db, row):
    intent = StockIntent.model_validate_json(row["intent_json"])
    approval = json.loads(row["approval_json"])
    if approval.get("intent_terms") != intent.model_dump(mode="json", exclude={"approval_hash"}):
        raise ValueError("STOCK_NATIVE_TERMS_CHANGED")
    if (
        row["client_id"] != intent.client_id
        or row["source_key"] != intent.source_key
        or fingerprint(approval) != intent.approval_hash
    ):
        raise ValueError("STOCK_NATIVE_APPROVAL_CHANGED")
    decision = db.execute(
        "SELECT * FROM execution_stock_decisions WHERE source_key=?", (intent.source_key,)
    ).fetchone()
    if (
        decision is None
        or decision["fingerprint"] != row["fingerprint"]
        or json.loads(decision["result_json"]).get("client_id") != intent.client_id
    ):
        raise ValueError("STOCK_NATIVE_DECISION_CHANGED")
    if (
        json.loads(decision["inputs_json"]) != approval["inputs"]
        or fingerprint(approval["inputs"]) != row["fingerprint"]
    ):
        raise ValueError("STOCK_NATIVE_INPUT_CHANGED")
    if approval["revision"] != intent.account_revision or approval["admission"][
        "approved_at"
    ] != intent.prepared_at.isoformat().replace("+00:00", "Z"):
        # Pydantic emits Z; stored journal attempts use explicit UTC offsets.
        raise ValueError("STOCK_NATIVE_REVISION_OR_CLOCK_CHANGED")
    from app.mixed.governor import admit_stock
    from app.mixed.models import StockProposal, StockQuote
    from app.options.lifecycle import OptionExecutionPolicy
    from app.options.models import OptionAccount, SessionWindow

    proposal = StockProposal.model_validate(approval["inputs"]["proposal"])
    quote = StockQuote.model_validate(approval["inputs"]["quote"])
    account = OptionAccount.model_validate(approval["account"])
    h = CashHistory.model_validate(approval["history"])
    window = SessionWindow.model_validate(approval["session"])
    config = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    policy = OptionExecutionPolicy.model_validate(config["policy"])
    if (
        policy.mixed_owner is None
        or h.policy
        != MixedPolicy(
            capital=policy.capital,
            daily_loss_limit=policy.daily_loss_limit,
            total_loss_limit=policy.total_loss_limit,
            options=config["limits"],
            stocks=policy.mixed_owner.stocks,
        )
        or (h.account_id, h.population_id) != (account.account_id, account.population_id)
        or h.captured_at != intent.prepared_at
        or approval["inputs"]["origin"] not in {"DETERMINISTIC", "PROTECTIVE"}
    ):
        raise ValueError("STOCK_NATIVE_CONTRACT_CHANGED")
    reviewed = admit_stock(
        proposal,
        quote,
        h,
        window,
        now=intent.prepared_at,
        reconciled=account.reconciled,
        entry_halted=account.entry_halted,
    )
    reviewed = (
        reviewed.model_copy(
            update={
                "approval_expires_at": min(
                    reviewed.approval_expires_at,
                    account.captured_at
                    + timedelta(seconds=h.policy.options.account_max_age_seconds),
                )
            }
        )
        if reviewed.outcome == "APPROVED"
        else reviewed
    )
    if (
        reviewed.outcome != "APPROVED"
        or reviewed.model_dump(mode="json") != approval["admission"]
        or json.loads(decision["result_json"]).get("admission") != approval["admission"]
        or intent.approval_expires_at != reviewed.approval_expires_at
        or intent.limit_price != reviewed.limit_price
    ):
        raise ValueError("STOCK_NATIVE_ADMISSION_CHANGED")
    requested = approval["inputs"]["close_quantity"]
    quantity = (
        reviewed.quantity if requested is None else min(reviewed.quantity, Decimal(requested))
    )
    if intent.quantity != quantity:
        raise ValueError("STOCK_NATIVE_QUANTITY_CHANGED")
    if intent.side == "BUY":
        expected = {
            "instrument": proposal.instrument,
            "family": proposal.family,
            "source_hash": proposal.source_hash,
            "source_at": proposal.source_at,
            "source_valid_until": proposal.valid_until,
            "exit_at": proposal.exit_at,
            "original_invalidation": proposal.original_invalidation,
            "original_target": proposal.original_target,
            "thesis": proposal.thesis,
            "approved_entry_debit": reviewed.entry_debit,
            "reserved_exit_fee": reviewed.reserved_exit_fee,
            "order_expires_at": min(window.closes_at, proposal.exit_at),
        }
        if proposal.action != "OPEN_LONG" or requested is not None:
            raise ValueError("STOCK_NATIVE_ENTRY_CHANGED")
    else:
        original = db.execute(
            "SELECT * FROM execution_stock_orders WHERE client_id=?",
            (intent.closing_entry_client_id,),
        ).fetchone()
        if original is None or json.loads(original["intent_json"])["side"] != "BUY":
            raise ValueError("STOCK_NATIVE_CLOSE_UNOWNED")
        entry = verify_order(db, original)
        expected = {
            k: getattr(entry, k)
            for k in (
                "instrument",
                "family",
                "source_hash",
                "source_at",
                "source_valid_until",
                "exit_at",
                "original_invalidation",
                "original_target",
                "thesis",
            )
        }
        expected.update(
            approved_entry_debit=ZERO, reserved_exit_fee=ZERO, order_expires_at=window.closes_at
        )
        if proposal.action != "CLOSE" or proposal.instrument != entry.instrument:
            raise ValueError("STOCK_NATIVE_CLOSE_CHANGED")
    if any(getattr(intent, k) != v for k, v in expected.items()):
        raise ValueError("STOCK_NATIVE_ORIGINAL_TERMS_CHANGED")
    return intent


def stock_evidence(engine, db, snap, now, option_rows):
    rows = {r["client_id"]: r for r in db.execute("SELECT * FROM execution_stock_orders")}
    known = {r["fill_id"]: r for r in db.execute("SELECT * FROM execution_stock_fills")}
    observations = {o.client_id: o for o in snap.stock_orders}
    if len(observations) != len(snap.stock_orders) or set(rows) & set(option_rows):
        raise ValueError("MIXED_ORDER_ID_CONFLICT")
    if len({o.order_id for o in (*snap.orders, *snap.stock_orders)}) != len(snap.orders) + len(
        snap.stock_orders
    ):
        raise ValueError("MIXED_VENUE_ORDER_ID_CONFLICT")
    events = []
    new = []
    seen = set()
    usage = {}
    from app.mixed.accounting import _stock_fill_rules, _validate_stock_intent

    for client, obs in observations.items():
        row = rows.get(client)
        if row is None or not row["attempted_at"]:
            raise ValueError("UNOWNED_OR_UNATTEMPTED_STOCK_ORDER")
        intent = verify_order(db, row)
        attempt = clock(datetime.fromisoformat(row["attempted_at"]))
        _validate_stock_intent(engine.policy.mixed_owner.stocks, intent)
        if (
            obs.intent != intent
            or not intent.prepared_at <= attempt < intent.approval_expires_at
            or not attempt <= obs.updated_at <= snap.captured_at
        ):
            raise ValueError("STOCK_ORIGINAL_ATTEMPT_CHANGED")
        if row["order_id"] not in (None, obs.order_id):
            raise ValueError("STOCK_VENUE_ORDER_CHANGED")
        old = (
            StockObservation.model_validate_json(row["observation_json"])
            if row["observation_json"]
            else None
        )
        if old and (
            old.updated_at > obs.updated_at
            or old.fills != obs.fills[: len(old.fills)]
            or (old.status in TERMINAL and (old.status != obs.status or old.fills != obs.fills))
        ):
            raise ValueError("STOCK_ORDER_HISTORY_REGRESSION")
        paid = ZERO
        for index, fill in enumerate(obs.fills):
            if fill.fill_id in seen or fill.fill_id in {
                f.fill_id for o in snap.orders for f in o.fills
            }:
                raise ValueError("MIXED_DUPLICATE_FILL_ID")
            seen.add(fill.fill_id)
            if (
                not attempt <= fill.occurred_at <= obs.updated_at
                or fill.occurred_at >= intent.order_expires_at
            ):
                raise ValueError("STOCK_FILL_TIME_MISMATCH")
            _stock_fill_rules(engine.policy.mixed_owner.stocks, intent, fill, index, usage)
            paid += fill.quantity * fill.price + fill.fee
            if fill.fill_id in known:
                if (
                    known[fill.fill_id]["client_id"] != client
                    or known[fill.fill_id]["payload"] != fill.model_dump_json()
                ):
                    raise ValueError("STOCK_FILL_HISTORY_CHANGED")
            else:
                new.append((client, fill))
            events.append((fill.sequence, fill.occurred_at, "STOCK_FILL", (intent, fill)))
        if intent.side == "BUY" and paid > intent.approved_entry_debit:
            raise ValueError("STOCK_APPROVED_DEBIT_EXCEEDED")
    if set(known) - seen or any(
        r["attempted_at"] and k not in observations for k, r in rows.items()
    ):
        raise ValueError("STOCK_ATTEMPT_OR_FILL_HISTORY_MISSING")
    return events, observations, new


def persist(engine, db, stock, observations, new):
    for client, obs in observations.items():
        db.execute(
            "UPDATE execution_stock_orders SET status=?,order_id=?,observation_json=?,active_lock=? WHERE client_id=?",
            (
                obs.status,
                obs.order_id,
                obs.model_dump_json(),
                None if obs.status in TERMINAL else 1,
                client,
            ),
        )
    for client, fill in new:
        db.execute(
            "INSERT INTO execution_stock_fills VALUES(?,?,?)",
            (fill.fill_id, client, fill.model_dump_json()),
        )
    prior = protection(engine, db)
    if stock is None:
        prior = None
    elif prior is None or prior.entry_client_id != stock.entry.client_id:
        prior = StockProtection(
            entry_client_id=stock.entry.client_id, invalidation=stock.entry.original_invalidation
        )
    elif prior.invalidation < stock.entry.original_invalidation:
        raise ValueError("STOCK_PROTECTION_WIDENED")
    db.execute(
        "UPDATE execution_mixed_control SET position_json=?,protection_json=? WHERE id=1",
        (stock.model_dump_json() if stock else None, prior.model_dump_json() if prior else None),
    )
