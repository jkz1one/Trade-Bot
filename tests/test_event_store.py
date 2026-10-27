import json
from datetime import timedelta
from threading import Thread

import pytest
from test_event_assessment import AT, P, changed, coverage, event, request
from test_event_sources import spec

from app.events.assessment import assess
from app.events.models import Snapshot
from app.events.store import EventStore, SnapshotLoader
from app.events.worker import collect_once


def make_store(tmp_path):
    return EventStore(tmp_path / "events", "fixture-owner", P, create=True)


def retain(store, **fields):
    store.retain(
        {key: [v.model_dump(mode="json") for v in values] for key, values in fields.items()}
    )


def test_revisions_reschedule_cancel_out_of_order_and_restart(tmp_path):
    store = make_store(tmp_path)
    e = event()
    retain(store, events=(e,), coverage=(coverage(),))
    first = store.publish(now=AT)
    rescheduled = changed(
        e,
        starts_at=AT + timedelta(hours=2),
        ends_at=AT + timedelta(hours=2),
        revision="2",
        source_at=AT - timedelta(minutes=5),
        received_at=AT,
    )
    retain(store, events=(rescheduled,))
    store.publish(now=AT)
    retain(store, events=(e,))  # delayed duplicate cannot resurrect old timing
    s = store.publish(now=AT)
    assert s.events == (rescheduled,)
    cancel = changed(rescheduled, status="CANCELLED", revision="3", source_at=AT, received_at=AT)
    retain(store, events=(cancel,))
    store.publish(now=AT)
    restarted = EventStore(store.directory, "fixture-owner", P)
    assert restarted.as_of(AT).events[0].status == "CANCELLED"
    assert len(restarted.export()["snapshots"]) == 4
    assert first.events[0].starts_at == AT
    with pytest.raises(ValueError):
        EventStore(store.directory, "different-owner", P)
    with pytest.raises(ValueError):
        EventStore(store.directory, "fixture-owner", changed(P, quote_max_age_seconds=5))


def test_conflicting_same_revision_retained_and_atomic_reader(tmp_path):
    store = make_store(tmp_path)
    retain(
        store,
        events=(
            event(),
            changed(event(), starts_at=AT + timedelta(hours=1), ends_at=AT + timedelta(hours=1)),
        ),
    )
    store.publish(now=AT)
    loader = SnapshotLoader(store.directory / "risk.json", P)
    assert loader.refresh()
    assert len(loader.view.snapshot.events) == 2
    failures = []

    def reader():
        for _ in range(100):
            try:
                Snapshot.model_validate_json((store.directory / "risk.json").read_bytes())
            except (ValueError, OSError) as exc:
                failures.append(type(exc).__name__)

    thread = Thread(target=reader)
    thread.start()
    for i in range(5):
        store.publish(now=AT + timedelta(seconds=i))
    thread.join()
    assert not failures


def test_interrupted_publication_preserves_last_good_and_skips_unpublished_version(
    tmp_path, monkeypatch
):
    import app.events.store as module

    store = make_store(tmp_path)
    retain(store, events=(event(),))
    first = store.publish(now=AT)
    original = (store.directory / "risk.json").read_bytes()

    def fail(*args):
        raise OSError("fixture atomic failure")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError):
        store.publish(now=AT + timedelta(seconds=1))
    assert (store.directory / "risk.json").read_bytes() == original
    assert store.as_of(AT + timedelta(seconds=2)) == first


def test_loader_corruption_regression_and_same_sequence_change_are_unknown(tmp_path):
    store = make_store(tmp_path)
    store.publish(now=AT)
    path = store.directory / "risk.json"
    old = path.read_bytes()
    store.publish(now=AT)
    loader = SnapshotLoader(path, P)
    assert loader.refresh()
    path.write_bytes(old)
    assert not loader.refresh() and assess(loader.view, request()).state == "UNKNOWN"
    path.write_text("{")
    assert not loader.refresh()
    value = json.loads(old)
    value["sequence"] = 2
    value["issues"] = ["ALTERED_PUBLICATION"]
    path.write_text(json.dumps(value))
    assert not loader.refresh()


def test_source_outage_retains_events_and_collection_failure_no_secrets(tmp_path):
    store = make_store(tmp_path)
    retain(store, events=(event(),), coverage=(coverage(),))

    class Failed:
        spec = spec("fixture", "macro.us.high_impact")
        api_key = "never-print-this"

        def fetch(self):
            raise TimeoutError(self.api_key)

    out = collect_once(store, Failed(), clock=lambda: AT)
    exported = store.export()
    assert out["status"] == "UNAVAILABLE"
    assert "never-print-this" not in json.dumps(exported)
    assert exported["snapshots"][-1]["events"]
    assert exported["snapshots"][-1]["coverage"][0]["status"] == "UNAVAILABLE"
    assert exported["collections"][1]["collection_ms"] >= 0


def test_writer_lease_and_future_receipt_reject_without_partial_file(tmp_path):
    store = make_store(tmp_path)
    with store.writer(), pytest.raises(BlockingIOError):
        store.publish(now=AT)
    retain(store, events=(changed(event(), received_at=AT + timedelta(seconds=1)),))
    with pytest.raises(ValueError):
        store.publish(now=AT)
    assert not (store.directory / "risk.json").exists()


def test_worker_success_preserves_raw_and_original_source_times(tmp_path):
    store = make_store(tmp_path)

    class Ready:
        spec = spec()

        def fetch(self):
            return "original-provider-response"

        def parse(self, raw, now):
            return {"events": [event().model_dump(mode="json")]}

    out = collect_once(store, Ready(), clock=lambda: AT)
    assert out["status"] == "COLLECTED"
    assert store.export()["collections"][0]["raw"] == "original-provider-response"
    assert store.as_of(AT - timedelta(seconds=1)) is None
    assert store.as_of(AT).events[0].source_at == event().source_at


def test_sequence_revision_and_publication_clock_regression(tmp_path):
    store = make_store(tmp_path)
    first = changed(event(), revision_sequence=1)
    second = changed(
        first,
        revision="2",
        revision_sequence=2,
        starts_at=AT + timedelta(hours=1),
        ends_at=AT + timedelta(hours=1),
    )
    retain(store, events=(first, second))
    assert store.publish(now=AT).events == (second,)
    with pytest.raises(ValueError, match="regressed"):
        store.publish(now=AT - timedelta(seconds=1))
