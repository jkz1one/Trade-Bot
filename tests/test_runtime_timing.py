"""Correlated diagnostics preserve cancellation, original clocks and failures."""
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace

import pytest
from test_option_execution import NOW, owned
from test_paper_session_report import module as reports

from app.execution.process import FixtureProcessTimeout
from app.options import runtime_timing as timing
from app.options.process import run_option_process


@pytest.mark.parametrize("outcome", ["OPEN", "HOLD", "FAILED_SETTLEMENT"])
def test_paid_entry_local_phases_and_child_have_independent_counts(tmp_path, monkeypatch, outcome):
    from test_degen_options import AT
    from test_mixed_entry import owner
    from test_mixed_native_owner import changed
    from test_mixed_runtime import runtime
    from test_mixed_selection import stock_frame
    from test_option_runtime import step
    from pathlib import Path
    from app.options.runtime_models import PortfolioRuntimePacket

    assert set(reports.RUNTIME_PHASES) == timing.PHASES
    with owner(tmp_path, monkeypatch, choice="OPTION", portfolio=True,
               mode="ENTER" if outcome == "OPEN" else "HOLD") as (c, venue, times, _):
        r = runtime(c, tmp_path)
        if outcome == "FAILED_SETTLEMENT":
            with c.engine.journal.write() as db:
                db.execute("CREATE TRIGGER reject_usage BEFORE INSERT ON execution_events "
                           "WHEN NEW.kind='OPTION_MODEL_USAGE_RECORDED' BEGIN "
                           "SELECT RAISE(ABORT,'synthetic settlement failure'); END")
        packet = PortfolioRuntimePacket(sequence=1, kind="CYCLE", recorded_at=AT,
            population_id=c.engine.limits.population_id,
            frame=changed(stock_frame(), portfolio_version="portfolio-frame-v2"))
        path = Path(r.policy.feed_file)
        path.write_text(packet.model_dump_json())
        path.chmod(0o600)
        asyncio.run(step(r))
        asyncio.run(r.tick())
        c.engine.journal.flush_timings()  # Explicit owner boundary before inspecting final trace.
        with c.engine.journal.read() as db:
            trace = reports.runtime_timing_evidence(db, AT.isoformat(), times[0].isoformat())
        statuses = trace["by_status"]
        assert trace['trace_start_prepare']['samples'] == trace['measured']
        assert trace['trace_start_write'] is None
        assert trace['trace_storage'] == {'COALESCED': trace['measured']}
        for name in ("TICK_PACKET_VALIDATION", "TICK_NEW_RECEIPT", "TICK_REPEAT_RECEIPT",
                     "CYCLE_OPPORTUNITY_CLAIM"):
            assert statuses[name + ":COMPLETE"] >= 1
        for name in ("ENTRY_MODEL_REQUEST", "ENTRY_MODEL_ADMISSION", "ENTRY_MODEL"):
            assert statuses[name + ":COMPLETE"] == 1
        state = "FAILED" if outcome == "FAILED_SETTLEMENT" else "COMPLETE"
        settlement = "ENTRY_SETTLEMENT_AND_RESERVATION" if outcome == "OPEN" else "ENTRY_MODEL_SETTLEMENT"
        assert statuses[settlement + ":" + state] == 1
        assert statuses.get("ENTRY_PROTECTION_WAIT:COMPLETE", 0) == 0
        for name in ("ENTRY_MIXED_SELECTION", "ENTRY_OPTION_MARKET_READ", "ENTRY_REVIEW"):
            assert statuses.get(name + ":COMPLETE", 0) == int(outcome == "OPEN")
        assert trace["coverage"]["models"]["matched"] == 1
        assert trace["coverage"]["models"]["unsettled"] == int(outcome == "FAILED_SETTLEMENT")
        assert venue.submit_count == int(outcome == "OPEN")


@pytest.mark.parametrize("choice", ["DEGEN", "SCOPE"])
def test_paid_selection_timing_keeps_original_check_separate_from_refresh(tmp_path, monkeypatch, choice):
    from test_option_scope_ai import ai_owner

    trace = {"spans": [], "spans_omitted": 0, "native": [], "native_omitted": 0}
    with ai_owner(tmp_path, monkeypatch, family=choice) as (c, _, _, frame, _):
        token = timing.CURRENT.set(trace)
        try:
            result = asyncio.run(c.cycle(frame))
        finally:
            timing.CURRENT.reset(token)
    assert result["status"] == "OPEN", result
    names = [span["phase"] for span in trace["spans"]]
    assert names.count("ENTRY_SCOPE_RECEIPT_CHECK") == 1
    assert names.count("ENTRY_SCOPE_SELECTION") == 1
    assert names.count("SCOPE_REFRESH") == int(choice == "SCOPE")
    if choice == "SCOPE":
        assert names.index("ENTRY_SCOPE_RECEIPT_CHECK") < names.index("SCOPE_REFRESH")
        assert names.index("SCOPE_REFRESH") < names.index("ENTRY_SCOPE_SELECTION")


def test_regular_option_first_settled_commit_already_contains_both_choices(tmp_path, monkeypatch):
    from test_option_scope_ai import ai_owner

    with ai_owner(tmp_path, monkeypatch, family="DEGEN", portfolio=True) as (c, venue, _, frame, _):
        journal = c.engine.journal
        write = journal.write
        settled = []

        @contextmanager
        def observe_commits():
            with write() as db:
                yield db
            if not settled:
                # An independent reader can see only committed charge and choice evidence.
                with journal.read() as db:
                    row = db.execute(
                        "SELECT o.result_json FROM execution_option_opportunities o "
                        "JOIN execution_model_calls m ON m.source_key=o.cycle_key "
                        "WHERE m.cost IS NOT NULL"
                    ).fetchone()
                if row:
                    settled.append(json.loads(row[0]))

        monkeypatch.setattr(journal, "write", observe_commits)
        result = asyncio.run(c.cycle(frame))
        assert venue.submit_count == 1, result
        receipt, = settled
        candidate = receipt["entry_result"]["plan"]["candidate_id"]
        assert receipt["mixed_selection"]["selected"]["candidate_id"] == candidate
        assert receipt["scope_arbitration"]["selected"]["candidate_id"] == candidate
        assert receipt["entry_request"]["packet"]["cycle_key"] == receipt["scope_arbitration"]["cycle_key"]


def test_entry_request_and_cost_reservation_are_durable_together_before_model(tmp_path, monkeypatch):
    from test_mixed_entry import owner
    from test_mixed_selection import stock_frame

    with owner(tmp_path, monkeypatch, choice='OPTION', portfolio=True) as (c, venue, _, _):
        journal, observations = c.engine.journal, []
        writer, model = journal.write, c._model_run

        def admitted():
            with journal.read() as db:
                for row in db.execute('SELECT cycle_key,result_json FROM execution_option_opportunities'):
                    evidence = json.loads(row['result_json'] or '{}')
                    if 'entry_request' in evidence:
                        call = db.execute('SELECT packet_hash FROM execution_model_calls WHERE source_key=?',
                                          (row['cycle_key'],)).fetchone()
                        return bool(call and call[0] == evidence['model_input_hash'])
            return None

        @contextmanager
        def observe():
            with writer() as db:
                yield db
            if not observations and (value := admitted()) is not None:
                observations.append(value)

        async def checked(*args, **kwargs):
            assert admitted() is True
            return await model(*args, **kwargs)

        monkeypatch.setattr(journal, 'write', observe)
        monkeypatch.setattr(c, '_model_run', checked)
        result = asyncio.run(c.cycle(stock_frame()))
        assert observations == [True] and venue.submit_count == 1, result


def test_failed_cost_reservation_retains_request_but_never_calls_model(tmp_path, monkeypatch):
    from app.execution.engine import ExecutionBlocked
    from test_mixed_entry import owner
    from test_mixed_selection import stock_frame

    with owner(tmp_path, monkeypatch, choice='OPTION', portfolio=True) as (c, venue, _, _):
        admitted = c.engine._admit_model_attempt

        def failed(*args):
            admitted(*args)
            raise ExecutionBlocked('synthetic admission rollback')

        async def forbidden(*args, **kwargs):
            pytest.fail('Model ran without a committed budget reservation')

        monkeypatch.setattr(c.engine, '_admit_model_attempt', failed)
        monkeypatch.setattr(c, '_model_run', forbidden)
        result = asyncio.run(c.cycle(stock_frame()))
        assert result['entries'][0]['status'] == 'HOLD', result
        assert venue.submit_count == 0
        with c.engine.journal.read(verify_restore=True) as db:
            evidence = json.loads(db.execute('SELECT result_json FROM execution_option_opportunities').fetchone()[0])
            assert evidence['entry_request'] and evidence['blocker'] == 'synthetic admission rollback'
            assert db.execute('SELECT COUNT(*) FROM execution_model_calls').fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM execution_events WHERE kind='OPTION_MODEL_ATTEMPT_ADMITTED'").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["receipt", "write"])
def test_unusable_option_choice_preserves_exact_charge_and_raw_reply(tmp_path, monkeypatch, failure):
    from test_option_scope_ai import ai_owner
    from app.execution.engine import ExecutionBlocked
    from app.options import scope_ai

    with ai_owner(tmp_path, monkeypatch, family="DEGEN") as (c, venue, _, frame, _):
        if failure == "receipt":
            def reject(*args):
                raise ExecutionBlocked("REJECTED_SELECTION_RECEIPT")

            monkeypatch.setattr(scope_ai, "validate_stored", reject)
        else:
            with c.engine.journal.write() as db:
                db.execute(
                    "CREATE TRIGGER reject_choice BEFORE UPDATE OF result_json "
                    "ON execution_option_opportunities WHEN "
                    "json_extract(NEW.result_json,'$.scope_arbitration.selected') IS NOT NULL "
                    "BEGIN SELECT RAISE(ABORT,'rejected choice'); END"
                )
        result = asyncio.run(c.cycle(frame))
        assert result["status"] == "HOLD" and venue.submit_count == 0, result
        assert result["entry_timely"] and result["entry_result"]["plan"]["action"] == "ENTER"
        assert "scope_arbitration" not in result or result["scope_arbitration"]["selected"] is None
        with c.engine.journal.read() as db:
            call, = db.execute("SELECT cost,usage_json FROM execution_model_calls")
            assert call["cost"] is not None
            assert json.loads(call["usage_json"]) == result["entry_result"]["usage"]
            assert db.execute(
                "SELECT COUNT(*) FROM execution_events WHERE kind='OPTION_MODEL_USAGE_RECORDED'"
            ).fetchone()[0] == 1
        assert asyncio.run(c.cycle(frame)) == result and venue.submit_count == 0


def test_native_ack_received_before_unrelated_interpreter_teardown(tmp_path, monkeypatch):
    import sys
    import time
    from test_mixed_entry import owner
    from test_mixed_selection import stock_frame
    from app.mixed import portfolio_execution

    spawn, native = asyncio.create_subprocess_exec, portfolio_execution.run_option_process
    program = (
        "import atexit,runpy,time;"
        "atexit.register(time.sleep,5);"
        "runpy.run_module('app.options.worker',run_name='__main__')"
    )

    async def slow_teardown(*args, **kwargs):
        if args[-1] == "app.options.worker":
            assert args == (sys.executable, "-I", "-m", "app.options.worker")
            args = (sys.executable, "-I", "-c", program)
        return await spawn(*args, **kwargs)

    async def bounded(venue, **request):
        request["deadline"] = min(request["deadline"], time.monotonic() + 2)
        return await native(venue, **request)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_teardown)
    monkeypatch.setattr(portfolio_execution, "run_option_process", bounded)
    with owner(tmp_path, monkeypatch, choice="OPTION", portfolio=True) as (c, venue, _, _):
        result = asyncio.run(c.cycle(stock_frame()))
        assert venue.submit_count == 1
        assert result["entries"][0]["status"] == "OPEN"


def test_portfolio_ack_is_validated_while_owner_loop_is_occupied(tmp_path, monkeypatch):
    import threading
    from test_mixed_entry import owner
    from test_mixed_selection import stock_frame
    from app.options import process

    entered, validated = threading.Event(), threading.Event()
    observed = []
    transport = process._run_option_process

    async def exercise(c):
        owner_loop = asyncio.get_running_loop()

        def busy_tick():
            entered.set()
            observed.append(validated.wait(2))

        async def accept(venue, **request):
            if request.get("intent") is None:
                return await transport(venue, **request)
            owner_loop.call_soon_threadsafe(busy_tick)
            assert await asyncio.to_thread(entered.wait, 1)
            result = await transport(venue, **request)
            validated.set()
            return result

        monkeypatch.setattr(process, "_run_option_process", accept)
        return await c.cycle(stock_frame())

    with owner(tmp_path, monkeypatch, choice="OPTION", portfolio=True) as (c, venue, _, _):
        result = asyncio.run(exercise(c))
        assert observed == [True]
        assert result["entries"][0]["status"] == "OPEN" and venue.submit_count == 1


@pytest.mark.parametrize("accepted", [False, True])
def test_cancelled_portfolio_handoff_reaps_the_native_child(tmp_path, monkeypatch, accepted):
    from test_mixed_entry import owner
    from test_mixed_selection import stock_frame

    children = []
    spawn = asyncio.create_subprocess_exec

    async def observe(*args, **kwargs):
        child = await spawn(*args, **kwargs)
        if args[-1] == "app.options.worker":
            children.append(child)
        return child

    async def exercise(c, venue):
        task = asyncio.create_task(c.cycle(stock_frame()))
        async with asyncio.timeout(6):
            while not children or (accepted and venue.submit_count == 0):
                await asyncio.sleep(.01)
        task.cancel()
        if accepted:
            await asyncio.sleep(.02)
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe)
    with owner(tmp_path, monkeypatch, choice="OPTION", portfolio=True) as (c, venue, _, _):
        venue.fault = "IGNORE_TERM_AFTER_ACCEPT" if accepted else "STALL_BEFORE_ACCEPT"
        asyncio.run(exercise(c, venue))
        assert len(children) == 1 and children[0].returncode is not None
        assert venue.submit_count == int(accepted)
        with c.engine.journal.read() as db:
            assert db.execute("SELECT status FROM execution_portfolio_orders").fetchone()[0] == "UNKNOWN"
            assert db.execute("SELECT halted FROM execution_control").fetchone()[0]


def test_native_queue_time_consumes_original_portfolio_deadline(tmp_path, monkeypatch):
    import time
    from test_mixed_entry import owner
    from test_mixed_selection import stock_frame
    from app.mixed import portfolio_execution
    from app.options import process

    deadlines, children = [], []
    native, spawn = process._run_option_process, process._spawn_option_child

    async def short_lease(venue, **request):
        request["deadline"] = min(request["deadline"], time.monotonic() + .05)
        deadlines.append(request["deadline"])
        return await process.run_option_process(venue, **request)

    async def queued(venue, **request):
        if request.get("intent") is not None:
            assert request["deadline"] == deadlines[-1]
            await asyncio.sleep(max(0, request["deadline"] - time.monotonic()) + .01)
        return await native(venue, **request)

    async def observed(module, *args):
        if module == "app.options.worker":
            children.append(module)
        return await spawn(module, *args)

    monkeypatch.setattr(portfolio_execution, "run_option_process", short_lease)
    monkeypatch.setattr(process, "_run_option_process", queued)
    monkeypatch.setattr(process, "_spawn_option_child", observed)
    with owner(tmp_path, monkeypatch, choice="OPTION", portfolio=True) as (c, venue, _, _):
        result = asyncio.run(c.cycle(stock_frame()))
        assert len(deadlines) == 1 and not children and venue.submit_count == 0
        assert result["entries"][0]["status"] == "REJECTED"
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT halted FROM execution_control").fetchone()[0]


def test_cancelled_queued_portfolio_accept_never_starts_transport(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.options import process

    release = Event()
    called = []

    class DelayedExecutor(ThreadPoolExecutor):
        def submit(self, function, *args, **kwargs):
            def delayed():
                release.wait(5)
                return function(*args, **kwargs)
            return super().submit(delayed)

    async def transport(*args, **kwargs):
        called.append(True)

    async def exercise():
        task = asyncio.create_task(process._isolated_accept(None))
        try:
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    monkeypatch.setattr(process, "ThreadPoolExecutor", DelayedExecutor)
    monkeypatch.setattr(process, "_run_option_process", transport)
    asyncio.run(exercise())
    assert not called


def test_portfolio_handoff_runs_with_default_executor_fully_occupied(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.options import process

    release = Event()
    async def transport(*args, **kwargs):
        return "observed"

    async def exercise():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        busy = loop.run_in_executor(None, release.wait, 5)
        try:
            assert await asyncio.wait_for(process._isolated_accept(None), 1) == "observed"
        finally:
            release.set()
            await busy

    monkeypatch.setattr(process, "_run_option_process", transport)
    asyncio.run(exercise())


def test_native_success_timeout_and_cancellation_keep_separate_spans_and_reap(tmp_path, monkeypatch):
    children = []
    spawn = asyncio.create_subprocess_exec
    async def watch(*args, **kwargs):
        child = await spawn(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', watch)
    trace = {'spans': [], 'native': [], 'spans_omitted': 0}
    async def exercise(venue):
        token = timing.CURRENT.set(trace)
        try:
            await run_option_process(venue, now=NOW, timeout_seconds=2)
            venue.fault = 'STALL_READ'
            with pytest.raises(FixtureProcessTimeout):
                await run_option_process(venue, now=NOW, timeout_seconds=.4)
            task = asyncio.create_task(run_option_process(venue, now=NOW, timeout_seconds=2))
            while len(children) < 3:
                await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            timing.CURRENT.reset(token)
    with owned(tmp_path) as (_, venue, _):
        before = venue.path.read_bytes()
        asyncio.run(exercise(venue))
        assert venue.path.read_bytes() == before
    calls = [s for s in trace['spans'] if s['phase'] == 'NATIVE_SNAPSHOT']
    assert [s['status'] for s in calls] == ['COMPLETE', 'FAILED', 'INTERRUPTED']
    spawns = [s for s in trace['spans'] if s['phase'] == 'NATIVE_SNAPSHOT_SPAWN']
    assert len(spawns) == 3
    for span, limit in zip(spawns, (2, .4, 2), strict=True):
        assert 0 < span['remaining_at_start_seconds'] <= limit
    assert len(trace['native']) == 3
    assert all(child.returncode is not None for child in children)
    assert str(tmp_path) not in json.dumps(trace)



def test_already_finished_native_snapshot_retains_completed_stages(tmp_path, monkeypatch):
    spawn = asyncio.create_subprocess_exec

    async def finished(*args, **kwargs):
        child = await spawn(*args, **kwargs)
        # The preloaded request can finish while the parent's event loop is busy.
        await child.wait()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", finished)
    trace = {"spans": [], "native": [], "spans_omitted": 0}
    with owned(tmp_path) as (_, venue, _):
        token = timing.CURRENT.set(trace)
        try:
            result = asyncio.run(run_option_process(venue, now=NOW, timeout_seconds=2))
        finally:
            timing.CURRENT.reset(token)
        assert result.snapshot == venue.snapshot(NOW)
    (native,) = trace["native"]
    assert native["parent_phase"] == "RESPONSE_VALIDATE"
    assert native["child_trace_status"] == "OBSERVED"
    assert [item["stage"] for item in native["child_stages"]] == [
        "REQUEST", "VENUE_OPEN", "SNAPSHOT", "SERIALIZE", "COMPLETE",
    ]


@contextmanager
def runtime(db):
    @contextmanager
    def write():
        yield db
    yield SimpleNamespace(c=SimpleNamespace(now=lambda: NOW, engine=SimpleNamespace(
        journal=SimpleNamespace(write=write))), _bound=lambda _: {'generation': 7})


def test_cycle_context_isolated_from_concurrent_protection_and_original_clocks():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    async def exercise(r):
        waiting, release = asyncio.Event(), asyncio.Event()
        async def cycle():
            with timing.root(r, 'CYCLE', slot=123):
                with timing.phase('ENTRY_MODEL'):
                    waiting.set()
                    await release.wait()
        with timing.root(r, 'TICK'):
            task = asyncio.create_task(cycle())
            await waiting.wait()
            with timing.phase('DISPATCH', now=NOW, quote=SimpleNamespace(
                    source_at=NOW-timedelta(seconds=3), received_at=NOW-timedelta(seconds=2))):
                pass
            release.set()
            await task
    with runtime(db) as r:
        asyncio.run(exercise(r))
    records = [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM execution_runtime_timings ORDER BY id')]
    assert [s['phase'] for s in records[0]['spans']] == ['DISPATCH']
    assert [s['phase'] for s in records[1]['spans']] == ['ENTRY_MODEL']
    span = records[0]['spans'][0]
    assert (span['quote_age_seconds'], span['receive_lag_seconds'], span['local_age_seconds']) == (3, 1, 2)
    assert timing.CURRENT.get() is None
    measured = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
    assert measured["quote_age_by_phase"] == {"TICK:DISPATCH": {
        "samples": 1, "p50_seconds": 3, "p95_seconds": 3, "p99_seconds": 3, "max_seconds": 3,
    }}
    db.close()


def test_report_counts_unfinished_corrupt_omitted_and_failed_without_private_fields():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    with runtime(db) as r:
        with pytest.raises(ValueError):
            with timing.root(r, 'TICK'):
                with timing.phase('NATIVE_SNAPSHOT'):
                    raise ValueError('PRIVATE')
    good = db.execute('SELECT payload_json FROM execution_runtime_timings').fetchone()[0]
    for i in range(20002):
        raw = json.loads(good)
        raw['private'] = 'PRIVATE'
        if i == 20000:
            raw['status'] = 'RUNNING'
        if i == 20001:
            raw['elapsed_seconds'] = float('nan')
        db.execute('INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)', (NOW.isoformat(), json.dumps(raw)))
    result = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
    assert (result['records'], result['omitted'], result['measured'], result['missing_or_invalid']) == (20003, 3, 19998, 2)
    assert result['by_status']['TICK:FAILED'] == 19998
    assert 'PRIVATE' not in json.dumps(result)
    assert len(result['recent']) == 25
    db.close()


def test_diagnostic_storage_failure_does_not_interrupt_protection():
    @contextmanager
    def broken():
        raise sqlite3.OperationalError('unavailable diagnostic storage')
        yield
    r = SimpleNamespace(c=SimpleNamespace(now=lambda: NOW, engine=SimpleNamespace(
        journal=SimpleNamespace(write=broken))))
    with timing.root(r, 'TICK'):
        with timing.phase('PROTECTION'):
            assert timing.CURRENT.get() is not None
    assert timing.CURRENT.get() is None


def test_native_commitments_remain_counted_before_any_trace_and_after_unfinished_trace():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE execution_option_runtime_slots(slot INTEGER, status TEXT, started_at TEXT)')
    db.execute('CREATE TABLE execution_model_calls(source_key TEXT, started_at TEXT, cost TEXT)')
    at = NOW.isoformat()
    db.executemany('INSERT INTO execution_option_runtime_slots VALUES(?,?,?)',
        [(1, 'COMPLETE', at), (2, 'INTERRUPTED', at), (3, 'STARTED', at),
         (4, 'SKIPPED', at), (5, 'WAITING_FOR_FEED', at)])
    db.executemany('INSERT INTO execution_model_calls VALUES(?,?,?)',
                   [('settled', at, '.01'), ('unknown', at, None)])
    missing = reports.runtime_timing_evidence(db, at, at)['coverage']
    assert missing['cycles']['committed'] == missing['cycles']['without_matched_trace'] == 3
    assert missing['models']['committed'] == missing['models']['without_matched_trace'] == 2
    with runtime(db) as r:
        r._scheduler_delay = .25
        with timing.root(r, 'TICK'):
            timing.CURRENT.get()['native_omitted'] = 2
        with timing.root(r, 'CYCLE', slot=1):
            with timing.phase('ENTRY_MODEL', model_source_key='settled'):
                pass
        with timing.root(r, 'CYCLE', slot=3):
            with timing.phase('STOCK_MANAGEMENT_MODEL', model_source_key='unknown'):
                pass
    # The native attempt survived; its diagnostic update did not.
    db.execute("UPDATE execution_runtime_timings SET payload_json=json_set(payload_json,'$.status','RUNNING') WHERE id=3")
    result = reports.runtime_timing_evidence(db, at, at)
    assert result['coverage']['cycles']['matched'] == result['coverage']['models']['matched'] == 1
    assert result['coverage']['cycles']['without_matched_trace'] == 2
    assert result['coverage']['cycles']['not_started'] == 2
    assert result['coverage']['models']['without_matched_trace'] == result['coverage']['models']['unsettled'] == 1
    assert result['scheduler_delay']['max_seconds'] == .25 and result['native_omitted'] == 2
    assert result['missing_or_invalid'] == 1
    assert 'settled' not in json.dumps(result['recent'])
    db.close()


@pytest.mark.parametrize('after_trace_start', [False, True])
def test_real_process_exit_keeps_native_attempt_denominators(tmp_path, after_trace_start):
    import subprocess
    import sys
    path = tmp_path / 'crashed.db'
    program = '''
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
import os,sqlite3,sys
from app.options.runtime_timing import root
db=sqlite3.connect(sys.argv[1])
at=datetime.fromisoformat(sys.argv[2])
db.execute('CREATE TABLE execution_option_runtime_slots(slot INTEGER,status TEXT,started_at TEXT)')
db.execute('CREATE TABLE execution_model_calls(source_key TEXT,started_at TEXT,cost TEXT)')
db.execute("INSERT INTO execution_option_runtime_slots VALUES(1,'STARTED',?)",(at.isoformat(),))
db.execute("INSERT INTO execution_model_calls VALUES('committed-call',?,NULL)",(at.isoformat(),))
db.commit()
@contextmanager
def write():
    with db:
        yield db
r=SimpleNamespace(c=SimpleNamespace(now=lambda:at,engine=SimpleNamespace(journal=SimpleNamespace(write=write))),_bound=lambda _: {'generation':1})
if sys.argv[3]=='False':
    os._exit(17)
with root(r,'CYCLE',slot=1):
    os._exit(17)
'''
    result = subprocess.run([sys.executable, '-I', '-W', 'error', '-c', program,
        str(path), NOW.isoformat(), str(after_trace_start)], timeout=10, capture_output=True)
    assert result.returncode == 17, result.stderr.decode()
    db = reports.connection(path)
    try:
        result = reports.runtime_timing_evidence(db, NOW.isoformat(), NOW.isoformat())
        for name in ('cycles', 'models'):
            assert result['coverage'][name]['committed'] == result['coverage'][name]['without_matched_trace'] == 1
        assert result['coverage']['models']['unsettled'] == 1
        assert result['records'] == result['missing_or_invalid'] == int(after_trace_start)
        assert result['measured'] == 0
    finally:
        db.close()
