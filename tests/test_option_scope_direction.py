"""Neutral transitions cannot refund calls or reuse pre-reset confirmation."""

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_scope_watch import (
    AT,
    advance,
    append,
    call,
    choice,
    frame,
    owned,
    policy,
    ready,
    revision,
)

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution
from app.options.scope_watch import ScopeDirectionResetPolicy, ScopeWatchBook

D = Decimal


def enrolled(engine, *, cooldown=600, bars=2):
    p = policy().model_copy(
        update={
            "direction_reset": ScopeDirectionResetPolicy(
                cooldown_seconds=cooldown, confirmation_bars=bars
            )
        }
    )
    return ScopeWatchBook(engine, p, now=AT, create=True)


def neutral(book, f, *, key="neutral", expected=None):
    return book.neutralize(
        key,
        "first",
        f,
        now=f.histories[0].received_at,
        expected_revision=revision(book.engine) if expected is None else expected,
    )


def invalidated(book, right="CALL"):
    f = frame(right)
    original = call(book, f=f)["record"]
    f = append(f, **{"low" if right == "CALL" else "high": original["geometry"]["invalidation"]})
    advance(book, f)
    return f, original


def reset(book, right="CALL"):
    f, original = invalidated(book, right)
    f = append(f, close="100.5" if right == "CALL" else "99.5")
    result = neutral(book, f)
    return f, original, result


def opposing(f, old_right="CALL", count=3):
    for c in ("99.8", "99.6", "99.4", "99.2", "99.0")[:count]:
        f = append(
            f,
            close=c if old_right == "CALL" else 200 - D(c),
            cross_close="99.8" if old_right == "CALL" else "100.2",
        )
    right = "PUT" if old_right == "CALL" else "CALL"
    instrument = f.metadata.instrument.model_copy(
        update={
            "instrument_id": "reversal-" + right,
            "contract": f.metadata.instrument.contract.model_copy(update={"right": right}),
        }
    )
    return f.model_copy(
        update={
            "metadata": f.metadata.model_copy(
                update={"instrument": instrument, "delta": D("-.99" if right == "PUT" else ".99")}
            ),
            "quote": f.quote.model_copy(update={"instrument": instrument}),
        }
    )


def flip(book, venue, f, *, pattern="opening_drive_failure"):
    now = f.histories[0].received_at
    ready(book.engine, venue, now)
    return call(
        book,
        f=f,
        key="second",
        now=now,
        selected=choice(f.metadata.instrument.contract.right, pattern),
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_separate_neutral_and_post_reset_reversal_allow_second_unfilled_call(tmp_path, right):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine)
        f, original, result = reset(book, right)
        assert result["record"]["status"] == "INVALIDATED_UNFILLED"
        assert result["record"]["geometry"] == original["geometry"]
        assert len(book.snapshot()["watches"]) == 1
        out = flip(book, venue, opposing(f, right))
        assert out["record"]["status"] == "WATCHING"
        assert out["record"]["choice"]["right"] != right
        assert len(book.snapshot()["watches"]) == 2
        report = engine.journal.report(now=AT)
        assert not report["orders"] and D(report["ledger"]["cash"]) == 1000
        assert not out["authority"] and not out["live_enabled"]


def test_fresh_opposite_reversal_without_neutral_is_blocked(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine)
        f, _ = invalidated(book)
        with pytest.raises(ExecutionBlocked, match="NEUTRAL_RESET_REQUIRED"):
            flip(book, venue, opposing(f))


def test_new_policy_does_not_change_old_serialization_or_upgrade_existing_cohort(tmp_path):
    assert "direction_reset" not in policy().model_dump(mode="json")
    with owned(tmp_path) as (engine, _, book):
        with pytest.raises(ExecutionBlocked, match="POLICY_MISMATCH"):
            enrolled(engine)
        f, _ = invalidated(book)
        with pytest.raises(ExecutionBlocked, match="NOT_IMPLEMENTED"):
            neutral(book, append(f))


def test_neutral_is_idempotent_and_cannot_be_repeated_or_backdated(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = enrolled(engine)
        f, _ = invalidated(book)
        with pytest.raises(ExecutionBlocked, match="FRESH_COMPLETED_BAR"):
            neutral(book, f)
        f = append(f)
        expected = revision(engine)
        result = neutral(book, f, expected=expected)
        assert neutral(book, f, expected=expected) == result
        with pytest.raises(ExecutionBlocked, match="ACTION_CONFLICT"):
            neutral(book, f, expected=expected + 1)
        with pytest.raises(ExecutionBlocked, match="INVALIDATED_PLAY_REQUIRED"):
            neutral(book, append(f), key="repeat")


@pytest.mark.parametrize("count", [1, 2])
def test_no_pre_reset_or_overlapping_bar_counts_as_confirmation(tmp_path, count):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine)
        f, _, _ = reset(book)
        f = opposing(f, count=count)
        # At ten minutes cooldown has elapsed, but only one full bar began after reset.
        with pytest.raises(ExecutionBlocked, match="DIRECTION_COOLDOWN|POST_RESET_BARS_REQUIRED"):
            flip(book, venue, f)


def test_cooldown_exclusive_before_boundary_and_inclusive_at_boundary(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine, cooldown=901)
        f, _, result = reset(book)
        f = opposing(f)
        now = f.histories[0].received_at
        assert now.isoformat() > result["record"]["neutral_reset"]["recorded_at"]
        ready(engine, venue, now)
        with pytest.raises(ExecutionBlocked, match="DIRECTION_COOLDOWN"):
            call(
                book,
                f=f,
                key="second",
                now=now,
                selected=choice("PUT", "opening_drive_failure"),
            )
        boundary = now + timedelta(seconds=1)
        ready(engine, venue, boundary)
        assert (
            call(
                book,
                f=f,
                key="second",
                now=boundary,
                selected=choice("PUT", "opening_drive_failure"),
            )["record"]["status"]
            == "WATCHING"
        )


def test_continuation_cannot_substitute_for_fresh_reversal(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine)
        f, _, _ = reset(book)
        with pytest.raises(ExecutionBlocked, match="FRESH_REVERSAL_REQUIRED"):
            flip(book, venue, opposing(f), pattern="opening_range_break_hold")


def test_neutral_state_survives_owner_restart(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine)
        f, _, result = reset(book)
        path, limits, epolicy, frozen = (
            engine.journal.path,
            engine.limits,
            engine.policy,
            book.policy,
        )
    with OptionExecution.open(
        path, limits, epolicy, venue, now=f.histories[0].received_at
    ) as engine:
        book = ScopeWatchBook(engine, frozen, now=f.histories[0].received_at)
        assert book.snapshot()["watches"][0] == result["record"]
        assert flip(book, venue, opposing(f))["record"]["status"] == "WATCHING"


@pytest.mark.parametrize("which", ["active", "expired", "consumed"])
def test_neutral_requires_invalidation_not_other_terminal_or_active_state(tmp_path, which):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = enrolled(engine)
        f = frame()
        original = call(book, f=f)["record"]
        if which == "expired":
            advance(book, now=f.session.entry_cutoff_at)
        elif which == "consumed":
            f = append(f, high=original["geometry"]["target_two"])
            advance(book, f)
        with pytest.raises(ExecutionBlocked):
            neutral(book, append(f))


@pytest.mark.parametrize(
    "field,value",
    [
        ("cooldown_seconds", 599),
        ("cooldown_seconds", True),
        ("confirmation_bars", 1),
        ("confirmation_bars", 6),
    ],
)
def test_explicit_reset_policy_cannot_weaken_source_floor(field, value):
    with pytest.raises(ValidationError):
        ScopeDirectionResetPolicy.model_validate(
            {"cooldown_seconds": 600, "confirmation_bars": 2, field: value}
        )


@pytest.mark.parametrize("kind", ["identity", "history", "stale", "revision"])
def test_invalid_neutral_evidence_leaves_terminal_record_unchanged(tmp_path, kind):
    from test_option_scope_structure import bind as bind_structure

    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = enrolled(engine)
        f, _ = invalidated(book)
        f = append(f)
        now, expected = f.histories[0].received_at, revision(engine)
        if kind == "identity":
            f = f.model_copy(
                update={"session": f.session.model_copy(update={"evidence_hash": "f" * 64})}
            )
        elif kind == "history":
            h = f.histories[0]
            f = bind_structure(
                f.model_copy(
                    update={
                        "histories": (
                            h.model_copy(
                                update={
                                    "bars": (
                                        h.bars[0].model_copy(update={"volume": 101}),
                                        *h.bars[1:],
                                    )
                                }
                            ),
                            *f.histories[1:],
                        )
                    }
                )
            )
        elif kind == "stale":
            now += timedelta(seconds=31)
        else:
            expected -= 1
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked):
            book.neutralize("neutral", "first", f, expected_revision=expected, now=now)
        assert book.snapshot() == before


def test_neutral_transaction_failure_rolls_back_and_retry_succeeds(tmp_path, monkeypatch):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = enrolled(engine)
        f, _ = invalidated(book)
        f = append(f)
        before = book.snapshot()
        original = engine.journal.event

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected neutral failure")

        monkeypatch.setattr(engine.journal, "event", fail)
        with pytest.raises(RuntimeError, match="injected neutral failure"):
            neutral(book, f)
        assert book.snapshot() == before
        monkeypatch.setattr(engine.journal, "event", original)
        assert neutral(book, f)["record"]["neutral_reset"]


def test_neutral_cleanup_during_halt_does_not_allow_opposing_call(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine)
        f, _ = invalidated(book)
        with engine.journal.write() as db:
            engine._halt(db, "fixture", f.histories[0].received_at)
        f = append(f)
        neutral(book, f)
        with pytest.raises(ExecutionBlocked, match="OWNER_NOT_READY"):
            flip(book, venue, opposing(f))


def test_larger_confirmation_count_is_enforced(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book = enrolled(engine, bars=3)
        f, _, _ = reset(book)
        with pytest.raises(ExecutionBlocked, match="POST_RESET_BARS_REQUIRED"):
            flip(book, venue, opposing(f, count=3))
        assert flip(book, venue, opposing(f, count=4))["record"]["status"] == "WATCHING"
