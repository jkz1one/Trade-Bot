"""Fixture evidence for the read-only audit, never target-host acceptance."""

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.execution import host_audit as audit

UID, GID = 1234, 1235
ROOT = str(audit.CREDENTIALS)


def properties(role):
    return {
        "Id": audit.unit_name(role),
        "LoadState": "loaded",
        "ActiveState": "active",
        "SubState": "running",
        "FragmentPath": str(audit.UNITS / audit.unit_name(role)),
        "DropInPaths": "",
        "NeedDaemonReload": "no",
        "MainPID": "2345",
        "InvocationID": "a" * 32,
        "ExecMainStartTimestampMonotonic": "123",
        "User": "tradebot-paper",
        "Group": "tradebot-paper",
        "ProtectSystem": "strict",
        "NoNewPrivileges": "yes",
        "KillMode": "mixed",
        "Restart": "no" if role == "runtime" else "on-failure",
    }


def snapshot(role):
    host = {peer: audit.Directory(7, i, UID, 0o700) for i, peer in enumerate(audit.PEERS, 10)}
    allowed = {
        "runtime": {"model": "ro", "market": "rw"},
        "control": {"operator": "ro"},
        "alerts": {"alerts": "ro"},
    }[role]
    views = {peer: host[peer] if peer in allowed else None for peer in audit.PEERS}
    mounts = [audit.Mount(ROOT, frozenset({"ro"}), "tmpfs")]
    mounts += [
        audit.Mount(f"{ROOT}/{peer}", frozenset({option}), "ext4")
        for peer, option in allowed.items()
    ]
    return [
        99,
        "mnt:[42]",
        "digest",
        audit.Directory(9, 9, 0, 0o755),
        tuple(allowed),
        tuple(mounts),
        views,
        host,
        {},
    ]


@pytest.mark.parametrize("role", audit.ROLES)
def test_reviewed_unit_digest_and_command(role, monkeypatch):
    # Fixture root ownership without requiring the test checkout to be root-owned.
    fstat = audit.os.fstat

    def root_stat(fd):
        info = fstat(fd)
        names = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        return SimpleNamespace(st_uid=0, **{name: getattr(info, name) for name in names})

    monkeypatch.setattr(audit.os, "fstat", root_stat)
    monkeypatch.setattr(audit, "UNITS", Path(__file__).parent.parent / "deploy/paper")
    digest, argv = audit.unit_contract(role)
    assert digest == audit.UNIT_DIGESTS[role]
    assert argv[:3] == ("/opt/trade-bot-paper/venv/bin/python", "-I", "-m")


@pytest.mark.parametrize("change", ["edit", "symlink", "writable", "fifo"])
def test_unit_drift_and_special_files_are_blocked(tmp_path, monkeypatch, change):
    monkeypatch.setattr(audit, "UNITS", tmp_path)
    unit = tmp_path / audit.unit_name("runtime")
    if change == "symlink":
        unit.symlink_to(Path(__file__).parent.parent / "deploy/paper" / unit.name)
    elif change == "fifo":
        os.mkfifo(unit)
    else:
        unit.write_text("secret material must not appear in output")
        unit.chmod(0o666 if change == "writable" else 0o644)
    with pytest.raises((audit.AuditBlocked, OSError)):
        audit.unit_contract("runtime")


@pytest.mark.parametrize("role", audit.ROLES)
def test_matching_credentials_and_manager(role):
    assert audit.manager_contract(role, properties(role)) == 2345
    audit.credential_contract(role, snapshot(role), UID)


@pytest.mark.parametrize(
    "key,value",
    [
        ("DropInPaths", "/secret/override.conf"),
        ("NeedDaemonReload", "yes"),
        ("SubState", "auto-restart"),
        ("MainPID", "0"),
        ("MainPID", "123 secret"),
        ("InvocationID", "secret"),
        ("User", "root"),
        ("ProtectSystem", "no"),
        ("NoNewPrivileges", "no"),
        ("ExecMainStartTimestampMonotonic", "0"),
    ],
)
def test_manager_drift_is_blocked_without_echoing_values(key, value):
    values = properties("runtime")
    values[key] = value
    with pytest.raises(audit.AuditBlocked) as caught:
        audit.manager_contract("runtime", values)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("root_rw", "CREDENTIAL_ROOT_MOUNT_MISMATCH"),
        ("root_ext4", "CREDENTIAL_ROOT_MOUNT_MISMATCH"),
        ("stacked_root", "CREDENTIAL_ROOT_MOUNT_MISMATCH"),
        ("model_rw", "CREDENTIAL_BIND_OPTIONS_MISMATCH"),
        ("market_ro", "CREDENTIAL_BIND_OPTIONS_MISMATCH"),
        ("foreign_model", "CREDENTIAL_BIND_IDENTITY_MISMATCH"),
        ("readable_peer", "PEER_CREDENTIAL_VISIBLE"),
        ("nested_mount", "CREDENTIAL_NESTED_MOUNT"),
        ("required_missing", "REQUIRED_CREDENTIAL_DIRECTORY_MISSING"),
        ("nonempty_placeholder", "PEER_CREDENTIAL_VISIBLE"),
    ],
)
def test_mount_and_peer_failures(mutation, reason):
    role = "control" if mutation == "required_missing" else "runtime"
    value = snapshot(role)
    mounts = list(value[5])
    if mutation == "root_rw":
        mounts[0] = replace(mounts[0], options=frozenset({"rw"}))
    elif mutation == "root_ext4":
        mounts[0] = replace(mounts[0], filesystem="ext4")
    elif mutation == "stacked_root":
        mounts.append(mounts[0])
    elif mutation in {"model_rw", "market_ro"}:
        index = 1 if mutation == "model_rw" else 2
        mounts[index] = replace(mounts[index], options=frozenset({"rw" if index == 1 else "ro"}))
    elif mutation == "foreign_model":
        value[6]["model"] = replace(value[6]["model"], inode=999)
    elif mutation == "readable_peer":
        value[6]["operator"] = value[7]["operator"]
    elif mutation == "nested_mount":
        mounts.append(audit.Mount(ROOT + "/model/key", frozenset({"rw"}), "ext4"))
    elif mutation == "required_missing":
        value[6]["operator"] = value[7]["operator"] = None
    else:
        value[6]["operator"] = audit.Directory(1, 999, 0, 0)
        value[8]["operator"] = False
    value[5] = tuple(mounts)
    with pytest.raises(audit.AuditBlocked, match=reason):
        audit.credential_contract(role, value, UID)


def test_absent_optional_credentials_and_inaccessible_peer_placeholders():
    value = snapshot("runtime")
    value[5] = value[5][:1]
    for peer in ("model", "market"):
        value[6][peer] = value[7][peer] = None
    value[6]["operator"] = audit.Directory(1, 999, 0, 0)
    value[8]["operator"] = True
    audit.credential_contract("runtime", value, UID)


def test_mount_parser_uses_per_mount_options_and_octal_paths():
    result = audit.parse_mounts(
        b"1 2 0:1 / /etc/trade-bot-paper ro shared:7 - tmpfs tmpfs rw\n"
        b"3 1 8:1 / /space\\040name rw - ext4 /dev/sda ro\n"
    )
    assert result[0].options == frozenset({"ro"})
    assert result[1].path == "/space name"
    assert audit.start_ticks(b"123 (name (with) spaces) S " + b"0 " * 18 + b"99\n") == 99


@pytest.mark.parametrize("payload", [b"secret", b"Id=a\nId=b", b"Unexpected=secret"])
def test_bad_manager_protocol(payload):
    with pytest.raises(audit.AuditBlocked, match="MANAGER_PROTOCOL_MISMATCH"):
        audit.parse_properties(payload)


@pytest.fixture
def observed_host(monkeypatch):
    monkeypatch.setattr(audit.os, "geteuid", lambda: 0)
    monkeypatch.setattr(audit, "read_bounded", lambda path, limit: b"systemd")
    monkeypatch.setattr(audit, "boot_id", lambda: "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(audit.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=UID, pw_gid=GID))
    monkeypatch.setattr(audit, "unit_contract", lambda role: (audit.UNIT_DIGESTS[role], ("argv",)))
    monkeypatch.setattr(audit, "process_snapshot", lambda pid, argv, uid, gid: snapshot("runtime"))

    async def show(role):
        return properties(role)

    monkeypatch.setattr(audit, "show_unit", show)


def test_matching_snapshot_never_completes_acceptance(observed_host, monkeypatch):
    monkeypatch.setattr(audit, "credential_contract", lambda *args: None)
    report = asyncio.run(audit.audit_host())
    assert report["snapshot_status"] == "OBSERVED"
    assert report["host_acceptance"] == "UNVERIFIED"
    assert not report["execution_authority"] and not report["live_enabled"]
    assert len(report["roles"]) == 3 and len(report["remaining_gates"]) == 8


@pytest.mark.parametrize("change", ["pid", "mount", "boot", "unit"])
def test_changed_observation_cannot_pass(observed_host, monkeypatch, change):
    monkeypatch.setattr(audit, "credential_contract", lambda *args: None)
    count = 0

    def changed(*args):
        nonlocal count
        count += 1
        if change == "mount":
            value = snapshot("runtime")
            value[1] = f"mnt:[{count}]"
            return value
        if change == "unit":
            return (str(count), ("argv",))
        return str(count)

    if change == "pid":

        async def show(role):
            values = properties(role)
            values["MainPID"] = changed()
            return values

        monkeypatch.setattr(audit, "show_unit", show)
    else:
        monkeypatch.setattr(
            audit,
            {"mount": "process_snapshot", "boot": "boot_id", "unit": "unit_contract"}[change],
            changed,
        )
    report = asyncio.run(audit.audit_host())
    assert report["snapshot_status"] == "BLOCKED"
    assert report["host_acceptance"] == "UNVERIFIED"


def test_metadata_errors_are_sanitized(observed_host, monkeypatch):
    def fail(*args):
        raise OSError("secret material in path")

    monkeypatch.setattr(audit, "unit_contract", fail)
    report = asyncio.run(audit.audit_host())
    assert all(role["reason"] == "METADATA_UNAVAILABLE" for role in report["roles"])
    assert "secret" not in json.dumps(report)


@pytest.mark.parametrize(
    "root,manager,reason",
    [
        (False, b"systemd", "ROOT_METADATA_ACCESS_REQUIRED"),
        (True, b"supervisord", "SYSTEMD_MANAGER_UNAVAILABLE"),
    ],
)
def test_preconditions_do_not_query_or_read_services(monkeypatch, root, manager, reason):
    monkeypatch.setattr(audit.os, "geteuid", lambda: 0 if root else 1000)
    monkeypatch.setattr(audit, "read_bounded", lambda *args: manager)

    async def forbidden(*args):
        pytest.fail("service queried despite missing preconditions")

    monkeypatch.setattr(audit, "show_unit", forbidden)
    report = asyncio.run(audit.audit_host())
    assert report["reason"] == reason and report["roles"] == []


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("timeout", "MANAGER_QUERY_TIMEOUT"),
        ("overflow", "MANAGER_OUTPUT_TOO_LARGE"),
        ("error", "MANAGER_QUERY_FAILED"),
    ],
)
def test_native_bounded_query_reaps_child_and_never_echoes_stderr(monkeypatch, mode, reason):
    async def scenario():
        spawn = asyncio.create_subprocess_exec
        children = []

        async def fixture(*args, **kwargs):
            assert args[:4] == ("/usr/bin/systemctl", "--no-pager", "--no-ask-password", "show")
            assert args[-1] == "trade-bot-paper-runtime.service"
            assert set(kwargs["env"]) == {"PATH", "LANG", "LC_ALL"}
            code = {
                "timeout": "import time; time.sleep(30)",
                "overflow": "import sys; sys.stdout.write('x'*100000)",
                "error": "import sys; sys.stderr.write('secret'); sys.exit(2)",
            }[mode]
            process = await spawn(sys.executable, "-I", "-c", code, **kwargs)
            children.append(process)
            return process

        monkeypatch.setattr(audit.asyncio, "create_subprocess_exec", fixture)
        monkeypatch.setattr(audit, "COMMAND_TIMEOUT", 0.2)
        with pytest.raises(audit.AuditBlocked, match=reason) as caught:
            await audit.show_unit("runtime")
        assert "secret" not in str(caught.value)
        assert len(children) == 1 and children[0].returncode is not None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change,reason",
    [
        ("none", None),
        ("argv", "PROCESS_COMMAND_MISMATCH"),
        ("uid", "PROCESS_UID_MISMATCH"),
        ("gid", "PROCESS_GID_MISMATCH"),
        ("namespace", "MOUNT_NAMESPACE_MISMATCH"),
        ("extra_name", "CREDENTIAL_VIEW_MISMATCH"),
        ("reused_pid", "PROCESS_CHANGED"),
    ],
)
def test_proc_collection_is_metadata_only(tmp_path, monkeypatch, change, reason):
    proc = tmp_path / "proc"
    monkeypatch.setattr(audit, "PROC", proc)
    base = proc / "2345"
    (base / "ns").mkdir(parents=True)
    (proc / "1/ns").mkdir(parents=True)
    (proc / "1/ns/mnt").symlink_to("mnt:[1]")
    (base / "ns/mnt").symlink_to("mnt:[1]" if change == "namespace" else "mnt:[2]")
    (base / "stat").write_bytes(b"2345 (python) S " + b"0 " * 18 + b"99\n")
    argv = ("python", "-I", "-m", "app.execution.runtime_cli")
    (base / "cmdline").write_bytes(
        b"secret\0" if change == "argv" else "\0".join(argv).encode() + b"\0"
    )
    uid, gid = (0 if change == "uid" else UID), (0 if change == "gid" else GID)
    (base / "status").write_text(f"Uid:\t{uid} {uid} {uid} {uid}\nGid:\t{gid} {gid} {gid} {gid}\n")
    (base / "mountinfo").write_text(f"1 2 0:1 / {ROOT} ro - tmpfs tmpfs rw\n")
    root = base / "root" / ROOT.lstrip("/")
    root.mkdir(parents=True)
    root.chmod(0o755)
    original_directory = audit.directory

    def fixture_directory(path):
        result = original_directory(path)
        return replace(result, uid=0) if path == root and result is not None else result

    monkeypatch.setattr(audit, "directory", fixture_directory)
    if change == "extra_name":
        (root / "secret-name-must-not-appear").touch()
    # Do not open a credential file, execution database or any other path.
    original = audit.read_bounded
    seen = []

    def guarded(path, limit):
        assert path.parent == base
        assert path.name in {"stat", "cmdline", "status", "mountinfo"}
        seen.append(path.name)
        data = original(path, limit)
        if change == "reused_pid" and path.name == "stat" and seen.count("stat") == 2:
            return data.replace(b"99", b"100")
        return data

    monkeypatch.setattr(audit, "read_bounded", guarded)
    if reason:
        with pytest.raises(audit.AuditBlocked, match=reason) as caught:
            audit.process_snapshot(2345, argv, UID, GID)
        assert "secret" not in str(caught.value)
    else:
        value = audit.process_snapshot(2345, argv, UID, GID)
        assert value[0] == 99 and value[1] == "mnt:[2]"
        assert seen == ["stat", "cmdline", "status", "mountinfo", "stat"]


def test_native_query_parses_only_fixed_properties(monkeypatch):
    async def scenario():
        original = asyncio.create_subprocess_exec

        async def fixture(*args, **kwargs):
            payload = "\n".join(f"{key}={value}" for key, value in properties("runtime").items())
            assert "--all" in args  # Retain empty DropInPaths instead of suppressing it.
            return await original(sys.executable, "-I", "-c", f"print({payload!r})", **kwargs)

        monkeypatch.setattr(audit.asyncio, "create_subprocess_exec", fixture)
        assert await audit.show_unit("runtime") == properties("runtime")

    asyncio.run(scenario())


def test_native_query_cancellation_retains_child_ownership(monkeypatch):
    async def scenario():
        original = asyncio.create_subprocess_exec
        children = []
        ready = asyncio.Event()

        async def fixture(*args, **kwargs):
            child = await original(
                sys.executable, "-I", "-c", "import time; time.sleep(30)", **kwargs
            )
            children.append(child)
            ready.set()
            return child

        monkeypatch.setattr(audit.asyncio, "create_subprocess_exec", fixture)
        task = asyncio.create_task(audit.show_unit("runtime"))
        await asyncio.wait_for(ready.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert len(children) == 1 and children[0].returncode is not None

    asyncio.run(scenario())
