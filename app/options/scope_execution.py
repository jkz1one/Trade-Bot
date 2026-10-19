"""Frozen Scope PAPER entry consumption and native filled-play lifecycle.

Research receipts remain evidence. Only a newly enrolled owner may consume one,
inside the same transaction as its native decision/order. No venue is selected here.
"""

import json
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.lifecycle import TERMINAL, EntryLineage, OptionIntent, OptionLedger
from app.options.models import Name, OptionLimits, OptionProposal, OptionRecord, SessionWindow
from app.options.scope import ScopePreflightInput
from app.options.scope_admission import _review_entry_path, scope_quantity_cap
from app.options.scope_context import ScopeContextInput
from app.options.scope_contract import scan_scope_contract
from app.options.scope_entry import select_entry, verify_binding

TABLE = "execution_option_scope_entries"
ACTIVE = {"ORDER_WORKING", "POSITION_OPEN"}
FINISHED = {"CLOSED", "ENDED_UNFILLED"}


class ScopeExecutionRequest(OptionRecord):
    play_key: Name
    expected_revision: int = Field(strict=True, ge=1)
    arbitration_cycle: Name | None = Field(default=None, exclude_if=lambda v: v is None)


def enrolled(engine, policy):
    if (
        engine.policy.scope_execution != "scope-native-v1"
        or policy.native_execution != "scope-native-v1"
    ):
        raise ExecutionBlocked("SCOPE_NATIVE_EXECUTION_NOT_ENROLLED")


def entry_source(play_key, action_key):
    """A rejected preparation cannot burn a watch; a new admission gets a new source."""
    return "scope:" + fingerprint({"play_key": play_key, "action_key": action_key})


def lineage(packet):
    binding = packet["binding"]
    return EntryLineage(
        family="SCOPE",
        setup=packet["choice"]["pattern"],
        opportunity_key=entry_source(binding["play_key"], binding["action_key"]),
        candidate_id=binding["play_key"],
        candidate_hash=packet["binding_hash"],
    )


def prepare_review(engine, db, source_key, inputs, request, now):
    from app.options.scope_admission import reject_unlinked_scope_entry
    from app.options.scope_observer import stored_policy

    if inputs["proposal"]["action"] != "OPEN_LONG":
        if request is not None:
            raise ExecutionBlocked("SCOPE_ENTRY_BUY_REQUIRED")
        return None
    if request is None and engine.policy.scope_arbitration is not None:
        # The common prepare boundary has already verified the selected Degen/Swing source.
        return None
    if request is None:
        reject_unlinked_scope_entry(db, OptionProposal.model_validate(inputs["proposal"]))
        if engine.policy.scope_execution is not None:
            raise ExecutionBlocked("SCOPE_NATIVE_EXECUTION_NOT_ENROLLED")
        return None
    policy = stored_policy(db, engine.limits, json.loads)
    enrolled(engine, policy)
    packet = select_entry(engine, db, policy, request.play_key, request.expected_revision, now)
    if source_key != lineage(packet).opportunity_key:
        raise ExecutionBlocked("SCOPE_ENTRY_SOURCE_CHANGED")
    if packet["execution_blockers"]:
        raise ExecutionBlocked(";".join(packet["execution_blockers"]))
    if inputs["origin"] != "DETERMINISTIC" or any(
        k in inputs for k in ("entry_request", "entry_result")
    ):
        raise ExecutionBlocked("SCOPE_DETERMINISTIC_ENTRY_REQUIRED")
    if request.arbitration_cycle is not None:
        row = db.execute(
            "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
            (request.arbitration_cycle,),
        ).fetchone()
        if not row or json.loads(row[0]).get("scope_candidate") != packet:
            raise ExecutionBlocked("SHARED_SCOPE_ADMISSION_CHANGED")
    expected = {
        "proposal": packet["proposal"],
        "quote": packet["quote"],
        "underlying": packet["underlying"],
        "ceiling": packet["admission"],
        "target_exit_schedule": packet["management"]["target_exit_schedule"],
        "entry_premium_protection": packet["management"]["entry_premium_protection"],
        "entry_time_protection": packet["entry_time_protection"],
    }
    if any(fingerprint(inputs.get(k)) != fingerprint(v) for k, v in expected.items()):
        raise ExecutionBlocked("SCOPE_ENTRY_TERMS_CHANGED")
    if db.execute(f"SELECT 1 FROM {TABLE} WHERE play_key=?", (request.play_key,)).fetchone():
        raise ExecutionBlocked("SCOPE_PLAY_ALREADY_SUBMITTED")
    return packet


def _record_action(engine, db, record, key, now):
    """Native transitions have their own immutable watch action, never a fresh admission."""
    record.pop("entry_binding", None)
    active = 1 if record["status"] in ACTIVE else None
    db.execute(
        "UPDATE execution_option_scope_watches SET active_lock=?,record_json=? WHERE play_key=?",
        (active, json.dumps(record, sort_keys=True), record["play_key"]),
    )
    engine.journal.event(db, now, "SCOPE_WATCH_ACTION", {"action_key": key, "record": record})
    receipt = {
        "revision": engine.journal.revision(db),
        "record": record,
        "authority": False,
        "live_enabled": False,
    }
    db.execute(
        "INSERT INTO execution_option_scope_watch_actions VALUES(?,?,?)",
        (key, fingerprint({"native_transition": record}), json.dumps(receipt, sort_keys=True)),
    )
    db.execute(
        "UPDATE execution_option_scope_watch_policy SET last_action_at=? WHERE id=1",
        (now.isoformat(),),
    )


def consume(engine, db, intent, packet, now):
    from app.options.scope_observer import _watch_binding

    record = json.loads(
        db.execute(
            "SELECT record_json FROM execution_option_scope_watches WHERE play_key=?",
            (packet["binding"]["play_key"],),
        ).fetchone()[0]
    )
    receipt = {
        "version": "scope-native-v1",
        "client_id": intent.client_id,
        "packet": packet,
        "record": record,
        "audit": _watch_binding(db, record, json.loads),
    }
    db.execute(
        f"INSERT INTO {TABLE} VALUES(?,?,?)",
        (packet["binding"]["play_key"], intent.client_id, json.dumps(receipt, sort_keys=True)),
    )
    engine.journal.event(db, now, "SCOPE_ENTRY_CONSUMED", receipt, intent.client_id)
    record["native_client_id"] = intent.client_id
    record["status"] = "ORDER_WORKING"
    _record_action(engine, db, record, "scope-order-" + intent.client_id, now)


def stored_entry(db, source_key=None, *, play_key=None):
    """Verify original evidence, native receipt and frozen owner without granting authority."""
    from app.options.lifecycle import OptionExecutionPolicy
    from app.options.scope_observer import stored_policy

    if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return None
    row = (
        db.execute(f"SELECT * FROM {TABLE} WHERE play_key=?", (play_key,)).fetchone()
        if play_key is not None
        else db.execute(
            f"SELECT e.* FROM {TABLE} e JOIN execution_orders o ON o.client_id=e.client_id WHERE o.source_key=?",
            (source_key,),
        ).fetchone()
    )
    if row is None:
        return None
    receipt = json.loads(row["receipt_json"])
    config = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    limits = OptionLimits.model_validate(config["limits"])
    owner = OptionExecutionPolicy.model_validate(config["policy"])
    policy = stored_policy(db, limits, json.loads)
    events = db.execute(
        "SELECT payload FROM execution_events WHERE kind='SCOPE_ENTRY_CONSUMED' AND client_id=? LIMIT 2",
        (row["client_id"],),
    ).fetchall()
    packet = receipt["packet"]
    binding = verify_binding(
        db, receipt["record"], policy, owner, limits, receipt["audit"], json.loads
    )
    watch = db.execute(
        "SELECT record_json FROM execution_option_scope_watches WHERE play_key=?",
        (row["play_key"],),
    ).fetchone()
    order = db.execute(
        "SELECT source_key FROM execution_orders WHERE client_id=?", (row["client_id"],)
    ).fetchone()
    if (
        order is None
        or order["source_key"] != lineage(packet).opportunity_key
        or len(events) != 1
        or fingerprint(json.loads(events[0][0])) != fingerprint(receipt)
        or receipt["client_id"] != row["client_id"]
        or row["play_key"] != binding.play_key
        or (source_key is not None and source_key != lineage(packet).opportunity_key)
        or owner.scope_execution != "scope-native-v1"
        or policy.native_execution != "scope-native-v1"
        or packet["binding"] != binding.model_dump(mode="json")
        or packet["binding_hash"] != fingerprint(binding)
        or watch is None
        or json.loads(watch[0]).get("native_client_id") != row["client_id"]
    ):
        raise ValueError("SCOPE_NATIVE_RECEIPT_CHANGED")
    return receipt


def verify_native_intent(db, intent, approval):
    receipt = stored_entry(db, intent.source_key)
    if receipt is None:
        if "scope_entry" in approval or (
            intent.entry_lineage and intent.entry_lineage.family == "SCOPE"
        ):
            raise ValueError("SCOPE_NATIVE_RECEIPT_REQUIRED")
        return None
    p = receipt["packet"]
    decision = db.execute(
        "SELECT inputs_json FROM execution_option_decisions WHERE source_key=?",
        (intent.source_key,),
    ).fetchone()
    expected = {
        "proposal": p["proposal"],
        "quote": p["quote"],
        "underlying": p["underlying"],
        "ceiling": p["admission"],
        "target_exit_schedule": p["management"]["target_exit_schedule"],
        "entry_premium_protection": p["management"]["entry_premium_protection"],
        "entry_time_protection": p["entry_time_protection"],
        "scope_entry": {
            "play_key": p["binding"]["play_key"],
            "expected_revision": p["binding"]["revision"],
        },
    }
    original = json.loads(decision[0]) if decision else {}
    if "scope_arbitration" in original:
        expected["scope_entry"]["arbitration_cycle"] = original["scope_arbitration"]["cycle_key"]
    if (
        intent.side != "BUY"
        or intent.client_id != receipt["client_id"]
        or intent.entry_lineage != lineage(p)
        or any(
            fingerprint(approval.get(k)) != fingerprint(v)
            or fingerprint(original.get(k)) != fingerprint(v)
            for k, v in expected.items()
        )
        or intent.quantity != p["admission"]["quantity"]
        or any(
            getattr(intent, name) != Decimal(p["admission"][field])
            for name, field in (
                ("limit_price", "limit_price"),
                ("approved_entry_debit", "entry_debit"),
                ("approved_full_premium_loss", "full_premium_loss"),
            )
        )
        or any(
            getattr(intent, name) is None
            or getattr(intent, name).model_dump(mode="json") != expected[name]
            for name in (
                "target_exit_schedule",
                "entry_premium_protection",
                "entry_time_protection",
            )
        )
        or intent.instrument.model_dump(mode="json") != p["instrument"]
        or intent.original_underlying_invalidation
        != Decimal(p["management"]["geometry"]["invalidation"])
    ):
        raise ValueError("SCOPE_NATIVE_TERMS_CHANGED")
    return receipt


def dispatch_review(engine, db, intent, approval, quote, underlying, now):
    from app.options.governor import admit_option
    from app.options.models import OptionProposal
    from app.options.scope_admission import reject_unlinked_scope_entry
    from app.options.scope_observer import stored_policy

    if intent.side != "BUY":
        return
    receipt = verify_native_intent(db, intent, approval)
    if receipt is None and engine.policy.scope_arbitration is not None:
        # verified_lineage checks the immutable common selection receipt before dispatch.
        return
    if receipt is None:
        reject_unlinked_scope_entry(db, OptionProposal.model_validate(approval["proposal"]))
        if engine.policy.scope_execution is not None:
            raise ExecutionBlocked("SCOPE_NATIVE_EXECUTION_NOT_ENROLLED")
        return
    p = receipt["packet"]
    policy = stored_policy(db, engine.limits, json.loads)
    enrolled(engine, policy)
    if (
        not datetime.fromisoformat(p["binding"]["evaluated_at"])
        <= now
        < datetime.fromisoformat(p["binding"]["valid_until"])
    ):
        raise ExecutionBlocked("SCOPE_ENTRY_ADMISSION_EXPIRED")
    record = receipt["record"]
    frame = ScopePreflightInput.model_validate(record["arming"]["frame"])
    context = ScopeContextInput.model_validate(record["arming"]["context"])
    # Only the executable quote advances here; all retained coverage must still be fresh.
    frame = frame.model_copy(update={"quote": quote})
    scan = scan_scope_contract(frame, context, policy.contract, now=now)
    selected = [
        o for o in scan.observations if all(getattr(o, k) == v for k, v in p["choice"].items())
    ]
    if (
        scan.issues
        or len(selected) != 1
        or not selected[0].passed
        or selected[0].profile != p["management"]["contract_observation"]["profile"]
    ):
        raise ExecutionBlocked("SCOPE_DISPATCH_CONTRACT_BLOCKED")
    from app.options.scope_structure import ScopeGeometry

    g = ScopeGeometry.model_validate(p["geometry"])
    if underlying is None:
        raise ExecutionBlocked("SCOPE_DISPATCH_UNDERLYING_REQUIRED")
    # The common governor below checks source, freshness and exact quote identity.
    reference = underlying.ask if g.right == "CALL" else underlying.bid
    if reference >= g.target_one if g.right == "CALL" else reference <= g.target_one:
        raise ExecutionBlocked("SCOPE_CURRENT_FIRST_OBJECTIVE_CONSUMED")
    path = _review_entry_path(frame, context, p["geometry"], policy.quality, underlying, now=now)
    if not path.passed:
        raise ExecutionBlocked(";".join(path.reasons))
    effective = engine._effective_limits().model_copy(
        update={"max_contracts": min(engine.limits.max_contracts, scope_quantity_cap(quote.ask))}
    )
    admission = admit_option(
        OptionProposal.model_validate(p["proposal"]),
        quote,
        underlying,
        engine._account(db, now, exclude=intent.client_id),
        effective,
        SessionWindow.model_validate(p["session"]),
        now=now,
    )
    if (
        admission.outcome != "APPROVED"
        or admission.quantity < intent.quantity
        or admission.limit_price > intent.limit_price
    ):
        raise ExecutionBlocked("SCOPE_DISPATCH_ADMISSION_CHANGED")


def sync(engine, db, now):
    """Only native order/ledger evidence changes filled lifecycle; costs settle separately."""
    if engine.policy.scope_execution is None:
        return
    rows = (
        db.execute("SELECT * FROM execution_option_scope_watches WHERE active_lock=1").fetchall()
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_option_scope_watches'"
        ).fetchone()
        else []
    )
    ledger = OptionLedger.model_validate_json(engine._control(db)["ledger_json"])
    for row in rows:
        record = json.loads(row["record_json"])
        if "native_client_id" not in record:
            continue
        order = db.execute(
            "SELECT * FROM execution_orders WHERE client_id=?", (record["native_client_id"],)
        ).fetchone()
        if order is None:
            raise ValueError("SCOPE_NATIVE_ORDER_REQUIRED")
        intent = OptionIntent.model_validate_json(order["intent_json"])
        verify_native_intent(db, intent, json.loads(order["approval_json"]))
        held = ledger.position and ledger.position.entry_client_id == intent.client_id
        if held:
            status = "POSITION_OPEN"
        elif order["status"] not in TERMINAL:
            status = "ORDER_WORKING"
        else:
            filled = db.execute(
                "SELECT 1 FROM execution_fills WHERE client_id=? LIMIT 1", (intent.client_id,)
            ).fetchone()
            status = "CLOSED" if filled else "ENDED_UNFILLED"
        if status != record["status"]:
            record["status"] = status
            if status in FINISHED:
                record["terminal_at"] = now.isoformat()
            _record_action(
                engine, db, record, "scope-state-" + str(engine.journal.revision(db) + 1), now
            )
