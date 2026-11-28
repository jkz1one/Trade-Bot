"""Fill-time underlying evidence stays distinct from approval prices and accounting."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_option_admission import NOW
from test_option_execution import intent_for, ledger, owned, quote_at, underlying_at

from app.options.attribution import order_attribution
from app.options.engine import OptionExecution
from app.options.fill_evidence import validate_fill
from app.options.observer import OptionObserver


def prepared(e, d):
    out = e.prepare("entry", d["proposal"], d["quote"], d["underlying"], now=NOW)
    assert out["status"] == "PREPARED"
    intent = intent_for(e, out["client_id"])
    assert asyncio.run(e.dispatch(intent.client_id, d["quote"], d["underlying"], now=NOW)) == "OPEN"
    return intent


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_exact_partial_fill_observations_survive_reconcile_restart_and_read(tmp_path, right):
    with owned(tmp_path, right) as (e, v, d):
        buy = prepared(e, d)
        assert buy.quantity == 4
        fills = []
        for second in (1, 2):
            at = NOW + timedelta(seconds=second)
            u = underlying_at(d, at, bid=Decimal(600 + second), ask=Decimal(601 + second))
            fills.append(v.fill(buy, 2, quote_at(d, at), at, fill_id=str(second), underlying=u))
            assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        saved = ledger(e)
        assert saved.fees_paid == Decimal("3.60")
        assert saved.position.quantity == 4
        with e.journal.read() as db:
            row = db.execute("SELECT * FROM execution_orders").fetchone()
            attr = order_attribution(db, row)
            assert [x["underlying"] for x in attr["fill_underlyings"]] == [
                f.underlying.model_dump(mode="json") for f in fills
            ]
            assert sum(x["quantity"] for x in attr["fill_underlyings"]) == attr["filled_quantity"]
            assert json.loads(row["approval_json"])["underlying"] == d["underlying"].model_dump(
                mode="json"
            )
        path, limits, policy = e.journal.path, e.limits, e.policy
    with OptionExecution.open(path, limits, policy, v, now=at) as e:
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        assert ledger(e) == saved
        before = path.read_bytes()
        report = OptionObserver(path, limits.population_id, clock=lambda: at).report()
        assert report["status"] == "OK", report
        assert [f["underlying_observation"]["fill_id"] for f in report["fills"]] == ["2", "1"]
        assert path.read_bytes() == before
        assert not report["network_calls"]


@pytest.mark.parametrize(
    "damage",
    [
        "symbol",
        "source",
        "incomplete",
        "delayed",
        "crossed",
        "minimum",
        "stale",
        "future",
        "receipt",
        "lag",
        "sync",
    ],
)
def test_invalid_explicit_underlying_is_rejected_atomically_and_by_native_fill_audit(
    tmp_path, damage
):
    with owned(tmp_path) as (e, v, d):
        buy = prepared(e, d)
        at = NOW + timedelta(seconds=1)
        u = underlying_at(d, at)
        changes = {
            "symbol": {"symbol": "QQQ"},
            "source": {"source": "foreign"},
            "incomplete": {"complete": False},
            "delayed": {"entitlement": "DELAYED"},
            "crossed": {"bid": Decimal(601), "ask": Decimal(600)},
            "minimum": {"bid": Decimal(1), "ask": Decimal(2)},
            "stale": {"source_at": at - timedelta(seconds=e.limits.quote_max_age_seconds)},
            "future": {"source_at": at + timedelta(microseconds=1)},
            "receipt": {"received_at": at + timedelta(microseconds=1)},
            "lag": {"source_at": at - timedelta(seconds=e.limits.max_receive_lag_seconds + 1)},
            "sync": {
                "source_at": at - timedelta(seconds=e.limits.max_sync_seconds + 1),
                "received_at": at - timedelta(seconds=e.limits.max_sync_seconds + 1),
            },
        }
        u = u.model_copy(update=changes[damage])
        q = quote_at(d, at)
        before = v.snapshot(at)
        with pytest.raises(ValueError, match="OPTION_FILL_UNDERLYING_EVIDENCE_INVALID"):
            v.fill(buy, 1, q, at, fill_id="bad", underlying=u)
        assert v.snapshot(at) == before
        # A venue cannot bypass the same audit by constructing its own receipt.
        good = v.fill(buy, 1, q, at, fill_id="good")
        forged = good.model_copy(update={"underlying": u})
        with pytest.raises(ValueError, match="OPTION_FILL_UNDERLYING_EVIDENCE_INVALID"):
            validate_fill(e.limits, buy, forged, 0, {})
        order = v.snapshot(at).orders[0].model_copy(update={"fills": (forged,)})
        snap = v.snapshot(at).model_copy(update={"orders": (order,)})
        result = e.reconcile(snap, now=at)
        assert not result["reconciled"]
        assert ledger(e).position is None and ledger(e).cash == 1000


def test_missing_evidence_stays_missing_and_cannot_be_backfilled_on_reconciliation(tmp_path):
    with owned(tmp_path) as (e, v, d):
        buy = prepared(e, d)
        first = v.fill(buy, 1, d["quote"], NOW, fill_id="legacy")
        assert "underlying" not in first.model_dump()
        assert e.reconcile(v.snapshot(NOW), now=NOW)["reconciled"]
        at = NOW + timedelta(seconds=1)
        second = v.fill(
            buy, 1, quote_at(d, at), at, fill_id="observed", underlying=underlying_at(d, at)
        )
        assert e.reconcile(v.snapshot(at), now=at)["reconciled"]
        with e.journal.read() as db:
            attr = order_attribution(db, db.execute("SELECT * FROM execution_orders").fetchone())
        assert attr["filled_quantity"] == 2
        assert [x["fill_id"] for x in attr["fill_underlyings"]] == [second.fill_id]
        before = ledger(e)
        at += timedelta(seconds=1)
        snap = v.snapshot(at)
        changed = first.model_copy(update={"underlying": d["underlying"]})
        order = snap.orders[0].model_copy(update={"fills": (changed, second)})
        result = e.reconcile(snap.model_copy(update={"orders": (order,)}), now=at)
        assert not result["reconciled"] and "OPTION_FILL_ID_CONFLICT" in result["issues"]
        assert ledger(e) == before


@pytest.mark.parametrize("kind", ["valid", "stale", "missing", "later_same_time"])
def test_replay_attaches_only_usable_evidence_in_delivered_prefix(tmp_path, kind):
    from app.options.coordinator import DegenFrame
    from app.options.replay import _ArmReplay

    with owned(tmp_path) as (e, v, d):
        buy = prepared(e, d)
        at = NOW + timedelta(seconds=1)

        async def supervise(*args):
            return None

        c = SimpleNamespace(engine=e, supervise=supervise)
        replay = _ArmReplay(c, v, None, [NOW])
        u = underlying_at(d, NOW - timedelta(minutes=1) if kind == "stale" else at)
        event = SimpleNamespace(
            sequence=1,
            frame=DegenFrame(
                quotes=(quote_at(d, at),), underlyings=(u,) if kind in {"valid", "stale"} else ()
            ),
        )
        asyncio.run(replay.observe(at, event))
        receipt = v.snapshot(at).orders[0].fills[0]
        assert receipt.quantity == buy.quantity
        assert receipt.underlying == (u if kind == "valid" else None)
        if kind == "later_same_time":
            event = SimpleNamespace(sequence=2, frame=DegenFrame(underlyings=(u,)))
            asyncio.run(replay.observe(at, event))
            assert v.snapshot(at).orders[0].fills[0].underlying is None
        assert ledger(e).position.quantity == buy.quantity


def test_optional_evidence_does_not_change_costs_or_share_accounts(tmp_path):
    with owned(tmp_path / "a") as (a, av, ad), owned(tmp_path / "b") as (b, bv, bd):
        ai, bi = prepared(a, ad), prepared(b, bd)
        before_b = ledger(b)
        av.fill(ai, ai.quantity, ad["quote"], NOW, fill_id="same-id", underlying=ad["underlying"])
        assert a.reconcile(av.snapshot(NOW), now=NOW)["reconciled"]
        assert ledger(b) == before_b
        bv.fill(bi, bi.quantity, bd["quote"], NOW, fill_id="same-id")
        assert b.reconcile(bv.snapshot(NOW), now=NOW)["reconciled"]
        assert ledger(a).cash == ledger(b).cash
        assert ledger(a).fees_paid == ledger(b).fees_paid
        assert av.snapshot(NOW).orders[0].fills[0].underlying is not None
        assert bv.snapshot(NOW).orders[0].fills[0].underlying is None


@pytest.mark.parametrize("coverage", ["present", "missing", "late"])
def test_portable_accounting_requires_underlying_in_recorded_prefix(
    tmp_path, monkeypatch, coverage
):
    from test_option_evaluation import bundle_for, change_arm, round_trip
    from test_option_market_tape import record_bundle

    from app.options.coordinator import DegenFrame
    from app.options.evaluation import evaluate
    from app.options.market_tape import TapeRecorder, load_tape
    from app.options.venue import DurableOptionVenue

    original = DurableOptionVenue.fill

    def observed(self, intent, quantity, quote, at, **kwargs):
        from test_option_admission import inputs

        return original(
            self, intent, quantity, quote, at, underlying=underlying_at(inputs(), at), **kwargs
        )

    monkeypatch.setattr(DurableOptionVenue, "fill", observed)
    start, end, orders = round_trip(tmp_path / "engine")
    b = change_arm(bundle_for(), 0, initial=start, closing=end, orders=orders)
    root = tmp_path / "tape"
    root.mkdir(mode=0o700)
    b, old, _ = record_bundle(root, b)
    events = [(e.recorded_at, e.kind, e.frame) for e in old.events]
    if coverage != "missing":
        for order in orders:
            for fill in order.observation.fills:
                at = fill.occurred_at + (
                    timedelta(seconds=1) if coverage == "late" else timedelta()
                )
                events.append((at, "MARKET", DegenFrame(underlyings=(fill.underlying,))))
    with TapeRecorder(root / "observed.tape", old.header) as recorder:
        for at, kind, frame in sorted(events, key=lambda row: row[0]):
            recorder.append(frame, recorded_at=at, kind=kind)
        digest = recorder.seal()
    tape = load_tape(root / "observed.tape")
    b = b.model_copy(
        update={
            "manifest": b.manifest.model_copy(
                update={
                    "sessions": (b.manifest.sessions[0].model_copy(update={"tape_hash": digest}),)
                }
            ),
            "evidence": tuple(a.model_copy(update={"tape_hash": digest}) for a in b.evidence),
        }
    )
    report = evaluate(b, tapes=(tape,))
    if coverage == "present":
        assert report["status"] == "COMPLETE_ARITHMETIC", report
        assert report["recorded_market_verified"]
        assert Decimal(report["sessions"][0]["arms"]["A"]["venue_fees"]) == Decimal("7.20")
    else:
        assert "FILL_UNDERLYING_NOT_RECORDED_BY_FILL_TIME" in report["sessions"][0]["reasons"]
        assert report["totals"]["A"]["net_change"] is None
