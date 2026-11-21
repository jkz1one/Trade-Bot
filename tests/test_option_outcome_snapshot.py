"""Exact lineage reuse stays inside one unchanged transaction and outcome call."""

import copy
import json

import pytest
from test_option_native_entry_attribution import close_first
from test_option_scope_ai import ai_owner

from app.execution.engine import ExecutionBlocked
from app.options import scope_arbitration
from app.options.entry_lineage import outcome_snapshot, verified_lineage
from app.options.position_outcome import native_position_outcome


@pytest.fixture(scope="module")
def closed(tmp_path_factory):
    root = tmp_path_factory.mktemp("outcome-snapshot")
    with (
        pytest.MonkeyPatch.context() as patch,
        ai_owner(root, patch, later_entry=True) as (c, venue, times, frame, _),
    ):
        buy, _ = close_first(c, venue, times, frame)
        with c.engine.journal.read() as db:
            approval = json.loads(
                db.execute(
                    "SELECT approval_json FROM execution_orders WHERE client_id=?", (buy.client_id,)
                ).fetchone()[0]
            )
        yield c.engine, buy, approval, times[0]


def trace(monkeypatch):
    calls = []
    original = scope_arbitration.verify_entry

    def check(db, intent, approval):
        calls.append(intent.client_id)
        return original(db, intent, approval)

    monkeypatch.setattr(scope_arbitration, "verify_entry", check)
    return calls


def test_each_unique_lineage_is_validated_again_on_next_outcome(closed, monkeypatch):
    engine, buy, _, _ = closed
    calls = trace(monkeypatch)
    with engine.journal.read() as db:
        first = native_position_outcome(db, buy.client_id, engine.limits.population_id)
        checked = tuple(calls)
        assert len(checked) == len(set(checked)) == 2
        second = native_position_outcome(db, buy.client_id, engine.limits.population_id)
        assert second == first
    assert tuple(calls) == checked + checked


def test_any_write_disables_lineage_reuse(closed, monkeypatch):
    engine, buy, approval, at = closed
    calls = trace(monkeypatch)

    @outcome_snapshot
    def exercise(db):
        verified_lineage(db, buy, approval)
        engine.journal.event(db, at, "FIXTURE_LINEAGE_RECHECK", {})
        verified_lineage(db, buy, approval)

    with engine.journal.write() as db:
        exercise(db)
    assert calls == [buy.client_id, buy.client_id]


def test_changed_arguments_cannot_reuse_same_order_identity(closed, monkeypatch):
    engine, buy, approval, _ = closed
    calls = trace(monkeypatch)
    changed = copy.deepcopy(approval)
    changed["entry_lineage"]["candidate_hash"] = "0" * 64

    @outcome_snapshot
    def exercise(db):
        verified_lineage(db, buy, approval)
        with pytest.raises((ValueError, ExecutionBlocked)):
            verified_lineage(db, buy, changed)

    with engine.journal.read() as db:
        exercise(db)
        verified_lineage(db, buy, approval)
    assert calls == [buy.client_id] * 3
