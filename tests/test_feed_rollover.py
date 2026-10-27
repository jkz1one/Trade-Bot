"""Offline future-session append, exact originals, recovery and failure fencing."""

import asyncio
import json
import sqlite3
from datetime import date, timedelta

import pytest
from test_connected_runtime import digest, enrolled
from test_robinhood_read_mapping import AT, envelope, equity, instrument, option
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.execution.runtime import RuntimeAlreadyRunning, runtime_lease
from app.mixed import feed_rollover as rollover
from app.mixed.connected_runtime import check
from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
from app.options.engine import fingerprint
from app.options.models import OptionInstrument
from app.options.read_capture import CaptureResult, policy_digest
from app.options.runtime import read_packet

TARGET = date(2026, 10, 26)


def future(i=None, *, identity="future-contract"):
    i = i or instrument()
    shift = date(2026, 10, 30) - i.contract.expiration
    value = i.model_dump()
    value["instrument_id"] = identity
    value["contract"]["expiration"] += shift
    for key in ("last_trading_at", "expires_at", "settles_at"):
        value["contract"][key] += shift
    return OptionInstrument.model_validate(value)


def prepared(tmp_path, schemas):
    paths, settings, base = enrolled(tmp_path, schemas)
    proposed = FeedPolicy.model_validate(base.model_dump() | {"candidates": (future(),)})
    new_file = tmp_path / "next-policy.json"
    new_file.write_text(proposed.model_dump_json())
    new_file.chmod(0o600)
    return (*paths, new_file, TARGET), settings, base, proposed


def review(args, now=AT):
    return rollover.review(*args, clock_source=lambda: now)[0]


def apply(args, reviewed, now=AT):
    return rollover.apply(
        *args, expected_review=reviewed["review_sha256"], clock_source=lambda: now
    )


def captured(at, seen):
    async def read(p, *, schemas, plan):
        seen.append(plan)
        observations = []
        for call in plan.calls:
            if call.tool == "get_equity_quotes":
                values = []
                for symbol in call.arguments["symbols"]:
                    q = equity(symbol)
                    for k in ("venue_bid_time", "venue_ask_time", "venue_last_trade_time"):
                        q[k] = at.isoformat()
                    values.append({"quote": q})
            else:
                values = [
                    {"quote": option() | {"instrument_id": i, "updated_at": at.isoformat()}}
                    for i in call.arguments["instrument_ids"]
                ]
            observations.append(
                {"label": call.label, "tool": call.tool, "completed": True, "raw": envelope(values)}
            )
        return CaptureResult(
            request_id="c" * 32,
            operation="CAPTURE",
            policy_sha256=policy_digest(p),
            started_at=at,
            collected_at=at + timedelta(seconds=2),
            elapsed_seconds=2,
            status="COMPLETE",
            schemas=schemas,
            plan=plan,
            observations=observations,
        )

    return read


def stored(feed):
    return [tuple(r) for r in feed.db.execute("SELECT * FROM attempts ORDER BY sequence")]


def test_rollover_keeps_owner_attempts_budgets_and_exact_held_reads(tmp_path, schemas):
    args, _, base, proposed = prepared(tmp_path, schemas)
    owner, directory = args[:2]
    feed = ContinuousFeed(directory, base, schemas)
    try:
        assert asyncio.run(feed.tick(now=AT, reader=captured(AT, [])))["status"] == "DELIVERED"
        before_attempts = stored(feed)
        packet_before = (directory / "feed.json").read_bytes()
    finally:
        feed.close()
    owner_before = digest(owner)
    all_before = digest(tmp_path)
    reviewed = review(args, AT + timedelta(seconds=3))
    assert digest(tmp_path) == all_before and not reviewed["state_modified"]
    result = apply(args, reviewed, AT + timedelta(seconds=4))
    assert result["status"] == "SESSION_ROLLOVER_ENROLLED"
    assert not result["workers_started"] and not result["automatic_resume"]
    assert not result["trading_ready"] and not result["credentials_opened"]
    assert digest(owner) == owner_before
    feed = ContinuousFeed(directory, base, schemas)
    try:
        assert (
            stored(feed) == before_attempts
            and (directory / "feed.json").read_bytes() == packet_before
        )
        assert feed.policy_for(AT.date()) == base
        assert feed.policy_for(TARGET) == proposed
        assert feed.policy_for(TARGET + timedelta(days=1)) == base
        # Rate allowance cannot be reset by enrolling a new session.
        assert (
            asyncio.run(feed.tick(now=AT + timedelta(seconds=5), reader=captured(AT, [])))["status"]
            == "RATE_LIMITED"
        )
        later = AT + timedelta(days=3)
        seen = []
        assert (
            asyncio.run(feed.tick(now=later, held=base.candidates, reader=captured(later, seen)))[
                "sequence"
            ]
            == 2
        )
        assert seen[0].instrument_ids == tuple(
            sorted((instrument().instrument_id, future().instrument_id))
        )
        packet = read_packet(directory / "feed.json")
        books = (*packet.frame.quotes, *packet.frame.held_quotes)
        assert {q.instrument.instrument_id for q in books} == set(seen[0].instrument_ids)
        assert all(q.entitlement == "UNKNOWN" for q in books)
    finally:
        feed.close()
    result = check(*args[:4], clock_source=lambda: AT + timedelta(days=3))[0]
    assert result["rollover_sessions"] == [TARGET.isoformat()]
    assert result["effective_policy_sha256"] == fingerprint(proposed)
    assert not result["trading_ready"]
    with sqlite3.connect(directory / "collector.db") as db:
        assert db.execute("SELECT configuration FROM control").fetchone()[0] != rollover.base_hash(
            base, schemas
        )
    # An identical request cannot append a duplicate or reinterpret an old receipt.
    with pytest.raises(ValueError, match="already enrolled"):
        apply(args, reviewed)


@pytest.mark.parametrize(
    "damage",
    [
        "poll",
        "capture",
        "stocks",
        "history",
        "metadata",
        "expired",
        "alias",
        "changed_identity",
        "duplicate",
        "past",
        "weekend",
        "too_far",
    ],
)
def test_invalid_rollover_changes_nothing(tmp_path, schemas, damage):
    args, _, base, proposed = prepared(tmp_path, schemas)
    value = proposed.model_dump()
    if damage == "poll":
        value["poll_seconds"] = 21
    elif damage == "capture":
        value["capture"]["oauth_file"] = "/unopened/changed"
    elif damage == "stocks":
        value["stocks"] = (value["stocks"][0],)
    elif damage == "history":
        from app.mixed.swing_feed import SwingHistoryPolicy

        value["swing_history"] = SwingHistoryPolicy()
    elif damage == "metadata":
        value["candidates"][0]["metadata_complete"] = False
    elif damage == "expired":
        value["candidates"] = base.candidates
    elif damage == "alias":
        value["candidates"] = (future(), future(identity="alias"))
    elif damage == "changed_identity":
        value["candidates"] = (future(identity=instrument().instrument_id),)
    elif damage == "duplicate":
        value["candidates"] = (future(), future())
    elif damage == "past":
        args = (*args[:-1], AT.date())
    elif damage == "weekend":
        args = (*args[:-1], date(2026, 10, 25))
    else:
        args = (*args[:-1], date(2027, 1, 4))
    args[4].write_text(FeedPolicy.model_validate(value).model_dump_json())
    before = digest(tmp_path)
    with pytest.raises(ValueError):
        review(args)
    assert digest(tmp_path) == before


@pytest.mark.parametrize("damage", ["owner", "collector", "request"])
def test_stale_review_cannot_append(tmp_path, schemas, damage):
    args, _, _, proposed = prepared(tmp_path, schemas)
    reviewed = review(args)
    if damage == "request":
        args[4].write_text(proposed.model_copy(update={"candidates": ()}).model_dump_json())
    else:
        with sqlite3.connect(
            args[0 if damage == "owner" else 1]
            / ("options.db" if damage == "owner" else "collector.db")
        ) as db:
            if damage == "owner":
                db.execute(
                    "INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)",
                    (AT.isoformat(), "ROLLOVER_CHANGED", "{}"),
                )
            else:
                db.execute(
                    "INSERT INTO attempts VALUES(1,?,0,'FAILED',?,NULL,NULL,NULL)",
                    (AT.isoformat(), "a" * 64),
                )
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="review changed"):
        apply(args, reviewed)
    assert digest(tmp_path) == before


@pytest.mark.parametrize("owner_lock", [True, False])
def test_both_existing_leases_are_required(tmp_path, schemas, owner_lock):
    args, _, base, _ = prepared(tmp_path, schemas)
    reviewed = review(args)
    before = digest(tmp_path)
    if owner_lock:
        with runtime_lease(args[0] / "options.db"), pytest.raises(RuntimeAlreadyRunning):
            apply(args, reviewed)
    else:
        feed = ContinuousFeed(args[1], base, schemas)
        try:
            with pytest.raises(BlockingIOError):
                apply(args, reviewed)
        finally:
            feed.close()
    assert digest(tmp_path) == before
    assert apply(args, reviewed)["state_modified"]


@pytest.mark.parametrize("damage", ["payload", "delete", "head", "drop", "owner"])
def test_changed_rollover_receipt_blocks_restart(tmp_path, schemas, damage):
    args, _, base, _ = prepared(tmp_path, schemas)
    apply(args, review(args))
    with sqlite3.connect(args[1] / "collector.db") as db:
        if damage == "payload":
            db.execute("UPDATE feed_rollovers SET payload_json='{}'")
        elif damage == "delete":
            db.execute("DELETE FROM feed_rollovers")
        elif damage == "head":
            db.execute("UPDATE feed_rollover_control SET head_hash=?", ("0" * 64,))
        elif damage == "drop":
            db.execute("DROP TABLE feed_rollovers")
        else:
            record = rollover.FeedRollover.model_validate_json(
                db.execute("SELECT payload_json FROM feed_rollovers").fetchone()[0]
            )
            record = record.model_copy(update={"owner_configuration_sha256": "0" * 64})
            db.execute(
                "UPDATE feed_rollovers SET payload_json=?,payload_hash=?",
                (record.model_dump_json(), fingerprint(record)),
            )
            db.execute("UPDATE feed_rollover_control SET head_hash=?", (fingerprint(record),))
    before = digest(tmp_path)
    with pytest.raises(ValueError):
        check(*args[:4], clock_source=lambda: AT)
    assert digest(tmp_path) == before
    if damage != "owner":
        with pytest.raises(ValueError):
            ContinuousFeed(args[1], base, schemas)


def test_transaction_failure_rolls_back_both_protocol_and_receipt(tmp_path, schemas):
    args, _, base, _ = prepared(tmp_path, schemas)
    reviewed = review(args)
    with sqlite3.connect(args[1] / "collector.db") as db:
        db.execute(
            "CREATE TRIGGER refuse_rollover BEFORE UPDATE ON control BEGIN SELECT RAISE(ABORT,'synthetic interruption'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        apply(args, reviewed)
    feed = ContinuousFeed(args[1], base, schemas)
    try:
        assert not feed.rollovers
        assert not feed.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='feed_rollovers'"
        ).fetchone()
    finally:
        feed.close()
    with sqlite3.connect(args[1] / "collector.db") as db:
        db.execute("DROP TRIGGER refuse_rollover")
    assert apply(args, reviewed)["state_modified"]


def test_old_history_and_carry_binding_survive_new_session_schedule(tmp_path, schemas):
    from test_mixed_stock_carry import carry_policy
    from test_swing_binding import connected
    from test_swing_feed import PREOPEN, reader

    from app.mixed.carry import SwingCarryIntent
    from app.options.runtime_cli import initialize
    from app.options.runtime_models import RuntimeSettings

    settings, base = connected(tmp_path)
    value = settings.model_dump()
    value["execution"]["mixed_owner"]["stock_carry"] = carry_policy()
    settings = RuntimeSettings.model_validate(value)
    original_intent = SwingCarryIntent(
        target_session=PREOPEN.date(), stock_exit_session=PREOPEN.date() + timedelta(days=1)
    )
    base = FeedPolicy.model_validate(base.model_dump() | {"carry_intents": (original_intent,)})
    owner, directory = tmp_path / "owner", tmp_path / "feed"
    initialize(owner, settings, clock=lambda: PREOPEN)
    feed = ContinuousFeed(directory, base, schemas, create=True)
    try:
        asyncio.run(feed.tick(now=PREOPEN, reader=reader(PREOPEN, [])))
        first = feed.bind_swing_sources(settings, now=PREOPEN + timedelta(seconds=2))
        original = tuple(feed.db.execute("SELECT * FROM swing_source_bindings").fetchone())
        history = tuple(feed.db.execute("SELECT * FROM swing_history").fetchone())
        assert first["status"] == "BLOCKED"
    finally:
        feed.close()
    target = PREOPEN.date() + timedelta(days=1)
    intent = original_intent.model_copy(
        update={"target_session": target, "stock_exit_session": target + timedelta(days=1)}
    )
    proposed = FeedPolicy.model_validate(base.model_dump() | {"carry_intents": (intent,)})
    paths = tuple(tmp_path / n for n in ("policy.json", "schemas.json", "next.json"))
    for p, v in zip(paths, (base, schemas, proposed)):
        p.write_text(v.model_dump_json())
        p.chmod(0o600)
    args = owner, directory, *paths, target
    apply(args, review(args, PREOPEN + timedelta(seconds=3)), PREOPEN + timedelta(seconds=4))
    feed = ContinuousFeed(directory, base, schemas)
    try:
        assert tuple(feed.db.execute("SELECT * FROM swing_source_bindings").fetchone()) == original
        assert tuple(feed.db.execute("SELECT * FROM swing_history").fetchone()) == history
        assert (
            feed.load_swing_sources(
                settings, PREOPEN.date(), now=PREOPEN + timedelta(days=1)
            ).created_at.isoformat()
            == first["created_at"]
        )
        later = PREOPEN + timedelta(days=1)
        assert asyncio.run(feed.tick(now=later, reader=reader(later, [])))["status"] == "DELIVERED"
        result = feed.bind_swing_sources(settings, now=later + timedelta(seconds=2))
        assert result["status"] == "BLOCKED"  # UNKNOWN remains UNKNOWN.
        bound = feed.load_swing_sources(settings, target, now=later + timedelta(seconds=3))
        from app.mixed.swing_binding import policy_from_settings

        assert bound.policy_hash == fingerprint(
            policy_from_settings(settings, proposed.candidates, intent)
        )
    finally:
        feed.close()


def test_second_session_is_independent_and_first_record_is_immutable(tmp_path, schemas):
    args, _, base, proposed = prepared(tmp_path, schemas)
    first = apply(args, review(args))
    second_args = (*args[:-1], TARGET + timedelta(days=1))
    second = apply(second_args, review(second_args))
    assert first["rollover_sha256"] != second["rollover_sha256"]
    feed = ContinuousFeed(args[1], base, schemas)
    try:
        assert len(feed.rollovers) == 2
        assert fingerprint(feed.rollovers[0]) == first["rollover_sha256"]
        assert feed.rollovers[1].previous_sha256 == first["rollover_sha256"]
        assert feed.policy_for(TARGET) == feed.policy_for(TARGET + timedelta(days=1)) == proposed
    finally:
        feed.close()


@pytest.mark.parametrize("table", ["swing_history", "swing_source_bindings"])
def test_prepared_future_session_cannot_be_reinterpreted(tmp_path, schemas, table):
    args, _, _, _ = prepared(tmp_path, schemas)
    with sqlite3.connect(args[1] / "collector.db") as db:
        db.execute(f"CREATE TABLE {table}(target_session TEXT PRIMARY KEY)")
        db.execute(f"INSERT INTO {table} VALUES(?)", (TARGET.isoformat(),))
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="preparation already exists"):
        review(args)
    assert digest(tmp_path) == before


def test_running_owner_and_clock_regression_block_new_sessions(tmp_path, schemas):
    args, _, _, _ = prepared(tmp_path, schemas)
    with sqlite3.connect(args[0] / "options.db") as db:
        db.execute("UPDATE execution_option_runtime SET status='RUNNING'")
    with pytest.raises(ValueError, match="Stop the existing runtime"):
        review(args)
    with sqlite3.connect(args[0] / "options.db") as db:
        db.execute("UPDATE execution_option_runtime SET status='STOPPED'")
    created = AT + timedelta(seconds=10)
    apply(args, review(args, created), created)
    later = (*args[:-1], TARGET + timedelta(days=1))
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="clock regressed"):
        review(later, created - timedelta(seconds=1))
    assert digest(tmp_path) == before


def test_lease_recheck_catches_changed_request(tmp_path, schemas, monkeypatch):
    from contextlib import contextmanager

    args, _, _, proposed = prepared(tmp_path, schemas)
    reviewed = review(args)
    real_lease = rollover.collector_lease

    @contextmanager
    def changed(directory):
        with real_lease(directory):
            args[4].write_text(proposed.model_copy(update={"candidates": ()}).model_dump_json())
            yield

    monkeypatch.setattr(rollover, "collector_lease", changed)
    with pytest.raises(ValueError, match="review changed"):
        apply(args, reviewed)
    with sqlite3.connect(args[1] / "collector.db") as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='feed_rollovers'").fetchone()


def test_capture_crossing_session_boundary_keeps_quotes_without_entry_cycle(tmp_path, schemas):
    args, _, base, _ = prepared(tmp_path, schemas)
    apply(args, review(args))
    feed = ContinuousFeed(args[1], base, schemas)
    try:
        at = AT.replace(day=26, hour=3, minute=59, second=59)
        seen = []
        assert asyncio.run(feed.tick(now=at, reader=captured(at, seen)))["status"] == "DELIVERED"
        packet = read_packet(args[1] / "feed.json")
        assert packet.kind == "MARKET" and packet.frame.stocks
        assert "SESSION_BOUNDARY_DURING_CAPTURE" in packet.coverage_issues
        assert not seen[0].instrument_ids
        next_at = at + timedelta(seconds=10)
        assert asyncio.run(feed.tick(now=next_at, reader=captured(next_at, seen)))["sequence"] == 2
        assert seen[-1].instrument_ids == (future().instrument_id,)
    finally:
        feed.close()


def test_cli_review_apply_and_sanitized_failure_never_start_workers(
    tmp_path, schemas, monkeypatch, capsys
):
    args, _, _, _ = prepared(tmp_path, schemas)
    original_review = rollover.review
    monkeypatch.setattr(
        rollover, "review", lambda *a, **k: original_review(*a, clock_source=lambda: AT)
    )
    # Preserve the original implementation; only freeze the offline test clock.

    def forbidden(*a, **k):
        pytest.fail("Rollover started a worker")

    monkeypatch.setattr(ContinuousFeed, "run", forbidden)
    monkeypatch.setattr("app.options.runtime.OptionRuntime.run", forbidden)
    flags = [
        v
        for n, p in zip(
            ("directory", "feed-directory", "policy", "schemas", "next-policy", "target-session"),
            args,
        )
        for v in ("--" + n, str(p))
    ]
    assert rollover.main(["review", *flags]) == 0
    reviewed = json.loads(capsys.readouterr().out)
    # apply's default clock must also be frozen explicitly at this CLI seam.
    original_apply = rollover.apply
    monkeypatch.setattr(
        rollover, "apply", lambda *a, **k: original_apply(*a, **k, clock_source=lambda: AT)
    )
    assert rollover.main(["apply", *flags, "--expected-review", "unreviewed-private-text"]) == 2
    assert "unreviewed-private-text" not in capsys.readouterr().out
    assert rollover.main(["apply", *flags, "--expected-review", reviewed["review_sha256"]]) == 0
    assert not json.loads(capsys.readouterr().out)["workers_started"]
