import asyncio
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.models import Action
from app.execution import judgment
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentDiagnostics, process_evidence
from app.execution.judgment_worker import perform
from tests.test_execution_judgment import response, sdk_client, setup
from tests.test_execution_rehearsal import NOW, packet


def observations(**updates):
    return {
        "perform_seconds": 1.0,
        "input_count": {"attempted": 1, "completed": 1, "elapsed_seconds": 0.2},
        "generation": {"attempted": 1, "completed": 1, "elapsed_seconds": 0.3},
        **updates,
    }


def recorded(engine, kind="MODEL_JUDGMENT_RECORDED"):
    return next(e["payload"] for e in engine.journal.report(now=NOW)["events"] if e["kind"] == kind)


def test_worker_measures_fixed_calls_without_changing_payload_or_retaining_secrets(tmp_path):
    *_, request = setup(tmp_path)
    client, calls = sdk_client()
    with client:
        result = perform(request, client)
    observed = result.diagnostics
    assert observed.input_count.attempted == observed.input_count.completed == 1
    assert observed.generation.attempted == observed.generation.completed == 1
    assert (
        0
        <= observed.input_count.elapsed_seconds + observed.generation.elapsed_seconds
        <= observed.perform_seconds
        < 2
    )
    assert len(calls) == 2
    assert calls[0][1] == judgment.request_content(request.model, request.packet)
    assert calls[1][1] == {
        **calls[0][1],
        "max_output_tokens": 1024,
        "store": False,
        "background": False,
        "stream": False,
    }
    serialized = observed.model_dump_json()
    assert "MARKET_PACKET" not in serialized and "resp-test" not in serialized
    assert "fixture-only" not in serialized and "instructions" not in serialized


@pytest.mark.parametrize(
    "phase",
    ["configuration", "deadline", "count_limit", "count_failure", "generation_failure", "refusal"],
)
def test_partial_and_failed_worker_observations_preserve_existing_hold_usage(tmp_path, phase):
    *_, request = setup(tmp_path)
    client, calls = sdk_client(
        count=100000 if phase == "count_limit" else 1000, failure=phase == "count_failure"
    )
    if phase == "configuration":
        request = request.model_copy(update={"configuration": {}})
    if phase == "deadline":
        request = request.model_copy(update={"deadline_monotonic": 1.0})
    if phase == "generation_failure":

        def fail(**kwargs):
            raise RuntimeError("private SDK error")

        client.responses.create = fail
    if phase == "refusal":
        client, calls = sdk_client(
            output=response(
                output=[
                    {
                        **response()["output"][0],
                        "content": [{"type": "refusal", "refusal": "private refusal"}],
                    }
                ]
            )
        )
    with client:
        result = perform(request, client)
    assert result.error is not None and result.decision.action == Action.HOLD
    count, generation = result.diagnostics.input_count, result.diagnostics.generation
    if phase in {"configuration", "deadline"}:
        assert count.attempted == generation.attempted == 0 and calls == []
    elif phase == "count_failure":
        assert count.attempted == 1 and count.completed == generation.attempted == 0
    elif phase == "count_limit":
        assert count.completed == 1 and generation.attempted == 0
    elif phase == "generation_failure":
        assert count.completed == generation.attempted == 1 and generation.completed == 0
    else:
        assert (
            count.completed == generation.completed == 1 and result.usage.request_id == "resp-test"
        )
    assert (result.usage is not None) == (phase == "refusal")
    assert count.elapsed_seconds + generation.elapsed_seconds <= result.diagnostics.perform_seconds
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize(
    "field,value",
    [
        ("perform_seconds", float("nan")),
        ("perform_seconds", float("inf")),
        ("perform_seconds", -1.0),
        ("perform_seconds", 121.0),
        ("perform_seconds", "1"),
        ("attempted", True),
        ("attempted", 2),
        ("attempted", -1),
        ("attempted", "1"),
        ("completed", True),
        ("completed", 2),
        ("elapsed_seconds", -1.0),
        ("elapsed_seconds", 121.0),
        ("elapsed_seconds", float("nan")),
        ("elapsed_seconds", "1"),
    ],
)
def test_invalid_diagnostic_types_or_bounds_fail_the_protocol(field, value):
    raw = observations()
    if field == "perform_seconds":
        raw[field] = value
    else:
        raw["input_count"][field] = value
    with pytest.raises(ValidationError):
        JudgmentDiagnostics.model_validate(raw)


def test_completed_diagnostic_requires_a_recorded_attempt():
    raw = observations(input_count={"attempted": 0, "completed": 1, "elapsed_seconds": 0.0})
    with pytest.raises(ValidationError):
        JudgmentDiagnostics.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        observations(perform_seconds=3.0),
        observations(perform_seconds=0.1),
        observations(input_count={"attempted": 0, "completed": 0, "elapsed_seconds": 0.0}),
        observations(generation={"attempted": 0, "completed": 0, "elapsed_seconds": 0.0}),
    ],
)
def test_missing_or_incoherent_observations_cannot_claim_acceptance(tmp_path, raw):
    *_, request = setup(tmp_path)
    client, _ = sdk_client()
    with client:
        result = perform(request, client)
    result = result.model_copy(
        update={"diagnostics": JudgmentDiagnostics.model_validate(raw) if raw else None}
    )
    evidence = process_evidence(request, result, started=10.0, invoked=11.0, finished=13.0)
    assert evidence["admission_seconds"] == 1 and evidence["invocation_and_reap_seconds"] == 2
    assert evidence["total_seconds"] == 3 and evidence["process_timeout_seconds"] == 30
    assert evidence["request_timeout_seconds"] == 20
    assert evidence["observations_status"] == "UNVERIFIED"
    assert evidence["provider_acceptance"] == evidence["billing_acceptance"] == "UNVERIFIED"
    assert not evidence["execution_authority"]


@pytest.mark.anyio
async def test_durable_observations_link_packet_policy_usage_and_preserve_approval(
    tmp_path, monkeypatch
):
    engine, _, _, costs, coordinator, _ = setup(tmp_path)
    engine.journal.enable_restore_fence(now=NOW)
    frozen = judgment.configuration(costs, coordinator.limits)

    async def run(request, key):
        assert key == "fixture-only"
        client, _ = sdk_client()
        with client:
            return perform(request, client)

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    out = await coordinator.decide(
        "evidence", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    payload = recorded(engine)
    evidence = payload["process_evidence"]
    assert evidence["observations_status"] == "OBSERVED"
    assert evidence["configuration"] == frozen == judgment.configuration(costs, coordinator.limits)
    with engine.journal.read() as db:
        row = db.execute(
            "SELECT * FROM execution_model_calls WHERE source_key='evidence'"
        ).fetchone()
        assert evidence["packet_hash"] == row["packet_hash"]
        assert json.loads(row["usage_json"]) == payload["result"]["usage"]
    assert out.estimated_cost == Decimal(".00015")
    assert engine.prepare("evidence", out.result.decision, out.packet, now=NOW)
    assert "fixture-only" not in json.dumps(evidence)
    assert engine.journal.report(now=NOW)["restore_fence"]["status"] == "VERIFIED"


@pytest.mark.anyio
async def test_absent_diagnostics_do_not_change_existing_accounting_or_approval(
    tmp_path, monkeypatch
):
    engine, _, _, _, coordinator, _ = setup(tmp_path)

    async def run(request, key):
        client, _ = sdk_client()
        with client:
            return perform(request, client).model_copy(update={"diagnostics": None})

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    out = await coordinator.decide(
        "legacy", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    assert recorded(engine)["process_evidence"]["observations_status"] == "UNVERIFIED"
    assert engine.prepare("legacy", out.result.decision, out.packet, now=NOW)
    assert out.estimated_cost == Decimal(".00015")


@pytest.mark.anyio
async def test_cancelled_reaped_work_keeps_unknown_cost_and_interruption_evidence(
    tmp_path, monkeypatch
):
    engine, _, _, _, coordinator, _ = setup(tmp_path)
    begun, reaped = asyncio.Event(), asyncio.Event()

    async def run(request, key):
        begun.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.005)
            reaped.set()

    monkeypatch.setattr(judgment, "run_judgment_process", run)
    task = asyncio.create_task(
        coordinator.decide("cancel", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW)
    )
    await asyncio.wait_for(begun.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reaped.is_set()
    evidence = recorded(engine, "MODEL_JUDGMENT_INTERRUPTED")["process_evidence"]
    assert evidence["invocation_and_reap_seconds"] >= 0.005
    assert evidence["observations"] is None and evidence["observations_status"] == "UNVERIFIED"
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
    with pytest.raises(ExecutionBlocked):
        await coordinator.decide(
            "cancel", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )


@pytest.mark.anyio
async def test_actual_private_worker_records_two_calls_and_is_reaped_before_evidence(
    tmp_path, monkeypatch
):
    engine, _, _, _, coordinator, _ = setup(tmp_path)
    spawn_original = asyncio.create_subprocess_exec
    children = []
    source = """
import httpx2, json
from openai import OpenAI
from app.execution import judgment_worker as worker
def transport(request):
    if request.url.path.endswith('input_tokens'):
        return httpx2.Response(200,json={'object':'response.input_tokens','input_tokens':1000})
    return httpx2.Response(200,json=json.loads(OUTPUT))
worker.OpenAI=lambda **kw: OpenAI(**kw,http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))
raise SystemExit(worker.main())
""".replace("OUTPUT", repr(json.dumps(response())))

    async def spawn(*args, **kwargs):
        assert args[1:3] == ("-I", "-m")
        assert set(kwargs["env"]) <= {"PATH", "LANG", "LC_ALL", "OPENAI_API_KEY"}
        child = await spawn_original(*args[:2], "-c", source, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    out = await coordinator.decide(
        "native", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    evidence = recorded(engine)["process_evidence"]
    assert len(children) == 1 and children[0].returncode == 0
    assert evidence["observations_status"] == "OBSERVED"
    assert (
        evidence["observations"]["input_count"]["completed"]
        == evidence["observations"]["generation"]["completed"]
        == 1
    )
    assert evidence["invocation_and_reap_seconds"] >= evidence["observations"]["perform_seconds"]
    assert out.estimated_cost == Decimal(".00015")
