"""Private bounded installed command input; verification cannot grant authority."""

import json

import pytest

from app.mixed.replay_cli import main, read_private


@pytest.mark.parametrize(
    "damage", ["permissions", "symlink", "empty", "size", "relative", "directory"]
)
def test_private_replay_input_rejects_ambiguous_or_unbounded_sources(tmp_path, damage):
    original = tmp_path / "input.json"
    original.write_text("{}")
    original.chmod(0o600)
    path, maximum = original, 100
    if damage == "permissions":
        original.chmod(0o644)
    elif damage == "symlink":
        path = tmp_path / "link"
        path.symlink_to(original)
    elif damage == "empty":
        original.write_text("")
    elif damage == "size":
        maximum = 1
    elif damage == "relative":
        path = "relative.json"
    else:
        path = tmp_path
    with pytest.raises((ValueError, OSError)):
        read_private(path, maximum)


@pytest.mark.parametrize("command", ["run", "verify"])
def test_malformed_cli_input_retains_no_native_authority(tmp_path, capsys, command):
    path = tmp_path / "input.json"
    path.write_text('{"private-content": "must-not-appear-in-output"}')
    path.chmod(0o600)
    args = (
        ["run", "--request", str(path), "--output", str(tmp_path / "run")]
        if command == "run"
        else ["verify", "--bundle", str(path), "--expected-hash", "0" * 64]
    )
    assert main(args) == 2
    result = capsys.readouterr().out
    assert "must-not-appear" not in result
    assert json.loads(result) == {
        "status": "UNAVAILABLE",
        "reason": "MIXED_REPLAY_UNAVAILABLE",
        "execution_authority": False,
        "live_enabled": False,
    }
    assert not (tmp_path / "run").exists()
