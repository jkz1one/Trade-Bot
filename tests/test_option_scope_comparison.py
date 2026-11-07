"""Matched Scope replay validates independence and reconstructs native totals."""

import asyncio
import copy
import json
from decimal import Decimal

import pytest
from test_option_scope_model_replay import request as model_request
from test_option_scope_shortlist import request as shortlist_request

from app.options.engine import fingerprint
from app.options.scope_comparison import (
    ScopeComparison,
    comparison_report,
    run_scope_comparison,
    verify_scope_comparison,
)
from app.options.scope_model_replay import ScopeModelReplay
from app.options.scope_replay_model import ScopeReplayScript
from app.options.scope_trading_replay import ScopeTradingReplay


def request(tmp_path):
    sub = tmp_path / "seed"
    sub.mkdir()
    d = model_request(sub, arm="D")
    c = ScopeModelReplay.model_validate(
        d.model_dump()
        | {
            "script": ScopeReplayScript(arm="C", decisions=(d.script.decisions[0],)).model_dump(),
            "position_policy": None,
        }
    )
    other = tmp_path / "bseed"
    other.mkdir()
    b = shortlist_request(other)
    b = b.model_copy(update={"tape": d.tape, "watch_actions": d.watch_actions})
    a = ScopeTradingReplay(
        tape=d.tape,
        limits=d.limits,
        execution=d.execution.model_copy(
            update={"scope_arbitration": "shared-scope-selection-v1", "cost_policy": None}
        ),
        scope=d.scope.model_copy(update={"version": "shared-scope-selection-v1"}),
        watch_actions=d.watch_actions,
        data_cost=d.data_cost,
        host_cost=d.host_cost,
    )
    arms = [
        r.model_copy(
            update={
                "limits": r.limits.model_copy(
                    update={"population_id": "scope-" + arm, "account_id": "account-" + arm}
                )
            }
        )
        for arm, r in zip("ABCD", (a, b, c, d), strict=True)
    ]
    return ScopeComparison(baseline=arms[0], shortlist=arms[1], entry=arms[2], managed=arms[3])


@pytest.mark.parametrize(
    "kind",
    [
        "account",
        "population",
        "capital",
        "fees",
        "watch",
        "allocation",
        "costs",
        "model-limit",
        "entry-policy",
        "script",
        "role",
    ],
)
def test_comparison_rejects_unmatched_accounts_and_configuration(tmp_path, kind):
    req = request(tmp_path).model_dump(mode="json")
    b = req["shortlist"]
    c = req["entry"]
    if kind in ("account", "population"):
        key = kind + "_id"
        b["limits"][key] = c["limits"][key]
    elif kind == "capital":
        b["execution"]["capital"] = "10001"
    elif kind == "fees":
        b["limits"]["entry_fee_per_order"] = "0.19"
    elif kind == "watch":
        b["watch_actions"][0]["key"] = "different"
    elif kind == "allocation":
        b["data_cost"] = ".09"
    elif kind == "costs":
        b["execution"]["cost_policy"]["daily_budget"] = ".09"
    elif kind == "model-limit":
        b["judgment_limits"]["request_timeout_seconds"] = 2
    elif kind == "entry-policy":
        b["entry_policy"]["max_horizon_seconds"] = 1799
    elif kind == "script":
        req["managed"]["script"]["decisions"][0]["delay_seconds"] = 2
    elif kind == "role":
        req["shortlist"] = c
    with pytest.raises(ValueError):
        ScopeComparison.model_validate(req)


def test_native_four_independent_scope_accounts_and_portable_comparison(tmp_path):
    req = request(tmp_path)
    home = tmp_path / "run"
    report = asyncio.run(run_scope_comparison(req, home))
    assert report["status"] == "COMPLETE_FLAT_COMPARISON" and report["comparison_complete"]
    assert report["economic_conclusion"] == "INCONCLUSIVE" and not report["live_enabled"]
    a = report["accounts"]
    assert len({r["population_id"] for r in a.values()}) == 4
    assert len({r["account_id"] for r in a.values()}) == 4
    for arm in "ABCD":
        assert len(a[arm]["orders"]) == 2
        assert a[arm]["ledger"]["position"] is None
        assert Decimal(a[arm]["execution_fees"]) > 0
        if arm != "A":
            assert Decimal(report["net_difference_vs_a"][arm]) == Decimal(
                a[arm]["net_after_all_costs"]
            ) - Decimal(a["A"]["net_after_all_costs"])
    assert a["A"]["model_costs"]["known_cost"] == "0"
    assert (
        Decimal(a["D"]["model_costs"]["known_cost"])
        > Decimal(a["C"]["model_costs"]["known_cost"])
        > 0
    )
    bundle = json.loads((home / "comparison.json").read_text())
    assert verify_scope_comparison(bundle, bundle["comparison_hash"])["report"] == report
    with pytest.raises(FileExistsError):
        asyncio.run(run_scope_comparison(req, home))
    changed = copy.deepcopy(bundle)
    changed["report"]["net_difference_vs_a"]["B"] = "999"
    with pytest.raises(ValueError):
        verify_scope_comparison(changed, bundle["comparison_hash"])
    changed["comparison_hash"] = fingerprint(
        {k: v for k, v in changed.items() if k != "comparison_hash"}
    )
    with pytest.raises(ValueError, match="totals"):
        verify_scope_comparison(changed, changed["comparison_hash"])
    changed = copy.deepcopy(bundle["exports"])
    changed["B"] = changed["C"]
    with pytest.raises(ValueError, match="owner"):
        comparison_report(req, changed)
    # Unknown operating allocations cannot be filled with zero or publish paired nets.
    unknown = req.model_copy(
        update={
            k: getattr(req, k).model_copy(update={"host_cost": None})
            for k in ("baseline", "shortlist", "entry", "managed")
        }
    )
    # Inputs cannot relabel existing exports: frozen allocations are checked.
    with pytest.raises(ValueError):
        comparison_report(unknown, bundle["exports"])


def test_comparison_interruption_retains_partial_evidence(tmp_path, monkeypatch):
    import app.options.scope_comparison as module

    req = request(tmp_path)

    async def interrupted(r, home):
        home.mkdir()
        (home / "native-pending.txt").write_text("retained local fixture")
        raise RuntimeError("fixture-interruption")

    monkeypatch.setattr(module, "run_scope_trading_replay", interrupted)
    home = tmp_path / "run"
    with pytest.raises(RuntimeError, match="fixture-interruption"):
        asyncio.run(run_scope_comparison(req, home))
    assert (home / "A/native-pending.txt").is_file()
    assert not (home / "B").exists() and not (home / "report.json").exists()
    assert json.loads((home / "interrupted.json").read_text())["completed_arms"] == []
    with pytest.raises(FileExistsError):
        asyncio.run(run_scope_comparison(req, home))


def test_native_unknown_b_cost_does_not_contaminate_other_accounts(tmp_path):
    from test_option_scope_market_tape import record

    req = request(tmp_path)
    first = next(e for e in req.baseline.tape.events if e.kind == "CYCLE")
    tape = record(
        tmp_path / "unknown.tape",
        req.baseline.tape.header,
        [
            (e.recorded_at, "SCOPE" if e.kind == "CYCLE" and e != first else e.kind, e.frame)
            for e in req.baseline.tape.events
        ],
    )
    arms = {
        k: getattr(req, k).model_copy(update={"tape": tape})
        for k in ("baseline", "shortlist", "entry", "managed")
    }
    b = arms["shortlist"]
    d = b.script.decisions[0].model_copy(update={"action": "UNKNOWN", "scope": False})
    arms["shortlist"] = b.model_copy(
        update={"script": b.script.model_copy(update={"decisions": (d,)})}
    )
    req = ScopeComparison.model_validate(req.model_copy(update=arms).model_dump())
    report = asyncio.run(run_scope_comparison(req, tmp_path / "run"))
    assert report["status"] == "INCOMPLETE_ACCOUNTING" and not report["comparison_complete"]
    assert report["net_difference_vs_a"] == dict.fromkeys("BCD")
    assert report["accounts"]["B"]["model_costs"]["unknown_calls"] == 1
    assert report["accounts"]["B"]["orders"] == []
    assert report["accounts"]["B"]["net_after_all_costs"] is None
    for arm in "ACD":
        assert report["accounts"][arm]["status"] == "COMPLETE_FLAT_ACCOUNTING"
        assert len(report["accounts"][arm]["orders"]) == 2
    bundle = json.loads((tmp_path / "run/comparison.json").read_text())
    assert verify_scope_comparison(bundle, bundle["comparison_hash"])["report"] == report
