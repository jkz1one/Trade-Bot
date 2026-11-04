"""Operator auth helpers cannot mount/start the trader or expose private errors."""

import json
import os
import runpy
import signal
import subprocess
import sys
import tempfile

import pytest
from test_session_host import IMAGE, load


@pytest.fixture
def host(tmp_path, monkeypatch):
    module = load()
    auth = tmp_path / "auth"
    auth.mkdir(mode=0o700)
    for name in ("robinhood-oauth.json", "discovery.json"):
        path = auth / name
        path.write_text("private-fixture")
        path.chmod(0o600)
    monkeypatch.setattr(module, "AUTH", auth)
    monkeypatch.setattr(module, "no_active_session", lambda: None)
    mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **kw: mkdtemp(prefix=kw["prefix"], dir=tmp_path))
    return module


@pytest.mark.parametrize("kind", ["success", "authorization", "failure", "malformed", "wrong_reads"])
def test_check_is_bounded_schema_only_and_projects_safe_results(host, monkeypatch, kind):
    payload = {"status": "COMPLETE", "schema_sha256": "a" * 64, "completed_reads": 0,
               "private": "PRIVATE_TOKEN"}
    if kind == "authorization":
        payload.update(status="FAILED", failure={"causes": [{"error_class": "ReadAuthorizationRequired"}]})
    if kind == "wrong_reads":
        payload["completed_reads"] = 1
    calls = []
    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, int(kind == "failure"),
            "PRIVATE_BROKEN_JSON" if kind == "malformed" else json.dumps(payload), "PRIVATE_STDERR")
    monkeypatch.setattr(host.h, "docker", docker)
    result = host.read_auth(IMAGE)
    assert result["status"] == {"success": "READ_AUTH_VERIFIED", "authorization": "READ_AUTHORIZATION_REQUIRED"}.get(kind, "READ_AUTH_CHECK_FAILED")
    assert "PRIVATE" not in json.dumps(result)
    args, kwargs = calls[0]
    assert kwargs == {"timeout": 45, "allow_failure": True}
    assert args[-2:] == ("--timeout-seconds", "30")
    assert "app.options.read_cli" in args and "discover" in args and "-it" not in args
    mounts = [args[i + 1] for i, value in enumerate(args) if value == "--mount"]
    assert len(mounts) == 3
    assert not any("/state" in value or "/secrets" in value or "/exports" in value for value in mounts)
    assert any(value.endswith("/auth/discovery.json,readonly") for value in mounts)
    assert result["market_reads"] == result["model_calls"] == 0
    assert calls[-1][0] == ("stop", "--time", "5", args[args.index("--name") + 1])


def test_active_session_blocks_before_opening_credentials(host, monkeypatch):
    def blocked():
        raise ValueError("A connected session is already running")
    def forbidden(*args):
        raise AssertionError("must not open credentials")
    monkeypatch.setattr(host, "no_active_session", blocked)
    monkeypatch.setattr(host, "private", forbidden)
    with pytest.raises(ValueError, match="already running"):
        host.read_auth(IMAGE)


def test_login_requires_interactive_terminal_before_any_auth_work(host, monkeypatch):
    monkeypatch.setattr(host.sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="Interactive server terminal"):
        host.read_auth(IMAGE, login=True)


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_explicit_login_preserves_backup_and_verifies_headless_after_success(host, monkeypatch, outcome):
    monkeypatch.setattr(host.sys.stdin, "isatty", lambda: True)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 600
        assert "-it" in args and "TRADER_LIVE_ENABLED=false" in args
        assert "TRADER_ROBINHOOD_INTERACTIVE_AUTH=true" in args
        code = args[args.index("-c") + 1]
        assert "market_read_lease" in code and "oauth-before.json" in code
        assert "open('xb')" in code
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(args, 600)
        return subprocess.CompletedProcess(args, int(outcome == "failure"))
    def docker(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps({"status": "COMPLETE",
            "completed_reads": 0, "schema_sha256": "a" * 64}), "")
    monkeypatch.setattr(host.h.subprocess, "run", run)
    monkeypatch.setattr(host.h, "docker", docker)
    if outcome == "timeout":
        with pytest.raises(subprocess.TimeoutExpired):
            host.read_auth(IMAGE, login=True)
    else:
        result = host.read_auth(IMAGE, login=True)
        assert result["status"] == ("READ_AUTH_VERIFIED" if outcome == "success" else "READ_LOGIN_FAILED")
    assert calls[1][0] == "stop"
    assert len(calls) == (4 if outcome == "success" else 2)


@pytest.mark.parametrize("fail", [False, True])
def test_login_wrapper_really_locks_backs_up_and_keeps_stderr_private(host, tmp_path, monkeypatch, fail):
    from app.execution.market_reads import market_read_lease, MarketReadAlreadyRunning
    oauth = host.AUTH / "robinhood-oauth.json"
    original = b'{"tokens":{"access_token":"fixture"},"client_info":{"client_id":"fixture"}}'
    oauth.write_bytes(original)
    output = tmp_path / "out"
    output.mkdir(mode=0o700)
    alarms = []
    monkeypatch.setattr(signal, "alarm", alarms.append)
    def discover(module, **kwargs):
        assert module == "app.robinhood.cli" and kwargs == {"run_name": "__main__"}
        assert (output / "oauth-before.json").read_bytes() == original
        with pytest.raises(MarketReadAlreadyRunning):
            with market_read_lease(oauth):
                pass
        print("PRIVATE_FIXTURE_ERROR", file=sys.stderr)
        if fail:
            raise RuntimeError("synthetic discovery failure")
    monkeypatch.setattr(runpy, "run_module", discover)
    code = host.READ_LOGIN.replace("/auth/", str(host.AUTH) + "/").replace("/out/", str(output) + "/")
    prior_umask = os.umask(0o077)
    try:
        if fail:
            with pytest.raises(RuntimeError, match="synthetic discovery"):
                exec(compile(code, "login-wrapper", "exec"), {})
        else:
            exec(compile(code, "login-wrapper", "exec"), {})
    finally:
        os.umask(prior_umask)
    assert alarms == [600] and oauth.read_bytes() == original
    assert (output / "login-stderr.log").read_text() == "PRIVATE_FIXTURE_ERROR\n"
    for name in ("oauth-before.json", "login-stderr.log"):
        assert (output / name).stat().st_mode & 0o777 == 0o600
    with market_read_lease(oauth):
        pass
