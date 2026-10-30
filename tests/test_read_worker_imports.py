"""Cold market-read children do not load parent-only execution/storage machinery."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["app.options.read_worker", "app.execution.market_read_worker", "app.options.earnings_mapping"])
def test_installed_market_read_child_does_not_import_execution_engines(module):
    script = """
import importlib.abc, importlib, sys
blocked = ("app.execution.engine", "app.options.engine", "app.storage", "sqlalchemy", "exchange_calendars")
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError("Parent-only import in read child: " + fullname)
sys.meta_path.insert(0, Guard())
importlib.import_module(sys.argv[1])
assert not any(name in sys.modules for name in blocked)
print("CHILD_IMPORTS_OK")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", script, module],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "CHILD_IMPORTS_OK"
