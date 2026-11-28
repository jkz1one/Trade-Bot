import asyncio
import io
import json
import os
import sys
from types import SimpleNamespace

import pytest

from app.agent import process as model_process
from app.agent.process import (
    MAX_RESPONSE_BYTES, ModelProcessFailed, ModelProcessProtocolError, ModelProcessTimeout,
    run_model_process,
)
from app.agent.trader import OpenAIAgentsTrader, StubTraderAgent
from app.domain.models import AccountState, Action, MarketPacket, utc_now


@pytest.fixture
def packet():
    return MarketPacket(as_of=utc_now(), candidates=[], account=AccountState(
        equity=10, cash=10, buying_power=10, high_watermark=10,
    ))


def envelope(**updates):
    result = {"decision": StubTraderAgent().decide(None).decision.model_dump(mode="json"),
              "input_tokens": 123, "output_tokens": 45, "error": None}
    result.update(updates)
    return result


async def run(packet, source, *, timeout=3):
    return await run_model_process("gpt-6-luna", packet, timeout_seconds=timeout,
                                   request_timeout_seconds=60,
                                   _command=(sys.executable, "-c", source))


def blocked_source(path):
    # A real synchronous call that deliberately ignores graceful termination.
    return ("import sys,os,signal,threading,pathlib\n"
            "sys.stdin.buffer.read()\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"pathlib.Path({str(path)!r}).write_text(str(os.getpid()))\n"
            "threading.Event().wait()\n")


async def wait_started(path):
    async with asyncio.timeout(3):
        while not path.exists():
            await asyncio.sleep(.005)
    return int(path.read_text())


def assert_reaped(pid):
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


@pytest.mark.anyio
async def test_process_transports_exact_packet_decision_and_usage(packet):
    output = json.dumps(envelope())
    source = ("import json,sys\nrequest=json.load(sys.stdin)\n"
              "assert request['model']=='gpt-6-luna'\n"
              "assert request['request_timeout_seconds']==60\n"
              f"assert request['packet']=={packet.model_dump(mode='json')!r}\n"
              f"sys.stdout.write({output!r})\n")
    result = await run(packet, source)
    assert result.decision == StubTraderAgent().decide(None).decision
    assert (result.input_tokens, result.output_tokens, result.error) == (123, 45, None)


@pytest.mark.anyio
@pytest.mark.parametrize("payload", ["not-json", json.dumps(envelope(input_tokens=-1)),
                                     json.dumps(envelope(output_tokens=True)),
                                     json.dumps(envelope(extra="unexpected"))])
async def test_invalid_child_output_fails_closed(packet, payload):
    with pytest.raises(ModelProcessProtocolError):
        await run(packet, f"import sys;sys.stdin.read();sys.stdout.write({payload!r})")


@pytest.mark.anyio
async def test_child_error_cannot_grant_authority_or_invent_usage(packet):
    decision = envelope()["decision"]
    decision.update(action="OPEN_LONG", symbol="SPY", invalidation_price="99")
    payload = json.dumps(envelope(decision=decision, error="RateLimitError"))
    result = await run(packet, f"import sys;sys.stdin.read();sys.stdout.write({payload!r})")
    assert result.error == "RateLimitError"
    assert result.decision.action == Action.HOLD
    assert result.input_tokens == result.output_tokens == 0


@pytest.mark.anyio
async def test_crash_and_oversized_response_are_sanitized(packet, capsys):
    with pytest.raises(ModelProcessFailed):
        await run(packet, "import sys;sys.stdin.read();print('secret-value',file=sys.stderr);sys.exit(9)")
    with pytest.raises(ModelProcessProtocolError):
        await asyncio.wait_for(run(packet, f"import sys;sys.stdin.read();sys.stdout.write('x'*{MAX_RESPONSE_BYTES*32})"), 3)
    assert "secret-value" not in capsys.readouterr().err


@pytest.mark.anyio
async def test_timeout_kills_and_reaps_real_blocked_synchronous_child(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(model_process, "TERMINATION_GRACE_SECONDS", .05)
    path = tmp_path / "pid"
    task = asyncio.create_task(run(packet, blocked_source(path), timeout=.3))
    pid = await wait_started(path)
    with pytest.raises(ModelProcessTimeout):
        await asyncio.wait_for(task, 2)
    assert_reaped(pid)


@pytest.mark.anyio
async def test_repeated_cancellation_cleans_child_and_propagates(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(model_process, "TERMINATION_GRACE_SECONDS", .1)
    path = tmp_path / "pid"
    task = asyncio.create_task(run(packet, blocked_source(path)))
    pid = await wait_started(path)
    task.cancel()
    await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert_reaped(pid)


@pytest.mark.anyio
async def test_cancellation_during_spawn_does_not_orphan_child(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(model_process, "TERMINATION_GRACE_SECONDS", .05)
    real_spawn = asyncio.create_subprocess_exec
    path = tmp_path / "pid"
    created = asyncio.Event()
    release = asyncio.Event()
    processes = []

    async def delayed_spawn(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        processes.append(process)
        created.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    task = asyncio.create_task(run(packet, blocked_source(path)))
    await created.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert_reaped(processes[0].pid)


@pytest.mark.anyio
async def test_cancellation_during_success_cleanup_is_not_swallowed(packet, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    real_terminate = model_process._terminate

    async def delayed_terminate(process):
        started.set()
        await release.wait()
        await real_terminate(process)

    monkeypatch.setattr(model_process, "_terminate", delayed_terminate)
    payload = json.dumps(envelope())
    task = asyncio.create_task(run(packet, f"import sys;sys.stdin.read();sys.stdout.write({payload!r})"))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_worker_sdk_has_no_retries_tracing_or_tools_and_only_emits_valid_result(packet, monkeypatch, capsys):
    from app.agent import worker
    import agents
    import openai

    request = json.dumps({"model": "gpt-6-luna", "packet": packet.model_dump(mode="json"),
                          "request_timeout_seconds": 60}).encode()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(request)))
    configured = []
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: configured.append(kw) or "client")
    monkeypatch.setattr(agents, "set_default_openai_client", lambda client, **kw: configured.append(kw))
    monkeypatch.setattr(agents, "set_tracing_disabled", lambda disabled: configured.append(disabled))

    def fake_run(agent, prompt, *, max_turns):
        assert agent.tools == [] and max_turns == 1
        assert json.loads(prompt.split("\n", 1)[1]) == packet.model_dump(mode="json")
        print("secret SDK stdout")
        print("secret SDK stderr", file=sys.stderr)
        return SimpleNamespace(final_output=StubTraderAgent().decide(None).decision,
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace(
                                   input_tokens=123, output_tokens=45)))

    monkeypatch.setattr(agents.Runner, "run_sync", fake_run)
    worker.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == envelope()
    assert captured.err == ""
    assert configured == [True, {"timeout": 60, "max_retries": 0}, {"use_for_tracing": False}]


@pytest.mark.anyio
async def test_actual_worker_protocol_rejects_bad_input_without_network_calls(packet):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.agent.worker", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(process.communicate(b"not-json"), 5)
    response = json.loads(out)
    assert process.returncode == 0 and not err
    assert response["error"] == "ValidationError"
    assert response["decision"]["action"] == "HOLD"


@pytest.mark.anyio
async def test_shadow_uses_isolated_model_and_timeout_becomes_hold(repo, packet, monkeypatch):
    from app.config import Settings
    from app.robinhood.shadow import ShadowOrchestrator

    called = []

    async def isolated(self, supplied, **kw):
        called.append(kw)
        assert supplied is packet
        raise ModelProcessTimeout()

    monkeypatch.setattr(OpenAIAgentsTrader, "decide_isolated", isolated)
    monkeypatch.setattr(OpenAIAgentsTrader, "decide", lambda *args: pytest.fail("No model thread in parent"))
    orchestrator = ShadowOrchestrator(Settings(mode="SHADOW"), repo, object(), OpenAIAgentsTrader("gpt-6-luna"))
    result = await orchestrator._decide(packet)
    assert result.decision.action == Action.HOLD and result.error == "ModelProcessTimeout"
    assert called == [{"timeout_seconds": 120, "request_timeout_seconds": 60}]


@pytest.mark.anyio
@pytest.mark.parametrize("deadline", ["model", "cycle", "shutdown"])
async def test_blocked_model_in_real_shadow_service_halts_without_review_or_replay(
    repo, tmp_path, monkeypatch, deadline,
):
    from datetime import datetime, timedelta, timezone
    from app.config import Settings
    from app.robinhood.models import RobinhoodTruth
    from app.robinhood.schedule import SessionWindow, ShadowScheduler
    from app.robinhood.service import ShadowService
    from app.robinhood.shadow import ShadowOrchestrator

    monkeypatch.setattr(model_process, "TERMINATION_GRACE_SECONDS", .05)
    now = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)
    window = SessionWindow("2026-10-05", now - timedelta(minutes=30),
                           now + timedelta(hours=6), now)
    settings = Settings(mode="SHADOW", shadow_service_lock_path=str(tmp_path / "lock"),
                        model_process_timeout_seconds=.5 if deadline != "cycle" else 3)
    path = tmp_path / "pid"
    calls = []

    async def isolated(self, packet, **kw):
        calls.append(1)
        return await run_model_process(self.model_identifier, packet, **kw,
                                       _command=(sys.executable, "-c", blocked_source(path)))

    async def forbidden(*args):
        pytest.fail("No review, next cycle or network preflight after failure")

    monkeypatch.setattr(OpenAIAgentsTrader, "decide_isolated", isolated)
    truth = RobinhoodTruth.model_validate({
        "account": {"account_number": "FAKE", "type": "cash", "agentic_allowed": True,
                    "brokerage_account_type": "individual", "state": "active",
                    "deactivated": False, "permanently_deactivated": False},
        "portfolio": {"total_value": "10", "equity_value": "0", "cash": "10",
                      "buying_power": "10", "unleveraged_buying_power": "10", "unsupported_value": "0"},
    })

    async def reads():
        return truth

    async def candidates(*args):
        return []

    orchestrator = ShadowOrchestrator(settings, repo, SimpleNamespace(call_safe=forbidden),
                                     OpenAIAgentsTrader("gpt-6-luna"), clock=lambda: now)
    orchestrator.reads = SimpleNamespace(truth=reads)
    orchestrator.market = SimpleNamespace(candidates=candidates, regime=lambda rows: "test")

    async def cycle(window, token):
        result = await orchestrator.cycle(schedule_window=window, claim_token=token)
        return 8 if result[3].agent_error else 0

    async def ready(*args):
        return None

    scheduler = ShadowScheduler(repo, cycle, clock=lambda: now,
                                calendar=SimpleNamespace(current_window=lambda stamp: window))
    stop = asyncio.Event()
    service = ShadowService(settings, repo, scheduler, preflight=ready,
                            cycle_timeout=.5 if deadline == "cycle" else 3,
                            poll_seconds=.005, heartbeat_seconds=.005)
    task = asyncio.create_task(service.run(stop))
    try:
        pid = await wait_started(path)
        if deadline == "shutdown":
            # This is the same stop event set by the service's SIGTERM handler.
            stop.set()
            assert not task.done()
        async with asyncio.timeout(3):
            while repo.shadow_service_state()["status"] != "HALTED":
                await asyncio.sleep(.005)
        assert_reaped(pid)
        assert calls == [1]
        slot = repo.shadow_slot(window.key)
        if deadline != "cycle":
            assert slot.status == "FAILED" and slot.exit_code == 8
            evidence = repo.shadow_cycle_evidence(slot.cycle_id)
            assert evidence["model_usage"] is None
            row = repo.recent_cycles()[0]
            assert json.loads(row.execution_json)["agent_error"] == "ModelProcessTimeout"
            assert json.loads(row.decision_json)["action"] == "HOLD"
        else:
            assert slot.status == "CLAIMED" and repo.active_shadow_slot() is not None
            assert repo.recent_cycles() == []
    finally:
        stop.set()
        await asyncio.wait_for(task, 3)

    stopped = asyncio.Event()
    restart = ShadowService(settings, repo, SimpleNamespace(tick=forbidden), preflight=forbidden,
                            poll_seconds=.005)
    task = asyncio.create_task(restart.run(stopped))
    await asyncio.sleep(.02)
    stopped.set()
    await task
    assert repo.shadow_service_state()["status"] == "HALTED" and calls == [1]
