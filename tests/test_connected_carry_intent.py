"""Explicit frozen carry dates, native calendars and immutable restart binding."""

import asyncio
from datetime import date, timedelta

import pytest
from test_continuous_strategy_delivery import capture_for, normalized, prepared
from test_mixed_stock_carry import carry_policy
from test_option_swing_carry import request
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_binding import connected, original
from test_swing_feed import PREOPEN, reader

from app.mixed.carry import SwingCarryIntent
from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy, carry_intent_for
from app.mixed.swing_binding import bind_sources, policy_from_settings
from app.mixed.swing_feed import SwingHistoryPolicy
from app.options.runtime_models import RuntimeSettings


def configured(tmp_path):
    settings, feed, _, evidence, now = prepared(tmp_path)
    value = settings.model_dump()
    value["execution"]["swing_carry"] = "bounded-swing-carry-v1"
    value["execution"]["mixed_owner"]["stock_carry"] = carry_policy()
    value["swing_policy"].update(holding_policy="BOUNDED_CARRY_V1", carry=request().carry)
    settings = RuntimeSettings.model_validate(value)
    intent = SwingCarryIntent(
        target_session=now.date(),
        stock_exit_session=date(2026, 10, 12),
        option_exit_session=date(2026, 10, 13),
    )
    feed = FeedPolicy.model_validate(
        feed.model_dump() | {"swing_history": SwingHistoryPolicy(), "carry_intents": (intent,)}
    )
    return settings, feed, evidence, now


def test_distinct_explicit_stock_and_option_dates_reach_native_batch_and_runtime(tmp_path, schemas):
    settings, feed, evidence, now = configured(tmp_path)
    snapshot, _, _ = original()
    intent = carry_intent_for(feed, snapshot.target_session)
    policy = policy_from_settings(settings, feed.candidates, intent)
    bound = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    assert bound.status == "PREPARED", bound.blockers
    assert bound.stocks[0].carry_exit_session == intent.stock_exit_session
    assert bound.batches[0].carry_exit_session == intent.option_exit_session
    capture, catalog = capture_for(feed, schemas, now)
    packet = normalized(feed, schemas, capture, catalog, settings, bound, evidence, 1)
    assert packet.kind == "CYCLE"
    assert packet.frame.stocks[0].swing == bound.stocks[0]
    assert packet.frame.swing_batches[0].seed == bound.batches[0]
    # The fixture's catalyst only covers today's close; scheduling does not extend it.
    assert packet.frame.swing_batches[0].catalyst.valid_through.date() == now.date()


@pytest.mark.parametrize(
    "damage", ["weekend", "stock_limit", "option_limit", "expiry", "wrong_target", "legacy"]
)
def test_invalid_carry_intent_is_blocked_without_altering_originals(tmp_path, damage):
    settings, feed, _, _ = configured(tmp_path)
    snapshot, _, _ = original()
    intent = feed.carry_intents[0]
    if damage == "weekend":
        intent = intent.model_copy(update={"stock_exit_session": date(2026, 10, 11)})
    elif damage == "stock_limit":
        intent = intent.model_copy(update={"stock_exit_session": date(2026, 10, 19)})
    elif damage == "option_limit":
        intent = intent.model_copy(update={"option_exit_session": date(2026, 10, 19)})
    elif damage == "expiry":
        value = settings.model_dump()
        value["swing_policy"]["carry"]["expiry_session_buffer"] = 5
        settings = RuntimeSettings.model_validate(value)
    elif damage == "wrong_target":
        intent = intent.model_copy(update={"target_session": date(2026, 10, 8)})
    p = policy_from_settings(settings, feed.candidates, intent)
    if damage == "legacy":
        p = p.model_copy(update={"carry_exit_session": date(2026, 10, 12)})
    before = snapshot.model_dump_json(), p.model_dump_json()
    result = bind_sources(snapshot, p, created_at=snapshot.captured_at)
    assert result.status == "BLOCKED" and result.blockers
    assert not result.stocks and not result.batches and not result.seeds
    assert before == (snapshot.model_dump_json(), p.model_dump_json())


@pytest.mark.parametrize("asset", ["stock", "option"])
def test_intent_cannot_enable_unenrolled_asset_carry(tmp_path, asset):
    settings, feed, _, _, now = prepared(tmp_path)
    intent = SwingCarryIntent.model_validate(
        {"target_session": now.date(), asset + "_exit_session": date(2026, 10, 12)}
    )
    with pytest.raises(ValueError, match="matching native asset enrollment"):
        policy_from_settings(settings, feed.candidates, intent)


def test_schedule_is_opt_in_unique_and_requires_history(tmp_path):
    settings, feed, _, _ = configured(tmp_path)
    intent = feed.carry_intents[0]
    for changes in ({"carry_intents": (intent, intent)}, {"swing_history": None}):
        with pytest.raises(ValueError, match="Unique carry sessions"):
            FeedPolicy.model_validate(feed.model_dump() | changes)
    assert carry_intent_for(feed, date(2026, 10, 12)) is None
    legacy = FeedPolicy.model_validate(feed.model_dump() | {"carry_intents": ()})
    assert "carry_intents" not in legacy.model_dump()
    p = policy_from_settings(settings, feed.candidates)
    assert "carry_intent" not in p.model_dump() and "stock_carry" not in p.model_dump()


def test_unknown_history_stays_blocked_with_original_intent_across_restart(tmp_path, schemas):
    settings, feed = connected(tmp_path)
    value = settings.model_dump()
    value["execution"]["mixed_owner"]["stock_carry"] = carry_policy()
    settings = RuntimeSettings.model_validate(value)
    intent = SwingCarryIntent(
        target_session=PREOPEN.date(), stock_exit_session=PREOPEN.date() + timedelta(days=1)
    )
    feed = FeedPolicy.model_validate(feed.model_dump() | {"carry_intents": (intent,)})
    directory = tmp_path / "feed"
    collector = ContinuousFeed(directory, feed, schemas, create=True)
    try:
        asyncio.run(collector.tick(now=PREOPEN, reader=reader(PREOPEN, [])))
        first = collector.bind_swing_sources(settings, now=PREOPEN + timedelta(seconds=2))
        assert first["status"] == "BLOCKED"
        before = tuple(collector.db.execute("SELECT * FROM swing_source_bindings").fetchone())
    finally:
        collector.close()
    collector = ContinuousFeed(directory, feed, schemas)
    try:
        assert collector.bind_swing_sources(settings, now=PREOPEN + timedelta(hours=2)) == first
        assert (
            tuple(collector.db.execute("SELECT * FROM swing_source_bindings").fetchone()) == before
        )
    finally:
        collector.close()
    changed = FeedPolicy.model_validate(
        feed.model_dump()
        | {
            "carry_intents": (
                intent.model_copy(
                    update={"stock_exit_session": intent.stock_exit_session + timedelta(days=1)}
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="Frozen feed configuration changed"):
        ContinuousFeed(directory, changed, schemas)


def test_connection_check_rejects_unenrolled_carry_before_opening_state(tmp_path, schemas):
    from app.mixed.connected_check import connection_report

    settings, feed = connected(tmp_path)
    intent = SwingCarryIntent(
        target_session=PREOPEN.date(), stock_exit_session=PREOPEN.date() + timedelta(days=1)
    )
    feed = FeedPolicy.model_validate(feed.model_dump() | {"carry_intents": (intent,)})
    report = connection_report(
        settings,
        feed,
        schemas,
        journal=tmp_path / "owner/options.db",
        directory=tmp_path / "collector",
        now=PREOPEN,
    )
    assert "SWING_CARRY_INTENT_ENROLLMENT_MISMATCH" in report["wiring_errors"]
    assert not report["collector_can_start"]
    assert not (tmp_path / "collector").exists()


def test_option_only_schedule_does_not_put_stocks_into_carry(tmp_path):
    settings, feed, _, _ = configured(tmp_path)
    snapshot, _, _ = original()
    intent = feed.carry_intents[0].model_copy(update={"stock_exit_session": None})
    bound = bind_sources(
        snapshot,
        policy_from_settings(settings, feed.candidates, intent),
        created_at=snapshot.captured_at,
    )
    assert bound.status == "PREPARED", bound.blockers
    assert bound.stocks[0].carry_exit_session is None
    assert bound.batches[0].carry_exit_session == intent.option_exit_session


def test_missing_intent_cannot_infer_option_exit_from_maximum_carry_policy(tmp_path):
    settings, feed, _, _ = configured(tmp_path)
    snapshot, _, _ = original()
    bound = bind_sources(
        snapshot, policy_from_settings(settings, feed.candidates), created_at=snapshot.captured_at
    )
    assert bound.status == "BLOCKED" and not bound.batches
