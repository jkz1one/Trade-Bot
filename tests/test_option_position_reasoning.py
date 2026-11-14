"""Position/revision binding, monotone stops and mandatory-protection precedence."""

from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from agents import AgentOutputSchema
from pydantic import ValidationError
from test_option_entry_reasoning import AT
from test_option_entry_reasoning import packet_for as entry_packet
from test_option_execution import configuration

from app.options.engine import fingerprint
from app.options.lifecycle import EntryProtection, OptionIntent, OptionLot, OptionPosition
from app.options.models import OptionHolding
from app.options.position_reasoning import (
    PositionPacket,
    PositionPlan,
    PositionReasoningPolicy,
    review_position_plan,
)

D = Decimal


def packet_for(right="CALL"):
    original = entry_packet(right)
    o = original.opportunities[0]
    exit_at = AT + timedelta(minutes=10)
    protection = EntryProtection(
        packet_hash="c" * 64,
        plan_hash="d" * 64,
        underlying_target="602" if right == "CALL" else "598",
        exit_by=exit_at,
    )
    entry = OptionIntent(
        client_id="position-entry",
        source_key="prior-slot",
        instrument=o.quote.instrument,
        side="BUY",
        quantity=2,
        limit_price="1.01",
        approved_entry_debit="205",
        approved_full_premium_loss="210",
        prepared_at=AT - timedelta(minutes=5),
        approval_expires_at=AT - timedelta(minutes=4),
        order_expires_at=exit_at,
        exit_at=exit_at,
        original_underlying_invalidation="600",
        thesis="Original continuation thesis",
        entry_protection=protection,
    )
    position = OptionPosition(
        contract=entry.instrument.contract,
        quantity=2,
        entry_client_id=entry.client_id,
        lots=(OptionLot(quantity=2, price="1.01"),),
        exit_at=exit_at,
        original_underlying_invalidation="600",
        tightened_underlying_invalidation="600",
        entry_protection=protection,
    )
    holding = OptionHolding(
        contract=position.contract, quantity=2, original_underlying_invalidation="600"
    )
    account = original.account.model_copy(
        update={"position": holding, "cash": D(795), "settled_cash": D(795)}
    )
    _, _, execution_policy = configuration(right)
    packet = {
        "decision_id": "a" * 64,
        "cycle_key": "position:" + str(int(AT.timestamp()) // 300),
        "model_configuration_hash": "b" * 64,
        "as_of": AT,
        "valid_until": AT + timedelta(seconds=5),
        "position_revision": 7,
        "position": position,
        "entry": entry,
        "account": account,
        "quote": o.quote,
        "underlying": o.underlying,
        "scan": o.scan,
        "session": o.session,
        "limits": original.limits,
        "execution_policy": execution_policy,
        "policy": PositionReasoningPolicy(max_lease_seconds=5),
        "evidence_ids": tuple(
            fingerprint(x) for x in (position, entry, account, o.quote, o.underlying, o.scan)
        ),
    }
    return PositionPacket(**packet)


def plan_for(packet, **changes):
    return PositionPlan.model_validate(
        {
            "decision_id": packet.decision_id,
            "packet_hash": fingerprint(packet),
            "entry_client_id": packet.position.entry_client_id,
            "position_revision": packet.position_revision,
            "action": "TIGHTEN",
            "underlying_invalidation": "600.2"
            if packet.position.contract.right == "CALL"
            else "599.8",
            "evidence_ids": (packet.evidence_ids[0], packet.evidence_ids[5]),
            "thesis": "Protect thesis after completed context change",
            "change_since_entry": "Price moved favorably; tighten invalidation",
            "uncertainty": "Continuation can still fail",
        }
        | changes
    )


def review(packet, plan=None, **changes):
    args = {
        "position": packet.position,
        "position_revision": packet.position_revision,
        "account": packet.account,
        "quote": packet.quote,
        "underlying": packet.underlying,
        "now": AT,
    }
    return review_position_plan(packet, plan or plan_for(packet), **(args | changes))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("action", ["MAINTAIN", "EXIT_ALL", "TIGHTEN"])
def test_review_actions_never_execute_or_change_packet(right, action):
    p = packet_for(right)
    before = p.model_dump_json()
    plan = plan_for(
        p, action=action, **({"underlying_invalidation": None} if action != "TIGHTEN" else {})
    )
    r = review(p, plan)
    assert r.outcome == ("MAINTAIN" if action == "MAINTAIN" else "ELIGIBLE")
    assert not r.execution_authority and p.model_dump_json() == before
    if action == "EXIT_ALL":
        assert r.proposal.action == "CLOSE" and r.admission.quantity == p.position.quantity
        assert r.admission.valid_until <= p.valid_until
    else:
        assert r.proposal is r.admission is None
    assert bool(r.tightened_invalidation) == (action == "TIGHTEN")
    # Pure review is not durable consumption. Integration must consume once atomically.
    assert review(p, plan) == r


@pytest.mark.parametrize(
    "right,price",
    [
        ("CALL", "599"),
        ("CALL", "600"),
        ("CALL", "600.8"),
        ("CALL", "602"),
        ("PUT", "601"),
        ("PUT", "600"),
        ("PUT", "599.2"),
        ("PUT", "598"),
    ],
)
def test_tightening_cannot_widen_repeat_or_cross(right, price):
    p = packet_for(right)
    assert review(p, plan_for(p, underlying_invalidation=price)).outcome == "REJECTED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", 1),
        ("contract", "other"),
        ("underlying_target", "605"),
        ("exit_at", "later"),
        ("action", "ADD"),
        ("action", "EXIT_PARTIAL"),
        ("position_revision", True),
        ("underlying_invalidation", 600.2),
        ("underlying_invalidation", True),
        ("underlying_invalidation", "NaN"),
        ("underlying_invalidation", "1e999"),
        ("thesis", " "),
        ("uncertainty", " "),
        ("change_since_entry", " "),
    ],
)
def test_strict_output_cannot_add_authority_or_ambiguous_prices(field, value):
    with pytest.raises(ValidationError):
        plan_for(packet_for(), **{field: value})


@pytest.mark.parametrize("action", ["MAINTAIN", "EXIT_ALL"])
def test_non_tightening_cannot_carry_terms(action):
    with pytest.raises(ValidationError):
        plan_for(packet_for(), action=action)


@pytest.mark.parametrize(
    "damage", ["packet", "decision", "owner", "revision", "evidence", "missing"]
)
def test_foreign_response_rejected(damage):
    p = packet_for()
    changes = {
        "packet": {"packet_hash": "f" * 64},
        "decision": {"decision_id": "f" * 64},
        "owner": {"entry_client_id": "other"},
        "revision": {"position_revision": 8},
        "evidence": {"evidence_ids": ("f" * 64,)},
        "missing": {"evidence_ids": (p.evidence_ids[0],)},
    }[damage]
    assert review(p, plan_for(p, **changes)).outcome == "REJECTED"


@pytest.mark.parametrize(
    "damage", ["flat", "revision", "bool", "quantity", "lots", "owner", "stop", "target", "exit"]
)
def test_revised_position_cannot_use_old_plan(damage):
    p = packet_for()
    position = p.position
    changes = {
        "flat": {"position": None},
        "revision": {"position_revision": 8},
        "bool": {"position_revision": True},
    }
    if damage in changes:
        r = review(p, **changes[damage])
    else:
        update = {
            "quantity": {"quantity": 1, "lots": (OptionLot(quantity=1, price="1.01"),)},
            "lots": {"lots": (OptionLot(quantity=2, price="1.02"),)},
            "owner": {"entry_client_id": "replacement"},
            "stop": {"tightened_underlying_invalidation": D("600.1")},
            "target": {
                "entry_protection": position.entry_protection.model_copy(
                    update={"underlying_target": D("603")}
                )
            },
            "exit": {"exit_at": position.exit_at - timedelta(seconds=1)},
        }[damage]
        r = review(p, position=position.model_copy(update=update))
    assert r.outcome == "REJECTED" and r.proposal is None


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("trigger", ["stop", "premium", "target", "time", "expiry", "latched"])
@pytest.mark.parametrize("action", ["MAINTAIN", "EXIT_ALL", "TIGHTEN"])
def test_mandatory_exit_wins_every_advisory_action(right, trigger, action):
    p = packet_for(right)
    plan = plan_for(
        p, action=action, **({"underlying_invalidation": None} if action != "TIGHTEN" else {})
    )
    changes = {}
    reason = {
        "stop": "UNDERLYING_INVALIDATION",
        "premium": "PREMIUM_CATASTROPHE",
        "target": "UNDERLYING_TARGET",
        "time": "TIME_EXIT",
        "expiry": "EXPIRY_GUARD",
        "latched": "UNDERLYING_INVALIDATION",
    }[trigger]
    if trigger in {"stop", "target"}:
        price = "597" if (right == "CALL") == (trigger == "stop") else "603"
        changes["underlying"] = p.underlying.model_copy(update={"bid": D(price), "ask": D(price)})
    elif trigger == "premium":
        changes["quote"] = p.quote.model_copy(update={"bid": D(".1")})
    elif trigger in {"time", "expiry"}:
        changes = {
            "now": p.position.exit_at if trigger == "time" else p.position.contract.last_trading_at,
            "quote": None,
            "underlying": None,
        }
    else:
        changes["position"] = p.position.model_copy(
            update={"exit_reason": reason, "exit_required_at": AT}
        )
    r = review(p, plan, **changes)
    assert r.outcome == "MANDATORY_EXIT" and r.reasons == (reason,) and r.proposal is None


@pytest.mark.parametrize(
    "damage",
    [
        "halt",
        "unknown_cost",
        "working",
        "unreconciled",
        "foreign",
        "stale",
        "unsupported",
        "blocker",
        "holding",
    ],
)
def test_fresh_account_blockers_reject_discretionary_changes(damage):
    p = packet_for()
    changes = {
        "halt": {"entry_halted": True},
        "unknown_cost": {"budgets_known": False},
        "working": {"working_orders": 1},
        "unreconciled": {"reconciled": False},
        "foreign": {"account_id": "other"},
        "stale": {"captured_at": AT - timedelta(minutes=1)},
        "unsupported": {"unsupported_exposure": True},
        "blocker": {"entry_blockers": ("MODEL_COST_BUDGET_EXHAUSTED",)},
        "holding": {"position": None},
    }[damage]
    assert review(p, account=p.account.model_copy(update=changes)).reasons == (
        "POSITION_ACCOUNT_BLOCKED",
    )


@pytest.mark.parametrize(
    "damage",
    [
        "quote_missing",
        "underlying_missing",
        "quote_stale",
        "underlying_stale",
        "identity",
        "source",
        "delayed",
        "time_regression",
        "expired",
    ],
)
def test_changed_market_and_deadline_are_not_permissions(damage):
    p = packet_for()
    changes = {}
    if damage.endswith("missing"):
        changes[damage.split("_")[0]] = None
    elif damage.endswith("stale"):
        name = damage.split("_")[0]
        changes[name] = getattr(p, name).model_copy(update={"source_at": AT - timedelta(minutes=1)})
    elif damage == "identity":
        changes["quote"] = p.quote.model_copy(
            update={"instrument": p.quote.instrument.model_copy(update={"instrument_id": "other"})}
        )
    elif damage == "source":
        changes["quote"] = p.quote.model_copy(update={"source": "other"})
    elif damage == "delayed":
        changes["underlying"] = p.underlying.model_copy(update={"entitlement": "DELAYED"})
    elif damage == "time_regression":
        changes["quote"] = p.quote.model_copy(
            update={"source_at": p.quote.source_at - timedelta(milliseconds=1)}
        )
    else:
        changes["now"] = p.valid_until
    assert review(p, **changes).outcome == "REJECTED"


def test_exit_all_cannot_silently_scale_out_or_increase_quantity():
    p = packet_for()
    plan = plan_for(p, action="EXIT_ALL", underlying_invalidation=None)
    assert review(p, plan, quote=p.quote.model_copy(update={"bid_size": 1})).reasons == (
        "EXIT_ALL_EXECUTABLE_SIZE_REQUIRED",
    )
    assert (
        review(p, plan, quote=p.quote.model_copy(update={"bid_size": 100})).admission.quantity == 2
    )


@pytest.mark.parametrize(
    "damage",
    ["references", "entry", "deadline", "scan", "scan_future", "account", "position", "slot"],
)
def test_packet_preflight_revalidates_unchecked_mutation(damage):
    p = packet_for()
    changes = {
        "references": {"evidence_ids": ("f" * 64,) * 6},
        "entry": {"entry": p.entry.model_copy(update={"client_id": "other"})},
        "deadline": {"valid_until": AT + timedelta(minutes=1)},
        "scan": {"scan": p.scan.model_copy(update={"issues": ("GAP",)})},
        "scan_future": {
            "scan": p.scan.model_copy(update={"completed_through": AT + timedelta(seconds=1)})
        },
        "account": {"account": p.account.model_copy(update={"working_orders": 1})},
        "position": {
            "position": p.position.model_copy(
                update={"exit_reason": "TIME_EXIT", "exit_required_at": AT}
            )
        },
        "slot": {"cycle_key": "position:other"},
    }[damage]
    with pytest.raises(ValidationError):
        review(p.model_copy(update=changes))


def test_schema_and_decimal_context_keep_strict_contract():
    p = packet_for()
    expected = review(p)
    with localcontext() as context:
        context.prec = 2
        assert review(p) == expected
    schema = AgentOutputSchema(PositionPlan).json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_new_packet_respects_effective_stop_not_only_original(right):
    p = packet_for(right)
    position = p.position.model_copy(
        update={"tightened_underlying_invalidation": D("600.3" if right == "CALL" else "599.7")}
    )
    p = PositionPacket.model_validate(
        p.model_dump()
        | {
            "position": position.model_dump(),
            "position_revision": 8,
            "evidence_ids": (fingerprint(position), *p.evidence_ids[1:]),
        }
    )
    assert review(p).reasons == ("INVALIDATION_MUST_TIGHTEN_WITHOUT_CROSSING",)
    assert (
        review(
            p, plan_for(p, underlying_invalidation="600.4" if right == "CALL" else "599.6")
        ).outcome
        == "ELIGIBLE"
    )


def test_future_evidence_and_naive_clock_never_grant_action():
    p = packet_for()
    q = p.quote.model_copy(
        update={"source_at": AT + timedelta(seconds=1), "received_at": AT + timedelta(seconds=1)}
    )
    assert review(p, quote=q).outcome == "REJECTED"
    with pytest.raises(ValueError):
        review(p, now=AT.replace(tzinfo=None))
