"""Continuous Scope inputs exercise native watch, paid review and independent exits."""

import asyncio
import json
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_option_execution import intent_for, ledger
from test_option_runtime import enable, policy, state, step
from test_option_scope_ai import ai_owner
from test_option_scope_arbitration import shared
from test_option_scope_trading_replay import request

from app.options.coordinator import DegenFrame
from app.options.engine import OptionExecution, fingerprint
from app.options.runtime import OptionRuntime, read_packet
from app.options.runtime_cli import _coordinator, initialize
from app.options.runtime_models import (
    RuntimePacket,
    RuntimeSettings,
    ScopeRuntimeAction,
    ScopeRuntimePacket,
)
from app.options.venue import DurableOptionVenue


def settings(req, path):
    return RuntimeSettings(
        limits=req.limits,
        execution=req.execution,
        scope_policy=req.scope,
        setup=req.tape.header.setup,
        selection=req.tape.header.selection,
        runtime=policy(path, scope_inputs="scope-runtime-inputs-v1"),
    )


def send(r, frame, *, kind="MARKET", action=None, sequence=None, at=None):
    with r.c.engine.journal.read() as db:
        prior = db.execute("SELECT feed_sequence FROM execution_option_runtime").fetchone()[0]
    packet = ScopeRuntimePacket(
        population_id=r.c.engine.limits.population_id,
        sequence=prior + 1 if sequence is None else sequence,
        recorded_at=at or r.c.now(),
        frame=frame,
        kind=kind,
        action=action,
    )
    path = Path(r.policy.feed_file)
    path.write_text(packet.model_dump_json())
    path.chmod(0o600)
    return packet


@contextmanager
def owner(tmp_path, right="CALL"):
    req = request(tmp_path, right)
    s = settings(req, tmp_path)
    times = [req.tape.header.opens_at]
    directory = tmp_path / "runtime"
    initialize(directory, s, clock=lambda: times[0])
    v = DurableOptionVenue(directory / "venue.db")
    with OptionExecution.open(
        directory / "options.db", s.limits, s.execution, v, now=times[0]
    ) as e:
        c = _coordinator(e, s, False, lambda: times[0])
        r = OptionRuntime(c, s.runtime)
        enable(r)
        yield r, req, times, v


def rows(r):
    with r.c.engine.journal.read() as db:
        return [
            dict(x)
            for x in db.execute(
                "SELECT * FROM execution_option_scope_runtime_inputs ORDER BY sequence"
            )
        ]


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_continuous_watch_arming_cycle_fill_and_nested_protection(tmp_path, right):
    with owner(tmp_path, right) as (r, req, times, venue):

        async def exercise():
            for action in req.watch_actions:
                event = next(e for e in req.tape.events if e.sequence == action.sequence)
                times[0] = event.recorded_at
                send(
                    r,
                    event.frame,
                    kind="WATCH",
                    action=ScopeRuntimeAction(
                        key=action.key,
                        kind="OBSERVE_ARMING" if action.kind == "REVIEW_ADMISSION" else action.kind,
                        play_key=action.play_key,
                        choice=action.choice,
                    ),
                )
                await step(r)
                assert rows(r)[-1]["status"] == "RECORDED", rows(r)[-1]
                assert state(r.c)["cycles"] == {}
            cycle = next(e for e in req.tape.events if e.kind == "CYCLE")
            times[0] = cycle.recorded_at
            send(r, cycle.frame, kind="CYCLE")
            await step(r)
            with r.c.engine.journal.read() as db:
                order = db.execute("SELECT client_id FROM execution_orders").fetchone()
                assert order is not None
                key = order[0]
            buy = intent_for(r.c.engine, key)
            times[0] += timedelta(seconds=1)
            item = cycle.frame.scope
            quote = item.frame.quote.model_copy(
                update={"source_at": times[0], "received_at": times[0]}
            )
            venue.fill(
                buy,
                buy.quantity,
                quote,
                times[0],
                fill_id="scope-runtime-entry",
                underlying=item.underlying.model_copy(
                    update={"source_at": times[0], "received_at": times[0]}
                ),
            )
            nested = item.model_copy(
                update={"frame": item.frame.model_copy(update={"quote": quote})}
            )
            send(r, DegenFrame(scope=nested))
            await step(r)
            assert ledger(r.c.engine).position.quantity == buy.quantity
            # Runtime must project the nested quote even when common arrays are empty.
            times[0] = item.frame.session.protect_at
            quote = quote.model_copy(update={"source_at": times[0], "received_at": times[0]})
            underlying = item.underlying.model_copy(
                update={"source_at": times[0], "received_at": times[0]}
            )
            nested = item.model_copy(
                update={
                    "frame": item.frame.model_copy(update={"quote": quote}),
                    "underlying": underlying,
                }
            )
            send(r, DegenFrame(scope=nested))
            await step(r)
            assert ledger(r.c.engine).position.exit_reason == "TIME_EXIT"
            with r.c.engine.journal.read() as db:
                assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 2
                assert (
                    db.execute("SELECT COUNT(*) FROM execution_option_opportunities").fetchone()[0]
                    == 1
                )
            last = rows(r)[-1]
            await step(r)
            assert rows(r)[-1] == last  # Same packet does not repeat any watch action.
            from app.options.scope_execution_export import (
                export_scope_execution,
                verify_scope_execution_export,
            )

            exported = export_scope_execution(
                r.c.engine.journal, now=times[0], data_cost=".01", host_cost=".02"
            )
            assert exported["report"]["scope_runtime"]["statuses"]["RECORDED"] == 8
            assert (
                verify_scope_execution_export(exported, exported["export_hash"])["status"]
                == "VERIFIED_NATIVE_ACCOUNTING"
            )
            damaged = json.loads(json.dumps(exported))
            damaged["evidence"]["execution_option_scope_runtime_inputs"][0][1] = "0" * 64
            damaged["export_hash"] = fingerprint(
                {k: v for k, v in damaged.items() if k != "export_hash"}
            )
            with pytest.raises(ValueError, match="delivery binding"):
                verify_scope_execution_export(damaged, damaged["export_hash"])

        asyncio.run(exercise())


@pytest.mark.parametrize(
    "change", ["runtime", "scope", "owner", "costs", "priority", "universe", "source", "capacity"]
)
def test_settings_require_complete_explicit_scope_enrollment(tmp_path, change):
    req = request(tmp_path)
    raw = settings(req, tmp_path).model_dump()
    if change == "runtime":
        raw["runtime"]["scope_inputs"] = None
    if change == "scope":
        raw["scope_policy"] = None
    if change == "owner":
        raw["execution"]["scope_arbitration"] = None
    if change == "costs":
        raw["scope_policy"]["version"] = "shared-scope-entry-v1"
    if change == "priority":
        raw["scope_policy"]["family_priority"] = ("SCOPE", "SWING", "DEGEN")
    if change == "universe":
        raw["limits"]["allowed_underlyings"] = ("SPY",)
    if change == "source":
        raw["limits"]["option_source"] = "foreign"
    if change == "capacity":
        raw["setup"]["symbols"] = ("SPY", "SPX")
        raw["selection"]["max_quote_contracts"] = 4
    with pytest.raises(ValueError):
        RuntimeSettings.model_validate(raw)


def test_legacy_packets_reject_scope_and_preserve_absent_serialization(tmp_path):
    from test_option_runtime import settings as legacy
    from test_option_scope_market_tape import inputs

    raw = legacy(tmp_path).model_dump(mode="json")
    assert "scope_policy" not in raw and "scope_inputs" not in raw["runtime"]
    packet = RuntimePacket(
        population_id="old", sequence=1, recorded_at=inputs()[0].opens_at, frame=DegenFrame()
    )
    old = packet.model_dump(mode="json")
    old.pop("version")
    path = tmp_path / "old.json"
    path.write_text(json.dumps(old))
    path.chmod(0o600)
    assert read_packet(path) == packet
    assert list(packet.model_dump()) == [
        "version",
        "population_id",
        "sequence",
        "recorded_at",
        "frame",
    ]
    with pytest.raises(ValueError):
        RuntimePacket.model_validate(packet.model_dump() | {"frame": inputs()[1]})


@pytest.mark.parametrize(
    "damage", ["gap", "future", "conflict", "foreign", "nested", "duplicate", "session"]
)
def test_bad_inputs_fence_before_supervisor_and_preserve_last_receipt(
    tmp_path, monkeypatch, damage
):
    with shared(tmp_path) as (c, _, times, f):
        r = OptionRuntime(c, policy(tmp_path, scope_inputs="scope-runtime-inputs-v1"), create=True)
        enable(r)
        send(r, f, kind="CYCLE")
        asyncio.run(step(r))
        before = rows(r)
        times[0] += timedelta(seconds=1)
        change = {}
        if damage == "gap":
            change["sequence"] = 3
        if damage == "future":
            change["at"] = times[0] + timedelta(seconds=1)
        if damage == "conflict":
            change["sequence"] = 1
        if damage == "foreign":
            f = f.model_copy(
                update={
                    "scope": f.scope.model_copy(
                        update={
                            "underlying": f.scope.underlying.model_copy(update={"source": "wrong"})
                        }
                    )
                }
            )
        if damage == "nested":
            f = f.model_copy(
                update={
                    "underlyings": (
                        *f.underlyings,
                        f.scope.underlying.model_copy(update={"bid": Decimal(1)}),
                    )
                }
            )
        if damage == "duplicate":
            f = f.model_copy(update={"quotes": (f.quotes[0], f.quotes[0])})
        if damage == "session":
            f = f.model_copy(
                update={
                    "scope": f.scope.model_copy(
                        update={"frame": f.scope.frame.model_copy(update={"session": None})}
                    )
                }
            )
        # Market packets cannot carry ordinary cycle-only payloads.
        send(r, f, kind="CYCLE", **change)
        original = c.supervise

        async def supervise(*args):
            with c.engine.journal.read() as db:
                assert c.engine._control(db)["halted"]
            return await original(*args)

        monkeypatch.setattr(c, "supervise", supervise)
        asyncio.run(step(r))
        assert state(c)["status"] == "BLOCKED"
        assert rows(r) == before


@pytest.mark.parametrize("mode", ["fresh", "unchanged", "feed-loss", "late", "same-clocks"])
def test_paid_scope_uses_only_delivered_post_cost_input(tmp_path, monkeypatch, mode):
    with ai_owner(tmp_path, monkeypatch) as (c, _, times, f, _):
        fixture_refresh = c.scope_refresh
        r = OptionRuntime(c, policy(tmp_path, scope_inputs="scope-runtime-inputs-v1"), create=True)
        enable(r)
        original = c._model_run

        async def exercise():
            started, release = asyncio.Event(), asyncio.Event()

            async def model(*args, **kwargs):
                started.set()
                await release.wait()
                return await original(*args, **kwargs)

            monkeypatch.setattr(c, "_model_run", model)
            send(r, f, kind="CYCLE")
            await r.tick()
            await asyncio.wait_for(started.wait(), 15)
            times[0] += timedelta(seconds=1)
            if mode != "unchanged":
                if mode == "late":
                    times[0] += timedelta(seconds=10)
                value = (
                    f.scope if mode == "same-clocks" else await fixture_refresh(f.scope.play_key)
                )
                send(r, DegenFrame(scope=value))
                await r.tick()
                assert await c.scope_refresh(f.scope.play_key) == value
                if mode == "feed-loss":
                    Path(r.policy.feed_file).unlink()
                    await r.tick()
            release.set()
            await r.task
            with c.engine.journal.read() as db:
                assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == int(
                    mode == "fresh"
                )
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NOT NULL"
                    ).fetchone()[0]
                    == 1
                )

        asyncio.run(exercise())


def test_watch_rejection_and_restart_receipts_never_retry(tmp_path):
    with owner(tmp_path) as (r, req, times, _):
        event = req.tape.events[0]
        times[0] = event.recorded_at
        action = ScopeRuntimeAction(key="missing", kind="OBSERVE_ARMING", play_key="first")
        p = send(r, event.frame, kind="WATCH", action=action)
        asyncio.run(step(r))
        assert rows(r)[0]["status"] == "REJECTED"
        asyncio.run(step(r))
        assert len(rows(r)) == 1
        send(r, event.frame, kind="WATCH", action=action)
        asyncio.run(step(r))
        assert state(r.c)["status"] == "BLOCKED" and len(rows(r)) == 1
        # Simulate a process ending after a new receipt persisted but before its action finished.
        with r.c.engine.journal.write() as db:
            db.execute(
                "UPDATE execution_option_scope_runtime_inputs SET status='PENDING',result_json=NULL WHERE sequence=1"
            )
        r.c.engine._option_runtime = None
        reopened = OptionRuntime(r.c, r.policy)
        assert rows(reopened)[0]["status"] == "INTERRUPTED"
        with r.c.engine.journal.read() as db:
            assert r.c.engine._control(db)["halted"]
        enable(reopened)
        Path(r.policy.feed_file).write_text(p.model_dump_json())
        asyncio.run(step(reopened))
        assert rows(reopened)[0]["status"] == "INTERRUPTED"


def test_scope_packet_cannot_enter_legacy_runtime(tmp_path):
    from test_degen_options import owned_strategy

    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        send(r, DegenFrame())
        assert isinstance(read_packet(r.policy.feed_file), ScopeRuntimePacket)
        asyncio.run(step(r))
        assert state(c)["status"] == "BLOCKED" and state(c)["feed_sequence"] == 0


@pytest.mark.parametrize("kind", ["WATCH", "MARKET", "CYCLE"])
def test_scope_packet_cannot_smuggle_watch_or_full_cycle(kind):
    from test_option_scope_market_tape import inputs

    h, f = inputs()
    action = ScopeRuntimeAction(key="advance", kind="ADVANCE", play_key="first")
    with pytest.raises(ValueError):
        ScopeRuntimePacket(
            population_id="x",
            sequence=1,
            recorded_at=h.opens_at,
            frame=f,
            kind=kind,
            action=None if kind == "WATCH" else action,
        )


def test_original_unfilled_cutoff_expires_during_feed_failure(tmp_path):
    with shared(tmp_path) as (c, _, times, f):
        r = OptionRuntime(c, policy(tmp_path, scope_inputs="scope-runtime-inputs-v1"), create=True)
        enable(r)
        send(r, DegenFrame(scope=f.scope))
        asyncio.run(step(r))
        times[0] = f.scope.frame.session.entry_cutoff_at
        Path(r.policy.feed_file).unlink()
        asyncio.run(step(r))
        with c.engine.journal.read() as db:
            row = db.execute(
                "SELECT active_lock,record_json FROM execution_option_scope_watches"
            ).fetchone()
            assert row[0] is None
            assert json.loads(row[1])["status"] == "EXPIRED_UNFILLED"
            assert c.engine._control(db)["halted"]
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 0


def test_scope_management_wait_does_not_delay_nested_quote_stop(tmp_path, monkeypatch):
    from test_option_scope_position import enter, fake_model, management_frame

    from app.options import position_judgment
    from app.options.position_reasoning import PositionReasoningPolicy

    pp = PositionReasoningPolicy(max_lease_seconds=5, scope_management="scope-fixed-position-v1")
    with ai_owner(tmp_path, monkeypatch, position_policy=pp) as (c, venue, times, f, _):
        fixture_refresh = c.scope_refresh
        r = OptionRuntime(c, policy(tmp_path, scope_inputs="scope-runtime-inputs-v1"), create=True)
        enable(r)
        c.scope_refresh = fixture_refresh
        _, current = enter(c, venue, times, f)
        c.scope_refresh = r.scope.fresh
        fake_model(monkeypatch, "MAINTAIN")
        original = position_judgment.run_position_process

        async def exercise():
            started, release = asyncio.Event(), asyncio.Event()

            async def wait(*args):
                started.set()
                await release.wait()
                return await original(*args)

            monkeypatch.setattr(position_judgment, "run_position_process", wait)
            send(r, current, kind="CYCLE")
            await r.tick()
            await asyncio.wait_for(started.wait(), 15)
            times[0] += timedelta(seconds=1)
            fresh = management_frame(f, times[0]).scope
            u = fresh.underlying.model_copy(update={"bid": Decimal(1), "ask": Decimal("1.01")})
            send(r, DegenFrame(scope=fresh.model_copy(update={"underlying": u})))
            await r.tick()
            assert ledger(c.engine).position.exit_reason == "UNDERLYING_INVALIDATION"
            with c.engine.journal.read() as db:
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM execution_orders WHERE json_extract(intent_json,'$.side')='SELL'"
                    ).fetchone()[0]
                    == 1
                )
            release.set()
            await r.task
            with c.engine.journal.read() as db:
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NOT NULL"
                    ).fetchone()[0]
                    == 2
                )

        asyncio.run(exercise())


def test_interruption_after_native_watch_commit_is_never_reapplied(tmp_path, monkeypatch):
    from app.options import scope_runtime

    with owner(tmp_path) as (r, req, times, _):
        source = req.watch_actions[0]
        event = req.tape.events[0]
        times[0] = event.recorded_at
        send(
            r,
            event.frame,
            kind="WATCH",
            action=ScopeRuntimeAction(
                key=source.key, kind=source.kind, play_key=source.play_key, choice=source.choice
            ),
        )
        perform = scope_runtime._perform

        def interrupted(*args):
            perform(*args)
            raise RuntimeError("fixture process interruption after native commit")

        monkeypatch.setattr(scope_runtime, "_perform", interrupted)
        with pytest.raises(RuntimeError, match="fixture process interruption"):
            asyncio.run(step(r))
        assert rows(r)[0]["status"] == "PENDING"
        with r.c.engine.journal.read() as db:
            original = [
                tuple(row)
                for row in db.execute("SELECT * FROM execution_option_scope_watch_actions")
            ]
            assert len(original) == 1
        r.c.engine._option_runtime = None
        reopened = OptionRuntime(r.c, r.policy)
        enable(reopened)
        asyncio.run(step(reopened))
        assert rows(reopened)[0]["status"] == "INTERRUPTED"
        with r.c.engine.journal.read() as db:
            assert [
                tuple(row)
                for row in db.execute("SELECT * FROM execution_option_scope_watch_actions")
            ] == original
