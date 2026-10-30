"""Actual host coordinator with stateful offline Docker responses; no host acceptance."""

import copy
import fcntl
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.options.engine import fingerprint

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/connected-dashboard-host.py"
RELEASE = "b" * 40
OLD_ID = "a" * 64
IMAGE = "sha256:" + "b" * 64
BINDING = {
    "version": "native-dashboard-snapshot-v1",
    "source_journal": "/source/options.db",
    "destination": "/exports/connected-v1",
    "population_id": "native-simulation",
    "owner_configuration_sha256": "c" * 64,
    "publisher_uid": 0,
    "reader_uid": 10001,
    "reader_gid": 10001,
}


def load():
    spec = importlib.util.spec_from_file_location("dashboard_host_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Docker:
    def __init__(self, h):
        self.h = h
        old = self.item(h.ACTIVE, OLD_ID, frozen=True)
        self.items = {h.ACTIVE: old}
        for name in h.WORKERS:
            self.items[name] = self.item(name, name, frozen=True)
        self.calls = []
        self.failure = None
        self.probes = 0

    def item(self, name, id_, *, frozen):
        h = self.h
        return {
            "Name": "/" + name,
            "Id": id_,
            "Image": "sha256:old" if frozen else IMAGE,
            "Config": {
                "User": "10001:10001",
                "Image": h.OLD_IMAGE if frozen else IMAGE,
                "Env": ["TRADER_LIVE_ENABLED=false"],
                "Cmd": ["python", "-I", "-c", 'review_at=m["as_of"]']
                if frozen
                else h.reader_args(BINDING, "serve"),
                "Labels": {} if frozen else {h.LABEL: OLD_ID},
            },
            "HostConfig": {
                "ReadonlyRootfs": True,
                "PortBindings": h.PORTS,
                "CapAdd": None,
                "CapDrop": ["ALL"],
                "Privileged": False,
            },
            "Mounts": [
                {
                    "Destination": "/data",
                    "Source": h.FROZEN if frozen else str(h.SNAPSHOT),
                    "RW": False,
                },
                {"Destination": "/run/secrets/dashboard_password", "Source": h.SECRET, "RW": False},
            ],
            "State": {
                "Running": True,
                "Paused": False,
                "OOMKilled": False,
                "StartedAt": "original",
            },
            "RestartCount": 0,
        }

    def __call__(self, *args, **kwargs):
        h = self.h
        self.calls.append(args)
        output = ""
        if args[:2] == ("container", "inspect"):
            name = args[2]
            if name not in self.items:
                if kwargs.get("allow_failure"):
                    return subprocess.CompletedProcess(args, 1, "", "")
                raise RuntimeError("Missing container")
            output = json.dumps([self.items[name]])
        elif args[:2] == ("image", "inspect"):
            output = json.dumps(
                [{"Id": IMAGE, "Config": {"Env": ["TRADER_RELEASE_SHA=" + RELEASE]}}]
            )
        elif args[:2] == ("run", "--rm"):
            if self.failure == "preflight":
                raise RuntimeError("Synthetic preflight failed")
            output = json.dumps(
                {
                    "status": "SNAPSHOT_READER_READY",
                    "binding_sha256": fingerprint(BINDING),
                    "application_sha256": "d" * 64,
                }
            )
        elif args[:2] == ("run", "-d"):
            if self.failure == "create_before":
                raise RuntimeError("Creation failed before allocation")
            assert h.ACTIVE not in self.items
            self.items[h.ACTIVE] = self.item(h.ACTIVE, "new-id", frozen=False)
            output = "new-id"
            if self.failure == "create_after":
                raise RuntimeError("Creation failed after allocation")
            if self.failure == "stopped":
                self.items[h.ACTIVE]["State"]["Running"] = False
            if self.failure == "workers":
                self.items[h.WORKERS[0]]["State"]["StartedAt"] = "external-change"
        elif args[0] == "rename":
            old, new = args[1:]
            assert new not in self.items
            self.items[new] = self.items.pop(old)
            self.items[new]["Name"] = "/" + new
            if self.failure == "rename_after" and new == h.BACKUP:
                self.failure = None
                raise RuntimeError("Rename succeeded but response failed")
        elif args[0] == "stop":
            name = args[-1]
            if self.failure == "stop_before" and name == h.BACKUP:
                self.failure = None
                raise RuntimeError("Stop failed before mutation")
            self.items[name]["State"]["Running"] = False
        elif args[0] == "start":
            self.items[args[1]]["State"]["Running"] = True
        elif args[0] == "exec":
            if self.failure == "auth" and args[-1] == "connected":
                self.probes += 1
                return subprocess.CompletedProcess(args, 1, "", "")
            output = '{"authenticated":true}'
        else:
            pytest.fail("Unexpected Docker action " + repr(args))
        return subprocess.CompletedProcess(args, 0, output, "")


@pytest.fixture
def host(monkeypatch, tmp_path):
    h = load()
    fake = Docker(h)
    monkeypatch.setattr(h, "docker", fake)
    monkeypatch.setattr(h, "binding", lambda: copy.deepcopy(BINDING))
    monkeypatch.setattr(h.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(h, "LOCK", tmp_path / "switch.lock")
    monkeypatch.setattr(h.os, "chdir", lambda _path: None)
    monkeypatch.setattr(h.signal, "signal", lambda *_args: None)

    def command(args, **_kwargs):
        assert args[0] == "git"
        return subprocess.CompletedProcess(
            args, 0, "" if args[1] == "status" else RELEASE + "\n", ""
        )

    monkeypatch.setattr(h, "command", command)
    return h, fake


def mutations(fake):
    return [
        c for c in fake.calls if c[0] in {"rename", "stop", "start", "rm"} or c[:2] == ("run", "-d")
    ]


def test_review_is_deterministic_without_container_changes(host):
    h, fake = host
    before = copy.deepcopy(fake.items)
    plan = h.review(RELEASE)
    assert plan == h.review(RELEASE)
    assert h.digest(BINDING) == fingerprint(BINDING)
    assert fake.items == before and not mutations(fake)
    probe = next(c for c in fake.calls if c[:2] == ("run", "--rm"))
    assert probe[probe.index("--network") + 1] == "none"
    assert "--read-only" in probe and "--cap-drop" in probe
    assert "--cap-add" not in probe and "-p" not in probe


def test_activation_and_reviewed_rollback_preserve_same_old_container_and_workers(host):
    h, fake = host
    original_workers = h.workers()
    plan = h.review(RELEASE)
    h.apply(plan)
    assert fake.items[h.BACKUP]["Id"] == OLD_ID
    assert not fake.items[h.BACKUP]["State"]["Running"]
    assert fake.items[h.ACTIVE]["Id"] == "new-id"
    run = next(c for c in fake.calls if c[:2] == ("run", "-d"))
    assert run[run.index("-p") + 1] == "127.0.0.1:8790:8790"
    assert IMAGE in run and h.OLD_IMAGE not in run
    assert str(h.SNAPSHOT) in " ".join(run) and "readonly" in " ".join(run)
    assert "--cap-add" not in run and "--privileged" not in run
    rollback = h.review(RELEASE, rollback=True)
    h.apply(rollback)
    assert fake.items[h.ACTIVE]["Id"] == OLD_ID and fake.items[h.ACTIVE]["State"]["Running"]
    assert fake.items[h.RETIRED]["Id"] == "new-id" and not fake.items[h.RETIRED]["State"]["Running"]
    assert h.workers() == original_workers
    assert not any(c[0] == "rm" for c in fake.calls)
    assert all(not set(c[1:]) & set(h.WORKERS) for c in mutations(fake))


@pytest.mark.parametrize(
    "failure",
    ["create_before", "create_after", "rename_after", "stop_before", "stopped", "auth", "workers"],
)
def test_activation_failure_restores_original_and_retains_allocated_failure(host, failure):
    h, fake = host
    plan = h.review(RELEASE)
    fake.failure = failure
    with pytest.raises(RuntimeError):
        h.apply(plan)
    assert fake.items[h.ACTIVE]["Id"] == OLD_ID and fake.items[h.ACTIVE]["State"]["Running"]
    if failure in ("create_after", "stopped", "auth", "workers"):
        assert fake.items[h.FAILED]["Id"] == "new-id"
        assert not fake.items[h.FAILED]["State"]["Running"]
    assert not any(c[0] == "rm" for c in fake.calls)
    assert fake.probes <= 45


@pytest.mark.parametrize(
    "damage",
    [
        "backup_collision",
        "failed_collision",
        "wrong_image",
        "writable_mount",
        "public_listener",
        "wrong_user",
        "preflight",
    ],
)
def test_review_blocks_unexpected_host_before_mutation(host, damage):
    h, fake = host
    if damage.endswith("collision"):
        name = h.BACKUP if damage.startswith("backup") else h.FAILED
        fake.items[name] = fake.item(name, "retained", frozen=True)
    elif damage == "wrong_image":
        fake.items[h.ACTIVE]["Config"]["Image"] = "unreviewed"
    elif damage == "writable_mount":
        fake.items[h.ACTIVE]["Mounts"][0]["RW"] = True
    elif damage == "public_listener":
        fake.items[h.ACTIVE]["HostConfig"]["PortBindings"] = {
            "8790/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8790"}]
        }
    elif damage == "wrong_user":
        fake.items[h.ACTIVE]["Config"]["User"] = "0:0"
    else:
        fake.failure = "preflight"
    with pytest.raises((ValueError, RuntimeError)):
        h.review(RELEASE)
    assert not mutations(fake)


def test_rollback_accepts_stopped_connected_dashboard(host):
    h, fake = host
    h.apply(h.review(RELEASE))
    fake.items[h.ACTIVE]["State"]["Running"] = False
    h.apply(h.review(RELEASE, rollback=True))
    assert fake.items[h.ACTIVE]["Id"] == OLD_ID


def test_restore_never_stops_unrelated_active_container(host):
    h, fake = host
    h.apply(h.review(RELEASE))
    fake.items[h.ACTIVE]["Config"]["Labels"] = {h.LABEL: "foreign"}
    before = copy.deepcopy(fake.items)
    fake.calls.clear()
    with pytest.raises(RuntimeError):
        h.restore(OLD_ID, retain=h.FAILED)
    assert fake.items == before and not mutations(fake)


def test_cli_exact_review_hash_and_repeat_guard(host, capsys):
    h, fake = host
    if os.geteuid() != 0:
        pytest.skip("Root-only host coordinator")
    assert h.main(["review"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert h.main(["activate", "--review-sha256", "0" * 64]) == 2
    assert not mutations(fake)
    assert h.main(["activate", "--review-sha256", plan["review_sha256"]]) == 0
    assert fake.items[h.ACTIVE]["Id"] == "new-id"


def test_cli_concurrent_operation_lease_blocks_before_docker(host):
    h, fake = host
    if os.geteuid() != 0:
        pytest.skip("Root-only host coordinator")
    fd = os.open(h.LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert h.main(["review"]) == 2
        assert not fake.calls
    finally:
        os.close(fd)


def test_changed_review_between_final_checks_never_switches(host, monkeypatch):
    h, fake = host
    if os.geteuid() != 0:
        pytest.skip("Root-only host coordinator")
    plan = h.review(RELEASE)
    real_review = h.review
    count = [0]

    def changing(*args, **kwargs):
        count[0] += 1
        if count[0] == 2:
            fake.items[h.ACTIVE]["State"]["StartedAt"] = "restarted"
        return real_review(*args, **kwargs)

    monkeypatch.setattr(h, "review", changing)
    assert h.main(["activate", "--review-sha256", plan["review_sha256"]]) == 2
    assert not mutations(fake)


@pytest.mark.parametrize(
    "damage", ["none", "public_binding", "symlink", "public_parent", "wrong_source", "wrong_uid"]
)
@pytest.mark.parametrize('name', ['connected-v1', 'connected-price-options-v1'])
def test_real_binding_file_checks(tmp_path, monkeypatch, damage, name):
    if os.geteuid() != 0:
        pytest.skip("Root-owned publisher preflight")
    h = load()
    parent = tmp_path / "exports"
    parent.mkdir(mode=0o700)
    directory = parent / name
    directory.mkdir(mode=0o711)
    monkeypatch.setattr(h, "SNAPSHOT", directory)
    monkeypatch.setattr(h, "SNAPSHOT_NAME", name)
    value = copy.deepcopy(BINDING)
    value['destination'] = '/exports/' + name
    if damage == "wrong_source":
        value["source_journal"] = "/other/options.db"
    elif damage == "wrong_uid":
        value["reader_uid"] = 0
    path = directory / "binding.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    if damage == "public_binding":
        path.chmod(0o644)
    elif damage == "public_parent":
        parent.chmod(0o755)
    elif damage == "symlink":
        target = directory / "retained.json"
        path.rename(target)
        path.symlink_to(target)
    before = path.read_bytes()
    if damage == "none":
        assert h.binding() == value
    else:
        with pytest.raises((ValueError, OSError)):
            h.binding()
    assert path.read_bytes() == before
