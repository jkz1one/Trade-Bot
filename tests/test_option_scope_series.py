"""Scope owners retain original authority, paid evidence and independent session cash."""

import asyncio
import copy
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from test_option_scope_comparison import request as one_session
from test_option_scope_context import bind
from test_option_scope_market_tape import record
from test_option_scope_structure import bind as bind_structure

from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.lifecycle import OptionReceipt
from app.options.market_tape import TapeHeader
from app.options.replay import ScriptedSettlement
from app.options.scope_comparison import ScopeComparison
from app.options.scope_series import (
    ScopeSeries,
    _continuity,
    run_scope_series,
    series_report,
    verify_scope_series,
)
from app.options.scope_tape_watch import ScopeTapeWatchAction

SHIFT = timedelta(days=7)


def shifted(value):
    if isinstance(value, dict):
        return {
            k: v + "-later" if k in {"instrument_id", "play_key"} else shifted(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [shifted(v) for v in value]
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}(T|$)", value):
        return (
            (date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value))
            + SHIFT
        ).isoformat()
    return value


def request(root, *, settlement=True, unknown=False, missing_cost=False):
    first = one_session(root)
    tape = first.baseline.tape
    # Remove the extra cycle for unknown B so no unplanned paid call is introduced.
    if unknown:
        initial = next(e for e in tape.events if e.kind == "CYCLE")
        tape = record(
            root / "unknown.tape",
            tape.header,
            [
                (e.recorded_at, "SCOPE" if e.kind == "CYCLE" and e != initial else e.kind, e.frame)
                for e in tape.events
            ],
        )
    header = TapeHeader.model_validate(shifted(tape.header.model_dump(mode="json"))).model_copy(
        update={"declared_at": tape.header.declared_at}
    )
    frames = []
    for e in tape.events:
        f = DegenFrame.model_validate(shifted(e.frame.model_dump(mode="json")))
        if f.scope:
            f = f.model_copy(
                update={
                    "scope": f.scope.model_copy(
                        update={"frame": bind(bind_structure(f.scope.frame), f.scope.context)}
                    )
                }
            )
        frames.append((e.recorded_at + SHIFT, e.kind, f))
    later = record(root / "later.tape", header, frames)
    actions = tuple(
        ScopeTapeWatchAction.model_validate(
            shifted(a.model_dump(mode="json")) | {"key": a.key + "-later"}
        )
        for a in first.baseline.watch_actions
    )
    arms = {}
    for name in ("baseline", "shortlist", "entry", "managed"):
        r = getattr(first, name).model_copy(update={"tape": tape})
        if name != "baseline":
            decisions = r.script.decisions
            if unknown:
                decisions = tuple(d for d in decisions if d.cycle_key.startswith("degen:"))
            if unknown and name == "shortlist":
                decisions = (decisions[0].model_copy(update={"action": "UNKNOWN", "scope": False}),)
            later_decisions = tuple(
                d.model_copy(
                    update={
                        "cycle_key": d.cycle_key.split(":")[0]
                        + ":"
                        + str(int(d.cycle_key.split(":")[1]) + int(SHIFT.total_seconds()) // 300)
                    }
                )
                for d in decisions
            )
            r = r.model_copy(
                update={
                    "script": r.script.model_copy(update={"decisions": decisions + later_decisions})
                }
            )
        arms[name] = r
    first = ScopeComparison.model_validate(first.model_copy(update=arms).model_dump())
    second = ScopeComparison.model_validate(
        first.model_copy(
            update={
                name: getattr(first, name).model_copy(
                    update={"tape": later, "watch_actions": actions}
                )
                for name in arms
            }
        ).model_dump()
    )
    if missing_cost:
        first = first.model_copy(
            update={
                name: getattr(first, name).model_copy(update={"host_cost": None}) for name in arms
            }
        )
    receipts = (
        tuple(
            ScriptedSettlement(
                arm=arm,
                receipt=OptionReceipt(
                    receipt_id="sale-credit-" + arm,
                    sequence=3,
                    kind="FUNDS_SETTLED",
                    occurred_at=later.header.opens_at - timedelta(hours=1),
                    cash_change="1",
                ),
            )
            for arm in ("ACD" if unknown else "ABCD")
        )
        if settlement
        else ()
    )
    return ScopeSeries(sessions=(first, second), settlements=receipts)


@pytest.mark.parametrize(
    "kind",
    [
        "order",
        "duplicate",
        "owner",
        "policy",
        "script",
        "source",
        "action",
        "declaration",
        "settlement-time",
        "settlement-duplicate",
        "script-slot",
        "carry",
    ],
)
def test_series_rejects_changed_frozen_contract_before_output(tmp_path, kind):
    req = request(tmp_path)
    data = req.model_dump(mode="json")
    a, b = data["sessions"]
    if kind == "order":
        data["sessions"].reverse()
    elif kind == "duplicate":
        data["sessions"][1] = a
    elif kind in {"owner", "policy", "script", "carry"}:
        for name in ("shortlist", "entry", "managed"):
            r = b[name]
            if kind == "owner":
                r["limits"]["population_id"] += "-changed"
            elif kind == "policy":
                r["entry_policy"]["max_horizon_seconds"] = 1799
            elif kind == "script":
                r["script"]["decisions"][0]["delay_seconds"] = 2
            else:
                r["entry_policy"]["max_carry_horizon_seconds"] = 86400
    elif kind in {"source", "declaration"}:
        # A changed header must be resealed, even when all arms agree.
        h = req.sessions[1].baseline.tape.header
        if kind == "declaration":
            h = h.model_copy(update={"declared_at": h.declared_at - timedelta(seconds=1)})
        else:
            h = h.model_copy(update={"experiment_id": "changed-experiment"})
        t = record(
            tmp_path / "changed.tape",
            h,
            [(e.recorded_at, e.kind, e.frame) for e in req.sessions[1].baseline.tape.events],
        )
        for r in b.values():
            if isinstance(r, dict):
                r["tape"] = t.model_dump(mode="json")
    elif kind == "action":
        for name in ("baseline", "shortlist", "entry", "managed"):
            b[name]["watch_actions"][-1]["key"] = a[name]["watch_actions"][-1]["key"]
    elif kind == "settlement-time":
        data["settlements"][0]["receipt"]["occurred_at"] = a["baseline"]["tape"]["header"][
            "opens_at"
        ]
    elif kind == "settlement-duplicate":
        data["settlements"].append(data["settlements"][0])
    else:
        for s in data["sessions"]:
            for name in ("shortlist", "entry", "managed"):
                s[name]["script"]["decisions"][0]["cycle_key"] = "degen:1"
    with pytest.raises(ValueError):
        ScopeSeries.model_validate(data)
    assert not (tmp_path / "run").exists()


@pytest.fixture(scope="module")
def complete(tmp_path_factory):
    root = tmp_path_factory.mktemp("scope-series")
    req = request(root)
    report = asyncio.run(run_scope_series(req, root / "run"))
    bundle = json.loads((root / "run/series.json").read_text())
    return root, req, report, bundle


def test_native_series_retains_cash_settlements_costs_and_original_terms(complete):
    root, req, report, bundle = complete
    assert report["status"] == "COMPLETE_FLAT_SERIES", report
    assert report["economic_conclusion"] == "INCONCLUSIVE"
    assert report["spy_session_compounded_price_return"] is None
    assert report["net_return_difference_vs_spy"] == dict.fromkeys("ABCD")
    first, later = report["sessions"]
    for arm in "ABCD":
        a, b = first["accounts"][arm], later["accounts"][arm]
        assert b["opening"] == a["closing"]
        assert len(a["native"]["orders"]) == 2
        assert len(b["native"]["orders"]) == 4
        assert Decimal(b["native"]["execution_fees"]) == 2 * Decimal(a["native"]["execution_fees"])
        assert Decimal(b["native"]["model_costs"]["known_cost"]) == 2 * Decimal(
            a["native"]["model_costs"]["known_cost"]
        )
        assert Decimal(b["native"]["host_cost"]) == Decimal(".04")
        assert a["native"]["loss_control"]["state"]["consumed_entries"] == 1
        assert b["native"]["loss_control"]["state"]["consumed_entries"] == 2
        assert b["native"]["loss_control"]["state"]["locked"] is True
        receipt = json.loads(
            bundle["boundaries"][1][arm]["evidence"]["execution_option_receipts"][0][1]
        )
        assert receipt["cash_change"] == "1" and receipt["sequence"] == 3
        assert sum(
            Decimal(r["accounts"][arm]["net_after_all_costs"]) for r in (first, later)
        ) == Decimal(report["cumulative_net_after_all_costs"][arm])
        assert (
            later["boundaries"][arm]["previous_export_hash"]
            == first["boundaries"][arm]["export_hash"]
        )
        path = (
            root
            / "run"
            / arm
            / "sessions"
            / (req.sessions[0].baseline.tape.header.session_key + ".db")
        )
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 2
        with sqlite3.connect(root / "run" / arm / "options.db") as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 4
        # All receipts still point to original per-session protection, never next-day terms.
        intents = [
            json.loads(r[3]) for r in bundle["boundaries"][1][arm]["evidence"]["execution_orders"]
        ]
        buys = [i for i in intents if i["side"] == "BUY"]
        for i, s in zip(buys, req.sessions, strict=True):
            assert (
                datetime.fromisoformat(i["exit_at"])
                == s.baseline.tape.header.scope.session.protect_at
            )
    assert verify_scope_series(bundle, bundle["series_hash"])["report"] == report
    with pytest.raises(FileExistsError):
        asyncio.run(run_scope_series(req, root / "run"))


@pytest.mark.parametrize(
    "kind", ["missing", "reordered", "swapped", "totals", "allocation", "enrollment"]
)
def test_portable_series_rejects_rehashed_changes(complete, kind):
    _, _, _, saved = complete
    b = copy.deepcopy(saved)
    if kind == "missing":
        b["boundaries"].pop()
    elif kind == "reordered":
        b["boundaries"].reverse()
    elif kind == "swapped":
        b["boundaries"][1]["B"] = b["boundaries"][1]["C"]
    elif kind == "totals":
        b["report"]["net_difference_vs_a"]["B"] = "999"
    else:
        native = b["boundaries"][1]["B"]
        if kind == "allocation":
            native["report"]["host_cost"] = "0"
        else:
            rows = native["evidence"]["execution_option_strategy"]
            config = json.loads(rows[0][1])
            config["scope_replay"]["request_hash"] = "a" * 64
            rows[0][1] = json.dumps(config)
        native["export_hash"] = fingerprint({k: v for k, v in native.items() if k != "export_hash"})
    b["series_hash"] = fingerprint({k: v for k, v in b.items() if k != "series_hash"})
    with pytest.raises(ValueError):
        verify_scope_series(b, b["series_hash"])


@pytest.mark.parametrize(
    "table",
    [
        "execution_events",
        "execution_model_calls",
        "execution_fills",
        "execution_option_opportunities",
        "execution_option_strategy",
        "execution_option_scope_watch_actions",
        "execution_orders",
        "execution_control",
    ],
)
def test_continuity_cannot_rewrite_prior_native_evidence(complete, table):
    _, _, _, bundle = complete
    earlier = bundle["boundaries"][0]["D"]
    later = copy.deepcopy(bundle["boundaries"][1]["D"])
    later["evidence"][table][0][1] = "changed"
    with pytest.raises(ValueError):
        _continuity(earlier, later)


def test_unknown_b_cost_and_earlier_operating_cost_remain_unknown(tmp_path):
    req = request(tmp_path, unknown=True, missing_cost=True)
    report = asyncio.run(run_scope_series(req, tmp_path / "run"))
    assert not report["comparison_complete"]
    assert report["net_difference_vs_a"] == dict.fromkeys("BCD")
    for row in report["sessions"]:
        b = row["accounts"]["B"]["native"]
        assert b["model_costs"]["unknown_calls"] == 1
        assert b["orders"] == [] and b["net_after_all_costs"] is None
        for arm in "ACD":
            a = row["accounts"][arm]["native"]
            assert a["model_costs"]["unknown_calls"] == 0
            assert a["host_cost"] is None and "HOST_COST_UNKNOWN" in a["reasons"]
    bundle = json.loads((tmp_path / "run/series.json").read_text())
    assert verify_scope_series(bundle, bundle["series_hash"])["report"] == report


def test_interrupted_series_retains_evidence_and_cannot_resume(tmp_path, monkeypatch):
    import app.options.scope_series as module

    req = request(tmp_path)

    async def interrupted(self):
        raise RuntimeError("fixture interruption")

    monkeypatch.setattr(module._ScopeReplay, "run", interrupted)
    with pytest.raises(RuntimeError, match="fixture interruption"):
        asyncio.run(run_scope_series(req, tmp_path / "run"))
    assert (tmp_path / "run/A/options.db").exists()
    assert (tmp_path / "run/inputs.json").exists()
    assert json.loads((tmp_path / "run/interrupted.json").read_text())["completed_boundaries"] == [
        [],
        [],
    ]
    assert not (tmp_path / "run/series.json").exists()
    with pytest.raises(FileExistsError):
        asyncio.run(run_scope_series(req, tmp_path / "run"))


def test_one_session_enrollment_keeps_its_serialization():
    from app.options.scope_replay_enrollment import ScopeReplayEnrollment, parse_enrollment

    value = {
        "version": "scope-native-tape-model-v1",
        "tape_hash": "a" * 64,
        "request_hash": "b" * 64,
        "script_hash": "c" * 64,
    }
    assert type(parse_enrollment(value)) is ScopeReplayEnrollment
    assert parse_enrollment(value).model_dump(mode="json") == value


def test_series_requires_all_declared_boundaries(complete):
    _, req, _, bundle = complete
    with pytest.raises(ValueError, match="Every declared"):
        series_report(req, bundle["boundaries"][:1])


@pytest.mark.parametrize("kind", ["complete", "missing", "incomplete", "delayed", "outside"])
def test_spy_requires_complete_same_session_endpoints(tmp_path, kind):
    from test_option_scope_market_tape import inputs

    from app.options.models import UnderlyingQuote
    from app.options.scope_series import _spy

    h, _ = inputs()
    frames = []
    for when, price in ((h.opens_at, "100"), (h.closes_at, "101")):
        if kind == "missing" and when == h.closes_at:
            continue
        q = UnderlyingQuote(
            symbol="SPY",
            source=h.limits.underlying_source,
            source_at=when - (timedelta(seconds=6) if kind == "delayed" else timedelta()),
            received_at=when,
            complete=kind != "incomplete",
            entitlement="REALTIME",
            bid=price,
            ask=price,
        )
        if kind == "outside" and when == h.opens_at:
            when += timedelta(seconds=6)
            q = q.model_copy(update={"source_at": when, "received_at": when})
        frames.append((when, "MARKET", DegenFrame(underlyings=(q,))))
    tape = record(tmp_path / "spy.tape", h, frames)
    assert _spy(tape) == (Decimal(".01") if kind == "complete" else None)


def test_backdated_new_audit_event_cannot_move_prior_economics(complete):
    _, _, _, bundle = complete
    earlier = bundle["boundaries"][0]["A"]
    later = copy.deepcopy(bundle["boundaries"][1]["A"])
    index = len(earlier["evidence"]["execution_events"])
    later["evidence"]["execution_events"][index][1] = "2026-10-09T13:30:00Z"
    with pytest.raises(ValueError, match="predates"):
        _continuity(earlier, later)


@pytest.mark.parametrize("kind", ["duplicate", "single", "wrong-script", "legacy-adapter"])
def test_series_model_requires_exact_full_enrollment(kind):
    from app.options.replay_model import ReplayModel, ReplayScript
    from app.options.scope_replay_enrollment import ScopeSeriesEnrollment, validate_adapter
    from app.options.scope_replay_model import ScopeReplayModel, ScopeReplayScript

    script = ScopeReplayScript(arm="C", decisions=())
    data = {
        "tape_hashes": ("a" * 64, "b" * 64),
        "request_hash": "c" * 64,
        "script_hash": fingerprint(script),
    }
    if kind == "duplicate":
        data["tape_hashes"] = ("a" * 64,) * 2
    elif kind == "single":
        data["tape_hashes"] = ("a" * 64,)
    elif kind == "wrong-script":
        data["script_hash"] = "d" * 64
    adapter = (
        ReplayModel(ReplayScript(arm="C", decisions=()))
        if kind == "legacy-adapter"
        else ScopeReplayModel(script)
    )
    with pytest.raises(ValueError):
        validate_adapter(ScopeSeriesEnrollment(**data), adapter)
