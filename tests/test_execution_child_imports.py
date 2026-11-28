"""Writable import paths must not select any installed fixed execution worker."""

import asyncio
import sys
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.domain.models import Action
from app.execution import alerts, checkpoint_transfer, judgment, market_reads, process
from app.execution.durable_fixture import DurableFixtureVenue
from tests.test_execution_rehearsal import NOW

WORKERS = {
    "fixture": "app.execution.worker",
    "judgment": "app.execution.judgment_worker",
    "market": "app.execution.market_read_worker",
    "alert": "app.execution.alert_worker",
    "archive": "app.execution.checkpoint_worker",
}


@pytest.mark.anyio
@pytest.mark.parametrize("role", WORKERS)
@pytest.mark.parametrize("poison", ["cwd", "pythonpath", "startup-hook"])
async def test_native_fixed_worker_ignores_writable_import_paths(
    tmp_path, monkeypatch, role, poison
):
    venue = DurableFixtureVenue(tmp_path / "venue.db", capital=Decimal(10))
    venue_before = venue.path.read_bytes()
    work, injected = tmp_path / "work", tmp_path / "injected"
    work.mkdir()
    injected.mkdir()
    marker = tmp_path / "poison-executed"
    code = (
        "import os\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('untrusted import executed')\nos._exit(87)\n"
    )
    if poison == "startup-hook":
        (injected / "sitecustomize.py").write_text(code)
        (injected / "usercustomize.py").write_text(code)
    else:
        package = (work if poison == "cwd" else injected) / "app"
        package.mkdir()
        (package / "__init__.py").write_text(code)
    monkeypatch.chdir(work)
    monkeypatch.setenv("PYTHONPATH", str(injected))
    monkeypatch.setenv("PYTHONSTARTUP", str(injected / "sitecustomize.py"))
    monkeypatch.setenv("PYTHONUSERBASE", str(injected))
    monkeypatch.setenv("PYTHONHOME", str(injected))
    monkeypatch.setenv("PYTHONOPTIMIZE", "2")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-fixture-key")
    monkeypatch.setenv("ROBINHOOD_TOKEN", "ambient-fixture-token")
    original = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append((child, args, kwargs))
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    # Invalid private requests exercise import/startup and bounded error protocols
    # without opening credentials, clients or network connections. The fixture
    # worker instead performs a complete valid native local account snapshot.
    invalid = SimpleNamespace(
        model_dump_json=lambda: "{}", deadline_monotonic=time.monotonic() + 15
    )
    error, result = None, None
    try:
        if role == "fixture":
            result = await process.run_fixture_process(venue, now=NOW, timeout_seconds=15)
        elif role == "judgment":
            result = await judgment.run_judgment_process(invalid, "explicit-fixture-key")
        elif role == "market":
            result = await market_reads._read(invalid)
        elif role == "alert":
            result = await alerts._send(invalid)
        else:
            result = await checkpoint_transfer._run(invalid)
    except Exception as exc:  # noqa: BLE001 -- inspect native sanitized protocol failures below
        error = exc
    assert not marker.exists(), "Writable code executed before worker request validation"
    assert len(children) == 1
    child, args, kwargs = children[0]
    assert args == (sys.executable, "-I", "-m", WORKERS[role])
    assert child.returncode is not None
    allowed = {"PATH", "LANG", "LC_ALL"}
    if role == "judgment":
        allowed.add("OPENAI_API_KEY")
        assert kwargs["env"]["OPENAI_API_KEY"] == "explicit-fixture-key"
    assert set(kwargs["env"]) <= allowed
    assert venue.path.read_bytes() == venue_before
    if role == "fixture":
        assert error is None and child.returncode == 0
        assert result.snapshot.account_id == venue.account_id
        assert result.snapshot.cash == Decimal(10) and result.snapshot.orders == []
    elif role == "judgment":
        assert error is None and child.returncode == 0
        assert result.decision.action == Action.HOLD
        assert result.error == "ValidationError" and result.usage is None
    else:
        assert isinstance(error, ValueError) and result is None and child.returncode == 1
