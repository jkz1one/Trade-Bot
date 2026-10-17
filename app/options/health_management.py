"""Frozen PAPER health actions from observed evidence and native session authority."""

import json
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from app.options.engine import exact, fingerprint
from app.options.greek_health import SOURCE_COMMIT, review_greek_pressure
from app.options.lifecycle import OptionIntent
from app.options.models import OptionQuote

D = Decimal
VERSION = "observed-daytrade-health-v1"
TABLE = "execution_option_health"


def verify_binding(intent, approval):
    if intent.health_management != approval.get("health_management"):
        raise ValueError("OPTION_HEALTH_POLICY_CHANGED")


def stored(db, entry_id):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
    ).fetchone():
        return None
    row = db.execute(f"SELECT payload FROM {TABLE} WHERE entry_client_id=?", (entry_id,)).fetchone()
    if row is None:
        return None
    result = json.loads(row[0])
    event = db.execute(
        "SELECT payload FROM execution_events WHERE kind='OPTION_HEALTH_ASSESSED' AND client_id=? ORDER BY sequence DESC LIMIT 1",
        (entry_id,),
    ).fetchone()
    if result["entry_client_id"] != entry_id or event is None or json.loads(event[0]) != result:
        raise ValueError("Stored health lost its audited entry binding")
    return result


def blocked(engine, db, position):
    if engine.policy.health_management is None:
        return False
    review = stored(db, position.entry_client_id)
    return review is None or review["status"] == "INCOMPLETE"


@exact
def assess(engine, db, p, quote, underlying, progress, now):
    """Only the owner invokes this inside a native protection write transaction."""
    row = db.execute(
        "SELECT intent_json,approval_json FROM execution_orders WHERE client_id=?",
        (p.entry_client_id,),
    ).fetchone()
    entry = OptionIntent.model_validate_json(row[0])
    approval = json.loads(row[1])
    verify_binding(entry, approval)
    original = db.execute(
        "SELECT inputs_json FROM execution_option_decisions WHERE source_key=?",
        (entry.source_key,),
    ).fetchone()
    inputs = json.loads(original[0]) if original else {}
    if (
        entry.health_management != engine.policy.health_management
        or inputs.get("health_management") != entry.health_management
        or inputs.get("quote") != approval.get("quote")
    ):
        raise ValueError("OPTION_HEALTH_ORIGINAL_ENROLLMENT_CHANGED")
    old = stored(db, entry.client_id)
    if old and now < datetime.fromisoformat(old["evaluated_at"]):
        return p
    reasons = []
    excluded = (
        entry.entry_lineage is not None and entry.entry_lineage.family == "SWING"
    ) or p.contract.expiration != entry.prepared_at.astimezone(ZoneInfo("America/New_York")).date()
    greek = review_greek_pressure(
        OptionQuote.model_validate(approval["quote"]),
        quote,
        engine.limits,
        entry_at=entry.prepared_at,
        now=now,
    )
    if progress["evaluated_at"] != now.isoformat() or progress["status"] != "READY":
        reasons.append("CURRENT_PROGRESS_INCOMPLETE")
    if greek["status"] != "READY":
        reasons.append("CURRENT_GREEK_PRESSURE_INCOMPLETE")
    spread = None
    if (
        quote is not None
        and quote.ask is not None
        and quote.bid is not None
        and quote.ask >= quote.bid > 0
        and progress["status"] == "READY"
    ):
        spread = quote.ask - quote.bid > engine.limits.max_spread_fraction * quote.ask
    else:
        reasons.append("CURRENT_SPREAD_UNAVAILABLE")
    window = engine.calendar.current_window(now)
    minutes = int((window.closes_at - now).total_seconds() // 60) if window else None
    if minutes is None:
        reasons.append("NATIVE_SESSION_UNAVAILABLE")
    state = progress["state"]
    current_distance = risk = reference = None
    stage = state["highest_target_stage"] if state else None
    if state and progress["status"] == "READY":
        b = state["baseline"]
        reference, risk = D(b["underlying_reference"]), D(b["risk_distance"])
        mark = underlying.bid if b["direction"] == 1 else underlying.ask
        current_distance = b["direction"] * (mark - reference)
    signals = {**progress["signals"], **greek["signals"], "spread_degraded": spread}
    signals["late_session"] = (
        minutes <= 90 and stage == 0 and current_distance < risk * D(".5")
        if minutes is not None and current_distance is not None
        else None
    )
    weights = {
        "stalled": 2,
        "premium_divergence": 2,
        "premium_giveback": 1,
        "underlying_giveback": 1,
        "theta_pressure": 1,
        "iv_warning": 1,
        "delta_warning": 1,
        "spread_degraded": 2,
        "late_session": 1,
    }
    score = sum(weight for key, weight in weights.items() if signals[key] is True)
    status = "NOT_APPLICABLE" if excluded else "INCOMPLETE" if reasons else "READY"
    condition, action = "UNKNOWN", "WITHHOLD"
    action_reason = None
    stop = p.tightened_underlying_invalidation
    if p.exit_reason is not None:
        condition, action, action_reason = "EXIT", "EXIT_REQUIRED", p.exit_reason
    elif excluded:
        condition, action, action_reason = "NOT_APPLICABLE", "HOLD", "DAYTRADE_ONLY"
    elif status == "READY":
        decay = signals["stalled"] and (
            signals["theta_pressure"]
            or signals["iv_severe"]
            or signals["delta_severe"]
            or signals["premium_divergence"]
            or minutes <= 45
        )
        condition = (
            "EXIT" if decay else "DEFENSIVE" if score >= 2 else "CAUTION" if score else "HEALTHY"
        )
        action = "EXIT_REQUIRED" if decay else "HOLD"
        if decay:
            action_reason = "STALLED_DECAY"
        elif score and stage == 0:
            cap = D("-.25") if score >= 2 else D("-.50")
            sign = state["baseline"]["direction"]
            candidate = (reference + sign * cap * risk).quantize(
                D(".000000000001"), rounding=ROUND_CEILING if sign == 1 else ROUND_FLOOR
            )
            stop = max(stop, candidate) if sign == 1 else min(stop, candidate)
            if current_distance <= sign * (stop - reference):
                condition, action, action_reason = "EXIT", "EXIT_REQUIRED", "PRETARGET_RISK_CAP"
            elif stop != p.tightened_underlying_invalidation:
                action, action_reason = "TIGHTEN", "PRETARGET_HEALTH_STOP"
        if action == "EXIT_REQUIRED":
            p = p.model_copy(update={"exit_reason": "HEALTH_MANAGEMENT", "exit_required_at": now})
        p = p.model_copy(update={"tightened_underlying_invalidation": stop})
    # The semantic key describes durable protection, independent of changing prose/metrics.
    key = fingerprint({"condition": condition, "stop": stop, "exit_reason": p.exit_reason})
    decision_at = old["last_decision_at"] if old and old["decision_key"] == key else now.isoformat()
    missing = old["missing_quote_count"] if old else 0
    if not old or old["evaluated_at"] != now.isoformat():
        missing = missing + 1 if "CURRENT_OPTION_UNUSABLE" in progress["reasons"] else 0
    result = {
        "version": VERSION,
        "source_commit": SOURCE_COMMIT,
        "entry_client_id": entry.client_id,
        "evaluated_at": now.isoformat(),
        "status": status,
        "reasons": reasons,
        "condition": condition,
        "action": action,
        "action_reason": action_reason,
        "known_score": score,
        "signals": signals,
        "missing_quote_count": missing,
        "minutes_to_close": minutes,
        "session_closes_at": window.closes_at.isoformat() if window else None,
        "progress_hash": fingerprint(progress),
        "greek_pressure": greek,
        "effective_underlying_stop": str(stop),
        "exit_reason": p.exit_reason,
        "exit_required_at": p.exit_required_at.isoformat() if p.exit_required_at else None,
        "decision_key": key,
        "last_decision_at": decision_at,
        "execution_authority": False,
        "live_enabled": False,
        "note": "Stored native PAPER policy assessment; no caller order authority. Optional free-form market regime is not adopted. Missing/stale evidence withholds new health actions; independent mandatory protection remains active.",
    }
    if result != old:
        db.execute(
            f"INSERT INTO {TABLE} VALUES(?,?) ON CONFLICT(entry_client_id) DO UPDATE SET payload=excluded.payload",
            (entry.client_id, json.dumps(result, sort_keys=True)),
        )
        engine.journal.event(db, now, "OPTION_HEALTH_ASSESSED", result, entry.client_id)
    return p
