"""Read-only decision lineage. Proposals, approvals, attempts and fills stay distinct."""

from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.options.engine import exact, fingerprint
from app.options.entry_reasoning import Digest
from app.options.lifecycle import (
    EntryLineage,
    EntryPremiumProtection,
    OptionFill,
    OptionIntent,
    OptionObservation,
    TargetExitSchedule,
)
from app.options.models import Money, Name, OptionProposal, OptionRecord, PositiveCount


class DecisionAttribution(OptionRecord):
    health_management: Literal["observed-daytrade-health-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    trade_floor: Literal["native-target-floor-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    premium_trail: Literal["executable-premium-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    entry_lineage: EntryLineage | None = Field(default=None, exclude_if=lambda v: v is None)
    execution_authority: Literal[False] = False
    role: Literal["DETERMINISTIC", "SELECTION", "ENTRY", "MANAGEMENT"]
    source_key: Name
    packet_hash: Digest | None = None
    proposal_hash: Digest | None = None
    proposal_action: str | None = Field(default=None, max_length=32)
    thesis: str | None = Field(default=None, max_length=2000)
    requested_invalidation: Money | None = None
    applied_invalidation: Money | None = None
    requested_target: Money | None = None
    horizon_seconds: int | None = None
    change_since_entry: str | None = Field(default=None, max_length=500)
    uncertainty: str | None = Field(default=None, max_length=500)
    review_reasons: tuple[Name, ...] = Field(default=(), max_length=100)
    entry_client_id: Name | None = None
    position_revision: int | None = Field(default=None, ge=1)
    review_outcome: str | None = Field(default=None, max_length=64)
    application_status: str | None = Field(default=None, max_length=64)
    model_attempted: bool = False
    model_cost: Money | None = Field(default=None, ge=0)
    cost_status: Literal["NOT_CALLED", "UNKNOWN", "CONFIGURED_ESTIMATE"]
    client_id: Name | None = None
    approved_quantity: int | None = Field(default=None, ge=1)
    requested_close_quantity: PositiveCount | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    target_exit_schedule: TargetExitSchedule | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    entry_premium_protection: EntryPremiumProtection | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    target_exit_stage: int | None = Field(
        default=None, strict=True, ge=1, le=3, exclude_if=lambda v: v is None
    )
    order_status: str | None = Field(default=None, max_length=32)
    attempted: bool = False
    fill_ids: tuple[Name, ...] = Field(default=(), max_length=1000)
    filled_quantity: int = Field(default=0, ge=0)


def order_attribution(db, row):
    """Project only observed fills with exact fill-table linkage; never infer execution."""
    from app.options.observer import _json

    intent = OptionIntent.model_validate(_json(row["intent_json"]))
    approval = _json(row["approval_json"])
    from app.options.entry_lineage import entry_lineage, verified_lineage

    lineage = verified_lineage(db, intent, approval)
    obs = (
        OptionObservation.model_validate(_json(row["observation_json"]))
        if row["observation_json"]
        else None
    )
    if intent.client_id != row["client_id"] or intent.source_key != row["source_key"]:
        raise ValueError("Stored attribution order identity mismatch")
    if obs and (
        any(
            getattr(obs, k) != getattr(intent, k)
            for k in ("client_id", "instrument", "side", "quantity", "limit_price")
        )
        or obs.order_id != row["order_id"]
        or obs.status != row["status"]
        or row["attempted_at"] is None
    ):
        raise ValueError("Stored attribution observation mismatch")
    fills = tuple(obs.fills) if obs else ()
    stored = db.execute(
        "SELECT fill_id,payload FROM execution_fills WHERE client_id=? LIMIT 1001",
        (intent.client_id,),
    ).fetchall()
    if len(stored) > 1000 or {r[0]: OptionFill.model_validate(_json(r[1])) for r in stored} != {
        f.fill_id: f for f in fills
    }:
        raise ValueError("Stored attribution fill coverage mismatch")
    if (intent.position_protection is not None) != (approval.get("origin") == "POSITION_MODEL"):
        raise ValueError("Stored managed order origin mismatch")
    if approval["admission"]["quantity"] != intent.quantity:
        raise ValueError("Stored approval quantity mismatch")
    proposal = OptionProposal.model_validate(approval["proposal"])
    from app.options.target_exits import verify_binding

    verify_binding(intent, approval)
    from app.options.protection import verify_premium_binding

    verify_premium_binding(intent, approval)
    from app.options.premium_trail import verify_binding as verify_trail

    verify_trail(intent, approval)
    from app.options.trade_floor import verify_binding as verify_floor

    verify_floor(intent, approval)
    from app.options.health_management import verify_binding as verify_health

    verify_health(intent, approval)
    health_policy = intent.health_management
    floor_policy = intent.trade_floor
    trail_policy = intent.premium_trail
    premium_protection = intent.entry_premium_protection
    if intent.requested_close_quantity != proposal.close_quantity or (
        intent.requested_close_quantity is not None and approval["origin"] != "DETERMINISTIC"
    ):
        raise ValueError("Stored requested close quantity mismatch")
    entry_id = intent.position_protection.entry_client_id if intent.position_protection else None
    explicit = intent.closing_entry_client_id
    if explicit is not None or "closing_entry_client_id" in approval:
        if explicit is None or approval.get("closing_entry_client_id") != explicit:
            raise ValueError("Stored closing entry approval mismatch")
        if entry_id is not None and entry_id != explicit:
            raise ValueError("Stored closing entry protection mismatch")
        entry_id = explicit
    if approval["origin"] == "PROTECTIVE" and intent.source_key.startswith("protective:"):
        protective_entry = intent.source_key.split(":")[1]
        if entry_id is not None and entry_id != protective_entry:
            raise ValueError("Stored protective closing entry mismatch")
        entry_id = protective_entry
    if entry_id is not None:
        entry = db.execute(
            "SELECT intent_json,approval_json FROM execution_orders WHERE client_id=?", (entry_id,)
        ).fetchone()
        if entry is None:
            raise ValueError("Stored exit entry reference missing")
        entry_intent = OptionIntent.model_validate(_json(entry[0]))
        verify_premium_binding(entry_intent, _json(entry[1]))
        verify_trail(entry_intent, _json(entry[1]))
        verify_floor(entry_intent, _json(entry[1]))
        verify_health(entry_intent, _json(entry[1]))
        health_policy = entry_intent.health_management
        floor_policy = entry_intent.trade_floor
        trail_policy = entry_intent.premium_trail
        premium_protection = entry_intent.entry_premium_protection
        if (
            entry_intent.side != "BUY"
            or entry_intent.instrument != intent.instrument
            or intent.side != "SELL"
            or intent.prepared_at < entry_intent.prepared_at
        ):
            raise ValueError("Stored exit entry identity mismatch")
    if entry_id is not None:
        lineage = entry_lineage(db, entry_id)
    return {
        **({"health_management": health_policy} if health_policy is not None else {}),
        **({"trade_floor": floor_policy} if floor_policy is not None else {}),
        **({"premium_trail": trail_policy} if trail_policy is not None else {}),
        **(
            {"entry_premium_protection": premium_protection.model_dump(mode="json")}
            if premium_protection is not None
            else {}
        ),
        **(
            {"target_exit_schedule": intent.target_exit_schedule.model_dump(mode="json")}
            if intent.target_exit_schedule is not None
            else {}
        ),
        **(
            {"target_exit_stage": intent.target_exit_stage}
            if intent.target_exit_stage is not None
            else {}
        ),
        **({"entry_lineage": lineage.model_dump(mode="json")} if lineage is not None else {}),
        **(
            {"requested_close_quantity": intent.requested_close_quantity}
            if intent.requested_close_quantity is not None
            else {}
        ),
        "origin": approval["origin"],
        "source_key": intent.source_key,
        "client_id": intent.client_id,
        "approved_quantity": intent.quantity,
        "order_status": row["status"],
        "attempted": row["attempted_at"] is not None,
        "fill_ids": tuple(f.fill_id for f in fills),
        "filled_quantity": sum(f.quantity for f in fills),
        "entry_client_id": entry_id,
        "execution_authority": False,
    }


@exact
def decision_attribution(db, key, outcome, policy):
    """Reconstruct from the same stored snapshot used by export/observer.

    Unknown or foreign model results retain their proposal but grant no review or
    fill attribution. No provider call, owner attachment or mutation is performed.
    """
    from app.options import entry_judgment, position_judgment
    from app.options.entry_reasoning import EntryReview
    from app.options.observer import _json
    from app.options.position_reasoning import PositionReview

    prefix = (
        "position"
        if "position_request" in outcome
        else "entry"
        if "entry_request" in outcome
        else None
    )
    role = (
        "MANAGEMENT"
        if prefix == "position"
        else "ENTRY"
        if prefix
        else "SELECTION"
        if "model_result" in outcome
        else "DETERMINISTIC"
    )
    call = db.execute("SELECT * FROM execution_model_calls WHERE source_key=?", (key,)).fetchone()
    if call and role == "DETERMINISTIC":
        role = "SELECTION"
    decision = db.execute(
        "SELECT * FROM execution_option_decisions WHERE source_key=?", (key,)
    ).fetchone()
    applied = _json(decision["result_json"]) if decision else {}
    inputs = _json(decision["inputs_json"]) if decision else {}
    if any(k in inputs and k not in outcome for k in ("entry_request", "position_request")):
        raise ValueError("Stored application lost original model request")
    proposal, packet, result = None, None, None
    review = outcome.get("entry_review")
    if prefix:
        module = position_judgment if prefix == "position" else entry_judgment
        request_type = module.PositionRequest if prefix == "position" else module.EntryRequest
        result_type = module.PositionResult if prefix == "position" else module.EntryResult
        request = request_type.model_validate(outcome[prefix + "_request"])
        packet = request.packet
        strategy = _json(
            db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
        )
        expected_key = "position:" + key.split(":")[1] if prefix == "position" else key
        if packet.cycle_key != expected_key or strategy.get(
            prefix + "_model"
        ) != request.configuration.model_dump(mode="json"):
            raise ValueError("Stored attribution request binding mismatch")
        if call and call["packet_hash"] != fingerprint(module.request_content(request)):
            raise ValueError("Stored attribution model input mismatch")
        if prefix + "_result" in outcome:
            result = result_type.model_validate(outcome[prefix + "_result"])
            proposal = result.plan
            if call is None:
                raise ValueError("Stored result has no admitted attempt")
            # A foreign/unusable result may be retained only as unknown-cost evidence.
            if call["cost"] is not None and (
                result.request_id != request.request_id
                or result.packet_hash != fingerprint(packet)
                or result.configuration_hash != fingerprint(request.configuration)
                or call["decision_hash"] != fingerprint(proposal)
                or result.usage is None
                or _json(call["usage_json"]) != result.usage.model_dump(mode="json")
            ):
                raise ValueError("Stored paid proposal binding mismatch")
        if review is not None:
            checked = EntryReview.model_validate(review) if prefix == "entry" else None
            if checked and (checked.packet_hash != fingerprint(packet) or checked.plan != proposal):
                raise ValueError("Stored entry review binding mismatch")
        if decision and (
            inputs.get(prefix + "_request") != outcome[prefix + "_request"]
            or inputs.get(prefix + "_result") != outcome.get(prefix + "_result")
        ):
            raise ValueError("Stored proposal application mismatch")
        if prefix == "position":
            review = applied.get("position_review")
            if review is not None:
                checked = PositionReview.model_validate(review)
                if checked.packet_hash != fingerprint(packet) or checked.plan != proposal:
                    raise ValueError("Stored management review binding mismatch")
                expected_status = (
                    ("TIGHTENED" if proposal.action == "TIGHTEN" else "PREPARED")
                    if checked.outcome == "ELIGIBLE"
                    else checked.outcome
                )
                if applied.get("status") != expected_status:
                    raise ValueError("Stored management application status mismatch")
            elif decision:
                raise ValueError("Stored management review missing")
            tightened = db.execute(
                "SELECT payload FROM execution_events WHERE kind='OPTION_INVALIDATION_TIGHTENED' AND json_extract(payload,'$.source_key')=? LIMIT 2",
                (key,),
            ).fetchall()
            if applied.get("status") == "TIGHTENED":
                if len(tightened) != 1 or _json(tightened[0][0]) != {
                    "price": str(checked.tightened_invalidation),
                    "source_key": key,
                }:
                    raise ValueError("Stored tightening event mismatch")
            elif tightened:
                raise ValueError("Stored tightening lacks application")
            if decision and (
                decision["fingerprint"] != fingerprint(inputs)
                or outcome.get("position_action", applied) != applied
            ):
                raise ValueError("Stored management consumption mismatch")
            events = db.execute(
                "SELECT payload FROM execution_events WHERE kind='OPTION_POSITION_PLAN_CONSUMED' AND json_extract(payload,'$.source_key')=? LIMIT 2",
                (key,),
            ).fetchall()
            expected = {"source_key": key, "position_revision": packet.position_revision, **applied}
            if (decision is not None and (len(events) != 1 or _json(events[0][0]) != expected)) or (
                decision is None and events
            ):
                raise ValueError("Stored management consumption event mismatch")
            if decision and (
                result is None
                or result.error is not None
                or call["cost"] is None
                or outcome.get("position_timely") is not True
            ):
                raise ValueError("Stored management application without paid usable advice")
    else:
        proposal = outcome.get("model_result", {}).get("choice") or inputs.get("proposal")
    plan = proposal.model_dump(mode="json") if hasattr(proposal, "model_dump") else proposal
    order_rows = db.execute(
        "SELECT * FROM execution_orders WHERE source_key=? LIMIT 2", (key,)
    ).fetchall()
    if len(order_rows) > 1:
        raise ValueError("Duplicate stored proposal orders")
    order = order_attribution(db, order_rows[0]) if order_rows else {}
    if order:
        approval = _json(order_rows[0]["approval_json"])
        intent = OptionIntent.model_validate(_json(order_rows[0]["intent_json"]))
        if applied.get("client_id") != intent.client_id:
            raise ValueError("Stored order has no matching approval decision")
        if intent.requested_close_quantity is not None and (
            inputs.get("proposal") != approval["proposal"]
            or plan is None
            or plan.get("close_quantity") != intent.requested_close_quantity
        ):
            raise ValueError("Stored close proposal quantity mismatch")
        for field in (
            "target_exit_schedule",
            "target_exit_stage",
            "entry_premium_protection",
            "premium_trail",
            "trade_floor",
            "health_management",
        ):
            if inputs.get(field) != approval.get(field):
                raise ValueError("Stored target proposal binding mismatch")
        if prefix and (
            approval.get(prefix + "_request") != outcome[prefix + "_request"]
            or approval.get(prefix + "_result") != outcome.get(prefix + "_result")
        ):
            raise ValueError("Stored order lost full model receipt")
        if prefix == "position" and (
            approval.get("origin") != "POSITION_MODEL"
            or intent.position_protection is None
            or intent.position_protection.packet_hash != fingerprint(packet)
            or intent.position_protection.plan_hash != fingerprint(proposal)
            or intent.position_protection.entry_client_id != packet.position.entry_client_id
            or intent.position_protection.position_revision != packet.position_revision
            or plan["action"] != "EXIT_ALL"
            or applied["status"] != "PREPARED"
        ):
            raise ValueError("Stored managed exit lineage mismatch")
    if prefix == "position" and "entry_lineage" not in order:
        from app.options.entry_lineage import entry_lineage

        lineage = entry_lineage(db, packet.position.entry_client_id)
        if lineage is not None:
            order["entry_lineage"] = lineage.model_dump(mode="json")
    cost = Decimal(call["cost"]) if call and call["cost"] is not None else None
    if cost is not None:
        usage = _json(call["usage_json"])
        rates = policy.cost_policy
        if (
            rates is None
            or usage["model"] != rates.model
            or cost
            != (
                usage["input_tokens"] * rates.input_per_million
                + usage["output_tokens"] * rates.output_per_million
            )
            / 1000000
        ):
            raise ValueError("Stored attribution cost mismatch")
    return DecisionAttribution(
        role=role,
        source_key=key,
        packet_hash=fingerprint(packet) if packet else None,
        proposal_hash=fingerprint(proposal) if proposal else None,
        requested_invalidation=plan.get("underlying_invalidation") if plan else None,
        applied_invalidation=review.get("tightened_invalidation")
        if review and applied.get("status") == "TIGHTENED"
        else None,
        requested_target=plan.get("underlying_target") if plan else None,
        requested_close_quantity=plan.get("close_quantity") if plan else None,
        horizon_seconds=plan.get("horizon_seconds") if plan else None,
        change_since_entry=plan.get("change_since_entry") if plan else None,
        uncertainty=plan.get("uncertainty") if plan else None,
        review_reasons=tuple(review.get("reasons", ())) if review else (),
        proposal_action=plan.get("action") if plan else None,
        thesis=plan.get("thesis") if plan else None,
        entry_client_id=packet.position.entry_client_id
        if prefix == "position"
        else order.get("entry_client_id"),
        position_revision=packet.position_revision if prefix == "position" else None,
        review_outcome=review.get("outcome")
        if review
        else (applied.get("admission") or {}).get("outcome"),
        application_status=applied.get("status"),
        model_attempted=call is not None,
        model_cost=cost,
        cost_status="NOT_CALLED"
        if call is None
        else "UNKNOWN"
        if cost is None
        else "CONFIGURED_ESTIMATE",
        **{
            k: v
            for k, v in order.items()
            if k
            not in {
                "origin",
                "source_key",
                "execution_authority",
                "entry_client_id",
                "requested_close_quantity",
            }
        },
    )
