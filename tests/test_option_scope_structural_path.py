"""Completed structural levels add obstructions, never a universal clear-path claim."""

from datetime import timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_context import bind
from test_option_scope_quality import inputs, policy, review
from test_option_scope_structure import bind as bind_structure
from test_option_scope_watch import call, choice, owned, revision
from test_option_scope_watch import policy as watch_policy

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.scope_quality import _structural_path, scan_scope_quality
from app.options.scope_watch import ScopeWatchBook

D = Decimal
VERSION = "completed-spx-levels-v1"


def synthetic(right, level):
    sign = 1 if right == "CALL" else -1
    baseline = D(100 - 10 * sign)
    bars = [
        SimpleNamespace(
            high=baseline + 1,
            low=baseline - 1,
            close=baseline,
            volume=100,
            ends_at=AT + timedelta(minutes=5 * i),
        )
        for i in range(5)
    ]
    if sign == 1:
        bars[1].high = level
    else:
        bars[1].low = level
    bars[-1].high, bars[-1].low, bars[-1].close = D("100.1"), D("99.9"), D(100)
    frame = SimpleNamespace(histories=(SimpleNamespace(symbol="SPX", bars=bars),))
    geometry = SimpleNamespace(target_one=D(100 + sign), target_two=D(100 + 2 * sign))
    return frame, geometry, sign


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "distance,retained,before",
    [
        (0, True, True),
        (1, True, True),
        (D("1.5"), True, False),
        (2, True, False),
        (3, False, False),
        (-1, False, False),
    ],
)
def test_directional_pivot_path_endpoints_and_confirmation_time(right, distance, retained, before):
    sign = 1 if right == "CALL" else -1
    level = D(100) + distance * sign
    f, g, sign = synthetic(right, level)
    levels = [
        p
        for p in _structural_path(f, g, sign)
        if p.kind == ("PIVOT_HIGH" if sign == 1 else "PIVOT_LOW")
    ]
    assert bool(levels) is retained
    if retained:
        assert len(levels) == 1 and levels[0].level == level
        assert levels[0].at_or_before_first_target is before
        assert levels[0].confirmed_at == f.histories[0].bars[2].ends_at


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_equal_neighbor_is_not_a_confirmed_pivot_and_last_bar_cannot_look_ahead(right):
    f, g, sign = synthetic(right, D(100) + (1 if right == "CALL" else -1))
    attr = "high" if sign == 1 else "low"
    bars = f.histories[0].bars
    setattr(bars[2], attr, getattr(bars[1], attr))
    setattr(bars[-1], attr, D(100) + sign)
    assert not any(p.kind.startswith("PIVOT") for p in _structural_path(f, g, sign))


def test_exact_vwap_comparison_cannot_be_changed_by_display_rounding():
    f, g, _ = synthetic("CALL", D(101))
    for b in f.histories[0].bars:
        b.high, b.low, b.close = D("100.1"), D("99.9"), D(100)
    f.histories[0].bars[0].high += D(".000000000001")
    g.target_one = D(100)
    levels = _structural_path(f, g, 1)
    vwap = next(p for p in levels if p.kind == "SESSION_VWAP")
    assert vwap.level == D(100)  # Display rounds down; exact value is above the objective.
    assert not vwap.at_or_before_first_target
    assert vwap.confirmed_at == f.histories[0].bars[-1].ends_at


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_public_scan_blocks_new_structural_obstruction_without_changing_score(right):
    f, c = inputs(right=right)
    original = review(f, c)
    h = f.histories[0]
    bars = list(h.bars)
    attr = "high" if right == "CALL" else "low"
    bars[1] = bars[1].model_copy(update={attr: original.observation.geometry.target_one})
    f = f.model_copy(
        update={"histories": (h.model_copy(update={"bars": tuple(bars)}), *f.histories[1:])}
    )
    f = bind(bind_structure(f), c)
    legacy = review(f, c)
    strict = review(f, c, p=policy(structural_path=VERSION))
    assert legacy.passed
    assert not strict.passed and "KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE" in strict.reasons
    assert strict.score == legacy.score and strict.components == legacy.components
    assert {p.kind for p in strict.potential_obstructions} >= {
        "OPENING_HIGH" if right == "CALL" else "OPENING_LOW",
        "PIVOT_HIGH" if right == "CALL" else "PIVOT_LOW",
    }
    assert not strict.complete_path_proven


@pytest.mark.parametrize("damage", ["missing_bar", "forming", "payload", "zero_volume"])
def test_incomplete_or_unbound_history_never_reaches_structural_review(damage):
    f, c = inputs()
    h = f.histories[0]
    if damage == "missing_bar":
        h = h.model_copy(update={"bars": h.bars[1:]})
    elif damage == "forming":
        h = h.model_copy(
            update={"bars": (*h.bars, h.bars[-1].model_copy(update={"begins_at": AT}))}
        )
    elif damage == "zero_volume":
        h = h.model_copy(
            update={"bars": (*h.bars[:-1], h.bars[-1].model_copy(update={"volume": 0}))}
        )
    else:
        h = h.model_copy(
            update={
                "bars": (*h.bars[:-1], h.bars[-1].model_copy(update={"high": h.bars[-1].high + 1}))
            }
        )
    f = f.model_copy(update={"histories": (h, *f.histories[1:])})
    out = scan_scope_quality(f, c, policy(structural_path=VERSION), now=AT)
    assert out.issues and not out.observations
    assert not out.authority


def test_absence_of_structural_obstructions_never_claims_complete_path():
    f, c = inputs()
    p = policy(structural_path=VERSION)
    before = scan_scope_quality(f, c, p, now=AT)
    with localcontext() as ctx:
        ctx.prec = 3
        assert scan_scope_quality(f, c, p, now=AT) == before
    selected = review(f, c, p=p)
    assert selected.passed and not selected.potential_obstructions
    assert not selected.complete_path_proven and not before.authority and not before.live_enabled


def test_opt_in_serialization_and_watch_policy_are_frozen(tmp_path):
    legacy, strict = policy(), policy(structural_path=VERSION)
    assert "structural_path" not in legacy.model_dump()
    assert fingerprint(legacy) != fingerprint(strict)
    with pytest.raises(ValidationError):
        policy(structural_path="caller-proven-clear")
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = ScopeWatchBook(engine, watch_policy(quality=legacy), now=AT, create=True)
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked, match="FROZEN_SCOPE_WATCH_POLICY_MISMATCH"):
            ScopeWatchBook(engine, watch_policy(quality=strict), now=AT)
        assert book.snapshot() == before


def test_new_watch_retains_structural_policy_in_locked_evidence(tmp_path):
    strict = policy(structural_path=VERSION)
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = ScopeWatchBook(engine, watch_policy(quality=strict), now=AT, create=True)
        f, _ = inputs()
        out = call(book, f=f)
        assert out["record"]["locked_quality_scan"]["policy_hash"] == fingerprint(strict)
        assert not out["authority"]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_structural_obstruction_cannot_consume_a_called_play(tmp_path, right):
    strict = policy(structural_path=VERSION)
    f, c = inputs(right=right)
    level = review(f, c).observation.geometry.target_one
    h = f.histories[0]
    bars = list(h.bars)
    bars[1] = bars[1].model_copy(update={"high" if right == "CALL" else "low": level})
    f = bind(
        bind_structure(
            f.model_copy(
                update={"histories": (h.model_copy(update={"bars": tuple(bars)}), *f.histories[1:])}
            )
        ),
        c,
    )
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = ScopeWatchBook(engine, watch_policy(quality=strict), now=AT, create=True)
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked, match="QUALITY"):
            book.call(
                "blocked",
                choice(right, pattern="trend_pullback_continuation"),
                f,
                c,
                now=AT,
                expected_revision=revision(engine),
            )
        assert book.snapshot() == before
