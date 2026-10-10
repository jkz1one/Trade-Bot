"""Private bounded entry reasoning child; no broker, journal or execution handles."""

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
from app.options.entry_judgment import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    EntryRequest,
    request_content,
    result_for,
    validate_result,
)
from app.options.entry_reasoning import EntryPlan


def perform(request, client):
    request = EntryRequest.model_validate(request.model_dump(warnings=False))
    count, usage = None, None
    started = time.monotonic()
    limits = request.configuration.limits
    observations = {
        n: {"attempted": 0, "completed": 0, "elapsed_seconds": 0.0}
        for n in ("input_count", "generation")
    }

    def observe(name, fn):
        row, at = observations[name], time.monotonic()
        row["attempted"] += 1
        try:
            value = fn()
            row["completed"] += 1
            return value
        finally:
            row["elapsed_seconds"] += time.monotonic() - at

    def finish(plan=None, error=None):
        return result_for(
            request,
            plan=plan,
            usage=usage,
            count=count,
            error=error,
            diagnostics=JudgmentDiagnostics(
                perform_seconds=time.monotonic() - started, **observations
            ),
        )

    def timely():
        if not request.started_monotonic <= time.monotonic() < request.deadline_monotonic:
            raise TimeoutError("Entry reasoning deadline expired")

    try:
        timely()
        content = request_content(request)
        count = observe(
            "input_count", lambda: client.responses.input_tokens.count(**content)
        ).input_tokens
        if type(count) is not int or not 0 < count <= limits.max_input_tokens:
            count = None
            raise ValueError("Input token count missing or above ceiling")
        timely()
        response = observe(
            "generation",
            lambda: client.responses.create(
                **content,
                max_output_tokens=limits.max_output_tokens,
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
        timely()
        if response.status != "completed" or response.error is not None:
            raise ValueError("Entry response incomplete")
        plan = AgentOutputSchema(EntryPlan).validate_json(_decision_text(response))
        validated = validate_result(request, finish(plan))
        timely()
        return validated
    except Exception as exc:  # noqa: BLE001 -- retain usage, never echo provider errors
        return finish(error=type(exc).__name__)


def main():
    output = sys.stdout
    with open(os.devnull, "w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
        try:
            data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
            if len(data) > MAX_REQUEST_BYTES:
                return 1
            request = EntryRequest.model_validate_json(data)
            if (
                os.getppid() != request.parent_pid
                or not request.started_monotonic <= time.monotonic() < request.deadline_monotonic
            ):
                return 1
            threading.Thread(target=_watch, args=(request,), daemon=True).start()
            with OpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                base_url="https://api.openai.com/v1",
                timeout=request.configuration.limits.request_timeout_seconds,
                max_retries=0,
            ) as client:
                result = perform(request, client)
            data = result.model_dump_json()
            if len(data.encode()) > MAX_RESPONSE_BYTES:
                return 1
        except Exception:  # noqa: BLE001 -- parent must retain uncertain attempt
            return 1
    output.write(data)
    output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
