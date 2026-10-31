"""Continuous mixed delivery, independent native protection and explicit boundaries."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from test_degen_options import AT
from test_mixed_entry import owner, scope_owner
from test_mixed_native_owner import changed, intent_for
from test_mixed_selection import quote, stock_frame
from test_option_position_coordination import management_frame
from test_option_runtime import enable, policy, step

from app.execution.economics import UsageEvidence
from app.mixed.runtime import stored_inputs
from app.mixed.sources import StockCycleInput
from app.options import position_judgment as j
from app.options.coordinator import DegenFrame
from app.options.runtime import OptionRuntime, read_packet
from app.options.runtime_models import MixedRuntimePacket, RuntimePacket, ScopeRuntimePacket


def runtime(c, path, *, scope=False):
    r = OptionRuntime(
        c,
        policy(
            path,
            mixed_inputs="mixed-runtime-inputs-v1",
            **({"scope_inputs": "scope-runtime-inputs-v1"} if scope else {}),
        ),
        create=True,
    )
    enable(r)
    return r


def send(r, frame, *, kind="MARKET", sequence=None, at=None, action=None):
    with r.c.engine.journal.read() as db:
        prior = db.execute("SELECT feed_sequence FROM execution_option_runtime").fetchone()[0]
    packet = MixedRuntimePacket(
        population_id=r.c.engine.limits.population_id,
        sequence=sequence if sequence is not None else prior + 1,
        recorded_at=at or r.c.now(),
        frame=frame,
        kind=kind,
        action=action,
    )
    path = Path(r.policy.feed_file)
    path.write_text(packet.model_dump_json())
    path.chmod(0o600)
    return packet


@pytest.mark.parametrize("paid", [False, True])
def test_mixed_runtime_native_fill_and_fast_stock_exit(tmp_path, monkeypatch, paid):
    from test_mixed_selection import owner as deterministic_owner

    factory = owner(tmp_path, monkeypatch) if paid else deterministic_owner(tmp_path)
    with factory as values:
        c, v, times = values[:3]
        r = runtime(c, tmp_path)
        send(r, stock_frame(), kind="CYCLE")
        asyncio.run(step(r))
        with c.engine.journal.read() as db:
            out = json.loads(
                db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0]
            )
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="runtime-entry")
        send(
            r,
            DegenFrame(
                stocks=(StockCycleInput(quote=quote(times[0], bid=D(599), ask=D("599.01"))),)
            ),
        )
        asyncio.run(step(r))
        assert v.submit_count == 2
        with c.engine.journal.read() as db:
            assert (
                db.execute("SELECT count(*) FROM execution_option_opportunities").fetchone()[0] == 1
            )
            assert stored_inputs(db, times[0])["statuses"] == {"DELIVERED": 2}
        asyncio.run(step(r))
        assert v.submit_count == 2


@pytest.mark.parametrize(
    "damage", ["legacy", "gap", "identity", "future", "coverage", "unread_refresh"]
)
def test_mixed_runtime_delivery_cannot_bypass_enrollment(tmp_path, monkeypatch, damage):
    with owner(tmp_path, monkeypatch) as (c, v, _times, _):
        r = runtime(c, tmp_path)
        if damage == "legacy":
            path = Path(r.policy.feed_file)
            path.write_text(
                RuntimePacket(
                    population_id=c.engine.limits.population_id,
                    sequence=1,
                    recorded_at=AT,
                    frame=DegenFrame(),
                ).model_dump_json()
            )
            path.chmod(0o600)
        else:
            f = stock_frame()
            if damage == "identity":
                f = changed(
                    f,
                    stocks=(
                        StockCycleInput(
                            quote=changed(
                                quote(),
                                instrument=changed(quote().instrument, instrument_id="foreign"),
                            )
                        ),
                    ),
                )
            elif damage == "future":
                f = changed(f, stocks=(StockCycleInput(quote=quote(AT + timedelta(seconds=1))),))
            elif damage == "coverage":
                f = changed(f, stocks=())
            send(r, f, kind="CYCLE", sequence=2 if damage == "gap" else 1)
        if damage == "unread_refresh":
            with pytest.raises(RuntimeError, match="DELIVERED"):
                asyncio.run(c.stock_refresh(c.stock_policy.instruments[0]))
        else:
            asyncio.run(step(r))
        assert v.submit_count == 0


def test_mixed_envelope_does_not_relax_old_stock_boundaries():
    for cls, extra in ((RuntimePacket, {}), (ScopeRuntimePacket, {"kind": "CYCLE"})):
        with pytest.raises(ValueError, match="Stock inputs"):
            cls(population_id="p", sequence=1, recorded_at=AT, frame=stock_frame(), **extra)
    with pytest.raises(ValueError, match="Only mixed CYCLE"):
        from test_mixed_selection import source_fixture

        MixedRuntimePacket(
            population_id="p",
            sequence=1,
            recorded_at=AT,
            kind="MARKET",
            frame=stock_frame(item=source_fixture()[2]),
        )


def test_mixed_management_wait_keeps_independent_protection(tmp_path, monkeypatch):
    with owner(tmp_path, monkeypatch, management=True) as (c, v, times, _):
        r = runtime(c, tmp_path)

        async def exercise():
            send(r, stock_frame(), kind="CYCLE")
            await step(r)
            with c.engine.journal.read() as db:
                key = db.execute("SELECT client_id FROM execution_stock_orders").fetchone()[0]
            entry = intent_for(c.engine, key)
            times[0] += timedelta(seconds=1)
            v.fill_stock(
                entry, entry.quantity, quote(times[0]), times[0], fill_id="runtime-management-entry"
            )
            times[0] = AT + timedelta(minutes=5)
            started, finish = asyncio.Event(), asyncio.Event()

            async def delayed(request, _key):
                started.set()
                await finish.wait()
                return j.result_for(
                    request,
                    plan=j.maintain(request.packet),
                    count=100,
                    usage=UsageEvidence(
                        request_id="runtime-management",
                        model=request.configuration.costs.model,
                        input_tokens=100,
                        output_tokens=20,
                    ),
                )

            monkeypatch.setattr(j, "run_position_process", delayed)
            send(
                r,
                changed(management_frame(), stocks=(StockCycleInput(quote=quote(times[0])),)),
                kind="CYCLE",
            )
            await r.tick()
            await asyncio.wait_for(started.wait(), 10)
            times[0] += timedelta(seconds=1)
            send(
                r,
                DegenFrame(
                    stocks=(StockCycleInput(quote=quote(times[0], bid=D(599), ask=D("599.01"))),)
                ),
            )
            await r.tick()
            assert v.submit_count == 2
            finish.set()
            await r.task
            assert v.submit_count == 2

        asyncio.run(exercise())


@pytest.mark.parametrize("choice", ["STOCK", "OPTION", "SCOPE", "SCOPE_STALE"])
def test_joint_scope_runtime_retains_actual_native_choice(tmp_path, monkeypatch, choice):
    with scope_owner(tmp_path, monkeypatch, choice.split("_")[0]) as (c, v, times, f):
        fixture_refresh = c.scope_refresh
        r = runtime(c, tmp_path, scope=True)
        send(r, f, kind="CYCLE")
        assert isinstance(read_packet(r.policy.feed_file), MixedRuntimePacket)
        if choice == "SCOPE":
            original = c._model_run

            async def exercise():
                started, release = asyncio.Event(), asyncio.Event()

                async def model(*args, **kwargs):
                    started.set()
                    await release.wait()
                    return await original(*args, **kwargs)

                monkeypatch.setattr(c, "_model_run", model)
                await r.tick()
                await asyncio.wait_for(started.wait(), 15)
                times[0] += timedelta(seconds=1)
                fresh = await fixture_refresh(f.scope.play_key)
                send(r, DegenFrame(scope=fresh))
                await r.tick()
                release.set()
                await r.task

            asyncio.run(exercise())
        else:
            asyncio.run(step(r))
        count = 2 if choice == "SCOPE" else 1
        with c.engine.journal.read() as db:
            out = json.loads(
                db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0]
            )
            assert stored_inputs(db, times[0])["latest_sequence"] == count
            from app.options.scope_runtime import stored_inputs as scope_inputs

            assert scope_inputs(db, times[0])["statuses"] == {"OBSERVED": count}
        assert out["status"] == ("HOLD" if choice == "SCOPE_STALE" else "OPEN"), out
        assert v.submit_count == int(choice != "SCOPE_STALE")


def test_cli_mixed_restart_and_explicit_settlement_keep_one_balance(tmp_path):
    from test_degen_options import policies
    from test_mixed_native_owner import settings
    from test_mixed_selection import stock_policy

    from app.options.engine import OptionExecution
    from app.options.lifecycle import OptionReceipt
    from app.options.runtime_cli import _coordinator, initialize
    from app.options.runtime_models import RuntimeSettings
    from app.options.venue import DurableOptionVenue

    limits, execution = settings()
    execution = changed(
        execution,
        mixed_owner=changed(
            execution.mixed_owner, stocks=changed(execution.mixed_owner.stocks, share_step=".1")
        ),
    )
    setup, selection = policies()
    s = RuntimeSettings(
        limits=limits,
        execution=execution,
        setup=setup,
        selection=selection,
        stock_policy=stock_policy(),
        runtime=policy(tmp_path, mixed_inputs="mixed-runtime-inputs-v1"),
    )
    times = [AT]
    directory = tmp_path / "runtime"
    assert initialize(directory, s, clock=lambda: times[0])["mode"] == "MIXED_PAPER_FIXTURE"
    v = DurableOptionVenue(directory / "venue.db")
    with OptionExecution.open(directory / "options.db", limits, execution, v, now=AT) as e:
        c = _coordinator(e, s, False, lambda: times[0])
        r = OptionRuntime(c, s.runtime)
        enable(r)
        send(r, stock_frame(), kind="CYCLE")
        asyncio.run(step(r))
        with e.journal.read() as db:
            entry = intent_for(
                e, db.execute("SELECT client_id FROM execution_stock_orders").fetchone()[0]
            )
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="session-entry")
        times[0] += timedelta(seconds=1)
        q = quote(times[0], bid=D(602), ask=D("602.01"))
        send(r, DegenFrame(stocks=(StockCycleInput(quote=q),)))
        asyncio.run(step(r))
        with e.journal.read() as db:
            closing = intent_for(
                e,
                db.execute(
                    "SELECT client_id FROM execution_stock_orders WHERE json_extract(intent_json,'$.side')='SELL'"
                ).fetchone()[0],
            )
        times[0] += timedelta(seconds=1)
        v.fill_stock(
            closing,
            closing.quantity,
            changed(q, source_at=times[0], received_at=times[0]),
            times[0],
            fill_id="session-exit",
        )
        send(r, DegenFrame(stocks=(StockCycleInput(quote=quote(times[0])),)))
        asyncio.run(step(r))
        original_cash = e.mixed_account(now=times[0]).cash
        assert e.mixed_account(now=times[0]).settled_cash < original_cash
    times[0] = AT + timedelta(days=3)
    snapshot = v.snapshot(times[0])
    v.record_receipt(
        OptionReceipt(
            receipt_id="explicit-stock-settlement",
            sequence=3,
            kind="FUNDS_SETTLED",
            occurred_at=times[0],
            cash_change=snapshot.cash - snapshot.settled_cash,
        )
    )
    with OptionExecution.open(directory / "options.db", limits, execution, v, now=times[0]) as e:
        c = _coordinator(e, s, False, lambda: times[0])
        r = OptionRuntime(c, s.runtime)
        enable(r)
        send(r, DegenFrame())
        asyncio.run(step(r))
        account = e.mixed_account(now=times[0])
        assert account.cash == account.settled_cash == original_cash
        assert account.entry_halted  # Restart never silently resumes admission.
        assert v.submit_count == 2
        with e.journal.read() as db:
            assert stored_inputs(db, times[0])["latest_sequence"] == 4
    from app.options.runtime_cli import run

    stop = asyncio.Event()
    stop.set()
    result = asyncio.run(run(directory, stop, clock=lambda: times[0]))
    assert result["mode"] == "MIXED_PAPER_FIXTURE" and result["status"] == "STOPPED"


@pytest.mark.parametrize("bad", [False, True])
def test_fast_stock_quote_retirement_survives_rebound(tmp_path, monkeypatch, bad):
    import test_mixed_entry as fixture
    from test_mixed_selection import source_fixture

    from app.mixed.sources import geometry

    source, swing, item, _ = source_fixture()
    stock_policy = fixture.stock_policy
    monkeypatch.setattr(fixture, "stock_policy", lambda: stock_policy(swing=swing))
    with fixture.owner(tmp_path, monkeypatch, mode="HOLD") as (c, v, times, _):
        r = runtime(c, tmp_path)
        send(r, stock_frame(item=item), kind="CYCLE")
        asyncio.run(step(r))
        reference, stop, _ = geometry(source, swing.families[0], swing)
        times[0] += timedelta(seconds=1)
        target = 2 * reference - stop
        q = quote(times[0], bid=target, ask=target + D(".01"))
        if bad:
            q = changed(q, entitlement="DELAYED")
        send(r, DegenFrame(stocks=(StockCycleInput(quote=q),)))
        asyncio.run(step(r))
        times[0] += timedelta(seconds=1)
        send(r, DegenFrame(stocks=(StockCycleInput(quote=quote(times[0])),)))
        asyncio.run(step(r))
        with c.engine.journal.read() as db:
            terminal = db.execute(
                "SELECT evidence_json FROM execution_mixed_stock_terminals"
            ).fetchall()
            assert bool(terminal) != bad
            if terminal:
                assert json.loads(terminal[0][0])["reason"] == "TARGET_CONSUMED"
        assert v.submit_count == 0


@pytest.mark.parametrize("damage", ["hash", "clock", "prefix"])
def test_stored_mixed_delivery_rejects_changed_evidence(tmp_path, monkeypatch, damage):
    with owner(tmp_path, monkeypatch, mode="HOLD") as (c, v, times, _):
        r = runtime(c, tmp_path)
        send(r, DegenFrame(stocks=(StockCycleInput(quote=quote()),)))
        asyncio.run(step(r))
        with c.engine.journal.write() as db:
            if damage == "hash":
                db.execute("UPDATE execution_mixed_runtime_inputs SET packet_hash='changed'")
            elif damage == "clock":
                db.execute(
                    "UPDATE execution_mixed_runtime_inputs SET accepted_at=?",
                    ((AT - timedelta(seconds=1)).isoformat(),),
                )
            else:
                db.execute("UPDATE execution_option_runtime SET feed_sequence=2")
        with c.engine.journal.read() as db, pytest.raises(ValueError, match="changed"):
            stored_inputs(db, times[0])
        assert v.submit_count == 0


def test_interrupted_mixed_delivery_never_replays_or_refreshes(tmp_path, monkeypatch):
    with owner(tmp_path, monkeypatch, mode="HOLD") as (c, v, times, _):
        r = runtime(c, tmp_path)
        packet = send(r, DegenFrame(stocks=(StockCycleInput(quote=quote()),)))
        r.mixed.accept(packet, times[0])  # Process ends before native supervision completes.
        c.engine._option_runtime = None
        reopened = OptionRuntime(c, r.policy)
        enable(reopened)
        with c.engine.journal.read() as db:
            assert stored_inputs(db, times[0])["statuses"] == {"INTERRUPTED": 1}
            assert c.engine._control(db)["halted"]
        asyncio.run(step(reopened))
        with pytest.raises(RuntimeError, match="DELIVERED"):
            asyncio.run(c.stock_refresh(c.stock_policy.instruments[0]))
        with c.engine.journal.read() as db:
            assert stored_inputs(db, times[0])["statuses"] == {"INTERRUPTED": 1}
            assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 0
        assert v.submit_count == 0


def test_stock_refresh_waits_for_completed_protection_tick(tmp_path, monkeypatch):
    with owner(tmp_path, monkeypatch, mode="HOLD") as (c, v, _times, _):
        r = runtime(c, tmp_path)
        send(r, DegenFrame(stocks=(StockCycleInput(quote=quote()),)))
        supervise = c.supervise

        async def exercise():
            entered, finish = asyncio.Event(), asyncio.Event()

            async def suspended(*args, **kwargs):
                entered.set()
                await finish.wait()
                return await supervise(*args, **kwargs)

            monkeypatch.setattr(c, "supervise", suspended)
            tick = asyncio.create_task(r.tick())
            await entered.wait()
            refresh = asyncio.create_task(c.stock_refresh(c.stock_policy.instruments[0]))
            await asyncio.sleep(0)
            assert not refresh.done()
            finish.set()
            await tick
            assert await refresh == quote()
            Path(r.policy.feed_file).unlink()
            await r.tick()
            with pytest.raises(RuntimeError, match="RECEIPT_NOT_READY"):
                await c.stock_refresh(c.stock_policy.instruments[0])

        asyncio.run(exercise())
        assert v.submit_count == 0


def test_scope_protection_accepts_nested_index_beside_two_common_quotes(tmp_path, monkeypatch):
    with scope_owner(tmp_path, monkeypatch, "STOCK") as (c, v, times, f):
        r = runtime(c, tmp_path, scope=True)
        u = f.underlyings[0]
        send(r, DegenFrame(scope=f.scope, underlyings=(u, changed(u, symbol="QQQ"))))
        asyncio.run(step(r))
        with c.engine.journal.read() as db:
            assert stored_inputs(db, times[0])["statuses"] == {"DELIVERED": 1}
            assert not c.engine._control(db)["halted"]
        assert v.submit_count == 0
