"""Accelerated samples across 22 exchange sessions on one disposable PAPER owner.

Every sample passes through feed normalization, native supervision, the original
restore fence, and publication. The synthetic clock skips unobserved intraday
polls. Wall-clock, full-cadence capacity is exercised by paper-soak.py.
"""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import time
from uuid import NAMESPACE_URL, uuid5

import pytest
from test_combined_session_feed import combined
from test_contract_catalog import captures as captures
from test_observed_profile_lifecycle import market_reader
from test_paper_session_report import module as reports
from test_robinhood_read_mapping import schemas as schemas

from app.execution import restore
from app.execution.economics import UsageEvidence
from app.mixed import connected_runtime as connected
from app.mixed import feed_rollover
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.dashboard_snapshot import DashboardPublisher
from app.mixed.observer import MixedObserver
from app.options import entry_judgment
from app.options.entry_reasoning import plan_class
from app.options.engine import fingerprint
from app.options.operator_inbox import save
from app.options.runtime_cli import initialize
from app.robinhood.schedule import XNYSCalendar


def session_policy(base, day, calendar):
    """Build synthetic contract identities from terms, without altering captured evidence."""
    instruments = []
    first_expiry = min(i.contract.expiration for i in base.candidates)
    for template in base.candidates:
        expiry = day
        if template.contract.expiration != first_expiry:
            expiry = calendar.date_to_session(day + timedelta(days=9), direction="next").date()
        term = template.contract.model_dump()
        close = calendar.session_close(str(expiry)).to_pydatetime()
        term.update(
            expiration=expiry,
            expires_at=close,
            last_trading_at=close,
            settles_at=calendar.session_open(calendar.next_session(str(expiry))).to_pydatetime(),
        )
        contract = type(template.contract).model_validate(term)
        identity = str(uuid5(NAMESPACE_URL, "offline-calendar:" + contract.contract_id))
        instruments.append(
            type(template).model_validate(
                template.model_dump() | {"instrument_id": identity, "contract": contract}
            )
        )
    return type(base).model_validate(base.model_dump() | {"candidates": instruments})


def test_calendar_month_preserves_one_fenced_owner(tmp_path, captures, schemas, monkeypatch):
    calendar = XNYSCalendar()
    exchange = calendar.calendar
    sessions = exchange.sessions_in_range("2026-10-28", "2026-11-27")
    assert len(sessions) == 22 and sessions[-1].date().isoformat() == "2026-11-27"
    settings, template = combined(captures)
    population = "offline-calendar-growth-v1"
    # The fixture's first catalog also uses synthetic IDs, so overlapping Swing
    # and DEGEN contracts keep the same identity whenever their terms match.
    base = session_policy(template, sessions[0].date(), exchange)
    base = type(base).model_validate(base.model_dump() | {"population_id": population})
    owner, collector, dashboard = (tmp_path / n for n in ("owner", "collector", "dashboard"))
    key = tmp_path / "synthetic-key"
    key.write_text("offline-never-transmitted")
    key.chmod(0o600)
    raw = settings.model_dump()
    raw["limits"]["population_id"] = population
    raw["key_file"] = str(key)
    raw["runtime"]["feed_file"] = str(collector / "feed.json")
    settings = type(settings).model_validate(raw)
    policy_file, schemas_file = tmp_path / "policy.json", tmp_path / "schemas.json"
    save(policy_file, base.model_dump(mode="json"))
    save(schemas_file, schemas.model_dump(mode="json"))
    clock = [exchange.session_open(sessions[0]).to_pydatetime() - timedelta(hours=1)]
    paced = os.environ.get("TRADE_BOT_CALENDAR_PACED") == "1"
    paced_start = None
    if paced:
        from app.options.release_identity import inspect_release

        assert os.environ.get("TRADE_BOT_CALENDAR_DENSITY") == "extended"
        assert inspect_release().status == "VERIFIED_FILES"
        assert len(os.sched_getaffinity(0)) == 1
        assert all(
            line.split(":")[0].strip() == "lo"
            for line in Path("/proc/net/dev").read_text().splitlines()[2:]
        )

    def now():
        if paced_start is not None:
            return clock[0] + timedelta(seconds=time.monotonic() - paced_start)
        return clock[0]

    initialize(owner, settings, clock=now)
    ContinuousFeed(collector, base, schemas, create=True).close()
    with connected.existing_runtime(owner, clock=now) as (initial, _):

        async def stop_initial():
            stop, ready = asyncio.Event(), asyncio.Event()
            task = asyncio.create_task(initial.run(stop, ready=ready))
            try:
                await asyncio.wait_for(ready.wait(), 20)
            finally:
                stop.set()
                await task

        asyncio.run(stop_initial())
    publisher = DashboardPublisher(
        owner, dashboard, os.getuid(), os.getgid(), create=True, clock_source=now
    )
    try:
        publisher.publish()
    finally:
        publisher.close()

    original_open = connected.existing_runtime
    normal_feed_loop = ContinuousFeed.run
    calls, observations = [], []
    entry_call = 1
    runtime = None

    async def model(request, _secret, *, broad):
        calls.append(request.packet.decision_id)
        plan = entry_judgment.hold(request.packet)
        if len(calls) == entry_call:
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
                thesis="Synthetic entry",
                uncertainty="Offline calendar fixture",
            )
        return entry_judgment.result_for(
            request,
            plan=plan,
            count=100,
            usage=UsageEvidence(
                request_id=f"calendar-{len(calls)}",
                model=settings.execution.cost_policy.model,
                input_tokens=100,
                output_tokens=20,
            ),
        )

    @contextmanager
    def opened(*args, **kwargs):
        nonlocal runtime
        with original_open(*args, **kwargs) as pair:
            runtime = pair[0]
            runtime.c._model_run = model
            yield pair

    async def forbidden(*args, **kwargs):
        pytest.fail("External transport in isolated calendar fixture")

    async def samples(
        feed, stop, *, clock_source, held_source, calendar, source_settings, **kwargs
    ):
        # Sparse real traffic at known points around start, decision, protection and close.
        for n, sample in enumerate(sample_times):
            clock[0] = sample
            result = await feed.tick(
                now=sample,
                held=held_source(),
                window=calendar.current_window(sample),
                source_settings=source_settings,
                reader=market_reader(
                    sample, feed.policy_for(sample.date()), exit_symbol="SPY" if n >= 3 else None
                ),
            )
            assert result["status"] == "DELIVERED", result
            clock[0] += timedelta(seconds=1)
            async with asyncio.timeout(30):
                while True:
                    with runtime.c.engine.journal.read() as db:
                        state = runtime._bound(db)
                        receipt = db.execute(
                            "SELECT status FROM execution_mixed_runtime_inputs WHERE sequence=?",
                            (result["sequence"],),
                        ).fetchone()
                        consumed = (
                            state["feed_sequence"] == result["sequence"]
                            and receipt is not None
                            and receipt[0] == "DELIVERED"
                        )
                        halted = runtime.c.engine._control(db)["halted"]
                    assert not runtime.entry_fault, runtime.entry_fault
                    protection_done = runtime._scope_tick is None or runtime._scope_tick.done()
                    if (
                        consumed
                        and protection_done
                        and (runtime.task is None or runtime.task.done())
                        and (n or not halted)
                    ):
                        break
                    await asyncio.sleep(0.04)
        stop.set()

    monkeypatch.setattr(connected, "existing_runtime", opened)
    monkeypatch.setattr(ContinuousFeed, "run", samples)
    monkeypatch.setattr("app.options.read_capture._collect_owned", forbidden)
    monkeypatch.setattr("app.options.entry_judgment.run_entry_process", forbidden)
    monkeypatch.setattr("app.options.position_judgment.run_position_process", forbidden)
    args = owner, collector, policy_file, schemas_file
    native_path = owner / "options.db"
    observer = MixedObserver(native_path, population, clock=now, native_journal=True)
    last_sequence = 0
    authority_id = None

    def prepare_session(label, *, rollover):
        day = label.date()
        opens = exchange.session_open(label).to_pydatetime()
        closes = exchange.session_close(label).to_pydatetime()
        clock[0] = opens - timedelta(minutes=20)
        if rollover:
            next_file = tmp_path / f"catalog-{day}.json"
            proposal = session_policy(base, day, exchange)
            save(next_file, proposal.model_dump(mode="json"))
            rollover_args = *args, next_file, day
            review = feed_rollover.review(*rollover_args, clock_source=now)[0]
            feed_rollover.apply(
                *rollover_args, expected_review=review["review_sha256"], clock_source=now
            )
        clock[0] = opens + timedelta(minutes=30)
        return day, opens, closes

    def run_worker(stop):
        check = connected.check(*args, clock_source=now)[0]
        return connected.run(
            *args,
            stop,
            clock_source=now,
            snapshot_directory=dashboard,
            reader_uid=os.getuid(),
            reader_gid=os.getgid(),
            resume_flat_reviewed_revision=check["owner_state"]["owner_revision"],
            max_feed_recoveries=0,
        )

    for number, label in enumerate(sessions):
        day, opens, closes = prepare_session(label, rollover=bool(number))
        start = clock[0]
        sample_times = [start + timedelta(seconds=s) for s in (0, 12, 24, 36, 48, 60)]
        # The larger offline capacity run samples intermediate market deliveries.
        if os.environ.get("TRADE_BOT_CALENDAR_DENSITY") == "extended":
            sample_times.extend(start + timedelta(seconds=72 + 12 * n) for n in range(72))
        sample_times = sorted(
            {*sample_times, start + timedelta(minutes=5), closes - timedelta(minutes=3)}
        )
        outcome = asyncio.run(run_worker(asyncio.Event()))
        assert outcome["status"] == "STOPPED" and outcome["dashboard_published"]
        report = reports.report(tmp_path, start.isoformat(), now().isoformat())
        assert not report["runtime_failures"] and not report["publication_failures"]
        assert report["runtime_timing"]["missing_or_invalid"] == 0
        assert report["run_execution"]["completed_round_trips"] == (1 if number == 0 else 0)
        view = observer.report(limit=100)
        assert view["accounting"] == "VERIFIED" and not view["positions"]
        with observer.read() as db:
            state = restore.status(db, restore.authority_path(native_path))
            assert state["status"] == "VERIFIED"
            authority_id = authority_id or state["authority_id"]
            assert state["authority_id"] == authority_id
            sequence = db.execute("SELECT feed_sequence FROM execution_option_runtime").fetchone()[
                0
            ]
            assert sequence == last_sequence + len(sample_times)
            last_sequence = sequence
        observations.append(
            {
                "session": str(day),
                "open": opens.isoformat(),
                "close": closes.isoformat(),
                "last_sequence": sequence,
                "round_trips": report["run_execution"]["completed_round_trips"],
                "native_bytes": native_path.stat().st_size,
                "collector_bytes": (collector / "collector.db").stat().st_size,
                "display_bytes": (dashboard / "options.db").stat().st_size,
                "restore_generation": state["generation"],
            }
        )
        if os.environ.get("TRADE_BOT_OFFLINE_PROOF"):
            path = Path(os.environ["TRADE_BOT_OFFLINE_PROOF"]) / "calendar-growth.json"
            pending = path.with_suffix(".tmp")
            pending.write_text(
                json.dumps(
                    {
                        "synthetic": True,
                        "full_cadence": False,
                        "model_calls": len(calls),
                        "samples_per_session": len(sample_times),
                        "sessions": observations,
                    },
                    indent=2,
                )
            )
            pending.replace(path)
    assert observations[0]["native_bytes"] < observations[-1]["native_bytes"]
    assert all(
        a["restore_generation"] < b["restore_generation"]
        for a, b in zip(observations, observations[1:])
    )
    assert (closes - opens).total_seconds() == 3.5 * 3600
    if not paced:
        return

    from soak_worker import cpu_sample, cpu_window, decision_coverage

    day, _, _ = prepare_session(exchange.next_session(sessions[-1]), rollover=True)
    start = clock[0]
    before_bytes = native_path.stat().st_size
    before_calls = len(calls)
    entry_call = before_calls + 1

    async def paced_feed(feed, stop, **kwargs):
        async def capture(policy, **request):
            at = now()
            exit_symbol = "SPY" if at >= start + timedelta(seconds=30) else None
            response = await market_reader(at, feed.policy_for(day), exit_symbol=exit_symbol)(
                policy, **request
            )
            await asyncio.sleep(max(0, (response.collected_at - now()).total_seconds()))
            return response

        await normal_feed_loop(feed, stop, reader=capture, **kwargs)

    monkeypatch.setattr(ContinuousFeed, "run", paced_feed)
    seconds = 335

    failure = None

    async def exercise():
        nonlocal paced_start, failure
        stop = asyncio.Event()
        worker = run_worker(stop)
        initial_cpu = cpu_sample()
        paced_start = initial_cpu[0]
        task = asyncio.create_task(worker)
        try:
            done, _ = await asyncio.wait({task}, timeout=seconds)
        finally:
            stop.set()
            try:
                outcome = await asyncio.wait_for(task, 60)
            except connected.ComponentFailure as exc:
                failure = exc
                outcome = {"status": str(exc), "dashboard_published": False}
        assert failure is not None or not done, "Worker ended before the calendar follow-up cutoff"
        return outcome, cpu_window(initial_cpu, cpu_sample(), 1)

    outcome, cpu = asyncio.run(exercise())
    end = now()
    report = reports.report(tmp_path, start.isoformat(), end.isoformat())
    with observer.read() as db:
        state = restore.status(db, restore.authority_path(native_path))
        assert state["status"] == "VERIFIED" and state["authority_id"] == authority_id
        coverage = decision_coverage(db, start, seconds)
        sequence = db.execute("SELECT feed_sequence FROM execution_option_runtime").fetchone()[0]
    view = observer.report(limit=100)
    result = {
        "synthetic": True,
        "provider_calls": False,
        "external_model_calls": False,
        "history_sessions": len(sessions),
        "retained_prior_packets": last_sequence,
        "retained_prior_model_calls": before_calls,
        "next_calendar_session": str(day),
        "duration_seconds": seconds,
        "new_packets": sequence - last_sequence,
        "model_calls": len(calls) - before_calls,
        "start_native_bytes": before_bytes,
        "final_native_bytes": native_path.stat().st_size,
        "cpu": cpu,
        "coverage": coverage,
        "decision_reason_counts": report["decision_reason_counts"],
        "prior_generation": observations[-1]["restore_generation"],
        "ending_generation": state["generation"],
        "operator_outcome": outcome["status"],
        "published": outcome["dashboard_published"],
        "execution": report["run_execution"],
        "entry_freshness": report["entry_freshness"],
        "native_accept_failures": report["runtime_timing"]["by_status"].get(
            "NATIVE_ACCEPT:FAILED", 0
        ),
        "runtime_failures": len(report["runtime_failures"]),
        "publication_failures": len(report["publication_failures"]),
        "accounting": view.get("accounting"),
        "held_positions": len(view["positions"]),
    }
    if output := os.environ.get("TRADE_BOT_OFFLINE_PROOF"):
        Path(output, "calendar-paced.json").write_text(json.dumps(result, indent=2))
    if failure is not None:
        raise failure
    assert outcome["status"] == "STOPPED" and outcome["dashboard_published"]
    assert (
        coverage["target_met"]
        and not report["runtime_failures"]
        and not report["publication_failures"]
    )
    assert view["accounting"] == "VERIFIED" and not view["positions"]
    assert (
        report["run_execution"]["completed_round_trips"] == 1
        and not result["native_accept_failures"]
    )
