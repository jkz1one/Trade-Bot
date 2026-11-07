"""Exact profile gates cannot turn cheap contracts or research scores into authority."""

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_arming import refresh
from test_option_scope_context import bind
from test_option_scope_quality import inputs
from test_option_scope_quality import policy as quality_policy
from test_option_scope_watch import choice, owned, revision
from test_option_scope_watch import policy as watch_policy

from app.execution.engine import ExecutionBlocked
from app.options.scope_contract import ScopeContractPolicy, scan_scope_contract
from app.options.scope_watch import ScopeArmingPolicy, ScopeWatchBook


def policy(**changes):
    return ScopeContractPolicy.model_validate(
        {
            "quality": quality_policy(),
            "minimum_ask": ".2",
            "cheap_ceiling": "1.25",
            "medium_ceiling": "2.5",
            "maximum_ask": "5",
            "maximum_spread_fraction": ".15",
            "minimum_volume": 0,
            "minimum_open_interest": 0,
            **changes,
        }
    )


def data(right="CALL", *, delta=".32", ask="2", pattern="trend_pullback_continuation"):
    f, c = inputs(pattern, right)
    f = f.model_copy(
        update={
            "metadata": f.metadata.model_copy(
                update={
                    "delta": Decimal(delta) * (1 if right == "CALL" else -1),
                    "greek_provenance": "OBSERVED",
                    "volume": 100,
                    "open_interest": 200,
                }
            ),
            "quote": f.quote.model_copy(update={"ask": Decimal(ask), "bid": Decimal(ask)}),
        }
    )
    return f, c


def selected(f, c, *, p=None, pattern="trend_pullback_continuation", parent=None):
    out = scan_scope_contract(f, c, p or policy(), now=AT)
    assert not out.issues, out.issues
    assert not out.authority and not out.live_enabled
    return next(
        o
        for o in out.observations
        if o.pattern == pattern
        and o.parent_pattern == (parent or pattern)
        and o.right == f.metadata.instrument.contract.right
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "delta,ask,profile",
    [
        (".479999", "2.5", "BALANCED"),
        (".48", "2.5", "RESPONSIVE"),
        (".99", "2", "RESPONSIVE"),
        (".32", "2.55", "RESPONSIVE"),
        (".32", ".2", "BALANCED"),
        (".32", "5", "RESPONSIVE"),
    ],
)
def test_profiles_and_price_boundaries(right, delta, ask, profile):
    f, c = data(right, delta=delta, ask=ask)
    result = selected(f, c)
    assert result.passed and result.profile == profile
    assert result.target_abs_delta == Decimal(".5" if profile == "RESPONSIVE" else ".32")


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("delta,profile", [(".349999", "BALANCED"), (".35", "RESPONSIVE")])
def test_reversals_favor_responsiveness(right, delta, profile):
    f, c = data(right, delta=delta, pattern="trap_reversal")
    out = selected(f, c, pattern="trap_reversal")
    assert out.profile == profile and out.passed


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_convexity_classification_cannot_bypass_missing_complete_path(right):
    f, c = data(right, delta=".2", ask="1.25")
    out = selected(f, c, pattern="dealer_level_acceptance", parent="trend_pullback_continuation")
    assert out.profile == "CONVEXITY" and not out.passed
    assert out.reasons == ("CONVEXITY_COMPLETE_PATH_UNPROVEN",)
    assert out.target_abs_delta == Decimal(".18")
    # Lower quality keeps the original balanced branch, not invented convexity permission.
    assert selected(f, c).profile == "BALANCED"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("delta", None, "OBSERVED_NONZERO_DELTA_REQUIRED"),
        ("delta", Decimal(0), "OBSERVED_NONZERO_DELTA_REQUIRED"),
        ("greek_provenance", "ESTIMATED", "OBSERVED_NONZERO_DELTA_REQUIRED"),
        ("greek_provenance", "UNAVAILABLE", "OBSERVED_NONZERO_DELTA_REQUIRED"),
        ("volume", None, "CONTRACT_VOLUME_UNAVAILABLE_OR_LOW"),
        ("open_interest", None, "CONTRACT_OPEN_INTEREST_UNAVAILABLE_OR_LOW"),
    ],
)
def test_unknowns_do_not_become_zero_or_ranking_defaults(field, value, reason):
    f, c = data()
    f = f.model_copy(update={"metadata": f.metadata.model_copy(update={field: value})})
    if field == "delta" and value == 0:
        scan = scan_scope_contract(f, c, policy(), now=AT)
        assert scan.issues == ("SCOPE_QUALITY_BLOCKED",) and not scan.observations
        return
    out = selected(f, c)
    assert not out.passed and out.profile is None and reason in out.reasons


@pytest.mark.parametrize("ask", [".15", "5.10"])
def test_ask_outside_bounds(ask):
    f, c = data(ask=ask)
    assert "CONTRACT_ASK_OUTSIDE_POLICY" in selected(f, c).reasons


@pytest.mark.parametrize("spread,passed", [(".15", True), (".149999999999", False)])
def test_exact_midpoint_spread_boundary(spread, passed):
    f, c = data(ask="2.15")
    f = f.model_copy(update={"quote": f.quote.model_copy(update={"bid": Decimal("1.85")})})
    assert selected(f, c, p=policy(maximum_spread_fraction=spread)).passed is passed


def test_quality_failure_and_stale_identity_are_not_rescued():
    f, c = data()
    c = c.model_copy(update={"flow": c.flow.model_copy(update={"state": "BEARISH"})})
    assert not selected(bind(f, c), c).passed
    out = scan_scope_contract(f, c, policy(), now=AT + timedelta(seconds=40))
    assert out.issues and not out.observations


def test_threshold_liquidity_and_frozen_policy():
    f, c = data()
    assert selected(f, c, p=policy(minimum_volume=100, minimum_open_interest=200)).passed
    assert not selected(f, c, p=policy(minimum_volume=101)).passed
    assert not selected(f, c, p=policy(minimum_open_interest=201)).passed
    with pytest.raises(ValidationError):
        policy(cheap_ceiling="3")
    with pytest.raises(ValidationError):
        watch_policy(contract=policy())
    assert "contract" not in watch_policy().model_dump()


def test_watch_call_and_arming_recompute_current_contract_gates(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        p = watch_policy(
            quality=quality_policy(),
            contract=policy(),
            arming=ScopeArmingPolicy(confirmation_hold_seconds=60, max_sample_gap_seconds=10),
        )
        book = ScopeWatchBook(engine, p, now=AT, create=True)
        f, c = data()
        out = book.call(
            "first",
            choice(pattern="trend_pullback_continuation"),
            f,
            c,
            expected_revision=revision(engine),
            now=AT,
        )
        assert out["record"]["locked_contract_scan"]["observations"]
        out = book.observe_arming(
            "sample", "first", frame=f, context=c, now=AT, expected_revision=revision(engine)
        )
        assert out["record"]["arming"]["status"] == "HOLDING"
        now = AT + timedelta(seconds=1)
        f, c = refresh(f, now)
        f = f.model_copy(update={"metadata": f.metadata.model_copy(update={"volume": None})})
        out = book.observe_arming(
            "bad", "first", frame=f, context=c, now=now, expected_revision=revision(engine)
        )
        assert out["record"]["arming"]["status"] == "RESET"
        assert out["record"]["arming"]["reasons"] == ["SCOPE_WATCH_CONTRACT_BLOCKED"]
        assert out["record"]["arming"]["contract_scan"]
        with pytest.raises(ExecutionBlocked, match="FROZEN"):
            ScopeWatchBook(engine, p.model_copy(update={"contract": None}), now=now)


def test_rejected_contract_call_consumes_no_play_or_event(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = ScopeWatchBook(
            engine, watch_policy(quality=quality_policy(), contract=policy()), now=AT, create=True
        )
        f, c = data(ask="5.10")
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked, match="CONTRACT_BLOCKED"):
            book.call(
                "first",
                choice(pattern="trend_pullback_continuation"),
                f,
                c,
                expected_revision=revision(engine),
                now=AT,
            )
        assert book.snapshot() == before


@pytest.mark.parametrize(
    "delta,ask,profile",
    [(".249999", "1.25", "CONVEXITY"), (".25", "1.25", "BALANCED"), (".2", "1.30", "BALANCED")],
)
def test_convexity_strict_delta_and_inclusive_price_boundaries(delta, ask, profile):
    f, c = data(delta=delta, ask=ask)
    out = selected(f, c, pattern="dealer_level_acceptance", parent="trend_pullback_continuation")
    assert out.profile == profile
    assert out.passed is (profile != "CONVEXITY")


def test_hashes_bind_price_metadata_policy_and_clock_is_validated():
    f, c = data()
    a = scan_scope_contract(f, c, policy(), now=AT)
    f2 = f.model_copy(update={"metadata": f.metadata.model_copy(update={"volume": 101})})
    b = scan_scope_contract(f2, c, policy(), now=AT)
    d = scan_scope_contract(f, c, policy(minimum_volume=1), now=AT)
    assert a.input_hash != b.input_hash and a.policy_hash == b.policy_hash
    assert a.input_hash == d.input_hash and a.policy_hash != d.policy_hash
    with pytest.raises(ValueError):
        scan_scope_contract(f, c, policy(), now=AT.replace(tzinfo=None))
