"""Scope sizing uses the owner's governor and ledger, never caller balances or quantity."""

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_arming import refresh
from test_option_scope_contract import data
from test_option_scope_contract import policy as contract_policy
from test_option_scope_quality import policy as quality_policy
from test_option_scope_watch import choice, owned, ready, revision
from test_option_scope_watch import policy as watch_policy

from app.execution.engine import ExecutionBlocked
from app.options.governor import admit_option
from app.options.models import (
    OptionAccount,
    OptionLimits,
    OptionProposal,
    SessionWindow,
    UnderlyingQuote,
)
from app.options.scope_admission import ScopeAdmissionPolicy
from app.options.scope_watch import ScopeArmingPolicy, ScopeWatchBook

D = Decimal


def policy(debit="500"):
    return watch_policy(
        quality=quality_policy(),
        contract=contract_policy(),
        arming=ScopeArmingPolicy(confirmation_hold_seconds=60, max_sample_gap_seconds=10),
        admission=ScopeAdmissionPolicy(max_entry_debit=debit),
    )


def start(engine, venue, right="CALL", debit="500", *, watch_policy=None):
    book = ScopeWatchBook(engine, watch_policy or policy(debit), now=AT, create=True)
    f, c = data(right)
    book.call(
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
        fresh, c = refresh(f, now)
        book.observe_arming(
            f"sample-{seconds}",
            "first",
            frame=fresh,
            context=c,
            now=now,
            expected_revision=revision(engine),
        )
    return book, f


def evidence(engine, f, seconds=60):
    now = AT + timedelta(seconds=seconds)
    fresh, c = refresh(f, now)
    price = fresh.histories[0].bars[-1].close
    u = UnderlyingQuote(
        symbol="SPX",
        source=engine.limits.underlying_source,
        source_at=now,
        received_at=now,
        complete=True,
        entitlement="REALTIME",
        bid=price,
        ask=price,
    )
    return fresh, c, u, now


def review(book, fresh, c, u, now, key="review"):
    return book.review_admission(
        key,
        "first",
        frame=fresh,
        context=c,
        underlying=u,
        now=now,
        expected_revision=revision(book.engine),
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_owned_sizing_matches_native_governor_with_split_exit_fees(tmp_path, right):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, right)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        out = review(book, fresh, c, u, now)
        r = out["record"]["admission_review"]
        assert r["eligible"] and not r["authority"] and not out["authority"]
        a = r["admission"]
        expected = admit_option(
            OptionProposal.model_validate(r["proposal"]),
            fresh.quote,
            u,
            OptionAccount.model_validate(r["account"]),
            OptionLimits.model_validate(r["effective_limits"]),
            SessionWindow.model_validate(r["session"]),
            now=now,
        )
        assert a == expected.model_dump(mode="json")
        assert a["quantity"] == 2
        assert D(a["limit_price"]) == D("2.05")
        assert D(a["entry_debit"]) == D("412.30")
        assert D(a["reserved_exit_fees"]) == D("3.30")
        assert D(a["full_premium_loss"]) == D("415.60")
        assert r["index_session"] == f.session.model_dump(mode="json")
        assert r["session"]["entry_cutoff_at"] == f.session.entry_cutoff_at.isoformat().replace(
            "+00:00", "Z"
        )
        assert r["proposal"]["underlying_invalidation"] == out["record"]["geometry"]["invalidation"]
        with engine.journal.read() as db:
            for table in (
                "execution_orders",
                "execution_option_decisions",
                "execution_model_calls",
            ):
                assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert out["record"]["status"] == "WATCHING"


@pytest.mark.parametrize(
    "debit,quantity",
    [("412.30", 2), ("412.299999999999", 1), ("206.65", 1), ("206.649999999999", 0)],
)
def test_exact_fee_inclusive_debit_boundaries(tmp_path, debit, quantity):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, debit=debit)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        r = review(book, fresh, c, u, now)["record"]["admission_review"]
        assert r["admission"]["quantity"] == quantity
        assert r["eligible"] is (quantity > 0)


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("missing", "UNDERLYING_EVIDENCE_MISSING"),
        ("stale", "INVALID_UNDERLYING_QUOTE"),
        ("source", "UNDERLYING_SOURCE_OR_SYMBOL_MISMATCH"),
        ("stop", "INVALID_UNDERLYING_INVALIDATION"),
        ("size", "NO_EXECUTABLE_ASK_SIZE"),
    ],
)
def test_current_governor_gates_are_not_bypassed(tmp_path, failure, reason):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        if failure == "missing":
            u = None
        elif failure == "stale":
            u = u.model_copy(update={"source_at": AT, "received_at": AT})
        elif failure == "source":
            u = u.model_copy(update={"source": "wrong"})
        elif failure == "stop":
            stop = D(book.snapshot()["watches"][0]["geometry"]["invalidation"])
            u = u.model_copy(update={"bid": stop, "ask": stop})
        else:
            fresh = fresh.model_copy(
                update={"quote": fresh.quote.model_copy(update={"ask_size": 0})}
            )
        r = review(book, fresh, c, u, now)["record"]["admission_review"]
        assert not r["eligible"]
        if failure == "size":
            assert r["reasons"] == ["SCOPE_WATCH_QUALITY_BLOCKED"]
        else:
            assert reason in r["reasons"]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_current_target_crossing_resets_hold(tmp_path, right):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, right)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        target = D(book.snapshot()["watches"][0]["geometry"]["target_one"])
        u = u.model_copy(update={"bid": target, "ask": target})
        out = review(book, fresh, c, u, now)["record"]
        assert out["arming"]["status"] == "RESET"
        assert out["admission_review"]["reasons"] == ["SCOPE_CURRENT_FIRST_OBJECTIVE_CONSUMED"]
        assert not out["admission_review"]["eligible"]


def test_unfinished_hold_cannot_size_and_retries_are_historical(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f, 59)
        ready(engine, venue, now)
        kwargs = {
            "frame": fresh,
            "context": c,
            "underlying": u,
            "now": now,
            "expected_revision": revision(engine),
        }
        first = book.review_admission("review", "first", **kwargs)
        assert first["record"]["arming"]["status"] == "HOLDING"
        assert first["record"]["admission_review"]["admission"] is None
        assert book.review_admission("review", "first", **kwargs) == first
        fresh, c, u, now = evidence(engine, f, 60)
        ready(engine, venue, now)
        assert review(book, fresh, c, u, now, key="next")["record"]["admission_review"]["eligible"]
        assert book.review_admission("review", "first", **kwargs) == first
        assert book.snapshot()["watches"][0]["admission_review"]["eligible"]


def test_global_owner_block_cannot_size_and_native_activity_stays_blocked(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f, 80)
        out = review(book, fresh, c, u, now)["record"]
        assert not out["admission_review"]["eligible"] and out["arming"]["status"] == "RESET"
        engine.prepare("hold", OptionProposal(action="HOLD", thesis="fixture"), now=now)
        with pytest.raises(ExecutionBlocked, match="EXECUTION_LINK_NOT_IMPLEMENTED"):
            review(book, fresh, c, u, now, key="native")


def test_opt_in_and_policy_bounds(tmp_path):
    assert "admission" not in watch_policy().model_dump()
    with pytest.raises(ValidationError):
        watch_policy(admission=ScopeAdmissionPolicy(max_entry_debit="500"))
    for value in ("0", "500.01"):
        with pytest.raises(ValidationError):
            ScopeAdmissionPolicy(max_entry_debit=value)
    with (
        owned(tmp_path) as (engine, _, book),
        pytest.raises(ExecutionBlocked, match="NOT_ENROLLED"),
    ):
        book.review_admission("x", "first", now=AT, expected_revision=revision(engine))


@pytest.mark.parametrize(
    "loss,quantity",
    [("415.60", 2), ("415.599999999999", 1), ("208.30", 1), ("208.299999999999", 0)],
)
def test_full_loss_reserves_all_exit_order_fees(tmp_path, loss, quantity):
    with owned(tmp_path, enroll=False, max_full_premium_loss=loss) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        r = review(book, fresh, c, u, now)["record"]["admission_review"]
        assert r["admission"]["quantity"] == quantity


def test_review_survives_owner_restart_and_other_accounts_are_unchanged(tmp_path):
    from app.options.engine import OptionExecution

    with owned(tmp_path / "a", enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        expected = review(book, fresh, c, u, now)["record"]
        path, limits, epolicy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, epolicy, venue, now=now) as engine:
        book = ScopeWatchBook(engine, policy(), now=now)
        assert book.snapshot()["watches"][0] == expected
        with owned(tmp_path / "b", enroll=False, max_full_premium_loss="208.30") as (
            other,
            venue_b,
            _,
        ):
            other_book, f = start(other, venue_b)
            fresh, c, u, now = evidence(other, f)
            ready(other, venue_b, now)
            assert (
                review(other_book, fresh, c, u, now)["record"]["admission_review"]["admission"][
                    "quantity"
                ]
                == 1
            )
        assert book.snapshot()["watches"][0] == expected


def test_failed_write_rolls_back_hold_and_admission_together(tmp_path, monkeypatch):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        before = book.snapshot()
        event = engine.journal.event

        def fail(*args, **kwargs):
            event(*args, **kwargs)
            raise RuntimeError("injected")

        monkeypatch.setattr(engine.journal, "event", fail)
        with pytest.raises(RuntimeError, match="injected"):
            review(book, fresh, c, u, now)
        assert book.snapshot() == before
