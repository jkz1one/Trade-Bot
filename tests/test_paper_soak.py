import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "paper_soak", Path(__file__).resolve().parents[1] / "scripts/paper-soak.py"
)
soak = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(soak)


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(soak, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True)))


@pytest.mark.parametrize("seconds", [0, 59, 23401, True, 75.5])
def test_reject_invalid_duration_before_creating_state(isolated, tmp_path, seconds):
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="DURATION"):
        soak.run(output, seconds, 68)
    assert not output.exists()


def test_reject_existing_account_without_modification(isolated, tmp_path):
    evidence = tmp_path / "existing.db"
    evidence.write_bytes(b"retain")
    with pytest.raises(ValueError, match="EXISTING_OUTPUT"):
        soak.run(tmp_path, 75, 68)
    assert evidence.read_bytes() == b"retain"
    assert list(tmp_path.iterdir()) == [evidence]


def test_reject_symlink_and_checkout_output(isolated, tmp_path):
    output = tmp_path / "alias"
    output.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError, match="OUTPUT"):
        soak.run(output, 75, 68)
    with pytest.raises(ValueError, match="OUTSIDE_CHECKOUT"):
        soak.run(soak.ROOT / "new", 75, 68)


def test_reject_network_before_import_or_state_creation(isolated, tmp_path, monkeypatch):
    original = Path.read_text

    def read(path, *args, **kwargs):
        if str(path) == "/proc/net/dev":
            return "header\nheader\n lo: 0\n eth0: 0\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="NETWORK_NAMESPACE"):
        soak.run(output, 75, 68)
    assert not output.exists()


@pytest.mark.parametrize("cpus", [0, 2, 3, True])
def test_cpu_comparison_cannot_expand_available_affinity(cpus, tmp_path, monkeypatch):
    monkeypatch.setattr(soak, "validate", lambda *_: {})
    monkeypatch.setattr(soak.os, "sched_getaffinity", lambda _: {7})
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="CPU_AFFINITY"):
        soak.run(output, 90, 68, cpus=cpus)
    assert not output.exists()


@pytest.mark.parametrize("cpus, percent", [(1, 60.0), (2, 30.0)])
def test_cpu_window_includes_reaped_child_and_excludes_setup(cpus, percent):
    from soak_worker import cpu_window

    result = cpu_window((100, 25, 20, 11, 5), (110, 28, 20.5, 13, 5.5), cpus)
    assert result == {
        "elapsed_seconds": 10, "worker_user_seconds": 3, "worker_system_seconds": .5,
        "reaped_child_user_seconds": 2, "reaped_child_system_seconds": .5,
        "average_busy_cores": .6, "average_allocated_cpu_percent": percent,
    }
