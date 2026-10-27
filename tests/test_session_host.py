"""Offline Docker command/state boundary for the actual host session launcher."""

import copy
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/connected-session-host.py"
IMAGE = "sha256:" + "a" * 64
RELEASE = "b" * 40


def load():
    spec = importlib.util.spec_from_file_location("session_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def host(tmp_path, monkeypatch):
    m = load()
    calls = []
    containers = {}
    for key in ("STATE", "EXPORTS", "AUTH"):
        path = tmp_path / key.lower()
        path.mkdir(mode=0o700)
        monkeypatch.setattr(m, key, path)
    for path in (m.STATE / "config", m.STATE / "owner"):
        path.mkdir(mode=0o700)
    for path in (m.AUTH / "robinhood-oauth.json", m.AUTH / "discovery.json"):
        path.write_text("synthetic-unused")
        path.chmod(0o600)
    manifest = {
        "review_sha256": "c" * 64,
        "binding": {"secret_files": {}},
        "entry_blockers": ["UNKNOWN"],
        "population_id": "host-test",
        "initial_virtual_capital": "1000",
        "maximum_plays": 2,
        "families": ["DEGEN"],
    }
    workers = {"shadow": "original", "observer": "original"}
    monkeypatch.setattr(m.h, "workers", lambda: copy.deepcopy(workers))
    monkeypatch.setattr(m.h, "container", lambda name, missing=False: containers.get(name))

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "ps":
            out = ""
        elif args[:2] == ("image", "inspect"):
            out = json.dumps([{"Id": IMAGE, "Config": {"Env": ["TRADER_RELEASE_SHA=" + RELEASE]}}])
        elif args[:2] == ("run", "-d"):
            name = args[args.index("--name") + 1]
            containers[name] = {
                "Id": "container-1",
                "Image": IMAGE,
                "State": {"Running": True},
                "Config": {"Labels": {m.LABEL: "review"}},
                "RestartCount": 0,
            }
            out = "container-1\n"
        elif args[0] == "stop":
            for item in containers.values():
                item["State"]["Running"] = False
            out = "container-1"
        elif "-m" in args:
            module = args[args.index("-m") + 1]
            if module == "app.mixed.host_bundle":
                out = json.dumps(manifest | {"status": "HOST_BUNDLE_VERIFIED"})
            elif module == "app.mixed.connected_owner":
                out = json.dumps(
                    {
                        "review_sha256": "d" * 64,
                        "entry_blockers": ["UNKNOWN"],
                        "status": "OWNER_AND_COLLECTOR_ENROLLED",
                    }
                )
            elif module == "app.mixed.connected_runtime":
                out = json.dumps(
                    {
                        "owner_state": {"owner_revision": 1},
                        "effective_policy_sha256": "e" * 64,
                        "dashboard_snapshot": {"binding_sha256": "f" * 64},
                        "entry_blockers": ["UNKNOWN"],
                    }
                )
            elif module == "app.mixed.dashboard_snapshot":
                out = '{"status":"PUBLISHED"}'
            else:
                pytest.fail(module)
        else:
            pytest.fail(repr(args))
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(m.h, "docker", docker)
    return m, calls, containers, workers, manifest


def test_enrollment_and_run_mounts_keep_offline_stages_without_broker_auth(host):
    m, calls, _containers, _, _ = host
    plan = m.review(IMAGE, "enroll")
    assert m.apply(plan)["dashboard_snapshot_created"]
    offline = list(calls)
    assert all(c[c.index("--network") + 1] == "none" for c in offline if c[0] == "run")
    assert all(c[c.index("--cpus") + 1] == "1" for c in offline if c[0] == "run")
    assert all(str(m.AUTH) not in " ".join(c) for c in offline)
    plan = m.review(IMAGE, "run", 60, "session-one")
    result = m.apply(plan)
    assert result["status"] == "SESSION_STARTED" and result["seconds"] == 60
    live = next(c for c in calls if c[:2] == ("run", "-d"))
    assert live[live.index("--restart") + 1] == "no"
    assert live[live.index("--network") + 1] == "bridge"
    assert live[live.index("--cpus") + 1] == str(plan["binding"]["resources"]["cpus"])
    assert result["resources"] == plan["binding"]["resources"]
    assert result["resources"]["cpus"] == min(2, result["resources"]["available_logical_cpus"])
    assert result["resources"]["available_logical_cpus"] >= 1
    assert live[live.index("--stop-timeout") + 1] == "45"
    assert "--publish" not in live and "-p" not in live
    assert live[-2:] == ("--seconds", "60")
    assert live[live.index("--directory") + 1] == "/state/owner"
    assert live[live.index("--snapshot-owner") + 1] == "/source"
    checks = [c for c in calls if "app.mixed.connected_runtime" in c and "check" in c]
    assert checks
    assert all(c[c.index("--directory") + 1] == "/state/owner" for c in checks)
    assert all(c[c.index("--snapshot-owner") + 1] == "/source" for c in checks)
    assert f"type=bind,src={m.STATE}/config,dst=/state/config,readonly" in live
    assert f"type=bind,src={m.AUTH},dst=/auth" in live
    assert f"type=bind,src={m.AUTH}/discovery.json,dst=/auth/discovery.json,readonly" in live
    assert "TRADER_LIVE_ENABLED=false" in live
    with pytest.raises(ValueError, match="already exists"):
        m.review(IMAGE, "run", 60, "session-one")
    assert not any(c[0] in ("rm", "rename", "start") for c in calls)


def test_changed_cpu_capacity_requires_a_new_review_before_launch(host, monkeypatch):
    m, calls, _, _, _ = host
    monkeypatch.setattr(m.os, "sched_getaffinity", lambda pid: {0, 1})
    original = m.review(IMAGE, "run", 60, "cpu-check")
    assert original["binding"]["resources"] == {"cpus": 2, "available_logical_cpus": 2}
    monkeypatch.setattr(m.os, "sched_getaffinity", lambda pid: {0})
    changed = m.review(IMAGE, "run", 60, "cpu-check")
    assert changed["review_sha256"] != original["review_sha256"]
    assert changed["binding"]["resources"]["available_logical_cpus"] == 1
    assert changed["binding"]["resources"]["cpus"] == 1
    with pytest.raises(ValueError, match="resources changed"):
        m.apply(original)
    assert not any(c[:2] == ("run", "-d") for c in calls)


def test_modified_cpu_quota_cannot_bypass_review(host):
    m, calls, _, _, _ = host
    plan = m.review(IMAGE, "run", 60, "cpu-check")
    plan["binding"]["resources"]["cpus"] = 8
    with pytest.raises(ValueError, match="resources changed"):
        m.apply(plan)
    assert not any(c[:2] == ("run", "-d") for c in calls)


@pytest.mark.parametrize(
    "seconds,run_id",
    [(0, "a"), (86401, "a"), (True, "a"), (60, "../a"), (60, "a,readonly"), (60, "")],
)
def test_invalid_bounded_run_is_refused(host, seconds, run_id):
    m, calls, _, _, _ = host
    with pytest.raises(ValueError):
        m.review(IMAGE, "run", seconds, run_id)
    assert not any(c[:2] == ("run", "-d") for c in calls)


def test_stop_requires_exact_container_id_and_retains_it(host):
    m, calls, containers, _, _ = host
    m.apply(m.review(IMAGE, "run", 60, "test"))
    args = SimpleNamespace(operation="stop", run_id="test", expected_container="wrong")
    with pytest.raises(ValueError, match="Exact inspected"):
        m.run(args, RELEASE)
    assert containers["trade-bot-connected-test"]["State"]["Running"]
    args.expected_container = "container-1"
    assert not m.run(args, RELEASE)["state"]["Running"]
    assert "trade-bot-connected-test" in containers
    assert not any(c[0] == "rm" for c in calls)


def test_changed_worker_after_start_stops_only_new_session(host, monkeypatch):
    m, calls, containers, workers, _ = host
    plan = m.review(IMAGE, "run", 60, "test")
    original = m.h.docker

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[:2] == ("run", "-d"):
            workers["shadow"] = "external-change"
        return result

    monkeypatch.setattr(m.h, "docker", change)
    with pytest.raises(RuntimeError, match="new session stopped"):
        m.apply(plan)
    assert not containers["trade-bot-connected-test"]["State"]["Running"]
    assert ("stop", "--time", "45", "container-1") in calls


def test_existing_active_session_prevents_another_launch(host, monkeypatch):
    m, calls, _, _, _ = host
    original = m.h.docker

    def active(*args, **kwargs):
        if args[0] == "ps":
            return subprocess.CompletedProcess(args, 0, "already-running\n", "")
        return original(*args, **kwargs)

    monkeypatch.setattr(m.h, "docker", active)
    with pytest.raises(ValueError, match="already running"):
        m.review(IMAGE, "run", 60, "new")
    assert not any(c[:2] == ("run", "-d") for c in calls)


def test_private_mount_rejects_symlink_and_public_file(tmp_path):
    if os.getuid() != 0:
        pytest.skip("Root host check")
    m = load()
    p = tmp_path / "input"
    p.write_text("test")
    p.chmod(0o600)
    m.private(p)
    link = tmp_path / "link"
    link.symlink_to(p)
    with pytest.raises(ValueError):
        m.private(link)
    p.chmod(0o644)
    with pytest.raises(ValueError):
        m.private(p)


def test_stop_does_not_require_image_or_configuration(host, monkeypatch):
    m, _, containers, _, _ = host
    m.apply(m.review(IMAGE, "run", 60, "test"))
    monkeypatch.setattr(m, "image", lambda *_a: pytest.fail("Stop inspected release image"))
    monkeypatch.setattr(m, "bundle", lambda *_a: pytest.fail("Stop opened configuration"))
    result = m.run(
        SimpleNamespace(operation="stop", run_id="test", expected_container="container-1"), RELEASE
    )
    assert not result["state"]["Running"] and containers


def test_stale_host_review_refuses_before_launch(host, monkeypatch):
    m, calls, _, _, _ = host
    plan = m.review(IMAGE, "run", 60, "test")
    args = SimpleNamespace(operation="run", seconds=60, run_id="test", expected_review="0" * 64)
    with pytest.raises(ValueError, match="review changed"):
        m.run(args, RELEASE)
    assert not any(c[:2] == ("run", "-d") for c in calls)
    args.expected_review = plan["review_sha256"]
    assert m.run(args, RELEASE)["status"] == "SESSION_STARTED"
