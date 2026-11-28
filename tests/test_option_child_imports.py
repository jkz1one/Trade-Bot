"""Fixed native children must not initialize the model runtime to acknowledge work."""

import json
import os
import subprocess
import sys
import time

import pytest
from test_mixed_accounting import buy
from test_mixed_accounting import option_trades as option_trades  # noqa: PLC0414 -- shared fixture
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
                       'app.options.engine', 'app.robinhood.schedule', 'app.storage.repository',
                       'app.execution.process', 'app.execution.worker', 'app.execution.durable_fixture',
                       'app.execution.fixture', 'app.execution.models', 'app.execution.economics',
                       'app.domain', 'app.options.process'):
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


def test_native_wire_contracts_and_compatibility_exports_are_unchanged():
    import hashlib

    from app.execution.contracts import Contract
    from app.execution.cost_models import CostPolicy
    from app.execution.economics import CostPolicy as LegacyCostPolicy
    from app.execution.models import Contract as LegacyContract
    from app.options.process import OptionProcessResult as ParentResult
    from app.options.process_models import OptionProcessResult
    from app.options.process_models import OptionRequest as WireRequest

    assert Contract is LegacyContract
    assert CostPolicy is LegacyCostPolicy
    assert WireRequest is OptionRequest
    assert OptionProcessResult is ParentResult
    # Fingerprints from 91b69b6, before moving the types out of owner modules.
    # This includes bounds, unions, strict fields and all nested frozen policies.
    expected = {
        "Contract": "a61879e856f9fc86c37bca6eed9eeebdee363ae390e1c097b73aa4ab77aa7fb2",
        "CostPolicy": "302ccb861c1f6495cc7de1730ac7bf5299134513c5c3b604ef85502e49aac67a",
        "OptionProcessResult": "86b6bfdf7eea64d6511260693dc4d69091a54cb7787e1b23c9ddc89ac4a06a44",
        "OptionRequest": "8f2ec715d7da3ae94dd6ac76ee940919705964cddbca5f575bfc2c4465feb9e0",
    }
    for cls in (Contract, CostPolicy, OptionRequest, OptionProcessResult):
        actual = hashlib.sha256(json.dumps(cls.model_json_schema(), sort_keys=True).encode()).hexdigest()
        assert actual == expected[cls.__name__]
