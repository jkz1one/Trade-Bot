"""Scope admission must use current directional prices and the original locked play."""

from decimal import Decimal, localcontext

import pytest
from test_option_scope_observer import observer
from test_option_scope_owned_admission import evidence, policy, review, start
from test_option_scope_watch import owned, ready, revision

from app.options.engine import OptionExecution
from app.options.scope_watch import ScopeWatchBook

D = Decimal


def price_at(u, price):
    return u.model_copy(update={"bid": price, "ask": price})


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "distance,eligible",
    [(".599999999999", True), (".6", True), (".600000000001", False), ("1.49", False)],
)
def test_actual_reward_boundary_not_old_reference_or_rounded_display(
    tmp_path, right, distance, eligible
):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, right)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        before = book.snapshot()["watches"][0]
        g = before["geometry"]
        sign = 1 if right == "CALL" else -1
        price = D(g["invalidation"]) + sign * D(distance)
        out = review(book, fresh, c, price_at(u, price), now)["record"]
        r = out["admission_review"]
        path = r["entry_path"]
        assert r["eligible"] is eligible and path["passed"] is eligible
        assert path["geometry"] == g == out["geometry"]
        assert D(path["reference"]) == price
        assert D(path["minimum_first_target_r"]) == D("1.5")
        assert not path["complete_path_proven"] and not path["authority"]
        assert out["locked_frame"] == before["locked_frame"]
        assert out["arming"]["status"] == ("ARMED" if eligible else "RESET")
        if eligible:
            assert r["admission"]["quantity"] == 2
            assert D(r["admission"]["full_premium_loss"]) == D("415.60")
        else:
            assert r["reasons"] == ["SCOPE_CURRENT_FIRST_TARGET_R_TOO_LOW"]
            assert r["admission"]["outcome"] == "REJECTED"
            assert r["admission"]["quantity"] == 0
            assert r["admission"]["valid_until"] is None
        seen = observer(engine, now).report()
        assert seen["status"] == "OK"
        assert seen["scope"]["active_watch"]["admission"]["entry_path"] == path
        assert not seen["orders"] and not seen["fills"]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_adverse_quote_side_cannot_hide_behind_midpoint(tmp_path, right):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, right)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        # Midpoint equals the original passing reference; adverse side does not.
        u = u.model_copy(update={"bid": u.bid - D(".01"), "ask": u.ask + D(".01")})
        r = review(book, fresh, c, u, now)["record"]["admission_review"]
        assert not r["eligible"]
        assert D(r["entry_path"]["reference"]) == (u.ask if right == "CALL" else u.bid)
        assert r["reasons"] == ["SCOPE_CURRENT_FIRST_TARGET_R_TOO_LOW"]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("structural", [False, True])
def test_retreat_reveals_levels_behind_completed_close(tmp_path, right, structural):
    p = policy()
    if structural:
        quality = p.quality.model_copy(update={"structural_path": "completed-spx-levels-v1"})
        p = p.model_copy(
            update={
                "quality": quality,
                "contract": p.contract.model_copy(update={"quality": quality}),
            }
        )
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, right, watch_policy=p)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        sign = 1 if right == "CALL" else -1
        u = price_at(u, D(100) + sign * D(".1"))
        out = review(book, fresh, c, u, now)["record"]
        r = out["admission_review"]
        assert not r["eligible"] and out["arming"]["status"] == "RESET"
        assert r["reasons"] == ["SCOPE_CURRENT_KNOWN_LEVEL_BEFORE_FIRST_OBJECTIVE"]
        assert D(r["entry_path"]["first_target_r"]) == 14
        kinds = {v["kind"] for v in r["entry_path"]["potential_obstructions"]}
        assert ("PRIOR_HIGH" if right == "CALL" else "PRIOR_LOW") in kinds
        if structural:
            assert kinds >= {"SESSION_VWAP", "OPENING_HIGH" if right == "CALL" else "OPENING_LOW"}
        else:
            assert "SESSION_VWAP" not in kinds
        # The completed-close review passed: only the new current reference exposed this path.
        selected = next(
            o
            for o in out["arming"]["quality_scan"]["observations"]
            if all(o["observation"][k] == v for k, v in out["choice"].items())
        )
        assert selected["passed"] and not selected["potential_obstructions"]
        with engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 0


def test_rejected_review_retry_restart_and_independent_owner(tmp_path):
    with owned(tmp_path / "a", enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        u = price_at(u, D("101.49"))
        kwargs = {
            "frame": fresh,
            "context": c,
            "underlying": u,
            "now": now,
            "expected_revision": revision(engine),
        }
        receipt = book.review_admission("review", "first", **kwargs)
        assert not receipt["record"]["admission_review"]["eligible"]
        rev = revision(engine)
        assert book.review_admission("review", "first", **kwargs) == receipt
        assert revision(engine) == rev
        path, limits, epolicy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, epolicy, venue, now=now) as engine:
        book = ScopeWatchBook(engine, policy(), now=now)
        assert book.snapshot()["watches"][0] == receipt["record"]
        with owned(tmp_path / "b", enroll=False) as (other, venue_b, _):
            other_book, f = start(other, venue_b)
            fresh, c, u, now = evidence(other, f)
            ready(other, venue_b, now)
            assert review(other_book, fresh, c, u, now)["record"]["admission_review"]["eligible"]
        assert book.snapshot()["watches"][0] == receipt["record"]


def test_invalid_quote_never_gets_current_geometry_clearance(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        u = u.model_copy(update={"source": "wrong"})
        r = review(book, fresh, c, u, now)["record"]["admission_review"]
        assert not r["eligible"] and r["entry_path"] is None
        assert r["reasons"] == ["UNDERLYING_SOURCE_OR_SYMBOL_MISMATCH"]


def test_current_path_arithmetic_is_independent_of_ambient_precision():
    from test_option_scope import AT
    from test_option_scope_contract import data
    from test_option_scope_quality import policy as quality_policy
    from test_option_scope_quality import review as quality_review

    from app.options.models import UnderlyingQuote
    from app.options.scope_admission import _review_entry_path

    f, c = data()
    g = quality_review(f, c).observation.geometry.model_dump()
    u = UnderlyingQuote(
        symbol="SPX",
        source="fixture",
        source_at=AT,
        received_at=AT,
        complete=True,
        entitlement="REALTIME",
        bid="100.600000000001",
        ask="100.600000000001",
    )
    with localcontext() as ctx:
        ctx.prec = 6
        r = _review_entry_path(f, c, g, quality_policy(), u, now=AT)
    assert not r.passed and r.reasons == ("SCOPE_CURRENT_FIRST_TARGET_R_TOO_LOW",)
