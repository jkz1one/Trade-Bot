"""Disposable sustained PAPER fixture; only external market/advice are synthetic."""

import asyncio
import json
import os
import resource
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_combined_session_feed import combined
from test_contract_catalog import captures
from test_observed_profile_lifecycle import market_reader
from test_option_observer import PASSWORD
from test_paper_session_report import module as reports
from test_robinhood_read_mapping import schemas

from app.execution.economics import UsageEvidence
from app.mixed import connected_runtime as connected
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.dashboard_reader import create_app
from app.mixed.dashboard_snapshot import DashboardPublisher
from app.options import entry_judgment, position_judgment
from app.options.engine import fingerprint
from app.options.entry_reasoning import plan_class
from app.options.runtime_cli import initialize

NOMINAL_SECONDS = 21480  # 10:00 to 16:00, less the daily launcher's 120s cushion.
BASE = datetime(2026, 10, 28, 14, tzinfo=UTC)


def save(path, value):
    temporary = path.with_suffix(".pending")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def tree_sample(root):
    """Sample this process and descendants, not unrelated host processes."""
    processes = {}
    for item in Path("/proc").iterdir():
        if not item.name.isdigit():
            continue
        try:
            fields = (item / "stat").read_text().rsplit(")", 1)[1].split()
            processes[int(item.name)] = (
                int(fields[1]),
                int(fields[21]),
                int(fields[11]) + int(fields[12]),
            )
        except (OSError, ValueError, IndexError):
            continue
    owned = {root}
    while True:
        found = {pid for pid, (parent, _, _) in processes.items() if parent in owned}
        if found <= owned:
            break
        owned.update(found)
    return {
        "processes": len(owned),
        "rss_bytes": sum(processes[p][1] for p in owned if p in processes)
        * os.sysconf("SC_PAGE_SIZE"),
        "cpu_seconds": sum(processes[p][2] for p in owned if p in processes)
        / os.sysconf("SC_CLK_TCK"),
    }


def seed_capacity(journal, mib):
    """Labeled diagnostic padding, not fabricated measured or accounting history."""
    if not mib:
        return 0
    payload = json.dumps({"version": "synthetic-capacity-padding-v1", "padding": "x" * 32768})
    # Even disposable diagnostic writes must advance the original restore fence.
    with journal.write() as db:
        before = db.execute("SELECT COUNT(*) FROM execution_runtime_timings").fetchone()[0]
        for _ in range((mib * 1024 * 1024) // len(payload.encode()) + 1):
            db.execute(
                "INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)",
                ((BASE - timedelta(days=1)).isoformat(), payload),
            )
        return db.execute("SELECT COUNT(*) FROM execution_runtime_timings").fetchone()[0] - before


def run(output, seconds, seed_mib):
    from types import SimpleNamespace

    from app.options import engine as engine_module

    settings, policy = combined(captures.__wrapped__())
    schema = schemas.__wrapped__(SimpleNamespace())
    owner, collector, dashboard = (output / p for p in ("owner", "collector", "dashboard"))
    key, password = output / "synthetic-key", output / "password"
    for path, value in ((key, "offline-never-transmitted"), (password, PASSWORD)):
        path.write_text(value)
        path.chmod(0o600)
    raw = settings.model_dump()
    raw["limits"]["population_id"] = "offline-duration-capacity-v1"
    raw["key_file"] = str(key)
    raw["runtime"]["feed_file"] = str(collector / "feed.json")
    settings = type(settings).model_validate(raw)
    policy = type(policy).model_validate(
        policy.model_dump() | {"population_id": settings.limits.population_id}
    )
    now = [BASE - timedelta(minutes=5)]
    clock = lambda: now[0]
    initialize(owner, settings, clock=clock)
    ContinuousFeed(collector, policy, schema, create=True).close()
    policy_file, schema_file = output / "policy.json", output / "schemas.json"
    for path, value in ((policy_file, policy), (schema_file, schema)):
        path.write_text(value.model_dump_json())
        path.chmod(0o600)
    with connected.existing_runtime(owner, clock=clock) as (initial, _):

        async def prepare():
            stop, ready = asyncio.Event(), asyncio.Event()
            task = asyncio.create_task(initial.run(stop, ready=ready))
            await asyncio.wait_for(ready.wait(), 15)
            stop.set()
            await task

        asyncio.run(prepare())
        seed_rows = seed_capacity(initial.c.engine.journal, seed_mib)
    initial_bytes = (owner / "options.db").stat().st_size
    now[0] = BASE
    publisher = DashboardPublisher(
        owner, dashboard, os.getuid(), os.getgid(), create=True, clock_source=clock
    )
    try:
        publisher.publish()
        binding = publisher.binding
    finally:
        publisher.close()

    metrics = {
        "version": "paper-soak-result-v1",
        "status": "RUNNING",
        "synthetic": True,
        "provider_calls": False,
        "model_service_calls": False,
        "live_enabled": False,
        "planned_seconds": seconds,
        "nominal_worker_seconds": NOMINAL_SECONDS,
        "wall_clock_full_duration": "PENDING" if seconds >= NOMINAL_SECONDS else "NOT_REQUESTED",
        "source_seed": {
            "kind": "labeled diagnostic padding, not month-history proof",
            "rows": seed_rows,
            "initial_database_bytes": initial_bytes,
        },
        "memory_enforcement": "sampled aggregate RSS ceiling; not a kernel cgroup",
        "memory_limit_bytes": 1024**3,
        "logical_cpus": len(os.sched_getaffinity(0)),
        "native_snapshot_calls": 0,
        "native_snapshot_failures": 0,
        "native_snapshot_max_seconds": 0,
        "capture_attempts": 0,
        "entry_model_calls": 0,
        "management_model_calls": 0,
        "dashboard_reads": 0,
        "report_reads": 0,
        "peak_tree_rss_bytes": 0,
        "peak_processes": 0,
        "children_reaped_count": 0,
    }
    save(output / "progress.json", metrics)
    children, native_times = [], []
    original_open, original_loop = connected.existing_runtime, ContinuousFeed.run
    native_read, spawn = engine_module.run_option_process, asyncio.create_subprocess_exec
    started = [None]

    def live_clock():
        return (
            BASE + timedelta(seconds=time.monotonic() - started[0])
            if started[0] is not None
            else now[0]
        )

    async def forbidden(*args, **kwargs):
        raise AssertionError("External transport forbidden in disposable soak")

    async def tracked_spawn(*args, **kwargs):
        child = await spawn(*args, **kwargs)
        children.append(child)
        return child

    async def measured_native(*args, **kwargs):
        before = time.monotonic()
        metrics["native_snapshot_calls"] += 1
        try:
            return await native_read(*args, **kwargs)
        except BaseException:
            metrics["native_snapshot_failures"] += 1
            raise
        finally:
            elapsed = time.monotonic() - before
            native_times.append(elapsed)
            metrics["native_snapshot_max_seconds"] = max(
                metrics["native_snapshot_max_seconds"], elapsed
            )

    async def model(request, _secret, *, broad):
        metrics["entry_model_calls"] += 1
        if metrics["entry_model_calls"] > 1:
            plan = entry_judgment.hold(request.packet)
        else:
            item = request.packet.opportunities[0]
            stop = item.candidate.proposal.underlying_invalidation
            anchor = item.underlying.ask
            plan = plan_class(request.packet.policy)(
                decision_id=request.packet.decision_id,
                packet_hash=fingerprint(request.packet),
                action="ENTER",
                stock=False,
                scope=False,
                candidate_id=item.candidate.candidate_id,
                condition="NOW",
                underlying_invalidation=stop,
                underlying_target=anchor + 2 * (anchor - stop),
                horizon_seconds=600,
                evidence_ids=item.evidence_ids,
                thesis="Synthetic soak entry",
                uncertainty="Offline fixture",
            )
        return entry_judgment.result_for(
            request,
            plan=plan,
            count=100,
            usage=UsageEvidence(
                request_id="soak-entry-" + str(metrics["entry_model_calls"]),
                model=request.configuration.costs.model,
                input_tokens=100,
                output_tokens=20,
            ),
        )

    async def management(request, _secret):
        metrics["management_model_calls"] += 1
        return position_judgment.result_for(
            request,
            plan=position_judgment.maintain(request.packet),
            count=100,
            usage=UsageEvidence(
                request_id="soak-management-" + str(metrics["management_model_calls"]),
                model=request.configuration.costs.model,
                input_tokens=100,
                output_tokens=20,
            ),
        )

    @contextmanager
    def opened(*args, **kwargs):
        with original_open(*args, **kwargs) as pair:
            pair[0].c._model_run = model
            yield pair

    async def collect(self, stop, **kwargs):
        async def capture(capture_policy, **request):
            at = live_clock()
            metrics["capture_attempts"] += 1
            response = await market_reader(
                at, policy, exit_symbol="SPY" if (at - BASE).total_seconds() >= 30 else None
            )(capture_policy, **request)
            # Real elapsed time, never advance the runtime clock to fit a response.
            await asyncio.sleep(max(0, (response.collected_at - live_clock()).total_seconds()))
            return response

        await original_loop(self, stop, **kwargs, reader=capture)

    async def exercise():
        stop = asyncio.Event()
        args = owner, collector, policy_file, schema_file
        revision = connected.check(*args, clock_source=live_clock)[0]["owner_state"][
            "owner_revision"
        ]
        started[0] = time.monotonic()
        task = asyncio.create_task(
            connected.run(
                *args,
                stop,
                clock_source=live_clock,
                snapshot_directory=dashboard,
                reader_uid=os.getuid(),
                reader_gid=os.getgid(),
                resume_flat_reviewed_revision=revision,
                max_feed_recoveries=0,
            )
        )
        app = create_app(
            dashboard, binding, str(password), clock_source=live_clock, allow_degraded=True
        )

        def inspect():
            with TestClient(app) as client:
                client.auth = ("trader", PASSWORD)
                response = client.get("/api/mixed")
                if response.status_code != 200:
                    raise ValueError("SOAK_DASHBOARD_UNAVAILABLE")
                if response.json().get("accounting") != "VERIFIED":
                    raise ValueError("SOAK_ACCOUNTING_UNVERIFIED")
            return reports.report(output, BASE.isoformat(), live_clock().isoformat())

        next_report = 5
        try:
            while time.monotonic() - started[0] < seconds:
                if task.done():
                    await task
                    raise ValueError("SOAK_WORKER_STOPPED_EARLY")
                sample = tree_sample(os.getpid())
                metrics["children_reaped_count"] += sum(
                    child.returncode is not None for child in children
                )
                children[:] = [child for child in children if child.returncode is None]
                metrics["peak_tree_rss_bytes"] = max(
                    metrics["peak_tree_rss_bytes"], sample["rss_bytes"]
                )
                metrics["peak_processes"] = max(metrics["peak_processes"], sample["processes"])
                if sample["rss_bytes"] > metrics["memory_limit_bytes"]:
                    raise ValueError("SOAK_MEMORY_CEILING_EXCEEDED")
                elapsed = time.monotonic() - started[0]
                metrics["elapsed_seconds"] = elapsed
                metrics["source_database_bytes"] = (owner / "options.db").stat().st_size
                if elapsed >= next_report:
                    report = await asyncio.to_thread(inspect)
                    metrics["dashboard_reads"] += 1
                    metrics["report_reads"] += 1
                    save(output / "latest-report.json", report)
                    next_report = elapsed + 30
                save(output / "progress.json", metrics)
                await asyncio.sleep(min(1, max(0, seconds - (time.monotonic() - started[0]))))
        finally:
            stop.set()
            await asyncio.wait_for(task, 60)
        metrics["elapsed_seconds"] = time.monotonic() - started[0]
        final = await asyncio.to_thread(
            reports.report, output, BASE.isoformat(), live_clock().isoformat()
        )
        save(output / "report.json", final)
        assert not any(child.returncode is None for child in children), "Unreaped native child"
        assert not metrics["native_snapshot_failures"], "Native snapshot deadline/read failure"
        assert not final["runtime_failures"], "Runtime failure"
        assert not final["publication_failures"], "Publication failure"
        assert final["run_execution"]["completed_round_trips"] >= 1, (
            "Known fixture lifecycle did not complete"
        )
        assert final["runtime_timing"]["missing_or_invalid"] == 0
        assert final["collection_timing"]["missing_or_invalid"] == 0
        assert not final["collection_timing"]["by_status"].get("FAILED"), "Capture failures"
        metrics["execution"] = final["run_execution"]
        from app.mixed.observer import MixedObserver

        view = MixedObserver(
            owner / "options.db",
            settings.limits.population_id,
            clock=live_clock,
            native_journal=True,
        ).report(limit=100)
        assert view["accounting"] == "VERIFIED" and not view["positions"], (
            "Final account not verified flat"
        )
        metrics["final_accounting"] = "VERIFIED_FLAT"
        metrics["runtime_timing"] = final["runtime_timing"]
        metrics["source_growth_bytes"] = (owner / "options.db").stat().st_size - initial_bytes
        metrics["projected_22_sessions_growth_bytes"] = round(
            max(0, metrics["source_growth_bytes"]) * NOMINAL_SECONDS / seconds * 22
        )
        metrics["projection_note"] = "Linear extrapolation only, not a month-growth pass"
        metrics["native_snapshot_p99_seconds"] = sorted(native_times)[
            max(0, __import__("math").ceil(len(native_times) * 0.99) - 1)
        ]
        metrics["native_deadline_seconds"] = settings.execution.process_timeout_seconds
        metrics["native_headroom_target_met"] = (
            metrics["native_snapshot_p99_seconds"] < settings.execution.process_timeout_seconds / 2
        )

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(connected, "existing_runtime", opened)
            patch.setattr(ContinuousFeed, "run", collect)
            patch.setattr(engine_module, "run_option_process", measured_native)
            patch.setattr(asyncio, "create_subprocess_exec", tracked_spawn)
            patch.setattr("app.options.read_capture._collect_owned", forbidden)
            patch.setattr(entry_judgment, "run_entry_process", forbidden)
            patch.setattr(position_judgment, "run_position_process", management)
            asyncio.run(exercise())
        metrics["status"] = "PASSED"
        metrics["wall_clock_full_duration"] = (
            "OBSERVED" if seconds >= NOMINAL_SECONDS else "NOT_RUN"
        )
    except BaseException as exc:
        metrics.update(status="FAILED", failure_class=type(exc).__name__, failure=str(exc)[:200])
        raise
    finally:
        metrics["cpu_user_seconds"] = resource.getrusage(resource.RUSAGE_SELF).ru_utime
        metrics["cpu_system_seconds"] = resource.getrusage(resource.RUSAGE_SELF).ru_stime
        metrics["children_reaped"] = all(child.returncode is not None for child in children)
        save(output / "progress.json", metrics)
    return metrics
