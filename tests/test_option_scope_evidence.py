"""Stored selected Scope reviews must retain their inputs, policy and action binding."""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_option_scope import AT
from test_option_scope_observer import observer
from test_option_scope_owned_admission import evidence, review, start
from test_option_scope_watch import owned, ready, revision

from app.web.options import create_options_app


def selected(scan, choice, *, quality=False):
    return next(
        o
        for o in scan["observations"]
        if all((o["observation"] if quality else o)[k] == v for k, v in choice.items())
    )


def approved(engine, venue, right="CALL"):
    book, f = start(engine, venue, right)
    fresh, c, u, now = evidence(engine, f)
    ready(engine, venue, now)
    receipt = review(book, fresh, c, u, now)
    return book, receipt, now


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_selected_original_and_sampled_reviews_keep_identity_costs_and_read_only_timing(
    tmp_path, right
):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, receipt, now = approved(engine, venue, right)
        record = receipt["record"]
        before, rev = book.snapshot(), revision(engine)
        report = observer(engine, now).report()
        w = report["scope"]["active_watch"]
        d = w["decision_evidence"]
        for name, q, c in (
            ("called", record["locked_quality_scan"], record["locked_contract_scan"]),
            ("latest_sample", record["arming"]["quality_scan"], record["arming"]["contract_scan"]),
        ):
            assert d[name]["quality"]["selected"] == selected(q, record["choice"], quality=True)
            assert d[name]["contract"]["selected"] == selected(c, record["choice"])
            assert d[name]["quality"]["input_hash"] == q["input_hash"]
            assert d[name]["quality"]["policy_hash"] == q["policy_hash"]
        assert d["called"]["quality"]["time_status"] == "NO_VALIDITY_RECORDED"
        assert d["latest_sample"]["quality"]["time_status"] == "WITHIN_RECORDED_WINDOW"
        assert d["stored_only"] and not d["authority"] and not d["live_enabled"]
        assert w["audit"]["sequence"] == receipt["revision"]
        assert w["audit"]["action_key"] == "review"
        assert w["admission"]["result"] == record["admission_review"]["admission"]
        for clock, status in (
            (now + timedelta(seconds=11), "EXPIRED"),
            (AT - timedelta(seconds=1), "FUTURE"),
        ):
            later = observer(engine, clock).report()["scope"]["active_watch"]
            assert later["decision_evidence"]["latest_sample"]["quality"]["time_status"] == status
            assert (
                later["decision_evidence"]["latest_sample"]["quality"]["selected"]
                == d["latest_sample"]["quality"]["selected"]
            )
        assert revision(engine) == rev and book.snapshot() == before
        assert not report["orders"] and not report["fills"]


def test_failed_missing_sample_does_not_reuse_original_passing_review(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, _, now = approved(engine, venue)
        now += timedelta(seconds=1)
        ready(engine, venue, now)
        book.observe_arming("missing", "first", now=now, expected_revision=revision(engine))
        w = observer(engine, now).report()["scope"]["active_watch"]
        assert w["arming"]["recorded_status"] == "RESET"
        assert w["decision_evidence"]["latest_sample"] == {"quality": None, "contract": None}
        assert w["decision_evidence"]["called"]["quality"]["selected"]["passed"]
        assert w["audit"]["action_key"] == "missing"


@pytest.mark.parametrize(
    "damage",
    [
        "record",
        "event",
        "receipt",
        "revision",
        "authority_type",
        "request_hash",
        "missing_event",
        "missing_receipt",
        "enrollment",
        "policy_clock",
    ],
)
def test_unbound_or_rewritten_records_never_become_displayed_decisions(tmp_path, damage):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        _, receipt, now = approved(engine, venue)
        with engine.journal.write() as db:
            if damage == "record":
                raw = receipt["record"]
                raw["locked_quality_scan"]["observations"][0]["score"] = 100
                db.execute(
                    "UPDATE execution_option_scope_watches SET record_json=?", (json.dumps(raw),)
                )
            elif damage == "event":
                row = db.execute(
                    "SELECT sequence,payload FROM execution_events WHERE kind='SCOPE_WATCH_ACTION' ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                raw = json.loads(row["payload"])
                raw["record"]["geometry"]["target_one"] = "101.6"
                db.execute(
                    "UPDATE execution_events SET payload=? WHERE sequence=?",
                    (json.dumps(raw), row["sequence"]),
                )
            elif damage in ("receipt", "revision", "authority_type"):
                raw = json.loads(
                    db.execute(
                        "SELECT result_json FROM execution_option_scope_watch_actions WHERE action_key='review'"
                    ).fetchone()[0]
                )
                if damage == "receipt":
                    raw["record"]["geometry"]["target_one"] = "101.6"
                elif damage == "revision":
                    raw["revision"] -= 1
                else:
                    raw["authority"] = 0  # False equality must not hide a type substitution.
                db.execute(
                    "UPDATE execution_option_scope_watch_actions SET result_json=? WHERE action_key='review'",
                    (json.dumps(raw),),
                )
            elif damage == "request_hash":
                db.execute(
                    "UPDATE execution_option_scope_watch_actions SET request_hash='invalid' WHERE action_key='review'"
                )
            elif damage == "missing_event":
                db.execute("DELETE FROM execution_events WHERE sequence=?", (receipt["revision"],))
            elif damage == "missing_receipt":
                db.execute(
                    "DELETE FROM execution_option_scope_watch_actions WHERE action_key='review'"
                )
            elif damage == "enrollment":
                db.execute("DELETE FROM execution_events WHERE kind='SCOPE_WATCH_ENROLLED'")
            else:
                db.execute(
                    "UPDATE execution_option_scope_watch_policy SET last_action_at=?",
                    (AT.isoformat(),),
                )
        assert observer(engine, now).report()["status"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "damage", ["input", "policy", "selection", "contract", "clock", "missing_original"]
)
def test_typed_projection_rejects_inconsistent_saved_scan_even_if_receipt_copied(tmp_path, damage):
    # Coherent fixture envelopes isolate semantic binding checks, not hostile-host protection.
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        _, receipt, now = approved(engine, venue)
        record = receipt["record"]
        if damage == "missing_original":
            del record["locked_quality_scan"]
        else:
            q = record["arming"]["quality_scan"]
            if damage == "input":
                q["input_hash"] = "a" * 64
            if damage == "policy":
                q["policy_hash"] = "a" * 64
            if damage == "selection":
                q["observations"] = []
            if damage == "clock":
                q["evaluated_at"] = AT.isoformat()
            if damage == "contract":
                record["arming"]["contract_scan"]["policy_hash"] = "a" * 64
        with engine.journal.write() as db:
            db.execute(
                "UPDATE execution_option_scope_watches SET record_json=?", (json.dumps(record),)
            )
            db.execute(
                "UPDATE execution_events SET payload=? WHERE sequence=?",
                (json.dumps({"action_key": "review", "record": record}), receipt["revision"]),
            )
            db.execute(
                "UPDATE execution_option_scope_watch_actions SET result_json=? WHERE action_key='review'",
                (json.dumps(receipt),),
            )
        assert observer(engine, now).report()["status"] == "UNAVAILABLE"


def test_no_rescan_or_owner_attachment_for_saved_quality_and_contract(tmp_path, monkeypatch):
    from app.options import scope_contract, scope_quality, scope_watch

    with owned(tmp_path, enroll=False) as (engine, venue, _):
        _, _, now = approved(engine, venue)

        def forbidden(*args, **kwargs):
            pytest.fail("Stored review cannot call a strategy or execution owner")

        monkeypatch.setattr(scope_quality, "scan_scope_quality", forbidden)
        monkeypatch.setattr(scope_contract, "scan_scope_contract", forbidden)
        monkeypatch.setattr(scope_watch.ScopeWatchBook, "__init__", forbidden)
        assert observer(engine, now).report()["status"] == "OK"


def test_authenticated_details_keep_recorded_time_and_no_order_controls(tmp_path):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        _, _, now = approved(engine, venue)
        secret = tmp_path / "password"
        secret.write_text("fixture-scope-evidence-only")
        secret.chmod(0o600)
        client = TestClient(
            create_options_app(
                engine.journal.path,
                engine.limits.population_id,
                secret,
                clock=lambda: now + timedelta(seconds=11),
            )
        )
        assert client.get("/").status_code == 401
        client.auth = ("trader", secret.read_text())
        before = revision(engine)
        html = client.get("/?family=SCOPE")
        assert html.status_code == 200
        for expected in (
            "Decision evidence",
            "At call",
            "Latest sample",
            "Quality 95",
            "Contract profile: Balanced",
            "expired",
            "Full path unproven",
        ):
            assert expected in html.text
        report = client.get("/api/options?family=SCOPE").json()
        assert report["scope"]["active_watch"]["decision_evidence"]["stored_only"]
        assert client.post("/api/options").status_code == 405
        assert revision(engine) == before
