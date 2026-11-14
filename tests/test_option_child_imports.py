"""Fixed native children must not initialize the model runtime to acknowledge work."""

import json
import os
import subprocess
import sys
import time

import pytest
from test_mixed_accounting import buy, option_trades as option_trades
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
    response = child_response(request)
    if operation == "snapshot":
        assert response["snapshot"]["population_id"] == venue.population_id
        assert venue.submit_count == 0
    else:
        assert response["order_id"]
        assert venue.submit_count == 1


def test_native_exit_child_checks_the_original_portfolio_option_fill_without_loading_owner(tmp_path, option_trades):
    from test_portfolio_accounting import labeled
    from test_portfolio_venue import venue as portfolio_venue

    venue = portfolio_venue(tmp_path)
    (opening, closing), _ = option_trades
    entry = labeled(opening).intent
    venue._accept(entry, NOW, None, None)
    venue.fill(entry, entry.quantity, opening.fill.quote, NOW, fill_id="entry")
    close = closing.intent.model_copy(update={"closing_entry_client_id": entry.client_id})
    request = OptionRequest(
        operation="accept", path=str(venue.path), venue_id=venue.venue_id,
        account_id=venue.account_id, population_id=venue.population_id, now=NOW,
        deadline_monotonic=time.monotonic() + 5, parent_pid=os.getpid(),
        stock_limits=venue.stock_limits, portfolio_policy=venue.portfolio_policy, intent=close,
    )
    response = child_response(request)
    assert response["order_id"] and venue.submit_count == 2
    venue.fill(close, close.quantity, closing.fill.quote, NOW, fill_id="exit")
    assert not venue.snapshot(NOW).positions


def child_response(request):
    # A fresh isolated interpreter exercises the real worker protocol. Import
    # denial catches the dependency regression without relying on a speed ratio.
    code = """
import sys
class DenyModelRuntime:
    def find_spec(self, fullname, path=None, target=None):
        for prefix in ('agents', 'app.execution.runtime', 'app.execution.judgment', 'app.agent',
                       'app.options.engine', 'app.robinhood.schedule', 'app.storage.repository'):
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
    return json.loads(result.stdout)
