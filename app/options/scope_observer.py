"""Bounded stored Scope research projection; no watch owner or fresh evaluation."""

from datetime import datetime

from pydantic import TypeAdapter

from app.options.engine import clock, fingerprint
from app.options.models import Name, OptionAdmission
from app.options.scope import ScopePreflightInput
from app.options.scope_admission import ScopeEntryPathReview
from app.options.scope_context import ScopeContextInput
from app.options.scope_contract import ScopeContractScan
from app.options.scope_management import ScopeManagementReview
from app.options.scope_quality import ScopeQualityScan
from app.options.scope_quote import ScopeQuoteReview
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


def _watch_binding(db, record, read_json):
    event = db.execute(
        "SELECT sequence,occurred_at,payload FROM execution_events "
        "WHERE kind='SCOPE_WATCH_ACTION' AND json_extract(payload,'$.record.play_key')=? "
        "ORDER BY sequence DESC LIMIT 1",
        (record["play_key"],),
    ).fetchone()
    if event is None:
        raise ValueError("Stored Scope watch has no recorded action")
    payload = read_json(event["payload"])
    action_key = TypeAdapter(Name).validate_python(payload["action_key"])
    receipt = db.execute(
        "SELECT request_hash,result_json FROM execution_option_scope_watch_actions WHERE action_key=?",
        (action_key,),
    ).fetchone()
    expected = {
        "revision": event["sequence"],
        "record": record,
        "authority": False,
        "live_enabled": False,
    }
    if (
        fingerprint(payload["record"]) != fingerprint(record)
        or receipt is None
        or len(receipt["request_hash"]) != 64
        or any(c not in "0123456789abcdef" for c in receipt["request_hash"])
        or fingerprint(read_json(receipt["result_json"])) != fingerprint(expected)
    ):
        raise ValueError("Stored Scope watch/action/receipt mismatch")
    return {
        "sequence": event["sequence"],
        "action_key": action_key,
        "recorded_at": _stamp(event["occurred_at"]).isoformat(),
    }


def _decision_evidence(record, policy, choice, now):
    """Project selected stored observations only. Never call a strategy evaluator."""

    def review(frame, context, quality, contract, evaluated_at, until):
        result = {"quality": None, "contract": None}
        if quality is None and contract is None:
            return result
        if quality is None or policy.quality is None or frame is None or context is None:
            raise ValueError("Incomplete stored Scope review inputs")
        frame = ScopePreflightInput.model_validate(frame)
        context = ScopeContextInput.model_validate(context)
        q = ScopeQualityScan.model_validate(quality)
        digest = fingerprint({"frame": frame, "context": context})
        stamp = _stamp(evaluated_at)
        if (
            q.input_hash != digest
            or q.policy_hash != fingerprint(policy.quality)
            or q.evaluated_at != stamp
            or q.context.evaluated_at != stamp
            or q.context.input_hash != digest
            or q.context.policy_hash != fingerprint(policy.context)
        ):
            raise ValueError("Stored Scope quality lost its input/policy binding")
        selected = [
            o
            for o in q.observations
            if all(getattr(o.observation, k) == v for k, v in choice.model_dump().items())
        ]
        if len(selected) > 1 or (not q.issues and len(selected) != 1):
            raise ValueError("Ambiguous stored Scope quality selection")
        result["quality"] = {
            "evaluated_at": stamp.isoformat(),
            "time_status": _timing(stamp, until, now),
            "input_hash": digest,
            "policy_hash": q.policy_hash,
            "issues": list(q.issues),
            "selected": selected[0].model_dump(mode="json") if selected else None,
        }
        if contract is not None:
            c = ScopeContractScan.model_validate(contract)
            if (
                policy.contract is None
                or c.quality != q
                or c.input_hash != digest
                or c.policy_hash != fingerprint(policy.contract)
                or c.evaluated_at != stamp
            ):
                raise ValueError("Stored Scope contract lost its quality/policy binding")
            selected = [
                o
                for o in c.observations
                if all(getattr(o, k) == v for k, v in choice.model_dump().items())
            ]
            if len(selected) > 1 or (not c.issues and len(selected) != 1):
                raise ValueError("Ambiguous stored Scope contract selection")
            result["contract"] = {
                "evaluated_at": stamp.isoformat(),
                "time_status": _timing(stamp, until, now),
                "issues": list(c.issues),
                "selected": selected[0].model_dump(mode="json") if selected else None,
            }
        return result

    if (policy.quality is not None) != ("locked_quality_scan" in record) or (
        (policy.contract is not None) != ("locked_contract_scan" in record)
    ):
        raise ValueError("Missing original Scope review")
    called = review(
        record["locked_frame"],
        record["locked_context"],
        record.get("locked_quality_scan"),
        record.get("locked_contract_scan"),
        record["called_at"],
        None,
    )
    latest = None
    if "arming" in record:
        a = record["arming"]
        latest = review(
            a.get("frame"),
            a.get("context"),
            a.get("quality_scan"),
            a.get("contract_scan"),
            a["evaluated_at"],
            a["valid_until"],
        )
    return {
        "called": called,
        "latest_sample": latest,
        "stored_only": True,
        "authority": False,
        "live_enabled": False,
    }


def _watch(db, row, policy, now, read_json, owner_policy, limits):
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
    audit = _watch_binding(db, record, read_json)
    called = _stamp(record["called_at"])
    reviewed = _stamp(record["reviewed_through"])
    terminal = _stamp(record["terminal_at"]) if record["terminal_at"] else None
    if (terminal is None) != (status == "WATCHING"):
        raise ValueError("Conflicting terminal Scope evidence")
    result = {
        "audit": audit,
        "decision_evidence": _decision_evidence(record, policy, choice, now),
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
    for name in ("quote_review", "terminal_quote"):
        if name not in record:
            continue
        quote_review = ScopeQuoteReview.model_validate(record[name])
        if (
            policy.quote_lifecycle is None
            or quote_review.geometry != geometry
            or quote_review.limits_hash != fingerprint(limits)
            or not called <= quote_review.evaluated_at <= _stamp(audit["recorded_at"])
            or (
                name == "terminal_quote"
                and (
                    quote_review.status
                    not in {"INVALIDATED_UNFILLED", "OBJECTIVE_CONSUMED_UNFILLED"}
                    or quote_review.status != status
                    or quote_review.evaluated_at != terminal
                    or quote_review.quote.model_dump(mode="json")
                    != record.get("last_observed_quote")
                )
            )
        ):
            raise ValueError("Conflicting stored Scope quote lifecycle")
        result[name] = quote_review.model_dump(mode="json") | {
            "time_status": "FUTURE" if quote_review.evaluated_at > now else "HISTORICAL"
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
        if "entry_path" in r:
            path = ScopeEntryPathReview.model_validate(r["entry_path"]) if r["entry_path"] else None
            if path and (
                path.geometry != geometry
                or path.passed != (not path.reasons)
                or (r["eligible"] and not path.passed)
            ):
                raise ValueError("Conflicting stored Scope current-entry path")
            result["admission"]["entry_path"] = path.model_dump(mode="json") if path else None
        if policy.management is not None and r["eligible"] != ("management" in r):
            raise ValueError("Stored Scope management coverage mismatch")
        if "management" in r:
            management = ScopeManagementReview.model_validate(r["management"])
            if (
                management.policy != policy.management
                or management.geometry != geometry
                or management.admission_hash != fingerprint(admission)
                or not r["eligible"]
                or management.admitted_quantity != admission.quantity
                or management.contract_id != admission.contract_id
                or management.evaluated_at != admission.approved_at
                or management.valid_until != admission.valid_until
                or management.owner_maximum_loss_fraction
                != owner_policy.premium_catastrophe_fraction
                or any(
                    getattr(management.contract_observation, k) != v
                    for k, v in record["choice"].items()
                )
            ):
                raise ValueError("Conflicting stored Scope management plan")
            result["admission"]["management"] = management.model_dump(mode="json")
    if "entry_binding" in record:
        from app.options.scope_entry import verify_binding

        binding = verify_binding(db, record, policy, owner_policy, limits, audit, read_json)
        result["entry_binding"] = binding.model_dump(mode="json") | {
            "time_status": _timing(binding.evaluated_at, binding.valid_until, now),
            "current_revision": db.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM execution_events"
            ).fetchone()[0]
            == binding.revision,
        }
    return result


def stored_scope(db, tables, limits, now, read_json, *, owner_policy):
    """Latest 25 records plus the active record, independent of opportunity paging."""
    base = {"authority": False, "live_enabled": False, "execution": "NOT_ENROLLED"}
    if not TABLES & tables:
        return base | {"status": "NOT_ENROLLED", "watches": [], "active_watch": None}
    if not TABLES <= tables:
        raise ValueError("Incomplete Scope schema")
    policy = stored_policy(db, limits, read_json)
    last_action = _stamp(
        db.execute(
            "SELECT last_action_at FROM execution_option_scope_watch_policy WHERE id=1"
        ).fetchone()[0]
    )
    count = db.execute("SELECT COUNT(*) FROM execution_option_scope_watches").fetchone()[0]
    rows = db.execute(
        "SELECT * FROM execution_option_scope_watches ORDER BY session_date DESC,rowid DESC LIMIT 25"
    ).fetchall()
    watches = [_watch(db, row, policy, now, read_json, owner_policy, limits) for row in rows]
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
        "active_watch": _watch(db, active[0], policy, now, read_json, owner_policy, limits)
        if active
        else None,
    }


def stored_policy(db, limits, read_json):
    """Read the frozen enrollment and its clock binding, without owner mutation."""
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
    enrollment = db.execute(
        "SELECT occurred_at,payload FROM execution_events WHERE kind='SCOPE_WATCH_ENROLLED' LIMIT 2"
    ).fetchall()
    latest = db.execute(
        "SELECT occurred_at FROM execution_events WHERE kind='SCOPE_WATCH_ACTION' "
        "ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    if (
        len(enrollment) != 1
        or read_json(enrollment[0]["payload"]) != policy.model_dump(mode="json")
        or last_action != _stamp((latest or enrollment[0])["occurred_at"])
    ):
        raise ValueError("Stored Scope policy/action clock lost its enrollment binding")
    return policy
