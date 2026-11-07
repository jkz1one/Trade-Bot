"""Automatic native-source comparisons without execution-authority attachment."""

import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from test_degen_options import AT, frame, policies
from test_option_admission import END, inputs
from test_option_entry_reasoning import packet_for
from test_option_evaluation import OPEN, bundle_for
from test_option_execution import intent_for, quote_at, underlying_at
from test_option_market_tape import header_for

from app.execution.economics import UsageEvidence
from app.execution.judgment import JudgmentLimits
from app.options import entry_judgment, judgment
from app.options.coordinator import DegenCoordinator, DegenFrame
from app.options.engine import OptionExecution
from app.options.evaluation_export import export_arm, export_comparison, strategy_hash
from app.options.evaluation_export_cli import ExportRequest, ExportSource
from app.options.market_tape import TapeRecorder, load_tape
from app.options.venue import DurableOptionVenue


@pytest.fixture(scope="module")
def native_sources(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-export")
    b = bundle_for()
    header = header_for(b)
    definitions, sources, owners = [], {}, {}
    times = [OPEN]
    setup, selection = policies()

    async def narrow(request, _key):
        return judgment.result_for(
            request,
            count=1000,
            usage=UsageEvidence(
                request_id="narrow-hold", model=request.model, input_tokens=1000, output_tokens=100
            ),
        )

    async def broad(request, _key):
        return entry_judgment.result_for(
            request,
            plan=entry_judgment.hold(request.packet),
            count=1000,
            usage=UsageEvidence(
                request_id="broad-hold",
                model=request.configuration.costs.model,
                input_tokens=1000,
                output_tokens=100,
            ),
        )

    with pytest.MonkeyPatch.context() as patch, ExitStack() as stack:
        patch.setattr(judgment, "run_candidate_process", narrow)
        patch.setattr(entry_judgment, "run_entry_process", broad)
        for d in b.manifest.arms:
            directory = root / d.arm
            directory.mkdir(mode=0o700)
            key = directory / "private-model.key"
            key.write_text("fixture-only\n")
            key.chmod(0o600)
            venue = DurableOptionVenue(
                directory / "venue.db", limits=d.limits, capital=d.policy.capital
            )
            engine = stack.enter_context(
                OptionExecution.open(
                    directory / "journal.db", d.limits, d.policy, venue, now=OPEN, create=True
                )
            )
            assert engine.reconcile(venue.snapshot(OPEN), now=OPEN)["reconciled"]
            engine.assess(None, None, now=OPEN)
            c = DegenCoordinator(
                engine,
                setup,
                selection,
                create=True,
                clock=lambda: times[0],
                judgment_limits=JudgmentLimits() if d.arm != "A" else None,
                key_file=key if d.arm != "A" else None,
                entry_policy=packet_for().policy if d.arm == "C" else None,
            )
            definitions.append(
                d.model_copy(
                    update={"strategy_hash": strategy_hash(json.loads(c._configuration()))}
                )
            )
            sources[d.arm] = {
                "journal": str(directory / "journal.db"),
                "data_cost": ".01",
                "host_cost": ".02",
            }
            owners[d.arm] = c, venue
        with TapeRecorder(root / "common.tape", header) as recorder:
            start = b.benchmarks[0].start
            recorder.append(DegenFrame(underlyings=(start,)), recorded_at=OPEN, kind="MARKET")
            for n in range(78):
                at = OPEN + timedelta(minutes=5 * n)
                times[0] = at
                base = frame()
                f = (
                    base
                    if at == AT
                    else DegenFrame(
                        histories=(
                            base.histories[0].model_copy(
                                update={"source_at": at, "received_at": at, "bars": ()}
                            ),
                        ),
                        underlyings=(underlying_at(inputs(), at),),
                    )
                )
                recorder.append(f, recorded_at=at)
                results = {arm: asyncio.run(c.cycle(f)) for arm, (c, _) in owners.items()}
                if at == AT:
                    assert results["A"]["status"] == "OPEN", results
                    assert results["B"]["status"] == results["C"]["status"] == "HOLD", results
                    c, venue = owners["A"]
                    buy = intent_for(c.engine, results["A"]["client_id"])
                    filled = AT + timedelta(seconds=1)
                    q = quote_at(inputs(), filled)
                    recorder.append(DegenFrame(quotes=(q,)), recorded_at=filled, kind="MARKET")
                    venue.fill(buy, buy.quantity, q, filled, fill_id="buy")
                    assert c.engine.reconcile(venue.snapshot(filled), now=filled)["reconciled"]
                    times[0] = AT + timedelta(seconds=2)
                    q, u = (
                        quote_at(inputs(), times[0]),
                        underlying_at(inputs(), times[0], bid=Decimal(590), ask=Decimal("590.01")),
                    )
                    recorder.append(
                        DegenFrame(quotes=(q,), underlyings=(u,)),
                        recorded_at=times[0],
                        kind="MARKET",
                    )
                    result = asyncio.run(c.supervise((q,), (u,)))
                    with c.engine.journal.read() as db:
                        client = db.execute(
                            "SELECT client_id FROM execution_orders WHERE active_lock=1"
                        ).fetchone()[0]
                    sell = intent_for(c.engine, client)
                    assert sell.side == "SELL", result
                    filled = AT + timedelta(seconds=3)
                    q = quote_at(inputs(), filled)
                    recorder.append(DegenFrame(quotes=(q,)), recorded_at=filled, kind="MARKET")
                    venue.fill(sell, sell.quantity, q, filled, fill_id="sell")
                    assert c.engine.reconcile(venue.snapshot(filled), now=filled)["reconciled"]
            recorder.append(
                DegenFrame(underlyings=(b.benchmarks[0].end,)), recorded_at=END, kind="MARKET"
            )
            digest = recorder.seal()
        for c, venue in owners.values():
            assert c.engine.reconcile(venue.snapshot(END), now=END)["reconciled"]
    manifest = b.manifest.model_copy(
        update={
            "arms": tuple(definitions),
            "sessions": (b.manifest.sessions[0].model_copy(update={"tape_hash": digest}),),
        }
    )
    return root, manifest, sources


@pytest.fixture
def captured(native_sources, tmp_path):
    root, manifest, sources = native_sources
    copied = {}
    for arm, source in sources.items():
        destination = tmp_path / (arm + ".db")
        shutil.copy2(source["journal"], destination)
        copied[arm] = {**source, "journal": str(destination)}
    # These standalone copies have no usable authority pair, venue or model key.
    return manifest, load_tape(root / "common.tape"), copied


def test_native_three_arm_export_reconstructs_trade_and_paid_holds(captured):
    manifest, tape, sources = captured
    before = {a: Path(s["journal"]).read_bytes() for a, s in sources.items()}
    result = export_comparison(manifest, tape, sources)
    report = result["report"]
    assert report["status"] == "COMPLETE_ARITHMETIC", report
    assert report["recorded_market_verified"]
    assert report["economic_conclusion"] == "INCONCLUSIVE"
    assert Decimal(report["totals"]["A"]["net_change"]) == Decimal("-23.23")
    assert Decimal(report["totals"]["B"]["net_change"]) == Decimal("-.03015")
    assert report["totals"]["B"] == report["totals"]["C"]
    assert len(result["bundle"].evidence[0].orders) == 2
    assert all(len(a.cycles) == 78 for a in result["bundle"].evidence)
    assert all(p["revision"] > 0 and not p["execution_authority"] for p in result["source_proof"])
    for arm, source in sources.items():
        assert Path(source["journal"]).read_bytes() == before[arm]
    assert "private-model.key" not in result["bundle"].model_dump_json()


@pytest.mark.parametrize(
    "damage",
    [
        "definition",
        "strategy",
        "model_row",
        "model_cost",
        "model_event",
        "model_both_removed",
        "fill",
        "cycle",
        "cycle_finish",
        "attempt",
        "event_gap",
        "snapshot_cash",
        "historical",
    ],
)
def test_conflicting_native_evidence_cannot_be_exported(captured, damage):
    manifest, tape, sources = captured
    arm = "B" if damage.startswith("model") else "A"
    with sqlite3.connect(sources[arm]["journal"]) as db:
        if damage == "definition":
            raw = json.loads(db.execute("SELECT config_json FROM execution_control").fetchone()[0])
            raw["limits"]["population_id"] = "foreign"
            db.execute("UPDATE execution_control SET config_json=?", (json.dumps(raw),))
        elif damage == "strategy":
            raw = json.loads(
                db.execute("SELECT policy_json FROM execution_option_strategy").fetchone()[0]
            )
            raw["setup"]["history_source"] = "foreign"
            db.execute("UPDATE execution_option_strategy SET policy_json=?", (json.dumps(raw),))
        elif damage == "model_row":
            db.execute("DELETE FROM execution_model_calls")
        elif damage == "model_cost":
            db.execute("UPDATE execution_model_calls SET cost='0'")
        elif damage == "model_event":
            db.execute(
                "UPDATE execution_events SET kind='REMOVED' WHERE kind='OPTION_MODEL_USAGE_RECORDED'"
            )
        elif damage == "model_both_removed":
            db.execute("DELETE FROM execution_model_calls")
            db.execute(
                "UPDATE execution_events SET kind='REMOVED' WHERE kind IN ('OPTION_MODEL_USAGE_RECORDED','OPTION_MODEL_ATTEMPT_ADMITTED')"
            )
        elif damage == "fill":
            db.execute("DELETE FROM execution_fills WHERE fill_id='buy'")
        elif damage == "cycle":
            db.execute("UPDATE execution_option_opportunities SET fingerprint=?", ("f" * 64,))
        elif damage == "cycle_finish":
            db.execute(
                "UPDATE execution_events SET kind='REMOVED' WHERE kind='DEGEN_CYCLE_COMPLETED'"
            )
        elif damage == "attempt":
            db.execute("UPDATE execution_orders SET attempted_at=NULL")
        elif damage == "event_gap":
            db.execute("DELETE FROM execution_events WHERE sequence=1")
        elif damage == "snapshot_cash":
            raw = json.loads(
                db.execute("SELECT snapshot_json FROM execution_control").fetchone()[0]
            )
            raw["cash"] = "999"
            db.execute("UPDATE execution_control SET snapshot_json=?", (json.dumps(raw),))
        elif damage == "historical":
            db.execute(
                "UPDATE execution_option_opportunities SET started_at=?",
                ((OPEN - timedelta(days=1)).isoformat(),),
            )
    with pytest.raises(ValueError):
        export_comparison(manifest, tape, sources)


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("missing_cost", "ALLOCATED_COST_UNKNOWN"),
        ("closing", "UNRESOLVED_ORDER_OR_CLOSING_EVIDENCE"),
        ("interrupted", "UNRESOLVED_CYCLE"),
        ("unknown_usage", "MODEL_COST_UNKNOWN"),
    ],
)
def test_retained_unknowns_remain_inconclusive(captured, damage, reason):
    manifest, tape, sources = captured
    if damage == "missing_cost":
        sources["B"]["host_cost"] = None
    else:
        with sqlite3.connect(sources["B"]["journal"]) as db:
            if damage == "closing":
                raw = json.loads(
                    db.execute("SELECT snapshot_json FROM execution_control").fetchone()[0]
                )
                raw["captured_at"] = (END - timedelta(minutes=1)).isoformat()
                db.execute("UPDATE execution_control SET snapshot_json=?", (json.dumps(raw),))
            elif damage == "interrupted":
                db.execute(
                    "UPDATE execution_option_opportunities SET status='INTERRUPTED' WHERE cycle_key=(SELECT cycle_key FROM execution_option_opportunities LIMIT 1)"
                )
            else:
                db.execute(
                    "UPDATE execution_model_calls SET usage_json=NULL,request_id=NULL,decision_hash=NULL,cost=NULL"
                )
                db.execute(
                    "UPDATE execution_events SET kind='REMOVED' WHERE kind='OPTION_MODEL_USAGE_RECORDED'"
                )
    report = export_comparison(manifest, tape, sources)["report"]
    assert report["status"] == "INCONCLUSIVE"
    assert reason in report["sessions"][0]["arms"]["B"]["reasons"]
    assert report["totals"]["B"]["net_change"] is None


def test_missing_scheduler_slot_is_not_fabricated(captured):
    manifest, tape, sources = captured
    with sqlite3.connect(sources["A"]["journal"]) as db:
        key = "degen:" + str(int(OPEN.timestamp()) // 300)
        db.execute("DELETE FROM execution_option_opportunities WHERE cycle_key=?", (key,))
        for row in db.execute(
            "SELECT sequence,payload FROM execution_events WHERE kind LIKE 'DEGEN_CYCLE_%'"
        ).fetchall():
            if json.loads(row[1]).get("cycle_key") == key:
                db.execute("UPDATE execution_events SET kind='REMOVED' WHERE sequence=?", (row[0],))
    result = export_comparison(manifest, tape, sources)
    assert len(result["bundle"].evidence[0].cycles) == 77
    assert (
        "INCOMPLETE_SCHEDULER_COVERAGE" in result["report"]["sessions"][0]["arms"]["A"]["reasons"]
    )


def test_ambient_decimal_context_cannot_change_export(captured):
    manifest, tape, sources = captured
    expected = export_comparison(manifest, tape, sources)
    with localcontext() as context:
        context.prec = 3
        assert export_comparison(manifest, tape, sources) == expected


def test_missing_source_is_not_created(captured, tmp_path):
    manifest, tape, _ = captured
    path = tmp_path / "absent.db"
    with pytest.raises(OSError):
        export_arm(path, manifest.arms[0], manifest.sessions[0], tape)
    assert not path.exists()


@pytest.mark.parametrize("missing", [False, True])
def test_installed_export_cli_private_sanitized_output(captured, native_sources, tmp_path, missing):
    manifest, _, sources = captured
    root = native_sources[0]
    if missing:
        sources["B"]["journal"] = str(tmp_path / "private-missing.db")
    request = ExportRequest(
        manifest=manifest,
        tape=str(root / "common.tape"),
        sources=tuple(ExportSource(arm=arm, **source) for arm, source in sources.items()),
    )
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    path.chmod(0o600)
    r = subprocess.run(
        [sys.executable, "-I", "-m", "app.options.evaluation_export_cli", "--request", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert r.returncode == (2 if missing else 0), r.stderr
    result = json.loads(r.stdout)
    assert not r.stderr and str(tmp_path) not in r.stdout
    if missing:
        assert result["status"] == "UNAVAILABLE"
    else:
        assert result["report"]["status"] == "COMPLETE_ARITHMETIC"


def test_management_cohort_cannot_be_exported_as_deterministic_management_arm(captured):
    manifest, tape, sources = captured
    with sqlite3.connect(sources["C"]["journal"]) as db:
        strategy = json.loads(
            db.execute("SELECT policy_json FROM execution_option_strategy").fetchone()[0]
        )
        strategy["position_model"] = {"version": "fixture-managed-cohort"}
        db.execute("UPDATE execution_option_strategy SET policy_json=?", (json.dumps(strategy),))
    definition = manifest.arms[2].model_copy(update={"strategy_hash": strategy_hash(strategy)})
    with pytest.raises(ValueError, match="strategy binding"):
        export_arm(
            sources["C"]["journal"],
            definition,
            manifest.sessions[0],
            tape,
            data_cost=".01",
            host_cost=".02",
        )
