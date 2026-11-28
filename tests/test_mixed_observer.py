"""Read-only mixed desk verification using native fixture ownership and receipts."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from test_mixed_native_owner import NOW, close, enter, owned_mixed
from test_option_observer import PASSWORD, digest

from app.mixed.observer import MixedObserver, history_chart
from app.options.observer import OptionObserver
from app.web.options import create_options_app, templates


def view(engine, at=NOW, **kwargs):
    return MixedObserver(engine.journal.path, engine.limits.population_id, clock=lambda: at).report(
        **kwargs
    )


def render(data):
    return templates.env.get_template("mixed_desk.html").render(data=data, auto_refresh=False)


def test_explicit_mixed_flat_read_is_complete_and_does_not_attach_owner(tmp_path, monkeypatch):
    with owned_mixed(tmp_path) as (e, v):
        paths = [e.journal.path, v.path]
        before = digest(paths)
        monkeypatch.setattr(type(e), "open", lambda *a, **k: pytest.fail("Observer attached owner"))
        data = view(e)
        assert data["status"] == "OK", data
        assert data["accounting"] == "VERIFIED", data
        assert data["equity"] == data["cash"] == "1000"
        assert data["points"][0]["equity"] == "1000"
        assert (
            OptionObserver(e.journal.path, e.limits.population_id, clock=lambda: NOW).report()[
                "status"
            ]
            == "UNAVAILABLE"
        )
        assert digest(paths) == before
        html = render(data)
        assert "LIVE DISABLED" in html and "No open position recorded" in html
        assert 'role="img"' in html


@pytest.mark.parametrize("quantity", ["1", "2"])
def test_stock_partial_and_complete_fills_retain_original_protection(tmp_path, quantity):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v, quantity=quantity)
        before = digest([e.journal.path, v.path])
        data = view(e, at)
        assert data["accounting"] == "VERIFIED", data
        p = data["position"]
        assert p["asset"] == "STOCK" and p["quantity"] == quantity
        assert p["entry"] == entry.model_dump(mode="json")
        assert p["original_stop"] == str(entry.original_invalidation)
        assert p["targets"][0]["underlying_price"] == str(entry.original_target)
        assert data["fill_count"] == 1 and data["fills"][0]["quantity"] == quantity
        assert data["points"][-1]["equity"] is None
        assert data["equity"] is None if quantity == "1" else data["equity"] is not None
        assert digest([e.journal.path, v.path]) == before
        assert "Reaching a target does not confirm a sale" in render(data)


def test_stale_owned_mark_is_withheld_without_losing_thesis(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        data = view(e, at + timedelta(minutes=5))
        assert data["accounting"] == "VERIFIED"
        assert data["health"] == "STALE" and data["equity"] is None
        assert data["position"]["mark"] is None and data["position"]["gross_unrealized"] is None
        assert data["position"]["thesis"] == entry.thesis
        assert "stale or missing" in render(data)


def test_roundtrip_history_has_open_gap_and_exact_full_cost_close(tmp_path):
    with owned_mixed(
        tmp_path, daily_host_cost="1", daily_data_cost=".5", daily_operating_cost=".25"
    ) as (e, v):
        entry, at = enter(e, v)
        _, at = close(e, v, entry, at + timedelta(seconds=1))
        data = view(e, at)
        assert data["position"] is None
        assert data["cash"] == "1003.76"
        assert Decimal(data["known_cost"]) == Decimal("1.75")
        assert Decimal(data["equity"]) == Decimal("1002.01")
        assert data["points"][-1]["equity"] == data["equity"]
        assert any(p["equity"] is None for p in data["points"])
        assert len(data["chart"]["segments"]) == 2
        assert data["fill_count"] == 2


def test_unknown_allocation_suppresses_equity_not_cash(tmp_path):
    with owned_mixed(tmp_path, daily_host_cost=None) as (e, _):
        data = view(e)
        assert data["cash"] == "1000" and data["equity"] is None
        assert len(data["unknown_costs"]) == 1
        assert data["chart"] is None
        assert "Unknown" in render(data)


@pytest.mark.parametrize("damage", ["orphan", "ledger", "missing_snapshot_order"])
def test_incomplete_native_coverage_withholds_balances_and_authoritative_fills(tmp_path, damage):
    with owned_mixed(tmp_path) as (e, v):
        _, at = enter(e, v)
        with e.journal.write() as db:
            if damage == "orphan":
                row = db.execute("SELECT * FROM execution_stock_fills").fetchone()
                payload = json.loads(row["payload"])
                payload["fill_id"] = "orphan"
                db.execute(
                    "INSERT INTO execution_stock_fills VALUES(?,?,?)",
                    ("orphan", row["client_id"], json.dumps(payload)),
                )
            elif damage == "ledger":
                db.execute(
                    "UPDATE execution_control SET ledger_json=json_set(ledger_json,'$.cash','1')"
                )
            else:
                db.execute(
                    "UPDATE execution_control SET snapshot_json=json_set(snapshot_json,'$.stock_orders',json('[]'))"
                )
        data = view(e, at)
        if damage == "ledger":
            assert data["status"] == "UNAVAILABLE" and "cash" not in data
            return
        assert data["accounting"] == "UNAVAILABLE", data
        assert data["cash"] is None and data["equity"] is None and data["fill_count"] is None
        assert data["position"] is None and data["orders"]
        assert "Balances, positions and fill totals are unavailable until checked" in render(data)


@pytest.mark.parametrize("mode", ["HOLD", "UNKNOWN", "ENTER"])
def test_paid_proposal_cost_and_actual_attempt_are_separate(tmp_path, monkeypatch, mode):
    from test_mixed_entry import owner
    from test_mixed_selection import stock_frame

    with owner(tmp_path, monkeypatch, mode=mode) as (c, _v, times, _):
        asyncio.run(c.cycle(stock_frame()))
        data = view(c.engine, times[0])
        assert data["status"] == "OK", data
        assert data["decisions"], data
        if mode == "ENTER":
            assert data["orders"] and data["orders"][0]["attempted_at"]
            assert data["fill_count"] is None  # No complete post-attempt snapshot yet.
            assert Decimal(data["known_cost"]) > 0
            assert data["decisions"][0]["proposal"]["action"] == "ENTER"
        else:
            assert data["orders"] == [] and data["fill_count"] == 0
            assert data["decisions"][0]["proposal"]["action"] == "HOLD"
        if mode == "UNKNOWN":
            assert data["equity"] is None and data["unknown_costs"]
        html = render(data)
        for label in ("01 Proposal", "02 Approval", "03 Attempt", "04 Fills"):
            assert label in html


@pytest.mark.parametrize("choice", ["OPTION", "SCOPE"])
def test_mixed_option_card_preserves_exact_contract_floors_and_original_targets(
    tmp_path, monkeypatch, choice
):
    from test_mixed_entry import scope_owner
    from test_mixed_native_owner import changed
    from test_option_execution import intent_for

    with scope_owner(tmp_path, monkeypatch, choice) as (c, v, times, f):
        out = asyncio.run(c.cycle(f))
        entry = intent_for(c.engine, out["client_id"])
        q, u = (
            (f.scope.frame.quote, f.scope.underlying)
            if choice == "SCOPE"
            else (f.quotes[0], f.underlyings[0])
        )
        q = changed(q, source_at=times[0], received_at=times[0])
        u = changed(u, source_at=times[0], received_at=times[0])
        v.fill(entry, entry.quantity, q, times[0], fill_id="observer-option", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        data = view(c.engine, times[0])
        assert data["status"] == "OK", data
        assert data["position"]["asset"] == "OPTION", data
        assert (
            data["position"]["details"]["contract"]["contract_id"]
            == entry.instrument.contract.contract_id
        )
        assert data["position"]["thesis"] == entry.thesis
        assert data["position"]["targets"] == (
            entry.target_exit_schedule.model_dump(mode="json")["steps"]
            if entry.target_exit_schedule
            else []
        )
        assert data["fill_count"] == 1
        assert "Original protection and terms" in render(data)
        assert "Not recorded" in render(data)
        assert data["orders"][0]["origin"] != "UNKNOWN"
        assert data["orders"][0]["origin"] != "NATIVE"


def test_http_mixed_opt_in_keeps_auth_and_get_only_reads(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        key = tmp_path / "key"
        key.write_text(PASSWORD)
        key.chmod(0o600)
        app = create_options_app(
            e.journal.path, e.limits.population_id, key, clock=lambda: NOW, mixed=True
        )
        client = TestClient(app)
        assert client.get("/api/mixed").status_code == 401
        client.auth = ("trader", PASSWORD)
        before = digest([e.journal.path, v.path])
        assert client.get("/").status_code == 200
        assert client.get("/api/mixed").json()["mode"] == "MIXED_PAPER_FIXTURE"
        assert client.get("/api/options").status_code == 404
        assert client.post("/api/mixed").status_code == 405
        assert client.get("/?family=SWING").status_code == 422
        assert digest([e.journal.path, v.path]) == before
        with pytest.raises(ValueError):
            create_options_app(
                e.journal.path, e.limits.population_id, key, mixed=True, comparison_file="/tmp/old"
            )


def test_chart_never_connects_across_missing_equity():
    chart = history_chart(
        [{"at": str(i), "equity": v} for i, v in enumerate(["1000", None, "900", "950"])]
    )
    assert len(chart["segments"]) == 2 and len(chart["dots"]) == 3


def test_historical_orphan_coverage_cannot_draw_a_flat_equity_point(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        _, at = close(e, v, entry, at + timedelta(seconds=1))
        with e.journal.write() as db:
            db.execute(
                "UPDATE execution_snapshots SET payload=json_set(payload,'$.stock_orders',json('[]')) WHERE rowid=(SELECT max(rowid) FROM execution_snapshots)"
            )
        data = view(e, at)
        assert data["accounting"] == "VERIFIED"
        assert data["equity"] == "1003.76"
        assert data["points"][-1]["equity"] is None


def test_native_latched_exit_and_tightened_stop_are_not_model_proposals(tmp_path):
    from test_mixed_venue import q

    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        e.tighten_stock_invalidation("95", q(entry, at), now=at)
        e.assess_stock(q(entry, at, bid="120", ask="120.01"), now=at)
        data = view(e, at)
        assert data["position"]["active_stop"] == "95"
        assert data["position"]["original_stop"] == str(entry.original_invalidation)
        assert data["position"]["exit_reason"] == "STOCK_TARGET"
        assert data["fill_count"] == 1  # Target touch did not create a sale.
        assert "STOCK_TARGET" in render(data)


def test_rail_separates_premium_from_underlying_and_groups_collisions():
    from app.web.trade_rail import trade_rail

    p = {
        "asset": "OPTION",
        "original_stop": "99",
        "active_stop": "99.001",
        "targets": [{"underlying_price": "101"}],
        "details": {
            "quote": {"bid": ".25"},
            "entry_underlying_reference": {"status": "BLOCKED", "reference": None},
        },
    }
    rail = trade_rail(p)
    assert len(rail) == 2
    assert len(rail[0]["labels"]) == 2
    assert all(".25" not in label and "Entry" not in label for g in rail for label in g["labels"])


def test_stock_stale_rail_labels_last_bid_and_never_marks_target_filled(tmp_path):
    from app.web.trade_rail import trade_rail

    with owned_mixed(tmp_path) as (e, v):
        _, at = enter(e, v)
        p = view(e, at + timedelta(minutes=5))["position"]
        labels = " ".join(label for group in trade_rail(p) for label in group["labels"])
        assert "Last bid" in labels and "T1" in labels and "filled" not in labels


def test_historical_coverage_requires_attempts_even_without_fills(tmp_path):
    from types import SimpleNamespace

    from app.mixed.observer import snapshot_prefix
    from app.options.lifecycle import OptionVenueSnapshot

    with owned_mixed(tmp_path) as (e, _):
        with e.journal.read() as db:
            raw = db.execute("SELECT snapshot_json FROM execution_control").fetchone()[0]
        snap = OptionVenueSnapshot.model_validate_json(raw)
        captured = SimpleNamespace(events=())
        # A retained attempt before this clock cannot disappear merely because it
        # has no fill yet. Omitting it must create a chart gap, not flat equity.
        orders = [
            {
                "intent": {"client_id": "pending"},
                "attempted_at": (snap.captured_at - timedelta(seconds=1)).isoformat(),
            }
        ]
        assert snapshot_prefix(snap, captured, [])
        assert not snapshot_prefix(snap, captured, orders)
