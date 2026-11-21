"""Actual host shell paths with an offline Docker recorder, not host acceptance."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/connected-dashboard-snapshot-host.sh"
pytestmark = pytest.mark.skipif(os.getuid() != 0, reason="Root-only host helper")


def fixture(tmp_path, operation):
    root = tmp_path / "repo with spaces"
    (root / "scripts").mkdir(parents=True)
    output = tmp_path / "publish"
    script = root / "scripts/connected-dashboard-snapshot-host.sh"
    script.write_text(
        SCRIPT.read_text().replace("/var/lib/trade-bot-dashboard-publish", str(output))
    )
    source = tmp_path / "owner"
    source.mkdir(mode=0o700)
    for name in ("runtime.json", "options.db", "venue.db"):
        (source / name).write_text("untouched source")
    if operation != "prepare":
        output.mkdir(mode=0o700)
        (output / "connected-v1").mkdir(mode=0o711)
    binary = tmp_path / "bin"
    binary.mkdir()
    git = binary / "git"
    git.write_text(
        '#!/bin/bash\nif [[ "$1" == status ]]; then printf "%s" "${SNAPSHOT_DIRTY:-}"; else printf "%040d\\n" 1; fi\n'
    )
    git.chmod(0o700)
    docker = binary / "docker"
    docker.write_text("""#!/usr/bin/env python3
import json,os,sys
with open(os.environ['SNAPSHOT_DOCKER_LOG'],'a') as stream:
    stream.write(json.dumps(sys.argv[1:])+'\\n')
if os.environ.get('SNAPSHOT_FAIL_IMAGE') and sys.argv[1:3]==['image','inspect']:
    sys.exit(1)
""")
    docker.chmod(0o700)
    log = tmp_path / "docker.jsonl"
    env = {
        **os.environ,
        "PATH": str(binary) + ":" + os.environ["PATH"],
        "SNAPSHOT_DOCKER_LOG": str(log),
    }
    return script, source, output, log, env


def execute(script, source, operation, env, seconds=None):
    args = ["bash", str(script), operation, str(source)]
    if seconds is not None:
        args.append(str(seconds))
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=10, check=False)


@pytest.mark.parametrize("operation", ["prepare", "publish", "check", "run"])
def test_host_helper_only_runs_bounded_offline_snapshot(operation, tmp_path):
    script, source, output, log, env = fixture(tmp_path, operation)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    result = execute(script, source, operation, env, seconds=60 if operation == "run" else None)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    run = next(c for c in calls if c[0] == "run")
    assert run[run.index("--network") + 1] == "none"
    assert run[run.index("--user") + 1] == "0:0"
    assert "--read-only" in run and "--init" in run
    assert [run[i + 1] for i, x in enumerate(run) if x == "--cap-add"] == [
        "CHOWN",
        "DAC_READ_SEARCH",
    ]
    assert run[run.index("--cap-drop") + 1] == "ALL"
    mounts = [run[i + 1] for i, x in enumerate(run) if x == "--mount"]
    assert mounts == [
        f"type=bind,src={source},dst=/source,readonly",
        f"type=bind,src={output},dst=/exports" + (",readonly" if operation == "check" else ""),
    ]
    assert "app.mixed.dashboard_snapshot" in run
    assert ("create" if operation == "prepare" else operation) in run
    assert "--reader-uid" in run and run[run.index("--reader-uid") + 1] == "10001"
    assert "--reader-gid" in run and run[run.index("--reader-gid") + 1] == "10001"
    if operation == "run":
        assert run[-4:] == ["--seconds", "60", "--interval", "5"]
    assert not any(c[0] in {"stop", "start", "rename", "rm", "exec"} for c in calls)
    assert not {"-p", "--publish", "--restart"} & set(run)
    assert not any("read-auth" in x or "dashboard_password" in x or "ui-review" in x for x in run)
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


@pytest.mark.parametrize(
    "damage", ["dirty", "existing", "missing_owner", "image", "duration", "mount_injection"]
)
def test_host_preflight_refuses_before_container_run(tmp_path, damage):
    operation = "prepare" if damage == "existing" else "run"
    script, source, output, log, env = fixture(tmp_path, operation)
    if damage == "dirty":
        env["SNAPSHOT_DIRTY"] = "modified\n"
    elif damage == "existing":
        output.mkdir(mode=0o700)
        (output / "connected-v1").mkdir(mode=0o700)
        (output / "connected-v1/retained").write_text("original failure evidence")
    elif damage == "missing_owner":
        source = tmp_path / "missing"
    elif damage == "image":
        env["SNAPSHOT_FAIL_IMAGE"] = "1"
    elif damage == "mount_injection":
        changed = tmp_path / "owner,readonly"
        source.rename(changed)
        source = changed
    result = execute(
        script,
        source,
        operation,
        env,
        seconds=None if operation == "prepare" else 90000 if damage == "duration" else 60,
    )
    assert result.returncode != 0
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert not any(c[0] == "run" for c in calls)
    if damage == "existing":
        assert (output / "connected-v1/retained").read_text() == "original failure evidence"
