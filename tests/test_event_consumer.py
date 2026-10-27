"""Offline native publisher/owner fixtures; no provider or host acceptance."""

import json
import sqlite3
from datetime import timedelta

import pytest
from test_dashboard_snapshot import digest, publisher, view
from test_event_assessment import P, changed, event
from test_event_native import published_fixture

from app.events.consumer import ObserverBatch, SuppliedContext, consume_once
from app.events.store import EventStore


def fixture(tmp_path):
    source, settings, path, binding, requests, at = published_fixture(tmp_path)
    store = EventStore(tmp_path / "events", settings.limits.population_id, P, create=True)
    store.retain({"events": [event(requests[0].evaluated_at).model_dump(mode="json")]})
    store.publish(now=requests[0].evaluated_at)
    return source, settings, path, binding, requests, at, store


def test_bounded_restart_exactly_once_and_unchanged_native_accounting(tmp_path, monkeypatch):
    source, settings, path, binding, requests, at, store = fixture(tmp_path)
    before, account = digest(source), view(path, settings, at)

    def forbidden(*args, **kwargs):
        pytest.fail("Observer opened a provider/model/owner")

    monkeypatch.setattr("app.options.runtime_cli.existing_runtime", forbidden)
    monkeypatch.setattr("app.options.read_capture.collect", forbidden)
    monkeypatch.setattr("app.options.coordinator.model_key", forbidden)
    first = consume_once(store, binding, recorded_at=at, batch=ObserverBatch(max_events=1))
    assert first["status"] == "BACKLOG" and first["events_scanned"] == 1
    restarted = EventStore(store.directory, settings.limits.population_id, P)
    result = consume_once(restarted, binding, recorded_at=at, batch=ObserverBatch(max_events=1000))
    assert result["status"] == "CAUGHT_UP" and result["unresolved_gaps"] == 0
    out = restarted.export()
    assert len(out["observations"]) == len(requests) == 2
    assert all(o["assessment"]["would_block_new_entries"] for o in out["observations"])
    assert {o["context_origin"] for o in out["observations"]} == {
        "RETAINED_NATIVE_DECISION_CONTEXT"
    }
    assert {o["assessment"]["request"]["holding_until"] for o in out["observations"]} == {
        r.model_dump(mode="json")["holding_until"] for r in requests
    }
    again = consume_once(restarted, binding, recorded_at=at + timedelta(seconds=1))
    assert again["events_scanned"] == again["observed"] == 0
    assert restarted.export()["observations"] == out["observations"]
    assert digest(source) == before and view(path, settings, at) == account


def rejected_copy(source, path, at):
    from app.mixed.models import StockProposal
    from app.options.runtime_cli import existing_runtime

    with existing_runtime(source, clock=lambda: at) as (runtime, _):
        result = runtime.c.engine.prepare_stock(
            "missing-context",
            StockProposal(action="HOLD", thesis="No candidate selected"),
            None,
            now=at,
        )
        assert result["status"] in {"HOLD", "REJECTED"}
    p = publisher(source, path.parent, create=False, at=at + timedelta(seconds=1))
    try:
        p.publish()
    finally:
        p.close()


def test_missing_context_gap_is_retained_then_repaired_without_lookahead(tmp_path):
    source, _, path, binding, requests, at, store = fixture(tmp_path)
    rejected_copy(source, path, at)
    before = digest(source)
    result = consume_once(store, binding, recorded_at=at + timedelta(seconds=1))
    assert result["status"] == "CAUGHT_UP_WITH_GAPS" and result["unresolved_gaps"] == 1
    gap = next(d for d in store.export()["observer"]["deliveries"] if d["status"] == "GAP")
    assert gap["reason"] == "MISSING_CANDIDATE_FAMILY_OR_HOLDING_CONTEXT"
    r = changed(requests[0], decision_id="missing-context", evaluated_at=at)
    supplied = ObserverBatch(contexts=(SuppliedContext(kind="PORTFOLIO", request=r),))
    fixed = consume_once(store, binding, recorded_at=at + timedelta(seconds=2), batch=supplied)
    assert fixed["observed"] == 1 and fixed["unresolved_gaps"] == 0 and fixed["events_scanned"] == 0
    out = store.export()
    obs = next(o for o in out["observations"] if o["decision_id"] == "missing-context")
    assert not obs["native_instrument_verified"]
    assert obs["context_origin"] == "EXPLICIT_CALLER_CANDIDATE_AND_HORIZON"
    assert out["observer"]["attempts"][0]["unresolved_gaps"] == 1
    assert digest(source) == before
    # A later event publication cannot change an already persisted observation.
    store.publish(now=at + timedelta(seconds=2))
    assert consume_once(store, binding, recorded_at=at + timedelta(seconds=3))["observed"] == 0
    assert store.export()["observations"] == out["observations"]


def test_conflicting_context_is_gap_not_silently_shorter_holding_coverage(tmp_path):
    _, _, _, binding, requests, at, store = fixture(tmp_path)
    bad = changed(requests[0], holding_until=requests[0].evaluated_at)
    result = consume_once(
        store,
        binding,
        recorded_at=at,
        batch=ObserverBatch(
            contexts=(SuppliedContext(kind="PORTFOLIO", request=bad),),
        ),
    )
    assert result["observed"] == 1 and result["unresolved_gaps"] == 1
    assert any(d["reason"] == "CONTEXT_CONFLICT_OR_INVALID" for d in result["delivery_outcomes"])
    retry = consume_once(store, binding, recorded_at=at)
    assert retry["observed"] == 1 and retry["unresolved_gaps"] == 0


def test_atomic_batch_rollback_and_retry_after_persistence_failure(tmp_path):
    _, _, _, binding, _, at, store = fixture(tmp_path)
    consume_once(store, binding, recorded_at=at, batch=ObserverBatch(max_events=1))
    before = store.export()["observer"]["state"]
    with store.db() as db:
        db.execute(
            "CREATE TRIGGER fail_cursor BEFORE UPDATE ON observer_state BEGIN "
            "SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    failed = consume_once(store, binding, recorded_at=at)
    assert failed["status"] == "UNAVAILABLE" and failed["observed"] == 0
    assert not failed["committed"] and failed["delivery_outcomes"] == []
    assert failed["pending_native_events"] == (
        failed["native_publication"]["checkpoint"]["owner_revision"] - before["cursor"]
    )
    out = store.export()
    assert out["observer"]["state"] == before
    assert out["observations"] == out["observer"]["deliveries"] == []
    with store.db() as db:
        db.execute("DROP TRIGGER fail_cursor")
    assert consume_once(store, binding, recorded_at=at)["observed"] == 2


@pytest.mark.parametrize("failure", ["stale", "future", "missing", "corrupt", "sequence_gap"])
def test_unavailable_snapshot_retains_failure_without_advancing(tmp_path, failure):
    _, _, path, binding, _, at, store = fixture(tmp_path)
    if failure == "missing":
        path.unlink()
    elif failure == "corrupt":
        path.write_bytes(b"broken database")
    elif failure == "sequence_gap":
        with sqlite3.connect(path) as db:
            db.execute("DELETE FROM execution_events WHERE sequence=1")
    when = at + timedelta(seconds=61) if failure == "stale" else at
    when = at - timedelta(seconds=1) if failure == "future" else when
    result = consume_once(store, binding, recorded_at=when)
    assert result["status"] == "UNAVAILABLE" and result["cursor_after"] == 0
    if failure == "stale":
        assert result["reason"] == "STALE_NATIVE_PUBLICATION"
        assert result["publication_age_seconds"] == 61
    elif failure == "future":
        assert result["reason"] == "NATIVE_PUBLICATION_IN_FUTURE"
    elif failure == "sequence_gap":
        assert result["reason"] == "NATIVE_EVENT_SEQUENCE_GAP"
    out = store.export()
    assert not out["observations"] and not out["observer"]["deliveries"]
    assert out["observer"]["attempts"][-1]["error_type"]


def test_publication_regression_and_anchor_mutation_rejected_across_restart(tmp_path):
    _, settings, path, binding, _, at, store = fixture(tmp_path)
    saved = path.read_bytes()
    assert consume_once(store, binding, recorded_at=at)["status"] == "CAUGHT_UP"
    before = store.export()["observer"]["state"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE execution_events SET payload='{}' WHERE sequence=?", (before["cursor"],))
    restarted = EventStore(store.directory, settings.limits.population_id, P)
    assert consume_once(restarted, binding, recorded_at=at)["status"] == "UNAVAILABLE"
    path.write_bytes(saved)
    with sqlite3.connect(path) as db:
        raw = json.loads(db.execute("SELECT payload FROM dashboard_snapshot").fetchone()[0])
        raw["published_at"] = (at - timedelta(seconds=1)).isoformat()
        db.execute("UPDATE dashboard_snapshot SET payload=?", (json.dumps(raw),))
    assert consume_once(restarted, binding, recorded_at=at)["status"] == "UNAVAILABLE"
    assert restarted.export()["observer"]["state"] == before


def test_snapshot_replaced_during_assessment_rolls_back_entire_batch(tmp_path, monkeypatch):
    import app.events.consumer as module

    _, _, path, binding, _, at, store = fixture(tmp_path)
    original = module.observation_payload

    def replace(*args, **kwargs):
        result = original(*args, **kwargs)
        other = path.with_suffix(".replacement")
        other.write_bytes(path.read_bytes())
        other.chmod(0o600)
        other.replace(path)
        return result

    monkeypatch.setattr(module, "observation_payload", replace)
    assert consume_once(store, binding, recorded_at=at)["status"] == "UNAVAILABLE"
    assert store.export()["observations"] == []


def test_no_event_snapshot_at_decision_is_unknown(tmp_path):
    _, settings, _, binding, _, at, _ = fixture(tmp_path)
    empty = EventStore(tmp_path / "empty-events", settings.limits.population_id, P, create=True)
    empty.publish(now=at)  # Later than the native decisions.
    assert consume_once(empty, binding, recorded_at=at)["observed"] == 2
    assert all(
        o["assessment"]["state"] == "UNKNOWN" and o["assessment"]["snapshot_sequence"] is None
        for o in empty.export()["observations"]
    )


def test_active_owner_and_duplicate_contexts_and_changed_binding_refused(tmp_path, monkeypatch):
    source, _, _, binding, requests, at, store = fixture(tmp_path)
    active = binding | {"destination": str(source)}
    original = sqlite3.connect

    def connect(path, *args, **kwargs):
        assert str(source / "options.db") not in str(path), "Active owner was opened"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert consume_once(store, active, recorded_at=at)["status"] == "UNAVAILABLE"
    with pytest.raises(ValueError, match="binding changed"):
        consume_once(store, binding, recorded_at=at)
    context = SuppliedContext(kind="PORTFOLIO", request=requests[0])
    with pytest.raises(ValueError, match="Unique contexts"):
        consume_once(
            store, binding, recorded_at=at, batch=ObserverBatch(contexts=(context, context))
        )


def test_concurrent_consumer_lease_and_collection_independence(tmp_path):
    import fcntl
    import os

    _, _, _, binding, _, at, store = fixture(tmp_path)
    fd = os.open(store.directory / "observer.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            consume_once(store, binding, recorded_at=at)
        store.retain({"kind": "INDEPENDENT_COLLECTION"})
        store.publish(now=at)
    finally:
        os.close(fd)
    assert consume_once(store, binding, recorded_at=at)["observed"] == 2


def test_gap_retry_budget_does_not_starve_later_gaps(tmp_path):
    _, _, _, binding, requests, at, store = fixture(tmp_path)
    bad = tuple(
        SuppliedContext(kind="PORTFOLIO", request=changed(r, family="SWING")) for r in requests
    )
    assert (
        consume_once(
            store,
            binding,
            recorded_at=at,
            batch=ObserverBatch(
                contexts=bad,
            ),
        )["unresolved_gaps"]
        == 2
    )
    first = consume_once(
        store,
        binding,
        recorded_at=at,
        batch=ObserverBatch(
            max_gap_retries=1,
            contexts=bad,
        ),
    )
    second = consume_once(
        store,
        binding,
        recorded_at=at,
        batch=ObserverBatch(
            max_gap_retries=1,
            contexts=bad,
        ),
    )
    assert first["gap_retries"] == second["gap_retries"] == 1
    assert first["delivery_outcomes"][0]["sequence"] != second["delivery_outcomes"][0]["sequence"]
    assert consume_once(store, binding, recorded_at=at)["unresolved_gaps"] == 0


def test_one_shot_cli_reports_committed_batch_and_unavailable_exit(tmp_path, monkeypatch, capsys):
    from app.events import cli

    _, settings, path, _, _, at, store = fixture(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(P.model_dump_json())
    now = at

    class OfflineClock:
        @staticmethod
        def now(_zone):
            return now

    monkeypatch.setattr(cli, "datetime", OfflineClock)
    args = [
        "observe-once",
        "--directory",
        str(store.directory),
        "--population",
        settings.limits.population_id,
        "--policy",
        str(policy_path),
        "--snapshot-binding",
        str(path.parent / "binding.json"),
    ]
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["committed"] and first["observed"] == 2 and not first["authority"]
    now += timedelta(seconds=61)
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "UNAVAILABLE"


def blocked_consumer(directory, population, binding, at, started, release, fail):
    import app.events.consumer as module

    original = module.native_context

    def wait(*args, **kwargs):
        started.set()
        if fail or not release.wait(10):
            raise TimeoutError("fixture consumer outage")
        return original(*args, **kwargs)

    module.native_context = wait
    store = EventStore(directory, population, P)
    module.consume_once(store, binding, recorded_at=at)


@pytest.mark.parametrize("fail", [False, True])
def test_slow_or_failed_observer_cannot_delay_native_protection(tmp_path, fail):
    import asyncio
    import multiprocessing

    from test_mixed_venue import q

    from app.mixed.stock_models import StockIntent
    from app.options.runtime_cli import existing_runtime

    source, settings, _, binding, _, at, store = fixture(tmp_path)
    ctx = multiprocessing.get_context("fork")
    started, release = ctx.Event(), ctx.Event()
    process = ctx.Process(
        target=blocked_consumer,
        args=(
            store.directory,
            settings.limits.population_id,
            binding,
            at,
            started,
            release,
            fail,
        ),
    )
    process.start()
    try:
        assert started.wait(3)
        when = at + timedelta(seconds=1)
        with existing_runtime(source, clock=lambda: when) as (runtime, _):
            e = runtime.c.engine
            with e.journal.read() as db:
                intents = [
                    StockIntent.model_validate_json(r[0])
                    for r in db.execute("SELECT intent_json FROM execution_portfolio_orders")
                ]
            quotes = tuple(q(i, when, bid="89", ask="89.01") for i in intents)

            async def protect():
                return await asyncio.wait_for(e.protective_tick(now=when, stock_quotes=quotes), 3)

            result = asyncio.run(protect())
            assert len(result["plays"]) == 2
            assert all(p["status"] == "OPEN" for p in result["plays"].values())
            if not fail:
                assert process.is_alive() and not release.is_set()
    finally:
        release.set()
        process.join(3)
        if process.is_alive():
            process.kill()
            process.join()
    assert process.exitcode == 0
