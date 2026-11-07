"""Cold snapshot reads need no trading schemas and retain native validation."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta

import pytest
from test_option_execution import NOW, owned
from test_mixed_venue import venue_at, q
from test_portfolio_venue import venue as portfolio_venue
from test_portfolio_accounting import two_stocks

from app.execution.failure import failure_details
from app.execution.process import FixtureProcessProtocolError, FixtureProcessTimeout
from app.options.process import run_option_process
from app.options.snapshot_worker import VERSION, MAX_RESPONSE_BYTES, read_record


def request(venue):
    return {"version": VERSION, "path": str(venue.path), "parent_pid": os.getpid(),
            "deadline_monotonic": time.monotonic() + 5, "fault": "NONE"}


def test_installed_snapshot_child_reads_without_pydantic_or_execution_imports(tmp_path):
    venue = portfolio_venue(tmp_path)
    before = venue.path.read_bytes()
    code = """
import sys
class Guard:
    def find_spec(self, fullname, path=None, target=None):
        if (fullname.startswith(('pydantic', 'app.execution', 'app.mixed', 'app.domain'))
                or (fullname.startswith('app.options.') and fullname not in
                    ('app.options.snapshot_worker', 'app.options.process_trace'))):
            raise AssertionError('Heavy snapshot dependency')
sys.meta_path.insert(0, Guard())
from app.options.snapshot_worker import main
raise SystemExit(main())
"""
    result = subprocess.run([sys.executable, "-I", "-c", code],
                            input=json.dumps(request(venue)), capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    actual = venue.snapshot_from_record(record["meta"], record["state"], NOW)
    assert actual == venue.snapshot(NOW)
    assert venue.path.read_bytes() == before


@pytest.mark.parametrize("mode", ["option", "mixed", "portfolio"])
def test_fast_snapshot_matches_direct_native_snapshot_and_does_not_write(tmp_path, mode):
    if mode == "option":
        with owned(tmp_path) as (_, venue, _):
            check_snapshot(venue)
    else:
        venue = venue_at(tmp_path) if mode == "mixed" else portfolio_venue(tmp_path)
        at = NOW
        if mode == "portfolio":
            a, b = two_stocks()
            for intent in (a, b):
                venue._accept_stock(intent, intent.prepared_at, None, None)
            at = max(a.prepared_at, b.prepared_at) + timedelta(seconds=1)
            for intent in (a, b):
                venue.fill_stock(intent, intent.quantity, q(intent, at), at,
                                 fill_id=intent.client_id)
        check_snapshot(venue, at)


def check_snapshot(venue, at=NOW):
    before = venue.path.read_bytes()
    expected = venue.snapshot(at)
    actual = asyncio.run(run_option_process(venue, now=at, timeout_seconds=5))
    assert actual.snapshot == expected
    assert actual.order_id is None
    assert venue.path.read_bytes() == before


@pytest.mark.parametrize("damage", ["policy", "cash", "provider", "schema", "identity"])
def test_parent_rejects_changed_binding_or_forged_economics(tmp_path, damage):
    venue = portfolio_venue(tmp_path)
    with sqlite3.connect(venue.path) as db:
        meta, state = map(json.loads, db.execute(
            "SELECT meta,state FROM option_fixture_control WHERE id=1").fetchone())
        if damage == "policy":
            meta["portfolio_policy"]["max_plays"] = 1
        elif damage == "cash":
            state["cash"] = "999"
        elif damage == "provider":
            meta["limits"]["provider"] = "different"
        elif damage == "schema":
            meta["schema"] = "durable-option-fixture-v1"
        else:
            meta["venue_id"] = "different"
        db.execute("UPDATE option_fixture_control SET meta=?,state=? WHERE id=1",
                   (json.dumps(meta), json.dumps(state)))
    before = venue.path.read_bytes()
    with pytest.raises(FixtureProcessProtocolError):
        asyncio.run(run_option_process(venue, now=NOW, timeout_seconds=5))
    assert venue.path.read_bytes() == before


@pytest.mark.parametrize("damage", ["order", "parent", "deadline", "fault", "symlink", "permissions"])
def test_snapshot_transport_cannot_accept_orders_or_unbound_requests(tmp_path, damage):
    venue = portfolio_venue(tmp_path)
    value = request(venue)
    before = venue.path.read_bytes()
    if damage == "order":
        value["operation"] = "accept"
    elif damage == "parent":
        value["parent_pid"] += 10000
    elif damage == "deadline":
        value["deadline_monotonic"] = time.monotonic() - 1
    elif damage == "fault":
        value["fault"] = "STALL_AFTER_ACCEPT"
    elif damage == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(venue.path)
        value["path"] = str(alias)
    else:
        venue.path.chmod(0o644)
    result = subprocess.run([sys.executable, "-I", "-m", "app.options.snapshot_worker"],
                            input=json.dumps(value), capture_output=True, text=True, timeout=5)
    assert result.returncode != 0 and not result.stdout
    assert venue.path.read_bytes() == before


def test_oversized_record_is_rejected_before_loading_it(tmp_path):
    venue = portfolio_venue(tmp_path)
    with sqlite3.connect(venue.path) as db:
        db.execute("UPDATE option_fixture_control SET state=?", ("x" * (MAX_RESPONSE_BYTES + 1),))
    with pytest.raises(ValueError, match="Bounded"):
        read_record(venue.path)


def test_native_parent_validation_cannot_extend_process_deadline(tmp_path, monkeypatch):
    venue = portfolio_venue(tmp_path)
    original = venue.snapshot_from_record

    def slow(*args):
        time.sleep(0.3)
        return original(*args)

    monkeypatch.setattr(venue, "snapshot_from_record", slow)
    with pytest.raises(FixtureProcessTimeout) as caught:
        asyncio.run(run_option_process(venue, now=NOW, timeout_seconds=0.2))
    assert failure_details(caught.value)["option_process"]["parent_phase"] == "RESPONSE_VALIDATE"
