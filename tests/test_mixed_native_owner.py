"""Actual common native owner, fixed child, full-cost loss and independent exits."""

import asyncio
import json
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from test_mixed_accounting import buy, changed, policy
from test_mixed_venue import q
from test_option_execution import NOW, configuration

from app.execution.engine import ExecutionBlocked
from app.mixed.models import StockProposal
from app.mixed.native_models import MixedOwnerPolicy
from app.mixed.native_store import position, protection
from app.mixed.stock_models import StockIntent
from app.options.engine import OptionExecution
from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy
from app.options.venue import DurableOptionVenue

D = Decimal


def settings(**changes):
    _, limits, p = configuration()
    stocks = changed(policy().stocks, max_shares="2")
    mixed = MixedOwnerPolicy.model_validate(
        {
            "stocks": stocks,
            "daily_data_cost": "0",
            "daily_host_cost": "0",
            "daily_operating_cost": "0",
            **changes,
        }
    )
    loss = NativeLossPolicy(
        max_consecutive_losses=2,
        cooldown_seconds=1800,
        families=tuple(
            FamilyLossPolicy(family=f, max_consecutive_losses=2, cooldown_seconds=1800)
            for f in ("DEGEN", "SWING", "SCOPE")
        ),
    )
    return limits, changed(p, mixed_owner=mixed, loss_control=loss)


@contextmanager
def owned_mixed(tmp_path, **changes):
    limits, p = settings(**changes)
    v = DurableOptionVenue(
        tmp_path / "venue.db", limits=limits, stock_limits=p.mixed_owner.stocks, capital=p.capital
    )
    with OptionExecution.open(tmp_path / "engine.db", limits, p, v, now=NOW, create=True) as e:
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        e.assess_stock(None, now=NOW)
        yield e, v


def proposal(at=NOW, **changes):
    i = buy(at=at)
    base = StockProposal(
        action="OPEN_LONG",
        instrument=i.instrument,
        source_hash=i.source_hash,
        family=i.family,
        source_at=i.source_at,
        valid_until=i.source_valid_until,
        exit_at=i.exit_at,
        original_invalidation=i.original_invalidation,
        original_target=i.original_target,
        thesis=i.thesis,
    )
    return changed(base, **changes)


def intent_for(e, client):
    with e.journal.read() as db:
        return StockIntent.model_validate_json(
            db.execute(
                "SELECT intent_json FROM execution_stock_orders WHERE client_id=?", (client,)
            ).fetchone()[0]
        )


def enter(e, v, *, at=NOW, key="stock-entry", quantity="2"):
    pr = proposal(at)
    quote = q(buy(at=at), at)
    out = e.prepare_stock(key, pr, quote, now=at)
    assert out["status"] == "PREPARED", out
    intent = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch_stock(intent.client_id, quote, now=at)) == "OPEN"
    when = at + timedelta(seconds=1)
    v.fill_stock(intent, quantity, q(intent, when), when, fill_id=key + "-fill")
    result = e.reconcile(v.snapshot(when), now=when)
    assert result["reconciled"], result
    e.assess_stock(q(intent, when), now=when)
    return intent, when


def close(e, v, entry, at, *, bid="102", quantity=None, key="stock-close"):
    pr = StockProposal(
        action="CLOSE", instrument=entry.instrument, thesis="Close original owned stock"
    )
    quote = q(entry, at, bid=bid, ask=str(D(bid) + D(".01")))
    out = e.prepare_stock(key, pr, quote, now=at, close_quantity=quantity)
    assert out["status"] == "PREPARED", out
    intent = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch_stock(intent.client_id, quote, now=at)) == "OPEN"
    when = at + timedelta(seconds=1)
    v.fill_stock(
        intent,
        intent.quantity,
        q(intent, when, bid=bid, ask=str(D(bid) + D(".01"))),
        when,
        fill_id=key + "-fill",
    )
    result = e.reconcile(v.snapshot(when), now=when)
    assert result["reconciled"], result
    return intent, when


def test_native_owner_stock_roundtrip_and_full_cost_loss_state(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        a = e.mixed_account(now=at)
        assert a.cash == D("799.88") and a.position.symbol == "SPY" and a.working_orders == 0
        assert e.journal.report(now=at)["mode"] == "MIXED_PAPER_FIXTURE"
        _, at = close(e, v, entry, at + timedelta(seconds=1))
        report = e.journal.report(now=at)
        assert report["stock_position"] is None
        assert report["ledger"]["cash"] == "1003.76"
        assert report["loss_control"]["consumed_entries"] == 1
        with e.journal.read() as db:
            record = json.loads(
                db.execute("SELECT record_json FROM execution_option_loss_outcomes").fetchone()[0]
            )
        assert record["entry_kind"] == "STOCK" and record["net_after_all_costs"] == "3.76"
        assert len(record["operating_allocations"]) == 3


def test_native_protection_latches_target_rebound_and_restart(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        result = e.assess_stock(q(entry, at, bid="120", ask="120.01"), now=at)
        assert result["exit_reason"] == "STOCK_TARGET"
        assert e.assess_stock(q(entry, at), now=at)["exit_reason"] == "STOCK_TARGET"
        limits, p = e.limits, e.policy
    with OptionExecution.open(tmp_path / "engine.db", limits, p, v, now=at) as e:
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        with e.journal.read() as db:
            assert protection(e, db).exit_reason == "STOCK_TARGET"
        out = asyncio.run(
            e.protective_stock_tick(
                q(entry, at + timedelta(seconds=1)), now=at + timedelta(seconds=1)
            )
        )
        assert out["status"] == "OPEN", out


def test_native_partial_close_and_tighten_preserve_original(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        e.tighten_stock_invalidation("95", q(entry, at), now=at)
        with pytest.raises(ExecutionBlocked):
            e.tighten_stock_invalidation("94", q(entry, at), now=at)
        _, at = close(e, v, entry, at + timedelta(seconds=1), quantity="1")
        with e.journal.read() as db:
            held = position(e, db)
            guard = protection(e, db)
            assert held.quantity == 1 and held.entry == entry and guard.invalidation == 95
        assert e.journal.report(now=at)["loss_control"]["consumed_entries"] == 0
        _, at = close(e, v, entry, at + timedelta(seconds=1), key="rest")
        assert e.journal.report(now=at)["loss_control"]["consumed_entries"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_hash", "f" * 64),
        ("family", "DEGEN"),
        ("original_invalidation", "91"),
        ("original_target", "121"),
        ("exit_at", NOW + timedelta(minutes=11)),
        ("thesis", "Replacement thesis"),
        ("quantity", "1"),
        ("limit_price", "101"),
        ("account_revision", 0),
    ],
)
def test_rehashed_stock_intent_cannot_replace_original_native_admission(tmp_path, field, value):
    from app.options.engine import fingerprint

    with owned_mixed(tmp_path) as (e, v):
        quote = q(buy(at=NOW), NOW)
        out = e.prepare_stock("entry", proposal(), quote, now=NOW)
        client = out["client_id"]
        with e.journal.write() as db:
            row = db.execute("SELECT * FROM execution_stock_orders").fetchone()
            intent = changed(StockIntent.model_validate_json(row["intent_json"]), **{field: value})
            approval = json.loads(row["approval_json"])
            approval["intent_terms"] = intent.model_dump(mode="json", exclude={"approval_hash"})
            intent = changed(intent, approval_hash=fingerprint(approval))
            db.execute(
                "UPDATE execution_stock_orders SET intent_json=?,approval_json=?",
                (intent.model_dump_json(), json.dumps(approval)),
            )
        assert asyncio.run(e.dispatch_stock(client, quote, now=NOW)) == "REJECTED"
        assert v.submit_count == 0


@pytest.mark.parametrize("kind", ["expired", "stale_account", "higher_price", "stale_quote"])
def test_dispatch_requires_original_deadline_and_fresh_full_admission(tmp_path, kind):
    with owned_mixed(tmp_path) as (e, v):
        quote = q(buy(at=NOW), NOW)
        out = e.prepare_stock("entry", proposal(), quote, now=NOW)
        intent = intent_for(e, out["client_id"])
        at = NOW + timedelta(seconds=1)
        if kind == "expired":
            at = intent.approval_expires_at
        elif kind == "stale_account":
            at = NOW + timedelta(seconds=e.limits.account_max_age_seconds)
        quote = q(intent, at)
        if kind == "higher_price":
            quote = changed(quote, bid="101", ask="101.01")
        elif kind == "stale_quote":
            quote = changed(quote, source_at=NOW - timedelta(minutes=1), received_at=at)
        assert asyncio.run(e.dispatch_stock(intent.client_id, quote, now=at)) == "REJECTED"
        assert v.submit_count == 0


@pytest.mark.parametrize("first", ["stock", "option"])
def test_one_native_lock_and_cross_instrument_source_identity(tmp_path, first):
    with owned_mixed(tmp_path) as (e, v):
        data, _, _ = configuration()
        quote = q(buy(at=NOW), NOW)

        def stock(key):
            return e.prepare_stock(key, proposal(), quote, now=NOW)

        def option(key):
            return e.prepare(key, data["proposal"], data["quote"], data["underlying"], now=NOW)

        a, b = (stock, option) if first == "stock" else (option, stock)
        if first == "option":
            from test_option_family_loss import seed

            seed(e, v, data, "same", "DEGEN", NOW)
        first_result = a("same")
        assert first_result["status"] == "PREPARED", first_result
        with pytest.raises(ExecutionBlocked, match="MIXED_SOURCE"):
            b("same")
        assert b("different")["status"] == "REJECTED"
        assert v.submit_count == 0 and e.mixed_account(now=NOW).working_orders == 1


def test_unknown_stock_attempt_reconciles_without_replay(tmp_path):
    limits, p = settings()
    v = DurableOptionVenue(
        tmp_path / "venue.db",
        limits=limits,
        stock_limits=p.mixed_owner.stocks,
        capital=p.capital,
        fault="LOST_ACK",
    )
    with OptionExecution.open(tmp_path / "engine.db", limits, p, v, now=NOW, create=True) as e:
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        e.assess_stock(None, now=NOW)
        quote = q(buy(at=NOW), NOW)
        out = e.prepare_stock("uncertain", proposal(), quote, now=NOW)
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "UNKNOWN"
        assert v.submit_count == 1
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "UNKNOWN"
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "OPEN"
        assert e.mixed_account(now=NOW).entry_halted
        assert v.submit_count == 1


def test_interrupted_stock_attempt_restores_unknown_and_missing_evidence_blocks(tmp_path):
    from app.mixed.native_execution import begin

    with owned_mixed(tmp_path) as (e, v):
        quote = q(buy(at=NOW), NOW)
        out = e.prepare_stock("interrupted", proposal(), quote, now=NOW)
        assert isinstance(begin(e, out["client_id"], quote, NOW), StockIntent)
        limits, p = e.limits, e.policy
    with OptionExecution.open(tmp_path / "engine.db", limits, p, v, now=NOW) as e:
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=NOW)) == "UNKNOWN"
        result = e.reconcile(v.snapshot(NOW), now=NOW)
        assert not result["reconciled"] and "STOCK_ATTEMPT_OR_FILL_HISTORY_MISSING" in str(result)
        assert v.submit_count == 0


@pytest.mark.parametrize("kind", ["intent", "missing", "sequence", "fee", "cash", "position"])
def test_mixed_reconciliation_rejects_changed_stock_evidence(tmp_path, kind):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        snapshot = v.snapshot(at)
        obs = snapshot.stock_orders[0]
        if kind == "intent":
            snapshot = changed(
                snapshot, stock_orders=(changed(obs, intent=changed(entry, thesis="Changed")),)
            )
        elif kind == "missing":
            snapshot = changed(snapshot, stock_orders=())
        elif kind in {"sequence", "fee"}:
            fields = {"sequence": 2} if kind == "sequence" else {"fee": D("0")}
            snapshot = changed(
                snapshot, stock_orders=(changed(obs, fills=(changed(obs.fills[0], **fields),)),)
            )
        elif kind == "cash":
            snapshot = changed(snapshot, cash=snapshot.cash + 1)
        else:
            snapshot = changed(snapshot, stock_position=None)
        before = e.journal.report(now=at)["ledger"]
        result = e.reconcile(snapshot, now=at)
        assert not result["reconciled"], result
        assert e.journal.report(now=at)["ledger"] == before


def test_operating_cost_turns_gross_stock_win_into_full_cost_loss(tmp_path):
    with owned_mixed(tmp_path, daily_operating_cost="5") as (e, v):
        entry, at = enter(e, v)
        _, at = close(e, v, entry, at + timedelta(seconds=1))
        report = e.journal.report(now=at)
        loss = report["loss_control"]
        assert loss["consecutive_losses"] == 1
        assert (
            next(f for f in loss["families"] if f["family"] == entry.family)["consecutive_losses"]
            == 1
        )
        assert e.mixed_account(now=at).total_loss_available == D("798.76")
        with e.journal.read() as db:
            record = json.loads(
                db.execute("SELECT record_json FROM execution_option_loss_outcomes").fetchone()[0]
            )
        assert record["net_after_all_costs"] == "-1.24"
        assert report["ledger"]["cash"] == "1003.76"
        e.assess_stock(None, now=at)
        next_proposal = e.prepare_stock("cooldown", proposal(at), q(entry, at), now=at)
        assert next_proposal["status"] == "REJECTED" and "COOLDOWN" in str(next_proposal)


@pytest.mark.parametrize("cost", ["daily_data_cost", "daily_host_cost", "daily_operating_cost"])
def test_unknown_operating_allocation_blocks_both_asset_entries(tmp_path, cost):
    with owned_mixed(tmp_path, **{cost: None}) as (e, v):
        assert not e.mixed_account(now=NOW).budgets_known
        assert (
            e.prepare_stock("stock", proposal(), q(buy(at=NOW), NOW), now=NOW)["status"]
            == "REJECTED"
        )
        data, _, _ = configuration()
        assert (
            e.prepare("option", data["proposal"], data["quote"], data["underlying"], now=NOW)[
                "status"
            ]
            == "REJECTED"
        )
        assert v.submit_count == 0


def test_unbound_model_charge_never_unlocks_entries_or_suppresses_owned_exit(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        with e.journal.write() as db:
            db.execute(
                "INSERT INTO execution_model_calls VALUES(?,?,?,NULL,NULL,NULL,NULL)",
                ("unbound", "a" * 64, at.isoformat()),
            )
        assert not e.mixed_account(now=at).budgets_known
        assert (
            e.assess_stock(q(entry, at, bid="80", ask="80.01"), now=at)["exit_reason"]
            == "STOCK_INVALIDATION"
        )
        _, at = close(e, v, entry, at + timedelta(seconds=1), bid="80")
        report = e.journal.report(now=at)
        assert report["stock_position"] is None
        assert report["loss_control"]["consumed_entries"] == 0
        assert "MIXED_PAID_CONTRACT_NOT_ENROLLED" in report["loss_control"]["reasons"]


@pytest.mark.parametrize("cause", ["stop", "target", "time"])
def test_independent_stock_exit_survives_rebound_and_halt(tmp_path, cause):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        if cause == "time":
            at = entry.exit_at
            assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
            result = e.assess_stock(None, now=at)
            assert result["status"] == "BLOCKED"
        else:
            bid = "80" if cause == "stop" else "120"
            result = e.assess_stock(q(entry, at, bid=bid, ask=str(D(bid) + D(".01"))), now=at)
        reason = {
            "stop": "STOCK_INVALIDATION",
            "target": "STOCK_TARGET",
            "time": "STOCK_TIME_EXIT",
        }[cause]
        assert result["exit_reason"] == reason
        with e.journal.write() as db:
            e._halt(db, "TEST_HALT", at)
        result = asyncio.run(e.protective_stock_tick(q(entry, at), now=at))
        assert result["status"] == "OPEN" and result["exit_reason"] == reason, result
        close_intent = intent_for(e, result["client_id"])
        assert close_intent.closing_entry_client_id == entry.client_id
        assert close_intent.quantity == 2 and close_intent.thesis == entry.thesis


def test_mandatory_stock_exit_supersedes_only_unattempted_partial_close(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        quote = q(entry, at)
        partial = e.prepare_stock(
            "partial",
            StockProposal(action="CLOSE", instrument=entry.instrument, thesis="Partial"),
            quote,
            now=at,
            close_quantity="1",
        )
        assert partial["status"] == "PREPARED"
        e.assess_stock(q(entry, at, bid="120", ask="120.01"), now=at)
        out = asyncio.run(e.protective_stock_tick(quote, now=at))
        assert out["status"] == "OPEN", out
        assert intent_for(e, out["client_id"]).quantity == 2
        assert asyncio.run(e.dispatch_stock(partial["client_id"], quote, now=at)) == "REJECTED"
        assert v.submit_count == 2


def test_native_owner_rejects_unbound_models_and_option_only_exports(tmp_path):
    from app.options.evaluation_models import ArmDefinition
    from app.options.scope_execution_export import export_scope_execution

    with owned_mixed(tmp_path) as (e, v):
        with pytest.raises(ExecutionBlocked, match="MIXED"):
            e.begin_model_attempt("paid", "a" * 64, now=NOW)
        with pytest.raises(ValueError, match="Mixed replay/export"):
            ArmDefinition(arm="A", limits=e.limits, policy=e.policy, strategy_hash="a" * 64)
        with pytest.raises(ValueError, match="Mixed Scope export"):
            export_scope_execution(e.journal, now=NOW)
        assert v.submit_count == 0


def test_stock_carry_not_silently_shortened_into_supported_session(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        out = e.prepare_stock(
            "carry", proposal(exit_at=NOW + timedelta(days=1)), q(buy(at=NOW), NOW), now=NOW
        )
        assert out["status"] == "REJECTED" and "STOCK_CARRY_NOT_ENROLLED" in str(out)
        assert v.submit_count == 0


def test_native_stock_option_stock_uses_one_capital_and_shared_loss_state(tmp_path):
    from test_option_execution import intent_for as option_intent
    from test_option_execution import quote_at, underlying_at

    from app.options.lifecycle import OptionReceipt
    from app.options.models import OptionProposal

    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        _, at = close(e, v, entry, at + timedelta(seconds=1))
        data, _, _ = configuration()
        at += timedelta(seconds=1)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        e.assess(None, None, now=at)
        oq, u = quote_at(data, at), underlying_at(data, at)
        from test_option_family_loss import seed

        seed(e, v, data, "option-entry", "DEGEN", at)
        out = e.prepare("option-entry", data["proposal"], oq, u, now=at)
        assert out["status"] == "PREPARED", out
        opt = option_intent(e, out["client_id"])
        assert asyncio.run(e.dispatch(opt.client_id, oq, u, now=at)) == "OPEN"
        v.fill(opt, opt.quantity, oq, at, fill_id="option-buy")
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        assert e.mixed_account(now=at).cash == D("1003.76") - opt.quantity * D("101.65") - D("1")
        e.assess(oq, u, now=at)
        out = e.prepare(
            "option-close",
            OptionProposal(
                action="CLOSE", contract=opt.instrument.contract, thesis="Native option close"
            ),
            oq,
            now=at,
        )
        assert out["status"] == "PREPARED", out
        sell = option_intent(e, out["client_id"])
        profit_quote = quote_at(data, at, bid="1.20", ask="1.21")
        assert asyncio.run(e.dispatch(sell.client_id, profit_quote, now=at)) == "OPEN"
        v.fill(sell, sell.quantity, profit_quote, at, fill_id="option-sell")
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        snapshot = v.snapshot(at)
        v.record_receipt(
            OptionReceipt(
                receipt_id="common-settlement",
                sequence=5,
                kind="FUNDS_SETTLED",
                occurred_at=at,
                cash_change=snapshot.cash - snapshot.settled_cash,
            )
        )
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        assert e.journal.report(now=at)["loss_control"]["consumed_entries"] == 2
        e.assess_stock(None, now=at)
        next_entry, at = enter(e, v, at=at, key="second-stock")
        assert e.mixed_account(now=at).cash == snapshot.cash - D("200.12")
        assert next_entry.account_revision > entry.account_revision


@pytest.mark.parametrize("stage", ["prepare", "dispatch"])
def test_partial_stock_close_freshly_reviews_mandatory_protection(tmp_path, stage):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        pr = StockProposal(action="CLOSE", instrument=entry.instrument, thesis="Partial")
        quote = q(entry, at, bid="120", ask="120.01")
        out = e.prepare_stock(
            "partial", pr, quote if stage == "prepare" else q(entry, at), now=at, close_quantity="1"
        )
        if stage == "prepare":
            assert out["status"] == "REJECTED"
        else:
            assert out["status"] == "PREPARED"
            assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=at)) == "REJECTED"
        with e.journal.read() as db:
            assert protection(e, db).exit_reason == "STOCK_TARGET"
        assert v.submit_count == 1


def test_mixed_journal_restore_and_second_owner_are_fenced(tmp_path):
    import shutil

    with owned_mixed(tmp_path) as (e, v):
        with (
            pytest.raises(RuntimeError, match="already running"),
            OptionExecution.open(e.journal.path, e.limits, e.policy, v, now=NOW),
        ):
            pass
        backup = tmp_path / "stale.db"
        shutil.copyfile(e.journal.path, backup)
        e.prepare_stock("hold", StockProposal(action="HOLD", thesis="No setup"), now=NOW)
        path, limits, p = e.journal.path, e.limits, e.policy
    shutil.copyfile(backup, path)
    with (
        pytest.raises(ValueError, match="RESTORED_OR_CHANGED"),
        OptionExecution.open(path, limits, p, v, now=NOW),
    ):
        pass


def test_signed_mixed_resume_sees_stock_ownership_and_common_revision(tmp_path):
    from test_option_loss_reset import KEY, apply, request

    from app.options.operator import OptionsControl

    with owned_mixed(tmp_path) as (e, v):
        OptionsControl.enroll(e, KEY, now=NOW)
        entry, at = enter(e, v)
        assert apply(e, request(e, at, action="HALT"), at)["status"] == "APPLIED"
        assert e.assess_stock(None, now=at)["status"] == "BLOCKED"
        assert apply(e, request(e, at, action="RESUME"), at)["status"] == "REJECTED"
        _, at = close(e, v, entry, at + timedelta(seconds=1))
        e.assess_stock(None, now=at)
        command = request(e, at, action="RESUME")
        result = apply(e, command, at)
        assert result["status"] == "APPLIED", result
        assert apply(e, command, at)["replayed"]
        assert not e.mixed_account(now=at).entry_halted


def test_frozen_native_mixed_policy_and_sql_lock_cannot_change(tmp_path):
    with owned_mixed(tmp_path) as (e, _v):
        with e.journal.write() as db:
            db.execute("DROP TRIGGER mixed_stock_insert")
        with pytest.raises(ExecutionBlocked, match="MIXED_ORDER_LOCK_CHANGED"):
            e.mixed_account(now=NOW)


def test_mixed_owner_keeps_native_scope_targets_and_original_entry(tmp_path):
    from test_option_scope import AT
    from test_option_scope_execution import execution_policy, filled, sell

    limits, p = settings()
    fields = execution_policy()
    fields.pop("loss_control")
    p = changed(p, **fields)
    limits = changed(
        limits,
        allowed_underlyings=("SPX",),
        provider="fixture-provider",
        option_source="fixture-quote",
    )
    p = changed(
        p,
        mixed_owner=changed(
            p.mixed_owner, stocks=changed(p.mixed_owner.stocks, provider=limits.provider)
        ),
    )
    v = DurableOptionVenue(
        tmp_path / "venue.db", limits=limits, capital=p.capital, stock_limits=p.mixed_owner.stocks
    )
    with OptionExecution.open(tmp_path / "engine.db", limits, p, v, now=AT, create=True) as e:
        assert e.reconcile(v.snapshot(AT), now=AT)["reconciled"]
        e.assess(None, None, now=AT)
        book, entry, frame, underlying, at = filled(e, v)
        assert entry.entry_lineage.family == "SCOPE"
        assert entry.target_exit_schedule is not None
        sell(e, v, entry, frame.quote, underlying, at, key="scale", quantity=1)
        with e.journal.read() as db:
            stored = json.loads(
                db.execute("SELECT ledger_json FROM execution_control").fetchone()[0]
            )
        assert stored["position"]["target_exit_schedule"] == entry.target_exit_schedule.model_dump(
            mode="json"
        )
        assert stored["position"]["entry_client_id"] == entry.client_id
        sell(e, v, entry, frame.quote, underlying, at)
        assert book.snapshot()["watches"][0]["status"] == "CLOSED"
        assert e.refresh_loss_control(now=at)["consumed_entries"] == 1


def test_mixed_owner_preserves_swing_carry_and_rejects_old_runtime(tmp_path):
    from test_degen_options import AT, policies
    from test_option_execution import intent_for as option_intent
    from test_option_runtime import policy as runtime_policy
    from test_option_swing_execution import carry_frame
    from test_option_swing_execution import settings as carry_settings

    from app.options.coordinator import DegenCoordinator
    from app.options.runtime import OptionRuntime

    r, swing, p = carry_settings()
    _, mixed = settings()
    p = changed(
        p,
        mixed_owner=changed(
            mixed.mixed_owner, stocks=changed(mixed.mixed_owner.stocks, provider=r.limits.provider)
        ),
        loss_control=mixed.loss_control,
    )
    v = DurableOptionVenue(
        tmp_path / "venue.db", limits=r.limits, capital=p.capital, stock_limits=p.mixed_owner.stocks
    )
    setup, selection = policies()
    with OptionExecution.open(tmp_path / "engine.db", r.limits, p, v, now=AT, create=True) as e:
        assert e.reconcile(v.snapshot(AT), now=AT)["reconciled"]
        e.assess(None, None, now=AT)
        c = DegenCoordinator(e, setup, selection, clock=lambda: AT, create=True, swing_policy=swing)
        with pytest.raises(ValueError, match="Mixed runtime"):
            OptionRuntime(c, runtime_policy(tmp_path / "feed"), create=True)
        frame = carry_frame()
        out = asyncio.run(c.cycle(frame))
        assert out["status"] == "OPEN", out
        entry = option_intent(e, out["client_id"])
        assert entry.entry_lineage.family == "SWING" and entry.swing_carry is not None
        quote = next(q for q in frame.quotes if q.instrument == entry.instrument)
        underlying = frame.underlyings[0]
        v.fill(entry, entry.quantity, quote, AT, fill_id="carry", underlying=underlying)
        assert e.reconcile(v.snapshot(AT), now=AT)["reconciled"]
    with OptionExecution.open(tmp_path / "engine.db", r.limits, p, v, now=AT) as e:
        assert e.reconcile(v.snapshot(AT), now=AT)["reconciled"]
        held = e.mixed_account(now=AT).position
        assert held.contract == entry.instrument.contract and held.quantity == entry.quantity
        with e.journal.read() as db:
            ledger = json.loads(
                db.execute("SELECT ledger_json FROM execution_control").fetchone()[0]
            )
        assert ledger["position"]["entry_client_id"] == entry.client_id
        assert ledger["position"]["exit_at"] == entry.model_dump(mode="json")["exit_at"]
        assert ledger["position"]["swing_carry"] == entry.swing_carry.model_dump(mode="json")


def test_mandatory_exit_does_not_replay_an_attempted_stock_close(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        quote = q(entry, at)
        out = e.prepare_stock(
            "partial",
            StockProposal(action="CLOSE", instrument=entry.instrument, thesis="Partial"),
            quote,
            now=at,
            close_quantity="1",
        )
        assert out["status"] == "PREPARED"
        assert asyncio.run(e.dispatch_stock(out["client_id"], quote, now=at)) == "OPEN"
        e.assess_stock(q(entry, at, bid="120", ask="120.01"), now=at)
        assert asyncio.run(e.protective_stock_tick(quote, now=at))["status"] == "EXIT_BLOCKED"
        v.record_stock_terminal(out["client_id"], "CANCELED", at)
        assert (
            asyncio.run(e.protective_stock_tick(quote, now=at))["status"] == "EXIT_REVIEW_REQUIRED"
        )
        assert v.submit_count == 2


def test_signed_global_and_family_loss_reset_preserves_stock_evidence(tmp_path):
    from test_option_loss_reset import KEY, apply, request

    from app.options.operator import OptionsControl

    with owned_mixed(tmp_path) as (e, v):
        OptionsControl.enroll(e, KEY, now=NOW)
        at = NOW
        for index in range(2):
            assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
            e.assess_stock(None, now=at)
            entry, at = enter(e, v, at=at, key=f"entry-{index}")
            _, at = close(e, v, entry, at + timedelta(seconds=1), bid="99", key=f"close-{index}")
            at += timedelta(seconds=1800)
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        e.assess_stock(None, now=at)
        state = e.refresh_loss_control(now=at)
        assert state["locked"] and state["consumed_entries"] == 2
        with e.journal.read() as db:
            before = [tuple(r) for r in db.execute("SELECT * FROM execution_option_loss_outcomes")]
        assert apply(e, request(e, at), at)["status"] == "APPLIED"
        assert apply(e, request(e, at, loss_family=entry.family), at)["status"] == "APPLIED"
        with e.journal.read() as db:
            assert before == [
                tuple(r) for r in db.execute("SELECT * FROM execution_option_loss_outcomes")
            ]
        state = e.refresh_loss_control(now=at)
        assert not state["locked"] and state["consumed_entries"] == 2
        assert not next(f for f in state["families"] if f["family"] == entry.family)["locked"]
