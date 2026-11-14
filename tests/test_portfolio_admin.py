"""Authenticated web review -> signed file inbox -> native revision-bound application."""

from fastapi.testclient import TestClient
from test_portfolio_controls import owned

from app.options.operator import OptionsControl
from app.options.operator_inbox import CommandInbox
from app.web.options import create_options_app


def test_dashboard_control_requires_auth_review_and_native_owner(tmp_path):
    from test_mixed_native_owner import NOW

    with owned(tmp_path) as (e, _):
        password = tmp_path / "password"
        password.write_text("offline-dashboard-password-123")
        password.chmod(0o600)
        key_file = tmp_path / "operator.key"
        key = b"a" * 32
        key_file.write_text(key.hex())
        key_file.chmod(0o600)
        for name in ("operator-inbox", "operator-receipts"):
            (tmp_path / name).mkdir(mode=0o700)
        OptionsControl.enroll(e, key, now=NOW)
        app = create_options_app(
            e.journal.path,
            e.limits.population_id,
            password,
            mixed=True,
            operator_key_file=key_file,
            clock=lambda: NOW,
        )
        client = TestClient(app)
        assert client.get("/admin/review").status_code == 401
        client.auth = ("trader", password.read_text())
        page = client.get("/")
        assert page.status_code == 200 and 'id="admin-dialog"' in page.text
        review = client.get("/admin/review").json()["review"]
        payload = {"review": review, "max_plays": 1, "reason": "Offline limit test"}
        assert client.post("/admin/max-plays", json=payload).status_code == 403
        headers = {"X-Portfolio-Review": "1"}
        assert (
            client.post(
                "/admin/max-plays",
                json=payload,
                headers={**headers, "Origin": "https://foreign.example"},
            ).status_code
            == 403
        )
        for value in (3, -1, "1", True):
            assert (
                client.post(
                    "/admin/max-plays", json={**payload, "max_plays": value}, headers=headers
                ).status_code
                == 422
            )
        response = client.post("/admin/max-plays", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "QUEUED"
        with e.journal.read() as db:
            assert (
                db.execute("SELECT limit_value FROM execution_portfolio_control").fetchone()[0] == 2
            )
        assert CommandInbox(e, key_file).poll(now=NOW) is None
        receipt = client.get("/admin/receipts/" + result["command_id"]).json()["result"]
        assert receipt["status"] == "APPLIED" and receipt["max_plays"] == 1
        assert client.post("/admin/max-plays", json=payload, headers=headers).status_code == 409
        with e.journal.read() as db:
            assert (
                db.execute("SELECT limit_value FROM execution_portfolio_control").fetchone()[0] == 1
            )


def test_unconfigured_observer_has_no_mutating_controls(tmp_path):
    from test_mixed_native_owner import NOW

    with owned(tmp_path) as (e, _):
        password = tmp_path / "password"
        password.write_text("offline-dashboard-password-123")
        password.chmod(0o600)
        client = TestClient(
            create_options_app(
                e.journal.path, e.limits.population_id, password, mixed=True, clock=lambda: NOW
            )
        )
        client.auth = ("trader", password.read_text())
        assert 'id="admin-dialog"' not in client.get("/").text
        assert client.get("/admin/review").status_code == 404
