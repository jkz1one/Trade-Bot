"""Held Swing consumes one shared slot and retains its original locked seed."""

import asyncio
from datetime import timedelta

from test_mixed_native_owner import changed
from test_option_scope_arbitration import shared
from test_portfolio_controls import get_intent


def test_paid_swing_uses_original_shared_scope_shortlist_and_one_call(tmp_path, monkeypatch):
    from test_option_scope_ai import ai_owner

    with ai_owner(tmp_path, monkeypatch, portfolio=True, family="SWING") as (
        c,
        v,
        _times,
        frame,
        _,
    ):
        result = asyncio.run(c.cycle(frame))
        chosen = result["entries"][0]
        assert chosen["status"] == "OPEN", {
            k: v for k, v in chosen.items() if k in {"status", "reason", "blocker", "prepared"}
        }
        entry = get_intent(c.engine, chosen["client_id"])
        assert entry.entry_lineage.family == "SWING" and v.submit_count == 1
        with c.engine.journal.read() as db:
            from app.mixed.paid_costs import records

            assert len(records(db, c.engine.policy)) == 1
            assert records(db, c.engine.policy)[0].entry_client_id == entry.client_id


def test_swing_and_scope_share_one_owner_with_two_original_native_approvals(tmp_path):
    with shared(tmp_path, priority=("SWING", "SCOPE", "DEGEN"), portfolio=True) as (
        c,
        v,
        times,
        frame,
    ):
        from decimal import Decimal

        from test_option_scope_arming import refresh

        frame = changed(
            frame,
            quotes=tuple(
                changed(q, ask_size=1, bid=Decimal(".49"), ask=Decimal(".50")) for q in frame.quotes
            ),
        )
        first = asyncio.run(c._cycle_once(frame, portfolio_slot=0))
        assert first["status"] == "OPEN", first.get("reason")
        swing = get_intent(c.engine, first["client_id"])
        assert swing.entry_lineage.family == "SWING"
        q = next(q for q in frame.quotes if q.instrument == swing.instrument)
        u = next(u for u in frame.underlyings if u.symbol == swing.instrument.contract.underlying)
        v.fill(swing, swing.quantity, q, times[0], fill_id="swing-entry", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        times[0] += timedelta(seconds=1)
        fresh, context = refresh(frame.scope.frame, times[0])
        frame = changed(
            frame,
            scope=changed(
                frame.scope,
                frame=fresh,
                context=context,
                underlying=changed(
                    frame.scope.underlying, source_at=times[0], received_at=times[0]
                ),
            ),
        )
        out = asyncio.run(c.cycle(frame))
        assert [x["status"] for x in out["entries"]] == ["OPEN", "OPEN"], [
            (
                x.get("status"),
                x.get("reason"),
                x.get("scope_review", {}).get("admission_review", {}).get("reasons"),
            )
            for x in out["entries"]
        ]
        scope = get_intent(c.engine, out["entries"][1]["client_id"])
        entries = [swing, scope]
        assert scope.entry_lineage.family == "SCOPE" and v.submit_count == 2
        v.fill(
            scope,
            scope.quantity,
            frame.scope.frame.quote,
            times[0],
            fill_id="scope-entry",
            underlying=frame.scope.underlying,
        )
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        held = v.snapshot(times[0]).positions
        assert len(held) == 2
        assert all(get_intent(c.engine, i.client_id).thesis == i.thesis for i in entries)
        times[0] += timedelta(seconds=1)
        out = asyncio.run(c.cycle(changed(frame)))
        assert out["reason"] == "PLAY_CAPACITY" and v.submit_count == 2
        from app.mixed.observer import MixedObserver
        from app.web.mixed_view import mixed_view
        from app.web.options import templates

        report = MixedObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: times[0]
        ).report()
        assert report["status"] == "OK", report.get("reason")
        html = templates.env.get_template("mixed_content.html").render(
            data=report, view=mixed_view(report)
        )
        assert html.count("data-play-id=") == 2 and all(i.client_id in html for i in entries)
        assert html.count("Exact levels and original targets") == 2
        target = scope.target_exit_schedule.steps[0].underlying_price
        q = changed(frame.scope.frame.quote, source_at=times[0], received_at=times[0])
        u = changed(
            frame.scope.underlying, bid=target, ask=target, source_at=times[0], received_at=times[0]
        )
        protected = asyncio.run(
            c.engine.protective_tick(option_quotes=(q,), underlyings=(u,), now=times[0])
        )
        result = protected["plays"][scope.client_id]
        assert result["status"] == "OPEN", result
        assert protected["plays"][swing.client_id]["status"] == "BLOCKED"
        sale = get_intent(c.engine, result["client_id"])
        assert sale.closing_entry_client_id == scope.client_id and sale.quantity < scope.quantity
        v.fill(sale, sale.quantity, q, times[0], fill_id="scope-target", underlying=u)
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        after = v.snapshot(times[0]).positions
        assert after[swing.client_id] == held[swing.client_id]
        assert after[scope.client_id].quantity == scope.quantity - sale.quantity
