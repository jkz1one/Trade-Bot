"""Harness protocol/cleanup proof only; no local fixture proves systemd enforcement."""

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness():
    return load("paper-sandbox-acceptance")


@pytest.mark.parametrize("role", ["runtime", "control", "alerts", "checkpoint"])
def test_reviewed_sandbox_directives_survive_only_named_substitutions(harness, role):
    state, credentials = Path("/var/lib/disposable"), Path("/etc/disposable")
    actual = harness.properties(role, state, credentials)
    raw = (ROOT / f"deploy/paper/trade-bot-paper-{role}.service").read_text()
    section = raw.split("[Service]\n")[1].split("[Install]")[0]
    omitted = {"Type", "ExecStart", "Restart", "TimeoutStopSec"}
    expected = [
        line.replace("/var/lib/trade-bot-paper", str(state)).replace(
            "/etc/trade-bot-paper", str(credentials)
        )
        for line in section.splitlines()
        if "=" in line and line.split("=", 1)[0] not in omitted
    ]
    assert actual == expected + ["Restart=no", "TimeoutStopSec=5", "RuntimeMaxSec=30"]
    assert "User=tradebot-paper" in actual and "Group=tradebot-paper" in actual
    assert "TemporaryFileSystem=/etc/disposable:ro,mode=0755,size=1M" in actual
    assert "InaccessiblePaths=-/var/lib/trade-bot -/etc/trade-bot -/opt/trade-bot" in actual
    assert "ProtectSystem=strict" in actual
    if role == "checkpoint":
        assert "PrivateNetwork=yes" in actual and "RestrictAddressFamilies=AF_UNIX" in actual


@pytest.mark.parametrize("role", ["runtime", "control", "alerts", "checkpoint"])
def test_modified_reviewed_unit_rejected_before_mutation(harness, tmp_path, monkeypatch, role):
    units = tmp_path / "deploy/paper"
    units.mkdir(parents=True)
    (units / f"trade-bot-paper-{role}.service").write_text("[Service]\nUser=root\n")
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="REVIEWED_UNIT_CHANGED"):
        harness.properties(role, Path("/var/lib/unused"), Path("/etc/unused"))


@pytest.mark.parametrize("role", ["runtime", "control", "alerts", "checkpoint"])
def test_native_parser_accepts_rendered_probe_directives(harness, tmp_path, role):
    binary = shutil.which("systemd-analyze")
    if binary is None:
        pytest.skip("Native systemd parser unavailable")
    props = harness.properties(role, Path("/var/lib/unused"), Path("/etc/unused"))
    # Parser proof only. Account substitution is not used by the real harness.
    props = [
        p.replace("User=tradebot-paper", f"User={os.geteuid()}").replace(
            "Group=tradebot-paper", f"Group={os.getegid()}"
        )
        for p in props
    ]
    target = tmp_path / f"paper-acceptance-{role}.service"
    target.write_text(
        "[Service]\nType=exec\nExecStart=/usr/bin/python3 -I -B /probe.py\n"
        + "\n".join(props)
        + "\n"
    )
    result = subprocess.run(
        [binary, "verify", "--man=no", str(target)], capture_output=True, timeout=10, check=False
    )
    assert result.returncode == 0 and result.stderr == b""


@pytest.mark.parametrize("blocked", ["opt-in", "root", "systemd", "identity"])
def test_missing_prerequisite_never_calls_manager(harness, monkeypatch, capsys, blocked):
    monkeypatch.setattr(harness.os, "geteuid", lambda: 1 if blocked == "root" else 0)
    monkeypatch.setattr(
        Path, "read_text", lambda self: "systemd" if blocked != "systemd" else "other"
    )
    monkeypatch.setattr(harness.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=0, pw_gid=0))
    monkeypatch.setattr(harness.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=0))
    monkeypatch.setattr(harness, "command", lambda *a, **k: pytest.fail("manager must not run"))
    monkeypatch.setattr(harness, "run_case", lambda *a: pytest.fail("case must not run"))
    assert harness.main([] if blocked == "opt-in" else ["--run"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED" and report["cases"] == []
    assert report["host_acceptance"] == "UNVERIFIED"
    assert not report["execution_authority"] and not report["live_enabled"]


def enable_prerequisites(harness, monkeypatch):
    monkeypatch.setattr(harness.os, "geteuid", lambda: 0)
    original = Path.read_text
    monkeypatch.setattr(
        Path, "read_text", lambda self: "systemd" if str(self) == "/proc/1/comm" else original(self)
    )
    monkeypatch.setattr(
        harness.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=123, pw_gid=124)
    )
    monkeypatch.setattr(harness.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=124))


def test_all_templates_checked_before_first_case(harness, tmp_path, monkeypatch, capsys):
    enable_prerequisites(harness, monkeypatch)
    units = tmp_path / "deploy/paper"
    units.mkdir(parents=True)
    for role in harness.DIGESTS:
        shutil.copyfile(
            ROOT / f"deploy/paper/trade-bot-paper-{role}.service",
            units / f"trade-bot-paper-{role}.service",
        )
    with (units / "trade-bot-paper-checkpoint.service").open("a") as stream:
        stream.write("# unreviewed drift\n")
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(
        harness, "run_case", lambda *a: pytest.fail("must check final unit before admission")
    )
    assert harness.main(["--run"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "REVIEWED_UNIT_CHANGED"


@pytest.mark.parametrize("cleanup", [False, True])
def test_complete_or_cleanup_blocked_report_cannot_grant_host_acceptance(
    harness, monkeypatch, capsys, cleanup
):
    enable_prerequisites(harness, monkeypatch)
    calls = []
    unit = "trade-bot-paper-acceptance-" + "a" * 32 + ".service"

    def case(*args):
        calls.append(args[:2])
        if cleanup:
            raise harness.CleanupBlocked(unit)
        return {"status": "OBSERVED"}

    monkeypatch.setattr(harness, "run_case", case)
    assert harness.main(["--run"]) == (1 if cleanup else 0)
    report = json.loads(capsys.readouterr().out)
    assert report["host_acceptance"] == "UNVERIFIED" and not report["execution_authority"]
    if cleanup:
        assert (
            report["reason"] == "PROBE_CLEANUP_BLOCKED"
            and report["retained_transient_unit"] == unit
        )
        assert len(calls) == 1 and report["cases"] == []
    else:
        assert calls == [(role, missing) for role in harness.DIGESTS for missing in (False, True)]
        assert report["status"] == "OBSERVED" and len(report["cases"]) == 8


def test_probe_wait_detects_failed_service_without_waiting_for_deadline(
    harness, tmp_path, monkeypatch
):
    monkeypatch.setattr(harness, "command", lambda *a, **k: "failed")
    with pytest.raises(RuntimeError, match="PROBE_NOT_RUNNING"):
        harness.wait_file(tmp_path / "missing.json", "trade-bot-paper-acceptance-fixture.service")


def test_probe_wait_deadline_is_bounded(harness, tmp_path, monkeypatch):
    clock = iter((0, 11))
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(harness, "command", lambda *a, **k: pytest.fail("expired wait must stop"))
    with pytest.raises(RuntimeError, match="PROBE_DEADLINE"):
        harness.wait_file(tmp_path / "missing.json", "trade-bot-paper-acceptance-fixture.service")


@pytest.mark.parametrize("role", ["runtime", "control", "alerts", "checkpoint"])
def test_unrestricted_dummy_access_cannot_pass_as_sandbox_proof(harness, role):
    value = {
        "uid": 123,
        "gid": 124,
        "access": {
            peer: {"read": True, "write": True}
            for peer in ("model", "market", "operator", "alerts", "late", "outside")
        },
    }
    with pytest.raises(RuntimeError, match="SANDBOX_ACCESS_MISMATCH"):
        harness.validate(
            value, role, {"model", "market", "operator", "alerts"}, 123, 124, before=True
        )


@pytest.fixture
def case_environment(harness, tmp_path, monkeypatch):
    for name in ("var", "etc"):
        (tmp_path / name).mkdir()

    def mapped_path(value):
        return tmp_path / {"/var/lib": "var", "/etc": "etc"}.get(value, value)

    monkeypatch.setattr(harness, "Path", mapped_path)
    monkeypatch.setattr(
        harness.os, "readlink", lambda path: "mnt:1" if path == "/proc/1/ns/mnt" else "mnt:2"
    )
    # Current test UID owns harmless files. Manager/query behavior is simulated.
    stopped, submitted = [], []
    monkeypatch.setattr(harness, "stop", lambda unit: stopped.append(unit))

    def manager(argv, **kwargs):
        if argv[0] == "/usr/bin/systemd-run":
            submitted.append(argv)
            return None
        assert argv[:2] == ["/usr/bin/systemctl", "show"]
        return "123" if "--property=MainPID" in argv else "active"

    monkeypatch.setattr(harness, "command", manager)
    return tmp_path, stopped, submitted


@pytest.mark.parametrize("role", ["runtime", "control", "alerts", "checkpoint"])
@pytest.mark.parametrize("missing", [False, True])
def test_two_observations_late_creation_and_unique_owned_cleanup(
    harness, case_environment, monkeypatch, role, missing
):
    root, stopped, submitted = case_environment
    snapshots = []

    def observation(path, unit):
        credentials = next((root / "etc").iterdir())
        population = next((root / "var").iterdir()) / "population"
        present = {p.name for p in credentials.iterdir()}
        if snapshots:
            assert present == {"model", "market", "operator", "alerts", "late"}
            assert (population / "continue").exists()
        else:
            assert "late" not in present
            snapshots.append(present)
        # This is a simulated access matrix, never evidence of kernel enforcement.
        access = {
            peer: {
                "read": peer in harness.ALLOWED[role] and peer in snapshots[0],
                "write": harness.ALLOWED[role].get(peer, False) and peer in snapshots[0],
            }
            for peer in ("model", "market", "operator", "alerts", "late")
        }
        access["outside"] = {"read": True, "write": False}
        return {"uid": os.geteuid(), "gid": os.getegid(), "access": access}

    monkeypatch.setattr(harness, "wait_file", observation)
    previous = os.umask(0o077)
    try:
        result = harness.run_case(role, missing, os.geteuid(), os.getegid())
    finally:
        os.umask(previous)
    assert (
        result["status"] == "OBSERVED" and result["before"]["access"] == result["after"]["access"]
    )
    assert len(stopped) == len(submitted) == 1
    argv = submitted[0]
    assert "--unit=" + stopped[0] in argv
    assert "--no-block" in argv and "--property=Restart=no" in argv
    assert argv[-7:-4] == ["/usr/bin/python3", "-I", "-B"]
    assert not list((root / "etc").iterdir()) and not list((root / "var").iterdir())


@pytest.mark.parametrize("failure", ["lost-start", "bad-probe", "cleanup"])
def test_uncertain_submission_always_stops_and_unconfirmed_cleanup_retains_files(
    harness, case_environment, monkeypatch, failure
):
    root, stopped, _submitted = case_environment
    if failure == "lost-start":

        def lost(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 10)

        monkeypatch.setattr(harness, "command", lost)
    else:
        monkeypatch.setattr(harness, "wait_file", lambda *a: {"access": {}})
    if failure == "cleanup":

        def blocked(unit):
            stopped.append(unit)
            raise RuntimeError("PROBE_CLEANUP_BLOCKED")

        monkeypatch.setattr(harness, "stop", blocked)
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired, harness.CleanupBlocked)) as caught:
        harness.run_case("runtime", False, os.geteuid(), os.getegid())
    assert len(stopped) == 1
    if failure == "cleanup":
        assert caught.value.unit == stopped[0]
    assert bool(list((root / "etc").iterdir())) == (failure == "cleanup")
    assert bool(list((root / "var").iterdir())) == (failure == "cleanup")


def test_native_dummy_probe_handshake_and_explicit_termination(tmp_path):
    population, credentials = tmp_path / "population", tmp_path / "credentials"
    population.mkdir()
    credentials.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("dummy")
    child = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            str(ROOT / "scripts/paper-sandbox-probe.py"),
            str(population),
            str(credentials),
            str(outside),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def wait(name):
        path = population / name
        deadline = time.monotonic() + 5
        while not path.exists():
            assert child.poll() is None and time.monotonic() < deadline
            time.sleep(0.01)
        return json.loads(path.read_text())

    try:
        before = wait("before.json")
        assert before["uid"] == os.geteuid()
        assert before["access"]["late"] == {"read": False, "write": False}
        (credentials / "late").mkdir()
        (credentials / "late/dummy").write_text("dummy")
        (population / "continue").touch()
        after = wait("after.json")
        assert after["access"]["late"] == {"read": True, "write": True}
        # Ordinary filesystem access is deliberately not accepted as sandbox evidence.
        child.terminate()
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == -signal.SIGTERM and stdout == stderr == b""
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
