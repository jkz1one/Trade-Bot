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


def test_execute_reports_only_fixed_rollover_failure_codes(monkeypatch):
    m = load()
    for payload, expected in (({"reason": "SESSION_CLOSED"}, "SESSION_CLOSED"),
                              ({"reason": "private-token"}, "Host command failed")):
        def docker(*args, **kwargs):
            assert kwargs["allow_failure"] is True
            return subprocess.CompletedProcess(args, 2, json.dumps(payload), "private-stderr")
        monkeypatch.setattr(m.h, "docker", docker)
        with pytest.raises(RuntimeError, match=expected) as caught:
            m.execute(IMAGE, "app.mixed.feed_rollover", [], [])
        assert "private" not in str(caught.value)


def load():
    spec = importlib.util.spec_from_file_location("session_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize('operation', ['review-strategy-upgrade', 'apply-strategy-upgrade'])
def test_strategy_upgrade_mounts_only_apply_configuration_writable(tmp_path, monkeypatch, operation):
    m = load()
    state = tmp_path / 'state'; state.mkdir(mode=0o700)
    config = state / 'config'; config.mkdir(mode=0o700)
    for name in ('policy.json', 'schemas.json'):
        path = config / name; path.write_text('{}'); path.chmod(0o600)
    monkeypatch.setattr(m, 'STATE', state)
    monkeypatch.setattr(m, 'image', lambda _: IMAGE)
    monkeypatch.setattr(m, 'no_active_session', lambda: None)
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{}', '')
    monkeypatch.setattr(m.h, 'docker', docker)
    review = 'c' * 64
    m.run(SimpleNamespace(operation=operation, expected_review=review), RELEASE)
    invocation = calls[0]
    assert invocation[invocation.index('--network') + 1] == 'none'
    assert not any('/auth' in x or '/run/secrets' in x for x in invocation)
    if operation == 'apply-strategy-upgrade':
        assert f'type=bind,src={state},dst=/state' in invocation
        assert not any('dst=/state/config,' in x for x in invocation)
        for name in ('policy.json', 'schemas.json'):
            assert f'type=bind,src={config / name},dst=/state/config/{name},readonly' in invocation
        assert invocation[-2:] == ('--expected-review', review)
    else:
        assert f'type=bind,src={state},dst=/state,readonly' in invocation
    # Ordinary writable runtime/enrollment operations still cannot alter config.
    assert f'type=bind,src={config},dst=/state/config,readonly' in m.config_mounts(True)
    with pytest.raises(ValueError, match='requires writable'):
        m.config_mounts(amend_strategy=True)


def test_session_preparation_mounts_optional_original_earnings_read_only(tmp_path, monkeypatch):
    m = load()
    captures = tmp_path / 'captures'; captures.mkdir(mode=0o700)
    for name in ('contracts.json', 'quotes-1.json', 'quotes-2.json', 'quotes-3.json'):
        path = captures / name; path.write_text('{}'); path.chmod(0o600)
    earnings = tmp_path / 'probe.json'; earnings.write_text('{}'); earnings.chmod(0o600)
    monkeypatch.setattr(m, 'image', lambda release: IMAGE)
    monkeypatch.setattr(m, 'bundle', lambda image: None)
    monkeypatch.setattr(m, 'no_active_session', lambda: None)
    monkeypatch.setattr(m, 'config_mounts', lambda: [])
    seen = []
    monkeypatch.setattr(m, 'execute', lambda *args: seen.append(args) or {})
    args = SimpleNamespace(operation='prepare-session', target_session='2026-10-30',
                           next_policy=str(tmp_path / 'proposal' / 'policy.json'),
                           capture_directory=str(captures), earnings_probe=str(earnings))
    m.run(args, RELEASE)
    call = seen[0]
    assert call[1] == 'app.mixed.simulation_catalog'
    assert call[2][-2:] == ['--earnings-probe', '/earnings/probe.json']
    assert f'type=bind,src={earnings},dst=/earnings/probe.json,readonly' in call[3]
    assert not any('/auth' in x or 'model_key' in x for x in call[3])


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


def test_upgraded_owner_gets_separate_bound_snapshot_for_create_review_and_run(host):
    m, calls, _, _, manifest = host
    manifest['strategy_amendment_sha256'] = '7' * 64
    old = m.EXPORTS / 'connected-v1'
    old.mkdir(mode=0o711)
    evidence = old / 'original'; evidence.write_bytes(b'retain old snapshot')
    m.snapshot(IMAGE)
    create = next(c for c in calls if 'app.mixed.dashboard_snapshot' in c)
    assert create[create.index('--destination') + 1] == '/exports/connected-price-options-v1'
    assert create[create.index('--network') + 1] == 'none'
    assert f'type=bind,src={m.STATE}/owner,dst=/source,readonly' in create
    assert not any('/auth' in a or '/run/secrets' in a for a in create)
    checks = [c for c in calls if 'app.mixed.connected_runtime' in c]
    assert checks and all('--snapshot-directory' not in c for c in checks)
    plan = m.review(IMAGE, 'run', 60, 'upgraded')
    assert plan['binding']['snapshot_directory'] == '/exports/connected-price-options-v1'
    m.apply(plan)
    check = [c for c in calls if 'app.mixed.connected_runtime' in c and 'check' in c][-1]
    live = next(c for c in calls if c[:2] == ('run', '-d'))
    for call in (check, live):
        assert call[call.index('--snapshot-directory') + 1] == plan['binding']['snapshot_directory']
    assert evidence.read_bytes() == b'retain old snapshot'
    assert not any(c[0] in ('rm', 'rename', 'start') for c in calls)


def test_snapshot_destination_change_cannot_reuse_run_review(host):
    m, calls, _, _, manifest = host
    plan = m.review(IMAGE, 'run', 60, 'changed-snapshot')
    manifest['strategy_amendment_sha256'] = '7' * 64
    with pytest.raises(ValueError, match='snapshot destination changed'):
        m.apply(plan)
    assert not any(c[:2] == ('run', '-d') for c in calls)


def test_incomplete_upgraded_owner_does_not_create_snapshot(host, monkeypatch):
    m, calls, _, _, manifest = host
    manifest['strategy_amendment_sha256'] = '7' * 64
    original = m.execute
    def execute(image, module, *args, **kwargs):
        if module == 'app.mixed.connected_runtime':
            raise ValueError('Pending amendment')
        return original(image, module, *args, **kwargs)
    monkeypatch.setattr(m, 'execute', execute)
    with pytest.raises(ValueError, match='Pending amendment'):
        m.snapshot(IMAGE)
    assert not any('app.mixed.dashboard_snapshot' in c for c in calls)


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


def test_resume_requires_review_binding_and_reaches_bounded_container(host, monkeypatch):
    m, calls, _, _, _ = host
    original = m.execute
    def execute(image, module, args, mounts, **kwargs):
        result = original(image, module, args, mounts, **kwargs)
        if module == "app.mixed.connected_runtime":
            result["owner_state"]["halt_reason"] = "OPTION_RUNTIME_STOPPED"
        return result
    monkeypatch.setattr(m, "execute", execute)
    plan = m.review(IMAGE, "run", 600, "resume-test", resume_flat=True)
    assert plan["binding"]["resume_flat_reviewed_revision"] == 1
    ordinary = m.review(IMAGE, "run", 600, "resume-test")
    assert plan["review_sha256"] != ordinary["review_sha256"]
    m.apply(plan)
    invocation = next(c for c in calls if c[:2] == ("run", "-d"))
    assert invocation[invocation.index("--resume-flat-reviewed-revision") + 1] == "1"


def test_swing_preparation_uses_separate_readonly_capture_mount(tmp_path, monkeypatch):
    m = load()
    captures, swing = tmp_path / 'degen', tmp_path / 'swing'
    for folder in (captures, swing):
        folder.mkdir(mode=0o700)
        for name in ('contracts.json', 'quotes-1.json', 'quotes-2.json', 'quotes-3.json'):
            path = folder / name
            path.write_text('{}')
            path.chmod(0o600)
    monkeypatch.setattr(m, 'image', lambda release: IMAGE)
    monkeypatch.setattr(m, 'bundle', lambda image: None)
    monkeypatch.setattr(m, 'no_active_session', lambda: None)
    monkeypatch.setattr(m, 'config_mounts', lambda: [])
    seen = []
    monkeypatch.setattr(m, 'execute', lambda *args: seen.append(args) or {})
    args = SimpleNamespace(operation='prepare-session', target_session='2026-10-30',
        next_policy=str(tmp_path / 'proposal/policy.json'), capture_directory=str(captures),
        swing_capture_directory=str(swing), observed_swing_history=True)
    m.run(args, RELEASE)
    call = seen[0]
    assert '--observed-swing-history' in call[2]
    assert call[2][call[2].index('--swing-capture-directory')+1] == '/swing-captures'
    assert f'type=bind,src={swing},dst=/swing-captures,readonly' in call[3]
    assert not any('/auth' in value or 'model_key' in value for value in call[3])
