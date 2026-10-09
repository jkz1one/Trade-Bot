"""Stored options observer proof: truthful uncertainty, immutable reads and no work."""

import asyncio
import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_degen_options import AT, frame, owned_strategy
from test_option_execution import intent_for
from test_option_judgment import owned_model, receipt_for

from app.options import judgment, observer
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution
from app.options.models import OptionProposal
from app.options.observer import OptionObserver
from app.web import options

PASSWORD = "fixture-observer-password-only-not-a-secret"


def app_for(c, path, *, clock=None):
    password = path / "observer.password"
    password.write_text(PASSWORD + "\n")
    password.chmod(0o600)
    app = options.create_options_app(
        c.engine.journal.path, c.engine.limits.population_id, password, clock=clock or c.clock
    )
    client = TestClient(app)
    client.auth = ("trader", PASSWORD)
    return client, password


def digest(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def seed_position(c, venue):
    f = frame()
    result = asyncio.run(c.cycle(f))
    assert result["status"] == "OPEN", result
    intent = intent_for(c.engine, result["client_id"])
    venue.fill(intent, intent.quantity, f.quotes[0], AT, fill_id="observer-fill")
    assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
    return intent


def add_frame(c, f, key="later"):
    with c.engine.journal.write() as db:
        db.execute(
            "INSERT INTO execution_option_opportunities VALUES(?, ?, ?, ?, 'COMPLETE', ?)",
            (
                key,
                "a" * 64,
                AT.isoformat(),
                f.model_dump_json(),
                json.dumps({"status": "HOLD", "reason": "FIXTURE_OBSERVATION"}),
            ),
        )


def test_missing_journal_never_creates_database_or_reports_zero(tmp_path):
    path = tmp_path / "missing.db"
    o = OptionObserver(path, "new-pop", clock=lambda: AT)
    assert o.report()["status"] == "EMPTY"
    assert "account" not in o.report()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("damage", ["relative", "blank_population", "memory"])
def test_explicit_file_population_binding_required(tmp_path, damage):
    with pytest.raises(ValueError):
        OptionObserver(
            "relative.db"
            if damage == "relative"
            else ":memory:"
            if damage == "memory"
            else tmp_path / "missing.db",
            " " if damage == "blank_population" else "population",
        )


@pytest.mark.parametrize(
    "damage",
    [
        "foreign_schema",
        "empty_file",
        "public",
        "symlink",
        "fifo",
        "oversize",
        "wrong_population",
        "bad_json",
        "wrong_snapshot",
    ],
)
def test_incompatible_or_unsafe_evidence_is_unavailable_without_adoption(
    tmp_path, monkeypatch, damage
):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        path = c.engine.journal.path
        population = c.engine.limits.population_id
        if damage == "foreign_schema":
            path = tmp_path / "foreign.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE trade_history(value)")
            path.chmod(0o600)
        elif damage == "empty_file":
            path = tmp_path / "empty.db"
            path.touch(mode=0o600)
        elif damage == "public":
            path.chmod(0o644)
        elif damage == "symlink":
            path = tmp_path / "link.db"
            path.symlink_to(c.engine.journal.path)
        elif damage == "fifo":
            path = tmp_path / "pipe"
            os.mkfifo(path, 0o600)
        elif damage == "oversize":
            monkeypatch.setattr(observer, "MAX_DATABASE_BYTES", 1)
        elif damage == "wrong_population":
            population = "another-population"
        elif damage == "bad_json":
            with c.engine.journal.write() as db:
                db.execute("UPDATE execution_control SET ledger_json='bad-json'")
        else:
            with c.engine.journal.write() as db:
                row = db.execute("SELECT snapshot_json FROM execution_control").fetchone()
                data = json.loads(row[0])
                data["population_id"] = "different"
                db.execute("UPDATE execution_control SET snapshot_json=?", (json.dumps(data),))
        before = path.lstat()
        result = OptionObserver(path, population, clock=lambda: AT).report()
        assert result["status"] == "UNAVAILABLE" and "account" not in result
        assert path.lstat().st_mode == before.st_mode
        if damage == "public":
            path.chmod(0o600)


def test_flat_report_is_stored_evidence_not_worker_or_authority_proof(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        data = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT
        ).report()
        assert data["status"] == "OK", data
        assert data["account"]["position_state"] == "FLAT" and data["position"] is None
        assert data["worker_status"] == "NOT_RECORDED"
        assert data["restore_authority"] == "NOT_CHECKED_BY_OBSERVER"
        assert data["execution_authority"] is data["network_calls"] is data["live_enabled"] is False
        assert data["release"] is None and data["economics"]["spy_return"] is None
        assert data["economics"]["all_costs_known"] is False
        assert data["strategy"]["families"]["SWING"] == "NOT_IMPLEMENTED"


@pytest.mark.parametrize(
    "offset,account_health,supervision",
    [
        (timedelta(seconds=10), "STALE", "FRESH"),
        (timedelta(seconds=20), "STALE", "STALE"),
        (timedelta(seconds=-1), "FUTURE", "FUTURE"),
    ],
)
def test_staleness_and_future_records_never_look_current(
    tmp_path, offset, account_health, supervision
):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        data = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT + offset
        ).report()
        assert data["account"]["health"] == account_health
        assert data["supervision"]["freshness"] == supervision
        assert data["account"]["cash"] == "1000"
        assert data["economics"]["equity_before_exit_costs"] is None
        assert data["account"]["position_state"] != "FLAT"


def test_pending_acceptance_is_not_fill_or_position_and_hides_equity(tmp_path):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        asyncio.run(c.cycle(frame()))
        data = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT
        ).report()
        assert data["account"]["position_state"] == "PENDING_OR_UNKNOWN"
        assert data["active_orders"] == 1 and data["position"] is None
        assert data["orders"][0]["status"] == "OPEN" and not data["fills"]
        assert data["economics"]["equity_before_exit_costs"] is None
        assert data["opportunities"][0]["candidates"][0]["contract"]["right"] == "CALL"


def test_fills_locked_position_management_and_decimal_marks_are_distinct(tmp_path):
    with owned_strategy(tmp_path) as (c, venue, _, _, _, _):
        intent = seed_position(c, venue)
        data = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT
        ).report()
        assert data["position"]["contract"]["contract_id"] == intent.instrument.contract.contract_id
        assert data["position"]["quantity"] == intent.quantity
        assert data["position"]["quote_status"] == "USABLE_STORED_BID"
        assert data["position"]["gross_bid_mark"] == "392.00"
        assert data["fills"][0]["quantity"] == intent.quantity and data["fills"][0]["fee"] == "3.60"
        assert (
            data["position"]["original_invalidation"] == data["position"]["tightened_invalidation"]
        )
        assert data["position"]["underlying"]["symbol"] == "SPY"
        assert data["economics"]["equity_before_exit_costs"] == "984.40"
        assert data["economics"]["spy_return"] is None


@pytest.mark.parametrize(
    "damage",
    [
        "stale",
        "future",
        "missing_bid",
        "small_size",
        "delayed",
        "incomplete",
        "conflict",
        "wrong_contract",
        "metadata",
    ],
)
def test_unusable_latest_quote_never_becomes_current_or_falls_back(tmp_path, damage):
    with owned_strategy(tmp_path) as (c, venue, _, _, _, _):
        seed_position(c, venue)
        f = frame()
        quote = f.quotes[0]
        later = AT + timedelta(seconds=1)
        changes = {"source_at": later, "received_at": later}
        if damage == "stale":
            changes = {"source_at": AT - timedelta(seconds=11), "received_at": later}
        elif damage == "future":
            changes = {
                "source_at": AT + timedelta(seconds=10),
                "received_at": AT + timedelta(seconds=10),
            }
        elif damage == "missing_bid":
            changes["bid"] = None
        elif damage == "small_size":
            changes["bid_size"] = 1
        elif damage == "delayed":
            changes["entitlement"] = "DELAYED"
        elif damage == "incomplete":
            changes["complete"] = False
        elif damage == "conflict":
            changes = {"bid": Decimal("1.1"), "ask": Decimal("1.2")}
        elif damage == "wrong_contract":
            changes["instrument"] = quote.instrument.model_copy(
                update={"contract": quote.instrument.contract.model_copy(update={"right": "PUT"})}
            )
        else:
            changes["instrument"] = quote.instrument.model_copy(update={"metadata_complete": False})
        quote = quote.model_copy(update=changes)
        add_frame(c, f.model_copy(update={"quotes": (quote,)}))
        data = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: later
        ).report()
        assert data["status"] == "OK", data
        assert data["position"]["gross_bid_mark"] is None
        assert data["economics"]["equity_before_exit_costs"] is None
        assert data["position"]["contract"]["right"] == "CALL"
        assert data["position"]["quote_status"] != "USABLE_STORED_BID"


def test_unknown_model_cost_keeps_cash_but_suppresses_net_economics(tmp_path):
    with owned_model(tmp_path) as (c, _, _, _):
        c.engine.begin_model_attempt("unknown", "a" * 64, now=AT)
        data = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT
        ).report()
        assert data["model"]["known_cost"] == "0" and data["model"]["unknown_calls"] == 1
        assert data["account"]["cash"] == "1000"
        assert data["economics"]["equity_after_known_model_cost_before_exit_costs"] is None
        assert "MODEL_COST_UNKNOWN" in data["entry"]["recorded_blockers"]


def test_known_cost_sums_once_and_does_not_expose_credentials_paths_or_packets(
    tmp_path, monkeypatch
):
    async def run(request, key):
        return receipt_for(request, action="HOLD")

    monkeypatch.setattr(judgment, "run_candidate_process", run)
    with owned_model(tmp_path) as (c, _, _, _):
        asyncio.run(c.cycle(frame()))
        o = OptionObserver(c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT)
        data = o.report()
        assert data["model"]["known_cost"] == "0.00015"
        assert data["economics"]["equity_after_known_model_cost_before_exit_costs"] == "999.99985"
        raw = json.dumps(data)
        for forbidden in (
            str(tmp_path),
            "model.key",
            "fixture-only",
            "resp-options",
            "model_request",
            "key_file",
            "venue_path",
            "account_id",
        ):
            assert forbidden not in raw
        assert data["opportunities"][0]["model_choice"]["action"] == "HOLD"
        assert o.report()["model"] == data["model"]


@pytest.mark.parametrize(
    "damage",
    ["model_capacity", "record_capacity", "response_capacity", "deadline", "incoherent_cost"],
)
def test_capacity_or_corruption_is_unavailable_without_partial_metrics(
    tmp_path, monkeypatch, damage
):
    with owned_model(tmp_path) as (c, _, _, _):
        if damage == "model_capacity":
            c.engine.begin_model_attempt("one", "a" * 64, now=AT)
            monkeypatch.setattr(observer, "MAX_MODEL_ROWS", 0)
        elif damage == "record_capacity":
            monkeypatch.setattr(observer, "MAX_RECORD_BYTES", 1)
        elif damage == "response_capacity":
            monkeypatch.setattr(observer, "MAX_REPORT_BYTES", 1)
        elif damage == "deadline":
            monkeypatch.setattr(observer, "READ_SECONDS", 0)
        else:
            from app.execution.economics import UsageEvidence

            c.engine.begin_model_attempt("one", "a" * 64, now=AT)
            c.engine.record_model_usage(
                "one",
                UsageEvidence(
                    request_id="resp", model="gpt-6-luna", input_tokens=1000, output_tokens=100
                ),
                OptionProposal(action="HOLD", thesis="Keep cash"),
                now=AT,
            )
            with c.engine.journal.write() as db:
                db.execute("UPDATE execution_model_calls SET cost='999'")
        result = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT
        ).report()
        assert result["status"] == "UNAVAILABLE" and "economics" not in result


def test_history_pagination_keeps_current_position_and_costs_independent(tmp_path):
    with owned_strategy(tmp_path) as (c, venue, _, _, _, _):
        seed_position(c, venue)
        for n in range(5):
            add_frame(c, frame(), key="history-" + str(n))
        o = OptionObserver(c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT)
        first = o.report(limit=2)
        second = o.report(limit=2, before=first["page"]["next_before"])
        assert first["page"]["has_older"] and second["page"]["has_older"]
        assert {r["id"] for r in first["opportunities"]}.isdisjoint(
            r["id"] for r in second["opportunities"]
        )
        assert second["position"] == first["position"] and second["model"] == first["model"]
        for family in ("SWING", "SCOPE"):
            report = o.report(family=family)
            assert not report["opportunities"] and not report["page"]["has_older"]
            assert report["strategy"]["families"][family] == "NOT_IMPLEMENTED"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"before": 0},
        {"before": True},
        {"family": "LIVE"},
    ],
)
def test_invalid_pages_are_rejected_before_database_access(tmp_path, kwargs):
    with pytest.raises(ValueError):
        OptionObserver(tmp_path / "missing.db", "population").report(**kwargs)
    assert not list(tmp_path.iterdir())


def test_single_snapshot_never_mixes_concurrent_halt_revision(tmp_path, monkeypatch):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        o = OptionObserver(c.engine.journal.path, c.engine.limits.population_id, clock=lambda: AT)
        original = o._orders
        ready = Event()

        def writer():
            with c.engine.journal.write() as db:
                c.engine._halt(db, "CONCURRENT_REVIEW", AT)
                ready.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            futures = []

            def orders(db):
                futures.append(pool.submit(writer))
                assert ready.wait(1)
                return original(db)

            monkeypatch.setattr(o, "_orders", orders)
            data = o.report()
            assert data["status"] == "OK" and not data["entry"]["halted"]
            monkeypatch.setattr(o, "_orders", original)
            futures[0].result(timeout=5)
        next_data = o.report()
        assert next_data["entry"]["halted"] and next_data["revision"] > data["revision"]


def test_observer_reads_do_not_recover_interrupted_cycles_or_change_any_source(
    tmp_path, monkeypatch
):
    with owned_model(tmp_path) as (c, venue, _, _):
        add_frame(c, frame())
        with c.engine.journal.write() as db:
            db.execute(
                "UPDATE execution_option_opportunities SET status='STARTED',result_json=NULL"
            )
        paths = [
            c.engine.journal.path,
            Path(str(c.engine.journal.path) + ".authority.db"),
            venue.path,
            c.key_file,
        ]
        before = digest(paths)

        def forbidden(*args, **kwargs):
            pytest.fail("An observer read invoked trading work")

        for name in (
            "open",
            "prepare",
            "dispatch",
            "reconcile_fixture",
            "begin_model_attempt",
            "protective_tick",
        ):
            monkeypatch.setattr(OptionExecution, name, forbidden)
        monkeypatch.setattr(DegenCoordinator, "cycle", forbidden)
        monkeypatch.setattr(judgment, "run_candidate_process", forbidden)
        client, password = app_for(c, tmp_path)
        for url in ("/", "/api/options", "/?refresh=true", "/?family=SWING", "/?before=2"):
            assert client.get(url).status_code == 200
        assert digest(paths) == before and password.stat().st_mode & 0o777 == 0o600
        assert client.get("/api/options").json()["opportunities"][0]["storage_status"] == "STARTED"


@pytest.mark.parametrize("damage", ["missing", "public", "symlink", "short", "space", "relative"])
def test_private_independent_observer_authentication_required(tmp_path, damage):
    key = tmp_path / "password"
    key.write_text(PASSWORD)
    key.chmod(0o600)
    if damage == "missing":
        key.unlink()
    elif damage == "public":
        key.chmod(0o644)
    elif damage == "symlink":
        target = tmp_path / "target"
        key.rename(target)
        key.symlink_to(target)
    elif damage == "short":
        key.write_text("short")
    elif damage == "space":
        key.write_text(PASSWORD + " bad")
    else:
        key = Path("relative")
    with pytest.raises((OSError, ValueError)):
        options.create_options_app(tmp_path / "missing.db", "population", key)


def test_http_auth_rotation_revocation_and_browsing_cannot_mutate(tmp_path, monkeypatch):
    with owned_strategy(tmp_path) as (c, _, _, _, _, _):
        client, key = app_for(c, tmp_path)
        anonymous = TestClient(client.app)
        assert anonymous.get("/api/options").status_code == 401
        assert anonymous.get("/").status_code == 401
        assert anonymous.get("/healthz").json()["trader_health"] == "NOT_CHECKED"

        def forbidden(*args, **kwargs):
            pytest.fail("Unauthenticated client read execution records")

        original = observer.OptionObserver.report
        monkeypatch.setattr(observer.OptionObserver, "report", forbidden)
        assert anonymous.get("/api/options").status_code == 401
        monkeypatch.setattr(observer.OptionObserver, "report", original)
        for url in ("/cycle", "/halt", "/resume", "/order", "/cancel", "/api/options"):
            assert client.post(url).status_code in {404, 405}
        for url in ("/api/options?limit=101", "/?before=0", "/?family=LIVE"):
            assert client.get(url).status_code == 422
        html = client.get("/")
        assert html.status_code == 200
        assert "default-src 'none'" in html.headers["Content-Security-Policy"]
        assert html.headers["Cache-Control"] == "no-store"
        assert 'http-equiv="refresh"' not in html.text
        assert 'http-equiv="refresh"' in client.get("/?refresh=true").text
        assert 'http-equiv="refresh"' not in client.get("/?refresh=true&before=2").text
        key.write_text(PASSWORD + "-rotated")
        assert client.get("/").status_code == 401
        client.auth = ("trader", PASSWORD + "-rotated")
        assert client.get("/").status_code == 200
        key.unlink()
        assert client.get("/").status_code == 503


def test_html_escapes_untrusted_thesis_and_explains_empty_family(tmp_path, monkeypatch):
    async def run(request, key):
        result = receipt_for(request, action="HOLD")
        return result.model_copy(
            update={
                "choice": result.choice.model_copy(
                    update={"thesis": "<script>alert('unsafe')</script>"}
                )
            }
        )

    monkeypatch.setattr(judgment, "run_candidate_process", run)
    with owned_model(tmp_path) as (c, _, _, _):
        asyncio.run(c.cycle(frame()))
        client, _ = app_for(c, tmp_path)
        html = client.get("/").text
        assert "<script>" not in html and "&lt;script&gt;" in html
        assert "SPY comparison" in html and "Unknown model usage" in html
        assert "Swing is not implemented" in client.get("/?family=SWING").text
        assert "Scope is not implemented" in client.get("/?family=SCOPE").text


def test_cli_is_loopback_only_and_never_initializes_execution(tmp_path, monkeypatch):
    from app.options import observer_cli

    key = tmp_path / "password"
    key.write_text(PASSWORD)
    key.chmod(0o600)
    calls = []
    monkeypatch.setattr(observer_cli.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    observer_cli.main(
        [
            "--journal",
            str(tmp_path / "missing.db"),
            "--population-id",
            "population",
            "--password-file",
            str(key),
        ]
    )
    assert calls == [
        {"host": "127.0.0.1", "port": 8790, "access_log": False, "log_level": "warning"}
    ]
    assert not (tmp_path / "missing.db").exists()
