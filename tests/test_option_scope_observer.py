"""Stored Scope visibility cannot advance watches, approve entries or hide old evidence."""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_option_scope import AT
from test_option_scope_owned_admission import evidence, review, start
from test_option_scope_watch import call, owned, ready, revision

from app.options.observer import OptionObserver
from app.web.options import create_options_app


def observer(engine, now=AT):
    return OptionObserver(engine.journal.path, engine.limits.population_id, clock=lambda: now)


def test_absent_and_empty_enrollment_are_distinct(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, _, _):
        r = observer(engine).report()
        assert r["status"] == "OK"
        assert r["scope"]["status"] == "NOT_ENROLLED"
    other = tmp_path / "other"
    other.mkdir()
    with owned(other) as (engine, _, _):
        r = observer(engine).report()
        assert r["scope"]["status"] == "RESEARCH_ONLY"
        assert r["scope"]["watches"] == []
        assert r["scope"]["active_watch"] is None


def test_stored_watch_survives_read_after_cutoff_without_mutation(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        call(book)
        before = book.snapshot()
        rev = revision(engine)
        now = AT + timedelta(days=1)
        for family in ("ALL", "SCOPE", "SWING"):
            r = observer(engine, now).report(family=family, limit=1, before=1)
            assert r["status"] == "OK"
            w = r["scope"]["active_watch"]
            assert w["recorded_status"] == "WATCHING"
            assert w["time_status"] == "PAST_ENTRY_CUTOFF"
            assert w["arming"] is None and w["admission"] is None
            assert not w["authority"] and not w["live_enabled"]
            assert not r["orders"] and not r["fills"]
        assert before == book.snapshot() and rev == revision(engine)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_admission_preserves_full_costs_and_expired_evidence(tmp_path, right):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, right)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        result = review(book, fresh, c, u, now)["record"]
        before = book.snapshot()
        w = observer(engine, now).report()["scope"]["active_watch"]
        assert w["admission"]["result"] == result["admission_review"]["admission"]
        assert w["admission"]["recorded_eligible"]
        assert w["admission"]["time_status"] == "WITHIN_RECORDED_WINDOW"
        assert w["arming"]["recorded_status"] == "ARMED"
        later = observer(engine, now + timedelta(seconds=11)).report()["scope"]["active_watch"]
        assert later["admission"]["time_status"] == "EXPIRED"
        assert later["arming"]["time_status"] == "EXPIRED"
        assert later["admission"]["recorded_eligible"]
        assert book.snapshot() == before


@pytest.mark.parametrize(
    "damage",
    ["policy_missing", "table_missing", "owner", "key", "status", "lock", "terminal", "oversize"],
)
def test_corrupt_scope_evidence_fails_closed(tmp_path, damage):
    with owned(tmp_path) as (engine, _, book):
        call(book)
        with engine.journal.write() as db:
            if damage == "policy_missing":
                db.execute("DELETE FROM execution_option_scope_watch_policy")
            elif damage == "table_missing":
                db.execute("DROP TABLE execution_option_scope_watch_actions")
            elif damage == "owner":
                raw = json.loads(
                    db.execute(
                        "SELECT config_json FROM execution_option_scope_watch_policy"
                    ).fetchone()[0]
                )
                raw["context"]["structure"]["preflight"]["provider"] = "other"
                db.execute(
                    "UPDATE execution_option_scope_watch_policy SET config_json=?",
                    (json.dumps(raw),),
                )
            else:
                raw = json.loads(
                    db.execute("SELECT record_json FROM execution_option_scope_watches").fetchone()[
                        0
                    ]
                )
                if damage == "key":
                    raw["play_key"] = "other"
                if damage == "status":
                    raw["status"] = "FILLED"
                if damage == "terminal":
                    raw["terminal_at"] = AT.isoformat()
                if damage == "oversize":
                    raw["padding"] = "x" * 262144
                if damage == "lock":
                    db.execute("UPDATE execution_option_scope_watches SET active_lock=NULL")
                db.execute(
                    "UPDATE execution_option_scope_watches SET record_json=?", (json.dumps(raw),)
                )
        assert observer(engine).report()["status"] == "UNAVAILABLE"


def test_authenticated_html_api_and_no_control_routes(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        call(book)
        secret = tmp_path / "password"
        secret.write_text("fixture-observer-password-only")
        secret.chmod(0o600)
        client = TestClient(
            create_options_app(
                engine.journal.path, engine.limits.population_id, secret, clock=lambda: AT
            )
        )
        assert client.get("/api/options").status_code == 401
        client.auth = ("trader", secret.read_text())
        r = client.get("/api/options?family=SCOPE")
        assert r.status_code == 200 and r.json()["scope"]["active_watch"]["play_key"] == "first"
        html = client.get("/?family=SCOPE")
        assert "Scope research watches" in html.text
        assert "Research only." in html.text and "Not recorded" in html.text
        assert "Scope is not implemented" not in html.text
        assert client.post("/api/options").status_code == 405


def test_bounded_history_keeps_active_record_visible(tmp_path):
    # Seed a retained-history projection fixture; this does not exercise call admission.
    with owned(tmp_path) as (engine, _, book):
        call(book)
        with engine.journal.write() as db:
            raw = json.loads(
                db.execute("SELECT record_json FROM execution_option_scope_watches").fetchone()[0]
            )
            raw["status"] = "EXPIRED_UNFILLED"
            raw["terminal_at"] = AT.isoformat()
            for n in range(26):
                raw["play_key"] = f"retained-{n}"
                db.execute(
                    "INSERT INTO execution_option_scope_watches VALUES(?,?,NULL,?)",
                    (raw["play_key"], raw["session_date"], json.dumps(raw)),
                )
                # A visible retained record must have its original action and receipt.
                action_key = raw["play_key"] + "-action"
                engine.journal.event(
                    db, AT, "SCOPE_WATCH_ACTION", {"action_key": action_key, "record": raw}
                )
                receipt = {
                    "revision": engine.journal.revision(db),
                    "record": raw,
                    "authority": False,
                    "live_enabled": False,
                }
                db.execute(
                    "INSERT INTO execution_option_scope_watch_actions VALUES(?,?,?)",
                    (action_key, "a" * 64, json.dumps(receipt)),
                )
        s = observer(engine).report()["scope"]
        assert s["total_watches"] == 27 and s["history_truncated"]
        assert len(s["watches"]) == 25
        assert all(w["play_key"] != "first" for w in s["watches"])
        assert s["active_watch"]["play_key"] == "first"


def test_no_owner_scan_or_watch_mutation_on_read(tmp_path, monkeypatch):
    from app.options import scope_watch

    with owned(tmp_path) as (engine, _, book):
        call(book)

        def forbidden(*args, **kwargs):
            pytest.fail("Observer must not construct an owner or evaluate evidence")

        monkeypatch.setattr(scope_watch.ScopeWatchBook, "__init__", forbidden)
        monkeypatch.setattr(scope_watch, "scan_scope_quality", forbidden)
        monkeypatch.setattr(scope_watch, "scan_scope_context", forbidden)
        monkeypatch.setattr(scope_watch, "scan_scope_structure", forbidden)
        monkeypatch.setattr(scope_watch.OptionExecution, "open", forbidden)
        assert observer(engine).report()["scope"]["status"] == "RESEARCH_ONLY"


def test_future_and_terminal_records_keep_recorded_state(tmp_path):
    with owned(tmp_path) as (engine, _, book):
        call(book)
        assert (
            observer(engine, AT - timedelta(seconds=1)).report()["scope"]["active_watch"][
                "time_status"
            ]
            == "FUTURE"
        )
        cutoff = AT + timedelta(days=1)
        book.advance("expire", "first", expected_revision=revision(engine), now=cutoff)
        r = observer(engine, cutoff).report()["scope"]
        assert r["active_watch"] is None
        assert r["watches"][0]["recorded_status"] == "EXPIRED_UNFILLED"


@pytest.mark.parametrize("stamp", [7, None, "2026-10-15T10:00:00"])
def test_invalid_timestamp_returns_unavailable(tmp_path, stamp):
    with owned(tmp_path) as (engine, _, book):
        call(book)
        with engine.journal.write() as db:
            raw = json.loads(
                db.execute("SELECT record_json FROM execution_option_scope_watches").fetchone()[0]
            )
            raw["called_at"] = stamp
            db.execute(
                "UPDATE execution_option_scope_watches SET record_json=?", (json.dumps(raw),)
            )
        assert observer(engine).report()["status"] == "UNAVAILABLE"


def test_unfinished_hold_has_no_invented_sizing(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f, seconds=55)
        ready(engine, venue, now)
        review(book, fresh, c, u, now)
        w = observer(engine, now).report()["scope"]["active_watch"]
        assert w["arming"]["recorded_status"] == "HOLDING"
        assert not w["admission"]["recorded_eligible"]
        assert w["admission"]["result"] is None
        assert w["admission"]["time_status"] == "NO_VALIDITY_RECORDED"
