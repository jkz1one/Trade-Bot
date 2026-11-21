"""A later unselected Scope watch cannot rewrite the shared entry's alternatives."""

import asyncio
from datetime import timedelta
from decimal import Decimal

from test_option_execution import intent_for
from test_option_scope_arbitration import shared
from test_option_scope_execution import sell
from test_option_scope_watch import revision

from app.options.scope_execution_export import export_scope_execution, verify_scope_execution_export


def test_unselected_scope_history_survives_later_watch_termination(tmp_path):
    with shared(tmp_path, ("DEGEN", "SCOPE")) as (c, v, times, f):
        out = asyncio.run(c.cycle(f))
        assert out["status"] == "OPEN", out
        buy = intent_for(c.engine, out["client_id"])
        v.fill(
            buy, buy.quantity, f.quotes[0], times[0], fill_id="entry", underlying=f.underlyings[0]
        )
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] += timedelta(seconds=1)
        target = Decimal(out["scope_candidate"]["geometry"]["target_two"])
        q = f.scope.underlying.model_copy(
            update={"source_at": times[0], "received_at": times[0], "bid": target, "ask": target}
        )
        ended = c.scope_book.observe_quote(
            "later-target", "first", q, expected_revision=revision(c.engine), now=times[0]
        )
        assert ended["record"]["status"] != "WATCHING"
        option = f.quotes[0].model_copy(update={"source_at": times[0], "received_at": times[0]})
        underlying = f.underlyings[0].model_copy(
            update={"source_at": times[0], "received_at": times[0]}
        )
        sell(c.engine, v, buy, option, underlying, times[0])
        exported = export_scope_execution(
            c.engine.journal, now=times[0], data_cost="0", host_cost="0"
        )
        assert (
            verify_scope_execution_export(exported, exported["export_hash"])["accounting_status"]
            == "COMPLETE_FLAT_ACCOUNTING"
        )
        assert exported["report"]["orders"][0]["scope_arbitration"] == out["scope_arbitration"]


def test_ended_scope_watch_needs_no_scope_input(tmp_path):
    with shared(tmp_path) as (c, _, times, f):
        target = Decimal(c.scope_book.snapshot()["watches"][0]["geometry"]["target_two"])
        u = f.scope.underlying.model_copy(update={"bid": target, "ask": target})
        c.scope_book.observe_quote(
            "target-before-cycle", "first", u, expected_revision=revision(c.engine), now=times[0]
        )
        out = asyncio.run(c.cycle(f.model_copy(update={"scope": None})))
        assert out["status"] == "OPEN", out
        assert out["scope_arbitration"]["selected"]["family"] == "DEGEN"
        assert out["scope_candidate"] is None


def test_carry_enrollment_cannot_lose_strategy_to_use_legacy_path(tmp_path):
    from test_degen_options import AT
    from test_option_swing_execution import carry_frame, carry_owner, entered

    with carry_owner(tmp_path) as (c, v, _):
        entered(c, v, carry_frame())
        with c.engine.journal.write() as db:
            db.execute("DELETE FROM execution_option_strategy")
        result = c.engine.reconcile(v.snapshot(AT), now=AT)
        assert not result["reconciled"], result
