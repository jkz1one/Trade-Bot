"""Two-play native owner preparation, process dispatch and journal reconciliation."""

import asyncio
from datetime import timedelta

from test_mixed_accounting import changed
from test_mixed_native_owner import NOW, proposal, settings
from test_mixed_venue import q

from app.mixed.accounting import reconstruct
from app.mixed.native_models import PortfolioEnrollment
from app.mixed.portfolio_accounting import PortfolioPolicy
from app.mixed.portfolio_store import history, intent
from app.options.engine import OptionExecution
from app.options.venue import DurableOptionVenue


def test_native_two_pending_stock_entries_fill_and_close_independently(tmp_path):
    limits, p = settings(
        portfolio=PortfolioEnrollment(exposure_limit="900", index_exposure_limit="900")
    )
    limits = changed(limits, max_account_exposure="950")
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
    with OptionExecution.open(tmp_path / "owner.db", limits, p, v, now=NOW, create=True) as e:
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        orders = []
        for n, symbol in enumerate(("SPY", "QQQ")):
            pr = proposal(NOW)
            pr = changed(
                pr,
                instrument=changed(pr.instrument, symbol=symbol, instrument_id="stock-" + symbol),
            )
            from test_mixed_accounting import buy

            quote = changed(q(buy(at=NOW), NOW), instrument=pr.instrument)
            result = e.prepare_stock("entry-" + symbol, pr, quote, now=NOW)
            assert result["status"] == "PREPARED", result
            with e.journal.read() as db:
                i = intent(
                    db.execute(
                        "SELECT * FROM execution_portfolio_orders WHERE client_id=?",
                        (result["client_id"],),
                    ).fetchone()
                )
            orders.append((i, quote))
        blocked = e.prepare_stock("third", pr, quote, now=NOW)
        assert blocked["status"] == "REJECTED" and "PLAY_CAPACITY" in blocked["reason"]
        for i, quote in orders:
            assert asyncio.run(e.dispatch_stock(i.client_id, quote, now=NOW)) == "OPEN"
        at = NOW + timedelta(seconds=1)
        for i, quote in orders:
            v.fill_stock(
                i, i.quantity, changed(quote, source_at=at, received_at=at), at, fill_id=i.client_id
            )
        outcome = e.reconcile(v.snapshot(at), now=at)
        assert outcome["reconciled"], outcome
        with e.journal.read() as db:
            projection = reconstruct(history(e, db, pp, at))
        assert len(projection.ledger.positions) == 2
        a, b = (i for i, _ in orders)
        blocked = e.assess_stock(None, now=at, play_id=b.client_id)
        assert blocked["status"] == "BLOCKED"
        healthy = e.assess_stock(q(a, at), now=at, play_id=a.client_id)
        assert healthy["status"] == "HEALTHY"
        from app.mixed.models import StockProposal

        pr = StockProposal(action="CLOSE", instrument=a.instrument, thesis="Close one exact play")
        quote = q(a, at, bid="102", ask="102.01")
        closing = e.prepare_stock("exit-a", pr, quote, now=at, play_id=a.client_id)
        assert closing["status"] == "PREPARED", closing
        with e.journal.read() as db:
            i = intent(
                db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE client_id=?",
                    (closing["client_id"],),
                ).fetchone()
            )
        assert asyncio.run(e.dispatch_stock(i.client_id, quote, now=at)) == "OPEN"
        at += timedelta(seconds=1)
        v.fill_stock(
            i, i.quantity, changed(quote, source_at=at, received_at=at), at, fill_id="exit-a"
        )
        outcome = e.reconcile(v.snapshot(at), now=at)
        assert outcome["reconciled"], outcome
        with e.journal.read() as db:
            after = reconstruct(history(e, db, pp, at))
        assert set(after.ledger.positions) == {b.client_id}
        assert after.ledger.positions[b.client_id] == projection.ledger.positions[b.client_id]

    with OptionExecution.open(
        tmp_path / "owner.db", limits, p, DurableOptionVenue(v.path), now=at
    ) as restarted:
        assert asyncio.run(restarted.reconcile_fixture(now=at))["reconciled"]
        with restarted.journal.read() as db:
            recovered = reconstruct(history(restarted, db, pp, at))
        assert recovered == after


def test_native_mixed_stock_option_reservations_and_independent_option_exit(tmp_path):
    """Original candidate fixture is recorded; native risk is freshly reviewed twice."""
    import json

    from test_mixed_accounting import buy
    from test_option_execution import configuration

    from app.mixed.portfolio_admission import admit_portfolio_option
    from app.options.engine import fingerprint
    from app.options.models import OptionAdmission, OptionProposal
    from app.options.selection import DegenCandidate

    data, _, _ = configuration()
    limits, p = settings(
        portfolio=PortfolioEnrollment(exposure_limit="900", index_exposure_limit="900")
    )
    limits = changed(limits, max_account_exposure="950")
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
    with OptionExecution.open(tmp_path / "owner.db", limits, p, v, now=NOW, create=True) as e:
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        pr = proposal(NOW)
        pr = changed(pr, instrument=changed(pr.instrument, symbol="QQQ", instrument_id="stock-qqq"))
        sq = changed(q(buy(at=NOW), NOW), instrument=pr.instrument)
        stock = e.prepare_stock("stock", pr, sq, now=NOW)
        assert stock["status"] == "PREPARED", stock
        with e.journal.write() as db:
            h = history(e, db, pp, NOW)
            admitted = admit_portfolio_option(
                data["proposal"],
                data["quote"],
                data["underlying"],
                h,
                e._session(data["proposal"].contract, NOW),
                now=NOW,
                reconciled=True,
            )
            assert admitted.outcome == "APPROVED", admitted
            original = OptionAdmission(
                **admitted.model_dump(
                    exclude={"policy_version", "history_hash", "proposal_hash", "play_id"}
                )
            )
            candidate = DegenCandidate(
                candidate_id=fingerprint(data["proposal"]),
                symbol="SPY",
                family="ORB_CONTINUATION",
                instrument=data["quote"].instrument,
                proposal=data["proposal"],
                admission=original,
            )
            db.execute(
                "CREATE TABLE execution_option_opportunities(cycle_key TEXT PRIMARY KEY,result_json TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO execution_option_opportunities VALUES(?,?)",
                (
                    "option",
                    json.dumps(
                        {
                            "candidate_id": candidate.candidate_id,
                            "candidates": [candidate.model_dump(mode="json")],
                        }
                    ),
                ),
            )
            e.journal.event(
                db,
                NOW,
                "FIXTURE_ORIGINAL_SELECTION_RECORDED",
                {"candidate_hash": fingerprint(candidate)},
            )
        option = e.prepare("option", data["proposal"], data["quote"], data["underlying"], now=NOW)
        assert option["status"] == "PREPARED", option
        with e.journal.read() as db:
            oi = intent(
                db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE client_id=?",
                    (option["client_id"],),
                ).fetchone()
            )
            si = intent(
                db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE client_id=?",
                    (stock["client_id"],),
                ).fetchone()
            )
        assert asyncio.run(e.dispatch_stock(si.client_id, sq, now=NOW)) == "OPEN"
        assert (
            asyncio.run(e.dispatch(oi.client_id, data["quote"], data["underlying"], now=NOW))
            == "OPEN"
        )
        at = NOW + timedelta(seconds=1)
        sq = changed(sq, source_at=at, received_at=at)
        data["quote"] = changed(data["quote"], source_at=at, received_at=at)
        data["underlying"] = changed(data["underlying"], source_at=at, received_at=at)
        v.fill_stock(si, si.quantity, sq, at, fill_id="stock-fill")
        v.fill(
            oi,
            oi.quantity,
            data["quote"],
            at,
            fill_id="option-fill",
            underlying=data["underlying"],
        )
        result = e.reconcile(v.snapshot(at), now=at)
        assert result["reconciled"], result
        before = v.snapshot(at)
        closing = e.prepare(
            "option-close",
            OptionProposal(
                action="CLOSE", contract=oi.instrument.contract, thesis="Close exact option"
            ),
            data["quote"],
            data["underlying"],
            now=at,
            play_id=oi.client_id,
        )
        assert closing["status"] == "PREPARED", closing
        with e.journal.read() as db:
            ci = intent(
                db.execute(
                    "SELECT * FROM execution_portfolio_orders WHERE client_id=?",
                    (closing["client_id"],),
                ).fetchone()
            )
        assert (
            asyncio.run(e.dispatch(ci.client_id, data["quote"], data["underlying"], now=at))
            == "OPEN"
        )
        v.fill(
            ci,
            ci.quantity,
            data["quote"],
            at,
            fill_id="option-exit",
            underlying=data["underlying"],
        )
        result = e.reconcile(v.snapshot(at), now=at)
        assert result["reconciled"], result
        assert v.snapshot(at).positions == {si.client_id: before.positions[si.client_id]}
