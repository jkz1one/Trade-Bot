"""Independent accounting replay, paired denominators and no invented economics."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_admission import END, NOW, inputs
from test_option_execution import intent_for, ledger, owned, quote_at, underlying_at

from app.execution.economics import CostPolicy, UsageEvidence
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.evaluation_models import (
    ArmDefinition,
    ArmSession,
    BenchmarkSession,
    EvaluationBundle,
    EvaluationManifest,
    EvaluationSession,
    ReplayCall,
    ReplayCycle,
    ReplayOrder,
)
from app.options.lifecycle import OptionLedger
from app.options.models import OptionProposal

D = Decimal
OPEN = NOW.replace(hour=13, minute=30)
KEY = "degen:" + str(int(NOW.timestamp()) // 300)


def bundle_for():
    from test_option_execution import configuration

    _, limits, policy = configuration()
    definitions = tuple(
        ArmDefinition(
            arm=arm,
            limits=limits.model_copy(update={"population_id": "evaluation-" + arm}),
            policy=policy
            if arm == "A"
            else policy.model_copy(
                update={"cost_policy": CostPolicy(total_budget="1", daily_budget=".1")}
            ),
            strategy_hash=fingerprint(arm),
        )
        for arm in ("A", "B", "C")
    )
    session = EvaluationSession(key="2026-10-09", opens_at=OPEN, closes_at=END, tape_hash="a" * 64)
    manifest = EvaluationManifest(
        experiment_id="fixture-compare",
        declared_at=OPEN - timedelta(days=1),
        arms=definitions,
        sessions=(session,),
        allocation_policy="equal-fixed-session-cost-v1",
        hurdle_per_session=".01",
        minimum_sessions=2,
    )
    initial = OptionLedger(cash="1000", high_watermark="1000")
    cycles = tuple(
        ReplayCycle(
            key="degen:" + str(t // 300),
            frame_hash=fingerprint(t),
            status="HOLD",
            model_called=False,
        )
        for t in range(int(OPEN.timestamp()), int(END.timestamp()), 300)
    )
    arms = []
    for definition in definitions:
        calls = ()
        current = cycles
        if definition.arm != "A":
            current = tuple(c.model_copy(update={"model_called": c.key == KEY}) for c in cycles)
            calls = (
                ReplayCall(
                    source_key=KEY,
                    started_at=NOW,
                    completed_at=NOW + timedelta(seconds=1),
                    usage=UsageEvidence(
                        request_id="response-" + definition.arm,
                        model=definition.policy.cost_policy.model,
                        input_tokens=1000,
                        output_tokens=100,
                    ),
                ),
            )
        arms.append(
            ArmSession(
                arm=definition.arm,
                session_key=session.key,
                definition_hash=fingerprint(definition),
                tape_hash=session.tape_hash,
                initial=initial,
                closing=initial,
                closing_complete=True,
                cycles=current,
                calls=calls,
                data_cost=".01",
                host_cost=".02",
            )
        )
    u = inputs()["underlying"]
    benchmark = BenchmarkSession(
        session_key=session.key,
        start=u.model_copy(
            update={"source_at": OPEN, "received_at": OPEN, "bid": D(600), "ask": D(600)}
        ),
        end=u.model_copy(
            update={"source_at": END, "received_at": END, "bid": D(606), "ask": D(606)}
        ),
    )
    return EvaluationBundle(manifest=manifest, evidence=tuple(arms), benchmarks=(benchmark,))


def change_arm(bundle, index=1, **changes):
    evidence = list(bundle.evidence)
    evidence[index] = evidence[index].model_copy(update=changes)
    return bundle.model_copy(update={"evidence": tuple(evidence)})


def round_trip(tmp_path):
    with owned(tmp_path) as (engine, venue, data):
        initial = ledger(engine)
        result = engine.prepare(KEY, data["proposal"], data["quote"], data["underlying"], now=NOW)
        buy = intent_for(engine, result["client_id"])
        assert (
            asyncio.run(engine.dispatch(buy.client_id, data["quote"], data["underlying"], now=NOW))
            == "OPEN"
        )
        filled = NOW + timedelta(seconds=1)
        venue.fill(buy, buy.quantity, quote_at(data, filled), filled, fill_id="buy")
        assert engine.reconcile(venue.snapshot(filled), now=filled)["reconciled"]
        at = NOW + timedelta(seconds=2)
        engine.assess(quote_at(data, at), underlying_at(data, at), now=at)
        result = engine.prepare(
            "close",
            OptionProposal(
                action="CLOSE", contract=buy.instrument.contract, thesis="Fixture close"
            ),
            quote_at(data, at),
            now=at,
        )
        sell = intent_for(engine, result["client_id"])
        assert asyncio.run(engine.dispatch(sell.client_id, quote_at(data, at), now=at)) == "OPEN"
        filled = at + timedelta(seconds=1)
        venue.fill(sell, sell.quantity, quote_at(data, filled), filled, fill_id="sell")
        assert engine.reconcile(venue.snapshot(filled), now=filled)["reconciled"]
        snapshot = venue.snapshot(filled)
        orders = (
            ReplayOrder(
                intent=buy,
                decision_completed_at=NOW,
                attempted_at=NOW,
                observation=snapshot.orders[0],
            ),
            ReplayOrder(
                intent=sell,
                decision_completed_at=at,
                attempted_at=at,
                observation=snapshot.orders[1],
            ),
        )
        return initial, ledger(engine), orders


def test_matched_hold_ledgers_include_every_cost_and_do_not_claim_profit():
    report = evaluate(bundle_for())
    assert report["status"] == "COMPLETE_ARITHMETIC"
    assert report["economic_conclusion"] == "INCONCLUSIVE"
    assert not report["minimum_sessions_met"]
    assert report["planned_sessions"] == report["complete_paired_sessions"] == 1
    assert D(report["totals"]["A"]["net_change"]) == D("-.03")
    assert D(report["totals"]["C"]["net_change"]) == D("-.03015")
    assert D(report["mean_paired_net_difference"]["C"]) == D("-.00015")
    assert D(report["sessions"][0]["spy_price_return"]) == D(".01")
    assert (
        report["execution_authority"] is report["network_calls"] is report["live_enabled"] is False
    )


def test_actual_native_fixture_fills_reconstruct_cash_fees_and_turnover(tmp_path):
    start, end, orders = round_trip(tmp_path)
    report = evaluate(change_arm(bundle_for(), 0, initial=start, closing=end, orders=orders))
    assert report["status"] == "COMPLETE_ARITHMETIC", report
    row = report["sessions"][0]["arms"]["A"]
    assert end.cash == D("976.8") and end.realized_pnl == D(-16) and end.fees_paid == D("7.2")
    assert D(row["net_change"]) == D("-23.23")
    assert D(row["turnover"]) == D(792)
    assert D(report["totals"]["A"]["session_boundary_drawdown"]) == D("23.23")


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "host",
        "data",
        "usage",
        "model",
        "cost_completion",
        "slot",
        "frame",
        "tape",
        "definition",
        "unknown_cycle",
        "closing",
        "capital",
        "cash",
        "duplicate_call",
        "missing_call",
    ],
)
def test_incomplete_evidence_stays_in_denominator_without_complete_case_totals(damage):
    b = bundle_for()
    a = b.evidence[1]
    if damage == "missing":
        b = b.model_copy(update={"evidence": (b.evidence[0], b.evidence[2])})
    elif damage in {"host", "data"}:
        b = change_arm(b, **{damage + "_cost": None})
    elif damage in {"usage", "model", "cost_completion"}:
        call = a.calls[0]
        updates = (
            {"usage": None}
            if damage == "usage"
            else {"completed_at": END + timedelta(seconds=1)}
            if damage == "cost_completion"
            else {"usage": call.usage.model_copy(update={"model": "foreign"})}
        )
        b = change_arm(b, calls=(call.model_copy(update=updates),))
    elif damage in {"slot", "frame", "unknown_cycle"}:
        cycles = (
            a.cycles[1:]
            if damage == "slot"
            else (
                a.cycles[0].model_copy(
                    update={"frame_hash": "f" * 64} if damage == "frame" else {"status": "UNKNOWN"}
                ),
                *a.cycles[1:],
            )
        )
        b = change_arm(b, cycles=cycles)
    elif damage in {"tape", "definition"}:
        b = change_arm(b, **{damage + "_hash": "f" * 64})
    elif damage == "closing":
        b = change_arm(b, closing_complete=False)
    elif damage == "capital":
        b = change_arm(b, initial=a.initial.model_copy(update={"cash": D(1001)}))
    elif damage == "cash":
        b = change_arm(b, closing=a.closing.model_copy(update={"cash": D(1001)}))
    else:
        b = change_arm(b, calls=a.calls * 2 if damage == "duplicate_call" else ())
    report = evaluate(b)
    assert report["status"] == "INCONCLUSIVE"
    assert report["planned_sessions"] == 1 and report["complete_paired_sessions"] == 0
    assert all(t["net_change"] is None for t in report["totals"].values())
    assert report["mean_paired_net_difference"] == {"B": None, "C": None}


@pytest.mark.parametrize(
    "damage",
    [
        "old_quote",
        "fee",
        "price",
        "sequence",
        "duplicate_fill",
        "debit",
        "unknown_order",
        "open_position",
    ],
)
def test_replay_never_invents_fills_or_ignores_conservation(tmp_path, damage):
    start, end, orders = round_trip(tmp_path)
    buy, sell = orders
    fill = buy.observation.fills[0]
    if damage == "unknown_order":
        orders = (buy.model_copy(update={"observation": None}),)
        end = start
    elif damage == "open_position":
        from app.options.accounting import apply_fill

        orders = (buy,)
        end = apply_fill(start, buy.intent, fill)
    elif damage == "debit":
        orders = (
            buy.model_copy(
                update={"intent": buy.intent.model_copy(update={"approved_entry_debit": D(1)})}
            ),
            sell,
        )
    else:
        if damage == "old_quote":
            quote = fill.quote.model_copy(update={"source_at": NOW})
            changes = {
                "quote": quote,
                "quote_hash": hashlib.sha256(quote.model_dump_json().encode()).hexdigest(),
            }
        elif damage == "duplicate_fill":
            sell_fill = sell.observation.fills[0].model_copy(update={"fill_id": fill.fill_id})
            orders = (
                buy,
                sell.model_copy(
                    update={
                        "observation": sell.observation.model_copy(update={"fills": (sell_fill,)})
                    }
                ),
            )
            changes = None
        else:
            changes = {damage: D(999) if damage != "sequence" else 10}
        if changes:
            orders = (
                buy.model_copy(
                    update={
                        "observation": buy.observation.model_copy(
                            update={"fills": (fill.model_copy(update=changes),)}
                        )
                    }
                ),
                sell,
            )
    report = evaluate(change_arm(bundle_for(), 0, initial=start, closing=end, orders=orders))
    assert report["status"] == "INCONCLUSIVE", report


def test_model_funded_entry_requires_retained_completion(tmp_path):
    start, end, orders = round_trip(tmp_path)
    b = change_arm(bundle_for(), 1, initial=start, closing=end, orders=orders)
    result = evaluate(b)
    assert "ENTRY_MODEL_COMPLETION_MISSING_OR_LATE" in result["sessions"][0]["arms"]["B"]["reasons"]


@pytest.mark.parametrize(
    "damage",
    [
        "late_enrollment",
        "mismatched_fees",
        "same_population",
        "wrong_calendar",
        "duplicate_session",
        "float_cost",
        "extra_authority",
    ],
)
def test_manifest_and_money_contracts_reject_unmatched_or_unbounded_inputs(damage):
    b = bundle_for().model_dump()
    m = b["manifest"]
    if damage == "late_enrollment":
        m["declared_at"] = NOW
    elif damage == "mismatched_fees":
        m["arms"][1]["limits"]["entry_fee_per_order"] = "99"
    elif damage == "same_population":
        m["arms"][1]["limits"]["population_id"] = m["arms"][0]["limits"]["population_id"]
    elif damage == "wrong_calendar":
        m["sessions"][0]["closes_at"] = NOW
    elif damage == "duplicate_session":
        m["sessions"] = m["sessions"] * 2
    elif damage == "float_cost":
        b["evidence"][0]["data_cost"] = 0.1
    else:
        m["live_enabled"] = True
    with pytest.raises(ValidationError):
        EvaluationBundle.model_validate(b)


def test_decimal_context_independence_and_digest_binding():
    b = bundle_for()
    expected = evaluate(b)
    with localcontext() as ctx:
        ctx.prec = 5
        assert evaluate(b) == expected
    changed = change_arm(b, host_cost=".03")
    assert evaluate(changed)["evidence_hash"] != expected["evidence_hash"]
    assert evaluate(changed)["manifest_hash"] == expected["manifest_hash"]


def test_installed_cli_is_read_only_and_rejects_symlink(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(bundle_for().model_dump_json())
    before = path.read_bytes()
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    result = subprocess.run(
        [sys.executable, "-I", "-m", "app.options.evaluation_cli", "--bundle", str(path)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "COMPLETE_ARITHMETIC"
    assert path.read_bytes() == before and {p.name for p in tmp_path.iterdir()} == {"bundle.json"}
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    result = subprocess.run(
        [sys.executable, "-I", "-m", "app.options.evaluation_cli", "--bundle", str(link)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 2 and json.loads(result.stdout)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("damage", ["missing", "symbol", "stale", "delayed", "crossed", "future"])
def test_benchmark_must_be_matching_usable_spy_boundary_evidence(damage):
    b = bundle_for()
    mark = b.benchmarks[0]
    if damage == "missing":
        b = b.model_copy(update={"benchmarks": ()})
    else:
        changes = (
            {"symbol": "QQQ"}
            if damage == "symbol"
            else {"source_at": END - timedelta(seconds=6)}
            if damage == "stale"
            else {"entitlement": "DELAYED"}
            if damage == "delayed"
            else {"bid": D(610)}
            if damage == "crossed"
            else {
                "source_at": END + timedelta(seconds=1),
                "received_at": END + timedelta(seconds=1),
            }
        )
        b = b.model_copy(
            update={
                "benchmarks": (
                    mark.model_copy(update={"end": mark.end.model_copy(update=changes)}),
                )
            }
        )
    result = evaluate(b)
    assert result["status"] == "INCONCLUSIVE"
    assert result["sessions"][0]["spy_price_return"] is None
    assert result["totals"]["C"]["net_change"] is None


def two_sessions():
    b = bundle_for()
    shift = timedelta(days=3)
    first = b.manifest.sessions[0]
    later = first.model_copy(
        update={
            "key": "2026-10-12",
            "opens_at": first.opens_at + shift,
            "closes_at": first.closes_at + shift,
        }
    )
    manifest = b.manifest.model_copy(update={"sessions": (first, later)})
    extra = []
    for a in b.evidence:

        def key(k):
            return "degen:" + str(int(k.split(":")[1]) + int(shift.total_seconds()) // 300)

        cycles = tuple(c.model_copy(update={"key": key(c.key)}) for c in a.cycles)
        calls = tuple(
            c.model_copy(
                update={
                    "source_key": key(c.source_key),
                    "started_at": c.started_at + shift,
                    "completed_at": c.completed_at + shift,
                    "usage": c.usage.model_copy(
                        update={"request_id": c.usage.request_id + "-later"}
                    ),
                }
            )
            for c in a.calls
        )
        extra.append(
            a.model_copy(update={"session_key": later.key, "cycles": cycles, "calls": calls})
        )
    mark = b.benchmarks[0]
    marks = {
        name: getattr(mark, name).model_copy(
            update={
                "source_at": getattr(mark, name).source_at + shift,
                "received_at": getattr(mark, name).received_at + shift,
            }
        )
        for name in ("start", "end")
    }
    return b.model_copy(
        update={
            "manifest": manifest,
            "evidence": (*b.evidence, *extra),
            "benchmarks": (mark, mark.model_copy(update={"session_key": later.key, **marks})),
        }
    )


def test_multisession_pairing_keeps_complete_denominator_and_no_claim_after_sample_minimum():
    b = two_sessions()
    result = evaluate(b)
    assert result["status"] == "COMPLETE_ARITHMETIC" and result["minimum_sessions_met"]
    assert result["economic_conclusion"] == "INCONCLUSIVE"
    assert D(result["totals"]["C"]["net_change"]) == D("-.0603")
    assert D(result["spy_session_compounded_price_return"]) == D(".0201")
    assert D(result["totals"]["C"]["net_excess_vs_spy_price"]) == D("-.0201603")
    missing = b.model_copy(update={"evidence": b.evidence[:4] + b.evidence[5:]})
    incomplete = evaluate(missing)
    assert incomplete["planned_sessions"] == 2 and incomplete["complete_paired_sessions"] == 1
    assert not incomplete["minimum_sessions_met"]
    assert incomplete["totals"]["A"]["net_change"] is None


def test_missing_first_session_cannot_reset_capital_and_resume_statistics():
    b = two_sessions()
    result = evaluate(b.model_copy(update={"evidence": b.evidence[1:]}))
    assert result["complete_paired_sessions"] == 0
    assert "CAPITAL_OR_SESSION_CONTINUITY_MISMATCH" in result["sessions"][1]["arms"]["A"]["reasons"]


def test_retained_model_receipt_attaches_all_costs_to_actual_entry_replay(tmp_path):
    start, end, orders = round_trip(tmp_path)
    b = change_arm(bundle_for(), 1, initial=start, closing=end, orders=orders)
    call = b.evidence[1].calls[0].model_copy(update={"completed_at": NOW})
    result = evaluate(change_arm(b, calls=(call,)))
    assert result["status"] == "COMPLETE_ARITHMETIC"
    row = result["sessions"][0]["arms"]["B"]
    assert row["accounting_verified"]
    assert D(row["net_change"]) == D("-23.23015")
    assert D(row["venue_fees"]) == D("7.2")


def test_between_session_settlement_preserves_cash_and_sequence(tmp_path):
    from app.options.accounting import apply_receipt
    from app.options.lifecycle import OptionReceipt

    start, end, orders = round_trip(tmp_path)
    b = two_sessions()
    b = change_arm(b, 0, initial=start, closing=end, orders=orders)
    receipt = OptionReceipt(
        receipt_id="next-session-settlement",
        sequence=3,
        kind="FUNDS_SETTLED",
        occurred_at=b.manifest.sessions[1].opens_at - timedelta(hours=1),
        cash_change=end.cash - end.settled_cash,
    )
    b = change_arm(b, 3, initial=end, closing=apply_receipt(end, receipt), receipts=(receipt,))
    result = evaluate(b)
    assert result["status"] == "COMPLETE_ARITHMETIC", result
    assert D(result["totals"]["A"]["net_change"]) == D("-23.26")
    assert D(result["sessions"][1]["arms"]["A"]["venue_cash_change"]) == 0


@pytest.mark.parametrize("damage", ["order_id", "source_key"])
def test_distinct_clients_cannot_reuse_order_receipt_or_source_identity(tmp_path, damage):
    start, end, orders = round_trip(tmp_path)
    buy, sell = orders
    if damage == "order_id":
        order_id = buy.observation.order_id
        obs = sell.observation.model_copy(
            update={
                "order_id": order_id,
                "fills": tuple(
                    f.model_copy(update={"order_id": order_id}) for f in sell.observation.fills
                ),
            }
        )
        sell = sell.model_copy(update={"observation": obs})
    else:
        sell = sell.model_copy(
            update={"intent": sell.intent.model_copy(update={"source_key": buy.intent.source_key})}
        )
    result = evaluate(change_arm(bundle_for(), 0, initial=start, closing=end, orders=(buy, sell)))
    assert result["status"] == "INCONCLUSIVE"
    assert result["sessions"][0]["arms"]["A"]["reasons"] == [
        "DUPLICATE_ORDER_RECEIPT" if damage == "order_id" else "DUPLICATE_ORDER_SOURCE"
    ]
