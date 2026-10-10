"""Private model subprocess entry point. It receives only a packet and model config."""
from __future__ import annotations

import os
import sys
from contextlib import redirect_stderr, redirect_stdout

from pydantic import BaseModel, ConfigDict, Field

from app.agent.process import MAX_RESPONSE_BYTES, ModelProcessResult
from app.agent.trader import OpenAIAgentsTrader, fail_closed_agent_run
from app.domain.models import MarketPacket


class ModelProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=100)
    packet: MarketPacket
    request_timeout_seconds: float = Field(gt=0, le=120)


def main():
    output = sys.stdout
    # SDK logs/errors cannot expose request/auth details or corrupt the JSON protocol.
    with open(os.devnull, "w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
        try:
            request = ModelProcessRequest.model_validate_json(sys.stdin.buffer.read())
            from agents import set_default_openai_client, set_tracing_disabled
            from openai import AsyncOpenAI

            set_tracing_disabled(True)  # Persisted application audit is authoritative.
            set_default_openai_client(AsyncOpenAI(
                timeout=request.request_timeout_seconds, max_retries=0,
            ), use_for_tracing=False)
            run = OpenAIAgentsTrader(request.model).decide(request.packet)
            response = ModelProcessResult(
                decision=run.decision, input_tokens=run.input_tokens,
                output_tokens=run.output_tokens, error=run.error,
            ).model_dump_json()
            if len(response.encode()) > MAX_RESPONSE_BYTES:
                raise ValueError("Response exceeds protocol limit")
        except Exception as exc:
            run = fail_closed_agent_run(exc)
            response = ModelProcessResult(
                decision=run.decision, input_tokens=0, output_tokens=0, error=run.error,
            ).model_dump_json()
    output.write(response)
    output.flush()


if __name__ == "__main__":
    main()
