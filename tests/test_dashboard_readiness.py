"""Exercise actual shell startup gates with fake local commands and no Docker/network."""

import os
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "scripts/dashboard-readiness.sh"


def run_shell(tmp_path, *, failures, state="true false 0"):
    binary = tmp_path / "bin"
    binary.mkdir()
    for name, content in {
        "docker": '#!/bin/bash\nprintf "%s\\n" "$PROBE_STATE"\n',
        "curl": """#!/bin/bash
count=0
[[ ! -e "$PROBE_COUNT" ]] || read -r count < "$PROBE_COUNT"
count=$((count+1))
printf '%s\\n' "$count" > "$PROBE_COUNT"
if ((count <= PROBE_FAILURES)); then exit 56; fi
printf '{"status":"OK","service":"options-observer"}\\n'
""",
        "sleep": "#!/bin/bash\nexit 0\n",
    }.items():
        path = binary / name
        path.write_text(content)
        path.chmod(0o700)
    counter = tmp_path / "calls"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; wait_for_dashboard test http://offline.invalid/healthz',
            "test",
            str(HELPER),
        ],
        env={
            **os.environ,
            "PATH": str(binary) + ":" + os.environ["PATH"],
            "PROBE_COUNT": str(counter),
            "PROBE_STATE": state,
            "PROBE_FAILURES": str(failures),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, int(counter.read_text()) if counter.exists() else 0


def test_cold_start_can_exceed_old_six_attempt_limit(tmp_path):
    result, calls = run_shell(tmp_path, failures=7)
    assert result.returncode == 0 and calls == 8
    assert '"status":"OK"' in result.stdout
    assert not result.stderr


def test_never_ready_is_bounded_and_fails(tmp_path):
    result, calls = run_shell(tmp_path, failures=100)
    assert result.returncode == 1 and calls == 45
    assert "90-second" in result.stderr


@pytest.mark.parametrize("state", ["false false 0", "true true 0", "true false 1"])
def test_stopped_oom_or_restarting_container_fails_without_polling(tmp_path, state):
    result, calls = run_shell(tmp_path, failures=0, state=state)
    assert result.returncode == 1 and calls == 0
    assert "stopped, restarted or ran out of memory" in result.stderr


def test_failure_capture_retains_state_and_startup_logs_in_private_directory(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    for name, content in {
        "mktemp": '#!/bin/bash\nmkdir -m 700 "$PROBE_DIR"\nprintf "%s\\n" "$PROBE_DIR"\n',
        "docker": """#!/bin/bash
if [[ "$1" == inspect ]]; then
  echo 'status=exited running=false oom=false exit=1 restarts=0'
else
  echo 'Synthetic startup error'
fi
""",
    }.items():
        path = binary / name
        path.write_text(content)
        path.chmod(0o700)
    directory = tmp_path / "diagnostics"
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; preserve_dashboard_failure test', "test", str(HELPER)],
        env={
            **os.environ,
            "PATH": str(binary) + ":" + os.environ["PATH"],
            "PROBE_DIR": str(directory),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert directory.stat().st_mode & 0o777 == 0o700
    assert "exit=1" in (directory / "state.txt").read_text()
    assert "Synthetic startup error" in (directory / "startup.log").read_text()
    assert str(directory) in result.stderr
