from __future__ import annotations

import asyncio
import fcntl
import json
import os
import signal
from datetime import datetime
from pathlib import Path

from app.domain.models import utc_now
from app.robinhood.client import JsonOAuthStorage


class ServiceAlreadyRunning(RuntimeError):
    pass


class ServiceLock:
    """Lifetime POSIX lock shared by the daemon and its local maintenance commands."""

    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.fd)
            self.fd = None
            raise ServiceAlreadyRunning("Stop the SHADOW service before maintenance") from exc
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


async def service_preflight(settings, repo):
    from app.robinhood.cli import _configured_openai_key_problem

    if settings.normalized_mode != "SHADOW" or settings.live_enabled:
        return {"reason": "INVALID_SERVICE_MODE", "exit_code": 14}
    if repo.active_shadow_slot() is not None:
        return {"reason": "INTERRUPTED_CLAIM", "exit_code": 10}
    if settings.synthetic_experiment_id:
        from app.experiment.storage import SyntheticStore
        try:
            SyntheticStore(repo.session_factory).validate_profile(settings, settings.model_name)
        except (ValueError, RuntimeError) as exc:
            return {"reason": "SYNTHETIC_PROFILE_INVALID", "error_class": type(exc).__name__, "exit_code": 14}
    if _configured_openai_key_problem(settings):
        return {"reason": "OPENAI_KEY_NOT_CONFIGURED", "exit_code": 4}
    try:
        storage = JsonOAuthStorage(settings.robinhood_oauth_storage)
        tokens = await storage.get_tokens()
        client = await storage.get_client_info()
        if not tokens or not tokens.access_token or not client or not client.client_id:
            return {"reason": "ROBINHOOD_AUTH_NOT_CONFIGURED", "exit_code": 14}
    except Exception as exc:
        return {"reason": "ROBINHOOD_AUTH_INVALID", "error_class": type(exc).__name__, "exit_code": 14}
    # Token refresh/access is tested by the first real session cycle, not by a
    # health check or a background authorization prompt.
    return None


class ShadowService:
    def __init__(self, settings, repo, scheduler, *, preflight=service_preflight,
                 clock=utc_now, poll_seconds=30, heartbeat_seconds=15, cycle_timeout=600):
        self.settings = settings
        self.repo = repo
        self.scheduler = scheduler
        self.preflight = preflight
        self.clock = clock
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.cycle_timeout = cycle_timeout

    def _halt(self, result):
        self.repo.set_shadow_service_state("HALTED", self.clock(), self.settings.release_sha, result)
        print(json.dumps({"service": "HALTED", **result}), flush=True)

    async def _heartbeat(self, stop):
        while not stop.is_set():
            self.repo.heartbeat_shadow_service(self.clock())
            try:
                await asyncio.wait_for(stop.wait(), self.heartbeat_seconds)
            except TimeoutError:
                pass

    async def run(self, stop: asyncio.Event) -> int:
        # A second daemon or maintenance command cannot mutate the active daemon's state.
        try:
            with ServiceLock(self.settings.shadow_service_lock_path):
                return await self._run_locked(stop)
        except ServiceAlreadyRunning:
            print(json.dumps({"service": "BLOCKED", "reason": "SERVICE_ALREADY_RUNNING", "exit_code": 13}))
            return 13

    async def _run_locked(self, stop):
        state = self.repo.shadow_service_state()
        if not state or state["status"] != "HALTED":
            try:
                issue = await self.preflight(self.settings, self.repo)
            except Exception as exc:
                issue = {"reason": "PREFLIGHT_FAILURE", "error_class": type(exc).__name__, "exit_code": 14}
            if issue:
                self._halt(issue)
            else:
                self.repo.set_shadow_service_state("RUNNING", self.clock(), self.settings.release_sha)
        else:
            print(json.dumps({"service": "HALTED", "reason": "PERSISTENT_HALT",
                              "last_result": state["last_result"]}), flush=True)
        heartbeat = asyncio.create_task(self._heartbeat(stop))
        previous = None
        try:
            while not stop.is_set():
                if heartbeat.done():
                    heartbeat.result()
                state = self.repo.shadow_service_state()
                if state["status"] != "HALTED":
                    try:
                        result = await asyncio.wait_for(self.scheduler.tick(), self.cycle_timeout)
                    except Exception as exc:
                        result = {"status": "ERROR", "reason": "CYCLE_EXCEPTION",
                                  "error_class": type(exc).__name__, "exit_code": 11}
                    if result.get("status") == "SKIPPED" and result.get("reason") == "SLOT_ALREADY_ATTEMPTED":
                        # Explicit resume never repeats the failed slot. Wait for
                        # the next slot instead of immediately halting on its old code.
                        result = {**result, "prior_exit_code": result["exit_code"], "exit_code": 0}
                    if result["exit_code"]:
                        self._halt(result)
                    else:
                        self.repo.set_shadow_service_state("RUNNING", self.clock(),
                                                           self.settings.release_sha, result)
                        if result != previous:
                            print(json.dumps({"service": "RUNNING", **result}), flush=True)
                            previous = result
                try:
                    await asyncio.wait_for(stop.wait(), self.poll_seconds)
                except TimeoutError:
                    pass
        except Exception as exc:
            self._halt({"reason": "SERVICE_EXCEPTION", "error_class": type(exc).__name__, "exit_code": 11})
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            except Exception:
                pass  # The loop already latched the heartbeat failure above.
            if self.repo.shadow_service_state()["status"] != "HALTED":
                self.repo.set_shadow_service_state("STOPPED", self.clock(), self.settings.release_sha)
        return 0


async def run_shadow_service(settings):
    from app.robinhood.cli import _repo, shadow_cycle
    from app.robinhood.schedule import ShadowScheduler

    settings = settings.model_copy(update={"robinhood_interactive_auth": False})
    repo = _repo(settings)

    async def run(window, token):
        return await shadow_cycle(settings, "openai", repo=repo,
                                  schedule_window=window, claim_token=token)

    class LazyScheduler:
        delegate = None

        async def tick(self):
            if self.delegate is None:
                try:
                    self.delegate = ShadowScheduler(repo, run)
                except Exception as exc:
                    return {"status": "ERROR", "reason": "CALENDAR_FAILURE",
                            "error_class": type(exc).__name__, "exit_code": 12}
            from app.experiment.storage import annotate_tick
            return annotate_tick(settings, repo, await self.delegate.tick())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        return await ShadowService(settings, repo, LazyScheduler()).run(stop)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def service_check(settings, *, now=None):
    from app.robinhood.cli import _repo

    state = _repo(settings).shadow_service_state()
    healthy = False
    if state and state["status"] == "RUNNING":
        stamp = datetime.fromisoformat(state["heartbeat_at"])
        healthy = 0 <= ((now or utc_now()) - stamp).total_seconds() <= 90
    print(json.dumps({"healthy": healthy, "service": state, "network_calls": False}))
    return 0 if healthy else 1


def service_maintenance(settings, *, abandon_slot=None):
    from app.robinhood.cli import _repo

    try:
        with ServiceLock(settings.shadow_service_lock_path):
            repo = _repo(settings)
            if abandon_slot is not None:
                repo.abandon_shadow_slot(abandon_slot, utc_now())
            else:
                repo.resume_shadow_service(utc_now(), settings.release_sha)
        print(json.dumps({"status": "OK", "action": "ABANDON_SLOT" if abandon_slot else "RESUME",
                          "slot_key": abandon_slot, "network_calls": False}))
        return 0
    except ServiceAlreadyRunning:
        print(json.dumps({"status": "BLOCKED", "reason": "STOP_SERVICE_FIRST"}))
        return 13
    except RuntimeError:
        print(json.dumps({"status": "BLOCKED", "reason": "REVIEW_SERVICE_STATE_AND_ACTIVE_CLAIM"}))
        return 10
