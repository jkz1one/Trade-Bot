"""Sampled hold requires fresh evidence; stored arming never grants order authority."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_context import bind, context
from test_option_scope_quality import inputs
from test_option_scope_quality import policy as quality_policy
from test_option_scope_structure import bind as bind_structure
from test_option_scope_watch import append, choice, owned, ready, revision
from test_option_scope_watch import policy as watch_policy

from app.execution.engine import ExecutionBlocked
from app.options.scope_watch import ScopeArmingPolicy, ScopeWatchBook


def policy(**changes):
    return watch_policy(
        quality=quality_policy(),
        arming=ScopeArmingPolicy(
            confirmation_hold_seconds=60, max_sample_gap_seconds=10, **changes
        ),
    )


def refresh(f, now):
    clocks = {"source_at": now, "received_at": now}
    f = f.model_copy(
        update={
            "histories": tuple(h.model_copy(update=clocks) for h in f.histories),
            "evidence": tuple(e.model_copy(update=clocks) for e in f.evidence),
            "metadata": f.metadata.model_copy(update=clocks),
            "quote": f.quote.model_copy(update=clocks),
        }
    )
    c = context(f)
    return bind(bind_structure(f), c), c


def start(engine, right="CALL"):
    book = ScopeWatchBook(engine, policy(), now=AT, create=True)
    f, c = inputs(right=right)
    book.call(
        "first",
        choice(right, "trend_pullback_continuation"),
        f,
        c,
        expected_revision=revision(engine),
        now=AT,
    )
    return book, f


def observe(book, f, seconds, *, c=None, key=None):
    now = AT + timedelta(seconds=seconds)
    return book.observe_arming(
        key or f"sample-{seconds}",
        "first",
        frame=f,
        context=c if c is not None else context(f),
        now=now,
        expected_revision=revision(book.engine),
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_full_hold_boundary_and_reopen(tmp_path, right):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, original = start(engine, right)
        for seconds in (*range(0, 60, 10), 59, 60):
            now = AT + timedelta(seconds=seconds)
            ready(engine, venue, now)
            f, c = refresh(original, now)
            out = observe(book, f, seconds, c=c)
            a = out["record"]["arming"]
            assert a["status"] == ("ARMED" if seconds == 60 else "HOLDING")
            assert a["started_at"] == AT.isoformat()
            assert not a["authority"] and not out["authority"] and not out["live_enabled"]
            assert out["record"]["status"] == "WATCHING"
            assert out["record"]["locked_frame"] == original.model_dump(mode="json")
            book = ScopeWatchBook(engine, policy(), now=now)
            assert book.snapshot()["watches"][0] == out["record"]
        assert a["sample_count"] == 8
        assert len(book.snapshot()["watches"]) == 1
        # Reads do not refresh the dated result or create new account costs/orders.
        before = revision(engine)
        assert book.snapshot()["watches"][0]["arming"] == a
        assert revision(engine) == before
        with engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 0


@pytest.mark.parametrize("seconds", [11, 60, 120])
def test_elapsed_time_or_sampling_gap_restarts_hold(tmp_path, seconds):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine)
        observe(book, f, 0)
        now = AT + timedelta(seconds=seconds)
        ready(engine, venue, now)
        f, c = refresh(f, now)
        a = observe(book, f, seconds, c=c)["record"]["arming"]
        assert a["status"] == "HOLDING" and a["sample_count"] == 1
        assert a["started_at"] == now.isoformat()


@pytest.mark.parametrize(
    "failure", ["stale", "missing", "quality", "source", "identity", "history", "halt"]
)
def test_failed_sample_commits_reset_and_requires_new_hold(tmp_path, failure):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine)
        observe(book, f, 0)
        now = AT + timedelta(seconds=5)
        fresh, c = refresh(f, now)
        if failure == "stale":
            now = AT + timedelta(seconds=20)
            fresh, c = f, context(f)
        elif failure == "missing":
            fresh = None
        elif failure == "quality":
            c = c.model_copy(update={"flow": c.flow.model_copy(update={"state": "BEARISH"})})
            fresh = bind(fresh, c)
        elif failure == "source":
            fresh, c = f, context(f)
        elif failure == "identity":
            fresh = fresh.model_copy(update={"metadata": None})
        elif failure == "history":
            h = fresh.histories[0]
            bars = (h.bars[0].model_copy(update={"volume": 101}), *h.bars[1:])
            fresh = bind(
                bind_structure(
                    fresh.model_copy(
                        update={
                            "histories": (h.model_copy(update={"bars": bars}), *fresh.histories[1:])
                        }
                    )
                ),
                c,
            )
        elif failure == "halt":
            # No fresh supervisor/account by 25 seconds.
            now = AT + timedelta(seconds=25)
            fresh, c = refresh(f, now)
        before = revision(engine)
        out = book.observe_arming(
            "bad", "first", frame=fresh, context=c, now=now, expected_revision=before
        )
        a = out["record"]["arming"]
        assert a["status"] == "RESET" and a["started_at"] is None and a["reasons"]
        assert out["revision"] > before
        assert book.snapshot()["watches"][0]["arming"] == a
        now += timedelta(seconds=1)
        ready(engine, venue, now)
        fresh, c = refresh(f, now)
        out = book.observe_arming(
            "recover", "first", frame=fresh, context=c, now=now, expected_revision=revision(engine)
        )
        assert out["record"]["arming"]["started_at"] == now.isoformat()
        assert out["record"]["arming"]["status"] == "HOLDING"


def test_duplicate_receipt_conflict_and_revision(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book, f = start(engine)
        kwargs = {
            "frame": f,
            "context": context(f),
            "now": AT,
            "expected_revision": revision(engine),
        }
        first = book.observe_arming("a", "first", **kwargs)
        assert book.observe_arming("a", "first", **kwargs) == first
        with pytest.raises(ExecutionBlocked, match="CONFLICT"):
            book.observe_arming("a", "first", **(kwargs | {"now": AT + timedelta(seconds=1)}))
        with pytest.raises(ExecutionBlocked, match="REVISION"):
            book.observe_arming("b", "first", **kwargs)
        assert observe(book, f, 1)["record"]["arming"]["status"] == "RESET"
        assert book.observe_arming("a", "first", **kwargs) == first
        assert book.snapshot()["watches"][0]["arming"]["status"] == "RESET"


def test_new_bars_recheck_geometry_and_expiry_clears_hold(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine)
        observe(book, f, 0)
        next_frame = append(f)
        now = next_frame.histories[0].received_at
        ready(engine, venue, now)
        out = observe(book, next_frame, 300)
        assert out["record"]["arming"]["status"] == "RESET"
        assert out["record"]["arming"]["reasons"]
        assert (
            out["record"]["reviewed_through"]
            == next_frame.histories[0].bars[-1].ends_at.isoformat()
        )
        out = book.advance(
            "expire", "first", now=f.session.entry_cutoff_at, expected_revision=revision(engine)
        )
        assert out["record"]["status"] == "EXPIRED_UNFILLED"
        assert out["record"]["arming"]["status"] == "RESET"
        with pytest.raises(ExecutionBlocked, match="NOT_ACTIVE"):
            book.observe_arming(
                "late", "first", now=f.session.entry_cutoff_at, expected_revision=revision(engine)
            )


def test_opt_in_compatibility_and_frozen_policy(tmp_path):
    assert "arming" not in watch_policy().model_dump()
    with pytest.raises(ValidationError, match="quality"):
        watch_policy(
            arming=ScopeArmingPolicy(confirmation_hold_seconds=60, max_sample_gap_seconds=10)
        )
    with owned(tmp_path) as (engine, _, book):
        with pytest.raises(ExecutionBlocked, match="NOT_ENROLLED"):
            book.observe_arming("a", "first", now=AT, expected_revision=revision(engine))
        with pytest.raises(ExecutionBlocked, match="FROZEN"):
            ScopeWatchBook(engine, policy(), now=AT)


@pytest.mark.parametrize(
    "field,value",
    [
        ("confirmation_hold_seconds", 0),
        ("confirmation_hold_seconds", 59),
        ("confirmation_hold_seconds", 601),
        ("max_sample_gap_seconds", 0),
        ("max_sample_gap_seconds", 11),
        ("max_sample_gap_seconds", True),
    ],
)
def test_policy_bounds(field, value):
    with pytest.raises(ValidationError):
        ScopeArmingPolicy.model_validate(
            {"confirmation_hold_seconds": 60, "max_sample_gap_seconds": 10, field: value}
        )


def test_hold_survives_owner_restart_without_crediting_downtime(tmp_path):
    from app.options.engine import OptionExecution

    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine)
        first = observe(book, f, 0)
        path, limits, epolicy = engine.journal.path, engine.limits, engine.policy
    now = AT + timedelta(seconds=5)
    with OptionExecution.open(path, limits, epolicy, venue, now=now) as engine:
        book = ScopeWatchBook(engine, policy(), now=now)
        assert book.snapshot()["watches"][0] == first["record"]
        ready(engine, venue, now)
        fresh, c = refresh(f, now)
        a = observe(book, fresh, 5, c=c)["record"]["arming"]
        assert a["sample_count"] == 2 and a["started_at"] == AT.isoformat()


@pytest.mark.parametrize("stream", ["quote", "metadata", "history", "evidence", "context"])
def test_one_unadvanced_source_or_receipt_only_refresh_breaks_hold(tmp_path, stream):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book, original = start(engine)
        observe(book, original, 0)
        fresh, c = refresh(original, AT + timedelta(seconds=1))
        if stream in ("quote", "metadata"):
            fresh = fresh.model_copy(
                update={stream: getattr(fresh, stream).model_copy(update={"source_at": AT})}
            )
        elif stream == "history":
            fresh = fresh.model_copy(
                update={
                    "histories": (
                        fresh.histories[0].model_copy(update={"source_at": AT}),
                        *fresh.histories[1:],
                    )
                }
            )
            fresh = bind_structure(fresh)
        elif stream == "evidence":
            fresh = fresh.model_copy(
                update={
                    "evidence": tuple(
                        e.model_copy(update={"source_at": AT})
                        if e.kind == "provider_readiness"
                        else e
                        for e in fresh.evidence
                    )
                }
            )
        else:
            c = c.model_copy(update={"flow": c.flow.model_copy(update={"source_at": AT})})
            fresh = bind(fresh, c)
        a = observe(book, fresh, 1, c=c)["record"]["arming"]
        assert a["status"] == "RESET" and a["reasons"]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_sample_reviews_new_bar_crossings_and_releases_active_lock(tmp_path, right):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, right)
        r = observe(book, f, 0)["record"]
        geometry = r["geometry"]
        f = append(
            f,
            **(
                {"low": geometry["invalidation"]}
                if right == "CALL"
                else {"high": geometry["invalidation"]}
            ),
        )
        now = f.histories[0].received_at
        ready(engine, venue, now)
        out = observe(book, f, 300)
        assert out["record"]["status"] == "INVALIDATED_UNFILLED"
        assert out["record"]["arming"]["status"] == "RESET"
        with engine.journal.read() as db:
            assert (
                db.execute("SELECT active_lock FROM execution_option_scope_watches").fetchone()[0]
                is None
            )


def test_atomic_failure_does_not_partially_reset_hold(tmp_path, monkeypatch):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book, f = start(engine)
        observe(book, f, 0)
        before = book.snapshot()
        event = engine.journal.event

        def crash(*args, **kwargs):
            event(*args, **kwargs)
            raise RuntimeError("injected")

        monkeypatch.setattr(engine.journal, "event", crash)
        with pytest.raises(RuntimeError, match="injected"):
            book.observe_arming("missing", "first", now=AT, expected_revision=revision(engine))
        assert book.snapshot() == before
