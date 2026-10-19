"""Read-only, audit-bound native risk evidence for independent session exports."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import clock, fingerprint
from app.options.entry_reasoning import Digest
from app.options.lifecycle import EntryLineage
from app.options.loss_control import LossState, stored_state
from app.options.models import Money, Name, OptionRecord


class ConsumedLossEvidence(OptionRecord):
    entry_client_id: Name
    outcome_hash: Digest
    outcome: Literal["WIN", "FLAT", "LOSS"]
    closed_at: datetime
    recognized_at: datetime
    revision: int = Field(ge=1, strict=True)
    net_after_known_execution_and_model_costs: Money
    execution_fees: Money = Field(ge=0)
    known_model_cost: Money = Field(ge=0)
    entry_lineage: EntryLineage | None = Field(default=None, exclude_if=lambda v: v is None)


class EntryRiskPause(OptionRecord):
    source_key: Name
    input_hash: Digest
    reasons: tuple[Name, ...] = Field(min_length=1, max_length=100)
    occurred_at: datetime
    revision: int = Field(ge=1, strict=True)


class LossResetEvidence(OptionRecord):
    command_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    loss_family: Literal["DEGEN", "SWING", "SCOPE"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    occurred_at: datetime
    revision: int = Field(ge=1, strict=True)


class LossControlEvidence(OptionRecord):
    version: Literal["native-loss-evidence-v1"] = "native-loss-evidence-v1"
    policy_hash: Digest
    state: LossState
    consumed: tuple[ConsumedLossEvidence, ...] = Field(max_length=200)
    entry_pauses: tuple[EntryRiskPause, ...] = Field(max_length=6000)
    resets: tuple[LossResetEvidence, ...] = Field(max_length=1000)
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self):
        if (
            len({r.entry_client_id for r in self.consumed}) != len(self.consumed)
            or len(self.consumed) != self.state.consumed_entries
        ):
            raise ValueError("Native loss evidence count mismatch")
        if any(
            r.closed_at > r.recognized_at or r.recognized_at > self.state.last_checked_at
            for r in self.consumed
        ):
            raise ValueError("Native loss evidence time mismatch")
        if any(
            r.occurred_at > self.state.last_checked_at for r in (*self.entry_pauses, *self.resets)
        ):
            raise ValueError("Native risk event after last review")
        for r in self.consumed:
            net = r.net_after_known_execution_and_model_costs
            if r.outcome != ("WIN" if net > 0 else "LOSS" if net < 0 else "FLAT"):
                raise ValueError("Native loss outcome sign mismatch")
        for family in self.state.families:
            if family.consumed_entries != sum(
                r.entry_lineage is not None and r.entry_lineage.family == family.family
                for r in self.consumed
            ):
                raise ValueError("Native family consumed count mismatch")
        return self


def export_loss_control(db, policy, population_id, events, *, boundary):
    """Verify stored state and consumed economics; never refresh or attach an owner.

    Audit consistency is not independent signature verification or replay of every
    historical risk decision. The last review time remains explicit.
    """
    from app.options.loss_control import outcome_record
    from app.options.observer import _json
    from app.options.position_outcome import native_position_outcome

    view = stored_state(db)
    if policy is None:
        if view is not None:
            raise ValueError("Unexpected native loss enrollment")
        return None
    if view is None or view["policy"] != policy.model_dump(mode="json"):
        raise ValueError("Native loss policy binding mismatch")
    state = LossState.model_validate({k: view[k] for k in LossState.model_fields if k in view})
    enrolled = [e for e in events if e["kind"] == "NATIVE_LOSS_CONTROL_ENROLLED"]
    if len(enrolled) != 1 or _json(enrolled[0]["payload"]) != policy.model_dump(mode="json"):
        raise ValueError("Native loss enrollment audit mismatch")
    if clock(state.last_checked_at) > boundary:
        raise ValueError("Native loss review after export boundary")
    admissions, commands = {}, {}
    for event in events:
        if event["kind"] == "OPTION_MODEL_ATTEMPT_ADMITTED":
            key = _json(event["payload"])["source_key"]
            admissions[key] = min(admissions.get(key, event["sequence"]), event["sequence"])
        elif event["kind"] == "OPTIONS_OPERATOR_COMMAND":
            key = _json(event["payload"])["command"]["command_id"]
            commands.setdefault(key, []).append(event)
    latest = None
    consumed_events, pauses, resets = {}, [], []
    for e in events:
        kind = e["kind"]
        if kind not in {
            "NATIVE_LOSS_OUTCOME_CONSUMED",
            "NATIVE_LOSS_CONTROL_REVIEWED",
            "NATIVE_LOSS_REVIEWED_RESET",
            "OPTION_ENTRY_MODEL_RISK_PAUSED",
        }:
            continue
        at = clock(datetime.fromisoformat(e["occurred_at"]))
        if e["sequence"] <= enrolled[0]["sequence"] or at > boundary:
            raise ValueError("Native loss event outside enrollment/boundary")
        p = _json(e["payload"])
        if kind == "NATIVE_LOSS_OUTCOME_CONSUMED":
            key = p["entry_client_id"]
            if key in consumed_events:
                raise ValueError("Duplicate native loss consumption")
            consumed_events[key] = (e, p)
        elif kind in {"NATIVE_LOSS_CONTROL_REVIEWED", "NATIVE_LOSS_REVIEWED_RESET"}:
            latest = LossState.model_validate(
                p if kind == "NATIVE_LOSS_CONTROL_REVIEWED" else p["state"]
            )
            if clock(latest.last_checked_at) != at:
                raise ValueError("Native loss review clock mismatch")
            if kind == "NATIVE_LOSS_REVIEWED_RESET":
                if p["population_id"] != population_id:
                    raise ValueError("Native loss reset population mismatch")
                matching = commands.get(p["command_id"], [])
                if len(matching) != 1:
                    raise ValueError("Native loss reset command audit missing")
                command_event = matching[0]
                operator = _json(command_event["payload"])
                command, result = operator["command"], operator["result"]
                receipt = db.execute(
                    "SELECT result_json FROM execution_commands WHERE command_id=?",
                    (p["command_id"],),
                ).fetchone()
                if (
                    command_event["sequence"] != e["sequence"] + 1
                    or command_event["occurred_at"] != e["occurred_at"]
                    or command["action"] != "RESET_LOSS_LOCK"
                    or command["population_id"] != population_id
                    or command.get("loss_family") != p.get("loss_family")
                    or command["expected_revision"] != p["expected_revision"]
                    or result["status"] != "APPLIED"
                    or result.get("loss_family") != p.get("loss_family")
                    or receipt is None
                    or _json(receipt[0]) != result | {"revision": command_event["sequence"]}
                ):
                    raise ValueError("Native loss reset receipt mismatch")
                resets.append(
                    LossResetEvidence(
                        command_id=p["command_id"],
                        loss_family=p.get("loss_family"),
                        occurred_at=at,
                        revision=e["sequence"],
                    )
                )
        else:
            if admissions.get(p["source_key"], e["sequence"] + 1) <= e["sequence"]:
                raise ValueError("Native entry pause follows admitted model attempt")
            pauses.append(EntryRiskPause(**p, occurred_at=at, revision=e["sequence"]))
    if latest is None:
        from app.options.loss_control import FamilyLossState

        latest = LossState(
            consecutive_losses=0,
            locked=False,
            last_checked_at=datetime.fromisoformat(enrolled[0]["occurred_at"]),
            consumed_entries=0,
            families=tuple(
                FamilyLossState(
                    family=f.family, consecutive_losses=0, locked=False, consumed_entries=0
                )
                for f in policy.families
            ),
        )
    if latest != state:
        raise ValueError("Native loss state audit mismatch")
    rows = db.execute(
        "SELECT * FROM execution_option_loss_outcomes ORDER BY rowid LIMIT 201"
    ).fetchall()
    if len(rows) > 200 or {r["entry_client_id"] for r in rows} != set(consumed_events):
        raise ValueError("Native loss consumption audit mismatch")
    consumed = []
    for row in rows:
        key = row["entry_client_id"]
        e, p = consumed_events[key]
        outcome = native_position_outcome(db, key, population_id)
        if outcome["status"] != "COMPLETE":
            raise ValueError("Consumed native loss outcome is incomplete")
        record = outcome_record(outcome, policy)
        digest = fingerprint(record)
        if (
            record["entry_client_id"] != key
            or row["outcome_hash"] != digest
            or fingerprint(_json(row["record_json"])) != digest
            or p != {"entry_client_id": key, "outcome_hash": digest, "outcome": record["outcome"]}
        ):
            raise ValueError("Native consumed loss economics mismatch")
        consumed.append(
            ConsumedLossEvidence(
                entry_client_id=key,
                outcome_hash=digest,
                outcome=record["outcome"],
                closed_at=record["closed_at"],
                recognized_at=e["occurred_at"],
                revision=e["sequence"],
                net_after_known_execution_and_model_costs=record[
                    "net_after_known_execution_and_model_costs"
                ],
                execution_fees=record["execution_fees"],
                known_model_cost=record["known_model_cost"],
                entry_lineage=record.get("entry_lineage"),
            )
        )
    return LossControlEvidence(
        policy_hash=fingerprint(policy),
        state=state,
        consumed=tuple(consumed),
        entry_pauses=tuple(pauses),
        resets=tuple(resets),
    )


def validate_loss_boundary(value, policy, boundary, previous=None):
    """Validate portable structure/continuity, without treating it as execution proof."""
    if (value is None) != (policy is None):
        raise ValueError("LOSS_CONTROL_EVIDENCE_ENROLLMENT_MISMATCH")
    if value is None:
        return
    if value.policy_hash != fingerprint(policy):
        raise ValueError("LOSS_CONTROL_POLICY_MISMATCH")
    if value.state.last_checked_at > boundary:
        raise ValueError("LOSS_CONTROL_REVIEW_AFTER_BOUNDARY")
    if tuple(s.family for s in value.state.families) != tuple(
        p.family for p in policy.families
    ) or (policy.families and any(r.entry_lineage is None for r in value.consumed)):
        raise ValueError("LOSS_CONTROL_FAMILY_BINDING_MISMATCH")
    if previous is not None and (
        value.state.last_checked_at < previous.state.last_checked_at
        or any(
            getattr(value, k)[: len(getattr(previous, k))] != getattr(previous, k)
            for k in ("consumed", "entry_pauses", "resets")
        )
    ):
        raise ValueError("LOSS_CONTROL_HISTORY_CHANGED")
