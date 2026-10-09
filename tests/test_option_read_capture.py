"""Read-only schema/sample acquisition, private artifacts and native process bounds."""

import asyncio
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from app.domain.models import utc_now
from app.options import read_capture, read_cli, read_worker
from app.options.read_capture import (
    CapturePolicy,
    CaptureRequest,
    CaptureResult,
    collect,
    policy_digest,
)
from app.options.read_gateway import READ_TOOLS, CapturePlan, OptionReadGateway, ReadSample
from app.robinhood.gateway import (
    RobinhoodMarketReadGateway,
    RobinhoodSafeGateway,
    UnsafeRobinhoodToolError,
)


def metadata(output=True):
    result = []
    for name in sorted(READ_TOOLS):
        item = {
            "name": name,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subjects": {"type": "array", "items": {"type": "string"}, "maxItems": 8}
                },
                "required": ["subjects"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        }
        if output:
            item["outputSchema"] = {
                "type": "object",
                "properties": {"rows": {"type": "array"}},
                "required": ["rows"],
                "additionalProperties": False,
            }
        result.append(item)
    return result


class Client:
    def __init__(self, tools=None, result=None):
        self.tools = metadata() if tools is None else tools
        self.result = (
            {"isError": False, "structuredContent": {"rows": []}} if result is None else result
        )
        self.calls = []
        self.discoveries = 0

    async def list_tools(self):
        self.discoveries += 1
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def plan(*tools):
    return CapturePlan(
        purpose="SCHEMA_MAPPING_EVIDENCE",
        symbols=("SPY",),
        instrument_ids=("owned-id",),
        calls=tuple(
            ReadSample(label=f"sample-{n}", tool=t, arguments={"subjects": ["owned-id"]})
            for n, t in enumerate(tools or ("get_option_quotes",))
        ),
    )


def oauth(path):
    p = path / "oauth.json"
    p.write_text(
        json.dumps(
            {
                "tokens": {"access_token": "PRIVATE-TOKEN"},
                "client_info": {"client_id": "PRIVATE-CLIENT"},
            }
        )
    )
    p.chmod(0o600)
    return p


def request(path, schemas=None, p=None):
    return CaptureRequest(
        operation="CAPTURE" if p else "DISCOVER",
        policy=CapturePolicy(oauth_file=str(oauth(path)), timeout_seconds=5),
        request_id="a" * 32,
        started_at=utc_now(),
        parent_pid=os.getpid(),
        deadline_monotonic=time.monotonic() + 5,
        schemas=schemas,
        plan=p,
    )


def test_discovery_retains_only_fixed_read_metadata_and_makes_zero_calls():
    client = Client(
        metadata()
        + [
            {"name": "place_option_order"},
            {"name": "get_accounts"},
            {"name": "review_option_order"},
        ]
    )
    g = OptionReadGateway(client)
    s = asyncio.run(g.discover())
    assert set(s.tools) == READ_TOOLS and not s.missing_tools and not client.calls
    assert "place_option_order" not in s.model_dump_json()


@pytest.mark.parametrize(
    "tool",
    [
        "place_option_order",
        "cancel_option_order",
        "exercise_option",
        "review_option_order",
        "review_equity_order",
        "get_accounts",
        "get_option_orders",
        "get_option_positions",
        "update_watchlist",
    ],
)
def test_forbidden_capabilities_never_reach_client(tool):
    client = Client()
    g = OptionReadGateway(client)
    unsafe = plan().calls[0].model_copy(update={"tool": tool})
    with pytest.raises(UnsafeRobinhoodToolError):
        asyncio.run(g.sample(unsafe, None))
    assert not client.calls and client.discoveries == 0


@pytest.mark.parametrize("gateway", [RobinhoodSafeGateway, RobinhoodMarketReadGateway])
def test_existing_legacy_firewalls_still_deny_option_reads(gateway):
    client = Client()
    with pytest.raises(UnsafeRobinhoodToolError):
        asyncio.run(gateway(client, "endpoint").call_safe("get_option_quotes", {}))
    assert not client.calls


@pytest.mark.parametrize("fault", ["duplicate", "bad_inventory", "too_many", "oversize"])
def test_invalid_schema_inventory_fails_without_call(fault):
    tools = metadata()
    if fault == "duplicate":
        tools.append(tools[0])
    if fault == "bad_inventory":
        tools = [None]
    if fault == "too_many":
        tools = [{"name": str(n)} for n in range(257)]
    if fault == "oversize":
        tools[0]["description"] = "x" * (128 * 1024)
    g = OptionReadGateway(Client(tools))
    with pytest.raises(ValueError):
        asyncio.run(g.discover())
    assert not g.client.calls


@pytest.mark.parametrize(
    "fault",
    [
        "changed",
        "missing_input",
        "mutation",
        "annotation",
        "remote_input",
        "remote_output",
        "late_arguments",
    ],
)
def test_all_plan_admission_precedes_first_provider_call(tmp_path, monkeypatch, fault):
    client = Client()
    g = OptionReadGateway(client)
    expected = asyncio.run(g.discover())
    p = plan("get_option_quotes", "get_equity_quotes")
    if fault == "changed":
        client.tools[0]["description"] = "drift"
        asyncio.run(g.discover())
    if fault == "missing_input":
        client.tools[-1].pop("inputSchema")
        expected = asyncio.run(g.discover())
        p = plan(client.tools[-1]["name"])
    if fault == "mutation":
        g.schemas.tools["get_option_quotes"]["description"] = "drift"
    if fault == "annotation":
        client.tools[0]["annotations"] = {"readOnlyHint": False}
        expected = asyncio.run(g.discover())
        p = plan(client.tools[0]["name"])
    if fault.startswith("remote_"):
        key = "inputSchema" if fault == "remote_input" else "outputSchema"
        client.tools[0][key] = {"$ref": "https://127.0.0.1:1/never"}
        expected = asyncio.run(g.discover())
        p = plan(client.tools[0]["name"])
    if fault == "late_arguments":
        p = p.model_copy(
            update={
                "calls": (p.calls[0], p.calls[1].model_copy(update={"arguments": {"wrong": True}}))
            }
        )
    with pytest.raises((ValueError, SchemaValidationError)):
        g.validate_plan(p, expected)
    assert not client.calls


def test_missing_output_schema_is_raw_sample_evidence_not_normalized_acceptance():
    client = Client(
        metadata(output=False), {"content": [{"type": "text", "text": "PRIVATE RAW SAMPLE"}]}
    )
    g = OptionReadGateway(client)
    s = asyncio.run(g.discover())
    raw, checked = asyncio.run(g.sample(plan().calls[0], s))
    assert not checked and raw == client.result and set(s.missing_output_schemas) == READ_TOOLS


@pytest.mark.parametrize(
    "result",
    [
        {"isError": True},
        {"isError": "false"},
        {"isError": False, "structuredContent": {"bad": []}},
        {"isError": False, "content": []},
        {"isError": False, "structuredContent": {"rows": ["x" * (128 * 1024)]}},
    ],
)
def test_failed_bad_or_oversize_sample_cannot_complete(result):
    g = OptionReadGateway(Client(result=result))
    s = asyncio.run(g.discover())
    with pytest.raises((ValueError, SchemaValidationError)):
        asyncio.run(g.sample(plan().calls[0], s))
    assert len(g.client.calls) == 1


def test_worker_retains_successful_prefix_and_sanitizes_failed_read(tmp_path, monkeypatch):
    class Failing(Client):
        async def call_tool(self, name, arguments):
            if self.calls:
                raise RuntimeError("PRIVATE-TOKEN broker details")
            return await super().call_tool(name, arguments)

    client = Failing()
    g = OptionReadGateway(client)
    s = asyncio.run(g.discover())

    @asynccontextmanager
    async def connection_client():
        yield client

    class Connection:
        client = staticmethod(connection_client)

    monkeypatch.setattr(read_worker, "connection", lambda p: Connection())
    req = request(tmp_path, s, plan("get_option_quotes", "get_equity_quotes"))
    result = asyncio.run(read_worker.collect(req))
    assert result.status == "FAILED" and result.error_class == "RuntimeError"
    assert result.observations[0]["completed"] is True
    assert result.observations[1]["completed"] is False
    assert "PRIVATE-TOKEN" not in result.model_dump_json()
    assert not result.execution_authority and not result.normalized_data_verified


def native_connection_script(tmp_path, fault="NONE"):
    script = tmp_path / "native_fixture.py"
    script.write_text(f"""import asyncio,json,os,signal,time
from contextlib import asynccontextmanager
from app.options import read_worker
class Client:
 async def list_tools(self):
  if {fault!r} in ('STALL','PID_STALL'):
   from pathlib import Path
   Path({str(tmp_path / "child.pid")!r}).write_text(str(os.getpid()))
   signal.signal(signal.SIGTERM,signal.SIG_IGN)
   while True: await asyncio.sleep(1)
  return json.loads({json.dumps(metadata())!r})
 async def call_tool(self,name,arguments):
  return {{'isError':False,'structuredContent':{{'rows':[]}}}}
@asynccontextmanager
async def client(): yield Client()
class Connection: client=staticmethod(client)
read_worker.connection=lambda policy: Connection()
raise SystemExit(read_worker.main())
""")
    return script


def intercept_native(monkeypatch, script):
    original = asyncio.create_subprocess_exec
    children = []

    async def spawn(*argv, **kwargs):
        assert argv[1:] == ("-I", "-m", "app.options.read_worker")
        assert kwargs["start_new_session"] and "PYTHONPATH" not in kwargs["env"]
        child = await original(argv[0], "-I", str(script), **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return children


def test_native_discovery_then_pinned_sample_collection(tmp_path, monkeypatch):
    script = native_connection_script(tmp_path)
    children = intercept_native(monkeypatch, script)
    policy = CapturePolicy(oauth_file=str(oauth(tmp_path)), timeout_seconds=10)
    discovery = asyncio.run(collect(policy))
    assert discovery.status == "COMPLETE" and not discovery.observations
    captured = asyncio.run(
        collect(
            policy, schemas=discovery.schemas, plan=plan("get_option_quotes", "get_equity_quotes")
        )
    )
    assert captured.status == "COMPLETE" and len(captured.observations) == 2
    assert all(o["output_schema_validated"] for o in captured.observations)
    assert all(c.returncode == 0 for c in children)
    assert "PRIVATE-TOKEN" not in captured.model_dump_json()


@pytest.mark.parametrize("cancel", [False, True])
def test_native_stall_timeout_or_cancellation_reaps_child(tmp_path, monkeypatch, cancel):
    children = intercept_native(monkeypatch, native_connection_script(tmp_path, "STALL"))
    policy = CapturePolicy(oauth_file=str(oauth(tmp_path)), timeout_seconds=2)

    async def run():
        task = asyncio.create_task(collect(policy))
        if cancel:
            while not children:
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.5)
            task.cancel()
        with pytest.raises((asyncio.CancelledError, TimeoutError, ValueError)):
            await task

    at = time.monotonic()
    asyncio.run(run())
    assert time.monotonic() - at < 5 and children[0].returncode is not None


@pytest.mark.parametrize("fault", ["request", "policy", "time", "plan", "calls"])
def test_parent_rejects_invalid_child_lineage(tmp_path, monkeypatch, fault):
    policy = CapturePolicy(oauth_file=str(oauth(tmp_path)), timeout_seconds=5)
    s = asyncio.run(OptionReadGateway(Client()).discover())

    async def fake_read(req):
        data = {
            "request_id": req.request_id,
            "policy_sha256": policy_digest(policy),
            "operation": req.operation,
            "started_at": req.started_at,
            "collected_at": utc_now(),
            "elapsed_seconds": 0.0,
            "status": "COMPLETE",
            "schemas": s,
            "plan": req.plan,
            "observations": [
                {"label": "sample-0", "tool": "get_option_quotes", "completed": True, "raw": {}}
            ],
        }
        if fault == "request":
            data["request_id"] = "b" * 32
        if fault == "policy":
            data["policy_sha256"] = "b" * 64
        if fault == "time":
            data["collected_at"] = req.started_at.replace(year=2020)
        if fault == "plan":
            data["plan"] = None
        if fault == "calls":
            data["observations"][0]["tool"] = "get_accounts"
        return CaptureResult(**data)

    monkeypatch.setattr(read_capture, "_read", fake_read)
    with pytest.raises(ValueError):
        asyncio.run(collect(policy, schemas=s, plan=plan()))


def test_private_cli_admits_before_read_and_never_echoes_raw(tmp_path, monkeypatch, capsys):
    tmp_path.chmod(0o700)
    credentials = oauth(tmp_path)
    output = tmp_path / "discovery.json"

    async def fake_collect(policy, **kwargs):
        assert json.loads(output.read_text())["status"] == "INCOMPLETE"
        assert output.stat().st_mode & 0o777 == 0o600
        s = await OptionReadGateway(Client()).discover()
        return CaptureResult(
            request_id="a" * 32,
            policy_sha256=policy_digest(policy),
            operation="DISCOVER",
            started_at=utc_now(),
            collected_at=utc_now(),
            elapsed_seconds=0.0,
            status="COMPLETE",
            schemas=s,
        )

    monkeypatch.setattr(read_cli, "collect", fake_collect)
    argv = ["discover", "--oauth-file", str(credentials), "--output", str(output)]
    assert read_cli.main(argv) == 0
    saved = output.read_bytes()
    assert read_cli.main(argv) == 1 and output.read_bytes() == saved
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "fault", ["timeout", "bad_parent_mode", "output_symlink", "bad_oauth_mode"]
)
def test_private_cli_rejects_or_records_sanitized_failure(tmp_path, monkeypatch, capsys, fault):
    tmp_path.chmod(0o700)
    credentials = oauth(tmp_path)
    output = tmp_path / "failed.json"

    async def failure(*args, **kwargs):
        raise TimeoutError("PRIVATE-TOKEN")

    monkeypatch.setattr(read_cli, "collect", failure)
    if fault == "bad_parent_mode":
        tmp_path.chmod(0o755)
    if fault == "output_symlink":
        output.symlink_to(credentials)
    if fault == "bad_oauth_mode":
        credentials.chmod(0o644)
    before = credentials.read_bytes()
    assert (
        read_cli.main(["discover", "--oauth-file", str(credentials), "--output", str(output)]) == 1
    )
    assert credentials.read_bytes() == before and "PRIVATE" not in capsys.readouterr().out
    if fault == "timeout":
        assert json.loads(output.read_text())["status"] == "FAILED"


@pytest.mark.parametrize("value", [True, float("nan"), 0, 31])
def test_timeout_is_finite_strict_and_bounded(tmp_path, value):
    with pytest.raises(ValidationError):
        CapturePolicy(oauth_file=str(tmp_path / "private"), timeout_seconds=value)


def test_private_plan_loader_rejects_duplicate_keys_and_public_file(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text('{"symbols":[],"symbols":["SPY"]}')
    path.chmod(0o600)
    with pytest.raises(ValueError):
        read_cli.private_json(path)
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        read_cli.private_json(path)


@pytest.mark.skipif(sys.platform != "linux", reason="Native Linux subreaper proof")
def test_actual_parent_sigkill_ends_orphaned_capture_child(tmp_path):
    worker = native_connection_script(tmp_path, "PID_STALL")
    credentials = oauth(tmp_path)
    parent_script = tmp_path / "parent.py"
    parent_script.write_text(f"""import asyncio
from app.options.read_capture import CapturePolicy,collect
original=asyncio.create_subprocess_exec
async def spawn(*argv,**kwargs):
 return await original(argv[0],'-I',{str(worker)!r},**kwargs)
asyncio.create_subprocess_exec=spawn
asyncio.run(collect(CapturePolicy(oauth_file={str(credentials)!r},timeout_seconds=20)))
""")
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    parent = subprocess.Popen(
        [sys.executable, "-I", str(parent_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid, reaped = None, False
    try:
        deadline = time.monotonic() + 10
        marker = tmp_path / "child.pid"
        while not marker.exists():
            assert parent.poll() is None and time.monotonic() < deadline
            time.sleep(0.025)
        pid = int(marker.read_text())
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            got, status = os.waitpid(pid, os.WNOHANG)
            if got:
                reaped = True
                assert os.waitstatus_to_exitcode(status) == 92
                break
            time.sleep(0.025)
        assert reaped, "Parent-death watcher left provider child alive"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if pid and not reaped:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def test_cli_capture_uses_reviewed_discovery_pin_and_keeps_raw_private(
    tmp_path, monkeypatch, capsys
):
    tmp_path.chmod(0o700)
    policy = CapturePolicy(oauth_file=str(oauth(tmp_path)), timeout_seconds=30)
    schemas = asyncio.run(OptionReadGateway(Client()).discover())
    discovery = CaptureResult(
        request_id="a" * 32,
        policy_sha256=policy_digest(policy),
        operation="DISCOVER",
        started_at=utc_now(),
        collected_at=utc_now(),
        elapsed_seconds=0.0,
        status="COMPLETE",
        schemas=schemas,
    )
    source = tmp_path / "schemas.json"
    source.write_text(
        json.dumps({"status": "COMPLETE", "result": discovery.model_dump(mode="json")})
    )
    source.chmod(0o600)
    p = plan()
    manifest = tmp_path / "plan.json"
    manifest.write_text(p.model_dump_json())
    manifest.chmod(0o600)
    output = tmp_path / "sample.json"
    calls = []

    async def fake_collect(policy, **kwargs):
        calls.append(kwargs)
        return CaptureResult(
            request_id="b" * 32,
            policy_sha256=policy_digest(policy),
            operation="CAPTURE",
            started_at=utc_now(),
            collected_at=utc_now(),
            elapsed_seconds=0.0,
            status="COMPLETE",
            schemas=schemas,
            plan=p,
            observations=[
                {
                    "label": "sample-0",
                    "tool": "get_option_quotes",
                    "completed": True,
                    "raw": {"fixture": "PRIVATE SAMPLE"},
                }
            ],
        )

    monkeypatch.setattr(read_cli, "collect", fake_collect)
    args = [
        "capture",
        "--oauth-file",
        policy.oauth_file,
        "--schemas",
        str(source),
        "--plan",
        str(manifest),
        "--output",
        str(output),
        "--schema-sha256",
        schemas.sha256,
    ]
    assert read_cli.main(args) == 0 and calls[0]["plan"] == p
    assert "PRIVATE SAMPLE" in output.read_text()
    assert "PRIVATE" not in capsys.readouterr().out
    args[-1] = "0" * 64
    args[args.index("--output") + 1] = str(tmp_path / "bad-pin.json")
    assert read_cli.main(args) == 1 and len(calls) == 1
    assert not (tmp_path / "bad-pin.json").exists()
