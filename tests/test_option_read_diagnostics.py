"""Failure evidence reveals bounded classes/codes without credential-bearing text."""

import asyncio
import json
import subprocess
import sys
from contextlib import asynccontextmanager

import httpx2
import pytest
from test_option_read_capture import Client, plan, request

from app.options import read_cli, read_worker
from app.options.read_capture import CaptureFailure, CaptureResult, failure_evidence
from app.options.read_gateway import OptionReadGateway


def http_failure(code="invalid_grant", status=400):
    req = httpx2.Request(
        "POST", "https://example.invalid/PRIVATE-URL", headers={"Authorization": "PRIVATE-TOKEN"}
    )
    response = httpx2.Response(
        status,
        request=req,
        json={
            "error": code,
            "error_description": "PRIVATE-DESCRIPTION",
            "access_token": "PRIVATE-TOKEN",
        },
    )
    return httpx2.HTTPStatusError("PRIVATE-MESSAGE", request=req, response=response)


def test_nested_group_keeps_only_safe_classes_status_and_oauth_code():
    exc = ExceptionGroup(
        "PRIVATE-GROUP",
        [ExceptionGroup("PRIVATE-INNER", [http_failure()]), RuntimeError("PRIVATE-OTHER")],
    )
    result = failure_evidence(exc, "CONNECT")
    assert [c.error_class for c in result.causes] == [
        "ExceptionGroup",
        "ExceptionGroup",
        "RuntimeError",
        "HTTPStatusError",
    ]
    assert result.causes[-1].http_status == 400 and result.causes[-1].oauth_error == "invalid_grant"
    assert not result.truncated and "PRIVATE" not in result.model_dump_json()


@pytest.mark.parametrize("code", ["PRIVATE-TOKEN", {"private": "PRIVATE"}, None, "x" * 9000])
def test_unrecognized_or_oversized_response_never_appears(code):
    result = failure_evidence(http_failure(code), "CONNECT")
    assert result.causes[0].http_status == 400 and result.causes[0].oauth_error is None
    assert "PRIVATE" not in result.model_dump_json()


def test_cause_links_cycles_depth_and_count_are_bounded():
    first, second = RuntimeError("PRIVATE"), ValueError("PRIVATE")
    first.__cause__ = second
    second.__cause__ = first
    assert len(failure_evidence(first, "PARENT").causes) == 2
    group = ExceptionGroup("PRIVATE", [RuntimeError("PRIVATE") for _ in range(100)])
    result = failure_evidence(group, "CONNECT")
    assert len(result.causes) == 16 and result.truncated
    for _ in range(10):
        group = ExceptionGroup("PRIVATE", [group])
    result = failure_evidence(group, "CONNECT")
    assert len(result.causes) == 5 and result.truncated


@pytest.mark.parametrize("stage", ["CONNECT", "DISCOVER", "VALIDATE_PLAN", "MARKET_READ", "CLOSE"])
def test_worker_records_failure_stage_without_unintended_reads(tmp_path, monkeypatch, stage):
    class Failing(Client):
        async def list_tools(self):
            if stage == "DISCOVER":
                raise ExceptionGroup("PRIVATE", [http_failure("invalid_client", 401)])
            return await super().list_tools()

        async def call_tool(self, name, arguments):
            assert stage == "MARKET_READ"
            self.calls.append((name, arguments))
            raise RuntimeError("PRIVATE")

    client = Failing()
    schemas = asyncio.run(OptionReadGateway(Client()).discover())
    p = plan() if stage in {"MARKET_READ", "VALIDATE_PLAN"} else None
    if stage == "VALIDATE_PLAN":
        p = p.model_copy(update={"calls": (p.calls[0].model_copy(update={"arguments": {}}),)})

    @asynccontextmanager
    async def context():
        if stage == "CONNECT":
            raise ExceptionGroup("PRIVATE", [http_failure()])
        yield client
        if stage == "CLOSE":
            raise RuntimeError("PRIVATE")

    class Connection:
        client = staticmethod(context)

    monkeypatch.setattr(read_worker, "connection", lambda policy: Connection())
    req = request(tmp_path, schemas if p else None, p)
    result = asyncio.run(read_worker.collect(req))
    assert result.status == "FAILED" and result.failure.stage == stage
    assert len(client.calls) == int(stage == "MARKET_READ")
    assert "PRIVATE" not in result.model_dump_json()
    assert (
        result.schemas is None if stage in {"CONNECT", "DISCOVER"} else result.schemas is not None
    )


def test_headless_login_stays_blocked_with_a_distinct_safe_class(tmp_path):
    req = request(tmp_path)
    connection = read_worker.connection(req.policy)
    for handler in (connection.redirect_handler, connection.callback_handler):
        with pytest.raises(read_worker.ReadAuthorizationRequired):
            asyncio.run(handler("PRIVATE-LOGIN-URL"))


def test_native_worker_serializes_safe_nested_failure(tmp_path):
    script = tmp_path / "diagnostic_child.py"
    script.write_text("""from contextlib import asynccontextmanager
import httpx2
from app.options import read_worker
@asynccontextmanager
async def client():
    req=httpx2.Request("POST","https://example.invalid/PRIVATE")
    response=httpx2.Response(401,request=req,json={"error":"invalid_client","error_description":"PRIVATE"})
    raise ExceptionGroup("PRIVATE",[httpx2.HTTPStatusError("PRIVATE",request=req,response=response)])
    yield
class Connection:
    client=staticmethod(client)
read_worker.connection=lambda policy:Connection()
raise SystemExit(read_worker.main())
""")
    req = request(tmp_path)
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", str(script)],
        input=req.model_dump_json(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0 and "PRIVATE" not in result.stdout + result.stderr
    value = CaptureResult.model_validate_json(result.stdout)
    assert value.failure.stage == "CONNECT" and value.failure.causes[1].http_status == 401
    assert not value.observations and value.schemas is None


def test_cli_emits_safe_failure_and_preserves_old_result_compatibility(
    tmp_path, monkeypatch, capsys
):
    tmp_path.chmod(0o700)
    req = request(tmp_path)

    async def fake_collect(policy, **kwargs):
        result = await read_worker.collect(req)
        assert result.failure is not None
        return result

    @asynccontextmanager
    async def context():
        raise ExceptionGroup("PRIVATE", [http_failure()])
        yield

    class Connection:
        client = staticmethod(context)

    monkeypatch.setattr(read_worker, "connection", lambda policy: Connection())
    monkeypatch.setattr(read_cli, "collect", fake_collect)
    output = tmp_path / "diagnostic.json"
    assert (
        read_cli.main(["discover", "--oauth-file", req.policy.oauth_file, "--output", str(output)])
        == 1
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["failure"]["stage"] == "CONNECT" and summary["completed_reads"] == 0
    artifact = json.loads(output.read_text())
    assert "PRIVATE" not in output.read_text() + json.dumps(summary)
    legacy = artifact["result"]
    legacy.pop("failure")
    restored = CaptureResult.model_validate(legacy)
    assert restored.failure is None and "failure" not in restored.model_dump()
    with pytest.raises(ValueError, match="diagnostics"):
        CaptureResult.model_validate(
            legacy
            | {"failure": CaptureFailure(stage="CONNECT", causes=({"error_class": "OtherError"},))}
        )
