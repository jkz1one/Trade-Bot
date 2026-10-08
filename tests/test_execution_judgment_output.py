"""Response-envelope integrity with the pinned SDK and actual private worker."""

import asyncio
import json
import sys
from decimal import Decimal

import pytest

from app.domain.models import Action
from app.execution.engine import ExecutionBlocked
from app.execution.judgment_worker import perform
from tests.test_execution_judgment import response, sdk_client, setup
from tests.test_execution_rehearsal import NOW, decision, packet


def message(**updates):
    return {**response()["output"][0], **updates}


def text(value):
    return {"type": "output_text", "text": value, "annotations": []}


def reasoning(status=None):
    return {"type": "reasoning", "id": "reason-1", "summary": [], "status": status}


DECISION = decision().model_dump_json()
REFUSAL = {"type": "refusal", "refusal": "private-provider-refusal"}
AMBIGUOUS = [
    pytest.param([message(content=[text(DECISION), REFUSAL])], id="text-with-refusal"),
    pytest.param([message(content=[REFUSAL, text(DECISION)])], id="refusal-with-text"),
    pytest.param([message(), message(id="msg-2", content=[REFUSAL])], id="second-message-refusal"),
    pytest.param([message(), message(id="msg-2", content=[text("")])], id="second-empty-message"),
    pytest.param(
        [
            message(content=[text(DECISION[:40])]),
            message(id="msg-2", content=[text(DECISION[40:])]),
        ],
        id="json-split-between-messages",
    ),
    pytest.param(
        [message(content=[text(DECISION[:40]), text(DECISION[40:])])],
        id="json-split-between-content-blocks",
    ),
    pytest.param([message(content=[text(DECISION), text("")])], id="second-empty-block"),
    pytest.param([message(role="user")], id="foreign-role"),
    pytest.param([message(role=None)], id="missing-role"),
    pytest.param([message(status="incomplete")], id="incomplete-message"),
    pytest.param([message(status="in_progress")], id="unfinished-message"),
    pytest.param([message(status=None)], id="missing-message-status"),
    pytest.param([message(phase="commentary")], id="intermediate-commentary"),
    pytest.param([message(phase="unknown")], id="unknown-message-phase"),
    pytest.param([reasoning("incomplete"), message()], id="incomplete-reasoning"),
    pytest.param([reasoning("in_progress"), message()], id="unfinished-reasoning"),
    pytest.param([reasoning("unknown"), message()], id="unknown-reasoning-status"),
    pytest.param([reasoning()], id="no-decision-message"),
]


@pytest.mark.parametrize("output", AMBIGUOUS)
def test_ambiguous_response_is_billed_hold_without_sdk_text_aggregation(tmp_path, output):
    *_, request = setup(tmp_path)
    client, calls = sdk_client(output=response(output=output))
    with client:
        result = perform(request, client)
    assert result.error == "ValueError"
    assert result.decision.action == Action.HOLD
    assert result.usage.request_id == "resp-test"
    assert result.usage.input_tokens == result.counted_input_tokens == 1000
    assert result.usage.output_tokens == 100
    assert len(calls) == 2
    assert "private-provider-refusal" not in result.model_dump_json()


@pytest.mark.parametrize(
    "output",
    [
        [message()],
        [message(phase="final_answer")],
        [reasoning(), message()],
        [reasoning("completed"), message()],
        [message(content=[text(decision(action=Action.HOLD).model_dump_json())])],
    ],
)
def test_single_completed_assistant_decision_and_reasoning_remain_accepted(tmp_path, output):
    *_, request = setup(tmp_path)
    client, calls = sdk_client(output=response(output=output))
    with client:
        result = perform(request, client)
    assert result.error is None
    assert result.decision.model_dump_json() == output[-1]["content"][0]["text"]
    assert result.usage.request_id == "resp-test" and len(calls) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "output",
    [
        [message(content=[text(DECISION), REFUSAL])],
        [message(content=[text(DECISION[:40]), text(DECISION[40:])])],
    ],
    ids=["mixed-refusal", "fragmented-json"],
)
async def test_actual_worker_retains_usage_and_journal_prevents_entry_or_replay(
    tmp_path, monkeypatch, output
):
    engine, _, _, _, coordinator, _ = setup(tmp_path)
    real_spawn = asyncio.create_subprocess_exec
    children = []
    # Only the SDK transport is replaced. Actual installed worker/main, watchdog,
    # bounded parent transport, accounting and deterministic admission run normally.
    source = """
import json
import httpx2
from openai import OpenAI
from app.execution import judgment_worker as worker
output = json.loads(OUTPUT)
calls = []
def transport(request):
    calls.append(request.url.path)
    assert len(calls) <= 2
    if request.url.path == '/v1/responses/input_tokens':
        return httpx2.Response(200, json={'object':'response.input_tokens','input_tokens':1000})
    assert request.url.path == '/v1/responses'
    return httpx2.Response(200, json=output)
worker.OpenAI = lambda **kwargs: OpenAI(
    **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))
raise SystemExit(worker.main())
""".replace("OUTPUT", repr(json.dumps(response(output=output))))

    async def spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-c", source, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    outcome = await coordinator.decide(
        "ambiguous", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
    )
    assert outcome.result.error == "ValueError"
    assert outcome.result.decision.action == Action.HOLD
    assert outcome.estimated_cost == Decimal(".00015")
    assert engine.prepare("ambiguous", outcome.result.decision, outcome.packet, now=NOW) is None
    # The hidden OPEN_LONG cannot be substituted for the persisted failed judgment.
    with pytest.raises(ExecutionBlocked):
        engine.prepare("ambiguous", decision(), outcome.packet, now=NOW)
    with pytest.raises(ExecutionBlocked, match="MODEL_SOURCE_ALREADY_ATTEMPTED"):
        await coordinator.decide(
            "ambiguous", packet(), api_key="fixture-only", now=NOW, clock=lambda: NOW
        )
    report = engine.journal.report(now=NOW)
    assert report["orders"] == [] and report["economics"]["unknown_calls"] == 0
    alerts = engine.journal.alerts()
    assert len(alerts) == 1 and alerts[0]["kind"] == "MODEL_JUDGMENT_RECORDED"
    assert "private-provider-refusal" not in json.dumps(alerts)
    assert len(children) == 1 and children[0].returncode == 0
