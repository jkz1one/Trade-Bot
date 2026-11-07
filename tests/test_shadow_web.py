import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.domain.models import Action
from app.storage.models import DecisionCycleRow, ShadowCycleEvidenceRow
from app.storage.repository import Repository
from app.web.shadow import create_shadow_app
from app.web.shadow_data import read_only_engine
from tests.test_shadow_evidence import save_evidence
from tests.test_shadow_outcomes import START, save_at

PASSWORD = "observer-test-password-that-is-not-a-real-secret"


@pytest.fixture
def observer_settings(settings, tmp_path):
    password = tmp_path / "dashboard-password"
    password.write_text(PASSWORD)
    return Settings(
        mode="SHADOW", robinhood_db_url=settings.db_url, dashboard_password_file=str(password)
    )


def client_for(settings, now=START):
    client = TestClient(create_shadow_app(settings, clock=lambda: now))
    client.auth = ("trader", PASSWORD)
    return client


@pytest.mark.parametrize("mode, live", [("PAPER", False), ("LIVE", False), ("SHADOW", True)])
def test_observer_requires_shadow_with_live_disabled(observer_settings, mode, live):
    with pytest.raises(RuntimeError, match="SHADOW with LIVE disabled"):
        create_shadow_app(observer_settings.model_copy(update={"mode": mode, "live_enabled": live}))


@pytest.mark.parametrize("password", [None, "missing", "short", "a" * 24 + "\n" + "b" * 24])
def test_authentication_has_no_default_or_weak_password(observer_settings, password):
    if password is None:
        observer_settings.dashboard_password_file = None
    elif password == "missing":
        Path(observer_settings.dashboard_password_file).unlink()
    else:
        Path(observer_settings.dashboard_password_file).write_text(password)
    with pytest.raises(RuntimeError, match="Dashboard password"):
        create_shadow_app(observer_settings)


def test_unauthenticated_reads_do_not_touch_database(observer_settings, monkeypatch):
    from app.web import shadow

    def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized read reached stored evidence")

    monkeypatch.setattr(shadow, "stored_snapshot", forbidden)
    client = client_for(observer_settings)
    for path in ("/", "/api/shadow"):
        for auth in (None, ("other", PASSWORD), ("trader", "wrong")):
            response = client.get(path, auth=auth)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == 'Basic realm="Trade-Bot"'
            assert response.headers["cache-control"] == "no-store"
    assert client.get("/healthz", auth=None).json() == {
        "status": "OK",
        "service": "shadow-observer",
    }
    assert not Path(observer_settings.robinhood_db_url.removeprefix("sqlite:///")).exists()


def test_password_rotation_and_missing_secret_fail_closed(observer_settings):
    client = client_for(observer_settings)
    assert client.get("/").status_code == 200
    path = Path(observer_settings.dashboard_password_file)
    changed = "replacement-observer-password-long-enough"
    path.write_text(changed)
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("trader", changed)).status_code == 200
    path.unlink()
    response = client.get("/", auth=("trader", changed))
    assert response.status_code == 503
    assert str(path) not in response.text


def test_missing_database_is_empty_and_never_bootstrapped(observer_settings):
    client = client_for(observer_settings)
    response = client.get("/api/shadow")
    assert response.json()["reason"] == "DATABASE_NOT_CREATED"
    assert response.json()["network_calls"] is False
    html = client.get("/")
    assert html.status_code == 200 and "Waiting for history" in html.text
    assert not Path(observer_settings.robinhood_db_url.removeprefix("sqlite:///")).exists()


@pytest.mark.parametrize("corruption", ["old_schema", "bad_database", "bad_packet"])
def test_unavailable_history_is_sanitized_without_database_repair(
    observer_settings,
    repo,
    corruption,
):
    path = Path(observer_settings.robinhood_db_url.removeprefix("sqlite:///"))
    if corruption == "old_schema":
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE shadow_cycle_evidence")
    elif corruption == "bad_database":
        path.write_bytes(b"private-database-value-not-sqlite")
    else:
        cycle_id = save_at(repo)
        with repo.session_factory.begin() as session:
            session.get(DecisionCycleRow, cycle_id).packet_json = "private-malformed-json"
    before = path.read_bytes()
    client = client_for(observer_settings)
    for route in ("/", "/api/shadow"):
        response = client.get(route)
        assert response.status_code == 503
        assert "private-" not in response.text and str(path) not in response.text
    assert path.read_bytes() == before


def test_read_only_connection_rejects_writes_and_other_database_types(observer_settings, repo):
    _, engine = read_only_engine(observer_settings.robinhood_db_url)
    with engine.connect() as connection:
        for statement in ("CREATE TABLE forbidden (x INTEGER)", "DELETE FROM decision_cycles"):
            with pytest.raises(OperationalError, match="readonly"):
                connection.exec_driver_sql(statement)
    engine.dispose()
    for url in ("sqlite:///:memory:", "sqlite://", "postgresql://localhost/shadow"):
        with pytest.raises(ValueError, match="file-backed"):
            read_only_engine(url)


def test_dashboard_has_no_mutation_routes_or_api_docs(observer_settings, repo):
    client = client_for(observer_settings)
    for path in ("/cycle", "/halt", "/resume", "/review", "/api/shadow", "/"):
        assert client.post(path).status_code in (404, 405)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert repo.recent_cycles() == []


def test_dashboard_reads_no_broker_model_or_credentials(observer_settings, repo, monkeypatch):
    from app.agent.trader import OpenAIAgentsTrader
    from app.robinhood import cli
    from app.storage import db

    def forbidden(*args, **kwargs):
        raise AssertionError("Observer attempted a broker/model/bootstrap call")

    monkeypatch.setattr(cli, "_connection", forbidden)
    monkeypatch.setattr(OpenAIAgentsTrader, "decide", forbidden)
    monkeypatch.setattr(db, "init_db", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    save_at(repo, action=Action.HOLD)
    client = client_for(observer_settings)
    assert client.get("/api/shadow").json()["network_calls"] is False
    assert "SHADOW observer" in client.get("/").text


def test_projection_escapes_model_text_and_omits_private_broker_fields(observer_settings, repo):
    cycle_id = save_at(repo)
    with repo.session_factory.begin() as session:
        row = session.get(DecisionCycleRow, cycle_id)
        decision = json.loads(row.decision_json)
        decision["thesis"] = '<script>alert("model")</script>'
        row.decision_json = json.dumps(decision)
        execution = json.loads(row.execution_json)
        execution["broker_review"] = {
            "account_number": "private-broker-account",
            "url": "private-review-url",
        }
        execution["order_id"] = "private-order-id"
        row.execution_json = json.dumps(execution)
        packet = json.loads(row.packet_json)
        packet["account"]["working_orders"] = [{"account_id": "private-working-order"}]
        row.packet_json = json.dumps(packet)
        link = session.scalar(
            select(ShadowCycleEvidenceRow).where(ShadowCycleEvidenceRow.cycle_id == cycle_id)
        )
        link.reconciliation_json = json.dumps(
            {"reconciled": True, "reasons": [], "account_id": "private-reconciliation"}
        )
    path = Path(observer_settings.robinhood_db_url.removeprefix("sqlite:///"))
    original = path.read_bytes()
    client = client_for(observer_settings)
    api = client.get("/api/shadow")
    page = client.get("/")
    assert api.status_code == page.status_code == 200
    for secret in (
        "private-broker",
        "private-review",
        "private-working",
        "private-order",
        "private-reconciliation",
        PASSWORD,
        observer_settings.dashboard_password_file,
    ):
        assert secret not in api.text + page.text
    assert api.json()["latest"]["execution"]["review_completed"] is True
    assert '<script>alert("model")</script>' not in page.text
    assert "&lt;script&gt;" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "status, age, healthy",
    [
        ("RUNNING", 0, True),
        ("RUNNING", 90, True),
        ("RUNNING", 91, False),
        ("RUNNING", 90.5, False),
        ("RUNNING", -1, False),
        ("RUNNING", -0.5, False),
        ("HALTED", 0, False),
        ("STOPPED", 0, False),
    ],
)
def test_health_uses_worker_state_and_heartbeat_not_observer_readiness(
    observer_settings, repo, status, age, healthy
):
    repo.set_shadow_service_state(
        status,
        START,
        "release",
        {"status": "ERROR", "exit_code": 8, "private_url": "private-credential"},
    )
    client = client_for(observer_settings, START + timedelta(seconds=age))
    data = client.get("/api/shadow").json()
    assert data["worker_healthy"] is healthy
    assert data["heartbeat_age_seconds"] == age
    assert "private-credential" not in json.dumps(data)
    assert client.get("/healthz", auth=None).status_code == 200
    assert client.get("/").status_code == 200


def test_bounded_pagination_keeps_latest_independent_and_outcomes_on_source_page(
    observer_settings, repo
):
    source = save_at(repo, action=Action.HOLD)
    second = save_at(
        repo, START + timedelta(minutes=15), action=Action.HOLD, spy_bid=202, spy_ask="202.10"
    )
    latest = save_at(repo, START + timedelta(minutes=30), action=Action.HOLD)
    client = client_for(observer_settings, START + timedelta(minutes=31))
    first_page = client.get("/api/shadow?limit=2").json()
    assert [c["cycle_id"] for c in first_page["history"]["cycles"]] == [second, latest]
    assert {o["source_cycle_id"] for o in first_page["outcomes"]["outcomes"]} == {second, latest}
    assert first_page["page"] == {
        "limit": 2,
        "before": None,
        "has_older": True,
        "next_before": second,
    }
    older = client.get(f"/api/shadow?limit=2&before={second}").json()
    assert older["latest"]["cycle_id"] == latest
    assert [c["cycle_id"] for c in older["history"]["cycles"]] == [source]
    observed = next(o for o in older["outcomes"]["outcomes"] if o["status"] == "OBSERVED")
    assert observed["measurement_cycle_id"] == second
    assert "quotes" not in observed and "baseline" not in observed
    assert older["page"]["has_older"] is False
    assert 'http-equiv="refresh"' not in client.get(f"/?before={second}").text
    assert 'http-equiv="refresh"' not in client.get("/?refresh=false").text
    assert 'http-equiv="refresh"' in client.get("/").text
    assert "Mean excess vs SPY" in client.get(f"/?before={second}").text
    for query in ("limit=0", "limit=101", "before=0", "before=-1"):
        assert client.get("/api/shadow?" + query).status_code == 422


def test_unknown_usage_and_failure_hold_are_distinct_from_model_hold(observer_settings, repo):
    save_evidence(repo, paid=True)
    failed = save_evidence(repo, failed=True)
    stub = save_evidence(repo, stub=True)
    client = client_for(observer_settings)
    data = client.get("/api/shadow").json()
    assert [c["hold_origin"] for c in data["history"]["cycles"]] == [
        "MODEL",
        "AGENT_FAILURE",
        "DETERMINISTIC",
    ]
    assert data["history"]["usage_reported_cycle_count"] == 1
    assert data["history"]["agent_failure_count"] == 1
    assert data["latest"]["cycle_id"] == stub
    assert data["latest"]["evidence"]["model_usage"] is None
    assert data["strategy_pnl"] is None and data["economic_pnl"] is None
    assert "Unknown / not reported" in client.get("/").text
    assert failed < stub


def test_report_uses_one_committed_snapshot_while_worker_commits(
    observer_settings, repo, monkeypatch
):
    with repo.session_factory().bind.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    source = save_at(repo, action=Action.HOLD)
    original = Repository.shadow_service_state
    inserted = []

    def state_then_commit(self):
        result = original(self)
        if not inserted:
            inserted.append(save_at(repo, START + timedelta(minutes=15), action=Action.HOLD))
        return result

    monkeypatch.setattr(Repository, "shadow_service_state", state_then_commit)
    client = client_for(observer_settings)
    first = client.get("/api/shadow").json()
    assert first["latest"]["cycle_id"] == source
    assert first["history"]["cycle_count"] == 1
    assert first["outcomes"]["status_counts"] == {"PENDING": 2}
    assert Decimal(first["history"]["database_model_cost_total"]) == Decimal("0.00003")
    next_read = client.get("/api/shadow").json()
    assert next_read["latest"]["cycle_id"] == inserted[0]
    assert next_read["history"]["cycle_count"] == 2
    assert next_read["outcomes"]["status_counts"]["OBSERVED"] == 1


def test_active_claim_identity_is_visible_but_owner_token_is_private(observer_settings, repo):
    from app.robinhood.schedule import XNYSCalendar

    window = XNYSCalendar().current_window(START)
    assert repo.claim_shadow_slot(window, "private-claim-token", START)
    client = client_for(observer_settings)
    data = client.get("/api/shadow").json()
    assert data["active_slot"] == window.key
    assert data["slots"][0]["status"] == "CLAIMED"
    assert "private-claim-token" not in json.dumps(data) + client.get("/").text


def test_readers_and_worker_make_progress_with_default_sqlite_journal(observer_settings, repo):
    save_at(repo, action=Action.HOLD)
    client = client_for(observer_settings)
    barrier = Barrier(3)

    def read():
        barrier.wait(timeout=5)
        for _ in range(10):
            response = client.get("/api/shadow")
            assert response.status_code == 200
            data = response.json()
            count = data["history"]["cycle_count"]
            assert data["latest"]["cycle_id"] == data["history"]["cycles"][-1]["cycle_id"]
            assert data["history"]["usage_reported_cycle_count"] == count
            assert (
                Decimal(data["history"]["database_model_cost_total"]) == Decimal("0.00003") * count
            )

    def write():
        barrier.wait(timeout=5)
        for minute in range(1, 11):
            save_at(repo, START + timedelta(minutes=minute), action=Action.HOLD)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(read), pool.submit(read), pool.submit(write)]
        for future in futures:
            future.result(timeout=15)
    assert client.get("/api/shadow").json()["history"]["cycle_count"] == 11
