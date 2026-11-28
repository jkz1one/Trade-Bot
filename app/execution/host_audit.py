"""Read-only, credential-content-free snapshot of the fixed isolated PAPER host.

This is evidence collection, never installation, lifecycle testing or execution
authority. A matching snapshot cannot complete host acceptance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pwd
import re
import shlex
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.execution.process import _cleanup

PROC = Path("/proc")
UNITS = Path("/etc/systemd/system")
CREDENTIALS = Path("/etc/trade-bot-paper")
ROLES = ("runtime", "control", "alerts")
PEERS = ("model", "market", "operator", "alerts")
UNIT_DIGESTS = {
    "runtime": "afd4847f83c15ea61fd189235083b5028dbb698f23318b09631a8177956a3f4f",
    "control": "ae786560e08674c27dce9724f5c16cdfd980f9b2fa5338146d76edc49557eb74",
    "alerts": "8d14e0c5448c817b49eaf0c360e3afcc69aca7812ff765e9f374f720d190c454",
}
PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "FragmentPath",
    "DropInPaths",
    "NeedDaemonReload",
    "MainPID",
    "InvocationID",
    "ExecMainStartTimestampMonotonic",
    "User",
    "Group",
    "ProtectSystem",
    "NoNewPrivileges",
    "KillMode",
    "Restart",
)
REMAINING_GATES = (
    "target_host_boot_and_lifecycle",
    "credential_peer_creation_after_start",
    "authenticated_market_and_model",
    "independent_alert_delivery",
    "independent_archive_retention_and_retrieval",
    "host_loss_recovery_drill",
    "optional_checkpoint_service_and_timer",
    "deployed_shadow_paths_and_full_namespace_enforcement",
)
COMMAND_TIMEOUT = 5
MAX_COMMAND_BYTES = 64 * 1024


class AuditBlocked(Exception):
    """Only fixed reason codes may reach the public report."""


def require(condition, code):
    if not condition:
        raise AuditBlocked(code)


def read_bounded(path, limit):
    with path.open("rb") as stream:
        result = stream.read(limit + 1)
    require(len(result) <= limit, "METADATA_TOO_LARGE")
    return result


def unit_name(role):
    require(role in ROLES, "UNKNOWN_ROLE")
    return f"trade-bot-paper-{role}.service"


def unit_contract(role):
    path = UNITS / unit_name(role)
    # Do not follow an operator-edited unit symlink or read a special file.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == 0
            and not before.st_mode & 0o022
            and before.st_size <= 16384,
            "UNIT_METADATA_MISMATCH",
        )
        content = stream.read(16385)
        after = os.fstat(stream.fileno())
    identity = lambda info: (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
    require(identity(before) == identity(after) and len(content) <= 16384, "UNIT_CHANGED")
    digest = hashlib.sha256(content).hexdigest()
    require(digest == UNIT_DIGESTS[role], "UNIT_DIGEST_MISMATCH")
    commands = [
        line[10:] for line in content.decode().splitlines() if line.startswith("ExecStart=")
    ]
    require(len(commands) == 1, "UNIT_COMMAND_MISMATCH")
    return digest, tuple(shlex.split(commands[0]))


def parse_properties(payload):
    values = {}
    for line in payload.decode("utf-8").splitlines():
        key, sep, value = line.partition("=")
        require(bool(sep) and key in PROPERTIES and key not in values, "MANAGER_PROTOCOL_MISMATCH")
        values[key] = value
    require(set(values) == set(PROPERTIES), "MANAGER_PROTOCOL_MISMATCH")
    return values


async def show_unit(role):
    # Fixed executable, fixed read-only verb and property whitelist. No shell,
    # supplied unit/path, credentials, journal output or inherited environment.
    process = None
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            "/usr/bin/systemctl",
            "--no-pager",
            "--no-ask-password",
            "show",
            "--all",  # Include empty requested properties such as DropInPaths.
            "--property=" + ",".join(PROPERTIES),
            unit_name(role),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    )
    try:
        async with asyncio.timeout(COMMAND_TIMEOUT):
            process = await asyncio.shield(spawn)
            process.stdin.close()
            output = bytearray()
            while chunk := await process.stdout.read(8192):
                output.extend(chunk)
                require(len(output) <= MAX_COMMAND_BYTES, "MANAGER_OUTPUT_TOO_LARGE")
            require(await process.wait() == 0, "MANAGER_QUERY_FAILED")
        return parse_properties(bytes(output))
    except TimeoutError:
        raise AuditBlocked("MANAGER_QUERY_TIMEOUT") from None
    finally:
        # Retain spawn ownership across timeout/cancellation, then reap the
        # process group using the already-tested repeated-cancellation fence.
        while not spawn.done():
            try:
                await asyncio.shield(spawn)
            except asyncio.CancelledError:
                continue
        if not spawn.cancelled() and spawn.exception() is None:
            await _cleanup(spawn.result())


@dataclass(frozen=True)
class Mount:
    path: str
    options: frozenset[str]
    filesystem: str


def parse_mounts(payload):
    mounts = []
    for line in payload.decode("utf-8").splitlines():
        left, sep, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        require(bool(sep) and len(fields) >= 6 and len(tail) == 3, "MOUNT_PROTOCOL_MISMATCH")
        require(fields[0].isdigit() and fields[1].isdigit(), "MOUNT_PROTOCOL_MISMATCH")
        path = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])
        require(path.startswith("/"), "MOUNT_PROTOCOL_MISMATCH")
        mounts.append(Mount(path, frozenset(fields[5].split(",")), tail[0]))
    return tuple(mounts)


@dataclass(frozen=True)
class Directory:
    device: int
    inode: int
    uid: int
    mode: int


def directory(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    require(stat.S_ISDIR(info.st_mode), "CREDENTIAL_DIRECTORY_MISMATCH")
    return Directory(info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode))


def entries(path):
    # Bound directory enumeration and expose no unexpected entry names.
    found = []
    with os.scandir(path) as items:
        for item in items:
            found.append(item.name)
            require(len(found) <= len(PEERS), "CREDENTIAL_VIEW_MISMATCH")
    return tuple(sorted(found))


def start_ticks(payload):
    # comm can contain spaces and parentheses; fields after its closing ')' start at 3.
    fields = payload.decode().rsplit(")", 1)[-1].split()
    require(len(fields) >= 20 and fields[19].isdigit(), "PROCESS_PROTOCOL_MISMATCH")
    return int(fields[19])


def manager_contract(role, properties):
    expected = {
        "Id": unit_name(role),
        "LoadState": "loaded",
        "ActiveState": "active",
        "SubState": "running",
        "FragmentPath": str(UNITS / unit_name(role)),
        "DropInPaths": "",
        "NeedDaemonReload": "no",
        "User": "tradebot-paper",
        "Group": "tradebot-paper",
        "ProtectSystem": "strict",
        "NoNewPrivileges": "yes",
        "KillMode": "mixed",
        "Restart": "no" if role == "runtime" else "on-failure",
    }
    require(
        all(properties[key] == value for key, value in expected.items()),
        "MANAGER_CONTRACT_MISMATCH",
    )
    pid = properties["MainPID"]
    require(bool(re.fullmatch(r"[1-9][0-9]{0,9}", pid)) and int(pid) > 1, "PROCESS_ID_MISMATCH")
    require(
        bool(re.fullmatch(r"[0-9a-f]{32}", properties["InvocationID"])), "INVOCATION_ID_MISMATCH"
    )
    require(
        bool(re.fullmatch(r"[1-9][0-9]*", properties["ExecMainStartTimestampMonotonic"])),
        "PROCESS_ID_MISMATCH",
    )
    return int(pid)


def process_snapshot(pid, argv, uid, gid):
    base = PROC / str(pid)
    ticks = start_ticks(read_bounded(base / "stat", 8192))
    namespace = os.readlink(base / "ns/mnt")
    host_namespace = os.readlink(PROC / "1/ns/mnt")
    require(
        bool(re.fullmatch(r"mnt:\[[0-9]+\]", namespace)) and namespace != host_namespace,
        "MOUNT_NAMESPACE_MISMATCH",
    )
    observed = read_bounded(base / "cmdline", 8192)
    require(
        observed.endswith(b"\0") and tuple(observed[:-1].decode().split("\0")) == argv,
        "PROCESS_COMMAND_MISMATCH",
    )
    lines = read_bounded(base / "status", 65536).decode().splitlines()
    ids = [line.split()[1:] for line in lines if line.startswith("Uid:")]
    require(ids == [[str(uid)] * 4], "PROCESS_UID_MISMATCH")
    groups = [line.split()[1:] for line in lines if line.startswith("Gid:")]
    require(groups == [[str(gid)] * 4], "PROCESS_GID_MISMATCH")
    payload = read_bounded(base / "mountinfo", 1024 * 1024)
    mounts = parse_mounts(payload)
    root = base / "root" / str(CREDENTIALS).lstrip("/")
    root_info = directory(root)
    require(
        root_info is not None and root_info.uid == 0 and root_info.mode == 0o755,
        "CREDENTIAL_ROOT_MISMATCH",
    )
    names = entries(root)
    require(set(names) <= set(PEERS), "CREDENTIAL_VIEW_MISMATCH")
    peers = {peer: directory(root / peer) for peer in PEERS}
    host_peers = {peer: directory(CREDENTIALS / peer) for peer in PEERS}
    empty = {
        peer: not entries(root / peer)
        for peer in PEERS
        if peers[peer] is not None and peers[peer].mode == 0
    }
    # Re-read start identity after traversing /proc to detect disappearance/reuse.
    require(start_ticks(read_bounded(base / "stat", 8192)) == ticks, "PROCESS_CHANGED")
    return (
        ticks,
        namespace,
        hashlib.sha256(payload).hexdigest(),
        root_info,
        names,
        mounts,
        peers,
        host_peers,
        empty,
    )


def credential_contract(role, snapshot, uid):
    _, _, _, _, _, mounts, peers, host_peers, empty = snapshot
    root_mounts = [mount for mount in mounts if mount.path == str(CREDENTIALS)]
    require(
        len(root_mounts) == 1
        and root_mounts[0].filesystem == "tmpfs"
        and "ro" in root_mounts[0].options
        and "rw" not in root_mounts[0].options,
        "CREDENTIAL_ROOT_MOUNT_MISMATCH",
    )
    allowed = {
        "runtime": {"model": "ro", "market": "rw"},
        "control": {"operator": "ro"},
        "alerts": {"alerts": "ro"},
    }[role]
    for peer in PEERS:
        view, host = peers[peer], host_peers[peer]
        path = str(CREDENTIALS / peer)
        peer_mounts = [mount for mount in mounts if mount.path == path]
        # Nested mounts could bypass the role directory's observed options.
        require(
            not any(mount.path.startswith(path + "/") for mount in mounts),
            "CREDENTIAL_NESTED_MOUNT",
        )
        if peer in allowed and host is not None:
            require(
                view == host and host.uid == uid and host.mode == 0o700,
                "CREDENTIAL_BIND_IDENTITY_MISMATCH",
            )
            require(
                len(peer_mounts) == 1
                and allowed[peer] in peer_mounts[0].options
                and ("rw" if allowed[peer] == "ro" else "ro") not in peer_mounts[0].options,
                "CREDENTIAL_BIND_OPTIONS_MISMATCH",
            )
        elif peer in allowed and role != "runtime":
            raise AuditBlocked("REQUIRED_CREDENTIAL_DIRECTORY_MISSING")
        else:
            # InaccessiblePaths may produce an empty mode-000 placeholder.
            require(
                view is None
                or (
                    view.mode == 0
                    and empty.get(peer)
                    and (host is None or (view.device, view.inode) != (host.device, host.inode))
                ),
                "PEER_CREDENTIAL_VISIBLE",
            )
            require(view is not None or not peer_mounts, "PEER_MOUNT_MISMATCH")


async def audit_role(role, uid, gid):
    digest, argv = unit_contract(role)
    before = await show_unit(role)
    pid = manager_contract(role, before)
    snapshot = process_snapshot(pid, argv, uid, gid)
    credential_contract(role, snapshot, uid)
    after = await show_unit(role)
    require(
        after == before
        and unit_contract(role) == (digest, argv)
        and process_snapshot(pid, argv, uid, gid) == snapshot,
        "SNAPSHOT_CHANGED",
    )
    return {
        "role": role,
        "status": "OBSERVED",
        "unit_sha256": digest,
        "pid": pid,
        "invocation_id": before["InvocationID"],
        "process_start_ticks": snapshot[0],
        "mount_namespace": snapshot[1],
    }


def boot_id():
    value = read_bounded(PROC / "sys/kernel/random/boot_id", 128).decode().strip()
    require(str(UUID(value)) == value, "BOOT_ID_MISMATCH")
    return value


async def audit_host():
    report = {
        "schema": "paper-host-audit-v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "snapshot_status": "BLOCKED",
        "host_acceptance": "UNVERIFIED",
        "execution_authority": False,
        "live_enabled": False,
        "roles": [],
        "remaining_gates": list(REMAINING_GATES),
    }
    try:
        require(os.geteuid() == 0, "ROOT_METADATA_ACCESS_REQUIRED")
        require(
            read_bounded(PROC / "1/comm", 128).strip() == b"systemd", "SYSTEMD_MANAGER_UNAVAILABLE"
        )
        before = boot_id()
        report["boot_id"] = before
        user = pwd.getpwnam("tradebot-paper")
        require(user.pw_uid > 0 and user.pw_gid > 0, "DEDICATED_USER_REQUIRED")
        for role in ROLES:
            try:
                report["roles"].append(await audit_role(role, user.pw_uid, user.pw_gid))
            except AuditBlocked as exc:
                report["roles"].append({"role": role, "status": "BLOCKED", "reason": str(exc)})
            except (OSError, ValueError, KeyError):
                report["roles"].append(
                    {"role": role, "status": "BLOCKED", "reason": "METADATA_UNAVAILABLE"}
                )
        require(boot_id() == before, "BOOT_CHANGED")
        if all(role["status"] == "OBSERVED" for role in report["roles"]):
            report["snapshot_status"] = "OBSERVED"
    except AuditBlocked as exc:
        report["reason"] = str(exc)
    except (OSError, ValueError, KeyError):
        report["reason"] = "METADATA_UNAVAILABLE"
    return report


def main():
    import argparse

    argparse.ArgumentParser(description=__doc__).parse_args()
    report = asyncio.run(audit_host())
    print(json.dumps(report, sort_keys=True))
    return 0 if report["snapshot_status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
