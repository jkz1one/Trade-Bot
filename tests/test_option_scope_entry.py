"""Scope selection binds original watch, owned admission and management without orders."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_management import admitted, watch_policy
from test_option_scope_observer import observer
from test_option_scope_owned_admission import evidence, review
from test_option_scope_watch import owned, ready, revision

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution, fingerprint
from app.options.models import OptionAdmission, OptionProposal
from app.options.scope_entry import ScopeEntryBinding
from app.options.scope_watch import ScopeWatchBook, ScopeWatchPolicy


def policy():
    return ScopeWatchPolicy.model_validate(
        watch_policy(version="scope-management-plan-v2").model_dump()
        | {"quote_lifecycle": "scope-observed-quotes-v1", "entry_binding": "scope-entry-binding-v1"}
    )


def select(book, now, expected=None):
    return book.entry_selection(
        "first", now=now, expected_revision=revision(book.engine) if expected is None else expected
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("quantity", [1, 2, 3, 4])
def test_exact_stored_selection_retains_all_terms_and_never_grants_authority(
    tmp_path, right, quantity
):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, f, _, u, now = admitted(e, v, right, quantity, p=policy())
        before = book.snapshot()
        selected = select(book, now)
        record = out["record"]
        r = record["admission_review"]
        binding = ScopeEntryBinding.model_validate(selected["binding"])
        assert binding.revision == out["revision"] == revision(e)
        assert binding.play_key == "first" and binding.action_key == "review"
        assert binding.population_id == e.limits.population_id
        assert binding.account_id == e.limits.account_id
        assert binding.family == "SCOPE"
        assert selected["binding_hash"] == fingerprint(binding)
        assert selected["proposal"] == r["proposal"]
        assert selected["admission"] == r["admission"]
        assert selected["management"] == r["management"]
        assert (
            selected["entry_time_protection"]["exit_by"]
            == record["locked_frame"]["session"]["protect_at"]
        )
        assert selected["geometry"] == record["geometry"]
        assert selected["account"] == r["account"]
        assert selected["effective_limits"] == r["effective_limits"]
        assert selected["session"] == r["session"]
        assert selected["quote"] == f.quote.model_dump(mode="json")
        assert selected["underlying"] == u.model_dump(mode="json")
        a = selected["admission"]
        assert Decimal(a["full_premium_loss"]) == Decimal(a["entry_debit"]) + Decimal(
            a["reserved_exit_fees"]
        )
        assert Decimal(a["reserved_exit_fees"]) == quantity * Decimal("1.65")
        assert not selected["authority"] and not selected["live_enabled"]
        assert "SCOPE_COMPLETE_PATH_UNPROVEN" in selected["execution_blockers"]
        assert ("SCOPE_THIRD_TARGET_UNSPECIFIED" in selected["execution_blockers"]) == (
            quantity == 4
        )
        assert select(book, now) == selected
        assert book.snapshot() == before and v.submit_count == 0
        view = observer(e, now).report()
        assert view["status"] == "OK", view
        saved = view["scope"]["active_watch"]["entry_binding"]
        assert saved["current_revision"] and saved["time_status"] == "WITHIN_RECORDED_WINDOW"
        assert saved["record_hash"] == binding.record_hash
        with e.journal.read() as db:
            for table in (
                "execution_orders",
                "execution_model_calls",
                "execution_fills",
                "execution_option_decisions",
            ):
                assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        # Even the exact selected ceiling/plan cannot bypass the native guard.
        result = e.prepare(
            "blocked-selection",
            OptionProposal.model_validate(selected["proposal"]),
            f.quote,
            u,
            now=now,
            ceiling=OptionAdmission.model_validate(selected["admission"]),
        )
        assert result["status"] == "REJECTED"
        assert result["reason"] == "SCOPE_NATIVE_EXECUTION_NOT_ENROLLED"
        assert result["client_id"] is None


@pytest.mark.parametrize("when", ["before", "deadline", "after"])
def test_selection_cannot_refresh_or_extend_saved_validity(tmp_path, when, monkeypatch):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, _, _, _, now = admitted(e, v, p=policy())
        binding = ScopeEntryBinding.model_validate(out["record"]["entry_binding"])
        at = {
            "before": now - timedelta(microseconds=1),
            "deadline": binding.valid_until,
            "after": binding.valid_until + timedelta(seconds=1),
        }[when]
        before = book.snapshot()

        def forbidden(*args, **kwargs):
            raise AssertionError("selection refreshed evidence")

        monkeypatch.setattr("app.options.scope_watch.scan_scope_contract", forbidden)
        monkeypatch.setattr("app.options.scope_watch.scan_scope_quality", forbidden)
        monkeypatch.setattr("app.options.scope_watch.admit_option", forbidden)
        with pytest.raises(ExecutionBlocked, match="SCOPE_ENTRY_ADMISSION_EXPIRED"):
            select(book, at)
        assert book.snapshot() == before
        view = observer(e, at).report()["scope"]["active_watch"]["entry_binding"]
        assert view["time_status"] == ("FUTURE" if when == "before" else "EXPIRED")


def test_any_later_owner_event_requires_new_admission_not_a_new_revision_argument(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, _, f, _, _, now = admitted(e, v, p=policy())
        old = select(book, now)
        ready(e, v, now + timedelta(seconds=1))
        with pytest.raises(ExecutionBlocked, match="SCOPE_ENTRY_REVISION_CHANGED"):
            select(book, now, old["binding"]["revision"])
        with pytest.raises(ExecutionBlocked, match="SCOPE_ENTRY_FRESH_ADMISSION_REQUIRED"):
            select(book, now + timedelta(seconds=1))
        view = observer(e, now).report()["scope"]["active_watch"]["entry_binding"]
        assert not view["current_revision"]
        fresh, c, u, at = evidence(e, f, 61)
        result = review(book, fresh, c, u, at, key="fresh")
        new = select(book, at)
        assert new["binding"]["revision"] == result["revision"]
        assert new["binding_hash"] != old["binding_hash"]
        assert new["binding"]["original_call_hash"] == old["binding"]["original_call_hash"]


@pytest.mark.parametrize("action", ["failed_admission", "quote", "terminal_quote", "arming"])
def test_later_watch_actions_retire_the_old_binding_and_retry_does_not_restore_it(tmp_path, action):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, f, c, u, now = admitted(e, v, p=policy())
        if action == "failed_admission":
            review(book, f, c, u, now, key="repeat")
        elif action == "arming":
            book.observe_arming(
                "arming", "first", frame=f, context=c, now=now, expected_revision=revision(e)
            )
        else:
            q = u.model_copy(
                update={
                    "source_at": now + timedelta(seconds=1),
                    "received_at": now + timedelta(seconds=1),
                }
            )
            if action == "terminal_quote":
                stop = Decimal(out["record"]["geometry"]["invalidation"])
                q = q.model_copy(update={"bid": stop, "ask": stop})
            book.observe_quote(
                "quote", "first", q, now=now + timedelta(seconds=1), expected_revision=revision(e)
            )
        assert "entry_binding" not in book.snapshot()["watches"][0]
        # Historical retries return the historical binding but cannot select it.
        assert (
            book.review_admission(
                "review",
                "first",
                frame=f,
                context=c,
                underlying=u,
                now=now,
                expected_revision=out["revision"] - 1,
            )
            == out
        )
        with pytest.raises(ExecutionBlocked, match="SCOPE_ENTRY_BOUND_ADMISSION_REQUIRED"):
            select(book, now + timedelta(seconds=1))
        assert observer(e, now + timedelta(seconds=1)).report()["status"] == "OK"


def test_binding_is_frozen_optional_and_requires_exact_prerequisites(tmp_path):
    old = watch_policy()
    assert "entry_binding" not in old.model_dump()
    for changes in (
        {"management": None},
        {"management": old.management},
        {"quote_lifecycle": None},
    ):
        with pytest.raises(ValidationError, match="requires v2 management and observed quotes"):
            ScopeWatchPolicy.model_validate(policy().model_dump() | changes)
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, *_ = admitted(e, v)
        with pytest.raises(ExecutionBlocked, match="FROZEN_SCOPE_WATCH_POLICY_MISMATCH"):
            ScopeWatchBook(e, policy(), now=AT)
        with pytest.raises(ExecutionBlocked, match="SCOPE_ENTRY_BOUND_ADMISSION_REQUIRED"):
            select(book, AT + timedelta(seconds=60))


def test_restart_retains_same_binding_without_refreshing_or_extending_it(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, _, _, _, now = admitted(e, v, p=policy())
        path, limits, epolicy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, epolicy, v, now=now) as e:
        book = ScopeWatchBook(e, policy(), now=now)
        assert book.snapshot()["watches"][0]["entry_binding"] == out["record"]["entry_binding"]
        assert observer(e, now).report()["status"] == "OK"
        assert select(book, now)["binding"] == out["record"]["entry_binding"]
        ready(e, v, now + timedelta(seconds=1))
        with pytest.raises(ExecutionBlocked, match="SCOPE_ENTRY_FRESH_ADMISSION_REQUIRED"):
            select(book, now)


def test_binding_and_receipt_rollback_together(tmp_path, monkeypatch):
    from test_option_scope_owned_admission import start

    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=policy())
        f, c, u, now = evidence(e, f)
        ready(e, v, now)
        before = book.snapshot()
        event = e.journal.event

        def fail(*args, **kwargs):
            event(*args, **kwargs)
            raise RuntimeError("binding audit failure")

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="binding audit failure"):
            review(book, f, c, u, now)
        assert book.snapshot() == before
        with e.journal.read() as db:
            assert (
                db.execute(
                    "SELECT 1 FROM execution_option_scope_watch_actions WHERE action_key='review'"
                ).fetchone()
                is None
            )


def rewrite_latest(e, record, action_key="review"):
    """Fixture damage keeps latest record/action copies consistent, not original call."""
    with e.journal.write() as db:
        row = db.execute(
            "SELECT result_json FROM execution_option_scope_watch_actions WHERE action_key=?",
            (action_key,),
        ).fetchone()
        receipt = json.loads(row[0])
        receipt["record"] = record
        db.execute(
            "UPDATE execution_option_scope_watches SET record_json=? WHERE play_key='first'",
            (json.dumps(record),),
        )
        db.execute(
            "UPDATE execution_option_scope_watch_actions SET result_json=? WHERE action_key=?",
            (json.dumps(receipt), action_key),
        )
        db.execute(
            "UPDATE execution_events SET payload=? WHERE sequence=?",
            (json.dumps({"action_key": action_key, "record": record}), receipt["revision"]),
        )


@pytest.mark.parametrize(
    "damage",
    [
        "population",
        "account",
        "request",
        "record",
        "revision",
        "deadline",
        "fees",
        "management_scan",
        "original_geometry",
        "original_receipt",
    ],
)
def test_consistent_latest_copies_cannot_substitute_bound_evidence(tmp_path, damage):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, _, _, _, now = admitted(e, v, p=policy())
        r = out["record"]
        b = r["entry_binding"]
        if damage in {"population", "account"}:
            b[damage + "_id"] = "another-owner"
        elif damage == "request":
            b["request_hash"] = "0" * 64
        elif damage == "record":
            b["record_hash"] = "0" * 64
        elif damage == "revision":
            b["revision"] -= 1
        elif damage == "deadline":
            b["valid_until"] = (now + timedelta(minutes=1)).isoformat()
        elif damage == "fees":
            r["admission_review"]["effective_limits"]["exit_fee_per_contract"] = "0"
        elif damage == "management_scan":
            r["admission_review"]["management"]["contract_scan_hash"] = "0" * 64
        elif damage == "original_geometry":
            r["locked_frame"]["histories"][0]["bars"][0]["volume"] += 1
        else:
            with e.journal.write() as db:
                db.execute(
                    "DELETE FROM execution_option_scope_watch_actions WHERE action_key='first'"
                )
        rewrite_latest(e, r)
        with pytest.raises((ValueError, KeyError)):
            select(book, now)
        assert observer(e, now).report()["status"] == "UNAVAILABLE"


def test_identical_watch_keys_in_independent_owners_do_not_share_binding(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    with owned(a, enroll=False, population_id="scope-a", account_id="account-a") as (e, v, _):
        book, _, _, _, _, now = admitted(e, v, p=policy())
        first = select(book, now)
    with owned(b, enroll=False, population_id="scope-b", account_id="account-b") as (e, v, _):
        book, out, _, _, _, now = admitted(e, v, p=policy())
        second = select(book, now)
        assert first["binding_hash"] != second["binding_hash"]
        out["record"]["entry_binding"] = first["binding"]
        rewrite_latest(e, out["record"])
        with pytest.raises(ValueError, match="SCOPE_ENTRY_BINDING_CHANGED"):
            select(book, now)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_portable_replay_retains_bound_admission_and_rejects_substitution(tmp_path, right):
    from test_option_scope_replay import settings, tape
    from test_option_scope_replay_verify import snapshot

    from app.options.scope_replay import run_scope_replay
    from app.options.scope_replay_verify import verify_scope_replay

    request = settings(tape(right), watch=policy())
    directory = tmp_path / "export"
    run_scope_replay(request, directory)
    before = snapshot(directory)
    result = verify_scope_replay(directory, fingerprint(request))
    assert result["status"] == "VERIFIED_RESEARCH_REPLAY"
    assert snapshot(directory) == before
    file = directory / "actions/007.json"
    action = json.loads(file.read_text())
    assert "entry_binding" in action["receipt"]["record"]
    action["receipt"]["record"]["entry_binding"]["account_id"] = "substitution"
    action["receipt_hash"] = fingerprint(action["receipt"])
    file.write_text(json.dumps(action))
    with pytest.raises(ValueError, match="differs from native reproduction"):
        verify_scope_replay(directory, fingerprint(request))
