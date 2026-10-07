import asyncio
import ctypes
import io
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx2
import pytest
from openai import OpenAI

from app.domain.models import Action
from app.execution import judgment
from app.execution.economics import CostAccounting, UsageEvidence
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.judgment import (
    JudgmentCoordinator,
    JudgmentLimits,
    JudgmentRequest,
    JudgmentResult,
    configuration,
)
from app.execution.judgment_worker import perform
from tests.test_execution_economics import context
from tests.test_execution_rehearsal import NOW, decision, packet


def setup(tmp_path, *, limits=None, policy=None):
    engine, venue, settings, costs = context(tmp_path, policy=policy)
    coordinator = JudgmentCoordinator(costs, limits or JudgmentLimits())
    request = JudgmentRequest(
        model=costs.policy.model,
        packet=packet(),
        limits=coordinator.limits,
        configuration=configuration(costs, coordinator.limits),
        deadline_monotonic=time.monotonic() + 30,
        parent_pid=os.getpid(),
    )
    return engine, venue, settings, costs, coordinator, request


def response(**updates):
    output = [
        {
            "type": "message",
            "id": "msg-1",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": decision().model_dump_json(), "annotations": []}
            ],
        }
    ]
    result = {
        "id": "resp-test",
        "model": "gpt-6-luna",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "output": output,
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 20},
        },
    }
    return {**result, **updates}


def sdk_client(*, output=None, count=1000, failure=None):
    calls = []

    def transport(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if failure:
            return httpx2.Response(
                429, json={"error": {"message": "secret", "type": "insufficient_quota"}}
            )
        if request.url.path.endswith("input_tokens"):
            return httpx2.Response(
                200, json={"object": "response.input_tokens", "input_tokens": count}
            )
        return httpx2.Response(200, json=output or response())

    client = OpenAI(
        api_key="fixture-only",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(transport)),
    )
    return client, calls


def test_pinned_sdk_counts_exact_payload_and_generates_one_toolless_strict_response(tmp_path):
    *_, request = setup(tmp_path)
    client, calls = sdk_client()
    with client:
        result = perform(request, client)
    assert result.error is None and result.decision == decision()
    assert result.usage.request_id == "resp-test" and result.counted_input_tokens == 1000
    assert [c[0] for c in calls] == ["/v1/responses/input_tokens", "/v1/responses"]
    counted, generated = calls[0][1], calls[1][1]
    assert counted == {
        k: v
        for k, v in generated.items()
        if k
        not in {
            "max_output_tokens",
            "store",
            "background",
            "stream",
        }
    }
    assert generated["tools"] == [] and generated["tool_choice"] == "none"
    assert generated["text"]["format"]["strict"] is True
    assert generated["max_output_tokens"] == 1024
    assert generated["store"] is generated["background"] is generated["stream"] is False


@pytest.mark.parametrize(
    "output",
    [
        response(status="incomplete"),
        response(error={"code": "server_error", "message": "secret"}),
        response(
            output=[
                {
                    "type": "message",
                    "id": "msg-1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "no"}],
                }
            ]
        ),
        response(
            output=[
                {
                    "type": "message",
                    "id": "msg-1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "not-json", "annotations": []}],
                }
            ]
        ),
        response(
            output=[
                {
                    "type": "function_call",
                    "id": "fc-1",
                    "name": "place_order",
                    "call_id": "call-1",
                    "arguments": "{}",
                    "status": "completed",
                }
            ]
        ),
    ],
)
def test_incomplete_refusal_bad_schema_or_tool_output_preserves_usage_as_hold(tmp_path, output):
    *_, request = setup(tmp_path)
    client, calls = sdk_client(output=output)
    with client:
        result = perform(request, client)
    assert result.error and result.decision.action == Action.HOLD
    assert result.usage.input_tokens == 1000 and result.usage.output_tokens == 100
    assert len(calls) == 2 and "secret" not in result.model_dump_json()


@pytest.mark.parametrize("count", [0, -1, True, "1000", 16001])
def test_bad_or_excessive_count_prevents_generation_without_inventing_zero_cost(tmp_path, count):
    *_, request = setup(tmp_path)
    client, calls = sdk_client(count=count)
    with client:
        result = perform(request, client)
    assert result.error and result.usage is None and result.decision.action == Action.HOLD
    assert len(calls) == 1


@pytest.mark.parametrize(
    "output",
    [
        response(usage=None),
        response(id=""),
        response(usage={"input_tokens": 0, "output_tokens": 0}),
    ],
)
def test_missing_or_invalid_response_usage_remains_unknown(tmp_path, output):
    *_, request = setup(tmp_path)
    client, _ = sdk_client(output=output)
    with client:
        result = perform(request, client)
    assert result.usage is None and result.error and result.decision.action == Action.HOLD


def test_provider_failure_is_sanitized_and_never_retried(tmp_path):
    *_, request = setup(tmp_path)
    client, calls = sdk_client(failure=True)
    with client:
        result = perform(request, client)
    assert result.error == "RateLimitError" and result.usage is None
    assert len(calls) == 1 and "secret" not in result.model_dump_json()


def test_expired_or_changed_configuration_does_not_call_sdk(tmp_path):
    *_, request = setup(tmp_path)
    client, calls = sdk_client()
    with client:
        assert perform(
            request.model_copy(update={"deadline_monotonic": time.monotonic() - 1}), client
        ).error
        config = {**request.configuration, "prompt_hash": "wrong"}
        assert perform(request.model_copy(update={"configuration": config}), client).error
    assert calls == []


@pytest.mark.anyio
async def test_coordinator_commits_before_invocation_uses_account_truth_and_never_replays(
    tmp_path, monkeypatch
):
    engine, _, settings, costs, coordinator, _ = setup(tmp_path)
    engine.journal.enable_restore_fence(now=NOW)
    calls = []

    async def run(request, api_key):
        calls.append(request)
        assert api_key == "fixture-only"
        assert request.packet.account.cash == Decimal(10)
        assert request.packet.session_context is not None
        assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
        client, _ = sdk_client()
        with client:
            return perform(request, client)

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    p = packet()
    p.account.cash = p.account.buying_power = p.account.equity = Decimal(99999)
    outcome = await coordinator.decide(
        "entry", p, api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    assert outcome.estimated_cost == Decimal(".00015")
    assert engine.prepare("entry", outcome.result.decision, outcome.packet, now=NOW)
    assert engine.journal.report(now=NOW)["restore_fence"]["status"] == "VERIFIED"
    restarted = ExecutionEngine(engine.journal.path, settings)
    again = JudgmentCoordinator(CostAccounting(restarted, costs.policy), coordinator.limits)
    with pytest.raises(ExecutionBlocked):
        await again.decide("entry", p, api_key="fixture-only", now=NOW, clock=lambda: NOW)
    assert len(calls) == 1


@pytest.mark.anyio
async def test_fail_closed_but_billed_hold_settles_cost_and_alerts(tmp_path, monkeypatch):
    engine, _, _, _, coordinator, _ = setup(tmp_path)

    async def run(request, key):
        client, _ = sdk_client(output=response(status="incomplete"))
        with client:
            return perform(request, client)

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    out = await coordinator.decide(
        "hold", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    assert out.result.decision.action == Action.HOLD and out.estimated_cost == Decimal(".00015")
    report = engine.journal.report(now=NOW)
    assert report["economics"]["unknown_calls"] == 0
    assert len(engine.journal.alerts()) == 1
    assert report["orders"] == []


@pytest.mark.anyio
async def test_unknown_failure_persists_and_blocks_next_judgment(tmp_path, monkeypatch):
    engine, _, _, _, coordinator, _ = setup(tmp_path)

    async def run(*args):
        raise TimeoutError("secret")

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    out = await coordinator.decide(
        "failed", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    assert out.result.error == "TimeoutError" and out.estimated_cost is None
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
    with pytest.raises(ExecutionBlocked, match="COST_UNKNOWN"):
        await coordinator.decide(
            "next", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "updates",
    [{"input_tokens": 16001}, {"output_tokens": 1025}, {"model": "foreign"}, {"input_tokens": 999}],
)
async def test_evidence_violations_preserve_full_known_cost_and_fence_entries(
    tmp_path, monkeypatch, updates
):
    engine, _, _, costs, coordinator, _ = setup(tmp_path)
    evidence = UsageEvidence.model_validate(
        {
            "request_id": "resp-test",
            "model": "gpt-6-luna",
            "input_tokens": 1000,
            "output_tokens": 100,
            **updates,
        }
    )

    async def run(*args):
        return JudgmentResult(decision=decision(), usage=evidence, counted_input_tokens=1000)

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    out = await coordinator.decide(
        "violated", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    assert (
        out.result.error == "ModelEvidenceViolation" and out.result.decision.action == Action.HOLD
    )
    assert (
        engine.journal.report(now=NOW)["economics"]["judgment_blocked"]
        == "MODEL_EVIDENCE_VIOLATION"
    )
    if evidence.model == "gpt-6-luna":
        assert (
            out.estimated_cost
            == (
                Decimal(evidence.input_tokens) * Decimal(".1")
                + Decimal(evidence.output_tokens) * Decimal(".5")
            )
            / 1_000_000
        )
    else:
        assert out.estimated_cost is None
    with pytest.raises(ExecutionBlocked):
        costs.begin("next", packet(), now=NOW)


@pytest.mark.anyio
async def test_audit_storage_failure_rolls_back_cost_and_decision_together(tmp_path, monkeypatch):
    engine, _, _, _, coordinator, _ = setup(tmp_path)
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER execution_fail_judgment BEFORE INSERT ON execution_events WHEN NEW.kind='MODEL_JUDGMENT_RECORDED' BEGIN SELECT RAISE(ABORT,'failure'); END"
        )

    async def run(*args):
        return JudgmentResult(
            decision=decision(),
            usage=UsageEvidence(
                request_id="resp-test", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
            counted_input_tokens=1000,
        )

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    with pytest.raises(sqlite3.IntegrityError):
        await coordinator.decide(
            "rollback", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
    assert engine.journal.report(now=NOW)["economics"]["known_cost"] == "0"


def test_request_limits_and_policy_are_frozen_before_any_receipt(tmp_path):
    _, _, _, costs, coordinator, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        JudgmentCoordinator(costs, JudgmentLimits(max_output_tokens=1023))
    with pytest.raises(ValueError, match="reservation"):
        JudgmentCoordinator(costs, JudgmentLimits(max_input_tokens=100000))
    with pytest.raises(ValueError):
        JudgmentLimits(max_input_tokens=True)
    with pytest.raises(ValueError):
        JudgmentLimits(request_timeout_seconds=31)
    assert coordinator.limits.max_output_tokens == 1024


@pytest.mark.anyio
async def test_invalid_key_clock_configuration_or_review_change_never_invokes(
    tmp_path, monkeypatch
):
    engine, _, _, costs, coordinator, _ = setup(tmp_path)

    async def forbidden(*args):
        pytest.fail("No invocation permitted")

    monkeypatch.setattr(judgment, "run_judgment_process", forbidden)
    with pytest.raises(ValueError):
        await coordinator.decide(
            "bad-key", packet(), api_key="two keys", now=NOW, clock=lambda: NOW
        )
    coordinator.limits = JudgmentLimits(max_output_tokens=1023)
    with pytest.raises(ExecutionBlocked, match="CONFIGURATION_CHANGED"):
        await coordinator.decide(
            "bad-config", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )
    coordinator.limits = JudgmentLimits()
    real_begin = costs.begin

    def changed(*args, **kwargs):
        engine.halt("Concurrent operator review", now=NOW)
        return real_begin(*args, **kwargs)

    monkeypatch.setattr(costs, "begin", changed)
    with pytest.raises(ExecutionBlocked, match="REVIEW_CHANGED"):
        await coordinator.decide(
            "race", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 0


@pytest.mark.anyio
async def test_real_child_protocol_and_environment_exclude_broker_keys_and_mutable_api_origin(
    tmp_path, monkeypatch
):
    *_, request = setup(tmp_path)
    monkeypatch.setenv("ROBINHOOD_TOKEN", "broker-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-wrong")
    real_spawn = asyncio.create_subprocess_exec
    expected = JudgmentResult(
        decision=decision(),
        usage=UsageEvidence(
            request_id="resp-test", model="gpt-6-luna", input_tokens=1000, output_tokens=100
        ),
        counted_input_tokens=1000,
    )
    source = (
        "import json,sys,os\nr=json.load(sys.stdin)\nassert os.environ['OPENAI_API_KEY']=='fixture-only'\nassert 'ROBINHOOD_TOKEN' not in os.environ\nassert 'OPENAI_BASE_URL' not in os.environ\nassert r['parent_pid']==os.getppid()\n"
        + f"sys.stdout.write({expected.model_dump_json()!r})"
    )

    async def spawn(*args, **kwargs):
        assert args == (sys.executable, "-m", "app.execution.judgment_worker")
        assert set(kwargs["env"]) <= {"PATH", "LANG", "LC_ALL", "OPENAI_API_KEY"}
        return await real_spawn(sys.executable, "-c", source, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert await judgment.run_judgment_process(request, "fixture-only") == expected


@pytest.mark.anyio
async def test_timeout_and_repeated_cancel_reap_real_child_and_preserve_unknown_receipt(
    tmp_path, monkeypatch
):
    engine, _, _, _, coordinator, _ = setup(
        tmp_path, limits=JudgmentLimits(process_timeout_seconds=0.5, request_timeout_seconds=0.2)
    )
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    real_spawn = asyncio.create_subprocess_exec
    path = tmp_path / "pid"
    source = f"import os,sys,signal,time,pathlib\nsys.stdin.read()\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\npathlib.Path({str(path)!r}).write_text(str(os.getpid()))\ntime.sleep(60)"

    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, "-c", source, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        coordinator.decide("cancel", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW)
    )
    async with asyncio.timeout(3):
        while not path.exists():
            await asyncio.sleep(0.005)
    pid = int(path.read_text())
    task.cancel()
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)  # noqa: ASYNC222 -- deliberately nonblocking reaping proof
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
    assert engine.journal.alerts()[0]["kind"] == "MODEL_JUDGMENT_INTERRUPTED"


@pytest.mark.anyio
async def test_completion_clock_regression_keeps_cost_unknown(tmp_path, monkeypatch):
    engine, _, _, _, coordinator, _ = setup(tmp_path)

    async def run(*args):
        return JudgmentResult(
            decision=decision(),
            usage=UsageEvidence(
                request_id="resp-test", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
            counted_input_tokens=1000,
        )

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    with pytest.raises(ValueError, match="regressed"):
        await coordinator.decide(
            "clock",
            packet(),
            api_key="fixture-only",
            now=NOW,
            clock=lambda: NOW - timedelta(seconds=1),
        )
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1


def test_worker_main_pins_origin_retries_and_secret_free_json(tmp_path, monkeypatch, capsys):
    from app.execution import judgment_worker

    *_, request = setup(tmp_path)
    request = request.model_copy(update={"parent_pid": os.getppid()})
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(request.model_dump_json().encode()))
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.invalid")
    configured = []
    client, calls = sdk_client()

    def sdk(**kwargs):
        configured.append(kwargs)
        print("secret SDK output")
        return client

    monkeypatch.setattr(judgment_worker, "OpenAI", sdk)
    # The live watchdog is proved separately in a real child.
    monkeypatch.setattr(
        threading := judgment_worker.threading,
        "Thread",
        lambda **kw: SimpleNamespace(start=lambda: None),
    )
    assert threading is judgment_worker.threading
    assert judgment_worker.main() == 0
    captured = capsys.readouterr()
    out = JudgmentResult.model_validate_json(captured.out)
    assert out.error is None and len(calls) == 2 and captured.err == ""
    assert configured == [
        {
            "api_key": "fixture-only",
            "base_url": "https://api.openai.com/v1",
            "timeout": 20,
            "max_retries": 0,
        }
    ]
    assert "secret" not in captured.out


@pytest.mark.anyio
async def test_real_deadline_crash_and_oversized_protocol_keep_receipts_unknown(
    tmp_path, monkeypatch
):
    engine, _, _, _, coordinator, _ = setup(
        tmp_path, limits=JudgmentLimits(process_timeout_seconds=0.5, request_timeout_seconds=0.2)
    )
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    real_spawn = asyncio.create_subprocess_exec
    source = "import sys,time\nsys.stdin.read()\ntime.sleep(60)"
    children = []

    async def spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-c", source, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    out = await coordinator.decide(
        "timeout", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    assert out.result.error == "TimeoutError"
    assert children[0].returncode is not None
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
    # Separate raw transport requests exercise failed children without creating another receipt.
    *_, request = setup(tmp_path / "protocol")
    source = "import sys\nsys.stdin.read()\nsys.exit(8)"
    with pytest.raises(RuntimeError):
        await judgment.run_judgment_process(request, "fixture-only")
    source = (
        f"import sys\nsys.stdin.read()\nsys.stdout.write('x'*{judgment.MAX_RESPONSE_BYTES * 2})"
    )
    with pytest.raises(ValueError, match="protocol limit"):
        await judgment.run_judgment_process(request, "fixture-only")
    assert all(child.returncode is not None for child in children)


@pytest.mark.anyio
async def test_receipt_storage_failure_prevents_child_launch(tmp_path, monkeypatch):
    engine, _, _, _, coordinator, _ = setup(tmp_path)
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER execution_bad_receipt BEFORE INSERT ON execution_model_calls BEGIN SELECT RAISE(ABORT,'failure'); END"
        )

    async def forbidden(*args):
        pytest.fail("Receipt must commit first")

    monkeypatch.setattr(judgment, "run_judgment_process", forbidden)
    with pytest.raises(sqlite3.IntegrityError):
        await coordinator.decide(
            "never-launched", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 0


def test_enrollment_cannot_relabel_existing_model_receipts(tmp_path):
    _, _, _, costs = context(tmp_path)
    costs.begin("older", packet(), now=NOW)
    with pytest.raises(ValueError, match="before model receipts"):
        JudgmentCoordinator(costs, JudgmentLimits())


def test_enrolled_policy_requires_bounded_judgment_record_for_entry(tmp_path):
    engine, _, _, costs, coordinator, _ = setup(tmp_path)
    with pytest.raises(ExecutionBlocked, match="REVIEW_REQUIRED"):
        costs.begin("direct", packet(), now=NOW)
    with engine.journal.read() as db:
        revision = engine.journal.revision(db)
    costs.begin("direct", packet(), now=NOW, expected_revision=revision)
    costs.settle(
        "direct",
        UsageEvidence(
            request_id="resp-test", model="gpt-6-luna", input_tokens=1000, output_tokens=100
        ),
        decision(),
        now=NOW,
    )
    with pytest.raises(ExecutionBlocked, match="BOUNDED_JUDGMENT_EVIDENCE"):
        engine.prepare("direct", decision(), packet(), now=NOW)
    assert coordinator.limits.max_output_tokens == 1024


@pytest.mark.anyio
async def test_changed_runtime_limits_during_invocation_cannot_settle_or_grant_entry(
    tmp_path, monkeypatch
):
    engine, _, _, _, coordinator, _ = setup(tmp_path)

    async def run(*args):
        coordinator.limits = JudgmentLimits(max_output_tokens=1023)
        return JudgmentResult(
            decision=decision(),
            usage=UsageEvidence(
                request_id="resp-test", model="gpt-6-luna", input_tokens=1000, output_tokens=100
            ),
            counted_input_tokens=1000,
        )

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    with pytest.raises(ExecutionBlocked, match="CONFIGURATION_CHANGED"):
        await coordinator.decide(
            "changed", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper owns orphan cleanup")
def test_parent_crash_stops_actual_worker_watchdog_and_preserves_unknown_cost(tmp_path):
    engine, _, settings, costs, coordinator, _ = setup(tmp_path)
    engine.journal.enable_restore_fence(now=NOW)
    pid_path = tmp_path / "model-child.pid"
    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(original), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        pytest.skip("Subreaper unavailable")
    child_pid = None
    script = '''
import asyncio, os, sys
from pathlib import Path
from datetime import datetime
from app.config import Settings
from app.execution.engine import ExecutionEngine
from app.execution.economics import CostAccounting, CostPolicy
from app.execution.judgment import JudgmentCoordinator, JudgmentLimits
from app.execution.cli import _packet
at=datetime.fromisoformat(sys.argv[3])
engine=ExecutionEngine(sys.argv[1], Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10))
costs=CostAccounting(engine, CostPolicy(total_budget=1,daily_budget=1))
coordinator=JudgmentCoordinator(costs, JudgmentLimits())
real_spawn=asyncio.create_subprocess_exec
# Actual worker.main starts its real watchdog. The replacement client never reaches a network.
child_source="""
import os,time,signal
from pathlib import Path
from app.execution import judgment_worker as worker
class Blocked:
    def __enter__(self):
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        Path(PATH).write_text(str(os.getpid()))
        time.sleep(60)
    def __exit__(self,*args): pass
worker.OpenAI=lambda **kwargs: Blocked()
worker.main()
""".replace("PATH",repr(sys.argv[2]))
async def spawn(*args,**kwargs):
    return await real_spawn(sys.executable,"-c",child_source,**kwargs)
asyncio.create_subprocess_exec=spawn
async def run():
    asyncio.create_task(coordinator.decide("parent-crash",_packet(at),api_key="fixture-only",now=at,clock=lambda:at))
    async with asyncio.timeout(10):
        while not Path(sys.argv[2]).exists(): await asyncio.sleep(.01)
    os._exit(94)
asyncio.run(run())
'''
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(engine.journal.path),
                str(pid_path),
                NOW.isoformat(),
            ],
            timeout=15,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 94, result.stderr
        child_pid = int(pid_path.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(child_pid, os.WNOHANG)
            if pid:
                child_pid = None
                assert os.waitstatus_to_exitcode(status) == 99
                break
            time.sleep(0.01)
        assert child_pid is None, "Watchdog did not stop orphaned model child"
        restarted = ExecutionEngine(engine.journal.path, settings)
        report = restarted.journal.report(now=NOW)
        assert report["economics"]["unknown_calls"] == 1
        assert report["restore_fence"]["status"] == "VERIFIED"
        again = JudgmentCoordinator(CostAccounting(restarted, costs.policy), coordinator.limits)
        with pytest.raises(ExecutionBlocked, match="ALREADY_ATTEMPTED"):
            from app.execution.cli import _packet

            asyncio.run(
                again.decide(
                    "parent-crash", _packet(NOW), api_key="fixture-only", now=NOW, clock=lambda: NOW
                )
            )
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child_pid, 0)
        libc.prctl(36, original.value, 0, 0, 0)
