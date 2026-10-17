"""Confirmed equal-extreme runs join the frozen Scope path without claiming clearance."""

from datetime import timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_arming import refresh
from test_option_scope_context import bind, context
from test_option_scope_contract import data
from test_option_scope_observer import observer
from test_option_scope_owned_admission import evidence
from test_option_scope_owned_admission import policy as admission_policy
from test_option_scope_owned_admission import review as admit
from test_option_scope_quality import policy, review
from test_option_scope_structure import bind as bind_structure
from test_option_scope_watch import append, choice, owned, ready, revision
from test_option_scope_watch import policy as watch_policy

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution, fingerprint
from app.options.scope_quality import ScopePathLevel, _plateau_path, scan_scope_quality
from app.options.scope_watch import ScopeWatchBook

D = Decimal
VERSION = "completed-spx-plateaus-v2"


def synthetic(right, distance, *, count=2):
    sign = 1 if right == "CALL" else -1
    value = D(100) + D(distance) * sign
    bars = []
    for i in range(count + 2):
        extreme = value if 0 < i <= count else value - sign
        bars.append(
            SimpleNamespace(
                high=extreme if sign == 1 else D(110),
                low=extreme if sign == -1 else D(90),
                begins_at=AT + timedelta(minutes=5 * i),
                ends_at=AT + timedelta(minutes=5 * (i + 1)),
            )
        )
    f = SimpleNamespace(histories=(SimpleNamespace(symbol="SPX", bars=bars),))
    g = SimpleNamespace(target_one=D(100 + sign), target_two=D(100 + 2 * sign))
    return f, g, sign


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "distance,retained,before",
    [
        ("-.000000000001", False, False),
        ("0", True, True),
        ("1", True, True),
        ("1.000000000001", True, False),
        ("2", True, False),
        ("2.000000000001", False, False),
    ],
)
def test_directional_inclusive_boundaries_and_exact_prices(right, distance, retained, before):
    f, g, sign = synthetic(right, distance)
    levels = _plateau_path(f, g, sign, spot=D(100))
    assert bool(levels) is retained
    if retained:
        assert len(levels) == 1
        p = levels[0]
        assert p.kind == ("PLATEAU_HIGH" if sign == 1 else "PLATEAU_LOW")
        assert p.level == D(100) + D(distance) * sign
        assert p.at_or_before_first_target is before and p.touches == 2
        bars = f.histories[0].bars
        assert p.formation_started_at == bars[1].begins_at
        assert p.formation_ended_at == bars[2].ends_at
        assert p.confirmed_at == bars[3].ends_at


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("count", [2, 3, 94])
def test_maximal_run_is_one_level_and_unconfirmed_prefix_is_not_lookahead(right, count):
    f, g, sign = synthetic(right, "1", count=count)
    full = _plateau_path(f, g, sign, spot=D(100))
    assert len(full) == 1 and full[0].touches == count
    f.histories[0].bars = f.histories[0].bars[:-1]
    assert not _plateau_path(f, g, sign, spot=D(100))
    # A session-edge run cannot use an invented left neighbor.
    f.histories[0].bars = f.histories[0].bars[1:]
    assert not _plateau_path(f, g, sign, spot=D(100))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("damage", ["left", "right", "unequal", "single"])
def test_no_epsilon_or_missing_strict_neighbor_creates_plateau(right, damage):
    f, g, sign = synthetic(right, "1")
    bars = f.histories[0].bars
    attr = "high" if sign == 1 else "low"
    value = getattr(bars[1], attr)
    if damage in ("left", "right"):
        setattr(bars[0 if damage == "left" else -1], attr, value + sign)
    elif damage == "unequal":
        setattr(bars[2], attr, value + sign * D(".000000000001"))
    else:
        del bars[2]
    assert not _plateau_path(f, g, sign, spot=D(100))


def plateau_frame(right, distance="1.5"):
    f, c = data(right)
    sign = 1 if right == "CALL" else -1
    h = f.histories[0]
    bars = list(h.bars)
    for i in (3, 4):
        bars[i] = bars[i].model_copy(
            update={"high" if sign == 1 else "low": D(100) + sign * D(distance)}
        )
    f = f.model_copy(
        update={"histories": (h.model_copy(update={"bars": tuple(bars)}), *f.histories[1:])}
    )
    return bind(bind_structure(f), c), c


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_public_quality_adds_only_plateau_gate_preserving_score_and_old_version(right):
    f, c = plateau_frame(right)
    old = review(f, c, p=policy(structural_path="completed-spx-levels-v1"))
    new = review(f, c, p=policy(structural_path=VERSION))
    assert old.passed and not old.potential_obstructions
    assert not new.passed and new.reasons == ("KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE",)
    assert (new.score, new.components, new.observation.geometry) == (
        old.score,
        old.components,
        old.observation.geometry,
    )
    assert len(new.potential_obstructions) == 1
    assert new.potential_obstructions[0].kind.startswith("PLATEAU")
    assert not new.complete_path_proven
    with localcontext() as ctx:
        ctx.prec = 3
        assert review(f, c, p=policy(structural_path=VERSION)) == new


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_blocked_call_consumes_no_watch_revision_cash_or_model_charge(tmp_path, right):
    f, c = plateau_frame(right)
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = ScopeWatchBook(
            engine, watch_policy(quality=policy(structural_path=VERSION)), now=AT, create=True
        )
        before, rev = book.snapshot(), revision(engine)
        account = engine.journal.report(now=AT)
        with pytest.raises(ExecutionBlocked, match="QUALITY"):
            book.call(
                "first",
                choice(right, "trend_pullback_continuation"),
                f,
                c,
                now=AT,
                expected_revision=rev,
            )
        assert book.snapshot() == before and revision(engine) == rev
        after = engine.journal.report(now=AT)
        assert (after["ledger"], after["economics"]) == (account["ledger"], account["economics"])
        assert not after["orders"]


def enrolled_policy():
    p = admission_policy()
    q = p.quality.model_copy(update={"structural_path": VERSION})
    return p.model_copy(
        update={"quality": q, "contract": p.contract.model_copy(update={"quality": q})}
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_later_objective_plateau_persists_through_arming_admission_observer_restart(
    tmp_path, right
):
    f, c = plateau_frame(right, "1.7")
    p = enrolled_policy()
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = ScopeWatchBook(engine, p, now=AT, create=True)
        called = book.call(
            "first",
            choice(right, "trend_pullback_continuation"),
            f,
            c,
            now=AT,
            expected_revision=revision(engine),
        )
        for seconds in range(0, 60, 10):
            now = AT + timedelta(seconds=seconds)
            ready(engine, venue, now)
            fresh, context = refresh(f, now)
            book.observe_arming(
                f"sample-{seconds}",
                "first",
                frame=fresh,
                context=context,
                now=now,
                expected_revision=revision(engine),
            )
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        receipt = admit(book, fresh, c, u, now)
        r = receipt["record"]["admission_review"]
        assert r["eligible"] and r["admission"]["quantity"] == 2
        assert D(r["admission"]["full_premium_loss"]) == D("415.60")
        levels = r["entry_path"]["potential_obstructions"]
        assert len(levels) == 1 and levels[0]["kind"].startswith("PLATEAU")
        assert not levels[0]["at_or_before_first_target"]
        assert not r["entry_path"]["complete_path_proven"]
        assert called["record"]["locked_quality_scan"]["policy_hash"] == fingerprint(p.quality)
        rev = revision(engine)
        seen = observer(engine, now).report()
        assert seen["scope"]["active_watch"]["admission"]["entry_path"] == r["entry_path"]
        assert revision(engine) == rev and not seen["orders"] and not seen["fills"]
        path, limits, epolicy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, epolicy, venue, now=now) as engine:
        book = ScopeWatchBook(engine, p, now=now)
        assert book.snapshot()["watches"][0] == receipt["record"]
        assert (
            observer(engine, now).report()["scope"]["active_watch"]["admission"]["entry_path"]
            == r["entry_path"]
        )
        legacy = admission_policy()
        with pytest.raises(ExecutionBlocked, match="FROZEN_SCOPE_WATCH_POLICY_MISMATCH"):
            ScopeWatchBook(engine, legacy, now=now)


@pytest.mark.parametrize("damage", ["payload", "missing", "future"])
def test_invalid_history_never_supplies_plateau_clearance(damage):
    f, c = plateau_frame("CALL")
    h = f.histories[0]
    if damage == "payload":
        h = h.model_copy(
            update={"bars": (*h.bars[:-1], h.bars[-1].model_copy(update={"high": D(102)}))}
        )
    elif damage == "missing":
        h = h.model_copy(update={"bars": h.bars[1:]})
    else:
        h = h.model_copy(update={"source_at": AT + timedelta(seconds=1)})
    f = f.model_copy(update={"histories": (h, *f.histories[1:])})
    scan = scan_scope_quality(f, c, policy(structural_path=VERSION), now=AT)
    assert scan.issues and not scan.observations and not scan.authority


def test_plateau_records_require_confirmation_and_cannot_disguise_legacy_levels():
    f, g, sign = synthetic("CALL", "1")
    p = _plateau_path(f, g, sign, spot=D(100))[0]
    for changes in (
        {"touches": None},
        {"confirmed_at": p.formation_ended_at},
        {"kind": "PIVOT_HIGH"},
    ):
        with pytest.raises(ValidationError):
            ScopePathLevel.model_validate(p.model_dump() | changes)
    legacy = ScopePathLevel(kind="PIVOT_HIGH", level="101", at_or_before_first_target=True)
    assert set(legacy.model_dump()) == {"kind", "level", "at_or_before_first_target"}
    assert "structural_path" not in policy().model_dump()


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_new_confirmation_resets_arming_without_rewriting_original_watch(tmp_path, right):
    f, c = data(right)
    sign = 1 if right == "CALL" else -1
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = ScopeWatchBook(engine, enrolled_policy(), now=AT, create=True)
        called = book.call(
            "first",
            choice(right, "trend_pullback_continuation"),
            f,
            c,
            now=AT,
            expected_revision=revision(engine),
        )
        # The last locked bar is the first touch. A second touch has no right
        # confirmation yet; only the following completed lower-high/higher-low bar confirms it.
        kwargs = {"high" if sign == 1 else "low": str(D(100) + sign * D(".8"))}
        f = append(f, close=str(D(100) + sign * D(".65")), **kwargs)
        kwargs = {"high" if sign == 1 else "low": str(D(100) + sign * D(".7"))}
        f = append(f, close=str(D(100) + sign * D(".7")), **kwargs)
        now = f.histories[0].received_at
        ready(engine, venue, now)
        result = book.observe_arming(
            "confirmation",
            "first",
            frame=f,
            context=context(f),
            now=now,
            expected_revision=revision(engine),
        )["record"]
        assert result["arming"]["status"] == "RESET"
        assert result["arming"]["reasons"] == ["SCOPE_WATCH_QUALITY_BLOCKED"]
        selected = next(
            o
            for o in result["arming"]["quality_scan"]["observations"]
            if all(o["observation"][k] == v for k, v in result["choice"].items())
        )
        level = next(
            p for p in selected["potential_obstructions"] if p["kind"].startswith("PLATEAU")
        )
        assert level["touches"] == 2 and level["at_or_before_first_target"]
        assert result["locked_frame"] == called["record"]["locked_frame"]
        assert result["geometry"] == called["record"]["geometry"]
        assert len(book.snapshot()["watches"]) == 1


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_plateau_on_current_entry_path_uses_adverse_quote_side(right):
    from app.options.models import UnderlyingQuote
    from app.options.scope_admission import _review_entry_path

    f, c = plateau_frame(right, "1.5")
    g = review(f, c).observation.geometry
    u = UnderlyingQuote(
        symbol="SPX",
        source="fixture",
        source_at=AT,
        received_at=AT,
        complete=True,
        entitlement="REALTIME",
        bid="100.599999999999" if right == "CALL" else "99.4",
        ask="100.6" if right == "CALL" else "99.400000000001",
    )
    result = _review_entry_path(f, c, g, policy(structural_path=VERSION), u, now=AT)
    assert not result.passed
    assert result.reasons == ("SCOPE_CURRENT_KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE",)
    assert result.reference == (u.ask if right == "CALL" else u.bid)
    assert any(p.kind.startswith("PLATEAU") for p in result.potential_obstructions)
