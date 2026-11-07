"""Fixed native children must not initialize the model runtime to acknowledge work."""

import json
import os
import subprocess
import sys
import time

import pytest
from test_mixed_accounting import buy
from test_mixed_venue import original_option, venue_at
from test_option_execution import NOW

from app.options.process import OptionRequest


@pytest.mark.parametrize("operation", ["snapshot", "stock_accept", "accept"])
def test_native_child_completes_without_loading_owner_or_model_runtime(tmp_path, operation):
    venue = venue_at(tmp_path)
    intent = original_option(tmp_path / "option")[0] if operation == "accept" else None
    request = OptionRequest(
        operation=operation,
        path=str(venue.path),
        venue_id=venue.venue_id,
        account_id=venue.account_id,
        population_id=venue.population_id,
        now=NOW,
        deadline_monotonic=time.monotonic() + 5,
        parent_pid=os.getpid(),
        stock_limits=venue.stock_limits,
        stock_intent=buy(at=NOW) if operation == "stock_accept" else None,
        intent=intent,
    )
    # A fresh isolated interpreter exercises the real worker protocol. Import
    # denial catches the dependency regression without relying on a speed ratio.
    code = """
import sys
class DenyModelRuntime:
    def find_spec(self, fullname, path=None, target=None):
        for prefix in ('agents', 'app.execution.runtime', 'app.execution.judgment', 'app.agent'):
            if fullname == prefix or fullname.startswith(prefix + '.'):
                raise RuntimeError('Unexpected child dependency: ' + fullname)
sys.meta_path.insert(0, DenyModelRuntime())
from app.options.worker import main
raise SystemExit(main())
"""
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", code],
        input=request.model_dump_json(),
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
        env={k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ},
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    if operation == "snapshot":
        assert response["snapshot"]["population_id"] == venue.population_id
        assert venue.submit_count == 0
    else:
        assert response["order_id"]
        assert venue.submit_count == 1
