"""Bounded stored Scope research projection; no watch owner or fresh evaluation."""

from datetime import datetime

from pydantic import TypeAdapter

from app.options.engine import clock, fingerprint
from app.options.models import Name, OptionAdmission
from app.options.scope import ScopePreflightInput
from app.options.scope_structure import ScopeGeometry
from app.options.scope_watch import ScopeWatchChoice, ScopeWatchPolicy

TABLES = frozenset(
    {
        "execution_option_scope_watch_policy",
        "execution_option_scope_watches",
        "execution_option_scope_watch_actions",
    }
)
TERMINAL = {"EXPIRED_UNFILLED", "INVALIDATED_UNFILLED", "OBJECTIVE_CONSUMED_UNFILLED"}


def _stamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise TypeError("Stored Scope timestamp required")
    return clock(value)


def _reasons(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("Bounded Scope reasons required")
    return [TypeAdapter(Name).validate_python(v) for v in value]


def _timing(evaluated, until, now):
    evaluated = _stamp(evaluated)
    deadline = _stamp(until) if until is not None else None
    return (
        "FUTURE"
        if evaluated > now
        else "NO_VALIDITY_RECORDED"
        if deadline is None
        else "EXPIRED"
        if now >= deadline
        else "WITHIN_RECORDED_WINDOW"
    )


def _watch(row, policy, now, read_json):
    record = read_json(row["record_json"])
    key = TypeAdapter(Name).validate_python(record["play_key"])
    frame = ScopePreflightInput.model_validate(record["locked_frame"])
    choice = ScopeWatchChoice.model_validate(record["choice"])
    geometry = ScopeGeometry.model_validate(record["geometry"])
    status = record["status"]
    if (
        key != row["play_key"]
        or record["session_date"] != row["session_date"]
        or record["session_date"] != str(frame.session.session_date)
        or status not in TERMINAL | {"WATCHING"}
        or (row["active_lock"] == 1) != (status == "WATCHING")
        or row["active_lock"] not in (None, 1)
        or frame.metadata is None
        or choice.right != geometry.right
        or choice.right != frame.metadata.instrument.contract.right
        or frame.metadata.instrument.contract.underlying != "SPX"
    ):
        raise ValueError("Conflicting stored Scope identity/state")
    called = _stamp(record["called_at"])
    reviewed = _stamp(record["reviewed_through"])
    terminal = _stamp(record["terminal_at"]) if record["terminal_at"] else None
    if (terminal is None) != (status == "WATCHING"):
        raise ValueError("Conflicting terminal Scope evidence")
    result = {
        "play_key": key,
        "session_date": record["session_date"],
        "called_at": called.isoformat(),
        "recorded_status": status,
        "active_record": row["active_lock"] == 1,
        "reviewed_through": reviewed.isoformat(),
        "terminal_at": terminal.isoformat() if terminal else None,
        "entry_cutoff_at": frame.session.entry_cutoff_at.isoformat(),
        "time_status": "FUTURE"
        if called > now or reviewed > now or (terminal and terminal > now)
        else "PAST_ENTRY_CUTOFF"
        if now >= frame.session.entry_cutoff_at
        else "BEFORE_ENTRY_CUTOFF",
        "choice": choice.model_dump(mode="json"),
        "contract": frame.metadata.instrument.contract.model_dump(mode="json"),
        "geometry": geometry.model_dump(mode="json"),
        "arming": None,
        "admission": None,
        "authority": False,
        "live_enabled": False,
    }
    if "arming" in record:
        a = record["arming"]
        if (
            policy.arming is None
            or a["status"] not in {"RESET", "HOLDING", "ARMED"}
            or type(a["sample_count"]) is not int
            or a["sample_count"] < 0
            or a["authority"] is not False
            or a["live_enabled"] is not False
        ):
            raise ValueError("Invalid stored Scope arming")
        result["arming"] = {
            "recorded_status": a["status"],
            "evaluated_at": _stamp(a["evaluated_at"]).isoformat(),
            "valid_until": _stamp(a["valid_until"]).isoformat() if a["valid_until"] else None,
            "sample_count": a["sample_count"],
            "time_status": _timing(a["evaluated_at"], a["valid_until"], now),
            "reasons": _reasons(a["reasons"]),
        }
    if "admission_review" in record:
        r = record["admission_review"]
        admission = OptionAdmission.model_validate(r["admission"]) if r["admission"] else None
        if (
            policy.admission is None
            or type(r["eligible"]) is not bool
            or r["eligible"] != bool(admission and admission.outcome == "APPROVED")
            or r["authority"] is not False
            or r["live_enabled"] is not False
            or (
                admission
                and admission.contract_id is not None
                and admission.contract_id != frame.metadata.instrument.contract.contract_id
            )
        ):
            raise ValueError("Invalid stored Scope admission")
        result["admission"] = {
            "evaluated_at": _stamp(r["evaluated_at"]).isoformat(),
            "recorded_eligible": r["eligible"],
            "time_status": _timing(
                r["evaluated_at"], admission.valid_until if admission else None, now
            ),
            "reasons": _reasons(r["reasons"]),
            "result": admission.model_dump(mode="json") if admission else None,
        }
    return result


def stored_scope(db, tables, limits, now, read_json):
    """Latest 25 records plus the active record, independent of opportunity paging."""
    base = {"authority": False, "live_enabled": False, "execution": "NOT_ENROLLED"}
    if not TABLES & tables:
        return base | {"status": "NOT_ENROLLED", "watches": [], "active_watch": None}
    if not TABLES <= tables:
        raise ValueError("Incomplete Scope schema")
    rows = db.execute("SELECT * FROM execution_option_scope_watch_policy LIMIT 2").fetchall()
    if len(rows) != 1 or rows[0]["id"] != 1:
        raise ValueError("Scope enrollment required")
    policy = ScopeWatchPolicy.model_validate(read_json(rows[0]["config_json"]))
    preflight = policy.context.structure.preflight
    if (
        "SPX" not in limits.allowed_underlyings
        or preflight.provider != limits.provider
        or preflight.quote_source != limits.option_source
    ):
        raise ValueError("Scope owner identity mismatch")
    last_action = _stamp(rows[0]["last_action_at"])
    count = db.execute("SELECT COUNT(*) FROM execution_option_scope_watches").fetchone()[0]
    rows = db.execute(
        "SELECT * FROM execution_option_scope_watches ORDER BY session_date DESC,rowid DESC LIMIT 25"
    ).fetchall()
    watches = [_watch(row, policy, now, read_json) for row in rows]
    active = db.execute(
        "SELECT * FROM execution_option_scope_watches WHERE active_lock IS NOT NULL LIMIT 2"
    ).fetchall()
    if len(active) > 1:
        raise ValueError("Multiple active Scope watches")
    return base | {
        "status": "RESEARCH_ONLY",
        "policy_hash": fingerprint(policy),
        "last_action_at": last_action.isoformat(),
        "last_action_time_status": "FUTURE" if last_action > now else "RECORDED",
        "total_watches": count,
        "history_limit": 25,
        "history_truncated": count > len(watches),
        "watches": watches,
        "active_watch": _watch(active[0], policy, now, read_json) if active else None,
    }
