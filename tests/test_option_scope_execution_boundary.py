"""Scope research sizing cannot authorize generic native preparation or dispatch."""

import asyncio
import json

import pytest
from test_option_execution import enter, intent_for
from test_option_execution import owned as native_owned
from test_option_scope import AT
from test_option_scope_owned_admission import evidence, review, start
from test_option_scope_watch import call, owned, policy, ready

from app.options.engine import OptionExecution
from app.options.models import OptionAdmission, OptionProposal
from app.options.scope_watch import ScopeWatchBook

BLOCK = "SCOPE_NATIVE_EXECUTION_NOT_ENROLLED"


def legacy_enrollment(engine, *, empty=False):
    # Fixture-only representation of a journal created by the earlier version.
    # Production enrollment rejects an account that already contains orders.
    with engine.journal.write() as db:
        db.execute(
            "CREATE TABLE execution_option_scope_watch_policy "
            "(id INTEGER PRIMARY KEY, config_json TEXT, last_action_at TEXT)"
        )
        if not empty:
            db.execute(
                "INSERT INTO execution_option_scope_watch_policy VALUES(1,'{}',?)",
                (AT.isoformat(),),
            )


@pytest.mark.parametrize("called", [False, True])
def test_research_enrollment_blocks_direct_entry_even_without_active_watch(tmp_path, called):
    with owned(tmp_path) as (engine, _, book):
        if called:
            call(book)
        from test_option_scope_watch import frame

        f = frame()
        from test_option_scope_owned_admission import evidence

        _, _, u, _ = evidence(engine, f, 0)
        p = OptionProposal(
            action="OPEN_LONG",
            contract=f.metadata.instrument.contract,
            underlying_invalidation="99",
            thesis="direct bypass",
        )
        out = engine.prepare("bypass", p, f.quote, u, now=AT)
        assert out["status"] == "REJECTED" and out["reason"] == BLOCK
        assert out["client_id"] is None
        assert engine.prepare("bypass", p, f.quote, u, now=AT) == out
        with engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 0


@pytest.mark.parametrize("ceiling", [False, True])
def test_even_eligible_owned_review_cannot_be_replayed_as_native_authority(tmp_path, ceiling):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, c, u, now = evidence(engine, f)
        ready(engine, venue, now)
        record = review(book, fresh, c, u, now)["record"]["admission_review"]
        assert record["eligible"]
        out = engine.prepare(
            "bypass",
            OptionProposal.model_validate(record["proposal"]),
            fresh.quote,
            u,
            now=now,
            ceiling=OptionAdmission.model_validate(record["admission"]) if ceiling else None,
        )
        assert out["status"] == "REJECTED" and out["reason"] == BLOCK
        assert out["client_id"] is None


@pytest.mark.parametrize("empty", [False, True])
def test_dispatch_rechecks_enrollment_before_attempt_or_worker(tmp_path, empty, monkeypatch):
    with native_owned(tmp_path) as (engine, _, data):
        from test_option_admission import NOW

        out = engine.prepare("entry", data["proposal"], data["quote"], data["underlying"], now=NOW)
        assert out["status"] == "PREPARED"
        legacy_enrollment(engine, empty=empty)

        def forbidden(*args, **kwargs):
            raise AssertionError("worker must not run")

        monkeypatch.setattr("app.options.engine.run_option_process", forbidden)
        assert (
            asyncio.run(
                engine.dispatch(out["client_id"], data["quote"], data["underlying"], now=NOW)
            )
            == "REJECTED"
        )
        with engine.journal.read() as db:
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            assert row["attempted_at"] is None and row["active_lock"] is None
            event = db.execute(
                "SELECT payload FROM execution_events WHERE kind='OPTION_DISPATCH_REJECTED'"
            ).fetchone()
            assert json.loads(event[0])["reason"] == BLOCK


def test_hold_and_owned_close_remain_available_in_legacy_state(tmp_path):
    with native_owned(tmp_path) as (engine, venue, data):
        from test_option_admission import NOW

        buy = enter(engine, venue, data)
        legacy_enrollment(engine)
        hold = engine.prepare("hold", OptionProposal(action="HOLD", thesis="stand aside"), now=NOW)
        assert hold["status"] == "HOLD"
        close = engine.prepare(
            "exit",
            OptionProposal(action="CLOSE", contract=buy.instrument.contract, thesis="owned close"),
            data["quote"],
            now=NOW,
        )
        assert close["status"] == "PREPARED"
        assert intent_for(engine, close["client_id"]).side == "SELL"
        assert asyncio.run(engine.dispatch(close["client_id"], data["quote"], now=NOW)) == "OPEN"


def test_guard_survives_owner_restart(tmp_path):
    with owned(tmp_path) as (engine, venue, _):
        path, limits, epolicy = engine.journal.path, engine.limits, engine.policy
    with OptionExecution.open(path, limits, epolicy, venue, now=AT) as engine:
        ScopeWatchBook(engine, policy(), now=AT)
        from test_option_scope_watch import frame

        f = frame()
        _, _, u, _ = evidence(engine, f, 0)
        out = engine.prepare(
            "bypass",
            OptionProposal(
                action="OPEN_LONG",
                contract=f.metadata.instrument.contract,
                underlying_invalidation="99",
                thesis="restart",
            ),
            f.quote,
            u,
            now=AT,
        )
        assert out["status"] == "REJECTED" and out["reason"] == BLOCK
