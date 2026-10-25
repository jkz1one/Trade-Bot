"""Stored stream and in-page snapshots retain native read-only authority."""

import copy
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from test_mixed_native_owner import NOW, enter, owned_mixed
from test_mixed_observer import render, view
from test_option_observer import PASSWORD, digest

from app.web.mixed_view import trade_summary
from app.web.options import create_options_app


def test_price_summary_uses_per_unit_basis_without_reviving_stale_pnl(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        _, at = enter(e, v)
        current = view(e, at)
        before = copy.deepcopy(current)
        card = trade_summary(current["position"])
        assert Decimal(card["average_entry"]) == 100
        assert card["bid"] == current["position"]["details"]["quote"]["bid"]
        assert current == before
        stale = view(e, at + timedelta(minutes=5))
        card = trade_summary(stale["position"])
        assert card["bid"] is not None and not card["usable"]
        assert (
            card["return_percent"] is None
            and stale["position"]["gross_unrealized"] is None
        )
        assert "Last-known bid" in render(stale)
        conflict = copy.deepcopy(current["position"])
        conflict["mark_status"] = "CONFLICTING"
        assert trade_summary(conflict)["bid"] is None
        conflict["mark_status"] = "STALE_OR_MISSING"
        conflict["details"]["quote"]["instrument"]["symbol"] = "QQQ"
        assert trade_summary(conflict)["bid"] is None


def test_option_average_premium_uses_multiplier_and_no_underlying_substitution():
    instrument = {"instrument_id": "exact-contract"}
    position = {
        "asset": "OPTION",
        "quantity": 2,
        "basis": "500",
        "mark_status": "STALE_OR_INVALID",
        "gross_unrealized": None,
        "entry": {"instrument": instrument},
        "details": {
            "contract": {"multiplier": 100},
            "quote": {"instrument": instrument, "bid": "2.4", "ask": "2.5"},
            "underlying": {"bid": "600", "ask": "600.01"},
        },
    }
    card = trade_summary(position)
    assert card["average_entry"] == "2.5" and card["bid"] == "2.4"
    assert card["underlying_bid"] == "600" and card["return_percent"] is None


def test_stream_is_recorded_bounded_and_read_only(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        _, at = enter(e, v)
        before = digest([e.journal.path, v.path])
        data = view(e, at)
        stream = data["stream"]
        assert 0 < len(stream) <= 80
        assert any(row["kind"] == "EVENT" for row in stream)
        quotes = [row for row in stream if row["kind"] == "QUOTE"]
        assert len(quotes) == 1
        assert datetime.fromisoformat(quotes[0]["at"]) == datetime.fromisoformat(
            data["position"]["quote_at"]
        )
        assert quotes[0]["bid"] == data["position"]["details"]["quote"]["bid"]
        assert 'data-panel="data-stream"' in render(data)
        assert digest([e.journal.path, v.path]) == before


def test_snapshot_authentication_and_native_changes_without_trading_reads(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        key = tmp_path / "key"
        key.write_text(PASSWORD)
        key.chmod(0o600)
        now = [NOW]
        app = create_options_app(
            e.journal.path,
            e.limits.population_id,
            key,
            mixed=True,
            clock=lambda: now[0],
        )
        with TestClient(app) as client:
            for route in ["/desk/snapshot", "/desk-live.js"]:
                assert client.get(route).status_code == 401
            client.auth = ("trader", PASSWORD)
            before = digest([e.journal.path, v.path])
            first = client.get("/desk/snapshot")
            assert first.status_code == 200 and "Verified flat" in first.json()["html"]
            assert 'data-update-mode="auto"' in first.json()["html"]
            assert "connect-src 'self'" in first.headers["content-security-policy"]
            assert digest([e.journal.path, v.path]) == before
            _, at = enter(e, v)
            now[0] = at
            before = digest([e.journal.path, v.path])
            second = client.get("/desk/snapshot").json()
            assert (
                "Average entry" in second["html"]
                and second["html"] != first.json()["html"]
            )
            assert (
                'data-update-mode="history"'
                in client.get("/desk/snapshot?before=1").json()["html"]
            )
            assert (
                'data-update-mode="paused"'
                in client.get("/desk/snapshot?refresh=false").json()["html"]
            )
            assert client.post("/desk/snapshot").status_code == 405
            assert client.get("/desk/snapshot?limit=101").status_code == 422
            assert client.get("/desk/snapshot?family=SWING").status_code == 422
            assert 'http-equiv="refresh"' not in client.get("/?refresh=true").text
            assert digest([e.journal.path, v.path]) == before
            key.unlink()
            assert client.get("/desk/snapshot").status_code == 503


def test_unavailable_snapshot_replaces_account_with_withheld_values(tmp_path):
    key = tmp_path / "key"
    key.write_text(PASSWORD)
    key.chmod(0o600)
    app = create_options_app(tmp_path / "missing.db", "mixed-pending", key, mixed=True)
    with TestClient(app) as client:
        client.auth = ("trader", PASSWORD)
        response = client.get("/desk/snapshot")
        assert response.status_code == 200 and response.json()["status"] == "EMPTY"
        assert "No PAPER account connected" in response.json()["html"]
        assert not (tmp_path / "missing.db").exists()
