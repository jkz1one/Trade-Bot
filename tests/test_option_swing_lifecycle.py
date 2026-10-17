"""A recovered breakout cannot revive an observed invalidated locked Swing seed."""

import asyncio
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame, policies
from test_option_entry_coordination import fake_model
from test_option_observer import app_for, digest
from test_option_shared_strategy import owner, shared_frame, swing_input, swing_policy

from app.execution.engine import ExecutionBlocked
from app.options.coordinator import DegenCoordinator
from app.options.degen import scan_degen
from app.options.engine import OptionExecution, fingerprint
from app.options.swing import scan_swing
from app.options.swing_lifecycle import load_terminal, retain_scans
from app.robinhood.schedule import XNYSCalendar

POLICY = "completed-invalidation-v1"
D = Decimal


def breached(right="CALL"):
    f = shared_frame(right)
    h = f.histories[0]
    bars = list(h.bars)
    bars[0] = bars[0].model_copy(update={"low": D(597)} if right == "CALL" else {"high": D(603)})
    return f.model_copy(update={"histories": (h.model_copy(update={"bars": tuple(bars)}),)})


def scan(f, *, at=AT, enrolled=True):
    cal = XNYSCalendar()
    h = f.histories[0]
    intraday = scan_degen(h, policies()[0], cal.current_window(at), now=at)
    return scan_swing(
        f.swing[0],
        swing_policy(unfilled_lifecycle=POLICY if enrolled else None),
        intraday,
        h,
        cal,
        ("SPY",),
        now=at,
        receive_lag=2,
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_completed_breach_then_recovery_is_terminal_only_in_enrolled_cohort(right):
    f = breached(right)
    old = scan(f, enrolled=False)
    assert old.observations[0].status == "CONFIRMED"  # Recorded pre-change reproducer.
    assert "terminal" not in old.model_dump()
    current = scan(f)
    assert current.observations[0].status == "BLOCKED"
    assert "SWING_SEED_INVALIDATED" in current.observations[0].reasons
    assert current.terminal.status == "INVALIDATED"
    assert current.terminal.triggered_at == f.histories[0].bars[0].ends_at
    assert current.terminal.history_hash == fingerprint(f.histories[0])
    assert current.terminal.seed_hash == fingerprint(f.swing[0].seed)
    assert current.terminal.invalidation == old.observations[0].invalidation


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_exact_touch_is_terminal_and_incomplete_bar_is_not_consumed(right):
    f = shared_frame(right)
    stop = scan(f).observations[0].invalidation
    h = f.histories[0]
    touch = h.bars[-1].model_copy(update={"low": stop} if right == "CALL" else {"high": stop})
    hit = f.model_copy(
        update={"histories": (h.model_copy(update={"bars": (*h.bars[:-1], touch)}),)}
    )
    assert scan(hit).terminal.triggered_at == AT
    unfinished = touch.model_copy(update={"begins_at": AT})
    h = h.model_copy(update={"bars": (*h.bars, unfinished)})
    assert scan(f.model_copy(update={"histories": (h,)})).terminal is None


@pytest.mark.parametrize("damage", ["source", "gap", "stale", "interpolated", "future_seed"])
def test_unreliable_evidence_never_retires_seed(damage):
    f = breached()
    h = f.histories[0]
    if damage == "source":
        h = h.model_copy(update={"source": "foreign"})
    elif damage == "gap":
        h = h.model_copy(update={"bars": h.bars[1:]})
    elif damage == "stale":
        h = h.model_copy(update={"source_at": AT - timedelta(minutes=10)})
    elif damage == "interpolated":
        h = h.model_copy(
            update={"bars": (h.bars[0].model_copy(update={"interpolated": True}), *h.bars[1:])}
        )
    else:
        item = f.swing[0]
        f = f.model_copy(
            update={
                "swing": (
                    item.model_copy(
                        update={"seed": item.seed.model_copy(update={"created_at": AT})}
                    ),
                )
            }
        )
    result = scan(f.model_copy(update={"histories": (h,)}))
    assert result.terminal is None and result.observations[0].status == "BLOCKED"


def test_unknown_catalyst_does_not_erase_observed_invalidation():
    f = breached()
    item = f.swing[0]
    f = f.model_copy(
        update={
            "swing": (
                item.model_copy(
                    update={"catalyst": item.catalyst.model_copy(update={"status": "UNKNOWN"})}
                ),
            )
        }
    )
    assert scan(f).terminal.status == "INVALIDATED"


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_cycle_retains_terminal_before_quote_work_and_restart_cannot_revive(tmp_path, right):
    with owner(tmp_path, right, lifecycle=POLICY) as (c, venue, _):
        f = breached(right).model_copy(update={"inventories": (), "quotes": ()})
        before = digest((c.engine.journal.path,))
        plan = c.quote_plan(f.histories, f.inventories, f.swing)
        assert plan["instruments"] == () and plan["scans"][0].terminal.status == "INVALIDATED"
        assert digest((c.engine.journal.path,)) == before
        result = asyncio.run(c.cycle(f))
        assert (
            result["status"] == "HOLD" and result["scans"][0]["terminal"]["status"] == "INVALIDATED"
        )
        with c.engine.journal.read() as db:
            saved_terminal = load_terminal(db, f.swing[0].seed)
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 0
        # Repeating retention cannot replace first evidence or create another event.
        retain_scans(c, plan["scans"])
        with c.engine.journal.read() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM execution_events WHERE kind='SWING_SEED_TERMINAL'"
                ).fetchone()[0]
                == 1
            )
        saved = c.engine.limits, c.engine.policy, c.policy, c.selection, c.swing_policy
        assert venue.submit_count == 0
        client, _password = app_for(c, tmp_path, clock=lambda: AT)
        before = digest((c.engine.journal.path,))
        api = client.get("/api/options", params={"family": "SWING"})
        page = client.get("/", params={"family": "SWING"})
        assert api.status_code == page.status_code == 200
        assert "SWING_SEED_INVALIDATED" in api.text and "SWING_SEED_INVALIDATED" in page.text
        assert digest((c.engine.journal.path,)) == before
    limits, execution, setup, selection, swing = saved
    with OptionExecution.open(tmp_path / "options.db", limits, execution, venue, now=AT) as e:
        c = DegenCoordinator(e, setup, selection, swing_policy=swing, clock=lambda: AT)
        revised = shared_frame(right)  # Removing the prior breach from history cannot revive it.
        plan = c.quote_plan(revised.histories, (), revised.swing)
        assert plan["instruments"] == ()
        assert plan["scans"][0].terminal == saved_terminal
        assert plan["scans"][0].observations[0].status == "BLOCKED"


@pytest.mark.parametrize("phase", ["prepare", "dispatch"])
@pytest.mark.parametrize("ai", [False, True])
def test_terminal_record_wins_entry_race_and_paid_call_keeps_its_cost(
    tmp_path, monkeypatch, phase, ai
):
    with owner(tmp_path, lifecycle=POLICY, ai=ai) as (c, venue, _):
        if ai:
            fake_model(monkeypatch, c)
        terminal = scan(breached())
        original = getattr(c.engine, phase)
        if phase == "prepare":

            def prepare(*args, **kwargs):
                retain_scans(c, (terminal,))
                return original(*args, **kwargs)

            monkeypatch.setattr(c.engine, phase, prepare)
        else:

            async def dispatch(*args, **kwargs):
                retain_scans(c, (terminal,))
                return await original(*args, **kwargs)

            monkeypatch.setattr(c.engine, phase, dispatch)
        result = asyncio.run(c.cycle(shared_frame()))
        assert result["status"] != "OPEN" and venue.submit_count == 0
        assert "SWING_SEED_TERMINAL" in json.dumps(c.engine.journal.report(now=AT))
        with c.engine.journal.read() as db:
            calls = db.execute("SELECT cost FROM execution_model_calls").fetchall()
            assert len(calls) == int(ai)
            assert all(r[0] is not None and D(r[0]) > 0 for r in calls)


def test_swing_terminal_does_not_block_independent_degen_candidate(tmp_path):
    with owner(tmp_path, lifecycle=POLICY) as (c, venue, _):
        f = breached().model_copy(update={"quotes": frame().quotes})
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        assert venue.submit_count == 1
        assert result["candidates"][0]["family"] != "SWING_DAILY_BREAKOUT"
        assert result["scans"][0]["terminal"]["status"] == "INVALIDATED"


@pytest.mark.parametrize("target", [date(2026, 10, 9), date(2026, 11, 27)])
def test_expiry_uses_actual_close_and_first_terminal_wins(tmp_path, target):
    from app.options.shared_strategy import lock_seeds

    item = swing_input(target=target)
    close = XNYSCalendar().calendar.session_close(target.isoformat()).to_pydatetime()
    with owner(tmp_path, lifecycle=POLICY) as (c, _, times):
        times[0] = close - timedelta(microseconds=1)
        lock_seeds(c, (item,))
        with c.engine.journal.read() as db:
            assert load_terminal(db, item.seed) is None
        times[0] = close
        lock_seeds(c, (item,))
        with c.engine.journal.read() as db:
            terminal = load_terminal(db, item.seed)
        assert terminal.status == "EXPIRED" and terminal.triggered_at == close
        assert terminal.history_hash is None
        times[0] = close + timedelta(days=3)
        lock_seeds(c, (item,))
        with c.engine.journal.read() as db:
            assert load_terminal(db, item.seed) == terminal


def test_new_population_required_and_legacy_hashes_unchanged(tmp_path):
    assert "unfilled_lifecycle" not in swing_policy().model_dump()
    with owner(tmp_path) as (c, venue, _):
        with c.engine.journal.read() as db:
            assert not db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='execution_option_swing_terminals'"
            ).fetchone()
        saved = c.engine.limits, c.engine.policy, c.policy, c.selection
    limits, execution, setup, selection = saved
    with (
        OptionExecution.open(tmp_path / "options.db", limits, execution, venue, now=AT) as e,
        pytest.raises(ExecutionBlocked, match="FROZEN_DEGEN_STRATEGY"),
    ):
        DegenCoordinator(
            e,
            setup,
            selection,
            swing_policy=swing_policy(unfilled_lifecycle=POLICY),
            clock=lambda: AT,
        )


def test_expiry_preserves_invalidation_and_fresh_session_has_its_own_seed(tmp_path):
    from app.options.shared_strategy import lock_seeds

    with owner(tmp_path, lifecycle=POLICY) as (c, _, times):
        f = breached().model_copy(update={"inventories": (), "quotes": ()})
        asyncio.run(c.cycle(f))
        with c.engine.journal.read() as db:
            first = load_terminal(db, f.swing[0].seed)
        times[0] = AT + timedelta(days=3)
        new = swing_input(target=times[0].date())
        lock_seeds(c, (f.swing[0], new))
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) == first
            assert load_terminal(db, new.seed) is None


def test_independent_population_does_not_inherit_terminal(tmp_path):
    bad, good = tmp_path / "bad", tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    with owner(bad, lifecycle=POLICY) as (c, venue, _):
        f = breached().model_copy(update={"inventories": (), "quotes": ()})
        assert asyncio.run(c.cycle(f))["status"] == "HOLD"
        assert venue.submit_count == 0
    with owner(good, lifecycle=POLICY) as (c, venue, _):
        assert asyncio.run(c.cycle(shared_frame()))["status"] == "OPEN"
        assert venue.submit_count == 1
        with c.engine.journal.read() as db:
            assert load_terminal(db, f.swing[0].seed) is None


@pytest.mark.parametrize("breach_first", [True, False])
def test_shortlist_reconstructs_only_visible_terminal_prefix(tmp_path, breach_first):
    from test_option_evaluation import bundle_for
    from test_option_market_tape import header_for

    from app.options.market_tape import TapeRecorder, load_tape, replay_shortlist

    first = breached() if breach_first else shared_frame()
    later = shared_frame() if breach_first else breached()
    later_at = AT + timedelta(minutes=5)
    h = later.histories[0]
    h = h.model_copy(
        update={
            "source_at": later_at,
            "received_at": later_at,
            "bars": (*h.bars, h.bars[-1].model_copy(update={"begins_at": AT})),
        }
    )
    later = later.model_copy(update={"histories": (h,)})
    header = header_for(bundle_for()).model_copy(
        update={"swing": swing_policy(unfilled_lifecycle=POLICY)}
    )
    path = tmp_path / "terminal.tape"
    with TapeRecorder(path, header) as recorder:
        recorder.append(first, recorded_at=AT)
        recorder.append(later, recorded_at=later_at)
        recorder.seal()
    tape = load_tape(path)
    a = replay_shortlist(tape, tape.events[0].cycle_key, as_of=later_at)["scans"][0]
    b = replay_shortlist(tape, tape.events[1].cycle_key, as_of=later_at)["scans"][0]
    assert ("terminal" in a) == breach_first
    assert b["terminal"]["status"] == "INVALIDATED"
    if breach_first:
        assert b["terminal"] == a["terminal"]
    else:
        assert datetime.fromisoformat(b["terminal"]["observed_at"]) == later_at


@pytest.mark.parametrize("lifecycle", [POLICY, "observed-invalidation-v2"])
def test_enrolled_native_abcd_replay_retains_independent_accounts_and_every_cost(
    tmp_path, lifecycle
):
    import sqlite3

    from test_option_managed_replay import managed_settings
    from test_option_shared_replay import shared_tape

    from app.options.replay import run_replay

    tape = shared_tape(tmp_path, full=True, lifecycle=lifecycle)
    result = asyncio.run(run_replay(managed_settings(tape), tape, tmp_path / "run"))
    assert result["report"]["status"] == "COMPLETE_ARITHMETIC"
    assert result["report"]["economic_conclusion"] == "INCONCLUSIVE"
    rows = result["bundle"]["evidence"]
    assert len({r["orders"][0]["intent"]["client_id"] for r in rows}) == 4
    costs = result["report"]["sessions"][0]["arms"]
    for row in rows:
        arm = row["arm"]
        assert [call["role"] for call in row["calls"]] == (
            [] if arm == "A" else ["ENTRY", "MANAGEMENT"] if arm == "D" else ["ENTRY"]
        )
        assert all(call["usage"] is not None for call in row["calls"])
        assert (
            D(costs[arm]["known_model_cost"]) > 0
            if row["calls"]
            else D(costs[arm]["known_model_cost"]) == 0
        )
        assert row["orders"][0]["intent"]["instrument"]["instrument_id"] == "swing-locked-contract"
        assert D(row["closing"]["fees_paid"]) > 0
        assert D(costs[arm]["net_change"]) == D(row["closing"]["cash"]) - D(
            row["initial"]["cash"]
        ) - D(costs[arm]["known_model_cost"]) - D(".03")
        with sqlite3.connect(tmp_path / "run" / arm / "journal.db") as db:
            assert db.execute("SELECT count(*) FROM execution_option_swing_terminals").fetchone()[
                0
            ] == (1 if lifecycle == "observed-invalidation-v2" else 0)
            if lifecycle == "observed-invalidation-v2":
                terminal = json.loads(
                    db.execute(
                        "SELECT terminal_json FROM execution_option_swing_terminals"
                    ).fetchone()[0]
                )
                last_fill = max(
                    datetime.fromisoformat(fill["occurred_at"])
                    for order in row["orders"]
                    for fill in order["observation"]["fills"]
                )
                assert datetime.fromisoformat(terminal["triggered_at"]) >= last_fill
                assert terminal["quote"] is not None
            assert (
                json.loads(
                    db.execute("SELECT policy_json FROM execution_option_strategy").fetchone()[0]
                )["swing"]["unfilled_lifecycle"]
                == lifecycle
            )
    assert D(costs["D"]["known_model_cost"]) == 2 * D(costs["C"]["known_model_cost"])
    assert (
        costs["D"]["model_cost_by_role"]["ENTRY"] == costs["D"]["model_cost_by_role"]["MANAGEMENT"]
    )
    assert result["live_enabled"] is False
