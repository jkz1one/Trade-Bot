"""Actual owner races, signed limits, per-play exits and read-only two-card views."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from test_mixed_accounting import buy, changed
from test_mixed_native_owner import NOW, proposal, settings
from test_mixed_venue import q

from app.mixed.accounting import reconstruct
from app.mixed.native_models import PortfolioEnrollment
from app.mixed.portfolio_accounting import PortfolioPolicy
from app.mixed.portfolio_store import history, intent
from app.options.engine import OptionExecution
from app.options.operator import OptionsControl, sign
from app.options.operator_models import OptionsCommand
from app.options.venue import DurableOptionVenue


@contextmanager
def owned(tmp_path, *, at=NOW):
    limits, p = settings(
        portfolio=PortfolioEnrollment(exposure_limit="900", index_exposure_limit="900")
    )
    limits = changed(limits, max_account_exposure="950", allowed_underlyings=("SPY", "QQQ"))
    p = changed(
        p,
        mixed_owner=changed(
            p.mixed_owner,
            stocks=changed(p.mixed_owner.stocks, share_step=".1", max_entry_debit="250"),
        ),
    )
    pp = PortfolioPolicy(
        capital=p.capital,
        daily_loss_limit=p.daily_loss_limit,
        total_loss_limit=p.total_loss_limit,
        options=limits,
        stocks=p.mixed_owner.stocks,
        exposure_limit="900",
        index_exposure_limit="900",
    )
    v = DurableOptionVenue(
        tmp_path / "venue.db",
        limits=limits,
        stock_limits=p.mixed_owner.stocks,
        capital=p.capital,
        portfolio_policy=pp,
    )
    with OptionExecution.open(tmp_path / "owner.db", limits, p, v, now=at, create=True) as e:
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        yield e, v


def stock(symbol, at=NOW):
    pr = proposal(at)
    pr = changed(
        pr, instrument=changed(pr.instrument, symbol=symbol, instrument_id="stock-" + symbol)
    )
    return pr, changed(q(buy(at=at), at), instrument=pr.instrument)


def get_intent(e, client_id):
    with e.journal.read() as db:
        return intent(
            db.execute(
                "SELECT * FROM execution_portfolio_orders WHERE client_id=?", (client_id,)
            ).fetchone()
        )


def open_pair(e, v):
    entries = []
    for symbol in ("SPY", "QQQ"):
        pr, quote = stock(symbol)
        result = e.prepare_stock("entry-" + symbol, pr, quote, now=NOW)
        assert result["status"] == "PREPARED", result
        i = get_intent(e, result["client_id"])
        assert asyncio.run(e.dispatch_stock(i.client_id, quote, now=NOW)) == "OPEN"
        entries.append(i)
    at = NOW + timedelta(seconds=1)
    for i in entries:
        v.fill_stock(i, i.quantity, q(i, at), at, fill_id=i.client_id)
    assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
    return entries, at


def test_native_concurrent_reservations_cannot_claim_a_third_slot(tmp_path):
    with owned(tmp_path) as (e, _):

        def prepare(symbol):
            pr, quote = stock(symbol)
            return e.prepare_stock("race-" + symbol, pr, quote, now=NOW)

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(prepare, ("SPY", "QQQ", "IWM")))
        assert sorted(r["status"] for r in results) == ["PREPARED", "PREPARED", "REJECTED"]
        with e.journal.read() as db:
            projected = reconstruct(history(e, db, e.portfolio_policy, NOW))
        assert len(projected.commitments) == 2
        assert projected.reserved_cash <= projected.ledger.settled_cash


def test_signed_limit_reduction_keeps_positions_and_rejects_stale_revision(tmp_path):
    with owned(tmp_path) as (e, v):
        entries, at = open_pair(e, v)
        key = b"f" * 32
        OptionsControl.enroll(e, key, now=at)
        ctl = OptionsControl(e, key)
        with e.journal.read() as db:
            binding = db.execute("SELECT * FROM execution_operator").fetchone()
            revision = e.journal.revision(db)
        cmd = OptionsCommand(
            journal_id=binding["journal_id"],
            population_id=e.limits.population_id,
            credential_generation=1,
            command_id=uuid4().hex,
            actor="offline test",
            action="SET_MAX_PLAYS",
            max_plays=0,
            reason="Pause additional entries",
            expected_revision=revision,
            issued_at=at,
            expires_at=at + timedelta(seconds=60),
        )
        before = v.snapshot(at).positions
        with pytest.raises(ValueError, match="authentication"):
            ctl.apply(cmd, "0" * 64, now=at)
        result = ctl.apply(cmd, sign(cmd, key), now=at)
        assert result["status"] == "APPLIED", result
        assert ctl.apply(cmd, sign(cmd, key), now=at)["replayed"]
        stale = changed(cmd, command_id=uuid4().hex, max_plays=2)
        assert (
            ctl.apply(stale, sign(stale, key), now=at)["reason"] == "OPTION_REVIEW_REVISION_CHANGED"
        )
        with e.journal.read() as db:
            h = history(e, db, e.portfolio_policy, at)
        assert h.policy.max_plays == 0
        assert reconstruct(h).ledger.positions == before
        assert set(before) == {i.client_id for i in entries}
        for invalid in (-1, 3, True, "2"):
            with pytest.raises(ValueError):
                changed(cmd, max_plays=invalid)


def test_simultaneous_native_exits_preserve_each_thesis(tmp_path):
    with owned(tmp_path) as (e, v):
        entries, at = open_pair(e, v)
        at += timedelta(seconds=1)
        quotes = tuple(q(i, at, bid="89", ask="89.01") for i in entries)
        result = asyncio.run(e.protective_tick(now=at, stock_quotes=quotes))
        assert len(result["plays"]) == 2
        at += timedelta(seconds=1)
        for i in entries:
            result_i = result["plays"][i.client_id]
            assert result_i["status"] == "OPEN", result
            closing = get_intent(e, result_i["client_id"])
            assert closing.closing_entry_client_id == i.client_id
            assert closing.thesis == i.thesis
            v.fill_stock(
                closing,
                closing.quantity,
                q(closing, at, bid="89", ask="89.01"),
                at,
                fill_id="exit-" + i.client_id,
            )
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        loss = e.refresh_loss_control(now=at)
        assert loss["consumed_entries"] == 2 and loss["locked"]
        assert e.refresh_loss_control(now=at) == loss
        with e.journal.read() as db:
            assert not reconstruct(history(e, db, e.portfolio_policy, at)).ledger.positions


def test_two_play_observer_and_render_keep_distinct_cards_and_unknown_marks(tmp_path):
    from app.mixed.observer import MixedObserver
    from app.web.mixed_view import mixed_view
    from app.web.options import templates

    with owned(tmp_path) as (e, v):
        entries, at = open_pair(e, v)
        for i in entries:
            e.assess_stock(q(i, at), now=at, play_id=i.client_id)
        with e.journal.read() as db:
            revision = e.journal.revision(db)
        observer = MixedObserver(e.journal.path, e.limits.population_id, clock=lambda: at)
        report = observer.report()
        assert report["status"] == "OK", report
        assert {p["play_id"] for p in report["positions"]} == {i.client_id for i in entries}
        html = templates.env.get_template("mixed_content.html").render(
            data=report, view=mixed_view(report)
        )
        assert 'data-tabs="plays"' in html
        assert html.count("data-play-id=") == 2
        assert html.count("Exact levels and original targets") == 2
        assert all(i.client_id in html for i in entries)
        from html.parser import HTMLParser

        class IDs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = []

            def handle_starttag(self, tag, attrs):
                self.ids.extend(v for k, v in attrs if k == "id")

        parser = IDs()
        parser.feed(html)
        assert len(set(parser.ids)) == len(parser.ids)
        at += timedelta(minutes=2)
        stale = observer.report()
        assert stale["status"] == "OK", stale
        assert stale["equity"] is None
        assert all(p["mark"] is None and p["gross_unrealized"] is None for p in stale["positions"])
        with e.journal.read() as db:
            assert e.journal.revision(db) == revision


def test_approval_event_tampering_blocks_reconciliation(tmp_path):
    with owned(tmp_path) as (e, v):
        pr, quote = stock("SPY")
        result = e.prepare_stock("entry", pr, quote, now=NOW)
        assert result["status"] == "PREPARED"
        with e.journal.write() as db:
            db.execute("UPDATE execution_events SET payload='{}' WHERE kind='PORTFOLIO_RESERVED'")
        result = e.reconcile(v.snapshot(NOW), now=NOW)
        assert not result["reconciled"]
        assert result["issues"] == ["PORTFOLIO_ORIGINAL_APPROVAL_EVIDENCE_CHANGED"]
