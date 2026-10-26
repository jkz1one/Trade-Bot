"""Prepared native sources must not interrupt intervening protection-only polls."""

from datetime import timedelta

import pytest
from test_connected_check import configuration
from test_robinhood_read_mapping import AT, envelope, equity, history, option
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_binding import original
from test_swing_delivery import fixture

from app.mixed.continuous_feed import FeedPolicy, normalize, planned
from app.mixed.swing_binding import bind_sources, policy_from_settings
from app.options.read_capture import CaptureResult, policy_digest
from app.options.runtime import read_packet
from app.options.runtime_models import RuntimeSettings
from app.robinhood.schedule import XNYSCalendar


def prepared(tmp_path, mode="batch"):
    _, _, binding, _, evidence, now = fixture()
    snapshot, _, _ = original()
    settings, feed = configuration(tmp_path)
    if mode == "single":
        value = binding.option_policy.model_dump()
        value.update(family_batch=None, daily_base=None, higher_levels=None)
        value["ma_pullback"]["periods"] = (8,)
        from app.options.swing import SwingPolicy

        binding = binding.model_copy(
            update={
                "option_policy": SwingPolicy.model_validate(value),
                "candidates": binding.candidates[:1],
            }
        )
    elif mode == "stock_only":
        binding = binding.model_copy(update={"option_policy": None})
        evidence = evidence.model_copy(update={"options": ()})
    elif mode == "option_only":
        binding = binding.model_copy(update={"stock_policy": None})
        evidence = evidence.model_copy(update={"stocks": ()})
    stock = binding.stocks[0].model_copy(update={"provider": "robinhood"})
    candidates = tuple(i.model_copy(update={"provider": "robinhood"}) for i in binding.candidates)
    settings = RuntimeSettings.model_validate(
        settings.model_dump()
        | {
            "setup": settings.setup.model_dump() | {"symbols": (stock.symbol,)},
            "stock_policy": settings.stock_policy.model_dump()
            | {
                "instruments": (stock,),
                "swing": binding.stock_policy,
                "family_priority": ("SWING", "DEGEN"),
            },
            "swing_policy": binding.option_policy,
        }
    )
    feed = FeedPolicy.model_validate(
        feed.model_dump()
        | {
            "stocks": (stock,),
            "candidates": candidates,
        }
    )
    bound = bind_sources(
        snapshot, policy_from_settings(settings, candidates), created_at=snapshot.captured_at
    )
    assert bound.status == "PREPARED", bound.blockers
    return settings, feed, bound, evidence, now


def capture_for(feed, schemas, now, *, cycle=True, missing_stock=False):
    window = XNYSCalendar().current_window(now)
    plan, catalog = planned(feed, (), now, window, cycle=cycle)
    _, raw_history = history()
    row = raw_history["structuredContent"]["data"]["results"][0]
    from datetime import datetime

    shift = window.opens_at - AT
    bars = [
        {**bar, "begins_at": (datetime.fromisoformat(bar["begins_at"]) + shift).isoformat()}
        for bar in row["bars"]
    ]
    observations = []
    for call in plan.calls:
        if call.tool == "get_equity_historicals":
            raw = envelope([row | {"bars": bars}])
        elif call.tool == "get_equity_quotes":
            q = equity()
            for field in ("venue_bid_time", "venue_ask_time", "venue_last_trade_time"):
                q[field] = now.isoformat()
            raw = envelope([] if missing_stock else [{"quote": q}])
        else:
            raw = envelope(
                [
                    {"quote": option() | {"instrument_id": i, "updated_at": now.isoformat()}}
                    for i in call.arguments["instrument_ids"]
                ]
            )
        observations.append({"label": call.label, "tool": call.tool, "completed": True, "raw": raw})
    captured = CaptureResult(
        request_id="a" * 32,
        policy_sha256=policy_digest(feed.capture),
        operation="CAPTURE",
        started_at=now,
        collected_at=now + timedelta(seconds=1),
        elapsed_seconds=1,
        status="COMPLETE",
        schemas=schemas,
        plan=plan,
        observations=observations,
    )
    return captured, catalog


def normalized(feed, schemas, capture, catalog, settings, bound, evidence, sequence, **kwargs):
    return normalize(
        feed,
        schemas,
        capture,
        catalog,
        (),
        sequence=sequence,
        now=capture.collected_at,
        source_settings=settings,
        swing_sources=bound,
        swing_evidence=evidence,
        **kwargs,
    )


@pytest.mark.parametrize("mode", ["batch", "single", "stock_only", "option_only"])
def test_native_prepared_cycle_then_quote_only_poll_then_next_cycle(tmp_path, schemas, mode):
    settings, feed, bound, evidence, now = prepared(tmp_path, mode)
    original_bytes = bound.model_dump_json()
    for sequence, cycle in enumerate((True, False, True), 1):
        capture, catalog = capture_for(feed, schemas, now, cycle=cycle)
        packet = normalized(feed, schemas, capture, catalog, settings, bound, evidence, sequence)
        assert packet.kind == ("CYCLE" if cycle else "MARKET")
        assert len(packet.frame.quotes) == len(feed.candidates) and len(packet.frame.stocks) == 1
        if cycle:
            if bound.batches:
                assert packet.frame.swing_batches[0].seed == bound.batches[0]
                assert packet.frame.swing_batches[0].metadata[0].entitlement == "UNKNOWN"
            if bound.seeds:
                assert packet.frame.swing[0].seed == bound.seeds[0]
                assert packet.frame.swing[0].metadata.entitlement == "UNKNOWN"
            if bound.stocks:
                assert packet.frame.stocks[0].swing == bound.stocks[0]
        else:
            assert not packet.frame.swing_batches and not packet.frame.swing
            assert packet.frame.stocks[0].swing is None and packet.frame.stocks[0].catalyst is None
        path = tmp_path / "feed.json"
        path.write_text(packet.model_dump_json())
        path.chmod(0o600)
        assert read_packet(path) == packet
        assert bound.model_dump_json() == original_bytes
        now += timedelta(minutes=5) if not cycle else timedelta(seconds=10)


@pytest.mark.parametrize("damage", ["history", "missing_stock"])
def test_prepared_sources_do_not_prevent_market_delivery_when_a_peer_input_fails(
    tmp_path, schemas, damage
):
    settings, feed, bound, evidence, now = prepared(tmp_path)
    extras = {"history_issues": ("SWING_HISTORY_UNAVAILABLE",)} if damage == "history" else {}
    capture, catalog = capture_for(feed, schemas, now, missing_stock=damage == "missing_stock")
    packet = normalized(feed, schemas, capture, catalog, settings, bound, evidence, 1, **extras)
    assert packet.kind == "MARKET" and packet.coverage_issues
    assert len(packet.frame.quotes) == 2
    assert not packet.frame.swing and not packet.frame.swing_batches
    assert not packet.frame.histories and not packet.frame.inventories
    assert all(s.swing is None and s.catalyst is None for s in packet.frame.stocks)


def test_native_scope_enrollment_requires_explicit_feed_coverage(tmp_path, schemas):
    from test_option_runtime import policy
    from test_option_scope_arbitration import shared

    from app.options.read_capture import CapturePolicy

    with shared(tmp_path / "scope-owner", portfolio=True) as (c, _, _, _):
        settings = RuntimeSettings(
            limits=c.engine.limits,
            execution=c.engine.policy,
            setup=c.policy,
            selection=c.selection,
            scope_policy=c.scope_policy,
            stock_policy=c.stock_policy,
            runtime=policy(
                tmp_path,
                mixed_inputs="mixed-runtime-inputs-v1",
                scope_inputs="scope-runtime-inputs-v1",
            ),
        )
    value = settings.model_dump()
    value["limits"].update(
        provider="robinhood", option_source="robinhood-mcp", underlying_source="robinhood-mcp"
    )
    value["execution"]["mixed_owner"]["stocks"].update(
        provider="robinhood", quote_source="robinhood-mcp"
    )
    for i in value["stock_policy"]["instruments"]:
        i["provider"] = "robinhood"
    value["scope_policy"]["watch"]["context"]["structure"]["preflight"].update(
        provider="robinhood", quote_source="robinhood-mcp"
    )
    watch = value["scope_policy"]["watch"]
    watch["quality"]["context"] = watch["context"]
    watch["contract"]["quality"] = watch["quality"]
    settings = RuntimeSettings.model_validate(value)
    feed = FeedPolicy(
        population_id=settings.limits.population_id,
        stocks=settings.stock_policy.instruments,
        capture=CapturePolicy(oauth_file="/unused/offline", timeout_seconds=5.0),
    )
    now = AT + timedelta(minutes=30)
    capture, catalog = capture_for(feed, schemas, now)
    packet = normalized(feed, schemas, capture, catalog, settings, None, None, 1)
    assert packet.kind == "MARKET"
    assert packet.coverage_issues == ("SCOPE_CURRENT_INPUT_UNAVAILABLE",)
    assert len(packet.frame.stocks) == len(feed.stocks)
    assert packet.frame.stocks[0].quote.source_at == now


def test_collector_publishes_intervening_quote_poll_and_recovers_it_after_restart(
    tmp_path, schemas, monkeypatch
):
    import asyncio

    from app.mixed.continuous_feed import ContinuousFeed
    from app.mixed.swing_feed import SwingHistoryPolicy
    from app.options.engine import fingerprint

    settings, policy, bound, evidence, now = prepared(tmp_path)
    policy = FeedPolicy.model_validate(
        policy.model_dump() | {"swing_history": SwingHistoryPolicy()}
    )
    directory = tmp_path / "collector"
    feed = ContinuousFeed(directory, policy, schemas, create=True)
    # Real normalized history is UNKNOWN and cannot prepare. Supply the separately
    # native-validated synthetic original at the loader boundary for this positive
    # delivery/recovery test. The raw mapper remains unchanged and UNKNOWN.
    monkeypatch.setattr(feed, "load_swing_sources", lambda *args, **kwargs: bound)
    try:
        for seq, at in enumerate((now, now + timedelta(seconds=10)), 1):

            async def reader(p, *, schemas, plan, at=at, seq=seq):
                capture, _ = capture_for(policy, schemas, at, cycle=seq == 1)
                assert plan == capture.plan
                return capture

            result = asyncio.run(
                feed.tick(
                    now=at,
                    window=XNYSCalendar().current_window(at),
                    reader=reader,
                    source_settings=settings,
                    swing_evidence=evidence,
                )
            )
            assert result["status"] == "DELIVERED", result
            packet = read_packet(directory / "feed.json")
            assert packet.sequence == seq and packet.kind == ("CYCLE" if seq == 1 else "MARKET")
            assert packet.frame.quotes[0].source_at == at
        retained = fingerprint(packet)
        assert (
            feed.db.execute("SELECT count(*) FROM attempts WHERE status='DELIVERED'").fetchone()[0]
            == 2
        )
    finally:
        feed.close()
    reopened = ContinuousFeed(directory, policy, schemas)
    try:
        assert fingerprint(read_packet(directory / "feed.json")) == retained
    finally:
        reopened.close()


@pytest.mark.parametrize("failure", ["missing", "failed", "schema", "coverage", "close"])
def test_intraday_failure_keeps_completed_books_and_original_failed_receipt(
    tmp_path, schemas, failure
):
    import asyncio

    from test_swing_delivery import captured_market

    from app.mixed.continuous_feed import ContinuousFeed

    policy, capture, _, held = captured_market(schemas)
    data = capture.model_dump()
    observation = data["observations"][-1]
    assert observation["tool"] == "get_equity_historicals"
    if failure in {"missing", "failed", "close"}:
        data.update(status="FAILED", error_class="ValueError")
        if failure == "missing":
            data["observations"].pop()
        elif failure == "failed":
            observation.update(completed=False, raw={"isError": True})
    elif failure == "schema":
        observation["raw"] = {"isError": False, "structuredContent": {"data": "invalid"}}
    else:
        observation["raw"]["structuredContent"]["data"]["results"][0]["bars"][0]["volume"] = -1
    captured = CaptureResult.model_validate(data)

    async def reader(p, *, schemas, plan):
        assert plan == captured.plan
        return captured

    collector = ContinuousFeed(tmp_path / "collector", policy, schemas, create=True)
    try:
        result = asyncio.run(
            collector.tick(
                now=captured.started_at,
                held=(held,),
                window=XNYSCalendar().current_window(captured.started_at),
                reader=reader,
            )
        )
        assert result["status"] == "DELIVERED", result
        packet = read_packet(collector.directory / "feed.json")
        assert packet.kind == "MARKET" and len(packet.frame.stocks) == 2
        assert packet.frame.held_quotes[0].instrument == held
        assert len(packet.frame.quotes) == 2
        assert packet.coverage_issues == (
            ("CAPTURE_INCOMPLETE",) if failure == "close" else ("INTRADAY_HISTORY_UNAVAILABLE",)
        )
        retained = collector.db.execute("SELECT raw_json FROM attempts").fetchone()[0]
        assert CaptureResult.model_validate_json(retained) == captured
    finally:
        collector.close()


def test_failed_required_quote_cannot_hide_behind_optional_intraday_history(tmp_path, schemas):
    from test_swing_delivery import captured_market

    policy, capture, catalog, held = captured_market(schemas)
    value = capture.model_dump()
    value.update(status="FAILED", error_class="ValueError", observations=value["observations"][:1])
    captured = CaptureResult.model_validate(value)
    with pytest.raises(ValueError, match="Original read receipt coverage changed"):
        normalize(
            policy, schemas, captured, catalog, (held,), sequence=1, now=captured.collected_at
        )
