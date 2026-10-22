"""Native bounded Swing carry, derived only from the owner's frozen selected seed."""

import json
from datetime import timedelta
from types import SimpleNamespace

from app.options.carry_models import SwingCarryTerms
from app.options.swing_base_models import SWING_FAMILIES


def scan_carry_terms(seed, policy, catalyst, calendar):
    from app.options.engine import fingerprint
    from app.options.swing_carry import _calendar_path

    if seed.carry_exit_session is None or seed.first_target is None:
        return None, ("SWING_CARRY_SEED_POLICY_REQUIRED",)
    # Scanner validates the structural calendar. Native owner reapplies its exact expiry guard.
    request = SimpleNamespace(
        item=SimpleNamespace(seed=seed, catalyst=catalyst),
        exit_session=seed.carry_exit_session,
        carry=policy.carry,
        execution=SimpleNamespace(expiry_guard_seconds=0),
    )
    try:
        sessions, deadline, reasons = _calendar_path(request, calendar)
    except ValueError:
        return None, ("SWING_CARRY_CALENDAR_UNAVAILABLE",)
    if reasons:
        return None, reasons
    return SwingCarryTerms(
        seed_hash=fingerprint(seed),
        policy_hash=fingerprint(policy),
        sessions=sessions,
        exit_at=deadline,
        first_target=seed.first_target,
        catalyst_valid_through=catalyst.valid_through,
    ), ()


def selected_scan(db, source_key):
    from app.options.swing import SwingScan

    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_opportunities'"
    ).fetchone():
        return None
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (source_key,)
    ).fetchone()
    result = json.loads(row[0]) if row and row[0] else {}
    candidate_id = result.get("entry_result", {}).get("plan", {}).get("candidate_id") or result.get(
        "candidate_id"
    )
    matches = [c for c in result.get("candidates", []) if c["candidate_id"] == candidate_id]
    if len(matches) != 1 or matches[0]["family"] not in SWING_FAMILIES:
        return None
    from app.options.selection import parse_candidate
    from app.options.swing_batch import scan_matches

    candidate = parse_candidate(matches[0])
    scans = [
        scan
        for s in result.get("scans", [])
        if s.get("version") == "swing-next-session-v1"
        and scan_matches(scan := SwingScan.model_validate(s), candidate)
    ]
    if len(scans) != 1:
        raise ValueError("SWING_CARRY_SELECTED_SCAN_REQUIRED")
    return scans[0]


def stored_terms(db, source_key):
    from app.options.engine import fingerprint
    from app.options.swing import SwingPolicy
    from app.robinhood.schedule import XNYSCalendar

    # Legacy native family-risk fixtures/owners need no optional carry scan contract.
    # A carry-enrolled owner, however, must retain its frozen strategy enrollment.
    row = (
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_option_strategy'"
        ).fetchone()
        else None
    )
    config = json.loads(row[0]) if row else {}
    if "swing" not in config:
        owner = json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )
        if owner["policy"].get("swing_carry") is not None:
            raise ValueError("SWING_CARRY_STRATEGY_REQUIRED")
        return None
    scan = selected_scan(db, source_key)
    if scan is None:
        return None
    policy = SwingPolicy.model_validate(config["swing"])
    if policy.target_derivation is not None or scan.seed.target_geometry is not None:
        from app.options.swing_targets import verify_stored_targets

        verify_stored_targets(db, scan, policy)
    if policy.carry is None:
        if scan.carry_terms is not None:
            raise ValueError("SWING_CARRY_NOT_ENROLLED")
        return None
    terms, reasons = scan_carry_terms(scan.seed, policy, scan.catalyst, XNYSCalendar())
    from app.options.swing_batch import seed_lock

    lock = seed_lock(db, scan.seed)
    if (
        reasons
        or terms is None
        or terms != scan.carry_terms
        or scan.holding_policy != policy.holding_policy
        or lock is None
        or lock[0] != fingerprint(scan.seed)
    ):
        raise ValueError("SWING_CARRY_ORIGINAL_TERMS_CHANGED")
    return terms


def prepare_terms(engine, db, source_key, proposal):
    if proposal.action != "OPEN_LONG":
        return None
    terms = stored_terms(db, source_key)
    if terms is not None:
        if engine.policy.swing_carry != terms.version:
            raise ValueError("SWING_CARRY_OWNER_NOT_ENROLLED")
        if terms.exit_at >= proposal.contract.last_trading_at - timedelta(
            seconds=engine.policy.expiry_guard_seconds
        ):
            raise ValueError("SWING_CARRY_CONTRACT_CUTOFF")
    return terms


def verify_binding(db, intent, approval):
    from app.options.lifecycle import OptionExecutionPolicy

    if intent.side != "BUY":
        if intent.swing_carry is not None or "swing_carry" in approval:
            raise ValueError("SWING_CARRY_BUY_ONLY")
        return
    expected = stored_terms(db, intent.source_key)
    if expected != intent.swing_carry or approval.get("swing_carry") != (
        expected.model_dump(mode="json") if expected else None
    ):
        raise ValueError("SWING_CARRY_BINDING_CHANGED")
    if expected is None:
        return
    control = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
    policy = OptionExecutionPolicy.model_validate(json.loads(control[0])["policy"])
    if (
        policy.swing_carry != expected.version
        or expected.exit_at
        >= intent.instrument.contract.last_trading_at
        - timedelta(seconds=policy.expiry_guard_seconds)
    ):
        raise ValueError("SWING_CARRY_OWNER_CHANGED")
    row = db.execute(
        "SELECT inputs_json FROM execution_option_decisions WHERE source_key=?",
        (intent.source_key,),
    ).fetchone()
    if row is None or json.loads(row[0]).get("swing_carry") != expected.model_dump(mode="json"):
        raise ValueError("SWING_CARRY_DECISION_CHANGED")
    exit_at = (
        min(expected.exit_at, intent.entry_protection.exit_by)
        if intent.entry_protection
        else expected.exit_at
    )
    if intent.exit_at != exit_at or intent.order_expires_at != min(
        expected.sessions[0].closes_at, exit_at
    ):
        raise ValueError("SWING_CARRY_DEADLINE_CHANGED")


def verify_portable(intent, policy):
    """Recheck calendar/deadline authority in detached accounting evidence."""
    terms = intent.swing_carry
    if terms is None:
        return
    from app.robinhood.schedule import XNYSCalendar

    calendar = XNYSCalendar()
    if policy.swing_carry != terms.version or terms.exit_at >= (
        intent.instrument.contract.last_trading_at - timedelta(seconds=policy.expiry_guard_seconds)
    ):
        raise ValueError("SWING_CARRY_OWNER_NOT_ENROLLED")
    for session in terms.sessions:
        window = calendar.current_window(session.opens_at)
        if window is None or (window.session_date, window.opens_at, window.closes_at) != (
            session.session.isoformat(),
            session.opens_at,
            session.closes_at,
        ):
            raise ValueError("SWING_CARRY_CALENDAR_CHANGED")
    exit_at = (
        min(terms.exit_at, intent.entry_protection.exit_by)
        if intent.entry_protection
        else terms.exit_at
    )
    if intent.exit_at != exit_at or intent.order_expires_at != min(
        terms.sessions[0].closes_at, exit_at
    ):
        raise ValueError("SWING_CARRY_DEADLINE_CHANGED")
