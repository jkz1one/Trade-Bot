"""Durable observed progress diagnostics; no protection or order authority."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

from app.options.engine import clock, exact, fingerprint
from app.options.governor import _fresh
from app.options.greek_health import SOURCE_COMMIT, _display
from app.options.lifecycle import OptionFill, OptionIntent
from app.options.models import UnderlyingQuote

D = Decimal
TABLE = "execution_option_progress"


def _underlying_ok(u, entry, limits, now):
    return (
        u is not None
        and u.symbol == entry.instrument.contract.underlying
        and u.source == limits.underlying_source
        and u.complete
        and u.entitlement == "REALTIME"
        and u.bid <= u.ask
        and _fresh(
            u.source_at,
            u.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    )


def _baseline(db, position, limits):
    portfolio = (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_portfolio_control'"
        ).fetchone()
        is not None
    )
    table = "execution_portfolio_orders" if portfolio else "execution_orders"
    row = db.execute(
        f"SELECT intent_json,approval_json FROM {table} WHERE client_id=?",
        (position.entry_client_id,),
    ).fetchone()
    entry = OptionIntent.model_validate_json(row[0])
    approval = json.loads(row[1])
    original = db.execute(
        "SELECT inputs_json FROM execution_option_decisions WHERE source_key=?",
        (entry.source_key,),
    ).fetchone()
    inputs = json.loads(original[0]) if original else {}
    if portfolio:
        inputs = approval["inputs"]
        approval = inputs
    if (
        entry.side != "BUY"
        or entry.instrument.contract != position.contract
        or entry.original_underlying_invalidation != position.original_underlying_invalidation
        or not approval.get("underlying")
        or inputs.get("underlying") != approval["underlying"]
    ):
        raise ValueError("Progress baseline lost original entry binding")
    u = UnderlyingQuote.model_validate(approval["underlying"])
    if not _underlying_ok(u, entry, limits, entry.prepared_at):
        raise ValueError("Progress baseline underlying is unusable")
    direction = 1 if position.contract.right == "CALL" else -1
    reference = u.ask if direction == 1 else u.bid
    risk = direction * (reference - entry.original_underlying_invalidation)
    if risk <= 0:
        raise ValueError("Progress baseline requires positive original risk")
    fills = [
        OptionFill.model_validate_json(r[0])
        for r in db.execute(
            "SELECT payload FROM execution_fills WHERE client_id=? ORDER BY fill_id",
            (entry.client_id,),
        )
    ]
    if portfolio:
        observed = db.execute(
            "SELECT observation_json FROM execution_portfolio_orders WHERE client_id=?",
            (entry.client_id,),
        ).fetchone()[0]
        fills = (
            [OptionFill.model_validate(f) for f in json.loads(observed)["fills"]]
            if observed
            else []
        )
    if sum(f.quantity for f in fills) != entry.quantity:
        return entry, None
    basis = sum(f.price * f.quantity * position.contract.multiplier for f in fills)
    baseline = {
        "entry_client_id": entry.client_id,
        "entry_quantity": entry.quantity,
        "entry_basis": str(basis),
        "entered_at": min(f.occurred_at for f in fills).isoformat(),
        "entry_completed_at": max(f.occurred_at for f in fills).isoformat(),
        "underlying_reference": str(reference),
        "original_stop": str(entry.original_underlying_invalidation),
        "risk_distance": str(risk),
        "direction": direction,
        "entry_underlying": u.model_dump(mode="json"),
        "entry_fill_hash": fingerprint(fills),
        "entry_intent_hash": fingerprint(entry),
    }
    return entry, baseline


@exact
def record(engine, db, position, quote, underlying, now):
    """Called only in the owner's audited write transaction after native protection."""
    now = clock(now)
    limits = engine.limits
    entry, baseline = _baseline(db, position, limits)
    row = db.execute(
        f"SELECT payload FROM {TABLE} WHERE entry_client_id=?", (entry.client_id,)
    ).fetchone()
    old = json.loads(row[0]) if row else None
    state = old["state"] if old else None
    if old and now < datetime.fromisoformat(old["evaluated_at"]):
        # An old observation cannot erase newer diagnostics or advance their clock.
        return old
    if state and (baseline is None or state["baseline"] != baseline):
        raise ValueError("Progress original completed entry changed")
    reasons = []
    signals = dict.fromkeys(
        ("stalled", "premium_divergence", "premium_giveback", "underlying_giveback")
    )
    metrics = {}
    if baseline is None:
        reasons.append("ORIGINAL_ENTRY_INCOMPLETE")
    if not (
        quote is not None
        and quote.instrument == entry.instrument
        and quote.instrument.metadata_complete
        and quote.instrument.option_tradable
        and quote.source == limits.option_source
        and quote.complete
        and quote.entitlement == "REALTIME"
        and quote.bid is not None
        and quote.bid > 0
        and quote.bid_size is not None
        and quote.bid_size >= position.quantity
        and (quote.ask is None or quote.ask >= quote.bid)
        and _fresh(
            quote.source_at,
            quote.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        reasons.append("CURRENT_OPTION_UNUSABLE")
    if not _underlying_ok(underlying, entry, limits, now):
        reasons.append("CURRENT_UNDERLYING_UNUSABLE")
    if not reasons and (
        abs(quote.source_at - underlying.source_at) > timedelta(seconds=limits.max_sync_seconds)
        or min(quote.source_at, underlying.source_at)
        < datetime.fromisoformat(baseline["entry_completed_at"])
    ):
        reasons.append("CURRENT_PAIR_UNSYNCHRONIZED_OR_PRE_ENTRY")
    if not reasons and state:
        for name, evidence in (("option", quote), ("underlying", underlying)):
            prior = state["observations"][name]
            if (
                evidence.source_at < datetime.fromisoformat(prior["source_at"])
                or evidence.received_at < datetime.fromisoformat(prior["received_at"])
                or (
                    evidence.source_at == datetime.fromisoformat(prior["source_at"])
                    and fingerprint(evidence) != prior["hash"]
                )
            ):
                reasons.append("CURRENT_EVIDENCE_REGRESSION_OR_CONFLICT")
                break
    if not reasons:
        sample_at = min(quote.source_at, underlying.source_at)
        direction = baseline["direction"]
        reference, risk, basis = (
            D(baseline[k]) for k in ("underlying_reference", "risk_distance", "entry_basis")
        )
        current_price = underlying.bid if direction == 1 else underlying.ask
        progress = direction * (current_price - reference)
        premium = quote.bid * entry.quantity * position.contract.multiplier
        if state is None:
            state = {
                "baseline": baseline,
                "tracking_started_at": now.isoformat(),
                "coverage_since": sample_at.isoformat(),
                "last_progress_at": now.isoformat(),
                "peak_underlying_distance": str(max(D(0), progress)),
                "peak_bid": str(quote.bid),
                "highest_target_stage": position.target_exit_stage,
            }
        else:
            state = dict(state)
            previous_at = datetime.fromisoformat(state["sample_at"])
            if state.pop("coverage_interrupted", False) or sample_at - previous_at >= timedelta(
                seconds=limits.quote_max_age_seconds
            ):
                state["coverage_since"] = sample_at.isoformat()
            if (
                progress > D(state["peak_underlying_distance"])
                or quote.bid > D(state["peak_bid"])
                or position.target_exit_stage > state["highest_target_stage"]
            ):
                state["last_progress_at"] = now.isoformat()
            state["peak_underlying_distance"] = str(
                max(D(state["peak_underlying_distance"]), progress)
            )
            state["peak_bid"] = str(max(D(state["peak_bid"]), quote.bid))
            state["highest_target_stage"] = max(
                position.target_exit_stage, state["highest_target_stage"]
            )
        state["sample_at"] = sample_at.isoformat()
        state["observations"] = {
            name: {
                "source_at": evidence.source_at.isoformat(),
                "received_at": evidence.received_at.isoformat(),
                "hash": fingerprint(evidence),
            }
            for name, evidence in (("option", quote), ("underlying", underlying))
        }
        peak = D(state["peak_underlying_distance"])
        peak_premium = D(state["peak_bid"]) * entry.quantity * position.contract.multiplier
        elapsed = now - datetime.fromisoformat(state["last_progress_at"])
        coverage = sample_at - datetime.fromisoformat(state["coverage_since"])
        stall_candidate = (
            elapsed >= timedelta(minutes=20)
            and progress < risk * D(".25")
            and premium <= basis
            and state["highest_target_stage"] == 0
        )
        signals = {
            "stalled": stall_candidate
            if coverage >= timedelta(minutes=20) or not stall_candidate
            else None,
            "premium_divergence": progress >= risk * D(".25") and premium <= basis * D(".95"),
            "premium_giveback": peak_premium > basis and peak_premium - premium >= basis * D(".25"),
            "underlying_giveback": peak >= risk * D(".75") and peak - progress >= risk * D(".5"),
        }
        if signals["stalled"] is None:
            reasons.append("PROGRESS_COVERAGE_GAP")
        metrics = {
            "current_underlying_r": _display(progress / risk),
            "peak_underlying_r": _display(peak / risk),
            "underlying_giveback_r": _display((peak - progress) / risk),
            "premium_return_pct": _display((premium / basis - 1) * 100),
            "peak_premium_return_pct": _display((peak_premium / basis - 1) * 100),
            "premium_giveback_percentage_points": _display((peak_premium - premium) / basis * 100),
            "minutes_since_observed_progress": int(elapsed.total_seconds() // 60),
            "coverage_seconds": int(coverage.total_seconds()),
        }
    elif state:
        state = {**state, "coverage_interrupted": True}
    result = {
        "version": "observed-progress-v1",
        "source_commit": SOURCE_COMMIT,
        "entry_client_id": entry.client_id,
        "evaluated_at": now.isoformat(),
        "status": "INCOMPLETE" if reasons else "READY",
        "reasons": reasons,
        "state": state,
        "metrics": metrics,
        "signals": signals,
        "execution_authority": False,
        "live_enabled": False,
        "note": "Observed progress diagnostics only. Premium returns exclude fees and model/data/host costs; they are not net returns or whole-trade floors.",
    }
    if result != old:
        db.execute(
            f"INSERT INTO {TABLE} VALUES(?,?) ON CONFLICT(entry_client_id) DO UPDATE SET payload=excluded.payload",
            (entry.client_id, json.dumps(result, sort_keys=True)),
        )
        engine.journal.event(db, now, "OPTION_PROGRESS_OBSERVED", result, entry.client_id)
    return result


def stored(db, entry_id, limits, now):
    """Read-only compatibility with historical journals that lack the new table."""
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
    ).fetchone():
        return None
    row = db.execute(f"SELECT payload FROM {TABLE} WHERE entry_client_id=?", (entry_id,)).fetchone()
    if row is None:
        return None
    result = json.loads(row[0])
    event = db.execute(
        "SELECT payload FROM execution_events WHERE kind='OPTION_PROGRESS_OBSERVED' AND client_id=? ORDER BY sequence DESC LIMIT 1",
        (entry_id,),
    ).fetchone()
    if result["entry_client_id"] != entry_id or event is None or json.loads(event[0]) != result:
        raise ValueError("Stored progress lost its audited entry binding")
    state = result["state"]
    fresh = bool(
        state
        and all(
            _fresh(
                datetime.fromisoformat(o["source_at"]),
                datetime.fromisoformat(o["received_at"]),
                now,
                limits.quote_max_age_seconds,
                limits.max_receive_lag_seconds,
            )
            for o in state["observations"].values()
        )
    )
    return {**result, "stored_only": True, "observations_fresh": fresh}
