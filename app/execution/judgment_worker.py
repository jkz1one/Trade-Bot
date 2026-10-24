"""Private bounded Responses child: model credential only, no journal or broker handles."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout

from agents import AgentOutputSchema
from openai import OpenAI

from app.agent.prompts import TRADER_INSTRUCTIONS, TRADER_PROMPT_VERSION
from app.agent.trader import fail_closed_agent_run
from app.domain.models import TradeDecision
from app.execution.economics import UsageEvidence
from app.execution.judgment import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    JudgmentDiagnostics,
    JudgmentRequest,
    JudgmentResult,
    request_content,
)


def _decision_text(response):
    """Accept one final decision message, never aggregate away refusals or fragments."""
    messages = []
    for item in response.output:
        if item.type == "reasoning":
            if item.status not in {None, "completed"}:
                raise ValueError("Reasoning output did not complete")
        elif item.type == "message":
            messages.append(item)
        else:
            raise ValueError("Unexpected tool or other output")
    if len(messages) != 1:
        raise ValueError("Exactly one decision message is required")
    message = messages[0]
    if (
        message.role != "assistant"
        or message.status != "completed"
        or message.phase not in {None, "final_answer"}
        or len(message.content) != 1
    ):
        raise ValueError("Decision message is not a single completed final answer")
    content = message.content[0]
    if content.type != "output_text" or not isinstance(content.text, str):
        raise ValueError("Decision message must contain only output text")
    return content.text


def perform(request, client):
    """Count the exact text/schema/tools payload, generate once, preserve valid usage on HOLD."""
    usage, count = None, None
    started = time.monotonic()
    observations = {
        name: {"attempted": 0, "completed": 0, "elapsed_seconds": 0.0}
        for name in ("input_count", "generation")
    }

    def observe(name, function):
        entry = observations[name]
        entry["attempted"] += 1
        before = time.monotonic()
        try:
            value = function()
            entry["completed"] += 1
            return value
        finally:
            entry["elapsed_seconds"] += time.monotonic() - before

    def finish(decision, error=None):
        return JudgmentResult(
            decision=decision,
            usage=usage,
            counted_input_tokens=count,
            error=error,
            diagnostics=JudgmentDiagnostics(
                perform_seconds=time.monotonic() - started,
                **observations,
            ),
        )

    try:
        content = request_content(request.model, request.packet)

        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

        expected = {
            "policy": "bounded-responses-v1",
            "limits": request.limits.model_dump(mode="json"),
            "prompt_version": TRADER_PROMPT_VERSION,
            "prompt_hash": digest(TRADER_INSTRUCTIONS),
            "schema_hash": digest(AgentOutputSchema(TradeDecision).json_schema()),
        }
        if any(request.configuration.get(k) != v for k, v in expected.items()):
            raise ValueError("Judgment configuration changed")
        if time.monotonic() >= request.deadline_monotonic:
            raise TimeoutError("Judgment deadline expired")
        count = observe(
            "input_count", lambda: client.responses.input_tokens.count(**content)
        ).input_tokens
        if type(count) is not int or not 0 < count <= request.limits.max_input_tokens:
            count = None
            raise ValueError("Input count is unavailable or exceeds the ceiling")
        if time.monotonic() >= request.deadline_monotonic:
            raise TimeoutError("Judgment deadline expired")
        response = observe(
            "generation",
            lambda: client.responses.create(
                **content,
                max_output_tokens=request.limits.max_output_tokens,
                store=False,
                background=False,
                stream=False,
            ),
        )
        # Capture provider usage before parsing, refusals or incomplete output can fail.
        usage = UsageEvidence(
            request_id=response.id,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        if response.status != "completed" or response.error is not None:
            raise ValueError("Response did not complete")
        decision = AgentOutputSchema(TradeDecision).validate_json(_decision_text(response))
        return finish(decision)
    except Exception as exc:  # noqa: BLE001 -- preserve usage even when decision parsing fails
        return finish(fail_closed_agent_run(exc).decision, type(exc).__name__)


def _watch(request):
    while os.getppid() == request.parent_pid and time.monotonic() < request.deadline_monotonic:
        time.sleep(0.05)
    os._exit(99)  # A parent crash or deadline cannot leave an API child running indefinitely.


def main():
    output = sys.stdout
    with open(os.devnull, "w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
        try:
            data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
            if len(data) > MAX_REQUEST_BYTES:
                raise ValueError("Request too large")
            request = JudgmentRequest.model_validate_json(data)
            if os.getppid() != request.parent_pid:
                raise ValueError("Parent identity changed")
            threading.Thread(target=_watch, args=(request,), daemon=True).start()
            with OpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                base_url="https://api.openai.com/v1",
                timeout=request.limits.request_timeout_seconds,
                max_retries=0,
            ) as client:
                result = perform(request, client)
        except Exception as exc:  # noqa: BLE001 -- sanitized private subprocess protocol
            result = JudgmentResult(
                decision=fail_closed_agent_run(exc).decision, error=type(exc).__name__
            )
        response = result.model_dump_json()
        if len(response.encode()) > MAX_RESPONSE_BYTES:
            return 1
    output.write(response)
    output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
