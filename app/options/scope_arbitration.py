"""Frozen deterministic Scope/Degen/Swing selection in one native PAPER owner."""

import json
from typing import Literal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.models import Name, OptionRecord, UnderlyingQuote
from app.options.scope import ScopePreflightInput
from app.options.scope_context import ScopeContextInput
from app.options.scope_watch import ScopeWatchPolicy
from app.options.swing_base_models import SWING_FAMILIES

VERSION = "shared-scope-selection-v1"


class SharedScopePolicy(OptionRecord):
    version: Literal["shared-scope-selection-v1", "shared-scope-entry-v1"] = VERSION
    scope_carry: Literal["shared-scope-carry-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    watch: ScopeWatchPolicy
    family_priority: tuple[Literal["DEGEN", "SWING", "SCOPE"], ...] = Field(
        min_length=2, max_length=3
    )

    @model_validator(mode="after")
    def bounded(self):
        if (
            (self.scope_carry is not None and "SWING" not in self.family_priority)
            or len(set(self.family_priority)) != len(self.family_priority)
            or not {"DEGEN", "SCOPE"} <= set(self.family_priority)
            or self.watch.native_execution != "scope-native-v1"
        ):
            raise ValueError("Explicit unique family priority and native Scope watch required")
        return self


class ScopeCycleInput(OptionRecord):
    play_key: Name
    frame: ScopePreflightInput
    context: ScopeContextInput
    underlying: UnderlyingQuote


def configuration(db):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_strategy'"
    ).fetchone():
        raise ExecutionBlocked("SHARED_SCOPE_COORDINATOR_REQUIRED")
    row = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
    config = json.loads(row[0]) if row else {}
    if "scope" not in config:
        raise ExecutionBlocked("SHARED_SCOPE_COORDINATOR_REQUIRED")
    policy = SharedScopePolicy.model_validate(config["scope"])
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_scope_watch_policy'"
    ).fetchone():
        raise ExecutionBlocked("SHARED_SCOPE_WATCH_REQUIRED")
    watch = db.execute(
        "SELECT config_json FROM execution_option_scope_watch_policy WHERE id=1"
    ).fetchone()
    if watch is None or ScopeWatchPolicy.model_validate_json(watch[0]) != policy.watch:
        raise ExecutionBlocked("SHARED_SCOPE_WATCH_POLICY_CHANGED")
    if policy.version == VERSION and any(
        k in config
        for k in ("entry_model", "model", "replay_model", "position_model", "scope_replay")
    ):
        raise ExecutionBlocked("SHARED_SCOPE_DETERMINISTIC_ONLY")
    if policy.version != VERSION:
        from app.options.entry_judgment import EntryModelConfiguration

        model = EntryModelConfiguration.model_validate(config.get("entry_model"))
        if model.entry_policy.scope_selection is None:
            raise ExecutionBlocked("SHARED_SCOPE_AI_CONFIGURATION_REQUIRED")
        if "scope_replay" in config:
            from app.options.scope_replay_enrollment import validate_stored

            replay_enrollment = validate_stored(config)
        elif (
            "replay_model" in config
            or model.entry_policy.scope_selection == "scope-fixed-shortlist-v1"
        ):
            raise ExecutionBlocked("SHARED_SCOPE_AI_CONFIGURATION_REQUIRED")
        if "position_model" in config:
            from app.options.position_judgment import PositionModelConfiguration

            management = PositionModelConfiguration.model_validate(config["position_model"])
            if management.position_policy.scope_management != "scope-fixed-position-v1":
                raise ExecutionBlocked("SHARED_SCOPE_POSITION_CONFIGURATION_REQUIRED")
    from app.options.lifecycle import OptionExecutionPolicy
    from app.options.scope_carry import validate_enrollment
    from app.options.swing import SwingPolicy

    owner = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    validate_enrollment(
        OptionExecutionPolicy.model_validate(owner["policy"]),
        policy,
        SwingPolicy.model_validate(config["swing"]) if "swing" in config else None,
        model.entry_policy if policy.version != VERSION else None,
        management.position_policy if "position_model" in config else None,
        replay="scope_replay" in config or "replay_model" in config,
        replay_enrollment=replay_enrollment if "scope_replay" in config else None,
    )
    return policy


def family(candidate):
    return "SWING" if candidate["family"] in SWING_FAMILIES else "DEGEN"


def selection(policy, key, evidence):
    from app.options.selection import parse_candidate

    if not isinstance(evidence["candidates"], list) or len(evidence["candidates"]) > 24:
        raise ValueError("Shared candidate capacity exceeded")
    choices = []
    for value in evidence["candidates"]:
        c = parse_candidate(value)
        if c.admission.outcome != "APPROVED":
            raise ValueError("Shared choice requires admitted candidates")
        choices.append(
            {
                "family": family(value),
                "candidate_id": c.candidate_id,
                "candidate_hash": fingerprint(c),
                "source_key": key,
            }
        )
    packet = evidence.get("scope_candidate")
    if packet is not None:
        from app.options.scope_execution import lineage

        label = lineage(packet)
        if packet["execution_blockers"]:
            raise ValueError("Blocked Scope plan cannot enter arbitration")
        choices.append(
            {
                "family": "SCOPE",
                "candidate_id": label.candidate_id,
                "candidate_hash": fingerprint(packet),
                "source_key": label.opportunity_key,
            }
        )
    if any(c["family"] not in policy.family_priority for c in choices):
        raise ValueError("Unenrolled shared family")
    if len({(c["family"], c["candidate_id"]) for c in choices}) != len(choices):
        raise ValueError("Duplicate shared choice")
    choices.sort(key=lambda c: policy.family_priority.index(c["family"]))
    selected = choices[0] if choices else None
    extra = {}
    if policy.version != VERSION:
        selected = None
        plan = evidence.get("entry_result", {}).get("plan", {})
        if plan.get("action") == "ENTER" and not plan.get("stock", False):
            matches = [
                x
                for x in choices
                if (
                    x["family"] == "SCOPE"
                    and plan.get("scope") is True
                    and x["candidate_hash"] == plan.get("candidate_id")
                )
                or (
                    x["family"] != "SCOPE"
                    and plan.get("scope") is False
                    and x["candidate_id"] == plan.get("candidate_id")
                )
            ]
            if len(matches) != 1:
                raise ValueError("SHARED_SCOPE_MODEL_SELECTION_REQUIRED")
            selected = matches[0]
            source = selected["source_key"]
            if selected["family"] == "SCOPE" and evidence.get("scope_fresh_candidate"):
                from app.options.scope_execution import lineage

                source = lineage(evidence["scope_fresh_candidate"]).opportunity_key
            extra["execution_source_key"] = source
            extra["model_valid_until"] = evidence["entry_request"]["packet"]["valid_until"]
    return {
        **extra,
        "version": policy.version,
        "cycle_key": key,
        "policy_hash": fingerprint(policy),
        "choices": choices,
        "selected": selected,
    }


def verify_scope_candidate(db, evidence, policy):
    """Retain alternatives against their original action, including after a later watch mutation."""
    from app.options.lifecycle import OptionExecutionPolicy
    from app.options.models import OptionLimits
    from app.options.scope_entry import packet_from_record, verify_binding

    packet = evidence.get("scope_candidate")
    if packet is None:
        return
    binding = packet["binding"]
    row = db.execute(
        "SELECT result_json FROM execution_option_scope_watch_actions WHERE action_key=?",
        (binding["action_key"],),
    ).fetchone()
    event = db.execute(
        "SELECT kind,occurred_at,payload FROM execution_events WHERE sequence=?",
        (binding["revision"],),
    ).fetchone()
    if row is None or event is None or event["kind"] != "SCOPE_WATCH_ACTION":
        raise ValueError("SHARED_SCOPE_ALTERNATIVE_ACTION_REQUIRED")
    receipt = json.loads(row[0])
    record = receipt["record"]
    if (
        receipt["revision"] != binding["revision"]
        or json.loads(event["payload"]) != {"action_key": binding["action_key"], "record": record}
        or fingerprint(record) != evidence["scope_review"]["record_hash"]
    ):
        raise ValueError("SHARED_SCOPE_ALTERNATIVE_CHANGED")
    config = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    owner, limits = (
        OptionExecutionPolicy.model_validate(config["policy"]),
        OptionLimits.model_validate(config["limits"]),
    )
    verify_binding(
        db,
        record,
        policy.watch,
        owner,
        limits,
        {
            "action_key": binding["action_key"],
            "sequence": binding["revision"],
            "recorded_at": event["occurred_at"],
        },
        json.loads,
    )
    if packet != packet_from_record(record, policy.watch, owner, limits):
        raise ValueError("SHARED_SCOPE_ALTERNATIVE_TERMS_CHANGED")


def review_entry(engine, db, source_key, proposal, quote, inputs, now):
    """No other entry route is available to an enrolled shared owner."""
    if proposal.action != "OPEN_LONG" or engine.policy.scope_arbitration is None:
        return None
    policy = configuration(db)
    request = inputs.get("scope_entry") or {}
    key = request.get("arbitration_cycle") or source_key
    if key != "degen:" + str(int(now.timestamp()) // 300):
        raise ExecutionBlocked("SHARED_SCOPE_CURRENT_CYCLE_REQUIRED")
    row = db.execute(
        "SELECT status,result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    if row is None or row["status"] != "STARTED" or not row["result_json"]:
        raise ExecutionBlocked("SHARED_SCOPE_SELECTED_CYCLE_REQUIRED")
    evidence = json.loads(row["result_json"])
    verify_scope_candidate(db, evidence, policy)
    receipt = selection(policy, key, evidence)
    chosen = receipt["selected"]
    if receipt != evidence.get("scope_arbitration") or chosen is None:
        raise ExecutionBlocked("SHARED_SCOPE_SELECTION_CHANGED")
    ai = policy.version != VERSION
    if ai:
        from app.options.scope_ai import validate_stored

        validate_stored(db, key, evidence, policy)
    expected_origin = "MODEL" if ai and chosen["family"] != "SCOPE" else "DETERMINISTIC"
    if (
        source_key != receipt.get("execution_source_key", chosen["source_key"])
        or inputs["origin"] != expected_origin
    ):
        raise ExecutionBlocked("SHARED_SCOPE_SELECTED_SOURCE_REQUIRED")
    if chosen["family"] == "SCOPE":
        packet = evidence["scope_fresh_candidate" if ai else "scope_candidate"]
        if (
            request.get("arbitration_cycle") != key
            or request.get("play_key") != chosen["candidate_id"]
            or packet["proposal"] != proposal.model_dump(mode="json")
            or quote is None
            or packet["instrument"] != quote.instrument.model_dump(mode="json")
        ):
            raise ExecutionBlocked("SHARED_SCOPE_SELECTED_PLAN_REQUIRED")
    else:
        matches = [c for c in evidence["candidates"] if c["candidate_id"] == chosen["candidate_id"]]
        if (
            request
            or evidence.get("candidate_id") != chosen["candidate_id"]
            or len(matches) != 1
            or (not ai and matches[0]["proposal"] != proposal.model_dump(mode="json"))
            or quote is None
            or matches[0]["instrument"] != quote.instrument.model_dump(mode="json")
        ):
            raise ExecutionBlocked("SHARED_SCOPE_SELECTED_PLAN_REQUIRED")
    return receipt


def verify_entry(db, intent, approval):
    if intent.side != "BUY":
        return
    from app.options.lifecycle import OptionExecutionPolicy

    owner = OptionExecutionPolicy.model_validate(
        json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )["policy"]
    )
    receipt = approval.get("scope_arbitration")
    if owner.scope_arbitration is None:
        if receipt is not None:
            raise ValueError("SHARED_SCOPE_NOT_ENROLLED")
        return
    policy = configuration(db)
    if (
        not receipt
        or receipt.get("execution_source_key", receipt["selected"]["source_key"])
        != intent.source_key
    ):
        raise ValueError("SHARED_SCOPE_RECEIPT_REQUIRED")
    key = receipt["cycle_key"]
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    data = json.loads(row[0]) if row and row[0] else {}
    verify_scope_candidate(db, data, policy)
    if policy.version != VERSION:
        from app.options.scope_ai import verify_paid_entry

        verify_paid_entry(db, intent, approval, data, policy)
    events = db.execute(
        "SELECT payload FROM execution_events WHERE kind='SHARED_SCOPE_ENTRY_SELECTED' AND client_id=?",
        (intent.client_id,),
    ).fetchall()
    original = db.execute(
        "SELECT inputs_json FROM execution_option_decisions WHERE source_key=?",
        (intent.source_key,),
    ).fetchone()
    if (
        receipt != selection(policy, key, data)
        or data.get("scope_arbitration") != receipt
        or original is None
        or json.loads(original[0]).get("scope_arbitration") != receipt
        or len(events) != 1
        or json.loads(events[0][0]) != receipt
        or intent.entry_lineage is None
        or intent.entry_lineage.family != receipt["selected"]["family"]
        or intent.entry_lineage.candidate_id != receipt["selected"]["candidate_id"]
    ):
        raise ValueError("SHARED_SCOPE_RECEIPT_CHANGED")


def collect(c, key, frame, evidence):
    """Refresh Scope's owned admission after reconciliation; no event follows before prepare."""
    with c.engine.journal.read() as db:
        rows = db.execute(
            "SELECT play_key,record_json FROM execution_option_scope_watches WHERE active_lock=1"
        ).fetchall()
        revision = c.engine.journal.revision(db)
    if len(rows) > 1:
        raise ValueError("Shared owner has multiple Scope watches")
    if rows and (frame.scope is None or rows[0]["play_key"] != frame.scope.play_key):
        raise ExecutionBlocked("EXACT_SCOPE_WATCH_COVERAGE_REQUIRED")
    if not rows and frame.scope is not None:
        raise ExecutionBlocked("SCOPE_WATCH_NOT_ACTIVE")
    evidence["scope_candidate"] = None
    if rows:
        item = frame.scope
        result = c.scope_book.review_admission(
            "shared:" + key,
            item.play_key,
            expected_revision=revision,
            now=c.now(),
            frame=item.frame,
            context=item.context,
            underlying=item.underlying,
        )
        evidence["scope_review"] = {
            "action_key": "shared:" + key,
            "revision": result["revision"],
            "play_key": item.play_key,
            "record_hash": fingerprint(result["record"]),
            "status": result["record"]["status"],
            "admission_review": result["record"]["admission_review"],
        }
        review = result["record"]["admission_review"]
        if review["eligible"] and review["management"] and review["management"]["passed"]:
            packet = c.scope_book.entry_selection(
                item.play_key, expected_revision=result["revision"], now=c.now()
            )
            if not packet["execution_blockers"]:
                evidence["scope_candidate"] = packet
    evidence["scope_arbitration"] = selection(c.scope_policy, key, evidence)
    selected = evidence["scope_arbitration"]["selected"]
    if selected and selected["family"] != "SCOPE":
        evidence["candidate_id"] = selected["candidate_id"]
    c._pending_evidence(key, evidence)
    return selected


async def execute_scope(c, key, frame, evidence):
    packet = evidence.get("scope_fresh_candidate") or evidence["scope_candidate"]
    prepared = c.scope_book.prepare_entry(
        frame.scope.play_key,
        expected_revision=packet["binding"]["revision"],
        now=c.now(),
        arbitration_cycle=key,
    )
    if prepared["status"] != "PREPARED":
        return c._finish(
            key,
            {
                **evidence,
                "status": "HOLD",
                "reason": "FRESH_EXECUTION_ADMISSION_REJECTED",
                "prepared": prepared,
            },
        )
    status = await c.engine.dispatch(
        prepared["client_id"], frame.scope.frame.quote, frame.scope.underlying, now=c.now()
    )
    return c._finish(
        key,
        {
            **evidence,
            "status": status,
            "client_id": prepared["client_id"],
            "selected_family": "SCOPE",
            "prepared": prepared,
        },
    )
