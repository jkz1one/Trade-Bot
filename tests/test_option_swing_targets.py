"""A missed original first target cannot become a fresh Swing entry after recovery."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT
from test_option_entry_coordination import fake_model
from test_option_shared_strategy import owner, shared_frame, swing_input, swing_policy

from app.execution.engine import ExecutionBlocked
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.shared_strategy import lock_seeds
from app.options.swing import SwingSeed, SwingTerminal, seed_issues
from app.options.swing_lifecycle import load_terminal, observe_quotes
from app.robinhood.schedule import XNYSCalendar

V3 = "observed-lifecycle-v3"
D = Decimal


def targeted(right="CALL", *, target=None):
    item = swing_input(right)
    value = D(605) if right == "CALL" else D(595)
    seed = SwingSeed.model_validate(item.seed.model_dump() | {"first_target": target or value})
    return shared_frame(right, item=item.model_copy(update={"seed": seed}))


def touch(f, *, at=AT):
    target = f.swing[0].seed.first_target
    call = f.swing[0].seed.instrument.contract.right == "CALL"
    return f.underlyings[0].model_copy(
        update={
            "bid": target if call else target - D(".01"),
            "ask": target + D(".01") if call else target,
            "source_at": at,
            "received_at": at,
        }
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_missed_target_recovery_and_restart_remain_terminal(tmp_path, right):
    f = targeted(right)
    with owner(tmp_path, right, lifecycle=V3) as (c, venue, _):
        lock_seeds(c, f.swing)
        asyncio.run(c.supervise((), (touch(f),)))
        asyncio.run(c.supervise((), f.underlyings))
        with c.engine.journal.read() as db:
            terminal = load_terminal(db, f.swing[0].seed)
        assert terminal.status == "TARGET_CONSUMED"
        assert terminal.first_target == f.swing[0].seed.first_target
        assert terminal.quote == touch(f) and terminal.history_hash is None
        scan = c.quote_plan(f.histories, (), f.swing)["scans"][0]
        assert "SWING_SEED_TARGET_CONSUMED" in scan.issues
        assert scan.observations[0].status == "BLOCKED"
        assert venue.submit_count == 0
        saved = c.engine.limits, c.engine.policy, c.policy, c.selection, c.swing_policy
    limits, execution, setup, selection, swing = saved
    with OptionExecution.open(tmp_path / "options.db", limits, execution, venue, now=AT) as e:
        c = DegenCoordinator(e, setup, selection, swing_policy=swing, clock=lambda: AT)
        with e.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) == terminal
        assert c.quote_plan(f.histories, (), f.swing)["scans"][0].terminal == terminal


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("bad", ["missing", "boundary", "wrong_side", "old_policy"])
def test_target_must_be_original_directional_and_enrolled(right, bad):
    seed = targeted(right).swing[0].seed
    reference = seed.history.bars[-1].high if right == "CALL" else seed.history.bars[-1].low
    policy = swing_policy(unfilled_lifecycle=V3)
    if bad == "old_policy":
        policy = swing_policy(unfilled_lifecycle="observed-invalidation-v2")
    else:
        seed = seed.model_copy(
            update={
                "first_target": {
                    "missing": None,
                    "boundary": reference,
                    "wrong_side": reference - 1 if right == "CALL" else reference + 1,
                }[bad]
            }
        )
    assert seed_issues(seed, policy, XNYSCalendar(), ("SPY",)) == (
        "SWING_FIRST_TARGET_POLICY_REQUIRED"
        if bad == "old_policy"
        else "SWING_ORIGINAL_FIRST_TARGET_REQUIRED",
    )
    legacy = swing_input(right).seed
    assert "first_target" not in legacy.model_dump()
    assert (
        "first_target"
        not in SwingTerminal(
            seed_hash=fingerprint(legacy),
            status="EXPIRED",
            observed_at=AT,
            triggered_at=AT,
        ).model_dump()
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "damage", ["stale", "future", "foreign", "duplicate", "incomplete", "crossed", "ask_only"]
)
def test_invalid_or_unreached_quote_cannot_consume_target(tmp_path, right, damage):
    with owner(tmp_path, right, lifecycle=V3) as (c, _, _):
        f = targeted(right)
        lock_seeds(c, f.swing)
        q = touch(f)
        changes = {
            "stale": {
                "source_at": AT - timedelta(minutes=1),
                "received_at": AT - timedelta(minutes=1),
            },
            "future": {
                "source_at": AT + timedelta(seconds=1),
                "received_at": AT + timedelta(seconds=1),
            },
            "foreign": {"source": "foreign"},
            "incomplete": {"complete": False},
            "crossed": {"bid": q.ask + 1},
            "ask_only": {"bid": q.bid - 1} if right == "CALL" else {"ask": q.ask + 1},
        }
        q = q.model_copy(update=changes.get(damage, {}))
        observe_quotes(c, (q, q) if damage == "duplicate" else (q,))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) is None


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("mode", ["target", "both", "unfinished", "foreign"])
def test_completed_target_touch_uses_valid_history_and_deterministic_tie(tmp_path, right, mode):
    with owner(tmp_path, right, lifecycle=V3) as (c, _, _):
        f = targeted(right)
        initial = c.quote_plan(f.histories, (), f.swing)["scans"][0]
        assert initial.terminal is None
        h = f.histories[0]
        change = {"high" if right == "CALL" else "low": f.swing[0].seed.first_target}
        if mode == "both":
            change["low" if right == "CALL" else "high"] = initial.observations[0].invalidation
        bar = h.bars[0].model_copy(update=change)
        bars = (bar, *h.bars[1:])
        if mode == "unfinished":
            bars = (*h.bars, bar.model_copy(update={"begins_at": AT}))
        h = h.model_copy(
            update={"bars": bars} | ({"source": "foreign"} if mode == "foreign" else {})
        )
        scan = c.quote_plan((h,), (), f.swing)["scans"][0]
        if mode in ("unfinished", "foreign"):
            assert scan.terminal is None
        else:
            assert scan.terminal.status == ("INVALIDATED" if mode == "both" else "TARGET_CONSUMED")
            assert scan.terminal.history_hash == fingerprint(h) and scan.terminal.quote is None
            assert scan.terminal.triggered_at == bar.ends_at
            lock_seeds(c, f.swing)
            from app.options.swing_lifecycle import retain_scans

            retain_scans(c, (scan,))
            assert c.quote_plan(f.histories, (), f.swing)["scans"][0].terminal == scan.terminal


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_target_cannot_be_replaced_and_first_terminal_wins(tmp_path, right):
    from test_option_swing_quotes import adverse

    with owner(tmp_path, right, lifecycle=V3) as (c, _, _):
        f = targeted(right)
        lock_seeds(c, f.swing)
        observe_quotes(c, (touch(f),))
        with c.engine.journal.read() as db:
            first = load_terminal(db, f.swing[0].seed)
        observe_quotes(c, (adverse(f, right),))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) == first
        other = targeted(right, target=D(606) if right == "CALL" else D(594))
        with pytest.raises(ExecutionBlocked, match="SWING_SEED_LOCK_CONFLICT"):
            lock_seeds(c, other.swing)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("phase", ["prepare", "dispatch", "prepared_tick"])
def test_paid_entry_target_race_persists_terminal_and_charge(tmp_path, monkeypatch, right, phase):
    with owner(tmp_path, right, ai=True, lifecycle=V3) as (c, venue, _):
        calls = fake_model(monkeypatch, c)
        f = targeted(right)
        q = touch(f)
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
            assert load_terminal(db, f.swing[0].seed).status == "TARGET_CONSUMED"
            assert D(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) == D(
                ".00015"
            )


@pytest.mark.parametrize("filled", [False, True])
def test_attempted_and_held_orders_are_not_unfilled_target_consumption(tmp_path, filled):
    from test_option_execution import intent_for

    with owner(tmp_path, lifecycle=V3) as (c, venue, _):
        f = targeted()
        result = asyncio.run(c.cycle(f))
        intent = intent_for(c.engine, result["client_id"])
        if filled:
            venue.fill(intent, intent.quantity, f.quotes[1], AT, fill_id="target-policy-fill")
            assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        asyncio.run(c.supervise((f.quotes[1],), (touch(f),)))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) is None
        assert venue.submit_count == 1


def test_runtime_and_observer_retain_target_evidence_without_read_side_effects(tmp_path):
    from test_option_observer import app_for, digest
    from test_option_runtime import enable, packet, policy, step

    from app.options.runtime import OptionRuntime

    with owner(tmp_path, lifecycle=V3) as (c, venue, _):
        f = targeted()
        lock_seeds(c, f.swing)
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        packet(r, value=f.model_copy(update={"underlyings": (touch(f),)}))
        asyncio.run(step(r))
        client, _ = app_for(c, tmp_path)
        before = digest((c.engine.journal.path,))
        response = client.get("/api/options", params={"family": "SWING"})
        assert response.status_code == 200 and "SWING_SEED_TARGET_CONSUMED" in response.text
        assert '"first_target":"605"' in response.text
        page = client.get("/")
        assert page.status_code == 200 and "Original first target 605" in page.text
        assert digest((c.engine.journal.path,)) == before and venue.submit_count == 0


def test_shortlist_target_is_visible_only_after_its_market_event(tmp_path):
    from test_option_evaluation import bundle_for
    from test_option_market_tape import header_for
    from test_option_shared_strategy import swing_policy

    from app.options.coordinator import DegenFrame
    from app.options.market_tape import TapeRecorder, load_tape, replay_shortlist

    f = targeted()
    h = header_for(bundle_for()).model_copy(update={"swing": swing_policy(unfilled_lifecycle=V3)})
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
            DegenFrame(underlyings=(touch(f, at=AT + timedelta(seconds=1)),)),
            recorded_at=AT + timedelta(seconds=1),
            kind="MARKET",
        )
        recorder.append(later_frame, recorded_at=later)
        recorder.seal()
    tape = load_tape(path)
    first = replay_shortlist(tape, tape.events[0].cycle_key, as_of=later)["scans"][0]
    final = replay_shortlist(tape, tape.events[-1].cycle_key, as_of=later)["scans"][0]
    assert "terminal" not in first
    assert final["terminal"]["quote"]["bid"] == "605"
    assert final["terminal"]["history_hash"] is None
    assert final["terminal"]["status"] == "TARGET_CONSUMED"


def test_native_replay_target_race_keeps_independent_arms_and_paid_costs(tmp_path):
    import sqlite3

    from test_option_admission import END
    from test_option_managed_replay import managed_settings
    from test_option_shared_replay import shared_tape

    from app.options.coordinator import DegenFrame
    from app.options.market_tape import TapeRecorder, load_tape
    from app.options.replay import run_replay

    original = shared_tape(tmp_path, lifecycle=V3, first_target=D(605))
    path = tmp_path / "quote-race.tape"
    with TapeRecorder(path, original.header) as recorder:
        for event in original.events:
            if AT + timedelta(seconds=6) < event.recorded_at < END:
                continue
            f = event.frame
            if event.recorded_at == AT + timedelta(seconds=1):
                f = DegenFrame(underlyings=(touch(targeted(), at=event.recorded_at),))
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
