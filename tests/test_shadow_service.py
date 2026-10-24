import asyncio
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import Settings
from app.domain.models import utc_now
from app.robinhood import cli
from app.robinhood.schedule import ShadowScheduler, XNYSCalendar
from app.robinhood.service import (
    ServiceAlreadyRunning, ServiceLock, ShadowService, service_check,
    service_maintenance, service_preflight,
)
from app.storage.db import make_engine, make_session_factory
from app.storage.models import SystemEventRow
from app.storage.repository import Repository


@pytest.fixture
def service_settings(settings, tmp_path):
    return Settings(mode="SHADOW", robinhood_db_url=settings.db_url,
                    shadow_service_lock_path=str(tmp_path / "service.lock"),
                    robinhood_oauth_storage=str(tmp_path / "oauth.json"), release_sha="test-release")


async def ready(settings, repo):
    return None


def write_auth(path):
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
    payload = {
        "tokens": OAuthToken(access_token="fake-token", token_type="Bearer",
                             refresh_token="fake-refresh", expires_in=1).model_dump(mode="json"),
        "client_info": OAuthClientInformationFull(
            client_id="fake-client", redirect_uris=["http://127.0.0.1:8765/callback"],
        ).model_dump(mode="json"),
    }
    Path(path).write_text(json.dumps(payload))


@pytest.mark.anyio
async def test_headless_oauth_never_opens_browser_or_prompts(monkeypatch):
    def forbidden(*args):
        raise AssertionError("Interactive authorization is forbidden in the service")

    monkeypatch.setattr(cli.webbrowser, "open", forbidden)
    monkeypatch.setattr("builtins.input", forbidden)
    connection = cli._connection(Settings(robinhood_interactive_auth=False))
    with pytest.raises(cli.HeadlessAuthorizationRequired):
        await connection.redirect_handler("https://example.invalid/secret-auth-url")
    with pytest.raises(cli.HeadlessAuthorizationRequired):
        await connection.callback_handler()
    manual = cli._connection(Settings())
    assert manual.redirect_handler is cli._open_browser


def test_private_key_file_overrides_env_without_printing_key(service_settings, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "old-key-long-enough-for-tests")
    key = tmp_path / "key"
    key.write_text("new-key-long-enough-for-tests\n")
    settings = service_settings.model_copy(update={"openai_api_key_file": str(key)})
    assert cli._configured_openai_key_problem(settings) is None
    assert cli.os.environ["OPENAI_API_KEY"] == "new-key-long-enough-for-tests"
    key.write_text("key1\nkey2")
    assert cli._configured_openai_key_problem(settings)
    key.unlink()
    assert cli._configured_openai_key_problem(settings)
    assert "new-key" not in capsys.readouterr().out


@pytest.mark.anyio
async def test_service_preflight_checks_local_credentials_only(repo, service_settings, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert (await service_preflight(service_settings, repo))["exit_code"] == 4
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-long-enough-for-tests")
    assert (await service_preflight(service_settings, repo))["reason"] == "ROBINHOOD_AUTH_NOT_CONFIGURED"
    Path(service_settings.robinhood_oauth_storage).write_text("not-json")
    assert (await service_preflight(service_settings, repo))["reason"] == "ROBINHOOD_AUTH_INVALID"
    write_auth(service_settings.robinhood_oauth_storage)
    # An expired access token can be refreshed by the SDK; preflight does not
    # attempt remote authentication or initiate a new registration.
    assert await service_preflight(service_settings, repo) is None
    for invalid in (service_settings.model_copy(update={"mode": "LIVE"}),
                    service_settings.model_copy(update={"live_enabled": True}), Settings()):
        assert (await service_preflight(invalid, repo))["reason"] == "INVALID_SERVICE_MODE"


@pytest.mark.anyio
async def test_service_failure_latches_across_restart_and_makes_no_further_calls(repo, service_settings, capsys):
    stop = asyncio.Event()
    entered = asyncio.Event()
    calls = []

    async def tick():
        calls.append(1)
        entered.set()
        return {"status": "ERROR", "exit_code": 8, "error_class": "RateLimitError"}

    worker = ShadowService(service_settings, repo, SimpleNamespace(tick=tick), preflight=ready,
                           poll_seconds=.005, heartbeat_seconds=.005)
    task = asyncio.create_task(worker.run(stop))
    await entered.wait()
    await asyncio.sleep(.025)
    assert len(calls) == 1
    assert repo.shadow_service_state()["status"] == "HALTED"
    assert service_check(service_settings) == 1
    stop.set()
    assert await task == 0
    reopened = Repository(make_session_factory(make_engine(service_settings.robinhood_db_url)))

    async def forbidden(*args):
        raise AssertionError("Persistent halt must bypass credential/network work")

    stop2 = asyncio.Event()
    worker2 = ShadowService(service_settings, reopened, SimpleNamespace(tick=forbidden),
                            preflight=forbidden, poll_seconds=.005, heartbeat_seconds=.005)
    task2 = asyncio.create_task(worker2.run(stop2))
    await asyncio.sleep(.025)
    assert reopened.shadow_service_state()["status"] == "HALTED"
    stop2.set()
    assert await task2 == 0
    with repo.session_factory() as session:
        events = list(session.scalars(select(SystemEventRow)))
    assert any("service halted" in e.message for e in events)
    assert "fake-key" not in capsys.readouterr().out


@pytest.mark.anyio
async def test_successful_closed_tick_is_healthy_and_shutdown_drains_active_cycle(repo, service_settings):
    stop = asyncio.Event()
    entered = asyncio.Event()
    finished = asyncio.Event()

    async def tick():
        entered.set()
        await finished.wait()
        return {"status": "SKIPPED", "reason": "MARKET_CLOSED", "exit_code": 0}

    worker = ShadowService(service_settings, repo, SimpleNamespace(tick=tick), preflight=ready,
                           heartbeat_seconds=.005)
    task = asyncio.create_task(worker.run(stop))
    await entered.wait()
    assert service_check(service_settings) == 0
    first = repo.shadow_service_state()["heartbeat_at"]
    await asyncio.sleep(.02)
    assert repo.shadow_service_state()["heartbeat_at"] != first
    stop.set()
    assert not task.done()
    finished.set()
    assert await task == 0
    state = repo.shadow_service_state()
    assert state["status"] == "STOPPED" and state["last_result"]["reason"] == "MARKET_CLOSED"


@pytest.mark.anyio
async def test_second_daemon_and_maintenance_cannot_touch_running_state(repo, service_settings):
    stop = asyncio.Event()
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def tick():
        entered.set()
        await finish.wait()
        return {"status": "SKIPPED", "reason": "MARKET_CLOSED", "exit_code": 0}

    first = asyncio.create_task(ShadowService(service_settings, repo, SimpleNamespace(tick=tick),
                                              preflight=ready).run(stop))
    await entered.wait()
    second = ShadowService(service_settings, repo, SimpleNamespace(tick=tick), preflight=ready)
    assert await second.run(asyncio.Event()) == 13
    assert service_maintenance(service_settings) == 13
    assert repo.shadow_service_state()["status"] == "RUNNING"
    stop.set()
    finish.set()
    await first


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["timeout", "exception", "preflight"])
async def test_worker_exceptions_and_timeouts_are_sanitized_and_sticky(repo, service_settings, capsys, failure):
    stop = asyncio.Event()

    async def tick():
        if failure == "timeout":
            await asyncio.Event().wait()
        raise RuntimeError("secret-not-to-be-logged")

    async def preflight(*args):
        if failure == "preflight":
            raise RuntimeError("secret-not-to-be-logged")

    worker = ShadowService(service_settings, repo, SimpleNamespace(tick=tick), preflight=preflight,
                           cycle_timeout=.01, poll_seconds=.005, heartbeat_seconds=.005)
    task = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(.05)
    assert repo.shadow_service_state()["status"] == "HALTED"
    stop.set()
    await task
    assert "secret-not-to-be-logged" not in capsys.readouterr().out


def test_health_check_rejects_stale_missing_future_or_halted_heartbeat(repo, service_settings):
    assert service_check(service_settings) == 1
    now = utc_now()
    repo.set_shadow_service_state("RUNNING", now, "release")
    assert service_check(service_settings, now=now + timedelta(seconds=90)) == 0
    assert service_check(service_settings, now=now + timedelta(seconds=91)) == 1
    assert service_check(service_settings, now=now - timedelta(seconds=1)) == 1
    repo.set_shadow_service_state("HALTED", now, "release", {"exit_code": 8})
    assert service_check(service_settings, now=now) == 1


@pytest.mark.anyio
async def test_operator_abandon_keeps_slot_non_replayable_and_resume_waits_for_next_slot(repo, service_settings):
    from datetime import datetime
    now = datetime.fromisoformat("2026-10-05T14:00:00+00:00")
    window = XNYSCalendar().current_window(now)
    assert repo.claim_shadow_slot(window, "crashed-owner", now)
    assert (await service_preflight(service_settings, repo))["reason"] == "INTERRUPTED_CLAIM"
    repo.set_shadow_service_state("HALTED", now, "test", {"exit_code": 10})
    assert service_maintenance(service_settings) == 10
    assert service_maintenance(service_settings, abandon_slot=window.key) == 0
    assert repo.shadow_slot(window.key).status == "ABANDONED"
    assert service_maintenance(service_settings) == 0
    assert repo.shadow_service_state()["status"] == "STOPPED"
    stop = asyncio.Event()

    async def forbidden(*args):
        raise AssertionError("Abandoned slot must never replay")

    scheduler = ShadowScheduler(repo, forbidden, clock=lambda: now)
    real_tick = scheduler.tick

    async def tick():
        result = await real_tick()
        stop.set()
        return result

    worker = ShadowService(service_settings, repo, SimpleNamespace(tick=tick), preflight=ready)
    assert await worker.run(stop) == 0
    state = repo.shadow_service_state()
    assert state["status"] == "STOPPED"
    assert state["last_result"]["prior_exit_code"] == 11
    assert state["last_result"]["exit_code"] == 0
    assert repo.shadow_slot(window.key).status == "ABANDONED"


def test_process_lock_is_released_on_exception(tmp_path):
    path = tmp_path / "lock"
    with pytest.raises(RuntimeError):
        with ServiceLock(path):
            with pytest.raises(ServiceAlreadyRunning):
                with ServiceLock(path):
                    pass
            raise RuntimeError("test")
    with ServiceLock(path):
        assert path.stat().st_mode & 0o777 == 0o600
