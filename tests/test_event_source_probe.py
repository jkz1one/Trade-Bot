"""Offline subprocess fixtures are separate from retained public-provider captures."""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from test_event_assessment import AT
from test_event_sources import ics, spec

from app.events import source_probe as probe
from app.events.adapters import BEA_URL, BLS_EASTERN_DEFINITION, BLS_URL, ICalendarAdapter
from app.options.engine import fingerprint


def request(source="bea", **kwargs):
    return probe.ProbeRequest(
        source=source, starts_at=AT, ends_at=AT + timedelta(days=30), **kwargs
    )


def command_for(raw):
    return [
        sys.executable,
        "-I",
        "-c",
        "from app.events import source_probe as p; p.ICalendarAdapter.fetch=lambda self: "
        + repr(raw)
        + ";p.main(['_child'])",
    ]


def test_fixed_child_capture_replay_keeps_original_clocks_and_has_no_store(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_command", lambda: command_for(ics()))
    result = probe.capture(tmp_path / "capture", request())
    assert result["status"] == "PARSED_PARTIAL"
    path = tmp_path / "capture" / "capture.json"
    artifact = json.loads(path.read_text())
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert list(path.parent.iterdir()) == [path]
    assert artifact["result"]["raw_decoded_utf8"] == ics()
    monkeypatch.setattr(
        probe.ICalendarAdapter, "fetch", lambda *_: pytest.fail("Network during replay")
    )
    report = probe.verify(path)
    assert report["offline_replay_verified"] and report["provider_calls_during_replay"] == 0
    assert report["coverage"][0]["checked_at"] == artifact["result"]["received_at"].replace(
        "+00:00", "Z"
    )
    assert not report["coverage_accepted"] and not report["host_accepted"]
    assert not report["operational_evidence_published"] and not report["execution_authority"]
    with pytest.raises(FileExistsError):
        probe.capture(path.parent, request())


def test_slow_child_killed_and_failure_durably_replayable(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    code = f"import os,time;from pathlib import Path;Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(20)"
    monkeypatch.setattr(probe, "_command", lambda: [sys.executable, "-I", "-c", code])
    result = probe.capture(tmp_path / "slow", request(timeout_seconds=1))
    assert result["status"] == "PROCESS_TIMEOUT"
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
    assert probe.verify(tmp_path / "slow" / "capture.json")["offline_replay_verified"]


@pytest.mark.parametrize(
    "code,status",
    [
        ("raise SystemExit(3)", "PROCESS_UNAVAILABLE"),
        ("print('invalid')", "PROCESS_PROTOCOL_OR_LAUNCH_UNAVAILABLE"),
    ],
)
def test_child_exit_and_malformed_protocol_are_explicit_failures(
    tmp_path, monkeypatch, code, status
):
    monkeypatch.setattr(probe, "_command", lambda: [sys.executable, "-I", "-c", code])
    assert probe.capture(tmp_path / "failed", request())["status"] == status
    assert probe.verify(tmp_path / "failed" / "capture.json")["status"] == status


def test_parse_failure_preserves_raw_not_normalized_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_command", lambda: command_for("not a calendar"))
    result = probe.capture(tmp_path / "bad", request())
    assert result["status"] == "PARSE_UNAVAILABLE" and result["error_class"] == "ValueError"
    artifact = json.loads((tmp_path / "bad" / "capture.json").read_text())
    assert artifact["result"]["raw_decoded_utf8"] == "not a calendar"
    assert artifact["result"]["normalized"] is None
    assert probe.verify(tmp_path / "bad" / "capture.json")["offline_replay_verified"]


def test_transport_failure_does_not_retain_exception_messages(monkeypatch):
    def fail(*args):
        raise RuntimeError("private-token-must-not-be-retained")

    monkeypatch.setattr(probe.ICalendarAdapter, "fetch", fail)
    value = probe.child_capture(request())
    assert value["status"] == "FETCH_UNAVAILABLE" and value["error_class"] == "RuntimeError"
    assert "private-token" not in json.dumps(value)
    probe.validate_child(request(), value)


@pytest.mark.parametrize("damage", ["raw", "normalized", "receipt", "authority", "endpoint"])
def test_tampered_artifact_cannot_pass_replay_even_with_rehashed_metadata(
    tmp_path, monkeypatch, damage
):
    monkeypatch.setattr(probe, "_command", lambda: command_for(ics()))
    probe.capture(tmp_path / "capture", request())
    path = tmp_path / "capture" / "capture.json"
    value = json.loads(path.read_text())
    if damage == "raw":
        value["result"]["raw_decoded_utf8"] += "tamper"
    elif damage == "normalized":
        value["result"]["normalized"]["events"][0]["title"] = "tamper"
    elif damage == "receipt":
        value["result"]["received_at"] = AT.isoformat()
    elif damage == "authority":
        value["execution_authority"] = True
    else:
        value["endpoint"] = "https://other.invalid"
    value["artifact_hash"] = fingerprint({k: v for k, v in value.items() if k != "artifact_hash"})
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        probe.verify(path)


def bls_ics(start="20261027T083000"):
    return ics("DTSTART;TZID=US-Eastern:" + start).replace(
        "VERSION:2.0", "VERSION:2.0\n" + BLS_EASTERN_DEFINITION
    )


@pytest.mark.parametrize("start,hour", [("20261027T083000", 12), ("20261102T083000", 13)])
def test_reviewed_bls_custom_timezone_preserves_dst(start, hour):
    value = ICalendarAdapter(spec(), BLS_URL).parse(bls_ics(start), AT)
    assert value["events"][0]["timezone"] == "America/New_York"
    assert int(value["events"][0]["starts_at"][11:13]) == hour
    assert value["coverage"][0]["status"] == "PARTIAL"


@pytest.mark.parametrize("damage", ["offset", "rule", "missing", "other_source", "ambiguous"])
def test_bls_timezone_alias_is_not_a_generic_permissive_rewrite(damage):
    raw, url = bls_ics(), BLS_URL
    if damage == "offset":
        raw = raw.replace("TZOFFSETTO:-0400", "TZOFFSETTO:-0300")
    elif damage == "rule":
        raw = raw.replace("BYDAY=2SU", "BYDAY=1SU")
    elif damage == "missing":
        raw = raw.replace(BLS_EASTERN_DEFINITION, "")
    elif damage == "other_source":
        url = BEA_URL
    else:
        raw = bls_ics("20261101T013000")
    with pytest.raises(ValueError):
        ICalendarAdapter(spec(), url).parse(raw, AT)


def test_original_bls_response_maps_missing_revision_times_without_fabricating_them():
    path = Path(__file__).parent / "fixtures/event_sources/bls-initial.json"
    value = json.loads(path.read_text())
    raw, received = value["result"]["raw_decoded_utf8"], value["result"]["received_at"]
    from datetime import datetime

    payload = probe.normalize(
        probe.ProbeRequest.model_validate(value["request"]), raw, datetime.fromisoformat(received)
    )
    assert payload["events"]
    assert all(e["source_at"] is None and not e["complete"] for e in payload["events"])
    assert all(e["source_version"] == "bls-adapter-v2" for e in payload["events"])


def test_bounded_allowlisted_request_and_unchanged_reference_to_original_raw():
    with pytest.raises(ValueError):
        request("unknown")
    with pytest.raises(ValueError):
        request(timeout_seconds=61)
    with pytest.raises(ValueError):
        probe.ProbeRequest(source="bea", starts_at=AT, ends_at=AT)


@pytest.mark.parametrize("source", ["bea", "vix", "bls"])
def test_retained_actual_provider_response_replays_offline_without_promoting_coverage(
    tmp_path, monkeypatch, source
):
    import shutil

    original = Path(__file__).parent / "fixtures/event_sources" / (source + ".json")
    destination = tmp_path / "capture.json"
    shutil.copyfile(original, destination)
    destination.chmod(0o600)
    monkeypatch.setattr(
        probe.ICalendarAdapter, "fetch", lambda *_: pytest.fail("Replay used network")
    )
    monkeypatch.setattr(
        probe.CboeDailyAdapter, "fetch", lambda *_: pytest.fail("Replay used network")
    )
    report = probe.verify(destination)
    assert report["status"] == "PARSED_PARTIAL"
    assert report["offline_replay_verified"]
    assert all(c["status"] == "PARTIAL" for c in report["coverage"])
    assert not report["coverage_accepted"] and not report["operational_evidence_published"]


def test_failed_atomic_publication_leaves_no_accepted_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_command", lambda: command_for(ics()))

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(probe.os, "replace", fail)
    with pytest.raises(OSError):
        probe.capture(tmp_path / "capture", request())
    assert list((tmp_path / "capture").iterdir()) == []
