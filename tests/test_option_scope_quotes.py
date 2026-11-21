"""Observed Scope invalidation is terminal, independent of admission or recovery."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_scope import AT
from test_option_scope_observer import observer
from test_option_scope_owned_admission import evidence, policy, review, start
from test_option_scope_watch import owned, ready, revision

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution, fingerprint
from app.options.scope_watch import ScopeWatchBook

D = Decimal
VERSION = "scope-observed-quotes-v1"


def enrolled():
    return policy().model_copy(update={"quote_lifecycle": VERSION})


def sample(e, f, book, field="invalidation", seconds=60):
    fresh, c, u, now = evidence(e, f, seconds)
    price = D(book.snapshot()["watches"][0]["geometry"][field])
    return fresh, c, u.model_copy(update={"bid": price, "ask": price}), now


def observe(book, u, now, key="quote"):
    return book.observe_quote(key, "first", u, now=now, expected_revision=revision(book.engine))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "field,status",
    [("invalidation", "INVALIDATED_UNFILLED"), ("target_two", "OBJECTIVE_CONSUMED_UNFILLED")],
)
def test_exact_quote_boundary_persists_terminal_without_bars_orders_or_cash(
    tmp_path, right, field, status
):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, right, watch_policy=enrolled())
        _, _, u, now = sample(e, f, book, field)
        old = book.snapshot()["watches"][0]
        before = e.journal.report(now=now)["ledger"]
        rev = revision(e)
        out = book.observe_quote("quote", "first", u, now=now, expected_revision=rev)
        r = out["record"]
        assert r["status"] == status and r["terminal_bar_ends_at"] is None
        assert r["terminal_quote"]["quote"] == u.model_dump(mode="json")
        assert r["terminal_quote"]["geometry"] == old["geometry"]
        assert r["reviewed_frame"] == old["reviewed_frame"]
        assert r["reviewed_through"] == old["reviewed_through"]
        assert r["arming"]["status"] == "RESET"
        assert not out["authority"] and not out["live_enabled"]
        assert book.observe_quote("quote", "first", u, now=now, expected_revision=rev) == out
        assert e.journal.report(now=now)["ledger"] == before
        view = observer(e, now).report()
        assert view["status"] == "OK", view
        assert view["scope"]["active_watch"] is None
        assert view["scope"]["watches"][0]["terminal_quote"]["status"] == status
        path, limits, execution = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, execution, v, now=now) as e:
        book = ScopeWatchBook(e, enrolled(), now=now)
        with pytest.raises(ExecutionBlocked, match="NOT_ACTIVE"):
            observe(book, u, now, "revive")
        assert book.snapshot()["watches"][0]["status"] == status


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("enable", [True, False])
def test_admission_breach_cannot_revive_but_old_cohort_retains_its_rules(tmp_path, right, enable):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, right, watch_policy=enrolled() if enable else policy())
        fresh, c, u, now = sample(e, f, book)
        ready(e, v, now)
        out = review(book, fresh, c, u, now)
        assert not out["record"]["admission_review"]["eligible"]
        if enable:
            assert out["record"]["status"] == "INVALIDATED_UNFILLED"
        for seconds in range(70, 141, 10):
            fresh, c, u, now = evidence(e, f, seconds)
            ready(e, v, now)
            if enable:
                with pytest.raises(ExecutionBlocked, match="NOT_ACTIVE"):
                    review(book, fresh, c, u, now, key=f"recovery-{seconds}")
            else:
                out = review(book, fresh, c, u, now, key=f"recovery-{seconds}")
        if not enable:
            assert out["record"]["admission_review"]["eligible"]
            assert "quote_lifecycle" not in book.policy.model_dump()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "stale",
        "future",
        "source",
        "symbol",
        "incomplete",
        "entitlement",
        "crossed",
        "precall",
    ],
)
def test_unusable_quotes_reset_hold_without_fabricating_a_terminal(tmp_path, fault):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=enrolled())
        _, _, u, now = sample(e, f, book)
        if fault == "missing":
            u = None
        elif fault == "stale":
            u = u.model_copy(
                update={
                    "source_at": now - timedelta(seconds=30),
                    "received_at": now - timedelta(seconds=30),
                }
            )
        elif fault == "future":
            u = u.model_copy(
                update={
                    "source_at": now + timedelta(seconds=1),
                    "received_at": now + timedelta(seconds=1),
                }
            )
        elif fault == "source":
            u = u.model_copy(update={"source": "foreign"})
        elif fault == "symbol":
            u = u.model_copy(update={"symbol": "SPY"})
        elif fault == "incomplete":
            u = u.model_copy(update={"complete": False})
        elif fault == "entitlement":
            u = u.model_copy(update={"entitlement": "UNKNOWN"})
        elif fault == "crossed":
            u = u.model_copy(update={"bid": u.ask + 1})
        else:
            u = u.model_copy(update={"source_at": AT - timedelta(seconds=1), "received_at": AT})
        out = observe(book, u, now)["record"]
        assert out["status"] == "WATCHING" and "terminal_quote" not in out
        assert out["quote_review"]["status"] == "REJECTED"
        assert out["arming"]["status"] == "RESET" and "last_observed_quote" not in out
        assert observer(e, now).report()["status"] == "OK"


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_quote_side_and_first_objective_do_not_substitute_for_locked_second(tmp_path, right):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, right, watch_policy=enrolled())
        _, _, u, now = sample(e, f, book, "target_one")
        assert observe(book, u, now)["record"]["status"] == "WATCHING"
        _, _, u, now = sample(e, f, book, "target_two", 61)
        u = (
            u.model_copy(update={"bid": u.bid - D(".01")})
            if right == "CALL"
            else u.model_copy(update={"ask": u.ask + D(".01")})
        )
        out = observe(book, u, now, "spread")["record"]
        assert out["status"] == "WATCHING" and out["quote_review"]["status"] == "OBSERVED"
        _, _, u, now = sample(e, f, book, "invalidation", 62)
        u = (
            u.model_copy(update={"ask": u.ask + 1})
            if right == "CALL"
            else u.model_copy(update={"bid": u.bid - 1})
        )
        assert observe(book, u, now, "stop")["record"]["status"] == "INVALIDATED_UNFILLED"


def test_quote_clock_conflict_rejected_and_identical_receipt_cannot_refresh_source(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=enrolled())
        _, _, u, now = evidence(e, f)
        first = observe(book, u, now)["record"]
        second = observe(book, u, now + timedelta(seconds=1), "same")["record"]
        assert second["quote_review"]["status"] == "OBSERVED"
        assert (
            second["arming"] == first["arming"]
            and second["last_observed_quote"] == first["last_observed_quote"]
        )
        stop = D(first["geometry"]["invalidation"])
        conflict = u.model_copy(update={"bid": stop, "ask": stop})
        r = observe(book, conflict, now + timedelta(seconds=2), "changed")["record"]
        assert r["status"] == "WATCHING" and r["quote_review"]["status"] == "REJECTED"
        assert r["last_observed_quote"] == first["last_observed_quote"]
        r = observe(book, u, now + timedelta(seconds=30), "receipt-refresh")["record"]
        assert r["quote_review"]["status"] == "REJECTED"


def test_admission_records_breach_even_without_frame_context_or_fresh_account(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=enrolled())
        _, _, u, now = sample(e, f, book, seconds=90)
        out = book.review_admission(
            "blocked", "first", underlying=u, now=now, expected_revision=revision(e)
        )["record"]
        assert out["status"] == "INVALIDATED_UNFILLED" and not out["admission_review"]["eligible"]
        assert out["admission_review"]["account"] is None
        assert observer(e, now).report()["status"] == "OK"


def test_quote_only_observation_removes_old_admission_but_does_not_extend_hold(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=enrolled())
        fresh, c, u, now = evidence(e, f)
        ready(e, v, now)
        out = review(book, fresh, c, u, now)["record"]
        assert out["admission_review"]["eligible"]
        r = observe(book, u, now)["record"]
        assert "admission_review" not in r and r["arming"] == out["arming"]
        assert observer(e, now).report()["scope"]["active_watch"]["admission"] is None


def test_cutoff_expires_without_quote_and_does_not_claim_price_crossing(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=enrolled())
        r = observe(book, None, f.session.entry_cutoff_at)["record"]
        assert r["status"] == "EXPIRED_UNFILLED" and "terminal_quote" not in r
        assert r["terminal_bar_ends_at"] is None


def test_quote_enrollment_is_frozen(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, _ = start(e, v)
        with pytest.raises(ExecutionBlocked, match="NOT_ENROLLED"):
            observe(book, None, AT + timedelta(seconds=60))
        with pytest.raises(ExecutionBlocked, match="FROZEN_SCOPE"):
            ScopeWatchBook(e, enrolled(), now=AT)


def test_rollback_and_independent_watch_state(tmp_path, monkeypatch):
    with (
        owned(tmp_path / "a", enroll=False) as (a, av, _),
        owned(tmp_path / "b", enroll=False) as (b, bv, _),
    ):
        ab, af = start(a, av, watch_policy=enrolled())
        bb, _ = start(b, bv, watch_policy=enrolled())
        before_a, before_b = ab.snapshot(), bb.snapshot()
        _, _, u, now = sample(a, af, ab)
        with monkeypatch.context() as patch:

            def fail(*args, **kwargs):
                raise RuntimeError("audit unavailable")

            patch.setattr(a.journal, "event", fail)
            with pytest.raises(RuntimeError, match="audit unavailable"):
                observe(ab, u, now)
        assert ab.snapshot() == before_a and bb.snapshot() == before_b
        assert observe(ab, u, now)["record"]["status"] == "INVALIDATED_UNFILLED"
        assert bb.snapshot() == before_b


def test_observer_rejects_modified_terminal_evidence_without_mutation(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=enrolled())
        _, _, u, now = sample(e, f, book)
        r = observe(book, u, now)["record"]
        r["terminal_quote"]["quote"]["bid"] = "1"
        with e.journal.write() as db:
            db.execute("UPDATE execution_option_scope_watches SET record_json=?", (json.dumps(r),))
        rev = revision(e)
        assert observer(e, now).report()["status"] == "UNAVAILABLE"
        assert revision(e) == rev


def test_native_decision_history_prevents_claiming_an_unfilled_watch(tmp_path):
    from app.options.models import OptionProposal

    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=enrolled())
        fresh, c, u, now = evidence(e, f)
        ready(e, v, now)
        r = review(book, fresh, c, u, now)["record"]["admission_review"]
        out = e.prepare(
            "native", OptionProposal.model_validate(r["proposal"]), fresh.quote, u, now=now
        )
        assert out["reason"] == "SCOPE_NATIVE_EXECUTION_NOT_ENROLLED"
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked, match="EXECUTION_LINK_NOT_IMPLEMENTED"):
            observe(book, u, now)
        assert book.snapshot() == before


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_quote_terminal_replays_and_portable_verifier_preserves_original(tmp_path, right):
    from test_option_scope_replay import settings, tape

    from app.options.scope_context import scan_scope_context
    from app.options.scope_replay import ScopeReplayStep, run_scope_replay
    from app.options.scope_replay_verify import verify_scope_replay

    steps = tape(right, expire=False)
    called = steps[0]
    scan = scan_scope_context(called.frame, called.context, enrolled().context, now=called.at)
    geometry = next(
        o.geometry
        for o in scan.observations
        if all(getattr(o, k) == v for k, v in called.choice.model_dump().items())
    )
    now = steps[-1].at + timedelta(seconds=1)
    u = steps[-1].underlying.model_copy(
        update={
            "source_at": now,
            "received_at": now,
            "bid": geometry.invalidation,
            "ask": geometry.invalidation,
        }
    )
    steps.append(
        ScopeReplayStep(
            key="quote-terminal", kind="OBSERVE_QUOTE", at=now, play_key="first", underlying=u
        )
    )
    steps.append(
        ScopeReplayStep(
            key="cannot-revive",
            kind="OBSERVE_QUOTE",
            at=now + timedelta(seconds=1),
            play_key="first",
        )
    )
    request = settings(steps, watch=enrolled())
    home = tmp_path / "run"
    report = run_scope_replay(request, home)
    assert report["scope"]["active_watch"] is None
    assert report["scope"]["watches"][0]["terminal_quote"]["status"] == "INVALIDATED_UNFILLED"
    assert report["steps"][-1]["reason"] == "SCOPE_WATCH_NOT_ACTIVE"
    assert report["data_cost"] is report["host_cost"] is report["net_return"] is None
    before = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    result = verify_scope_replay(home, fingerprint(request))
    assert result["status"] == "VERIFIED_RESEARCH_REPLAY"
    assert {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_quote_invalidation_neutral_reset_keeps_original_trigger_and_requires_later_bar(
    tmp_path, right
):
    from test_option_scope_watch import append

    from app.options.scope_watch import ScopeDirectionResetPolicy

    p = enrolled().model_copy(
        update={
            "direction_reset": ScopeDirectionResetPolicy(cooldown_seconds=600, confirmation_bars=2)
        }
    )
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, right, watch_policy=p)
        _, _, u, now = sample(e, f, book)
        terminal = observe(book, u, now)["record"]["terminal_quote"]
        with pytest.raises(ExecutionBlocked):
            book.neutralize("old-bars", "first", f, now=now, expected_revision=revision(e))
        newer = append(f)
        at = newer.histories[0].received_at
        out = book.neutralize("neutral", "first", newer, now=at, expected_revision=revision(e))[
            "record"
        ]
        assert out["status"] == "INVALIDATED_UNFILLED" and out["terminal_quote"] == terminal
        assert out["neutral_reset"]["recorded_at"] == at.isoformat()
        assert observer(e, at).report()["status"] == "OK"
        assert len(book.snapshot()["watches"]) == 1


def test_new_key_cannot_reuse_a_bar_completed_before_quote_invalidation(tmp_path):
    from test_option_scope_arming import refresh
    from test_option_scope_watch import append, call, choice, frame
    from test_option_scope_watch import policy as watch_policy

    from app.options.models import UnderlyingQuote

    with owned(tmp_path, enroll=False) as (e, v, _):
        book = ScopeWatchBook(e, watch_policy(quote_lifecycle=VERSION), now=AT, create=True)
        f = frame()
        original = call(book, f=f)["record"]
        advanced = append(f, close="100.7")
        now = advanced.histories[0].bars[-1].ends_at + timedelta(seconds=1)
        stop = D(original["geometry"]["invalidation"])
        u = UnderlyingQuote(
            symbol="SPX",
            source=e.limits.underlying_source,
            source_at=now,
            received_at=now,
            bid=stop,
            ask=stop,
            complete=True,
            entitlement="REALTIME",
        )
        observe(book, u, now)
        fresh, c = refresh(advanced, now)
        ready(e, v, now)
        with pytest.raises(ExecutionBlocked, match="POST_TERMINAL_BAR_REQUIRED"):
            book.call(
                "second",
                choice("CALL", "trend_pullback_continuation"),
                fresh,
                c,
                now=now,
                expected_revision=revision(e),
            )
        assert len(book.snapshot()["watches"]) == 1
        later = append(advanced, close="100.8")
        at = later.histories[0].received_at
        fresh, c = refresh(later, at)
        ready(e, v, at)
        out = book.call(
            "new-after-terminal",
            choice("CALL", "trend_pullback_continuation"),
            fresh,
            c,
            now=at,
            expected_revision=revision(e),
        )
        assert out["record"]["status"] == "WATCHING"
        assert len(book.snapshot()["watches"]) == 2
