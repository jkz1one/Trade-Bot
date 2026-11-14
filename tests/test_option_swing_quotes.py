"""Observed quote breaches retire Swing seeds between completed-bar decisions."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT
from test_option_entry_coordination import fake_model
from test_option_execution import intent_for
from test_option_observer import app_for, digest
from test_option_shared_strategy import owner, shared_frame

from app.options.coordinator import DegenCoordinator, DegenFrame
from app.options.engine import OptionExecution
from app.options.shared_strategy import lock_seeds
from app.options.swing_lifecycle import load_terminal, observe_quotes

V2 = "observed-invalidation-v2"
D = Decimal


def adverse(f, right="CALL", *, at=AT):
    return f.underlyings[0].model_copy(
        update={
            "bid": D(590) if right == "CALL" else D(610),
            "ask": D(590) if right == "CALL" else D(610),
            "source_at": at,
            "received_at": at,
        }
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("version", ["completed-invalidation-v1", V2])
def test_quote_breach_recovery_and_restart_preserve_frozen_version(tmp_path, right, version):
    with owner(tmp_path, right, lifecycle=version) as (c, venue, _):
        f = shared_frame(right)
        lock_seeds(c, f.swing)
        q = adverse(f, right)
        asyncio.run(c.supervise((), (q,)))
        asyncio.run(c.supervise((), f.underlyings))
        with c.engine.journal.read() as db:
            terminal = load_terminal(db, f.swing[0].seed)
        assert (terminal is not None) == (version == V2)
        if terminal:
            assert terminal.quote == q and terminal.history_hash is None
        planned = c.quote_plan(f.histories, (), f.swing)
        assert planned["scans"][0].observations[0].status == (
            "BLOCKED" if terminal else "CONFIRMED"
        )
        assert venue.submit_count == 0
        saved = c.engine.limits, c.engine.policy, c.policy, c.selection, c.swing_policy
    limits, execution, setup, selection, swing = saved
    with OptionExecution.open(tmp_path / "options.db", limits, execution, venue, now=AT) as e:
        c = DegenCoordinator(e, setup, selection, swing_policy=swing, clock=lambda: AT)
        with e.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) == terminal


@pytest.mark.parametrize(
    "damage",
    [
        "stale",
        "future",
        "lag",
        "source",
        "symbol",
        "delayed",
        "incomplete",
        "crossed",
        "floor",
        "duplicate",
    ],
)
def test_bad_or_ambiguous_quotes_cannot_establish_a_terminal(tmp_path, damage):
    with owner(tmp_path, lifecycle=V2) as (c, venue, _):
        f = shared_frame()
        lock_seeds(c, f.swing)
        q = adverse(f)
        changes = {
            "stale": {
                "source_at": AT - timedelta(seconds=60),
                "received_at": AT - timedelta(seconds=60),
            },
            "future": {
                "source_at": AT + timedelta(seconds=1),
                "received_at": AT + timedelta(seconds=1),
            },
            "lag": {
                "source_at": AT - timedelta(seconds=c.engine.limits.max_receive_lag_seconds + 1)
            },
            "source": {"source": "foreign"},
            "symbol": {"symbol": "QQQ"},
            "delayed": {"entitlement": "DELAYED"},
            "incomplete": {"complete": False},
            "crossed": {"bid": D(590), "ask": D(589)},
            "floor": {"bid": D(1), "ask": D(2)},
        }
        q = q.model_copy(update=changes.get(damage, {}))
        asyncio.run(c.supervise((), (q, q) if damage == "duplicate" else (q,)))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) is None
        assert venue.submit_count == 0


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_exact_quote_touch_uses_adverse_side_and_retains_first_observation(tmp_path, right):
    with owner(tmp_path, right, lifecycle=V2) as (c, _, times):
        f = shared_frame(right)
        lock_seeds(c, f.swing)
        stop = c.quote_plan(f.histories, (), f.swing)["scans"][0].observations[0].invalidation
        q = f.underlyings[0].model_copy(
            update={
                "bid": stop if right == "CALL" else stop - D(".01"),
                "ask": stop + D(".01") if right == "CALL" else stop,
            }
        )
        observe_quotes(c, (q,))
        with c.engine.journal.read() as db:
            first = load_terminal(db, f.swing[0].seed)
        assert first.quote == q and first.invalidation == stop
        times[0] += timedelta(seconds=1)
        observe_quotes(c, (adverse(f, right, at=times[0]),))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) == first
            assert (
                db.execute(
                    "SELECT count(*) FROM execution_events WHERE kind='SWING_SEED_TERMINAL'"
                ).fetchone()[0]
                == 1
            )


@pytest.mark.parametrize("phase", ["prepare", "dispatch", "prepared_tick"])
@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_native_review_persists_quote_race_and_keeps_paid_entry_cost(
    tmp_path, monkeypatch, phase, right
):
    with owner(tmp_path, right, ai=True, lifecycle=V2) as (c, venue, _):
        calls = fake_model(monkeypatch, c)
        f = shared_frame(right)
        q = adverse(f, right)
        if phase == "prepare":
            original = c.engine.prepare

            def prepare(key, proposal, quote=None, underlying=None, **kwargs):
                return original(key, proposal, quote, q, **kwargs)

            monkeypatch.setattr(c.engine, "prepare", prepare)
        else:
            original = c.engine.dispatch

            async def dispatch(client_id, quote, underlying, *, now):
                if phase == "prepared_tick":
                    observe_quotes(c, (q,))
                return await original(
                    client_id, quote, underlying if phase == "prepared_tick" else q, now=now
                )

            monkeypatch.setattr(c.engine, "dispatch", dispatch)
        result = asyncio.run(c.cycle(f))
        assert result["status"] != "OPEN" and venue.submit_count == 0 and len(calls) == 1
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed).quote == q
            assert D(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) == D(
                ".00015"
            )


@pytest.mark.parametrize("filled", [False, True])
def test_attempted_and_filled_positions_keep_existing_protection(tmp_path, filled):
    with owner(tmp_path, lifecycle=V2) as (c, venue, _):
        f = shared_frame()
        result = asyncio.run(c.cycle(f))
        intent = intent_for(c.engine, result["client_id"])
        if filled:
            venue.fill(intent, intent.quantity, f.quotes[1], AT, fill_id="quote-policy-fill")
            assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        result = asyncio.run(c.supervise((f.quotes[1],), (adverse(f),)))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) is None
        if filled:
            assert result["status"] == "OPEN" and venue.submit_count == 2
            assert (
                c.engine.assess(f.quotes[1], adverse(f), now=AT)["exit_reason"]
                == "UNDERLYING_INVALIDATION"
            )


def test_runtime_tick_retains_quote_and_observer_reads_saved_evidence_only(tmp_path):
    from test_option_runtime import enable, packet, policy, step

    from app.options.runtime import OptionRuntime

    with owner(tmp_path, lifecycle=V2) as (c, venue, _):
        f = shared_frame()
        lock_seeds(c, f.swing)
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        packet(r, value=f.model_copy(update={"underlyings": (adverse(f),)}))
        asyncio.run(step(r))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed).quote == adverse(f)
        client, _ = app_for(c, tmp_path)
        before = digest((c.engine.journal.path,))
        api = client.get("/api/options", params={"family": "SWING"})
        assert api.status_code == 200 and "SWING_SEED_INVALIDATED" in api.text
        assert '"quote"' in api.text
        assert client.get("/").status_code == 200
        assert digest((c.engine.journal.path,)) == before and venue.submit_count == 0


def test_shortlist_market_quote_is_visible_only_after_its_event(tmp_path):
    from test_option_evaluation import bundle_for
    from test_option_market_tape import header_for
    from test_option_shared_strategy import swing_policy

    from app.options.market_tape import TapeRecorder, load_tape, replay_shortlist

    f = shared_frame()
    h = header_for(bundle_for()).model_copy(update={"swing": swing_policy(unfilled_lifecycle=V2)})
    path = tmp_path / "quotes.tape"
    later = AT + timedelta(minutes=5)
    history = f.histories[0]
    later_frame = f.model_copy(
        update={
            "histories": (
                history.model_copy(
                    update={
                        "source_at": later,
                        "received_at": later,
                        "bars": (
                            *history.bars,
                            history.bars[-1].model_copy(update={"begins_at": AT}),
                        ),
                    }
                ),
            )
        }
    )
    with TapeRecorder(path, h) as recorder:
        recorder.append(f, recorded_at=AT)
        recorder.append(
            DegenFrame(underlyings=(adverse(f, at=AT + timedelta(seconds=1)),)),
            recorded_at=AT + timedelta(seconds=1),
            kind="MARKET",
        )
        recorder.append(later_frame, recorded_at=later)
        recorder.seal()
    tape = load_tape(path)
    first = replay_shortlist(tape, tape.events[0].cycle_key, as_of=later)["scans"][0]
    final = replay_shortlist(tape, tape.events[-1].cycle_key, as_of=later)["scans"][0]
    assert "terminal" not in first
    assert final["terminal"]["quote"]["bid"] == "590"
    assert final["terminal"]["history_hash"] is None
    assert final["terminal"]["status"] == "INVALIDATED"


def test_native_replay_quote_race_retires_only_unattempted_independent_arms(tmp_path):
    import sqlite3

    from test_option_admission import END
    from test_option_managed_replay import managed_settings
    from test_option_shared_replay import shared_tape

    from app.options.market_tape import TapeRecorder, load_tape
    from app.options.replay import run_replay

    original = shared_tape(tmp_path, lifecycle=V2)
    path = tmp_path / "quote-race.tape"
    with TapeRecorder(path, original.header) as recorder:
        for event in original.events:
            if AT + timedelta(seconds=6) < event.recorded_at < END:
                continue
            f = event.frame
            if event.recorded_at == AT + timedelta(seconds=1):
                f = DegenFrame(underlyings=(adverse(shared_frame(), at=event.recorded_at),))
            recorder.append(f, recorded_at=event.recorded_at, kind=event.kind)
        recorder.seal()
    tape = load_tape(path)
    result = asyncio.run(run_replay(managed_settings(tape), tape, tmp_path / "run"))
    assert result["report"]["economic_conclusion"] == "INCONCLUSIVE"
    rows = {r["arm"]: r for r in result["bundle"]["evidence"]}
    assert rows["A"]["orders"]  # Already attempted; no cancellation or synthetic flat state.
    for arm in "ABCD":
        with sqlite3.connect(tmp_path / "run" / arm / "journal.db") as db:
            assert db.execute("SELECT count(*) FROM execution_option_swing_terminals").fetchone()[
                0
            ] == (0 if arm == "A" else 1)
            if arm != "A":
                assert rows[arm]["orders"] == []
                assert D(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) == D(
                    ".00015"
                )
                assert all(c["usage"] is not None for c in rows[arm]["calls"])
    assert result["live_enabled"] is False
