"""Synthetic receipts through production Scope collection and ownership.

Explicit fixture SPXW/session terms are test inputs, never proposed host bindings.
"""

import asyncio
import copy
import json
from datetime import timedelta

import pytest
from test_option_runtime import enable, step
from test_option_scope import AT
from test_robinhood_read_mapping import envelope, equity, option
from test_robinhood_read_mapping import schemas as schemas
from test_scope_feed import setup

from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
from app.mixed.price_options_profile import proposal
from app.mixed.scope_feed import owner_state
from app.mixed.simulation_profile import configuration
from app.options.read_capture import CaptureResult, policy_digest
from app.options.runtime import read_packet
from app.options.runtime_cli import existing_runtime, initialize
from app.options.scope_read import calls
from app.robinhood.schedule import XNYSCalendar


def scope_reader(at, binding, *, exit_price=False, duration=1):
    started = at
    at = at + timedelta(seconds=duration - 1)
    _, cap, frame, _, _ = setup()

    async def capture(policy, *, schemas, plan, scope_input=False):
        rows = []
        for call in plan.calls:
            if call.tool == "get_equity_quotes":
                values = []
                for symbol in call.arguments["symbols"]:
                    q = equity(symbol) | {"bid_price": "101", "ask_price": "101.01"}
                    for key in ("venue_bid_time", "venue_ask_time", "venue_last_trade_time"):
                        q[key] = at.isoformat()
                    values.append({"quote": q})
            elif call.tool == "get_option_quotes":
                assert call.arguments["instrument_ids"] == [binding.instrument.instrument_id]
                values = [
                    {
                        "quote": option()
                        | {
                            "instrument_id": binding.instrument.instrument_id,
                            "updated_at": at.isoformat(),
                            "bid_price": ".40" if exit_price else "1.00",
                            "ask_price": ".40" if exit_price else "1.05",
                            "ask_size": 1,
                            "bid_size": 1,
                            "delta": ".45",
                            "volume": 100,
                            "open_interest": 1000,
                        }
                    }
                ]
            else:
                assert call.label == "history"
                values = [
                    {
                        "symbol": h.symbol,
                        "interval": "5minute",
                        "bounds": "regular",
                        "bars": [
                            {
                                "begins_at": b.begins_at.isoformat(),
                                "open_price": str(b.open),
                                "high_price": str(b.high),
                                "low_price": str(b.low),
                                "close_price": str(b.close),
                                "volume": b.volume,
                                "interpolated": False,
                                "session": "reg",
                            }
                            for b in h.bars
                        ],
                    }
                    for h in frame.histories
                ]
            rows.append(
                dict(
                    label=call.label,
                    tool=call.tool,
                    completed=True,
                    received_at=(at + timedelta(seconds=1)).isoformat(),
                    raw=envelope(values),
                )
            )
        originals = copy.deepcopy(cap.observations)
        for row, (_, arguments) in zip(
            originals, calls(originals[1]["arguments"]["instrument_ids"][0], started), strict=True
        ):
            row.update(
                arguments=arguments,
                attempted_at=at.isoformat(),
                received_at=(at + timedelta(seconds=1)).isoformat(),
            )
        originals[1]["raw"]["structuredContent"]["data"]["quotes"][0].update(
            venue_timestamp=at.isoformat(), updated_at=at.isoformat()
        )
        return CaptureResult(
            request_id="a" * 32,
            policy_sha256=policy_digest(policy),
            operation="CAPTURE",
            started_at=started,
            collected_at=at + timedelta(seconds=1),
            elapsed_seconds=duration,
            status="COMPLETE",
            plan=plan,
            schemas=schemas,
            observations=rows,
            scope_requested=scope_input,
            scope_observations=originals if scope_input else [],
        )

    return capture


@pytest.mark.parametrize("timing", ["fresh", "late", "demand", "demand_stale", "demand_quota", "demand_expired", "demand_failed", "demand_slow", "demand_timeout"])
def test_production_scope_feed_lifecycle(tmp_path, schemas, monkeypatch, timing):
    settings, base = configuration()
    settings = proposal(settings)[0]
    binding, _, _, _, _ = setup()
    binding = binding.model_copy(
        update={
            "session": binding.session.model_copy(
                update={
                    "source": settings.scope_policy.watch.context.structure.preflight.session_source
                }
            ),
            **({'post_cost_refresh': 'bounded-paid-refresh-v1'} if timing.startswith('demand') else {}),
        }
    )
    policy = FeedPolicy.model_validate(
        base.model_dump()
        | {
            "observed_simulation": "robinhood-observed-v1",
            "scope_binding": binding,
            "swing_history": None,
        }
    )
    key = tmp_path / "synthetic-key"
    key.write_text("offline-test-never-transmitted")
    key.chmod(0o600)
    owner, directory = tmp_path / "owner", tmp_path / "collector"
    settings = type(settings).model_validate(
        settings.model_dump()
        | {
            "key_file": str(key),
            "runtime": settings.runtime.model_dump() | {"feed_file": str(directory / "feed.json")},
        }
    )
    times = [AT]
    requests = []
    signals = {}

    async def model(request, _secret, *, broad):
        from app.execution.economics import UsageEvidence
        from app.options.engine import fingerprint
        from app.options.entry_judgment import result_for
        from app.options.entry_reasoning import plan_class

        requests.append(request)
        signals["started"].set()
        await signals["release"].wait()
        identity = fingerprint(request.packet.scope.model_dump(mode="json"))
        plan = plan_class(request.packet.policy)(
            decision_id=request.packet.decision_id,
            packet_hash=fingerprint(request.packet),
            action="ENTER",
            scope=True,
            stock=False,
            candidate_id=identity,
            evidence_ids=(identity,),
            thesis="Synthetic fixed Scope selection",
            uncertainty="Offline fixture",
        )
        return result_for(
            request,
            plan=plan,
            count=100,
            usage=UsageEvidence(
                request_id="synthetic-scope",
                model=settings.execution.cost_policy.model,
                input_tokens=100,
                output_tokens=20,
            ),
        )

    async def unexpected(*args, **kwargs):
        raise AssertionError("Unexpected external model worker")

    monkeypatch.setattr("app.options.entry_judgment.run_entry_process", unexpected)
    monkeypatch.setattr("app.options.position_judgment.run_position_process", unexpected)
    initialize(owner, settings, clock=lambda: times[0])
    feed = ContinuousFeed(directory, policy, schemas, create=True)
    try:
        with existing_runtime(owner, clock=lambda: times[0]) as (runtime, _):
            enable(runtime)
            monkeypatch.setattr(runtime.c, "_model_run", model)

            async def collect(at, *, exit_price=False, duration=1):
                times[0] = at
                outcome = await feed.tick(
                    now=at,
                    reader=scope_reader(at, binding, exit_price=exit_price, duration=duration),
                    source_settings=settings,
                    window=XNYSCalendar().current_window(at),
                    scope_state=lambda b: owner_state(runtime.c.engine.journal, b),
                )
                if outcome["status"] == "RATE_LIMITED":
                    return None
                assert outcome["status"] == "DELIVERED", outcome
                times[0] += timedelta(seconds=duration)
                packet = read_packet(directory / "feed.json")
                from app.mixed.runtime import validate_packet

                validate_packet(runtime.c, packet)
                await runtime.tick()
                return packet

            async def enter():
                signals.update(started=asyncio.Event(), release=asyncio.Event())
                for n in range(18):
                    prior_requests = len(requests)
                    # A later source read in the original bounded capture leaves a
                    # following delivered observation inside the five-second approval.
                    packet = await collect(
                        # Warm-up is explicit sampled evidence. Twenty-second
                        # samples leave quota for the new read; the separate quota
                        # case proves saturation refuses it without changing limits.
                        AT + timedelta(seconds=(20 if timing.startswith('demand') else 10) * n),
                        duration=8 if n == 8 and timing == "fresh" else 1,
                    )
                    if packet is None:
                        continue
                    assert packet.frame.scope is not None, packet.coverage_issues
                    if prior_requests:
                        signals["release"].set()
                        if runtime.task:
                            await runtime.task
                        if timing == "late":
                            break
                    elif packet.kind == "CYCLE":
                        await asyncio.wait_for(signals["started"].wait(), 15)
                        if timing.startswith('demand'):
                            from app.mixed.scope_refresh import ConnectedScopeRefresh
                            stop = asyncio.Event()
                            refresh = ConnectedScopeRefresh(runtime, feed, stop)
                            runtime.c.scope_refresh = refresh.fresh
                            reads = []

                            async def demand_reader(p, **kwargs):
                                reads.append(times[0])
                                if timing == 'demand_timeout':
                                    # Exceed the real caller timeout while the independent
                                    # collector remains alive and retains its late evidence.
                                    await asyncio.sleep(6)
                                result = await scope_reader(times[0], binding,
                                    duration=6 if timing in {'demand_slow', 'demand_timeout'} else 1)(p, **kwargs)
                                if timing == 'demand_failed':
                                    result = CaptureResult.model_validate(result.model_dump() | {
                                        'status': 'FAILED', 'error_class': 'TimeoutError',
                                        'schemas': None, 'observations': [],
                                        'scope_observations': [], 'scope_error_class': 'TimeoutError'})
                                if timing == 'demand_stale':
                                    # Stocks/options advance, but the SPX venue clock does not.
                                    # A new provider updated_at/receipt cannot replace that clock.
                                    old = (packet.recorded_at - timedelta(seconds=1)).isoformat()
                                    result.scope_observations[1]['raw']['structuredContent']['data']['quotes'][0]['venue_timestamp'] = old
                                times[0] = result.collected_at
                                return result

                            async def protect():
                                while not stop.is_set():
                                    await runtime.tick()
                                    await asyncio.sleep(.05)

                            if timing == 'demand_quota':
                                # Existing persisted reads consume the frozen quota; no new
                                # provider read may occur to satisfy this paid response.
                                last = feed.db.execute('SELECT MAX(sequence) FROM attempts').fetchone()[0]
                                feed.db.execute('UPDATE attempts SET calls=? WHERE sequence=?',
                                                (policy.calls_per_minute, last))
                                feed.db.commit()
                            signals['release'].set()
                            # Let the model settle and queue the native request before starting
                            # the real collector loop. No direct injected scope_refresh result.
                            for _ in range(200):
                                if refresh.pending is not None or runtime.task.done():
                                    break
                                await asyncio.sleep(.01)
                            assert refresh.pending is not None
                            if timing == 'demand_expired':
                                times[0] = requests[0].packet.valid_until
                            collector = asyncio.create_task(feed.run(
                                stop, clock_source=lambda: times[0], held_source=lambda: (),
                                calendar=XNYSCalendar(), source_settings=settings,
                                scope_state=lambda b: owner_state(runtime.c.engine.journal, b),
                                scope_refresh=refresh, reader=demand_reader))
                            protector = asyncio.create_task(protect())
                            cycle_task = runtime.task
                            try:
                                await asyncio.wait_for(asyncio.shield(cycle_task), 10)
                            finally:
                                stop.set()
                                await asyncio.gather(collector, protector)
                            assert len(reads) == (0 if timing in {'demand_quota', 'demand_expired'} else 1)
                            row = feed.db.execute('SELECT * FROM scope_refresh_requests').fetchone()
                            if timing == 'demand_timeout':
                                assert row['status'] == 'CANCELLED'
                                assert json.loads(row['result_json'])['status'] == 'DELIVERED'
                            if reads:
                                assert reads[0] < packet.recorded_at + timedelta(seconds=policy.poll_seconds)
                                extra = feed.db.execute('SELECT * FROM attempts WHERE sequence=?',
                                                        (row['capture_sequence'],)).fetchone()
                                assert extra['calls'] == 6
                                if timing == 'demand_failed':
                                    assert extra['status'] == 'FAILED' and extra['packet_json'] is None
                                else:
                                    assert json.loads(extra['packet_json'])['kind'] == 'MARKET'
                            if timing != 'demand':
                                break
                    with runtime.c.engine.journal.read() as db:
                        actions = [
                            dict(r)
                            for r in db.execute(
                                "SELECT status,result_json FROM execution_option_scope_runtime_inputs"
                            )
                        ]
                    assert actions[-1]["status"] in ("RECORDED", "OBSERVED"), actions[-1]
                    if runtime.c.engine.venue.snapshot(times[0]).positions:
                        break
                with runtime.c.engine.journal.read() as db:
                    decisions = [
                        json.loads(r[0])
                        for r in db.execute(
                            "SELECT result_json FROM execution_option_opportunities"
                        )
                    ]
                assert len(requests) == 1, decisions
                if timing == "late" or timing.startswith('demand_'):
                    assert runtime.c.engine.venue.submit_count == 0
                    if timing == 'late':
                        assert decisions[-1]["reason"] == "ENTRY_MODEL_HOLD_OR_REJECTED"
                        assert decisions[-1]["entry_timely"] is False
                    else:
                        assert decisions[-1]['entry_timely'] is True
                        assert decisions[-1]['reason'] == {
                            'demand_stale': 'SCOPE_POST_COST_ADMISSION_REJECTED',
                            'demand_quota': 'SCOPE_PAID_REFRESH_RATE_LIMITED',
                            'demand_expired': 'SCOPE_PAID_REFRESH_EXPIRED',
                            'demand_failed': 'SCOPE_PAID_REFRESH_FAILED',
                            'demand_slow': 'SCOPE_PAID_REFRESH_DELIVERY_EXPIRED',
                            'demand_timeout': 'SCOPE_FRESH_EVIDENCE_TIMEOUT',
                        }[timing]
                        with runtime.c.engine.journal.read() as db:
                            assert not runtime.c.engine._control(db)['halted']
                    with runtime.c.engine.journal.read() as db:
                        assert (
                            db.execute(
                                "SELECT COUNT(*) FROM execution_model_calls WHERE cost IS NOT NULL"
                            ).fetchone()[0]
                            == 1
                        )
                    return None
                assert runtime.c.engine.venue.submit_count == 1, decisions
                saved = runtime.c.engine.venue.snapshot(times[0])
                assert len(saved.positions) == 1, decisions
                assert owner_state(runtime.c.engine.journal, binding)["status"] == "POSITION_OPEN"
                return saved

            saved = asyncio.run(enter())
            if timing == "late" or timing.startswith('demand_'):
                return

        # Reopen both native owner and collector; original state and call budget survive.
        feed.close()
        feed = ContinuousFeed(directory, policy, schemas)
        with existing_runtime(owner, clock=lambda: times[0]) as (runtime, _):
            assert runtime.c.engine.venue.snapshot(times[0]).positions == saved.positions
            assert runtime.c.engine.venue.snapshot(times[0]).cash == saved.cash
            enable(runtime)

            async def exit_play():
                start = times[0]
                for n in range(1, 10):
                    packet = await collect(start + timedelta(seconds=10 * n), exit_price=True)
                    if packet is not None and runtime.task:
                        await runtime.task
                    if not runtime.c.engine.venue.snapshot(times[0]).positions:
                        break
                final = runtime.c.engine.venue.snapshot(times[0])
                assert not final.positions
                with runtime.c.engine.journal.read() as db:
                    from test_paper_session_report import module as host_report

                    assert host_report.fill_count(db) == (2, "PORTFOLIO_ORDER_OBSERVATIONS")
                    assert (
                        db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 1
                    )
                await step(runtime)
                assert runtime.c.engine.venue.snapshot(times[0]) == final
                with runtime.c.engine.journal.read() as db:
                    assert (
                        db.execute("SELECT status FROM execution_option_runtime").fetchone()[0]
                        == "RUNNING"
                    )
                saved_report = host_report.report(tmp_path, AT.isoformat(), times[0].isoformat())
                assert saved_report["account_total_fills"] == 2
                assert (
                    saved_report["accepted_packet"]["sequence"]
                    == saved_report["current_runtime"][0]["feed_sequence"]
                )
                current = host_report.operation(saved_report, {"Status": "running"})
                assert current["state"] == "MISSING_INPUTS"
                assert current["reasons"] == ["OPTION_RUNTIME_INTERRUPTED"]
                return final

            final = asyncio.run(exit_play())
        from app.mixed.observer import MixedObserver

        result = MixedObserver(
            owner / "options.db", settings.limits.population_id, clock=lambda: times[0]
        ).report()
        assert result["fill_count"] == 2 and not result["positions"]
        assert str(final.cash) == result["cash"]
    finally:
        feed.close()
