"""Unfilled watches persist without becoming fills, outcomes or admission."""

import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_execution import configuration
from test_option_scope import AT
from test_option_scope_context import bind, context
from test_option_scope_context import policy as context_policy
from test_option_scope_structure import bind as bind_structure
from test_option_scope_structure import frame as structure_frame

from app.execution.engine import ExecutionBlocked
from app.execution.restore import authority_path
from app.options.degen import DegenBar
from app.options.engine import OptionExecution
from app.options.models import OptionProposal
from app.options.scope_watch import ScopeWatchBook, ScopeWatchChoice, ScopeWatchPolicy
from app.options.venue import DurableOptionVenue

D = Decimal


def policy(**changes):
    return ScopeWatchPolicy(context=context_policy(), max_called_plays_per_session=2, **changes)


def choice(right="CALL", pattern="opening_range_break_hold", parent=None):
    return ScopeWatchChoice(pattern=pattern, parent_pattern=parent or pattern, right=right)


def frame(right="CALL"):
    f = structure_frame(right=right)
    return bind(f, context(f))


def revision(engine):
    with engine.journal.read() as db:
        return engine.journal.revision(db)


def ready(engine, venue, now):
    assert engine.reconcile(venue.snapshot(now), now=now)["reconciled"]
    engine.assess(None, None, now=now)


@contextmanager
def owned(tmp_path, *, enroll=True, **changes):
    _, limits, execution_policy = configuration()
    limits = limits.model_copy(
        update={
            "allowed_underlyings": ("SPX",),
            "provider": "fixture-provider",
            "option_source": "fixture-quote",
            **changes,
        }
    )
    venue = DurableOptionVenue(
        tmp_path / "venue.db", limits=limits, capital=execution_policy.capital
    )
    with OptionExecution.open(
        tmp_path / "options.db", limits, execution_policy, venue, now=AT, create=True
    ) as engine:
        ready(engine, venue, AT)
        book = ScopeWatchBook(engine, policy(), now=AT, create=True) if enroll else None
        yield engine, venue, book


def call(book, *, f=None, key="first", selected=None, now=AT, expected=None):
    f = f or frame()
    return book.call(
        key,
        selected or choice(f.metadata.instrument.contract.right),
        f,
        context(f),
        expected_revision=revision(book.engine) if expected is None else expected,
        now=now,
    )


def append(f, *, low=None, high=None, close=None, cross_close=None):
    now = f.histories[0].received_at + timedelta(minutes=5)
    common = {"source_at": now, "received_at": now}
    histories = []
    for h in f.histories:
        last = h.bars[-1]
        c = D(close) if h.symbol == "SPX" and close is not None else last.close
        if h.symbol != "SPX" and cross_close is not None:
            c = D(cross_close)
        lo = D(low) if h.symbol == "SPX" and low is not None else min(c, last.close) - D(".1")
        hi = D(high) if h.symbol == "SPX" and high is not None else max(c, last.close) + D(".1")
        bar = DegenBar(
            begins_at=last.ends_at,
            open=last.close,
            high=hi,
            low=lo,
            close=c,
            volume=100,
            interpolated=False,
        )
        histories.append(h.model_copy(update={**common, "bars": (*h.bars, bar)}))
    f = f.model_copy(
        update={
            "histories": tuple(histories),
            "evidence": tuple(e.model_copy(update=common) for e in f.evidence),
            "metadata": f.metadata.model_copy(update=common),
            "quote": f.quote.model_copy(update=common),
        }
    )
    return bind(bind_structure(f), context(f))


def advance(book, f=None, *, key="review", play="first", now=None, expected=None):
    return book.advance(
        key,
        play,
        frame=f,
        now=now or f.histories[0].received_at,
        expected_revision=revision(book.engine) if expected is None else expected,
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_watch_locks_full_evidence_and_has_no_account_or_cost_effect(tmp_path, right):
    with owned(tmp_path) as (engine, _, book):
        before = engine.journal.report(now=AT)
        f = frame(right)
        result = call(book, f=f)
        r = result["record"]
        assert r["status"] == "WATCHING"
        assert r["locked_frame"] == f.model_dump(mode="json")
        assert r["locked_context"] == context(f).model_dump(mode="json")
        assert r["geometry"]["right"] == right
        assert not result["authority"] and not result["live_enabled"]
        after = engine.journal.report(now=AT)
        assert before["ledger"] == after["ledger"]
        assert before["economics"] == after["economics"]
        assert after["orders"] == []
        assert "pnl" not in r and "quantity" not in r
        assert book.snapshot()["watches"] == [r]


def test_action_retry_is_exact_and_does_not_recount_even_after_terminal(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        expected = revision(engine)
        result = call(book, expected=expected)
        assert call(book, expected=expected) == result
        f = frame()
        advance(book, now=f.session.entry_cutoff_at)
        current = revision(engine)
        assert call(book, expected=expected) == result  # Historical receipt, not current state.
        assert revision(engine) == current
        assert book.snapshot()["watches"][0]["status"] == "EXPIRED_UNFILLED"
        with pytest.raises(ExecutionBlocked, match="ACTION_CONFLICT"):
            call(book, expected=expected + 1)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("terminal", ["invalid", "consumed", "both", "neither"])
def test_new_completed_bars_review_locked_geometry_conservatively(tmp_path, right, terminal):
    with owned(tmp_path) as (_, _, book):
        f = frame(right)
        first = call(book, f=f)["record"]
        g = first["geometry"]
        kwargs = {}
        if terminal in {"invalid", "both"}:
            kwargs["low" if right == "CALL" else "high"] = g["invalidation"]
        if terminal in {"consumed", "both"}:
            kwargs["high" if right == "CALL" else "low"] = g["target_two"]
        f = append(f, **kwargs)
        r = advance(book, f)["record"]
        expected = {
            "invalid": "INVALIDATED_UNFILLED",
            "consumed": "OBJECTIVE_CONSUMED_UNFILLED",
            "both": "INVALIDATED_UNFILLED",
            "neither": "WATCHING",
        }[terminal]
        assert r["status"] == expected
        for field in ("geometry", "locked_frame", "locked_context", "locked_scan", "called_at"):
            assert r[field] == first[field]
        assert (r["terminal_at"] is None) == (terminal == "neither")


def test_first_crossing_is_retained_when_later_bars_rebound(tmp_path):
    with owned(tmp_path) as (_, _, book):
        f = frame()
        g = call(book, f=f)["record"]["geometry"]
        first = append(f, low=g["invalidation"])
        later = append(first, high=g["target_two"])
        r = advance(book, later)["record"]
        assert r["status"] == "INVALIDATED_UNFILLED"
        assert r["terminal_bar_ends_at"] == first.histories[0].bars[-1].ends_at.isoformat()


def test_only_one_active_and_old_completed_evidence_cannot_be_recalled(tmp_path):
    with owned(tmp_path) as (engine, venue, book):
        f = frame()
        first = call(book, f=f)
        with pytest.raises(ExecutionBlocked, match="ALREADY_ACTIVE"):
            call(book, key="second")
        f = append(f, low=first["record"]["geometry"]["invalidation"])
        advance(book, f)
        ready(engine, venue, f.histories[0].received_at)
        with pytest.raises(ExecutionBlocked, match="FRESH_COMPLETED_BAR"):
            call(book, f=f, key="second", now=f.histories[0].received_at)


def test_two_calls_include_both_unfilled_invalidations_and_survive_restart(tmp_path):
    with owned(tmp_path) as (engine, venue, book):
        f = frame()
        first = call(book, f=f)["record"]
        f = append(f, low=first["geometry"]["invalidation"])
        advance(book, f)
        f = append(f, close="100.7")
        ready(engine, venue, f.histories[0].received_at)
        second = call(book, f=f, key="second", now=f.histories[0].received_at)["record"]
        f = append(f, low=second["geometry"]["invalidation"])
        advance(book, f, key="review-second", play="second")
        path, limits, epolicy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(
        path, limits, epolicy, venue, now=f.histories[0].received_at
    ) as engine:
        book = ScopeWatchBook(engine, policy(), now=f.histories[0].received_at)
        assert len(book.snapshot()["watches"]) == 2
        f = append(f, close="100.8")
        ready(engine, venue, f.histories[0].received_at)
        with pytest.raises(ExecutionBlocked, match="DAILY_CALL_LIMIT"):
            call(book, f=f, key="third", now=f.histories[0].received_at)


@pytest.mark.parametrize("kind", ["halt", "stale", "revision", "context", "selection"])
def test_rejected_call_rolls_back_without_consuming_count(tmp_path, kind):
    with owned(tmp_path) as (engine, _, book):
        f, selected, now = frame(), choice(), AT
        expected = revision(engine)
        if kind == "halt":
            with engine.journal.write() as db:
                engine._halt(db, "fixture", AT)
            expected = revision(engine)
        elif kind == "stale":
            now += timedelta(seconds=30)
        elif kind == "revision":
            expected -= 1
        elif kind == "context":
            f = f.model_copy(update={"evidence": f.evidence[:-1]})
        elif kind == "selection":
            selected = choice(pattern="dealer_level_acceptance", parent="trap_reversal")
        before = book.snapshot()
        with pytest.raises((ExecutionBlocked, ValidationError)):
            call(book, f=f, selected=selected, now=now, expected=expected)
        assert book.snapshot() == before


@pytest.mark.parametrize("market", ["SPX", "SPY", "QQQ"])
def test_rewritten_history_is_rejected_even_when_new_attestation_matches(tmp_path, market):
    with owned(tmp_path) as (_, _, book):
        f = frame()
        call(book, f=f)
        f = append(f)
        histories = tuple(
            h.model_copy(
                update={"bars": (h.bars[0].model_copy(update={"volume": 101}), *h.bars[1:])}
            )
            if h.symbol == market
            else h
            for h in f.histories
        )
        f = bind_structure(f.model_copy(update={"histories": histories}))
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked, match="HISTORY_REWRITTEN"):
            advance(book, f)
        assert book.snapshot() == before


@pytest.mark.parametrize("change", ["contract", "session", "stale", "no-progress", "missing"])
def test_invalid_advance_preserves_the_locked_watch(tmp_path, change):
    with owned(tmp_path) as (_, _, book):
        initial = frame()
        call(book, f=initial)
        f, now = append(initial), AT + timedelta(minutes=5)
        if change == "contract":
            instrument = f.metadata.instrument.model_copy(update={"instrument_id": "replacement"})
            f = f.model_copy(
                update={
                    "metadata": f.metadata.model_copy(update={"instrument": instrument}),
                    "quote": f.quote.model_copy(update={"instrument": instrument}),
                }
            )
        elif change == "session":
            f = f.model_copy(
                update={"session": f.session.model_copy(update={"evidence_hash": "b" * 64})}
            )
        elif change == "stale":
            now += timedelta(seconds=40)
        elif change == "no-progress":
            f, now = initial, AT
        else:
            f = None
        before = book.snapshot()
        with pytest.raises(ExecutionBlocked):
            advance(book, f, now=now)
        assert book.snapshot() == before


def test_cutoff_expiry_needs_no_feed_and_works_during_halt(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        f = frame()
        call(book, f=f)
        with engine.journal.write() as db:
            engine._halt(db, "fixture", AT)
        with pytest.raises(ExecutionBlocked, match="FRESH_FRAME_REQUIRED"):
            advance(book, now=f.session.entry_cutoff_at - timedelta(microseconds=1))
        result = advance(book, now=f.session.entry_cutoff_at)
        assert result["record"]["status"] == "EXPIRED_UNFILLED"
        assert result["record"]["terminal_bar_ends_at"] is None
        assert engine.journal.report(now=AT)["halted"]
        with pytest.raises(ExecutionBlocked, match="NOT_ACTIVE"):
            advance(book, key="again", now=f.session.entry_cutoff_at)


def test_reads_do_not_expire_or_mutate_files(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        call(book)
        paths = (engine.journal.path, authority_path(engine.journal.path))
        before = [p.read_bytes() for p in paths]
        assert book.snapshot()["watches"][0]["status"] == "WATCHING"
        assert [p.read_bytes() for p in paths] == before


def test_action_failure_rolls_back_count_receipt_event_and_restore_authority(tmp_path, monkeypatch):
    with owned(tmp_path) as (engine, _, book):
        snapshot, rev = book.snapshot(), revision(engine)
        original = engine.journal.event

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected crash")

        monkeypatch.setattr(engine.journal, "event", fail)
        with pytest.raises(RuntimeError, match="injected crash"):
            call(book)
        assert book.snapshot() == snapshot
        assert revision(engine) == rev
        monkeypatch.setattr(engine.journal, "event", original)
        assert call(book)["record"]["status"] == "WATCHING"


def test_watch_journal_rollback_is_rejected_by_existing_authority(tmp_path):
    with owned(tmp_path) as (engine, venue, book):
        backup = tmp_path / "stale.db"
        shutil.copyfile(engine.journal.path, backup)
        call(book)
        path, limits, epolicy = engine.journal.path, engine.limits, engine.policy
    shutil.copyfile(backup, path)
    with (
        pytest.raises(ValueError, match="RESTORED_OR_CHANGED"),
        OptionExecution.open(path, limits, epolicy, venue, now=AT),
    ):
        pass


def test_native_decision_history_blocks_enrollment_and_later_watch_actions(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        engine.prepare("hold", OptionProposal(action="HOLD", thesis="fixture"), now=AT)
        with pytest.raises(ExecutionBlocked, match="EXECUTION_LINK_NOT_IMPLEMENTED"):
            call(book)
    other = tmp_path / "other"
    other.mkdir()
    with owned(other, enroll=False) as (engine, _, _):
        engine.prepare("hold", OptionProposal(action="HOLD", thesis="fixture"), now=AT)
        with pytest.raises(ExecutionBlocked, match="EXECUTION_LINK_NOT_IMPLEMENTED"):
            ScopeWatchBook(engine, policy(), now=AT, create=True)


@pytest.mark.parametrize(
    "changes",
    [{"provider": "other"}, {"option_source": "other"}, {"allowed_underlyings": ("SPY",)}],
)
def test_wrong_owner_cannot_enroll(tmp_path, changes):
    with (
        owned(tmp_path, enroll=False, **changes) as (engine, _, _),
        pytest.raises(ExecutionBlocked, match="IDENTITY_MISMATCH"),
    ):
        ScopeWatchBook(engine, policy(), now=AT, create=True)


def test_policy_is_frozen_and_closed_owner_cannot_mutate(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        with pytest.raises(ExecutionBlocked, match="POLICY_MISMATCH"):
            ScopeWatchBook(engine, policy(), now=AT, create=True)
        changed = policy().model_copy(update={"max_called_plays_per_session": 1})
        with pytest.raises(ExecutionBlocked, match="POLICY_MISMATCH"):
            ScopeWatchBook(engine, changed, now=AT)
        call(book)
    with pytest.raises(ExecutionBlocked, match="OWNER_CLOSED"):
        advance(book, now=frame().session.entry_cutoff_at)


@pytest.mark.parametrize("value", [0, 3, True, 1.5, "2"])
def test_daily_call_policy_is_explicit_and_cannot_exceed_two(value):
    with pytest.raises(ValidationError):
        ScopeWatchPolicy(context=context_policy(), max_called_plays_per_session=value)


def test_competing_actions_cannot_create_two_active_watches(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        expected = revision(engine)

        def attempt(key):
            try:
                return call(book, key=key, expected=expected)["record"]["status"]
            except ExecutionBlocked as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ("one", "two")))
        assert sorted(results) == ["SCOPE_WATCH_REVISION_CHANGED", "WATCHING"]
        assert len(book.snapshot()["watches"]) == 1


def test_independent_accounts_do_not_share_watch_counts_or_cash(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    with (
        owned(a, population_id="scope-A") as (ea, _, ba),
        owned(b, population_id="scope-B") as (eb, _, bb),
    ):
        first = call(ba)
        assert bb.snapshot()["watches"] == []
        second = call(bb)
        assert first["record"] == second["record"]
        for engine in (ea, eb):
            report = engine.journal.report(now=AT)
            assert D(report["ledger"]["cash"]) == D(1000)
            assert not report["orders"]


def test_rewound_clock_and_missing_enrollment_are_rejected(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        with pytest.raises(ExecutionBlocked, match="NOT_ENROLLED"):
            ScopeWatchBook(engine, policy(), now=AT)
        book = ScopeWatchBook(engine, policy(), now=AT, create=True)
        with pytest.raises(ExecutionBlocked, match="CLOCK_REWOUND"):
            call(book, now=AT - timedelta(microseconds=1))
        with pytest.raises(ValueError, match="timezone-aware"):
            call(book, now=AT.replace(tzinfo=None))


def test_fresh_next_session_does_not_erase_old_records(tmp_path):
    from app.options.scope import ScopePreflightInput

    with owned(tmp_path) as (engine, venue, book):
        f = frame()
        call(book, f=f)
        advance(book, now=f.session.entry_cutoff_at)
        # Explicitly supplied reviewed Tuesday evidence, not weekday/calendar inference.
        value = (
            f.model_dump_json()
            .replace("2026-10-09", "2026-10-13")
            .replace("2026-10-10", "2026-10-14")
        )
        f = ScopePreflightInput.model_validate_json(value)
        f = bind(bind_structure(f), context(f))
        now = f.histories[0].received_at
        ready(engine, venue, now)
        call(book, f=f, key="tuesday", now=now)
        watches = book.snapshot()["watches"]
        assert [w["session_date"] for w in watches] == ["2026-10-09", "2026-10-13"]
        assert [w["status"] for w in watches] == ["EXPIRED_UNFILLED", "WATCHING"]


def test_new_call_cannot_change_prior_history_or_session(tmp_path):
    with owned(tmp_path) as (engine, venue, book):
        f = frame()
        first = call(book, f=f)["record"]
        f = append(f, low=first["geometry"]["invalidation"])
        advance(book, f)
        f = append(f, close="100.7")
        ready(engine, venue, f.histories[0].received_at)
        changed = f.model_copy(
            update={"session": f.session.model_copy(update={"evidence_hash": "c" * 64})}
        )
        with pytest.raises(ExecutionBlocked, match="LOCKED_SESSION_CHANGED"):
            call(book, f=changed, key="second", now=f.histories[0].received_at)
        h = f.histories[0]
        changed = f.model_copy(
            update={
                "histories": (
                    h.model_copy(
                        update={"bars": (h.bars[0].model_copy(update={"volume": 101}), *h.bars[1:])}
                    ),
                    *f.histories[1:],
                )
            }
        )
        changed = bind_structure(changed)
        with pytest.raises(ExecutionBlocked, match="HISTORY_REWRITTEN"):
            call(book, f=changed, key="second", now=f.histories[0].received_at)


def test_context_variant_is_locked_to_its_parent_and_original_geometry(tmp_path):
    with owned(tmp_path) as (_, _, book):
        result = call(
            book,
            selected=choice(pattern="dealer_level_acceptance", parent="opening_range_break_hold"),
        )
        r = result["record"]
        assert r["choice"]["parent_pattern"] == "opening_range_break_hold"
        assert r["choice"]["pattern"] == "dealer_level_acceptance"
        parent = next(
            o
            for o in r["locked_scan"]["observations"]
            if o["pattern"] == "opening_range_break_hold" and o["right"] == "CALL"
        )
        assert r["geometry"] == parent["geometry"]


def test_native_activity_does_not_turn_watches_into_fills_or_outcomes(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        call(book)
        engine.prepare("hold", OptionProposal(action="HOLD", thesis="fixture"), now=AT)
        with pytest.raises(ExecutionBlocked, match="EXECUTION_LINK_NOT_IMPLEMENTED"):
            advance(book, now=frame().session.entry_cutoff_at)
        assert book.snapshot()["watches"][0]["status"] == "WATCHING"


def test_opposite_detected_setup_cannot_skip_pending_durable_neutral_reset(tmp_path):
    from app.options.scope_context import scan_scope_context

    with owned(tmp_path) as (engine, venue, book):
        f = frame()
        first = call(book, f=f)["record"]
        f = append(f, low=first["geometry"]["invalidation"])
        advance(book, f)
        f = append(f, close="99.5", cross_close="99.9")
        f = append(f, close="99.3", cross_close="99.8")
        instrument = f.metadata.instrument.model_copy(
            update={
                "instrument_id": "exact-SPXW-put",
                "contract": f.metadata.instrument.contract.model_copy(update={"right": "PUT"}),
            }
        )
        f = f.model_copy(
            update={
                "metadata": f.metadata.model_copy(
                    update={"instrument": instrument, "delta": D("-.99")}
                ),
                "quote": f.quote.model_copy(update={"instrument": instrument}),
            }
        )
        now = f.histories[0].received_at
        scan = scan_scope_context(f, context(f), policy().context, now=now)
        assert not scan.issues
        assert any(
            o.pattern == "opening_range_break_hold" and o.right == "PUT" and o.status == "DETECTED"
            for o in scan.observations
        )
        ready(engine, venue, now)
        with pytest.raises(ExecutionBlocked, match="DIRECTION_RESET_NOT_IMPLEMENTED"):
            call(book, f=f, key="opposite", now=now)


@pytest.mark.parametrize("table", ["execution_option_opportunities", "execution_option_runtime"])
def test_existing_runtime_or_opportunity_cannot_adopt_watch_policy(tmp_path, table):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        # Nonempty lifecycle evidence is enough to reject enrollment, even without a fill.
        with engine.journal.write() as db:
            db.execute(f"CREATE TABLE {table}(evidence TEXT)")
            db.execute(f"INSERT INTO {table} VALUES('existing cohort')")
        with pytest.raises(ExecutionBlocked, match="EXECUTION_LINK_NOT_IMPLEMENTED"):
            ScopeWatchBook(engine, policy(), now=AT, create=True)
