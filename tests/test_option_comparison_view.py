"""Historical report projection, bounded immutable reads and truthful dashboard gaps."""

import copy
import json
import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import owned_strategy
from test_option_admission import END
from test_option_evaluation import bundle_for, change_arm
from test_option_observer import app_for

from app.options.comparison_view import (
    StoredComparison,
    build_comparison,
    chart_data,
    read_private_json,
    stored_comparison,
    write_comparison,
)
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.evaluation_export import strategy_hash


def result_for(bundle=None):
    """Synthetic publication unit input; actual native export is checked separately."""
    bundle = bundle or bundle_for()
    return {
        "bundle": bundle.model_dump(mode="json"),
        "report": evaluate(bundle),
        "source_proof": [
            {
                "arm": r.arm,
                "session_key": r.session_key,
                "revision": 1,
                "strategy_hash": next(
                    a.strategy_hash for a in bundle.manifest.arms if a.arm == r.arm
                ),
                "export_hash": fingerprint(r),
                "configuration_hash": "a" * 64,
                "event_hash": "b" * 64,
                "execution_authority": False,
                "source_kind": "READ_ONLY_NATIVE_FIXTURE_JOURNAL",
            }
            for r in bundle.evidence
        ],
    }


def database_and_view(tmp_path):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""CREATE TABLE execution_control(id INTEGER DEFAULT 1,config_json TEXT);
        CREATE TABLE execution_option_strategy(id INTEGER DEFAULT 1,policy_json TEXT);
        CREATE TABLE execution_events(sequence INTEGER,kind TEXT);""")
    config = {"limits": {"account_id": "option-paper"}}
    strategy = {"setup": {"version": "fixture"}, "selection": {}}
    db.execute("INSERT INTO execution_control(config_json) VALUES(?)", (json.dumps(config),))
    db.execute(
        "INSERT INTO execution_option_strategy(policy_json) VALUES(?)", (json.dumps(strategy),)
    )
    db.execute("INSERT INTO execution_events VALUES(1,'FIXTURE')")
    view = build_comparison(result_for(), "B").model_copy(
        update={
            "configuration_hash": fingerprint(config),
            "strategy_hash": strategy_hash(strategy),
            "event_hash": fingerprint([{"sequence": 1, "kind": "FIXTURE"}]),
        }
    )
    path = tmp_path / "comparison.json"
    write_comparison(path, view)
    return db, path, view


def test_projection_accounts_for_all_known_costs_and_exact_spy():
    view = build_comparison(result_for(), "B")
    point = view.points[0]
    assert point.equity == Decimal("999.96985")
    assert point.deterministic_equity == Decimal("999.97")
    assert point.spy_equity == Decimal(1010)
    assert point.entry_model_cost == Decimal(".00015")
    assert point.management_model_cost == 0 and point.unknown_model_calls == 0
    assert (
        point.venue_fees == 0
        and point.data_cost == Decimal(".01")
        and point.host_cost == Decimal(".02")
    )
    assert view.economic_conclusion == "INCONCLUSIVE" and not view.execution_authority
    chart = chart_data({"status": "AVAILABLE", **view.model_dump(mode="json")})
    assert len(chart["lines"]) == 3 and all(len(l["points"].split()) == 2 for l in chart["lines"])


@pytest.mark.parametrize(
    "damage",
    [
        "net",
        "fee",
        "model",
        "spy",
        "manifest",
        "evidence",
        "proof",
        "strategy",
        "authority",
        "profit",
    ],
)
def test_materialization_rejects_modified_report_or_proof(damage):
    result = result_for()
    row = result["report"]["sessions"][0]
    if damage in {"net", "fee", "model"}:
        row["arms"]["B"][
            {"net": "net_change", "fee": "venue_fees", "model": "known_model_cost"}[damage]
        ] = "999"
    elif damage == "spy":
        row["spy_price_return"] = "1"
    elif damage in {"manifest", "evidence"}:
        result["report"][damage + "_hash"] = "f" * 64
    elif damage in {"proof", "strategy"}:
        result["source_proof"][1]["export_hash" if damage == "proof" else "strategy_hash"] = (
            "f" * 64
        )
    elif damage == "authority":
        result["report"]["execution_authority"] = True
    else:
        result["report"]["economic_conclusion"] = "PASS"
    with pytest.raises(ValueError):
        build_comparison(result, "B")


def test_unknown_cost_is_not_zero_and_cumulative_paths_are_withheld():
    b = bundle_for()
    call = b.evidence[1].calls[0].model_copy(update={"completed_at": None, "usage": None})
    view = build_comparison(result_for(change_arm(b, calls=(call,))), "B")
    p = view.points[0]
    assert p.unknown_model_calls == 1 and p.equity is None and p.spy_equity is None
    assert p.net_change is None and p.status == "INCONCLUSIVE"
    assert "MODEL_COST_UNKNOWN" in p.reasons
    assert chart_data({"status": "AVAILABLE", **view.model_dump(mode="json")}) is None
    raw = view.model_dump()
    raw["points"][0]["equity"] = "1000"
    with pytest.raises(ValueError, match="Incomplete paths"):
        StoredComparison.model_validate(raw)


def test_chart_stops_at_first_gap_and_never_rebases_later_complete_rows():
    view = build_comparison(result_for(), "B")
    first = view.points[0]
    gap = first.model_copy(
        update={
            "session": "2026-10-12",
            "status": "INCONCLUSIVE",
            "equity": None,
            "deterministic_equity": None,
            "spy_equity": None,
            "net_change": None,
            "reasons": ("ALLOCATED_COST_UNKNOWN",),
        }
    )
    later = gap.model_copy(
        update={
            "session": "2026-10-13",
            "status": "COMPLETE",
            "reasons": (),
            "net_change": Decimal(".01"),
        }
    )
    view = StoredComparison.model_validate(
        view.model_dump() | {"points": (first, gap, later), "through": END + timedelta(days=4)}
    )
    chart = chart_data({"status": "AVAILABLE", **view.model_dump(mode="json")})
    assert all(len(line["points"].split()) == 2 for line in chart["lines"])
    assert all(line["points"].split()[-1].startswith("266.67,") for line in chart["lines"])


def test_reads_bind_historical_prefix_without_evaluation_or_writes(tmp_path, monkeypatch):
    from app.options import evaluation

    db, path, _ = database_and_view(tmp_path)
    before = path.read_bytes(), db.total_changes
    monkeypatch.setattr(
        evaluation, "evaluate", lambda *a, **k: pytest.fail("Evaluation on page read")
    )
    try:
        for _ in range(3):
            result = stored_comparison(path, db, "evaluation-B", END)
            assert result["status"] == "AVAILABLE" and result["points"][0]["equity"] == "999.96985"
        assert (path.read_bytes(), db.total_changes) == before
        db.execute("INSERT INTO execution_events VALUES(2,'LATER')")
        assert stored_comparison(path, db, "evaluation-B", END)["status"] == "AVAILABLE"
        db.execute("UPDATE execution_events SET kind='REPLACED' WHERE sequence=1")
        assert stored_comparison(path, db, "evaluation-B", END)["status"] == "UNAVAILABLE"
    finally:
        db.close()


@pytest.mark.parametrize(
    "damage",
    [
        "population",
        "account",
        "configuration",
        "strategy",
        "future",
        "seal",
        "symlink",
        "mode",
        "missing",
        "oversize",
        "fifo",
    ],
)
def test_foreign_unavailable_or_unsafe_view_is_sanitized(tmp_path, damage):
    db, path, _ = database_and_view(tmp_path)
    population, now = "evaluation-B", END
    if damage == "population":
        population = "other-population"
    elif damage in {"account", "configuration"}:
        value = {
            "limits": {"account_id": "other" if damage == "account" else "option-paper"},
            "changed": True,
        }
        db.execute("UPDATE execution_control SET config_json=?", (json.dumps(value),))
    elif damage == "strategy":
        db.execute("UPDATE execution_option_strategy SET policy_json='{}'")
    elif damage == "future":
        now -= timedelta(seconds=1)
    elif damage == "seal":
        envelope = json.loads(path.read_text())
        envelope["view"]["points"][0]["equity"] = "10000"
        path.write_text(json.dumps(envelope))
    elif damage == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    elif damage == "mode":
        path.chmod(0o644)
    elif damage == "missing":
        path.unlink()
    elif damage == "oversize":
        path.write_bytes(b" " * (256 * 1024 + 1))
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    try:
        result = stored_comparison(path, db, population, now)
        assert result == {"status": "UNAVAILABLE", "reason": "STORED_COMPARISON_UNAVAILABLE"}
        assert str(path) not in json.dumps(result)
    finally:
        db.close()


def test_create_only_seal_and_private_path_contract(tmp_path):
    view = build_comparison(result_for(), "B")
    path = tmp_path / "view.json"
    write_comparison(path, view)
    assert path.stat().st_mode & 0o777 == 0o600
    envelope = read_private_json(path, 256 * 1024)
    assert envelope["digest"] == fingerprint(envelope["view"])
    with pytest.raises(FileExistsError):
        write_comparison(path, view)
    with pytest.raises(ValueError):
        write_comparison("relative.json", view)
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="Private owned"):
        write_comparison(tmp_path / "public.json", view)


def test_installed_materialization_cli_is_create_only_and_sanitized(tmp_path):
    source = tmp_path / "result.json"
    source.write_text(json.dumps(result_for()))
    source.chmod(0o600)
    destination = tmp_path / "view.json"
    args = [
        sys.executable,
        "-I",
        "-m",
        "app.options.comparison_cli",
        "--result",
        str(source),
        "--arm",
        "B",
        "--output",
        str(destination),
    ]
    run = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)["status"] == "CREATED"
    original = destination.read_bytes()
    repeated = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    assert repeated.returncode == 2 and str(destination) not in repeated.stdout
    assert destination.read_bytes() == original


@pytest.mark.parametrize(
    "state", ["AVAILABLE", "UNAVAILABLE", "NOT_CONFIGURED", "INCOMPLETE", "LONG_TEXT"]
)
def test_server_rendered_comparison_states_preserve_truthful_labels(tmp_path, monkeypatch, state):
    from app.options.observer import OptionObserver

    with owned_strategy(tmp_path) as (c, *_):
        data = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
        view = build_comparison(result_for(), "B")
        data["comparison"] = (
            {"status": "AVAILABLE", **view.model_dump(mode="json")}
            if state in {"AVAILABLE", "INCOMPLETE", "LONG_TEXT"}
            else {"status": state}
        )
        if state == "INCOMPLETE":
            p = data["comparison"]["points"][0]
            p.update(
                status="INCONCLUSIVE",
                net_change=None,
                equity=None,
                deterministic_equity=None,
                spy_equity=None,
                unknown_model_calls=1,
                reasons=["MODEL_COST_UNKNOWN"],
            )
        if state == "LONG_TEXT":
            data["comparison"]["experiment_id"] = '<script>alert("x")</script>' + "L" * 100
        monkeypatch.setattr(OptionObserver, "report", lambda *a, **k: copy.deepcopy(data))
        client, _ = app_for(c, tmp_path)
        response = client.get("/")
        assert response.status_code == 200
        text = response.text
        assert 'href="#content"' in text and 'aria-label="Desk details"' in text
        assert "Balance history" in text
        assert "<script>" not in text
        if state in {"AVAILABLE", "LONG_TEXT"}:
            assert 'role="img"' in text and "Entry / management model" in text
            assert "$999.97" in text and "0.00015" in text
        elif state == "INCOMPLETE":
            assert "No complete cumulative path" in text and "MODEL_COST_UNKNOWN" in text
            assert 'role="img"' not in text
        elif state == "UNAVAILABLE":
            assert "does not match this population" in text
        else:
            assert "No historical comparison is linked" in text
