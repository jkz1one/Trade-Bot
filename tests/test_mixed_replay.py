"""Independent native accounts, full model contracts and portable recorded fills."""

import asyncio
import copy
import json
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT
from test_mixed_market_tape import header
from test_mixed_native_owner import changed, settings
from test_mixed_selection import quote, stock_frame
from test_option_entry_reasoning import packet_for

from app.execution.economics import CostPolicy
from app.execution.judgment import JudgmentLimits
from app.mixed.comparison import verify_mixed_comparison
from app.mixed.market_tape import MixedTapeRecorder, load_mixed_tape
from app.mixed.replay import (
    MixedComparison,
    MixedReplayAccount,
    MixedReplaySession,
    run_mixed_comparison,
)
from app.mixed.replay_model import MixedReplayScript, MixedScriptedDecision
from app.mixed.sources import StockCycleInput
from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.position_reasoning import PositionReasoningPolicy


def request_for(path, *, unknown=False, delay=1, operating="0"):
    limits, policy = settings(daily_operating_cost=operating)
    stocks = changed(policy.mixed_owner.stocks, share_step=".1")
    policy = changed(policy, mixed_owner=changed(policy.mixed_owner, stocks=stocks))
    h = header(stock_limits=stocks)
    path.mkdir(mode=0o700, parents=True)
    with MixedTapeRecorder(path / "common.tape", h) as recorder:
        recorder.append(stock_frame(), recorded_at=AT)
        for seconds in (1, 2, 3, 4, 7, 8):
            at = AT + timedelta(seconds=seconds)
            q = quote(at, **({"bid": "602", "ask": "602.01"} if seconds >= 3 else {}))
            recorder.append(
                DegenFrame(stocks=(StockCycleInput(quote=q),)), recorded_at=at, kind="MARKET"
            )
        recorder.seal()
    tape = load_mixed_tape(path / "common.tape")
    ep = changed(packet_for().policy, mixed_selection="mixed-paid-entry-v1")
    costs = CostPolicy(total_budget="10", daily_budget="2", max_call_cost=".01")
    accounts = []
    for arm in "ABCD":
        paid = arm != "A"
        execution = changed(
            policy,
            cost_policy=costs if paid else None,
            mixed_owner=changed(
                policy.mixed_owner, reasoning="mixed-paid-entry-v1" if paid else None
            ),
        )
        action = "UNKNOWN" if unknown and paid else "SELECT" if arm == "B" else "ENTER"
        decision = MixedScriptedDecision(
            cycle_key=tape.events[0].cycle_key,
            delay_seconds=delay,
            action=action,
            asset=None if action == "UNKNOWN" else "STOCK",
            candidate_index=None if action == "UNKNOWN" else 0,
        )
        accounts.append(
            MixedReplayAccount(
                arm=arm,
                limits=changed(
                    limits, account_id="mixed-" + arm, population_id="population-" + arm
                ),
                execution=execution,
                judgment_limits=JudgmentLimits(process_timeout_seconds=5, request_timeout_seconds=3)
                if paid
                else None,
                entry_policy=changed(
                    ep, mixed_shortlist="mixed-choice-only-v1" if arm == "B" else None
                )
                if paid
                else None,
                position_policy=PositionReasoningPolicy(
                    max_lease_seconds=5, mixed_management="mixed-stock-position-v1"
                )
                if arm == "D"
                else None,
                script=MixedReplayScript(arm=arm, decisions=(decision,)) if paid else None,
            )
        )
    return MixedComparison(sessions=(MixedReplaySession(tape=tape),), accounts=tuple(accounts))


@pytest.mark.parametrize(
    "damage", ["account", "capital", "fees", "allocation", "script", "deadline", "b_geometry"]
)
def test_comparison_requires_exact_independent_matched_contracts(tmp_path, damage):
    r = request_for(tmp_path / "source")
    value = r.model_dump()
    if damage == "account":
        value["accounts"][1]["limits"]["account_id"] = value["accounts"][0]["limits"]["account_id"]
    elif damage == "capital":
        value["accounts"][1]["execution"]["capital"] = "1001"
    elif damage == "fees":
        value["accounts"][1]["limits"]["entry_fee_per_contract"] = "1"
    elif damage == "allocation":
        value["accounts"][1]["execution"]["mixed_owner"]["daily_data_cost"] = None
    elif damage == "script":
        value["accounts"][3]["script"]["decisions"][0]["delay_seconds"] = 2
    elif damage == "deadline":
        value["accounts"][3]["judgment_limits"]["process_timeout_seconds"] = 6
    else:
        value["accounts"][1]["script"]["decisions"][0]["underlying_target"] = "605"
    with pytest.raises(ValueError):
        MixedComparison.model_validate(value)


@pytest.mark.parametrize("mode", ["complete", "unknown", "late", "unknown_operating"])
def test_native_mixed_comparison_retains_actual_fills_and_every_cost(tmp_path, mode):
    request = request_for(
        tmp_path / "source",
        unknown=mode == "unknown",
        delay=6 if mode == "late" else 1,
        operating=None if mode == "unknown_operating" else "0",
    )
    if mode == "unknown_operating":
        import sqlite3
        from contextlib import closing
        from types import SimpleNamespace

        from app.execution.engine import ExecutionBlocked
        from app.mixed.accounting import reconstruct
        from app.mixed.native_store import history

        directory = tmp_path / "replay"
        with pytest.raises(ExecutionBlocked, match="HEALTHY_EMPTY_STRATEGY_POPULATION_REQUIRED"):
            asyncio.run(run_mixed_comparison(request, directory))
        assert not (directory / "comparison.json").exists()
        assert not (directory / "B").exists()
        assert json.loads((directory / "interrupted.json").read_text())[
            "request_hash"
        ] == fingerprint(request)
        saved = json.loads((directory / "inputs.json").read_text())["request"]
        assert all(
            a["execution"]["mixed_owner"]["daily_operating_cost"] is None for a in saved["accounts"]
        )
        with closing(sqlite3.connect(f"file:{directory / 'A/options.db'}?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            control = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
            config = json.loads(control["config_json"])
            account = request.accounts[0]
            owner = SimpleNamespace(
                policy=account.execution,
                limits=account.limits,
                venue=SimpleNamespace(venue_id=config["venue_id"]),
                _control=lambda _db: control,
            )
            original = history(owner, db)
            assert not original.events and not original.reservations
            assert [c.amount for c in original.costs if c.kind == "OPERATING"] == [None]
            assert reconstruct(original).unknown_cost_ids
            assert db.execute("SELECT COUNT(*) FROM execution_model_calls").fetchone()[0] == 0
        return
    if mode == "complete":
        source = tmp_path / "request.json"
        source.write_text(request.model_dump_json())
        source.chmod(0o600)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-W",
                "error",
                "-m",
                "app.mixed.replay_cli",
                "run",
                "--request",
                str(source),
                "--output",
                str(tmp_path / "replay"),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=900,
        )
        assert result.returncode == 0, result.stderr
        bundle = json.loads((tmp_path / "replay/comparison.json").read_text())
        assert json.loads(result.stdout)["bundle_hash"] == bundle["bundle_hash"]
        verified = subprocess.run(
            [
                sys.executable,
                "-I",
                "-W",
                "error",
                "-m",
                "app.mixed.replay_cli",
                "verify",
                "--bundle",
                str(tmp_path / "replay/comparison.json"),
                "--expected-hash",
                bundle["bundle_hash"],
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        assert verified.returncode == 0, verified.stderr
        assert json.loads(verified.stdout)["report"] == bundle["report"]
        with pytest.raises(FileExistsError):
            asyncio.run(run_mixed_comparison(request, tmp_path / "replay"))
    else:
        bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "replay"))
    report = verify_mixed_comparison(json.loads(json.dumps(bundle)), bundle["bundle_hash"])
    assert report == bundle["report"]
    assert not report["execution_authority"] and not report["live_enabled"]
    accounts = report["sessions"][0]["accounts"]
    assert len({a["account_id"] for a in accounts.values()}) == 4
    for arm, account in accounts.items():
        value = account["accounting"]
        calls = [c for c in value["costs"] if c["kind"] == "ENTRY_MODEL"]
        assert len(calls) == int(arm != "A" and mode != "unknown_operating")
        if arm != "A" and mode == "unknown":
            assert calls[0]["amount"] is None and value["net_after_all_costs"] is None
        if mode == "complete":
            assert value["status"] == "COMPLETE_FLAT_ACCOUNTING"
            assert len(value["outcomes"]) == 1
            assert Decimal(value["outcomes"][0]["entry_quantity"]) > 0
            assert value["ledger"]["stock_position"] is None
        if mode == "late" and arm != "A":
            assert value["stock_orders"] == [] and calls[0]["amount"] is not None
    if mode == "complete":
        assert report["comparison_complete"]
        assert all(Decimal(v) < 0 for v in report["net_difference_vs_a"].values())
    if mode in {"unknown", "unknown_operating"}:
        assert not report["comparison_complete"]
        assert all(v is None for v in report["net_difference_vs_a"].values())
    if mode == "unknown":
        # Empty paid owners must reject unowned records even when all enclosing
        # hashes and the summary's export reference have been recomputed.
        for table in ("execution_stock_fills", "execution_fills"):
            altered = copy.deepcopy(bundle)
            native = altered["boundaries"][0]["B"]
            native["evidence"][table].append(
                copy.deepcopy(altered["boundaries"][0]["A"]["evidence"]["execution_stock_fills"][0])
            )
            native["export_hash"] = fingerprint(
                {k: v for k, v in native.items() if k != "export_hash"}
            )
            altered["report"]["sessions"][0]["accounts"]["B"]["export_hash"] = native["export_hash"]
            altered["bundle_hash"] = fingerprint(
                {k: v for k, v in altered.items() if k != "bundle_hash"}
            )
            with pytest.raises(ValueError, match="fill coverage"):
                verify_mixed_comparison(altered, altered["bundle_hash"])
    assert report["spy_session_compounded_price_return"] is None
    assert report["economic_conclusion"] == "INCONCLUSIVE"


def test_portable_mixed_comparison_rejects_rehashed_native_and_tape_tampering(tmp_path):
    request = request_for(tmp_path / "source")
    bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "replay"))
    for damage in ("cash", "cost", "clock", "account", "fill", "script", "skipped", "summary"):
        changed_bundle = copy.deepcopy(bundle)
        export = changed_bundle["boundaries"][0]["C"]
        if damage == "cash":
            import json

            ledger = json.loads(export["evidence"]["execution_control"][0][2])
            ledger["cash"] = "2000"
            export["evidence"]["execution_control"][0][2] = json.dumps(ledger)
        elif damage == "cost":
            export["evidence"]["execution_model_calls"][0][-1] = "0"
        elif damage == "clock":
            export["evidence"]["execution_option_opportunities"][0][2] = (
                AT - timedelta(seconds=1)
            ).isoformat()
        elif damage == "account":
            changed_bundle["boundaries"][0]["C"] = copy.deepcopy(
                changed_bundle["boundaries"][0]["B"]
            )
        elif damage == "fill":
            export["evidence"]["execution_stock_fills"].pop()
        elif damage == "script":
            changed_bundle["schedules"][0]["C"]["model_scripts_used"] = []
        elif damage == "skipped":
            changed_bundle["schedules"][0]["C"]["skipped_cycles"] = [
                request.sessions[0].tape.events[0].cycle_key
            ]
        else:
            changed_bundle["report"]["cumulative_net_after_all_costs"]["C"] = "1000"
        export["export_hash"] = fingerprint({k: v for k, v in export.items() if k != "export_hash"})
        changed_bundle["report"]["sessions"][0]["accounts"]["C"]["export_hash"] = changed_bundle[
            "boundaries"
        ][0]["C"]["export_hash"]
        changed_bundle["bundle_hash"] = fingerprint(
            {k: v for k, v in changed_bundle.items() if k != "bundle_hash"}
        )
        with pytest.raises((ValueError, RuntimeError)):
            verify_mixed_comparison(changed_bundle, changed_bundle["bundle_hash"])


def test_interrupted_comparison_retains_original_partial_native_evidence(tmp_path, monkeypatch):
    from app.mixed.replay import MixedArmReplay

    request = request_for(tmp_path / "source")

    async def fail(_self):
        raise RuntimeError("fixture interruption")

    monkeypatch.setattr(MixedArmReplay, "run", fail)
    with pytest.raises(RuntimeError, match="fixture interruption"):
        asyncio.run(run_mixed_comparison(request, tmp_path / "run"))
    assert (tmp_path / "run/A/options.db").is_file()
    assert not (tmp_path / "run/B").exists()
    assert not (tmp_path / "run/comparison.json").exists()
    assert json.loads((tmp_path / "run/interrupted.json").read_text()) == {
        "request_hash": fingerprint(request),
        "status": "INCOMPLETE_MIXED_REPLAY",
    }
    with pytest.raises(FileExistsError):
        asyncio.run(run_mixed_comparison(request, tmp_path / "run"))


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL", "UNKNOWN"])
def test_d_management_keeps_other_accounts_independent_and_all_charges(tmp_path, action):
    from test_option_position_coordination import management_frame

    request = request_for(tmp_path / "source")
    tape = request.sessions[0].tape
    at = AT + timedelta(minutes=5)
    current = changed(management_frame(), stocks=(StockCycleInput(quote=quote(at)),))
    with MixedTapeRecorder(tmp_path / "source/managed.tape", tape.header) as recorder:
        for event in tape.events[:3]:
            recorder.append(event.frame, recorded_at=event.recorded_at, kind=event.kind)
        recorder.append(current, recorded_at=at)
        for seconds, price in ((1, "600.8"), (2, "600.1"), (3, "600.1"), (4, "602"), (5, "602")):
            now = at + timedelta(seconds=seconds)
            q = quote(now, bid=price, ask=str(Decimal(price) + Decimal(".01")))
            recorder.append(
                DegenFrame(stocks=(StockCycleInput(quote=q),)), recorded_at=now, kind="MARKET"
            )
        recorder.seal()
    recorded = load_mixed_tape(tmp_path / "source/managed.tape")
    decision = MixedScriptedDecision(
        cycle_key="position:" + str(int(at.timestamp()) // 300),
        delay_seconds=1,
        action=action,
        underlying_invalidation="600.2" if action == "TIGHTEN" else None,
    )
    accounts = (
        *request.accounts[:3],
        changed(
            request.accounts[3],
            script=changed(
                request.accounts[3].script,
                decisions=(*request.accounts[3].script.decisions, decision),
            ),
        ),
    )
    request = changed(request, sessions=(MixedReplaySession(tape=recorded),), accounts=accounts)
    bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "replay"))
    report = verify_mixed_comparison(json.loads(json.dumps(bundle)), bundle["bundle_hash"])
    accounts = report["sessions"][0]["accounts"]
    for arm in "ABC":
        assert not any(
            c["kind"] == "MANAGEMENT_MODEL" for c in accounts[arm]["accounting"]["costs"]
        )
    d = accounts["D"]["accounting"]
    charges = [c for c in d["costs"] if c["kind"] == "MANAGEMENT_MODEL"]
    assert len(charges) == 1
    assert charges[0]["entry_client_id"] == d["outcomes"][0]["entry_client_id"]
    assert (charges[0]["amount"] is None) == (action == "UNKNOWN")
    assert d["ledger"]["stock_position"] is None
    cycles = [
        json.loads(r[5])
        for r in bundle["boundaries"][0]["D"]["evidence"]["execution_option_opportunities"]
    ]
    managed = next(r for r in cycles if "position_request" in r)
    assert (
        managed["status"]
        == {
            "MAINTAIN": "MAINTAIN",
            "TIGHTEN": "TIGHTENED",
            "EXIT_ALL": "OPEN",
            "UNKNOWN": "HELD",
        }[action]
    )
    assert len(d["outcomes"]) == 1
    if action != "UNKNOWN":
        assert report["comparison_complete"]
        assert Decimal(report["net_difference_vs_a"]["D"]) < Decimal(
            report["net_difference_vs_a"]["C"]
        )
    else:
        assert d["net_after_all_costs"] is None


@pytest.mark.parametrize(
    "mode",
    [
        "pending",
        "equal",
        "early",
        "missing",
        "hidden",
        "invented",
        "duplicate_skip",
        "unfinished",
        "unknown",
        "complete",
        "duplicate_attempt",
    ],
)
def test_cycle_coverage_cannot_hide_original_input_or_invent_paid_overlap(mode):
    from types import SimpleNamespace

    from app.mixed.comparison import schedule_binding

    later = AT + timedelta(minutes=5)
    events = tuple(
        SimpleNamespace(kind="CYCLE", cycle_key="degen:" + str(n), recorded_at=at)
        for n, at in enumerate((AT, later))
    )
    session = SimpleNamespace(tape=SimpleNamespace(events=events), watch_actions=())
    data = {
        "entry_request": {"packet": {"as_of": AT.isoformat()}},
        "entry_completed_at": (
            later + timedelta(seconds=1 if mode == "pending" else -1 if mode == "early" else 0)
        ).isoformat(),
    }
    rows = [{"cycle_key": "degen:0", "status": "COMPLETE", "result_json": json.dumps(data)}]
    skipped = ["degen:1"]
    if mode == "missing":
        rows[0]["result_json"] = "{}"
    elif mode == "hidden":
        skipped = []
    elif mode in {"invented", "complete"}:
        rows.append({"cycle_key": "degen:1", "status": "COMPLETE", "result_json": "{}"})
        if mode == "complete":
            skipped = []
    elif mode == "duplicate_skip":
        skipped *= 2
    elif mode == "unfinished":
        rows[0]["status"] = "STARTED"
    elif mode == "unknown":
        skipped.append("degen:2")
    elif mode == "duplicate_attempt":
        rows.append(rows[0])
    schedule = {
        "skipped_cycles": skipped,
        "model_scripts_used": [],
        "watch_actions": [],
        "fresh_reads": [],
    }
    tables = {"execution_option_opportunities": rows}
    if mode in {"pending", "equal", "complete"}:
        schedule_binding(session, schedule, tables, set())
    else:
        with pytest.raises(ValueError):
            schedule_binding(session, schedule, tables, set())
