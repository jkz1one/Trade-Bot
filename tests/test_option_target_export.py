"""Open target-managed positions retain economic evidence without claiming a net return."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import policies
from test_option_admission import END, NOW
from test_option_evaluation import bundle_for
from test_option_execution import intent_for, ledger, owned, quote_at, underlying_at
from test_option_market_tape import header_for
from test_option_target_exits import at_target
from test_option_target_stops import ENROLLED, plan

from app.options.coordinator import DegenCoordinator, DegenFrame
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.evaluation_export import export_arm, strategy_hash
from app.options.market_tape import TapeRecorder, load_tape

D = Decimal
POLICY = {**ENROLLED, "premium_trail": "executable-premium-v1"}


def native_boundary(root, right="CALL", sold=2, *, observed_entry=False, entry_time=None):
    base = bundle_for()
    frames = []
    with owned(root, right, **POLICY) as (engine, venue, data):
        setup, selection = policies()
        coordinator = DegenCoordinator(engine, setup, selection, create=True, clock=lambda: NOW)
        definition = base.manifest.arms[0].model_copy(
            update={
                "limits": engine.limits,
                "policy": engine.policy,
                "strategy_hash": strategy_hash(json.loads(coordinator._configuration())),
            }
        )
        out = engine.prepare(
            "target-entry",
            data["proposal"],
            data["quote"],
            data["underlying"],
            now=NOW,
            target_exit_schedule=plan(right),
            entry_time_protection=entry_time,
        )
        assert out["status"] == "PREPARED", out
        buy = intent_for(engine, out["client_id"])
        assert (
            asyncio.run(engine.dispatch(buy.client_id, data["quote"], data["underlying"], now=NOW))
            == "OPEN"
        )
        at = NOW + timedelta(seconds=1)
        q = quote_at(data, at)
        u_entry = underlying_at(data, at) if observed_entry else None
        venue.fill(buy, buy.quantity, q, at, fill_id="entry", underlying=u_entry)
        assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
        frames.append((at, DegenFrame(quotes=(q,), underlyings=(u_entry,) if u_entry else ())))
        at += timedelta(seconds=1)
        q = quote_at(data, at, bid=D("1.4"), ask=D("1.41"))
        u = at_target(data, at=at)
        if sold:
            out = asyncio.run(engine.protective_tick(q, u, now=at))
            assert out["status"] == "OPEN", out
            sell = intent_for(engine, out["client_id"])
            assert sell.quantity == 2 and sell.target_exit_stage == 1
            at += timedelta(seconds=1)
            q = quote_at(data, at, bid=D("1.4"), ask=D("1.41"))
            venue.fill(sell, sold, q, at, fill_id="scale")
            assert engine.reconcile(venue.snapshot(at), now=at)["reconciled"]
        else:
            assert engine.assess(q, u, now=at)["target_exit_stage"] == 1
        frames.append((at, DegenFrame(quotes=(q,), underlyings=(u,))))
        assert engine.reconcile(venue.snapshot(END), now=END)["reconciled"]
        closing = ledger(engine)
        assert closing.position.target_exit_stage == 1
        assert venue.snapshot(END).position.target_exit_stage == 0
        assert closing.position.quantity == 4 - sold
        journal = engine.journal.path
    with TapeRecorder(root / "market.tape", header_for(base)) as recorder:
        for at, frame in frames:
            recorder.append(frame, recorded_at=at, kind="MARKET")
        digest = recorder.seal()
    session = base.manifest.sessions[0].model_copy(update={"tape_hash": digest})
    definitions = (
        definition,
        *(
            a.model_copy(update={"policy": a.policy.model_copy(update=POLICY)})
            for a in base.manifest.arms[1:]
        ),
    )
    manifest = base.manifest.model_copy(update={"arms": definitions, "sessions": (session,)})
    return journal, definition, session, load_tape(root / "market.tape"), manifest, closing


def exported(boundary, **costs):
    journal, definition, session, tape, manifest, closing = boundary
    before = journal.read_bytes()
    row, proof = export_arm(journal, definition, session, tape, **costs)
    assert journal.read_bytes() == before
    assert row.closing == closing and proof["export_hash"] == fingerprint(row)
    bundle = bundle_for().model_copy(update={"manifest": manifest, "evidence": (row,)})
    return row, bundle


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("sold", [0, 1, 2])
def test_native_target_progress_exports_open_costs_and_portable_accounting(tmp_path, right, sold):
    boundary = native_boundary(tmp_path, right, sold)
    row, bundle = exported(boundary, data_cost=".01", host_cost=".02")
    assert row.closing.position.target_exit_stage == 1
    assert row.closing.position.target_exit_schedule == plan(right)
    assert row.closing.position.premium_trail.entry_basis == D(404)
    assert row.closing.position.premium_trail.peak_bid == D("1.4")
    assert row.closing.position.tightened_underlying_invalidation == D(600)
    report = evaluate(bundle)["sessions"][0]["arms"]["A"]
    assert report["accounting_verified"], report
    assert report["status"] == "INCONCLUSIVE" and report["net_change"] is None
    assert "OPEN_BOUNDARY_POSITION_UNVALUED" in report["reasons"]
    assert D(report["venue_fees"]) == D("3.60") + (D(1) + sold * D(".65") if sold else 0)
    assert D(report["venue_cash_change"]) == row.closing.cash - D(1000)
    assert report["allocated_data_cost"] == "0.01"
    assert report["allocated_host_cost"] == "0.02"
    assert report["known_model_cost"] == "0"
    if sold == 1:
        assert "UNRESOLVED_ORDER_OR_CLOSING_EVIDENCE" in report["reasons"]


def test_open_target_boundary_keeps_unknown_allocations_unknown(tmp_path):
    _, bundle = exported(native_boundary(tmp_path))
    report = evaluate(bundle)["sessions"][0]["arms"]["A"]
    assert report["accounting_verified"], report
    assert "ALLOCATED_COST_UNKNOWN" in report["reasons"]
    assert report["allocated_data_cost"] is report["allocated_host_cost"] is None
    assert report["net_change"] is None


@pytest.mark.parametrize("field", ["schedule", "original_stop", "entry_basis"])
def test_portable_target_progress_does_not_hide_changed_original_terms(tmp_path, field):
    row, bundle = exported(native_boundary(tmp_path), data_cost=".01", host_cost=".02")
    p = row.closing.position
    if field == "schedule":
        steps = (
            p.target_exit_schedule.steps[0].model_copy(update={"quantity": 1}),
            p.target_exit_schedule.steps[1],
        )
        changes = {
            "target_exit_schedule": p.target_exit_schedule.model_copy(update={"steps": steps})
        }
    elif field == "original_stop":
        changes = {"original_underlying_invalidation": D(597)}
    else:
        changes = {"premium_trail": p.premium_trail.model_copy(update={"entry_basis": D(400)})}
    damaged = row.model_copy(
        update={
            "closing": row.closing.model_copy(update={"position": p.model_copy(update=changes)})
        }
    )
    report = evaluate(bundle.model_copy(update={"evidence": (damaged,)}))["sessions"][0]["arms"][
        "A"
    ]
    assert "CASH_OR_OWNERSHIP_REPLAY_MISMATCH" in report["reasons"]
    assert not report["accounting_verified"] and report["net_change"] is None


def test_native_export_still_rejects_changed_frozen_schedule(tmp_path):
    boundary = native_boundary(tmp_path)
    journal, definition, session, tape, _, _ = boundary
    with sqlite3.connect(journal) as db:
        snapshot = json.loads(
            db.execute("SELECT snapshot_json FROM execution_control").fetchone()[0]
        )
        snapshot["position"]["target_exit_schedule"]["steps"][0]["quantity"] = 1
        db.execute("UPDATE execution_control SET snapshot_json=?", (json.dumps(snapshot),))
    with pytest.raises(ValueError, match="Native closing ownership mismatch"):
        export_arm(journal, definition, session, tape)
