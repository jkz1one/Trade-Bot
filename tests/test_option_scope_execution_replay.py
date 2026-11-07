"""Native Scope replay/export retains actual fills, fees, risk and unknown costs."""

import copy
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_scope_execution import execution_policy, filled, policy, sell
from test_option_scope_replay import settings, tape
from test_option_scope_watch import owned

from app.options.engine import fingerprint
from app.options.lifecycle import OptionExecutionPolicy
from app.options.scope_execution_export import export_scope_execution, verify_scope_execution_export
from app.options.scope_execution_replay import (
    ScopeExecutionReplay,
    ScopeNativeStep,
    run_scope_execution_replay,
)


def request(right="CALL", *, data_cost=".01", host_cost=".02"):
    old = settings(tape(right, expire=False))
    review = old.steps[-1]
    q = review.frame.quote
    u = review.underlying
    at = review.at + timedelta(seconds=1)
    later_q = q.model_copy(update={"source_at": at, "received_at": at})
    later_u = u.model_copy(update={"source_at": at, "received_at": at})
    return ScopeExecutionReplay(
        limits=old.limits,
        execution=OptionExecutionPolicy.model_validate(
            old.execution.model_dump() | execution_policy()
        ),
        watch=policy(),
        started_at=old.started_at,
        steps=(
            *old.steps[:-1],
            ScopeNativeStep(
                kind="ENTER",
                key="enter",
                at=review.at,
                play_key="first",
                frame=review.frame,
                context=review.context,
                underlying=u,
            ),
            ScopeNativeStep(
                kind="FILL",
                key="entry-fill",
                at=at,
                order_key="first",
                quantity=2,
                quote=later_q,
                underlying=later_u,
            ),
            ScopeNativeStep(
                kind="CLOSE",
                key="close",
                at=at,
                play_key="first",
                quote=later_q,
                underlying=later_u,
            ),
            ScopeNativeStep(
                kind="FILL",
                key="exit-fill",
                at=at,
                order_key="close",
                quantity=2,
                quote=later_q,
                underlying=later_u,
            ),
        ),
        data_cost=data_cost,
        host_cost=host_cost,
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_native_replay_and_portable_accounting_reconstruction(tmp_path, right):
    req = request(right)
    report = run_scope_execution_replay(req, tmp_path / "run")
    account = report["accounting"]
    assert account["status"] == "COMPLETE_FLAT_ACCOUNTING", report
    assert account["scope"]["watches"][0]["recorded_status"] == "CLOSED"
    assert account["loss_control"]["state"]["families"][0]["consecutive_losses"] == 1
    assert len(account["orders"]) == 2
    assert all(o["entry_lineage"]["family"] == "SCOPE" for o in account["orders"])
    assert Decimal(account["net_after_all_costs"]) == Decimal(
        account["ledger"]["cash"]
    ) - req.execution.capital - Decimal(".03")
    value = json.loads((tmp_path / "run" / "native.json").read_text())
    verified = verify_scope_execution_export(value, report["export_hash"])
    assert verified["status"] == "VERIFIED_NATIVE_ACCOUNTING"
    assert verified["net_after_all_costs"] == account["net_after_all_costs"]
    with pytest.raises(FileExistsError):
        run_scope_execution_replay(req, tmp_path / "run")


@pytest.mark.parametrize("missing", ["data", "host", "open"])
def test_missing_operating_costs_and_open_positions_never_become_zero(tmp_path, missing):
    req = request(
        data_cost=None if missing == "data" else ".01",
        host_cost=None if missing == "host" else ".02",
    )
    if missing == "open":
        req = req.model_copy(update={"steps": req.steps[:-2]})
    report = run_scope_execution_replay(req, tmp_path / "run")
    assert report["accounting"]["status"] == "INCOMPLETE"
    assert report["accounting"]["net_after_all_costs"] is None
    if missing == "open":
        assert report["accounting"]["loss_control"]["state"]["consumed_entries"] == 0
    value = json.loads((tmp_path / "run" / "native.json").read_text())
    assert verify_scope_execution_export(value, value["export_hash"])["net_after_all_costs"] is None


@pytest.mark.parametrize("damage", ["summary", "fill", "owner", "receipt", "loss"])
def test_rehashed_tampered_evidence_cannot_change_native_accounting(tmp_path, damage):
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        _, buy, f, u, now = filled(e, v)
        sell(e, v, buy, f.quote, u, now)
        original = export_scope_execution(e.journal, now=now, data_cost=".01", host_cost=".02")
    value = copy.deepcopy(original)
    if damage == "summary":
        value["report"]["net_after_all_costs"] = "100"
    else:
        table, column, field, changed = {
            "fill": ("execution_fills", 2, "fee", "0"),
            "owner": ("execution_control", 1, "capital", "2000"),
            "receipt": ("execution_option_scope_entries", 2, "client_id", "foreign"),
            "loss": ("execution_option_loss_control", 2, "consecutive_losses", 0),
        }[damage]
        row = value["evidence"][table][0]
        raw = json.loads(row[column])
        raw[field] = changed
        row[column] = json.dumps(raw)
    with pytest.raises(ValueError, match="retained hash"):
        verify_scope_execution_export(value, original["export_hash"])
    value["export_hash"] = fingerprint({k: v for k, v in value.items() if k != "export_hash"})
    with pytest.raises((ValueError, TypeError)):
        verify_scope_execution_export(value, value["export_hash"])


def test_open_export_checks_original_protection_even_when_ledger_and_snapshot_agree(tmp_path):
    with owned(tmp_path, enroll=False, execution_policy_changes=execution_policy()) as (e, v, _):
        _, _, _, _, now = filled(e, v)
        value = export_scope_execution(e.journal, now=now, data_cost=".01", host_cost=".02")
    row = value["evidence"]["execution_control"][0]
    for col in (2, 5):
        stored = json.loads(row[col])
        stored["position"]["exit_at"] = "2026-10-09T19:46:00Z"
        stored["position"]["entry_time_protection"]["exit_by"] = "2026-10-09T19:46:00Z"
        row[col] = json.dumps(stored)
    value["report"]["ledger"]["position"] = json.loads(row[2])["position"]
    value["export_hash"] = fingerprint({k: v for k, v in value.items() if k != "export_hash"})
    with pytest.raises(ValueError, match="original entry"):
        verify_scope_execution_export(value, value["export_hash"])


def test_replay_protective_order_is_fillable_by_its_step_key(tmp_path):
    req = request()
    enter = req.steps[-4]
    deadline = enter.frame.session.protect_at
    q = enter.frame.quote.model_copy(update={"source_at": deadline, "received_at": deadline})
    u = enter.underlying.model_copy(update={"source_at": deadline, "received_at": deadline})
    req = req.model_copy(
        update={
            "steps": (
                *req.steps[:-2],
                ScopeNativeStep(
                    kind="PROTECT", key="deadline-exit", at=deadline, quote=q, underlying=u
                ),
                ScopeNativeStep(
                    kind="FILL",
                    key="deadline-fill",
                    at=deadline,
                    order_key="deadline-exit",
                    quantity=2,
                    quote=q,
                    underlying=u,
                ),
            )
        }
    )
    report = run_scope_execution_replay(req, tmp_path / "protective")
    assert report["actions"][-2]["result"]["status"] == "OPEN"
    assert report["actions"][-1]["result"]["reconciled"]
    assert report["accounting"]["scope"]["watches"][0]["recorded_status"] == "CLOSED"
    assert report["accounting"]["status"] == "COMPLETE_FLAT_ACCOUNTING"
    exported = json.loads((tmp_path / "protective" / "native.json").read_text())
    intents = [json.loads(r[3]) for r in exported["evidence"]["execution_orders"]]
    sells = [i for i in intents if i["side"] == "SELL"]
    assert len(sells) == 1 and "TIME_EXIT" in sells[0]["thesis"]
