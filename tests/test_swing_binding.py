"""Native synthetic source binding and original captured-history rejection."""

import asyncio
import json
from datetime import timedelta

import pytest
from test_mixed_selection import source_fixture
from test_option_swing_batch import batch_frame
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_feed import PREOPEN, reader

from app.mixed.sources import StockDailyHistory, StockSwingPolicy
from app.mixed.swing_binding import SwingBindingPolicy, bind_sources
from app.mixed.swing_feed import SwingHistoryPolicy, SwingHistorySnapshot
from app.options.engine import fingerprint
from app.options.swing_batch import batch_seeds
from app.robinhood.schedule import XNYSCalendar


def original():
    frame, option_policy = batch_frame()
    batch = frame.swing_batches[0].seed
    stock, stock_policy, _, _ = source_fixture()
    daily = StockDailyHistory.model_validate(
        batch.history.model_dump() | {"version": "stock-swing-daily-v1"}
    )
    snapshot = SwingHistorySnapshot(
        target_session=batch.target_session,
        captured_at=batch.created_at,
        capture_hash="a" * 64,
        daily=(daily,),
        hourly=(batch.hourly_history,),
    )
    policy = SwingBindingPolicy(
        runtime_hash="b" * 64,
        stocks=(stock.instrument,),
        stock_policy=stock_policy,
        option_policy=option_policy,
        candidates=batch.instruments,
    )
    return snapshot, policy, batch


def test_shared_native_stock_and_complete_option_batch_keep_original_sources():
    snapshot, policy, original_batch = original()
    before = snapshot.model_dump_json(), policy.model_dump_json()
    result = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    assert result.status == "PREPARED", result.blockers
    assert not result.trading_ready and not result.live_enabled
    assert len(result.stocks) == len(result.batches) == 1 and not result.seeds
    assert result.stocks[0].history == snapshot.daily[0]
    assert result.batches[0] == original_batch
    children = batch_seeds(result.batches[0], policy.option_policy, XNYSCalendar(), ("SPY",))
    assert len(children) == 14 and len({fingerprint(seed) for seed in children}) == 14
    assert before == (snapshot.model_dump_json(), policy.model_dump_json())


def test_single_native_derived_seed_uses_original_targets():
    snapshot, policy, batch = original()
    p = policy.option_policy.model_dump()
    p.update(family_batch=None, daily_base=None, higher_levels=None)
    p["ma_pullback"]["periods"] = (8,)
    policy = SwingBindingPolicy.model_validate(
        {**policy.model_dump(), "option_policy": p, "candidates": (batch.instruments[0],)}
    )
    result = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    assert result.status == "PREPARED", result.blockers
    assert not result.batches and len(result.seeds) == 1
    seed = result.seeds[0]
    assert seed.ma_period == 8 and seed.target_geometry is not None
    assert seed.first_target == seed.target_geometry.targets[0]
    assert seed.created_at == snapshot.captured_at
    assert seed.history.bars == snapshot.daily[0].bars


@pytest.mark.parametrize(
    "damage",
    [
        "unknown",
        "late",
        "future_receipt",
        "duplicate_history",
        "metadata",
        "ambiguous",
        "coverage",
        "carry",
    ],
)
def test_binding_never_repairs_or_backdates_missing_evidence(damage):
    snapshot, policy, batch = original()
    created = snapshot.captured_at
    if damage == "unknown":
        snapshot = snapshot.model_copy(
            update={"daily": (snapshot.daily[0].model_copy(update={"entitlement": "UNKNOWN"}),)}
        )
    elif damage == "late":
        created = (
            XNYSCalendar()
            .calendar.session_open(snapshot.target_session.isoformat())
            .to_pydatetime()
        )
    elif damage == "future_receipt":
        snapshot = snapshot.model_copy(
            update={
                "daily": (
                    snapshot.daily[0].model_copy(
                        update={"received_at": created + timedelta(seconds=1)}
                    ),
                )
            }
        )
    elif damage == "duplicate_history":
        snapshot = snapshot.model_copy(update={"daily": snapshot.daily * 2})
    elif damage == "metadata":
        policy = policy.model_copy(
            update={
                "candidates": (
                    batch.instruments[0].model_copy(update={"metadata_complete": False}),
                    batch.instruments[1],
                )
            }
        )
    elif damage == "ambiguous":
        policy = policy.model_copy(
            update={
                "candidates": (
                    *policy.candidates,
                    policy.candidates[0].model_copy(update={"instrument_id": "another-call"}),
                )
            }
        )
    elif damage == "coverage":
        p = policy.stock_policy.model_copy(update={"daily_lookback": 60})
        policy = policy.model_copy(update={"stock_policy": p})
    elif damage == "carry":
        policy = policy.model_copy(
            update={"carry_exit_session": snapshot.target_session + timedelta(days=4)}
        )
    before = snapshot.model_dump_json(), policy.model_dump_json()
    result = bind_sources(snapshot, policy, created_at=created)
    assert result.status == "BLOCKED" and result.blockers
    assert not result.stocks and not result.seeds and not result.batches
    assert before == (snapshot.model_dump_json(), policy.model_dump_json())


def test_unused_hourly_entitlement_does_not_block_daily_only_stock_source():
    snapshot, policy, _ = original()
    p = policy.stock_policy.model_copy(update={"families": ("SWING_DAILY_BREAKOUT",)})
    policy = policy.model_copy(update={"stock_policy": p, "option_policy": None, "candidates": ()})
    snapshot = snapshot.model_copy(
        update={"hourly": (snapshot.hourly[0].model_copy(update={"entitlement": "UNKNOWN"}),)}
    )
    bound = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    assert bound.status == "PREPARED" and bound.stocks[0].hourly_history is None


def connected(tmp_path):
    from test_connected_check import configuration

    from app.mixed.continuous_feed import FeedPolicy
    from app.options.runtime_models import RuntimeSettings

    settings, feed = configuration(tmp_path)
    value = settings.model_dump()
    value["stock_policy"]["family_priority"] = ("SWING", "DEGEN")
    value["stock_policy"]["swing"] = StockSwingPolicy(
        families=("SWING_DAILY_BASE",),
        history_source="robinhood-mcp",
        daily_lookback=56,
        hourly_source="robinhood-mcp",
        hourly_lookback=54,
        catalyst_source="unavailable-events",
        catalyst_max_age_seconds=30,
        maximum_chase_fraction=".01",
        stop_buffer_fraction=".001",
    )
    return RuntimeSettings.model_validate(value), FeedPolicy.model_validate(
        {
            **feed.model_dump(),
            "candidates": (),
            "swing_history": SwingHistoryPolicy(),
        }
    )


def test_actual_normalized_unknowns_stay_blocked_across_restart(tmp_path, schemas):
    from app.mixed.continuous_feed import ContinuousFeed

    settings, policy = connected(tmp_path)
    feed = ContinuousFeed(tmp_path / "feed", policy, schemas, create=True)
    try:
        assert (
            asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])))["status"] == "DELIVERED"
        )
        first = feed.bind_swing_sources(settings, now=PREOPEN + timedelta(seconds=2))
        assert first["status"] == "BLOCKED" and first["stock_sources"] == 0
        assert set(first["blockers"]) == {
            "SWING_HISTORY_ENTITLEMENT_REQUIRED:SPY",
            "SWING_HISTORY_ENTITLEMENT_REQUIRED:QQQ",
        }
        before = tuple(feed.db.execute("SELECT * FROM swing_source_bindings").fetchone())
    finally:
        feed.close()
    reopened = ContinuousFeed(tmp_path / "feed", policy, schemas)
    try:
        again = reopened.bind_swing_sources(settings, now=PREOPEN + timedelta(hours=4))
        assert again == first
        full = reopened.load_swing_sources(
            settings, PREOPEN.date(), now=PREOPEN + timedelta(hours=4)
        )
        assert full.status == "BLOCKED" and fingerprint(full) == first["binding_hash"]
        assert (
            tuple(reopened.db.execute("SELECT * FROM swing_source_bindings").fetchone()) == before
        )
        assert reopened.db.execute("SELECT count(*) FROM swing_source_bindings").fetchone()[0] == 1
    finally:
        reopened.close()


def test_rehashed_source_receipt_cannot_upgrade_unknowns(tmp_path, schemas):
    from app.mixed.continuous_feed import ContinuousFeed
    from app.mixed.swing_binding import BoundSwingSources

    settings, policy = connected(tmp_path)
    feed = ContinuousFeed(tmp_path / "feed", policy, schemas, create=True)
    try:
        asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])))
        feed.bind_swing_sources(settings, now=PREOPEN + timedelta(seconds=2))
        value = json.loads(
            feed.db.execute("SELECT payload_json FROM swing_source_bindings").fetchone()[0]
        )
        value.update(status="PREPARED", blockers=[])
        changed = BoundSwingSources.model_validate(value)
        feed.db.execute(
            "UPDATE swing_source_bindings SET payload_json=?,payload_hash=?",
            (changed.model_dump_json(), fingerprint(changed)),
        )
        feed.db.commit()
        with pytest.raises(ValueError, match="Original Swing binding changed"):
            feed.bind_swing_sources(settings, now=PREOPEN + timedelta(seconds=30))
    finally:
        feed.close()


def test_continuous_run_binds_after_capture_without_starting_another_reader(
    tmp_path, schemas, monkeypatch
):
    from app.mixed.continuous_feed import ContinuousFeed

    settings, policy = connected(tmp_path)
    feed = ContinuousFeed(tmp_path / "feed", policy, schemas, create=True)
    now, seen = [PREOPEN], []
    native_tick = feed.tick
    stop = asyncio.Event()

    async def offline_tick(**kwargs):
        result = await native_tick(**kwargs, reader=reader(now[0], seen))
        now[0] += timedelta(seconds=2)
        stop.set()
        return result

    monkeypatch.setattr(feed, "tick", offline_tick)
    try:
        asyncio.run(
            feed.run(
                stop,
                clock_source=lambda: now[0],
                held_source=lambda: (),
                calendar=XNYSCalendar(),
                source_settings=settings,
            )
        )
        assert len(seen) == 1
        bound = json.loads(
            feed.db.execute("SELECT payload_json FROM swing_source_bindings").fetchone()[0]
        )
        assert bound["status"] == "BLOCKED" and bound["created_at"] == now[0].isoformat().replace(
            "+00:00", "Z"
        )
    finally:
        feed.close()


def observed_original():
    snapshot, policy, _ = original()
    common = {"source": "robinhood-mcp", "entitlement": "UNKNOWN"}
    snapshot = snapshot.model_copy(update={
        "daily": tuple(h.model_copy(update=common) for h in snapshot.daily),
        "hourly": tuple(h.model_copy(update=common) for h in snapshot.hourly),
    })
    raw = policy.model_dump()
    raw["stock_policy"].update(history_source="robinhood-mcp", hourly_source="robinhood-mcp")
    raw["option_policy"]["history_source"] = "robinhood-mcp"
    for key in ("daily_base", "ma_pullback"):
        if raw["option_policy"].get(key):
            raw["option_policy"][key]["hourly_source"] = "robinhood-mcp"
    return snapshot, SwingBindingPolicy.model_validate(raw)


def test_explicit_observed_swing_keeps_original_hash_clocks_and_all_native_children():
    snapshot, policy = observed_original()
    assert bind_sources(snapshot, policy, created_at=snapshot.captured_at).status == "BLOCKED"
    policy = policy.model_copy(update={"observed_simulation": "robinhood-observed-v1"})
    bound = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    assert bound.status == "PREPARED", bound.blockers
    assert bound.history_hash == fingerprint(snapshot)
    assert snapshot.daily[0].simulation_basis is None
    children = batch_seeds(bound.batches[0], policy.option_policy, XNYSCalendar(), ("SPY",))
    assert len(children) == 14
    for h in (bound.stocks[0].history, *(c.history for c in children)):
        assert h.entitlement == "UNKNOWN" and h.simulation_basis == "ROBINHOOD_OBSERVED_V1"
        assert h.source_at == snapshot.daily[0].source_at
        assert h.received_at == snapshot.daily[0].received_at
    assert not bound.trading_ready


@pytest.mark.parametrize("damage", ["delayed", "incomplete", "interpolated"])
def test_observed_swing_does_not_repair_unusable_history(damage):
    snapshot, policy = observed_original()
    policy = policy.model_copy(update={"observed_simulation": "robinhood-observed-v1"})
    daily = snapshot.daily[0]
    if damage == "delayed":
        daily = daily.model_copy(update={"entitlement": "DELAYED"})
    elif damage == "incomplete":
        daily = daily.model_copy(update={"complete": False})
    else:
        daily = daily.model_copy(update={"bars": (*daily.bars[:-1], daily.bars[-1].model_copy(update={"interpolated": True}))})
    snapshot = snapshot.model_copy(update={"daily": (daily,)})
    assert bind_sources(snapshot, policy, created_at=snapshot.captured_at).status == "BLOCKED"
