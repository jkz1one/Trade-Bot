"""Actual native simulator/journal tests, with synthetic market/provider evidence."""

import asyncio
import json
import multiprocessing
from datetime import timedelta

import pytest
from test_event_assessment import P, changed, event, request
from test_event_sources import spec
from test_mixed_venue import q
from test_portfolio_controls import NOW, get_intent, open_pair, owned

from app.events.assessment import assess, prepare
from app.events.observation import observe_decision
from app.events.store import EventStore
from app.events.worker import collect_once


def native_dump(e):
    with e.journal.read() as db:
        return tuple(db.iterdump())


def audit_for(tmp_path, e):
    store = EventStore(tmp_path / "events", e.limits.population_id, P, create=True)
    store.retain({"events": [event(NOW).model_dump(mode="json")]})
    store.publish(now=NOW)
    return store


def published_fixture(tmp_path):
    import sqlite3

    from test_dashboard_snapshot import owner, publisher
    from test_degen_options import AT

    source, settings = owner(tmp_path, positions=True)
    destination = tmp_path / "published"
    p = publisher(source, destination)
    try:
        p.publish()
        binding = p.binding
    finally:
        p.close()
    path = destination / "options.db"
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT source_key,intent_json FROM execution_portfolio_orders"
        ).fetchall()
    requests = []
    for key, raw in rows:
        intent = json.loads(raw)
        instrument = intent["instrument"]
        requests.append(
            request(
                AT,
                population_id=settings.limits.population_id,
                decision_id=key,
                symbol=instrument["symbol"],
                instrument_id=instrument["instrument_id"],
                underlying_kind=instrument["kind"],
                family=intent["family"],
                holding_until=intent["exit_at"],
            )
        )
    return source, settings, path, binding, requests, AT + timedelta(seconds=2)


def test_actual_two_play_decisions_and_accounting_unchanged_with_would_block(tmp_path):
    from test_dashboard_snapshot import digest, view

    source, settings, path, binding, requests, at = published_fixture(tmp_path)
    store = EventStore(tmp_path / "events", settings.limits.population_id, P, create=True)
    store.retain({"events": [event(requests[0].evaluated_at).model_dump(mode="json")]})
    store.publish(now=requests[0].evaluated_at)
    before, account_before = digest(source), view(source / "options.db", settings, at)
    for r in requests:
        receipt, a = observe_decision(
            store, path, "PORTFOLIO", r, recorded_at=at, snapshot_binding=binding
        )
        assert a.would_block_new_entries and not a.authority and receipt
    assert digest(source) == before
    assert view(source / "options.db", settings, at) == account_before
    out = store.export()
    assert len(out["observations"]) == 2
    assert all(o["native_result"]["status"] == "PREPARED" for o in out["observations"])
    assert all(
        o["kind"] == "EVENT_OBSERVATION_ONLY" and o["native_instrument_verified"]
        for o in out["observations"]
    )
    assert out["observations"][0]["detection_delays"][0]["source_to_detection_seconds"] is not None
    assert len(account_before["positions"]) == 2


def test_decision_link_refuses_invented_ids_population_clock_and_future_snapshot(tmp_path):
    source, settings, path, binding, requests, at = published_fixture(tmp_path)
    store = EventStore(tmp_path / "events", settings.limits.population_id, P, create=True)
    r = requests[0]
    store.retain({"events": [event(r.evaluated_at).model_dump(mode="json")]})
    store.publish(now=at)  # Not available when the native decision occurred.
    _, a = observe_decision(store, path, "PORTFOLIO", r, recorded_at=at, snapshot_binding=binding)
    assert a.state == "UNKNOWN" and a.snapshot_sequence is None
    for bad in (
        changed(r, decision_id="invented"),
        changed(r, population_id="wrong"),
        changed(r, evaluated_at=at),
        changed(r, symbol="AAPL"),
    ):
        with pytest.raises(ValueError):
            observe_decision(
                store, path, "PORTFOLIO", bad, recorded_at=at, snapshot_binding=binding
            )
    with pytest.raises(ValueError, match="active journal forbidden"):
        observe_decision(
            store, source / "options.db", "PORTFOLIO", r, recorded_at=at, snapshot_binding=binding
        )


def blocked_worker(directory, population_id, started, release, fail):
    store = EventStore(directory, population_id, P)

    class Provider:
        spec = spec()

        def fetch(self):
            started.set()
            if fail:
                raise TimeoutError("fixture outage")
            if not release.wait(10):
                raise TimeoutError("test release missing")
            return "fixture"

        def parse(self, raw, at):
            return {"events": [event(NOW).model_dump(mode="json")]}

    collect_once(store, Provider(), clock=lambda: NOW + timedelta(seconds=3))


@pytest.mark.parametrize("fail", [False, True])
def test_slow_or_failed_event_process_cannot_delay_two_mandatory_exits(tmp_path, fail):
    with owned(tmp_path) as (e, v):
        store = audit_for(tmp_path, e)
        entries, at = open_pair(e, v)
        ctx = multiprocessing.get_context("fork")
        started, release = ctx.Event(), ctx.Event()
        process = ctx.Process(
            target=blocked_worker,
            args=(store.directory, e.limits.population_id, started, release, fail),
        )
        process.start()
        try:
            assert started.wait(3)
            at += timedelta(seconds=1)
            quotes = tuple(q(i, at, bid="89", ask="89.01") for i in entries)

            async def protect():
                return await asyncio.wait_for(e.protective_tick(now=at, stock_quotes=quotes), 3)

            result = asyncio.run(protect())
            assert len(result["plays"]) == 2
            if not fail:
                assert process.is_alive() and not release.is_set()
            for i in entries:
                closing = get_intent(e, result["plays"][i.client_id]["client_id"])
                assert result["plays"][i.client_id]["status"] == "OPEN"
                assert closing.closing_entry_client_id == i.client_id
                assert closing.original_invalidation == i.original_invalidation
        finally:
            release.set()
            process.join(3)
            if process.is_alive():
                process.kill()
                process.join()
        assert process.exitcode == 0
        if fail:
            assert any(r.get("status") == "UNAVAILABLE" for r in store.export()["collections"])


def test_local_assessment_cannot_use_network_disk_or_model(monkeypatch):
    import builtins
    import socket

    from test_event_assessment import snapshot

    view = prepare(snapshot(), P)
    r = request()

    def forbidden(*args, **kwargs):
        pytest.fail("IO on assessment path")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(json, "dumps", forbidden)
    assert assess(view, r).state == "CLEAR"
