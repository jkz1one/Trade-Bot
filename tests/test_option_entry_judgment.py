"""Real SDK request shape and native entry child bounds, without provider traffic."""

import asyncio
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_execution_judgment import response, sdk_client
from test_option_entry_reasoning import AT, packet_for, plan_for

from app.execution.economics import CostPolicy, UsageEvidence
from app.execution.judgment import JudgmentLimits
from app.options.engine import fingerprint
from app.options.entry_judgment import (
    MAX_RESPONSE_BYTES,
    configuration,
    create_request,
    hold,
    request_content,
    result_for,
    run_entry_process,
    validate_result,
)
from app.options.entry_judgment_worker import perform


def request_for(*, right="CALL", seconds=5):
    packet = packet_for(right)
    config = configuration(
        CostPolicy(total_budget="1", daily_budget=".1"),
        JudgmentLimits(process_timeout_seconds=seconds, request_timeout_seconds=min(seconds, 3)),
        packet.policy,
    )
    packet = packet.model_copy(update={"model_configuration_hash": fingerprint(config)})
    return create_request(packet, config, request_id="e" * 32, now=AT)


def output_for(r, action="ENTER"):
    output = response()
    output["output"][0]["content"][0]["text"] = (
        hold(r.packet) if action == "HOLD" else plan_for(r.packet)
    ).model_dump_json()
    return output


def receipt(r):
    return result_for(
        r,
        plan=plan_for(r.packet),
        count=1000,
        usage=UsageEvidence(
            request_id="resp-entry",
            model=r.configuration.costs.model,
            input_tokens=1000,
            output_tokens=100,
        ),
    )


@pytest.mark.parametrize("right,action", [("CALL", "ENTER"), ("PUT", "ENTER"), ("CALL", "HOLD")])
def test_exact_sdk_count_and_generation_have_no_tools(right, action):
    r = request_for(right=right)
    client, calls = sdk_client(output=output_for(r, action))
    with client:
        result = perform(r, client)
    assert result.error is None and result.plan.action == action
    assert result.execution_authority is False and result.usage.input_tokens == 1000
    assert [path for path, _ in calls] == ["/v1/responses/input_tokens", "/v1/responses"]
    count, generation = [b for _, b in calls]
    assert count == request_content(r)
    assert count == {
        k: v
        for k, v in generation.items()
        if k not in {"max_output_tokens", "store", "background", "stream"}
    }
    assert generation["tools"] == [] and generation["tool_choice"] == "none"
    assert generation["truncation"] == "disabled"
    assert generation["text"]["format"]["strict"] is True
    assert generation["store"] is generation["background"] is generation["stream"] is False
    envelope = json.loads(generation["input"].split("\n", 1)[1])
    assert envelope["binding"] == {
        "decision_id": r.packet.decision_id,
        "packet_hash": fingerprint(r.packet),
    }
    assert envelope["packet"]["opportunities"][0]["evidence_ids"]
    assert result.diagnostics.generation.completed == result.diagnostics.input_count.completed == 1


@pytest.mark.parametrize(
    "damage",
    [
        "refusal",
        "incomplete",
        "tool",
        "fragment",
        "schema",
        "candidate",
        "evidence",
        "geometry",
        "binding",
        "model",
        "count",
        "input_ceiling",
        "output_ceiling",
        "provider_error",
    ],
)
def test_rejected_output_retains_usage_without_echoing_provider_data(damage):
    r = request_for()
    output = output_for(r)
    if damage == "refusal":
        output["output"][0]["content"] = [{"type": "refusal", "refusal": "private-provider-text"}]
    elif damage == "incomplete":
        output["status"] = "incomplete"
    elif damage == "tool":
        output["output"] = [
            {
                "type": "function_call",
                "id": "x",
                "call_id": "x",
                "name": "broker_write",
                "arguments": "{}",
                "status": "completed",
            }
        ]
    elif damage == "fragment":
        output["output"].append(output["output"][0].copy())
    elif damage == "schema":
        output["output"][0]["content"][0]["text"] = '{"quantity":100}'
    elif damage in {"candidate", "evidence", "geometry", "binding"}:
        changes = {
            "candidate": {"candidate_id": "f" * 64},
            "evidence": {"evidence_ids": ("f" * 64,)},
            "geometry": {"underlying_invalidation": "590"},
            "binding": {"packet_hash": "f" * 64},
        }[damage]
        output["output"][0]["content"][0]["text"] = plan_for(r.packet, **changes).model_dump_json()
    elif damage == "model":
        output["model"] = "other-model"
    elif damage in {"count", "input_ceiling"}:
        output["usage"]["input_tokens"] = 999 if damage == "count" else 16001
    elif damage == "output_ceiling":
        output["usage"]["output_tokens"] = 1025
    else:
        output["error"] = {"code": "server_error", "message": "private-provider-text"}
    client, calls = sdk_client(output=output)
    with client:
        result = perform(r, client)
    assert result.error and result.plan.action == "HOLD"
    assert result.usage is not None and len(calls) == 2
    assert "private-provider-text" not in result.model_dump_json()
    assert validate_result(r, result) == result  # Unusable usage remains evidence, not settlement.


@pytest.mark.parametrize("count", [True, "1000", 0, -1, 16001])
def test_invalid_input_count_never_generates(count):
    r = request_for()
    client, calls = sdk_client(count=count)
    with client:
        result = perform(r, client)
    assert result.error and result.usage is None and result.counted_input_tokens is None
    assert len(calls) == 1


def test_missing_usage_stays_unknown_and_quota_does_not_retry():
    r = request_for()
    client, calls = sdk_client(output=output_for(r) | {"usage": None})
    with client:
        result = perform(r, client)
    assert result.error and result.usage is None and len(calls) == 2
    client, calls = sdk_client(failure=True)
    with client:
        result = perform(r, client)
    assert result.error and result.usage is None and len(calls) == 1


def test_generation_finishing_after_deadline_keeps_usage_but_holds():
    r = request_for(seconds=0.05)
    client, calls = sdk_client(output=output_for(r))
    original = client.responses.create

    def delayed(**kwargs):
        value = original(**kwargs)
        time.sleep(0.06)
        return value

    client.responses.create = delayed
    with client:
        result = perform(r, client)
    assert len(calls) == 2 and result.error == "TimeoutError"
    assert result.plan.action == "HOLD" and result.usage.input_tokens == 1000


@pytest.mark.parametrize("damage", ["prompt", "schema", "config", "policy", "deadline", "expired"])
def test_changed_configuration_or_lease_blocks_before_provider(damage):
    r = request_for()
    if damage in {"prompt", "schema"}:
        r = r.model_copy(
            update={
                "configuration": r.configuration.model_copy(update={damage + "_hash": "f" * 64})
            }
        )
    elif damage == "config":
        r = r.model_copy(
            update={"packet": r.packet.model_copy(update={"model_configuration_hash": "f" * 64})}
        )
    elif damage == "policy":
        r = r.model_copy(
            update={
                "packet": r.packet.model_copy(
                    update={
                        "policy": r.packet.policy.model_copy(update={"max_horizon_seconds": 100})
                    }
                )
            }
        )
    elif damage == "deadline":
        r = r.model_copy(update={"deadline_monotonic": r.deadline_monotonic + 100})
    else:
        r = r.model_copy(
            update={
                "started_monotonic": time.monotonic() - 10,
                "deadline_monotonic": time.monotonic() - 9,
            }
        )
    client, calls = sdk_client()
    with client:
        if damage == "expired":
            assert perform(r, client).error == "TimeoutError"
        else:
            with pytest.raises(ValidationError):
                perform(r, client)
    assert calls == []


def test_factory_keeps_remaining_lease_and_token_cost_must_fit():
    r = request_for()
    later = create_request(
        r.packet, r.configuration, request_id="d" * 32, now=AT + timedelta(seconds=4)
    )
    assert later.deadline_monotonic - later.started_monotonic <= 1
    with pytest.raises(ValueError):
        create_request(r.packet, r.configuration, request_id="d" * 32, now=r.packet.valid_until)
    with pytest.raises(ValidationError):
        configuration(
            CostPolicy(total_budget="1", daily_budget=".1", max_call_cost=".00001"),
            r.configuration.limits,
            r.packet.policy,
        )


@pytest.mark.anyio
async def test_native_worker_main_uses_fixed_private_sdk_and_full_contract(monkeypatch):
    r = request_for()
    out = output_for(r)
    real_spawn = asyncio.create_subprocess_exec
    source = (
        f"import sys,os\nsys.path.insert(0,{str(Path(__file__).parent.parent)!r})\n"
        f"sys.path.insert(0,{str(Path(__file__).parent)!r})\n"
        "import app.options.entry_judgment_worker as worker\n"
        "from test_execution_judgment import sdk_client\n"
        f"output={out!r}\n"
        "def factory(**kw):\n"
        " assert kw['base_url']=='https://api.openai.com/v1' and kw['max_retries']==0\n"
        " assert kw['api_key']=='fixture-only'\n"
        " assert 'ROBINHOOD_TOKEN' not in os.environ and 'PYTHONPATH' not in os.environ\n"
        " return sdk_client(output=output)[0]\n"
        "worker.OpenAI=factory\nraise SystemExit(worker.main())\n"
    )

    async def spawn(*args, **kwargs):
        assert args == (sys.executable, "-I", "-m", "app.options.entry_judgment_worker")
        assert set(kwargs["env"]) <= {"PATH", "LANG", "LC_ALL", "OPENAI_API_KEY"}
        return await real_spawn(sys.executable, "-I", "-c", source, **kwargs)

    monkeypatch.setenv("ROBINHOOD_TOKEN", "not-for-model")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = await run_entry_process(r, "fixture-only")
    assert result.error is None and result.plan == plan_for(r.packet)
    assert result.usage.input_tokens == 1000


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["stall", "overflow", "invalid", "lineage", "usage", "exit"])
async def test_native_failures_are_bounded_and_reaped(monkeypatch, failure):
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    r = request_for(seconds=0.5)
    real_spawn, children = asyncio.create_subprocess_exec, []
    source = "import sys,time,signal\nsys.stdin.read()\n"
    if failure == "stall":
        source += "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)"
    elif failure == "overflow":
        source += f"sys.stdout.write('x'*{MAX_RESPONSE_BYTES * 2})"
    elif failure == "invalid":
        source += "sys.stdout.write('{}')"
    elif failure in {"lineage", "usage"}:
        result = receipt(r)
        if failure == "lineage":
            result = result.model_copy(update={"request_id": "f" * 32})
        else:
            result = result.model_copy(update={"counted_input_tokens": 999})
        source += f"sys.stdout.write({result.model_dump_json()!r})"
    else:
        source += "sys.exit(8)"

    async def spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-I", "-c", source, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises((ValueError, TimeoutError)):
        await run_entry_process(r, "fixture-only")
    assert len(children) == 1 and children[0].returncode is not None


@pytest.mark.anyio
async def test_repeated_cancel_reaps_even_term_ignoring_child(monkeypatch, tmp_path):
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    r = request_for()
    real_spawn, children = asyncio.create_subprocess_exec, []
    ready = tmp_path / "ready"
    source = (
        "import pathlib,sys,time,signal\nsys.stdin.read()\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        f"pathlib.Path({str(ready)!r}).touch()\ntime.sleep(60)"
    )

    async def spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-I", "-c", source, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(run_entry_process(r, "fixture-only"))
    async with asyncio.timeout(3):
        while not ready.exists():
            await asyncio.sleep(0.005)
    task.cancel()
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(children[0].pid, 0)
