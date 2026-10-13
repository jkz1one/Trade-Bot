"""Context can reject or annotate a completed Scope pattern, never invent one."""

from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_structure import bind as bind_structure
from test_option_scope_structure import frame as structure_frame
from test_option_scope_structure import policy as structure_policy

from app.options.scope_context import (
    CONTEXT_PATTERNS,
    ScopeBiasContext,
    ScopeContextInput,
    ScopeContextPolicy,
    ScopeDealerContext,
    ScopeEventContext,
    ScopeMoveContext,
    ScopePriorContext,
    context_payload_hashes,
    scan_scope_context,
)

D = Decimal


def policy(**changes):
    return ScopeContextPolicy.model_validate(
        {
            "structure": structure_policy(),
            "prior_source": "fixture-prior",
            "prior_max_age_seconds": 4 * 86400,
            "dealer_proximity_points": "3",
            "dealer_proximity_fraction": ".0015",
            "boundary_proximity_points": "4",
            "boundary_proximity_fraction": ".0015",
            "prior_proximity_points": "3",
            "prior_proximity_fraction": ".0012",
            "max_expected_move_consumed_fraction": ".72",
        }
        | changes
    )


def context(f):
    now = f.histories[0].received_at
    common = {"source_at": now, "received_at": now, "complete": True, "entitlement": "REALTIME"}
    prior_close = now.replace(hour=20, minute=0, second=0) - timedelta(days=1)
    return ScopeContextInput(
        previous_session=prior_close.date(),
        dealer=ScopeDealerContext(
            **common, source="fixture-dealer_structure", nodes=("100", "106")
        ),
        moves=ScopeMoveContext(
            **common,
            source="fixture-options_analytics",
            expiration=now.date(),
            reference_spot=f.histories[0].bars[-1].close,
            atm_straddle_move="6",
            iv_derived_move="5",
        ),
        flow=ScopeBiasContext(
            **common,
            source="fixture-options_flow",
            kind="options_flow",
            scope="SPX_SPXW",
            state="NEUTRAL",
            valid_through=now + timedelta(seconds=10),
        ),
        news=ScopeBiasContext(
            **common,
            source="fixture-broad_market_news",
            kind="broad_market_news",
            scope="BROAD_MARKET",
            state="NEUTRAL",
            valid_through=now + timedelta(seconds=10),
        ),
        events=ScopeEventContext(
            **common,
            source="fixture-economic_events",
            scope="US_MACRO",
            state="CLEAR",
            valid_through=now + timedelta(seconds=10),
        ),
        prior=ScopePriorContext(
            source="fixture-prior",
            source_at=prior_close,
            received_at=prior_close,
            complete=True,
            entitlement="REALTIME",
            session_date=prior_close.date(),
            closed_at=prior_close,
            high="100.2",
            low="99.8",
        ),
    )


def bind(f, c):
    hashes = context_payload_hashes(c)
    return f.model_copy(
        update={
            "evidence": tuple(
                e.model_copy(update={"payload_hash": hashes[e.kind]}) if e.kind in hashes else e
                for e in f.evidence
            )
        }
    )


def scan(f, c=None, p=None, *, now=AT):
    c = c or context(f)
    return scan_scope_context(bind(f, c), c, p or policy(), now=now)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_all_six_context_variants_retain_parent_geometry_and_level(right):
    found = set()
    for parent in ("opening_range_break_hold", "trap_reversal"):
        f = structure_frame(parent, right)
        result = scan(f)
        assert result.issues == ()
        assert result.authority is False and result.live_enabled is False
        assert len(result.observations) <= 90
        original = next(
            o for o in result.structure.observations if o.pattern == parent and o.right == right
        )
        derived = [
            o
            for o in result.observations
            if o.parent_pattern == parent and o.right == right and o.pattern in CONTEXT_PATTERNS
        ]
        for item in derived:
            assert item.status == "DETECTED" and item.geometry == original.geometry
            assert item.matched_level is not None and item.reasons == ()
            found.add(item.pattern)
    assert found == set(CONTEXT_PATTERNS)


@pytest.mark.parametrize(
    "field,kind",
    [
        ("dealer", "DEALER_STRUCTURE"),
        ("moves", "OPTIONS_ANALYTICS"),
        ("flow", "OPTIONS_FLOW"),
        ("news", "BROAD_MARKET_NEWS"),
        ("events", "ECONOMIC_EVENTS"),
        ("prior", "PRIOR_SESSION"),
    ],
)
def test_each_missing_payload_blocks_context_review(field, kind):
    f = structure_frame()
    c = context(f).model_copy(update={field: None})
    result = scan(f, c)
    assert kind + "_PAYLOAD_MISSING" in result.issues and not result.observations


@pytest.mark.parametrize(
    "field,kind",
    [
        ("dealer", "DEALER_STRUCTURE"),
        ("moves", "OPTIONS_ANALYTICS"),
        ("flow", "OPTIONS_FLOW"),
        ("news", "BROAD_MARKET_NEWS"),
        ("events", "ECONOMIC_EVENTS"),
    ],
)
@pytest.mark.parametrize(
    "change",
    [
        {"source": "foreign"},
        {"complete": False},
        {"entitlement": "DELAYED"},
        {"received_at": AT + timedelta(seconds=1)},
    ],
)
def test_hash_alone_cannot_bypass_payload_source_quality_or_clocks(field, kind, change):
    f = structure_frame()
    c = context(f)
    c = c.model_copy(update={field: getattr(c, field).model_copy(update=change)})
    result = scan(f, c)
    assert kind + "_PAYLOAD_BINDING_MISMATCH" in result.issues and not result.observations


def test_modified_payload_without_new_attestation_hash_blocks():
    f = structure_frame()
    c = context(f)
    f = bind(f, c)
    c = c.model_copy(update={"dealer": c.dealer.model_copy(update={"nodes": (D(99),)})})
    assert (
        "DEALER_STRUCTURE_PAYLOAD_BINDING_MISMATCH"
        in scan_scope_context(f, c, policy(), now=AT).issues
    )


@pytest.mark.parametrize(
    "field,kind",
    [("flow", "OPTIONS_FLOW"), ("news", "BROAD_MARKET_NEWS"), ("events", "ECONOMIC_EVENTS")],
)
@pytest.mark.parametrize("change", [{"state": "UNKNOWN"}, {"valid_through": AT}])
def test_unknown_or_expired_context_does_not_become_neutral(field, kind, change):
    f = structure_frame()
    c = context(f)
    c = c.model_copy(update={field: getattr(c, field).model_copy(update=change)})
    assert kind + "_STATE_UNKNOWN_OR_EXPIRED" in scan(f, c).issues


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "field,reason",
    [
        ("flow", "OPTIONS_FLOW_OPPOSES_DIRECTION"),
        ("news", "BROAD_MARKET_NEWS_OPPOSES_DIRECTION"),
        ("events", "HIGH_IMPACT_EVENT_WINDOW"),
    ],
)
def test_context_risk_blocks_base_and_every_derived_variant(right, field, reason):
    f = structure_frame("trap_reversal", right)
    c = context(f)
    state = (
        "HIGH_IMPACT_WINDOW" if field == "events" else "BEARISH" if right == "CALL" else "BULLISH"
    )
    c = c.model_copy(update={field: getattr(c, field).model_copy(update={"state": state})})
    result = scan(f, c)
    assert not result.issues
    relevant = [
        o for o in result.observations if o.parent_pattern == "trap_reversal" and o.right == right
    ]
    assert len(relevant) == 5
    assert all(o.status == "BLOCKED" and reason in o.reasons for o in relevant)


def test_elevated_risk_stays_explicit_without_inventing_a_quality_score():
    f = structure_frame()
    c = context(f)
    c = c.model_copy(update={"events": c.events.model_copy(update={"state": "ELEVATED"})})
    result = scan(f, c)
    items = [
        o
        for o in result.observations
        if o.parent_pattern == "opening_range_break_hold" and o.right == "CALL"
    ]
    assert all(o.notes == ("ELEVATED_EVENT_RISK_REQUIRES_QUALITY_REVIEW",) for o in items)
    assert not {"quality_score", "quantity", "proposal"} & type(result).model_fields.keys()


@pytest.mark.parametrize(
    "moves,maximum,blocked", [("1", ".55", False), ("1", ".549999999999", True)]
)
def test_expected_move_consumption_uses_exact_fraction(moves, maximum, blocked):
    f = structure_frame()
    c = context(f)
    c = c.model_copy(update={"moves": c.moves.model_copy(update={"atm_straddle_move": D(moves)})})
    result = scan(f, c, policy(max_expected_move_consumed_fraction=maximum))
    item = next(
        o
        for o in result.observations
        if o.pattern == "opening_range_break_hold" and o.right == "CALL"
    )
    # Opening midpoint is 100.05; completed spot is 100.6.
    assert ("EXPECTED_MOVE_ALREADY_CONSUMED" in item.reasons) is blocked


@pytest.mark.parametrize(
    "defect", ["source", "date", "current_day", "late_receipt", "before_close", "delayed", "stale"]
)
def test_prior_session_identity_and_known_before_open_boundary(defect):
    f = structure_frame()
    c = context(f)
    p = c.prior
    changes = {
        "source": {"source": "foreign"},
        "date": {"session_date": p.session_date - timedelta(days=1)},
        "current_day": {"session_date": AT.date()},
        "late_receipt": {"source_at": f.session.opens_at, "received_at": f.session.opens_at},
        "before_close": {"source_at": p.closed_at - timedelta(seconds=1)},
        "delayed": {"entitlement": "DELAYED"},
        "stale": {
            "source_at": p.source_at - timedelta(days=5),
            "received_at": p.received_at - timedelta(days=5),
            "closed_at": p.closed_at - timedelta(days=5),
            "session_date": p.session_date - timedelta(days=5),
        },
    }[defect]
    c = c.model_copy(update={"prior": p.model_copy(update=changes)})
    result = scan(f, c)
    assert (
        "PRIOR_SESSION_BINDING_COVERAGE_OR_CHRONOLOGY" in result.issues and not result.observations
    )


def test_context_cannot_rescue_pending_neutral_reset_or_missing_pattern():
    f = structure_frame("failed_break_reversal", count=5)
    result = scan(f, now=AT - timedelta(minutes=5))
    assert not result.issues
    assert not any(
        o.parent_pattern == "failed_break_reversal" and o.pattern in CONTEXT_PATTERNS
        for o in result.observations
    )
    h = f.histories[0]
    bars = tuple(
        b.model_copy(update={k: D(100) for k in ("open", "high", "low", "close")}) for b in h.bars
    )
    f = bind_structure(
        f.model_copy(update={"histories": (h.model_copy(update={"bars": bars}), *f.histories[1:])})
    )
    result = scan(f, now=AT - timedelta(minutes=5))
    assert result.unmatched_context_patterns == CONTEXT_PATTERNS
    assert all(o.status == "WATCHING" for o in result.observations)


def test_far_levels_do_not_create_anchored_variants():
    f = structure_frame("trap_reversal")
    c = context(f)
    c = c.model_copy(
        update={
            "dealer": c.dealer.model_copy(update={"nodes": (D(200),)}),
            "moves": c.moves.model_copy(update={"reference_spot": D(200)}),
            "prior": c.prior.model_copy(update={"high": D(200), "low": D(190)}),
        }
    )
    result = scan(f, c)
    assert result.unmatched_context_patterns == CONTEXT_PATTERNS
    assert len(result.observations) == len(result.structure.observations)


def test_expiry_and_flow_news_kind_are_exact():
    f = structure_frame()
    c = context(f)
    wrong_expiry = c.model_copy(
        update={"moves": c.moves.model_copy(update={"expiration": AT.date() + timedelta(days=1)})}
    )
    assert "EXPECTED_MOVE_EXPIRY_MISMATCH" in scan(f, wrong_expiry).issues
    wrong_kind = c.model_copy(update={"flow": c.news.model_copy(update={"source": c.flow.source})})
    assert "OPTIONS_FLOW_KIND_MISMATCH" in scan(f, wrong_kind).issues


def test_inputs_policy_context_and_no_io(monkeypatch):
    import builtins
    import socket
    import sqlite3

    f = structure_frame("trap_reversal")
    c, p = context(f), policy()
    original = f.model_dump_json(), c.model_dump_json(), p.model_dump_json()
    expected = scan(f, c, p)

    def forbidden(*args, **kwargs):
        raise AssertionError("Context review performs no I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    with localcontext() as ctx:
        ctx.prec = 2
        assert scan(f, c, p) == expected
    assert (f.model_dump_json(), c.model_dump_json(), p.model_dump_json()) == original
    assert scan(f, c, policy(prior_proximity_points="2")).policy_hash != expected.policy_hash
    c2 = c.model_copy(update={"dealer": c.dealer.model_copy(update={"nodes": (D(100),)})})
    assert scan(f, c2).input_hash != expected.input_hash


def test_unsafe_copied_models_cannot_bypass_validation():
    f = structure_frame()
    c = context(f)
    with pytest.raises(ValidationError):
        scan(
            f,
            c.model_copy(
                update={"dealer": c.dealer.model_copy(update={"nodes": (D(100), D(100))})}
            ),
        )
    with pytest.raises(ValidationError):
        scan(f, c.model_copy(update={"flow": c.flow.model_copy(update={"scope": "BROAD_MARKET"})}))
    with pytest.raises(ValidationError):
        scan(
            f, c.model_copy(update={"moves": c.moves.model_copy(update={"atm_straddle_move": 1.5})})
        )


@pytest.mark.parametrize("beyond", [False, True])
def test_dealer_proximity_boundary_is_inclusive_and_decimal_exact(beyond):
    f = structure_frame()
    c = context(f)
    level = D("103.3") + (D(".000000000001") if beyond else D(0))
    c = c.model_copy(update={"dealer": c.dealer.model_copy(update={"nodes": (level,)})})
    items = [
        o
        for o in scan(f, c).observations
        if o.parent_pattern == "opening_range_break_hold" and o.right == "CALL"
    ]
    assert any(o.pattern == "dealer_level_acceptance" for o in items) is not beyond


def test_nearest_node_tie_is_stable_without_source_order_ranking():
    f = structure_frame()
    c = context(f)
    results = []
    for nodes in ((D(100), D("100.6")), (D("100.6"), D(100))):
        value = c.model_copy(update={"dealer": c.dealer.model_copy(update={"nodes": nodes})})
        results.append(
            next(
                o
                for o in scan(f, value).observations
                if o.pattern == "dealer_level_acceptance"
                and o.parent_pattern == "opening_range_break_hold"
                and o.right == "CALL"
            )
        )
    assert results[0] == results[1] and results[0].matched_level == D(100)


@pytest.mark.parametrize("defect", ["wrong_right", "unreachable_strike"])
def test_context_cannot_remove_exact_contract_blockers(defect):
    f = structure_frame()
    changes = {"right": "PUT"} if defect == "wrong_right" else {"strike": D(1000)}
    i = f.metadata.instrument.model_copy(
        update={"contract": f.metadata.instrument.contract.model_copy(update=changes)}
    )
    f = f.model_copy(
        update={
            "metadata": f.metadata.model_copy(
                update={
                    "instrument": i,
                    "delta": D("-.99") if defect == "wrong_right" else f.metadata.delta,
                }
            ),
            "quote": f.quote.model_copy(update={"instrument": i}),
        }
    )
    items = [
        o
        for o in scan(f).observations
        if o.parent_pattern == "opening_range_break_hold" and o.right == "CALL"
    ]
    assert len(items) == 1 and items[0].status == "BLOCKED"
    assert items[0].pattern == "opening_range_break_hold"
