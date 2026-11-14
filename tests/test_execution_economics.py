import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest

from app.config import Settings
from app.execution.cli import main
from app.execution.economics import CostAccounting, CostPolicy, UsageEvidence
from app.execution.engine import ExecutionBlocked, ExecutionEngine
from app.execution.fixture import LocalFixtureVenue
from tests.test_execution_rehearsal import NOW, decision, packet

D = Decimal


def context(tmp_path, *, policy=None, limits=None):
    settings = Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10)
    engine = ExecutionEngine(tmp_path / "costs.db", settings, limits=limits)
    venue = LocalFixtureVenue(D(10))
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    accounting = CostAccounting(engine, policy or CostPolicy(total_budget=1, daily_budget=1))
    return engine, venue, settings, accounting


def usage(request_id="request-1", input_tokens=1000, output_tokens=100):
    return UsageEvidence(
        request_id=request_id,
        model="gpt-6-luna",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def record(accounting, key="entry", at=NOW, proposal=None, evidence=None):
    assert accounting.begin(key, packet(at), now=at)["invoke_model"]
    return accounting.settle(key, evidence or usage(key), proposal or decision(), now=at)


def test_exact_cost_idempotency_and_cash_separation(tmp_path):
    engine, venue, settings, accounting = context(tmp_path)
    assert record(accounting) == D(".00015")
    assert accounting.settle("entry", usage("entry"), decision(), now=NOW) == D(".00015")
    assert not accounting.begin("entry", packet(), now=NOW)["invoke_model"]
    report = engine.journal.report(now=NOW)
    assert report["ledger"]["cash"] == "10" and venue.cash == D(10)
    assert report["economics"]["known_cost"] == "0.00015"
    assert D(report["economics"]["net_equity"]) == D("9.99985")
    restarted = ExecutionEngine(engine.journal.path, settings)
    again = CostAccounting(restarted, accounting.policy)
    assert not again.begin("entry", packet(), now=NOW)["invoke_model"]
    assert restarted.prepare("entry", decision(), packet(), now=NOW)


def test_unknown_receipt_survives_restart_and_prevents_automatic_replay(tmp_path):
    engine, _, settings, accounting = context(tmp_path)
    assert accounting.begin("entry", packet(), now=NOW)["invoke_model"]
    restarted = ExecutionEngine(engine.journal.path, settings)
    accounting = CostAccounting(restarted, accounting.policy)
    assert not accounting.begin("entry", packet(), now=NOW)["invoke_model"]
    with pytest.raises(ExecutionBlocked, match="COST_UNKNOWN"):
        accounting.begin("second", packet(), now=NOW)
    with pytest.raises(ExecutionBlocked, match="COST_UNKNOWN"):
        restarted.prepare("entry", decision(), packet(), now=NOW)
    report = engine.journal.report(now=NOW)["economics"]
    assert report["unknown_calls"] == 1 and report["net_equity"] is None
    assert report["known_cost"] == "0"


def test_entry_requires_exact_settled_decision_and_original_packet(tmp_path):
    engine, _, _, accounting = context(tmp_path)
    record(accounting)
    with pytest.raises(ExecutionBlocked, match="DECISION_EVIDENCE"):
        engine.prepare(
            "entry", decision().model_copy(update={"thesis": "changed"}), packet(), now=NOW
        )
    changed = packet(NOW, "9.98", "10")
    with pytest.raises(ExecutionBlocked, match="PACKET_EVIDENCE"):
        engine.prepare("entry", decision(), changed, now=NOW)
    with pytest.raises(ExecutionBlocked, match="EVIDENCE"):
        engine.prepare("absent", decision(), packet(), now=NOW)


def test_dispatch_rechecks_new_unknown_cost_but_allows_fresh_quotes(tmp_path):
    engine, venue, _, accounting = context(tmp_path)
    record(accounting)
    intent = engine.prepare("entry", decision(), packet(), now=NOW)
    # A prepared reservation blocks new model calls through this same engine.
    with pytest.raises(ExecutionBlocked, match="IN_FLIGHT"):
        accounting.begin("pending", packet(), now=NOW)
    later = NOW + timedelta(seconds=1)
    assert engine.dispatch(intent.client_id, venue, now=later, packet=packet(later)) == "OPEN"


def test_hold_calls_count_and_provider_identity_is_unique(tmp_path):
    engine, _, _, accounting = context(tmp_path)
    record(accounting, proposal=decision("HOLD"))
    engine.prepare("entry", decision("HOLD"), packet(), now=NOW)
    accounting.begin("second", packet(), now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        accounting.settle("second", usage("entry"), decision("HOLD"), now=NOW)
    report = engine.journal.report(now=NOW)["economics"]
    assert report["known_cost"] == "0.00015" and report["unknown_calls"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"input_tokens": 0},
        {"input_tokens": -1},
        {"input_tokens": True},
        {"output_tokens": -1},
        {"request_id": " "},
        {"model": " "},
    ],
)
def test_bad_usage_never_becomes_zero_cost(tmp_path, change):
    engine, _, _, accounting = context(tmp_path)
    accounting.begin("entry", packet(), now=NOW)
    with pytest.raises(ValueError):
        accounting.settle("entry", usage().model_copy(update=change), decision(), now=NOW)
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1


def test_missing_foreign_conflicting_and_regressing_usage_rejected(tmp_path):
    engine, _, _, accounting = context(tmp_path)
    with pytest.raises(ValueError, match="RECEIPT"):
        accounting.settle("absent", usage(), decision(), now=NOW)
    accounting.begin("entry", packet(), now=NOW)
    with pytest.raises(ValueError, match="IDENTITY"):
        accounting.settle(
            "entry", usage().model_copy(update={"model": "foreign"}), decision(), now=NOW
        )
    with pytest.raises(ValueError, match="RECEIPT"):
        accounting.settle("entry", usage(), decision(), now=NOW - timedelta(seconds=1))
    accounting.settle("entry", usage(), decision(), now=NOW)
    with pytest.raises(ValueError, match="CONFLICT"):
        accounting.settle("entry", usage(output_tokens=101), decision(), now=NOW)
    with pytest.raises(ValueError, match="CONTENT_CONFLICT"):
        accounting.begin("entry", packet(NOW, "9.98", "10"), now=NOW)
    assert engine.journal.report(now=NOW)["economics"]["known_cost"] == "0.00015"


def test_frozen_policy_and_reserved_cost_gate(tmp_path):
    policy = CostPolicy(total_budget=".0002", daily_budget=".0002", max_call_cost=".00015")
    engine, _, _, accounting = context(tmp_path, policy=policy)
    record(accounting, proposal=decision("HOLD"))
    with pytest.raises(ExecutionBlocked, match="COST_BUDGET"):
        accounting.begin("second", packet(), now=NOW)
    with pytest.raises(ValueError, match="immutable"):
        CostAccounting(engine, policy.model_copy(update={"total_budget": D(2)}))
    accounting.policy = policy.model_copy(update={"input_per_million": D(0)})
    with pytest.raises(ExecutionBlocked, match="CONFIGURATION_CHANGED"):
        accounting.begin("second", packet(), now=NOW)


def test_usage_exceeding_bound_is_fully_charged_and_blocks_new_authority(tmp_path):
    engine, _, _, accounting = context(tmp_path)
    record(accounting, evidence=usage(input_tokens=200000, output_tokens=0))
    costs = engine.journal.report(now=NOW)["economics"]
    assert costs["known_cost"] == "0.02" and costs["calls_exceeding_bound"] == 1
    with pytest.raises(ExecutionBlocked, match="BOUND_EXCEEDED"):
        engine.prepare("entry", decision(), packet(), now=NOW)
    with pytest.raises(ExecutionBlocked, match="BOUND_EXCEEDED"):
        accounting.begin("next", packet(), now=NOW)
    assert any(a["kind"] == "MODEL_COST_BOUND_EXCEEDED" for a in engine.journal.alerts())


@pytest.mark.parametrize("limit", ["total_loss_limit", "daily_loss_limit"])
def test_model_costs_trigger_economic_loss_gates(tmp_path, limit):
    from app.execution.models import ExecutionLimits

    limits = ExecutionLimits(
        max_entry_notional=10, max_position_notional=10, total_loss_limit=10, daily_loss_limit=10
    ).model_copy(update={limit: D(".0001")})
    engine, _, _, accounting = context(tmp_path, limits=limits)
    record(accounting)
    with pytest.raises(ExecutionBlocked, match="LOSS_LIMIT"):
        engine.prepare("entry", decision(), packet(), now=NOW)
    assert engine.journal.report()["ledger"]["cash"] == "10"


def test_daily_cost_uses_attempt_day_and_next_day_budget_resets(tmp_path):
    policy = CostPolicy(total_budget=1, daily_budget=".00015", max_call_cost=".00015")
    engine, venue, _, accounting = context(tmp_path, policy=policy)
    record(accounting, proposal=decision("HOLD"))
    with pytest.raises(ExecutionBlocked, match="COST_BUDGET"):
        accounting.begin("today", packet(), now=NOW)
    tomorrow = NOW + timedelta(days=1)
    engine.reconcile(venue.snapshot(tomorrow), now=tomorrow)
    accounting.begin("tomorrow", packet(tomorrow), now=tomorrow)
    accounting.settle(
        "tomorrow", usage("tomorrow"), decision("HOLD"), now=tomorrow + timedelta(days=1)
    )
    assert engine.journal.report(now=tomorrow)["economics"]["daily_cost"] == {
        "2026-10-06": "0.00015",
        "2026-10-07": "0.00015",
    }


def test_unknown_cost_never_blocks_protective_close_or_debits_broker_cash(tmp_path):
    engine, venue, _, accounting = context(tmp_path)
    record(accounting)
    entry = engine.prepare("entry", decision(), packet(), now=NOW)
    engine.dispatch(entry.client_id, venue, now=NOW, packet=packet())
    venue.fill(entry.client_id, entry.quantity, D(10), NOW, fill_id="buy")
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    accounting.begin("unknown-hold", packet(), now=NOW)
    p = packet(NOW, "9.4", "9.41")
    exit_intent = engine.prepare_protective_exit(p, now=NOW)
    assert exit_intent.side == "SELL"
    assert engine.dispatch(exit_intent.client_id, venue, now=NOW, packet=p) == "OPEN"
    assert engine.journal.report(now=NOW)["economics"]["net_equity"] is None


def test_marks_and_account_evidence_must_be_fresh_for_net_report(tmp_path):
    engine, venue, _, accounting = context(tmp_path)
    record(accounting)
    entry = engine.prepare("entry", decision(), packet(), now=NOW)
    engine.dispatch(entry.client_id, venue, now=NOW, packet=packet())
    venue.fill(entry.client_id, entry.quantity, D(10), NOW, fill_id="buy")
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    assert engine.journal.report(now=NOW)["economics"]["net_equity"] is None
    engine.supervise(packet(), now=NOW)
    assert engine.journal.report(now=NOW)["economics"]["net_equity"] is not None
    assert engine.journal.report(now=NOW + timedelta(seconds=91))["economics"]["net_equity"] is None
    venue.account_id = "foreign"
    engine.reconcile(venue.snapshot(NOW), now=NOW)
    assert engine.journal.report(now=NOW)["economics"]["net_equity"] is None


def test_receipt_and_settlement_failures_rollback_and_fence_detects_old_costs(tmp_path):
    engine, _, _, accounting = context(tmp_path)
    engine.journal.enable_restore_fence(now=NOW)
    accounting.begin("entry", packet(), now=NOW)
    older = engine.journal.path.read_bytes()
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER execution_fail_cost BEFORE UPDATE ON execution_model_calls BEGIN SELECT RAISE(ABORT,'cost failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        accounting.settle("entry", usage(), decision(), now=NOW)
    assert engine.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
    with engine.journal.write() as db:
        db.execute("DROP TRIGGER execution_fail_cost")
    accounting.settle("entry", usage(), decision(), now=NOW)
    engine.journal.path.write_bytes(older)
    with pytest.raises(ValueError, match="RESTORED_OR_CHANGED"):
        accounting.settle("entry", usage(), decision(), now=NOW)


def test_concurrent_calls_and_duplicate_settlement_do_not_double_charge(tmp_path):
    engine, _, _, accounting = context(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: accounting.begin("entry", packet(), now=NOW), range(2)))
    assert sorted(r["invoke_model"] for r in results) == [False, True]
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(
            pool.map(lambda _: accounting.settle("entry", usage(), decision(), now=NOW), range(2))
        )
    assert values == [D(".00015"), D(".00015")]
    assert engine.journal.report(now=NOW)["economics"]["known_cost"] == "0.00015"


def test_economics_cli_saves_protective_exit_and_net_cost_without_network(tmp_path, capsys):
    path = tmp_path / "economics-cli.db"
    assert main(["economics-run", "--db", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "OK" and not report["network_calls"] and not report["live_enabled"]
    assert len(report["fills"]) == 2 and report["ledger"]["position"] is None
    assert D(report["economics"]["known_cost"]) == D(".00030")
    assert D(report["economics"]["net_equity"]) == D(report["ledger"]["cash"]) - D(".00030")
    before = path.read_bytes()
    assert main(["economics-run", "--db", str(path)]) == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        {"input_per_million": "NaN"},
        {"output_per_million": -1},
        {"model": " "},
        {"max_call_cost": 2},
        {"daily_budget": 0},
    ],
)
def test_cost_policy_rejects_nonfinite_or_invalid_authority(tmp_path, change):
    with pytest.raises(ValueError):
        CostPolicy(**{"total_budget": 1, "daily_budget": 1, **change})


def test_begin_storage_failure_never_returns_permission_to_invoke(tmp_path):
    engine, _, _, accounting = context(tmp_path)
    with engine.journal.write() as db:
        db.execute(
            "CREATE TRIGGER execution_fail_receipt BEFORE INSERT ON execution_model_calls BEGIN SELECT RAISE(ABORT,'receipt failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        accounting.begin("entry", packet(), now=NOW)
    with engine.journal.read() as db:
        assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 0
    assert engine.journal.report(now=NOW)["economics"]["known_cost"] == "0"


def test_child_crash_preserves_potential_charge_and_blocks_retry(tmp_path):
    engine, _, settings, accounting = context(tmp_path)
    engine.journal.enable_restore_fence(now=NOW)
    script = """
import os, sys
from app.config import Settings
from app.execution.engine import ExecutionEngine
from app.execution.economics import CostAccounting, CostPolicy
from app.execution.cli import _packet
from datetime import datetime
at = datetime.fromisoformat(sys.argv[2])
engine = ExecutionEngine(sys.argv[1], Settings(_env_file=None, mode="PAPER", live_enabled=False, starting_capital=10))
costs = CostAccounting(engine, CostPolicy(total_budget=1, daily_budget=1))
costs.begin("crashed-call", _packet(at), now=at)
os._exit(98)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(engine.journal.path), NOW.isoformat()],
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 98, result.stderr.decode()
    restarted = ExecutionEngine(engine.journal.path, settings)
    costs = CostAccounting(restarted, accounting.policy)
    # Child used the built-in CLI packet; exact source replay cannot call again.
    from app.execution.cli import _packet

    assert not costs.begin("crashed-call", _packet(NOW), now=NOW)["invoke_model"]
    assert restarted.journal.report(now=NOW)["economics"]["unknown_calls"] == 1
    assert restarted.journal.report(now=NOW)["restore_fence"]["status"] == "VERIFIED"


def test_total_and_daily_model_budget_exhaustion_blocks_admission(tmp_path):
    policy = CostPolicy(total_budget=".00015", daily_budget=".00015", max_call_cost=".00015")
    engine, _, _, accounting = context(tmp_path, policy=policy)
    record(accounting)
    with pytest.raises(ExecutionBlocked, match="MODEL_TOTAL_BUDGET.*MODEL_DAILY_BUDGET"):
        engine.prepare("entry", decision(), packet(), now=NOW)
