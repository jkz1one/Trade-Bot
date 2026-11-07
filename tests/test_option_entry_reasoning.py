"""Bounded entry geometry, exact lineage and original authority ceilings."""

from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from agents import AgentOutputSchema
from pydantic import ValidationError
from test_degen_options import AT, frame, policies
from test_option_admission import inputs

from app.options.degen import scan_degen
from app.options.engine import fingerprint
from app.options.entry_reasoning import (
    EntryOpportunity,
    EntryPacket,
    EntryPlan,
    EntryReasoningPolicy,
    review_entry_plan,
)
from app.options.selection import admit_candidates, plan_contract_reads

D = Decimal


def packet_for(right="CALL"):
    data, f = inputs(right), frame(right)
    account = data["account"].model_copy(update={"captured_at": AT})
    setup, selection = policies()
    scan = scan_degen(f.histories[0], setup, data["session"], now=AT)
    reads = plan_contract_reads(scan, f.inventories[0], selection, data["limits"], now=AT)
    candidates, _ = admit_candidates(
        scan, reads, f.quotes, f.underlyings[0], account, data["limits"], data["session"], now=AT
    )
    assert candidates
    return EntryPacket(
        decision_id="a" * 64,
        cycle_key="degen:" + str(int(AT.timestamp()) // 300),
        model_configuration_hash="b" * 64,
        as_of=AT,
        valid_until=min(c.admission.valid_until for c in candidates),
        account=account,
        limits=data["limits"],
        policy=EntryReasoningPolicy(
            max_horizon_seconds=1800,
            max_target_fraction=".01",
            max_trigger_fraction=".005",
            minimum_reward_risk="1",
        ),
        opportunities=tuple(
            EntryOpportunity(
                candidate=c,
                scan=scan,
                quote=f.quotes[0],
                underlying=f.underlyings[0],
                session=data["session"],
                evidence_ids=tuple(fingerprint(x) for x in (scan, f.quotes[0], f.underlyings[0])),
            )
            for c in candidates
        ),
    )


def plan_for(packet, **updates):
    o = packet.opportunities[0]
    call = o.candidate.instrument.contract.right == "CALL"
    return EntryPlan.model_validate(
        {
            "decision_id": packet.decision_id,
            "packet_hash": fingerprint(packet),
            "action": "ENTER",
            "candidate_id": o.candidate.candidate_id,
            "condition": "NOW",
            "underlying_invalidation": "600",
            "underlying_target": "602" if call else "598",
            "horizon_seconds": 600,
            "evidence_ids": o.evidence_ids,
            "thesis": "Completed structure supports continuation; tighter thesis invalidation",
            "uncertainty": "Continuation may fail; full premium remains at risk",
            **updates,
        }
    )


def review(packet, plan=None, **updates):
    o = packet.opportunities[0]
    args = {"quote": o.quote, "underlying": o.underlying, "account": packet.account, "now": AT}
    return review_entry_plan(packet, plan or plan_for(packet), **(args | updates))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_changed_geometry_is_readmitted_without_execution_authority(right):
    p = packet_for(right)
    r = review(p)
    original = p.opportunities[0].candidate
    assert r.outcome == "ELIGIBLE" and r.execution_authority is False
    assert r.proposal.underlying_invalidation != original.proposal.underlying_invalidation
    assert r.admission.quantity == original.admission.quantity
    assert r.admission.valid_until <= p.valid_until
    assert r.exit_by == AT + timedelta(seconds=600)
    assert r.plan.underlying_target == (D(602) if right == "CALL" else D(598))


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", 1),
        ("contract", "invented"),
        ("premium_target", "2"),
        ("horizon_seconds", True),
        ("underlying_target", 602.0),
        ("underlying_target", "NaN"),
        ("underlying_target", "1e999"),
        ("thesis", " "),
        ("uncertainty", " "),
        ("condition", "RUN_CODE"),
        ("condition", "ABOVE"),
        ("underlying_trigger", "600"),
    ],
)
def test_model_cannot_add_authority_or_ambiguous_terms(field, value):
    with pytest.raises(ValidationError):
        plan_for(packet_for(), **{field: value})


@pytest.mark.parametrize(
    "right,stop,target",
    [
        ("CALL", "598", "602"),
        ("PUT", "602", "598"),
        ("CALL", "601", "602"),
        ("PUT", "599", "598"),
        ("CALL", "600", "600.5"),
        ("PUT", "600", "599.5"),
        ("CALL", "600", "620"),
        ("PUT", "600", "580"),
    ],
)
def test_geometry_cannot_widen_reverse_or_escape_envelope(right, stop, target):
    p = packet_for(right)
    r = review(p, plan_for(p, underlying_invalidation=stop, underlying_target=target))
    assert r.outcome == "REJECTED" and r.admission is None


@pytest.mark.parametrize("damage", ["hash", "decision", "candidate", "reference", "missing"])
def test_stale_or_foreign_model_output_cannot_select(damage):
    p = packet_for()
    fields = {
        "hash": {"packet_hash": "c" * 64},
        "decision": {"decision_id": "c" * 64},
        "candidate": {"candidate_id": "c" * 64},
        "reference": {"evidence_ids": ("c" * 64,)},
        "missing": {"evidence_ids": (fingerprint(p.account),)},
    }
    assert review(p, plan_for(p, **fields[damage])).outcome == "REJECTED"


def test_hold_needs_bound_evidence_but_no_new_market_work():
    p = packet_for()
    plan = EntryPlan(
        decision_id=p.decision_id,
        packet_hash=fingerprint(p),
        action="HOLD",
        evidence_ids=(fingerprint(p.account),),
        thesis="Preserve cash",
        uncertainty="Weak edge",
    )
    assert review(p, plan, quote=None, underlying=None, account=None).outcome == "HOLD"
    assert review(p, plan, now=p.valid_until).outcome == "REJECTED"
    with pytest.raises(ValidationError):
        EntryPlan.model_validate(plan.model_dump() | {"underlying_target": "602"})


@pytest.mark.parametrize(
    "condition,trigger,outcome",
    [
        ("ABOVE", "600.7", "ELIGIBLE"),
        ("ABOVE", "600.9", "HOLD"),
        ("BELOW", "600.9", "ELIGIBLE"),
        ("BELOW", "600.7", "HOLD"),
        ("ABOVE", "650", "REJECTED"),
    ],
)
def test_conditions_use_conservative_quote_side_without_standing_order(condition, trigger, outcome):
    p = packet_for()
    r = review(p, plan_for(p, condition=condition, underlying_trigger=trigger))
    assert r.outcome == outcome
    if outcome != "ELIGIBLE":
        assert r.proposal is None and r.admission is None


def test_costs_reduce_size_and_lower_price_cannot_increase_original_quantity():
    p = packet_for()
    small = p.account.model_copy(update={"daily_loss_available": D(150)})
    assert review(p, account=small).admission.quantity == 1
    q = p.opportunities[0].quote.model_copy(update={"ask": D(".5"), "bid": D(".49")})
    r = review(p, quote=q)
    old = p.opportunities[0].candidate.admission
    assert r.admission.quantity == old.quantity
    assert r.admission.full_premium_loss <= old.full_premium_loss
    assert r.admission.entry_debit <= old.entry_debit
    higher = p.opportunities[0].quote.model_copy(update={"ask": D("1.01")})
    assert review(p, quote=higher).reasons == ("ORIGINAL_PRICE_CEILING_EXCEEDED",)


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_cost",
        "halt",
        "orders",
        "foreign_account",
        "delay",
        "future",
        "regression",
        "foreign_instrument",
    ],
)
def test_fresh_authority_and_market_revalidation(damage):
    p = packet_for()
    q = p.opportunities[0].quote
    updates = {
        "unknown_cost": {"account": p.account.model_copy(update={"budgets_known": False})},
        "halt": {"account": p.account.model_copy(update={"entry_halted": True})},
        "orders": {"account": p.account.model_copy(update={"working_orders": 1})},
        "foreign_account": {"account": p.account.model_copy(update={"account_id": "other"})},
        "delay": {"quote": q.model_copy(update={"entitlement": "DELAYED"})},
        "future": {"quote": q.model_copy(update={"source_at": AT + timedelta(seconds=1)})},
        "regression": {"quote": q.model_copy(update={"source_at": AT - timedelta(seconds=1)})},
        "foreign_instrument": {
            "quote": q.model_copy(
                update={"instrument": q.instrument.model_copy(update={"instrument_id": "other"})}
            )
        },
    }
    assert review(p, **updates[damage]).outcome == "REJECTED"


def test_expiry_horizon_and_clock_cannot_renew():
    p = packet_for()
    assert review(p, now=p.valid_until).outcome == "REJECTED"
    assert review(p, now=AT - timedelta(seconds=1)).outcome == "REJECTED"
    assert review(p, plan_for(p, horizon_seconds=1801)).outcome == "REJECTED"
    assert (
        review(p, plan_for(p, horizon_seconds=1), now=AT + timedelta(seconds=1)).outcome
        == "REJECTED"
    )
    with pytest.raises(ValueError):
        review(p, now=AT.replace(tzinfo=None))


@pytest.mark.parametrize("damage", ["expiry", "candidate", "admission", "setup", "duplicates"])
def test_preflight_revalidates_even_model_copy_bypasses(damage):
    p = packet_for()
    o = p.opportunities[0]
    changes = {
        "expiry": {"valid_until": AT + timedelta(seconds=30)},
        "duplicates": {"opportunities": (o, o)},
    }
    if damage == "candidate":
        changes[damage] = {
            "opportunities": (
                o.model_copy(
                    update={"candidate": o.candidate.model_copy(update={"candidate_id": "d" * 64})}
                ),
            )
        }
    if damage == "admission":
        changes[damage] = {
            "opportunities": (
                o.model_copy(
                    update={
                        "candidate": o.candidate.model_copy(
                            update={
                                "admission": o.candidate.admission.model_copy(
                                    update={"quantity": 999}
                                )
                            }
                        )
                    }
                ),
            )
        }
    if damage == "setup":
        changes[damage] = {
            "opportunities": (
                o.model_copy(update={"scan": o.scan.model_copy(update={"issues": ("BLOCKED",)})}),
            )
        }
    with pytest.raises(ValidationError):
        review(p.model_copy(update=changes[damage]))


def test_strict_schema_roundtrip_and_decimal_context_independence():
    p = packet_for()
    plan = plan_for(p)
    assert EntryPlan.model_validate_json(plan.model_dump_json()) == plan
    schema = AgentOutputSchema(EntryPlan).json_schema()
    assert schema["additionalProperties"] is False
    wire = p.model_dump(mode="json")
    assert tuple(wire["opportunities"][0]["evidence_ids"]) == p.opportunities[0].evidence_ids
    expected = review(p)
    with localcontext() as ctx:
        ctx.prec = 3
        assert (
            review(p)
            == expected
            == review_entry_plan(
                EntryPacket.model_validate_json(p.model_dump_json()),
                plan,
                quote=p.opportunities[0].quote,
                underlying=p.opportunities[0].underlying,
                account=p.account,
                now=AT,
            )
        )
