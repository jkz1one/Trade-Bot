"""One-shot public-source evidence capture/replay, isolated from operational stores."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from app.events.adapters import (
    ADAPTER_VERSIONS,
    BEA_URL,
    BLS_URL,
    MAX_RESPONSE,
    VIX_URL,
    CboeDailyAdapter,
    ICalendarAdapter,
    SourceSpec,
)
from app.events.models import Coverage, Event, Volatility
from app.options.engine import fingerprint
from app.options.models import OptionRecord
from app.options.operator_inbox import private_directory, read, sync_directory

SOURCES = {
    "bls": (BLS_URL, "macro.bls"),
    "bea": (BEA_URL, "macro.bea"),
    "vix": (VIX_URL, "volatility.daily"),
}
MAX_ARTIFACT = 8 * MAX_RESPONSE + 1024 * 1024


class ProbeRequest(OptionRecord):
    source: Literal["bls", "bea", "vix"]
    starts_at: datetime
    ends_at: datetime
    timeout_seconds: int = Field(default=20, ge=1, le=60)

    @model_validator(mode="after")
    def interval(self):
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=366):
            raise ValueError("Positive interval of at most 366 days required")
        return self


def adapter_for(request):
    url, dataset = SOURCES[request.source]
    spec = SourceSpec(
        request.source,
        ADAPTER_VERSIONS[request.source],
        dataset,
        request.starts_at,
        request.ends_at,
    )
    return CboeDailyAdapter(spec) if request.source == "vix" else ICalendarAdapter(spec, url)


def normalize(request, raw, received_at):
    """Original receipt clock is mandatory; replay never makes evidence younger."""
    if len(raw.encode()) > MAX_RESPONSE:
        raise ValueError("Oversized response")
    payload = adapter_for(request).parse(raw, received_at)
    if (
        len(payload.get("events", ())) > 10000
        or len(payload.get("coverage", ())) > 256
        or len(payload.get("volatility", ())) > 8
        or len(json.dumps(payload).encode()) > 16 * 1024 * 1024
    ):
        raise ValueError("Normalized response exceeds snapshot capacity")
    for key, cls in (("events", Event), ("coverage", Coverage), ("volatility", Volatility)):
        for row in payload.get(key, ()):
            cls.model_validate(row)
    return payload


def child_capture(request):
    started = datetime.now(UTC)
    tick = perf_counter_ns()
    raw, normalized, error, http_status = None, None, None, None
    try:
        raw = adapter_for(request).fetch()
        received = datetime.now(UTC)
        try:
            normalized = normalize(request, raw, received)
            status = "PARSED_PARTIAL"
        except Exception as exc:  # noqa: BLE001 - preserve evidence without private error text
            status, error = "PARSE_UNAVAILABLE", type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - isolate transport failure
        received = datetime.now(UTC)
        status, error = "FETCH_UNAVAILABLE", type(exc).__name__
        from urllib.error import HTTPError

        if isinstance(exc, HTTPError):
            http_status = exc.code
    return {
        "request_hash": fingerprint(request),
        "started_at": started.isoformat(),
        "received_at": received.isoformat(),
        "collection_and_parse_ms": (perf_counter_ns() - tick) / 1_000_000,
        "status": status,
        "error_class": error,
        "http_status": http_status,
        "raw_decoded_utf8": raw,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest() if raw is not None else None,
        "normalized": normalized,
    }


def _command():
    return [sys.executable, "-I", "-m", "app.events.source_probe", "_child"]


def capture(directory, request):
    """One fresh private evidence directory, one fixed child, no operational publication.

    Child timeout covers import/fetch/parse; local filesystem and OS scheduling are
    not hard-real-time bounded. Never invoke from a trading/protection process.
    """
    request = ProbeRequest.model_validate_json(request.model_dump_json())
    directory = Path(directory).absolute()
    directory.mkdir(mode=0o700)  # Refuse reuse; retain prior attempts unchanged.
    private_directory(directory)
    started, tick = datetime.now(UTC), perf_counter_ns()
    env_names = (
        "PATH",
        "LANG",
        "LC_ALL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    )
    result, status = None, "PROCESS_UNAVAILABLE"
    with tempfile.TemporaryFile(dir=directory) as output:
        try:
            completed = subprocess.run(
                _command(),
                input=request.model_dump_json().encode(),
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=request.timeout_seconds,
                env={k: os.environ[k] for k in env_names if k in os.environ},
                check=False,
            )
            if completed.returncode == 0:
                output.seek(0)
                wire = output.read(MAX_ARTIFACT + 1)
                if len(wire) <= MAX_ARTIFACT:
                    candidate = json.loads(wire)
                    validate_child(request, candidate)
                    result, status = candidate, candidate["status"]
        except subprocess.TimeoutExpired:
            status = "PROCESS_TIMEOUT"
        except (ValueError, KeyError, TypeError, OSError):
            status = "PROCESS_PROTOCOL_OR_LAUNCH_UNAVAILABLE"
    body = {
        "version": "event-source-probe-v1",
        "capture_id": uuid4().hex,
        "source": request.source,
        "source_version": ADAPTER_VERSIONS[request.source],
        "endpoint": SOURCES[request.source][0],
        "request": request.model_dump(mode="json"),
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "elapsed_ms": (perf_counter_ns() - tick) / 1_000_000,
        "status": status,
        "result": result,
        "adapter_sha256": hashlib.sha256(
            Path(__file__).with_name("adapters.py").read_bytes()
        ).hexdigest(),
        "process_attempted": True,
        "provider_attempt_confirmed": result is not None,
        "coverage_accepted": False,
        "host_accepted": False,
        "operational_evidence_published": False,
        "execution_authority": False,
        "model_calls": 0,
        "live_enabled": False,
    }
    artifact = body | {"artifact_hash": fingerprint(body)}
    fd, temporary = tempfile.mkstemp(prefix=".capture-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(artifact, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "capture.json")
        sync_directory(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return summary(artifact)


def validate_child(request, result):
    if result["request_hash"] != fingerprint(request):
        raise ValueError("Source request mismatch")
    started, received = (datetime.fromisoformat(result[k]) for k in ("started_at", "received_at"))
    if started.tzinfo is None or received.tzinfo is None or received < started:
        raise ValueError("Ordered aware source receipt clocks required")
    raw = result["raw_decoded_utf8"]
    if raw is None:
        if (
            result["status"] != "FETCH_UNAVAILABLE"
            or result["normalized"] is not None
            or result["raw_sha256"] is not None
            or not result["error_class"]
        ):
            raise ValueError("Missing raw response")
        return
    if not isinstance(raw, str) or len(raw.encode()) > MAX_RESPONSE:
        raise ValueError("Bounded decoded source text required")
    if hashlib.sha256(raw.encode()).hexdigest() != result["raw_sha256"]:
        raise ValueError("Original decoded response hash mismatch")
    if result["status"] == "PARSE_UNAVAILABLE":
        if result["normalized"] is not None or not result["error_class"]:
            raise ValueError("Failed parse cannot supply normalized evidence")
    elif result["status"] == "PARSED_PARTIAL":
        payload = result["normalized"]
        if not isinstance(payload, dict) or not payload.get("coverage") or result["error_class"]:
            raise ValueError("Normalized partial evidence required")
        for key, cls in (("events", Event), ("coverage", Coverage), ("volatility", Volatility)):
            for raw_row in payload.get(key, ()):
                row = cls.model_validate(raw_row)
                if (
                    row.source != request.source
                    or row.source_version != ADAPTER_VERSIONS[request.source]
                ):
                    raise ValueError("Normalized source identity mismatch")
                if (row.checked_at if isinstance(row, Coverage) else row.received_at) != received:
                    raise ValueError("Normalized receipt clock mismatch")
                if isinstance(row, Coverage) and row.status != "PARTIAL":
                    raise ValueError("Public-source completeness is not accepted")
    else:
        raise ValueError("Unknown child result")


def summary(artifact):
    result = artifact.get("result") or {}
    normalized = result.get("normalized") or {}
    return {
        k: artifact[k]
        for k in (
            "capture_id",
            "source",
            "status",
            "artifact_hash",
            "elapsed_ms",
            "coverage_accepted",
            "host_accepted",
            "operational_evidence_published",
            "execution_authority",
        )
    } | {
        "raw_sha256": result.get("raw_sha256"),
        "error_class": result.get("error_class"),
        "http_status": result.get("http_status"),
        "event_count": len(normalized.get("events", ())),
        "volatility_count": len(normalized.get("volatility", ())),
        "coverage": normalized.get("coverage", []),
    }


def verify(path):
    """Offline replay and integrity checks; hashes are not provider signatures."""
    artifact = json.loads(read(Path(path), MAX_ARTIFACT))
    body = {k: v for k, v in artifact.items() if k != "artifact_hash"}
    if (
        artifact["artifact_hash"] != fingerprint(body)
        or artifact["version"] != "event-source-probe-v1"
    ):
        raise ValueError("Capture integrity mismatch")
    request = ProbeRequest.model_validate(artifact["request"])
    if (
        artifact["source"] != request.source
        or artifact["source_version"] != ADAPTER_VERSIONS[request.source]
        or artifact["endpoint"] != SOURCES[request.source][0]
    ):
        raise ValueError("Capture source mismatch")
    started, finished = (datetime.fromisoformat(artifact[k]) for k in ("started_at", "finished_at"))
    if started.tzinfo is None or finished.tzinfo is None or finished < started:
        raise ValueError("Ordered aware capture clocks required")
    adapter_hash = hashlib.sha256(Path(__file__).with_name("adapters.py").read_bytes()).hexdigest()
    result = artifact["result"]
    if result is not None:
        validate_child(request, result)
        if (
            not started
            <= datetime.fromisoformat(result["started_at"])
            <= datetime.fromisoformat(result["received_at"])
            <= finished
        ):
            raise ValueError("Child receipt outside capture interval")
        if artifact["status"] != result["status"]:
            raise ValueError("Status mismatch")
        if result["raw_decoded_utf8"] is not None:
            try:
                normalized = normalize(
                    request,
                    result["raw_decoded_utf8"],
                    datetime.fromisoformat(result["received_at"]),
                )
            except Exception as exc:  # noqa: BLE001 - exact offline failure reproduction
                if (
                    result["status"] != "PARSE_UNAVAILABLE"
                    or type(exc).__name__ != result["error_class"]
                ):
                    raise ValueError("Parse outcome changed") from None
            else:
                if normalized != result["normalized"] or result["status"] != "PARSED_PARTIAL":
                    raise ValueError("Normalization changed")
    elif artifact["status"] not in {
        "PROCESS_TIMEOUT",
        "PROCESS_UNAVAILABLE",
        "PROCESS_PROTOCOL_OR_LAUNCH_UNAVAILABLE",
    }:
        raise ValueError("Missing child result")
    for key in (
        "coverage_accepted",
        "host_accepted",
        "operational_evidence_published",
        "execution_authority",
        "live_enabled",
    ):
        if artifact[key] is not False:
            raise ValueError("Capture cannot confer acceptance or authority")
    return summary(artifact) | {
        "offline_replay_verified": True,
        "provider_calls_during_replay": 0,
        "replay_adapter_sha256": adapter_hash,
        "same_adapter_implementation": artifact["adapter_sha256"] == adapter_hash,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "verify", "_child"))
    parser.add_argument("--request")
    parser.add_argument("--directory")
    parser.add_argument("--artifact")
    args = parser.parse_args(argv)
    try:
        if args.operation == "_child":
            request = ProbeRequest.model_validate_json(sys.stdin.buffer.read(16385))
            print(json.dumps(child_capture(request), sort_keys=True))
            return 0
        if args.operation == "capture":
            request = ProbeRequest.model_validate_json(read(Path(args.request), 16384))
            result = capture(args.directory, request)
        else:
            result = verify(args.artifact)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PARSED_PARTIAL" else 2
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"status": "SOURCE_PROBE_UNAVAILABLE", "execution_authority": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
