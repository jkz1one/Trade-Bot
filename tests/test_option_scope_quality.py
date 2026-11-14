"""Research scores explain evidence; they cannot erase blockers or authorize trades."""

from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_context import bind, context
from test_option_scope_context import policy as context_policy
from test_option_scope_structure import bind as bind_structure
from test_option_scope_structure import frame as structure_frame
from test_option_scope_watch import call, choice, owned
from test_option_scope_watch import policy as watch_policy

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.scope_quality import ScopeQualityPolicy, scan_scope_quality
from app.options.scope_watch import ScopeWatchBook, ScopeWatchPolicy

D = Decimal
BASE = {
    "opening_range_break_hold": 88,
    "vwap_reclaim_continuation": 86,
    "trend_pullback_continuation": 85,
    "compression_expansion": 84,
    "failed_reversal_continuation": 89,
    "failed_break_reversal": 90,
    "opening_drive_failure": 87,
    "vwap_rejection_reversal": 84,
    "trap_reversal": 93,
}


def policy(**changes):
    return ScopeQualityPolicy.model_validate(
        {
            "context": context_policy(),
            "observe_score": 80,
            "watching_score": 90,
            "arm_score": 94,
            "convexity_score": 97,
            "minimum_first_target_r": "1.5",
            **changes,
        }
    )


def inputs(pattern="trend_pullback_continuation", right="CALL"):
    f = structure_frame(pattern, right)
    c = context(f)
    return bind(f, c), c


def review(f, c, *, p=None, pattern="trend_pullback_continuation", parent=None):
    scan = scan_scope_quality(f, c, p or policy(), now=AT)
    assert not scan.issues, scan.issues
    return next(
        o
        for o in scan.observations
        if o.observation.pattern == pattern
        and o.observation.parent_pattern == (parent or pattern)
        and o.observation.right == f.metadata.instrument.contract.right
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("pattern,base", BASE.items())
def test_nine_source_base_scores_and_auditable_point_sum(right, pattern, base):
    f, c = inputs(pattern, right)
    out = review(f, c, pattern=pattern)
    assert out.base_score == base
    assert out.score == min(100, base + sum(x.points for x in out.components))
    assert not out.complete_path_proven
    assert out.first_target_r is not None
    assert len(out.components) == 7


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "variant,parent,bonus,cap",
    [
        ("dealer_level_acceptance", "trend_pullback_continuation", 2, 94),
        ("dealer_level_rejection", "trap_reversal", 2, 95),
        ("prior_level_break_retest", "trend_pullback_continuation", 2, 95),
        ("prior_level_rejection", "trap_reversal", 2, 95),
        ("implied_move_boundary_rejection", "trap_reversal", 3, 96),
        ("exhaustion_confluence_reversal", "trap_reversal", 5, 98),
    ],
)
def test_six_variant_scores_keep_exact_parent_lineage(right, variant, parent, bonus, cap):
    f, c = inputs(parent, right)
    # Explicit proximity envelope allows all six variants in these fixtures.
    p = policy(context=context_policy(boundary_proximity_points="10"))
    out = review(f, c, p=p, pattern=variant, parent=parent)
    assert out.base_score == min(cap, BASE[parent] + bonus)
    assert out.observation.parent_pattern == parent
    assert out.observation.geometry == review(f, c, p=p, pattern=parent).observation.geometry


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_passing_quality_is_not_execution_or_unobstructed_convexity(right):
    f, c = inputs(right=right)
    out = review(f, c)
    assert out.passed and out.score == 95 and out.grade == "ARM_THRESHOLD"
    variant = review(f, c, pattern="dealer_level_acceptance", parent="trend_pullback_continuation")
    assert variant.passed and variant.grade == "CONVEXITY_THRESHOLD"
    assert not variant.complete_path_proven
    scan = scan_scope_quality(f, c, policy(), now=AT)
    assert not scan.authority and not scan.live_enabled
    assert "quantity" not in scan.model_dump_json()


@pytest.mark.parametrize(
    "kind,aligned,points",
    [("flow", "BULLISH", 2), ("news", "BULLISH", 1), ("events", "ELEVATED", -4)],
)
def test_context_changes_score_with_explicit_components(kind, aligned, points):
    f, c = inputs()
    before = review(f, c)
    c = c.model_copy(update={kind: getattr(c, kind).model_copy(update={"state": aligned})})
    after = review(bind(f, c), c)
    assert after.score == before.score + points
    if kind == "events":
        assert not after.passed and "QUALITY_BELOW_ARM_THRESHOLD" in after.reasons


@pytest.mark.parametrize(
    "kind,state", [("flow", "BEARISH"), ("news", "BEARISH"), ("events", "HIGH_IMPACT_WINDOW")]
)
def test_context_rejection_cannot_be_rescued_by_scoring(kind, state):
    f, c = inputs("trap_reversal")
    c = c.model_copy(update={kind: getattr(c, kind).model_copy(update={"state": state})})
    out = review(bind(f, c), c, pattern="trap_reversal")
    assert out.score is None and out.grade == "UNSCORED" and not out.passed
    assert out.reasons


@pytest.mark.parametrize("kind", ["dealer", "moves", "flow", "news", "events", "prior"])
def test_missing_context_produces_no_quality_alternatives(kind):
    f, c = inputs()
    c = c.model_copy(update={kind: None})
    scan = scan_scope_quality(bind(f, c), c, policy(), now=AT)
    assert scan.issues == ("SCOPE_CONTEXT_BLOCKED",) and not scan.observations


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_one_cross_market_confirmation_gives_three_points(right):
    f, c = inputs(right=right)
    histories = []
    for h in f.histories:
        if h.symbol == "SPY":
            b = h.bars[-1]
            h = h.model_copy(
                update={
                    "bars": (
                        *h.bars[:-1],
                        b.model_copy(
                            update={
                                "open": D(100),
                                "close": D(100),
                                "low": D("99.9"),
                                "high": D("100.1"),
                            }
                        ),
                    )
                }
            )
        histories.append(h)
    f = bind_structure(f.model_copy(update={"histories": tuple(histories)}))
    out = review(f, c)
    assert out.score == 94 and out.passed
    assert out.components[0].points == 3


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "where,blocked",
    [
        ("spot", True),
        ("first", True),
        ("between", False),
        ("second", False),
        ("beyond", False),
        ("behind", False),
    ],
)
def test_known_level_path_boundaries_are_directional(right, where, blocked):
    f, c = inputs(right=right)
    g = review(f, c).observation.geometry
    spot = f.histories[0].bars[-1].close
    sign = 1 if right == "CALL" else -1
    level = {
        "spot": spot,
        "first": g.target_one,
        "between": (g.target_one + g.target_two) / 2,
        "second": g.target_two,
        "beyond": g.target_two + sign,
        "behind": spot - sign,
    }[where]
    c = c.model_copy(update={"dealer": c.dealer.model_copy(update={"nodes": (level,)})})
    out = review(bind(f, c), c)
    assert ("KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE" in out.reasons) == blocked
    assert bool(out.potential_obstructions) == (where not in {"beyond", "behind"})
    assert not out.complete_path_proven
    assert out.passed != blocked


def test_prior_and_expected_move_levels_are_retained_not_silently_ignored():
    f, c = inputs()
    c = c.model_copy(
        update={
            "prior": c.prior.model_copy(update={"high": D("100.8"), "low": D("100.7")}),
            "moves": c.moves.model_copy(update={"reference_spot": D("95.3")}),
        }
    )
    out = review(bind(f, c), c)
    assert {x.kind for x in out.potential_obstructions} == {"PRIOR_HIGH", "PRIOR_LOW", "ATM_UPPER"}
    assert not out.passed
    assert [x.level for x in out.potential_obstructions] == sorted(
        x.level for x in out.potential_obstructions
    )


def test_minimum_r_uses_exact_geometry_not_rounded_display():
    f, c = inputs()
    out = review(f, c, p=policy(minimum_first_target_r="1.500000000001"))
    assert out.first_target_r == D("1.5")
    assert "FIRST_TARGET_REWARD_BELOW_MINIMUM" in out.reasons
    assert not out.passed


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("spot,consumed", [("100.7499", False), ("100.75", True), ("100.9", True)])
def test_consumed_first_objective_does_not_pass_from_old_reference_reward(right, spot, consumed):
    f, c = inputs("opening_range_break_hold", right)
    value = D(spot) if right == "CALL" else 200 - D(spot)
    h = f.histories[0]
    bar = h.bars[-1].model_copy(
        update={
            "close": value,
            "high": max(h.bars[-1].open, value) + D(".2"),
            "low": min(h.bars[-1].open, value) - D(".2"),
        }
    )
    f = bind_structure(
        f.model_copy(
            update={
                "histories": (h.model_copy(update={"bars": (*h.bars[:-1], bar)}), *f.histories[1:])
            }
        )
    )
    out = review(f, c, pattern="opening_range_break_hold")
    assert ("FIRST_OBJECTIVE_ALREADY_CONSUMED" in out.reasons) == consumed
    assert out.passed != consumed


@pytest.mark.parametrize(
    "arm,convexity,grade,passed",
    [
        (94, 97, "ARM_THRESHOLD", True),
        (95, 97, "ARM_THRESHOLD", True),
        (96, 97, "WATCH", False),
        (95, 95, "CONVEXITY_THRESHOLD", True),
    ],
)
def test_threshold_equality_and_classification(arm, convexity, grade, passed):
    f, c = inputs()
    # The convexity source floor remains 97 even when arm/watch thresholds change.
    if convexity < 97:
        with pytest.raises(ValidationError):
            policy(arm_score=arm, convexity_score=convexity)
        return
    out = review(f, c, p=policy(arm_score=arm, convexity_score=convexity))
    assert out.grade == grade and out.passed == passed


def test_hashes_immutable_inputs_and_decimal_context_are_stable():
    f, c = inputs()
    p = policy()
    before = (f.model_dump_json(), c.model_dump_json(), p.model_dump_json())
    normal = scan_scope_quality(f, c, p, now=AT)
    with localcontext() as ctx:
        ctx.prec = 3
        low = scan_scope_quality(f, c, p, now=AT)
    assert low == normal
    assert normal.input_hash == fingerprint({"frame": f, "context": c})
    assert normal.policy_hash == fingerprint(p)
    assert before == (f.model_dump_json(), c.model_dump_json(), p.model_dump_json())


def test_opt_in_watch_locks_quality_and_old_policy_remains_unchanged(tmp_path):
    assert "quality" not in watch_policy().model_dump(mode="json")
    with owned(tmp_path, enroll=False) as (engine, _, _):
        p = watch_policy().model_copy(update={"quality": policy()})
        book = ScopeWatchBook(engine, p, now=AT, create=True)
        f, c = inputs()
        result = call(book, f=f, selected=choice(pattern="trend_pullback_continuation"))
        locked = result["record"]["locked_quality_scan"]
        assert locked == scan_scope_quality(f, c, policy(), now=AT).model_dump(mode="json")
        assert len(book.snapshot()["watches"]) == 1


def test_quality_rejection_does_not_consume_watch_call(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = ScopeWatchBook(
            engine,
            watch_policy().model_copy(update={"quality": policy(arm_score=96)}),
            now=AT,
            create=True,
        )
        f, _ = inputs()
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked, match="QUALITY_BLOCKED"):
            call(book, f=f, selected=choice(pattern="trend_pullback_continuation"))
        assert book.snapshot() == before


def test_quality_policy_cannot_disagree_with_watch_context():
    p = watch_policy().model_dump()
    p["quality"] = policy(context=context_policy(max_expected_move_consumed_fraction=".7"))
    with pytest.raises(ValidationError, match="context policies must match"):
        ScopeWatchPolicy.model_validate(p)


@pytest.mark.parametrize(
    "field,value",
    [
        ("arm_score", 93),
        ("observe_score", 79),
        ("watching_score", 89),
        ("convexity_score", 96),
        ("minimum_first_target_r", "1.49"),
        ("arm_score", True),
        ("watching_score", 98),
    ],
)
def test_quality_thresholds_cannot_weaken_baselines_or_reverse_order(field, value):
    with pytest.raises(ValidationError):
        policy(**{field: value})


@pytest.mark.parametrize("move,points", [("1.1", 3), ("1.099999999999", 1)])
def test_expected_move_half_boundary_is_exact(move, points):
    f, c = inputs()
    c = c.model_copy(update={"moves": c.moves.model_copy(update={"atm_straddle_move": D(move)})})
    out = review(bind(f, c), c)
    assert next(v.points for v in out.components if v.name == "EXPECTED_MOVE_REMAINING") == points


def test_two_r_bonus_uses_actual_target_geometry():
    f, c = inputs()
    cp = context_policy()
    cp = cp.model_copy(
        update={"structure": cp.structure.model_copy(update={"first_target_r": D(2)})}
    )
    out = review(f, c, p=policy(context=cp))
    assert out.first_target_r == 2 and out.score == 97
    assert next(v.points for v in out.components if v.name == "FIRST_TARGET_REWARD") == 2


def test_score_saturation_retains_all_components():
    f, c = inputs("trap_reversal")
    c = c.model_copy(
        update={
            "flow": c.flow.model_copy(update={"state": "BULLISH"}),
            "news": c.news.model_copy(update={"state": "BULLISH"}),
        }
    )
    out = review(bind(f, c), c, pattern="trap_reversal")
    assert out.score == 100
    assert out.base_score + sum(x.points for x in out.components) > 100


def test_quality_review_performs_no_io(monkeypatch):
    import builtins
    import socket
    import sqlite3

    f, c = inputs()
    p = policy()

    def forbidden(*args, **kwargs):
        raise AssertionError("quality must stay pure")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert scan_scope_quality(f, c, p, now=AT).observations
