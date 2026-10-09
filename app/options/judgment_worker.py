"""Private Responses child; no broker, execution journal or order handles."""

import os
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout

from agents import AgentOutputSchema
from openai import OpenAI

from app.execution.economics import UsageEvidence
from app.execution.judgment import JudgmentDiagnostics
from app.execution.judgment_worker import _decision_text, _watch
from app.options.engine import fingerprint
from app.options.judgment import (
    INSTRUCTIONS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PROMPT_VERSION,
    CandidateChoice,
    CandidateRequest,
    hold,
    request_content,
    result_for,
)


def perform(request, client):
    count, usage = None, None
    started = time.monotonic()
    observations = {
        n: {"attempted": 0, "completed": 0, "elapsed_seconds": 0.0}
        for n in ("input_count", "generation")
    }

    def observe(name, fn):
        row = observations[name]
        row["attempted"] += 1
        at = time.monotonic()
        try:
            value = fn()
            row["completed"] += 1
            return value
        finally:
            row["elapsed_seconds"] += time.monotonic() - at

    def finish(choice=None, error=None):
        return result_for(
            request,
            choice=choice,
            usage=usage,
            count=count,
            error=error,
            diagnostics=JudgmentDiagnostics(
                perform_seconds=time.monotonic() - started, **observations
            ),
        )

    try:
        expected = {
            "policy": "option-candidate-responses-v1",
            "model": request.model,
            "limits": request.limits.model_dump(mode="json"),
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": fingerprint(INSTRUCTIONS),
            "schema_hash": fingerprint(AgentOutputSchema(CandidateChoice).json_schema()),
        }
        if any(request.configuration.get(k) != v for k, v in expected.items()):
            raise ValueError("Candidate configuration changed")
        content = request_content(request)
        if time.monotonic() >= request.deadline_monotonic:
            raise TimeoutError("Candidate deadline expired")
        count = observe(
            "input_count", lambda: client.responses.input_tokens.count(**content)
        ).input_tokens
        if type(count) is not int or not 0 < count <= request.limits.max_input_tokens:
            count = None
            raise ValueError("Input token count unavailable or exceeds ceiling")
        if time.monotonic() >= request.deadline_monotonic:
            raise TimeoutError("Candidate deadline expired")
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
        usage = UsageEvidence(
            request_id=response.id,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        if response.status != "completed" or response.error is not None:
            raise ValueError("Candidate response incomplete")
        choice = AgentOutputSchema(CandidateChoice).validate_json(_decision_text(response))
        if choice.action == "SELECT" and choice.candidate_id not in {
            c.candidate_id for c in request.packet.candidates
        }:
            raise ValueError("Invented candidate ID")
        return finish(choice)
    except Exception as exc:  # noqa: BLE001 -- usage retained; provider errors never echoed
        return finish(hold(), type(exc).__name__)


def main():
    output = sys.stdout
    with open(os.devnull, "w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
        try:
            data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
            if len(data) > MAX_REQUEST_BYTES:
                return 1
            request = CandidateRequest.model_validate_json(data)
            if os.getppid() != request.parent_pid or time.monotonic() >= request.deadline_monotonic:
                return 1
            threading.Thread(target=_watch, args=(request,), daemon=True).start()
            with OpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                base_url="https://api.openai.com/v1",
                timeout=request.limits.request_timeout_seconds,
                max_retries=0,
            ) as client:
                result = perform(request, client)
            data = result.model_dump_json()
            if len(data.encode()) > MAX_RESPONSE_BYTES:
                return 1
        except Exception:  # noqa: BLE001 -- parent retains unknown attempt on protocol failure
            return 1
    output.write(data)
    output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
