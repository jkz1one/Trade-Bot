"""Transaction-bound two-play evidence in the existing owner's restore-fenced journal."""

import json
from datetime import datetime

from app.execution.engine import ExecutionBlocked
from app.mixed.accounting import reconstruct
from app.mixed.models import OptionTrade, Reservation, Settlement, StockTrade, TerminalOrder
from app.mixed.portfolio_accounting import PortfolioHistory, PortfolioPolicy, play_id
from app.mixed.stock_models import StockIntent
from app.options.engine import clock, fingerprint
from app.options.lifecycle import TERMINAL, OptionIntent

TABLES = frozenset(
    {"execution_portfolio_control", "execution_portfolio_orders", "execution_portfolio_decisions"}
)


def enroll(engine, db, policy, now, *, create):
    policy = PortfolioPolicy.model_validate(policy.model_dump())
    if (
        policy.options != engine.limits
        or policy.capital != engine.policy.capital
        or policy.stocks != engine.policy.mixed_owner.stocks
    ):
        raise ValueError("Portfolio enrollment must bind the native account")
    if create:
        db.execute(
            "CREATE TABLE execution_portfolio_control(id INTEGER PRIMARY KEY CHECK(id=1),policy_json TEXT NOT NULL,opened_at TEXT NOT NULL,snapshot_json TEXT,protection_json TEXT NOT NULL,limit_value INTEGER NOT NULL CHECK(limit_value IN(0,1,2)))"
        )
        db.execute(
            "CREATE TABLE execution_portfolio_orders(client_id TEXT PRIMARY KEY,play_id TEXT NOT NULL,asset TEXT NOT NULL CHECK(asset IN('STOCK','OPTION')),source_key TEXT UNIQUE NOT NULL,intent_json TEXT NOT NULL,approval_json TEXT NOT NULL,status TEXT NOT NULL,active_play TEXT UNIQUE,attempted_at TEXT,order_id TEXT UNIQUE,observation_json TEXT)"
        )
        db.execute(
            "CREATE TABLE execution_portfolio_decisions(source_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result_json TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO execution_portfolio_control VALUES(1,?,?,NULL,'{}',?)",
            (policy.model_dump_json(), now.isoformat(), policy.max_plays),
        )
        engine.journal.event(db, now, "PORTFOLIO_ENROLLED", policy.model_dump(mode="json"))
    row = control(engine, db, policy)
    for order in db.execute(
        "SELECT client_id FROM execution_portfolio_orders WHERE status='SUBMITTING'"
    ).fetchall():
        db.execute(
            "UPDATE execution_portfolio_orders SET status='UNKNOWN' WHERE client_id=?", (order[0],)
        )
        engine._halt(db, "INTERRUPTED_PORTFOLIO_ATTEMPT", now)
        engine.journal.event(db, now, "INTERRUPTED_ATTEMPT", {}, order[0])
    return row


def control(engine, db, policy):
    row = db.execute("SELECT * FROM execution_portfolio_control WHERE id=1").fetchone()
    if row is None or row["policy_json"] != policy.model_dump_json():
        raise ExecutionBlocked("FROZEN_PORTFOLIO_POLICY_CHANGED")
    for identity, saved in json.loads(row["protection_json"]).items():
        event = db.execute(
            "SELECT payload FROM execution_events WHERE client_id=? AND kind IN ('POSITION_SUPERVISED','PORTFOLIO_INVALIDATION_TIGHTENED') ORDER BY sequence DESC LIMIT 1",
            (identity,),
        ).fetchone()
        if event is None or json.loads(event[0]).get("protection") != saved:
            raise ExecutionBlocked("PORTFOLIO_PROTECTION_EVIDENCE_CHANGED")
    return row


def intent(row):
    cls = StockIntent if row["asset"] == "STOCK" else OptionIntent
    value = cls.model_validate_json(row["intent_json"])
    if (
        value.client_id != row["client_id"]
        or play_id(value) != row["play_id"]
        or value.source_key != row["source_key"]
    ):
        raise ValueError("Portfolio order identity changed")
    approval = json.loads(row["approval_json"])
    if approval["intent_hash"] != fingerprint(value):
        raise ValueError("Portfolio approved intent changed")
    return value


def history(engine, db, policy, now, *, exclude=None, snapshot=None):
    from app.mixed.native_store import allocations, model_costs
    from app.mixed.portfolio_venue import PortfolioVenueSnapshot

    c = control(engine, db, policy)
    snapshot = snapshot or (
        PortfolioVenueSnapshot.model_validate_json(c["snapshot_json"])
        if c["snapshot_json"]
        else None
    )
    if snapshot is None:
        raise ExecutionBlocked("PORTFOLIO_SNAPSHOT_REQUIRED")
    events, reservations, terminals = [], [], []
    observations = {o.client_id: o for o in (*snapshot.orders, *snapshot.stock_orders)}
    for row in db.execute("SELECT * FROM execution_portfolio_orders ORDER BY rowid"):
        i = verify_order(engine, db, policy, row)
        o = observations.pop(i.client_id, None)
        if o:
            if row["attempted_at"] is None or (
                row["order_id"] is not None and row["order_id"] != o.order_id
            ):
                raise ValueError("Portfolio observation has no matching native attempt")
            if any(
                getattr(i, k) != getattr(o, k)
                for k in ("client_id", "instrument", "side", "quantity", "limit_price")
            ):
                raise ValueError("Portfolio observation changed original order")
            cls = StockTrade if isinstance(i, StockIntent) else OptionTrade
            events.extend(
                cls(intent=i, attempted_at=datetime.fromisoformat(row["attempted_at"]), fill=f)
                for f in o.fills
            )
        status = o.status if o else row["status"]
        if status in TERMINAL:
            terminals.append(
                TerminalOrder(
                    intent=i,
                    status=status,
                    observed_at=o.updated_at if o else now,
                    order_id=o.order_id if o else row["order_id"],
                    attempted_at=datetime.fromisoformat(row["attempted_at"])
                    if row["attempted_at"]
                    else None,
                )
            )
        elif i.client_id != exclude:
            reservations.append(Reservation(intent=i, status=status))
    if observations:
        raise ValueError("Portfolio snapshot contains an unowned order")
    events.extend(
        Settlement(receipt=r, play_id=snapshot.settlement_plays.get(r.receipt_id))
        for r in snapshot.receipts
    )
    current_policy = policy.model_copy(update={"max_plays": c["limit_value"]})
    costs = (*allocations(engine, db, now), *model_costs(engine, db))
    if exclude is not None and not any(
        hasattr(e, "intent") and e.intent.client_id == exclude for e in events
    ):
        # A dispatch review removes its own unfunded reservation. Keep the full
        # charge as an account cost until that entry has a retained fill; the
        # durable paid receipt still names the original selected order.
        costs = tuple(
            c.model_copy(update={"entry_client_id": None}) if c.entry_client_id == exclude else c
            for c in costs
        )
    return PortfolioHistory(
        account_id=engine.limits.account_id,
        population_id=engine.limits.population_id,
        venue_id=engine.venue.venue_id,
        policy=current_policy,
        opened_at=clock(datetime.fromisoformat(c["opened_at"])),
        captured_at=now,
        events=tuple(events),
        reservations=tuple(reservations),
        terminals=tuple(terminals),
        costs=costs,
    )


def reserve(engine, db, policy, value, approval, now):
    """Caller holds the owner write transaction from fresh admission through insert."""
    identity = play_id(value)
    if db.execute(
        "SELECT 1 FROM execution_portfolio_orders WHERE active_play=?", (identity,)
    ).fetchone():
        raise ExecutionBlocked("PLAY_ORDER_UNRESOLVED")
    if (
        value.side == "SELL"
        and identity not in reconstruct(history(engine, db, policy, now)).ledger.positions
    ):
        raise ExecutionBlocked("PLAY_NOT_HELD")
    payload = {**approval, "intent_hash": fingerprint(value)}
    db.execute(
        "INSERT INTO execution_portfolio_orders VALUES(?,?,?,?,?,?,'PREPARED',?,NULL,NULL,NULL)",
        (
            value.client_id,
            identity,
            "STOCK" if isinstance(value, StockIntent) else "OPTION",
            value.source_key,
            value.model_dump_json(),
            json.dumps(payload, sort_keys=True),
            identity,
        ),
    )
    engine.journal.event(
        db, now, "PORTFOLIO_RESERVED", {"play_id": identity, "approval": payload}, value.client_id
    )
    projected = reconstruct(history(engine, db, policy, now))
    if projected.reserved_cash > projected.ledger.settled_cash or len(projected.commitments) > 2:
        raise ExecutionBlocked("PORTFOLIO_RESERVATION_UNFUNDED")
    return value


def verify_order(engine, db, policy, row):
    """Replay the frozen native approval and verify its immutable event/attempt bindings."""
    from app.mixed.governor import admit_stock
    from app.mixed.models import StockProposal
    from app.mixed.portfolio_admission import admit_portfolio_option
    from app.mixed.stock_models import StockQuote
    from app.options.models import OptionProposal, OptionQuote, SessionWindow, UnderlyingQuote

    i = intent(row)
    approval = json.loads(row["approval_json"])
    events = db.execute(
        "SELECT * FROM execution_events WHERE client_id=? AND kind='PORTFOLIO_RESERVED'",
        (i.client_id,),
    ).fetchall()
    if (
        len(events) != 1
        or json.loads(events[0]["payload"]) != {"play_id": row["play_id"], "approval": approval}
        or datetime.fromisoformat(events[0]["occurred_at"]) != i.prepared_at
    ):
        raise ValueError("PORTFOLIO_ORIGINAL_APPROVAL_EVIDENCE_CHANGED")
    h = PortfolioHistory.model_validate(approval["history"])
    if (
        h.policy.model_dump(exclude={"max_plays"}) != policy.model_dump(exclude={"max_plays"})
        or (h.account_id, h.population_id, h.venue_id)
        != (engine.limits.account_id, engine.limits.population_id, engine.venue.venue_id)
        or h.captured_at != i.prepared_at
    ):
        raise ValueError("PORTFOLIO_ORIGINAL_ACCOUNT_CHANGED")
    inputs = approval["inputs"]
    window = SessionWindow.model_validate(approval["session"])
    if isinstance(i, StockIntent):
        if (
            fingerprint({k: v for k, v in approval.items() if k != "intent_hash"})
            != i.approval_hash
        ):
            raise ValueError("PORTFOLIO_STOCK_APPROVAL_CHANGED")
        if approval["intent_terms"] != i.model_dump(mode="json", exclude={"approval_hash"}):
            raise ValueError("PORTFOLIO_STOCK_TERMS_CHANGED")
        reviewed = admit_stock(
            StockProposal.model_validate(inputs["proposal"]),
            StockQuote.model_validate(inputs["quote"]),
            h,
            window,
            now=i.prepared_at,
            reconciled=True,
            play_id=inputs["play_id"],
        )
    else:
        reviewed = admit_portfolio_option(
            OptionProposal.model_validate(inputs["proposal"]),
            OptionQuote.model_validate(inputs["quote"]),
            UnderlyingQuote.model_validate(inputs["underlying"]) if inputs["underlying"] else None,
            h,
            window,
            now=i.prepared_at,
            reconciled=True,
            play_id=inputs["play_id"],
        )
    if reviewed.model_dump(mode="json") != approval["admission"] or reviewed.outcome != "APPROVED":
        raise ValueError("PORTFOLIO_ORIGINAL_ADMISSION_CHANGED")
    if i.quantity > reviewed.quantity or i.limit_price != reviewed.limit_price:
        raise ValueError("PORTFOLIO_APPROVED_QUANTITY_OR_PRICE_CHANGED")
    if (row["status"] in TERMINAL) != (row["active_play"] is None):
        raise ValueError("PORTFOLIO_RESERVATION_STATUS_CHANGED")
    attempts = db.execute(
        "SELECT * FROM execution_events WHERE client_id=? AND kind='PORTFOLIO_ATTEMPT_STARTED'",
        (i.client_id,),
    ).fetchall()
    if row["attempted_at"] is None:
        if attempts or row["status"] not in {"PREPARED", "REJECTED"}:
            raise ValueError("PORTFOLIO_UNATTEMPTED_ORDER_CHANGED")
    elif (
        len(attempts) != 1
        or attempts[0]["occurred_at"] != row["attempted_at"]
        or not (
            i.prepared_at <= datetime.fromisoformat(row["attempted_at"]) < i.approval_expires_at
        )
        or json.loads(attempts[0]["payload"])["play_id"] != row["play_id"]
    ):
        raise ValueError("PORTFOLIO_NATIVE_ATTEMPT_CHANGED")
    return i
