"""Exact stored Scope admission handoff. Evidence selection never grants order authority."""

from copy import deepcopy
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.options.engine import clock, fingerprint
from app.options.lifecycle import EntryTimeProtection
from app.options.models import Name, OptionAdmission, OptionProposal, OptionRecord
from app.options.scope import ScopePreflightInput
from app.options.scope_admission import ScopeEntryPathReview
from app.options.scope_contract import ScopeContractScan
from app.options.scope_management import ScopeManagementReview

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
LOCKED = (
    "play_key",
    "session_date",
    "called_at",
    "choice",
    "geometry",
    "locked_frame",
    "locked_context",
    "locked_scan",
    "locked_quality_scan",
    "locked_contract_scan",
)


class ScopeEntryBinding(OptionRecord):
    version: Literal["scope-entry-binding-v1"] = "scope-entry-binding-v1"
    family: Literal["SCOPE"] = "SCOPE"
    population_id: Name
    account_id: Name
    play_key: Name
    original_call_hash: Digest
    policy_hash: Digest
    owner_hash: Digest
    action_key: Name
    request_hash: Digest
    revision: int = Field(strict=True, ge=1)
    record_hash: Digest
    evaluated_at: datetime
    valid_until: datetime
    authority: Literal[False] = False
    live_enabled: Literal[False] = False


def _record_hash(record):
    raw = deepcopy(record)
    raw.pop("entry_binding", None)
    return fingerprint(raw)


def _original(db, record, read_json):
    """The call key is the play key; latest action alone cannot rewrite its geometry."""
    row = db.execute(
        "SELECT result_json FROM execution_option_scope_watch_actions WHERE action_key=?",
        (record["play_key"],),
    ).fetchone()
    if row is None:
        raise ValueError("SCOPE_ENTRY_ORIGINAL_CALL_REQUIRED")
    receipt = read_json(row[0])
    original = receipt["record"]
    event = db.execute(
        "SELECT kind,payload FROM execution_events WHERE sequence=?", (receipt["revision"],)
    ).fetchone()
    if (
        event is None
        or event["kind"] != "SCOPE_WATCH_ACTION"
        or fingerprint(read_json(event["payload"]))
        != fingerprint({"action_key": record["play_key"], "record": original})
        or receipt.get("authority") is not False
        or receipt.get("live_enabled") is not False
        or original["status"] != "WATCHING"
        or "admission_review" in original
        or any(original.get(k) != record.get(k) for k in LOCKED)
    ):
        raise ValueError("SCOPE_ENTRY_ORIGINAL_CALL_CHANGED")
    return fingerprint(receipt)


def _terms(record, policy, owner_policy, limits):
    """Check stored cross-bindings without refreshing evidence or recomputing signals."""
    if policy.entry_binding is None:
        raise ValueError("SCOPE_ENTRY_BINDING_NOT_ENROLLED")
    r = record["admission_review"]
    a = record["arming"]
    admission = OptionAdmission.model_validate(r["admission"])
    proposal = OptionProposal.model_validate(r["proposal"])
    frame = ScopePreflightInput.model_validate(a["frame"])
    locked = ScopePreflightInput.model_validate(record["locked_frame"])
    plan = ScopeManagementReview.model_validate(r["management"])
    scan = ScopeContractScan.model_validate(a["contract_scan"])
    path = ScopeEntryPathReview.model_validate(r["entry_path"])
    selected = [
        o for o in scan.observations if all(getattr(o, k) == v for k, v in record["choice"].items())
    ]
    if (
        record["status"] != "WATCHING"
        or a["status"] != "ARMED"
        or not r["eligible"]
        or r["reasons"]
        or admission.outcome != "APPROVED"
        or admission.action != "OPEN_LONG"
        or proposal.action != "OPEN_LONG"
        or frame.metadata.instrument != locked.metadata.instrument
        or frame.quote.instrument != locked.metadata.instrument
        or proposal.contract != locked.metadata.instrument.contract
        or proposal.underlying_invalidation != plan.geometry.invalidation
        or proposal.max_entry_debit != policy.admission.max_entry_debit
        or admission.contract_id != proposal.contract.contract_id
        or clock(datetime.fromisoformat(r["evaluated_at"])) != admission.approved_at
        or clock(datetime.fromisoformat(a["evaluated_at"])) != admission.approved_at
        or admission.valid_until is None
        or not admission.approved_at
        < admission.valid_until
        <= datetime.fromisoformat(a["valid_until"])
        or plan.admission_hash != fingerprint(admission)
        or plan.contract_scan_hash != fingerprint(scan)
        or len(selected) != 1
        or plan.contract_observation != selected[0]
        or scan.issues
        or scan.evaluated_at != admission.approved_at
        or plan.policy != policy.management
        or plan.geometry.model_dump(mode="json") != record["geometry"]
        or plan.owner_maximum_loss_fraction != owner_policy.premium_catastrophe_fraction
        or plan.admitted_quantity != admission.quantity
        or plan.contract_id != admission.contract_id
        or plan.evaluated_at != admission.approved_at
        or plan.valid_until != admission.valid_until
        or path.geometry != plan.geometry
        or not path.passed
        or path.reasons
        or r["limits"] != limits.model_dump(mode="json")
        or r["authority"] is not False
        or r["live_enabled"] is not False
    ):
        raise ValueError("SCOPE_ENTRY_TERMS_CHANGED")
    return frame, proposal, admission, plan


def build_binding(
    db, record, policy, owner_policy, limits, action_key, request_hash, revision, read_json
):
    _, _, admission, _ = _terms(record, policy, owner_policy, limits)
    return ScopeEntryBinding(
        population_id=limits.population_id,
        account_id=limits.account_id,
        play_key=record["play_key"],
        original_call_hash=_original(db, record, read_json),
        policy_hash=fingerprint(policy),
        owner_hash=fingerprint({"limits": limits, "policy": owner_policy}),
        action_key=action_key,
        request_hash=request_hash,
        revision=revision,
        record_hash=_record_hash(record),
        evaluated_at=admission.approved_at,
        valid_until=admission.valid_until,
    )


def verify_binding(db, record, policy, owner_policy, limits, audit, read_json):
    binding = ScopeEntryBinding.model_validate(record["entry_binding"])
    receipt = db.execute(
        "SELECT request_hash FROM execution_option_scope_watch_actions WHERE action_key=?",
        (audit["action_key"],),
    ).fetchone()
    if (
        receipt is None
        or binding
        != build_binding(
            db,
            record,
            policy,
            owner_policy,
            limits,
            audit["action_key"],
            receipt[0],
            audit["sequence"],
            read_json,
        )
        or clock(datetime.fromisoformat(audit["recorded_at"])) != binding.evaluated_at
    ):
        raise ValueError("SCOPE_ENTRY_BINDING_CHANGED")
    return binding


def select_entry(engine, db, policy, play_key, expected_revision, now):
    """Read one exact latest bound admission inside the caller's journal transaction.

    A later native dispatcher must still refresh all evidence, account and risk
    gates. This packet has no intent/client ID and cannot bypass the Scope guard.
    """
    from app.execution.engine import ExecutionBlocked
    from app.options.observer import _json
    from app.options.scope_observer import _watch, stored_policy

    now = clock(now)
    engine._control(db)
    if type(expected_revision) is not int or engine.journal.revision(db) != expected_revision:
        raise ExecutionBlocked("SCOPE_ENTRY_REVISION_CHANGED")
    stored = stored_policy(db, engine.limits, _json)
    if stored != policy:
        raise ExecutionBlocked("FROZEN_SCOPE_WATCH_POLICY_MISMATCH")
    row = db.execute(
        "SELECT * FROM execution_option_scope_watches WHERE play_key=?", (play_key,)
    ).fetchone()
    if row is None:
        raise ExecutionBlocked("SCOPE_WATCH_NOT_ACTIVE")
    record = _json(row["record_json"])
    view = _watch(db, row, policy, now, _json, engine.policy, engine.limits)
    if not view["active_record"] or "entry_binding" not in record:
        raise ExecutionBlocked("SCOPE_ENTRY_BOUND_ADMISSION_REQUIRED")
    binding = ScopeEntryBinding.model_validate(record["entry_binding"])
    if binding.revision != expected_revision:
        raise ExecutionBlocked("SCOPE_ENTRY_FRESH_ADMISSION_REQUIRED")
    if not binding.evaluated_at <= now < binding.valid_until:
        raise ExecutionBlocked("SCOPE_ENTRY_ADMISSION_EXPIRED")
    frame, proposal, admission, plan = _terms(record, policy, engine.policy, engine.limits)
    reasons = ["SCOPE_COMPLETE_PATH_UNPROVEN", "SCOPE_NATIVE_EXECUTION_NOT_ENROLLED"]
    reasons.extend(plan.reasons)
    return {
        "binding": binding.model_dump(mode="json"),
        "binding_hash": fingerprint(binding),
        "choice": record["choice"],
        "geometry": record["geometry"],
        "instrument": frame.metadata.instrument.model_dump(mode="json"),
        "quote": frame.quote.model_dump(mode="json"),
        "underlying": record["admission_review"]["underlying"],
        "proposal": proposal.model_dump(mode="json"),
        "admission": admission.model_dump(mode="json"),
        "management": plan.model_dump(mode="json"),
        "entry_time_protection": EntryTimeProtection(
            exit_by=ScopePreflightInput.model_validate(record["locked_frame"]).session.protect_at
        ).model_dump(mode="json"),
        "account": record["admission_review"]["account"],
        "effective_limits": record["admission_review"]["effective_limits"],
        "session": record["admission_review"]["session"],
        "execution_blockers": reasons,
        "authority": False,
        "live_enabled": False,
    }
