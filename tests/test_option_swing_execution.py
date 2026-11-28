"""Native carry preserves one owner, DAY attempts, original protection and every cost."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, policies
from test_option_entry_coordination import fake_model
from test_option_entry_reasoning import packet_for
from test_option_execution import intent_for, ledger
from test_option_shared_strategy import shared_frame
from test_option_swing_carry import request

from app.execution.economics import CostPolicy
from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution
from app.options.entry_reasoning import CarryEntryPlan
from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.venue import DurableOptionVenue

D = Decimal


def settings(right="CALL", ai=False):
    r = request(right)
    swing = r.swing.model_copy(update={"holding_policy": "BOUNDED_CARRY_V1", "carry": r.carry})
    execution = r.execution.model_copy(
        update={
            "swing_carry": "bounded-swing-carry-v1",
            "loss_control": NativeLossPolicy(
                max_consecutive_losses=2,
                cooldown_seconds=1800,
                families=(
                    FamilyLossPolicy(
                        family="SWING", max_consecutive_losses=2, cooldown_seconds=1800
                    ),
                ),
            ),
            **({"cost_policy": CostPolicy(total_budget="1", daily_budget=".1")} if ai else {}),
        }
    )
    return r, swing, execution


def carry_frame(right="CALL"):
    r, _, _ = settings(right)
    item = r.item.model_copy(
        update={"seed": r.item.seed.model_copy(update={"carry_exit_session": r.exit_session})}
    )
    return shared_frame(right, item)


@contextmanager
def carry_owner(path, right="CALL", *, ai=False, management=False, create=True, at=AT):
    r, swing, execution = settings(right, ai)
    venue = DurableOptionVenue(
        path / "venue.db", limits=r.limits, capital=execution.capital if create else None
    )
    times = [at]
    setup, selection = policies()
    kwargs = {}
    if ai:
        key = path / "model.key"
        if create:
            key.write_text("fixture-only\n")
            key.chmod(0o600)
        kwargs = {
            "judgment_limits": JudgmentLimits(),
            "key_file": key,
            "entry_policy": packet_for(right).policy.model_copy(
                update={"max_carry_horizon_seconds": 600000}
            ),
        }
        if management:
            kwargs["position_policy"] = PositionReasoningPolicy(
                max_lease_seconds=10, swing_carry="bounded-swing-carry-v1"
            )
    with OptionExecution.open(
        path / "options.db", r.limits, execution, venue, now=at, create=create
    ) as e:
        assert e.reconcile(venue.snapshot(at), now=at)["reconciled"]
        e.assess(None, None, now=at)
        c = DegenCoordinator(
            e, setup, selection, clock=lambda: times[0], create=create, swing_policy=swing, **kwargs
        )
        yield c, venue, times


def model(monkeypatch, c, right="CALL"):
    def carry(request, result):
        out = result.plan.model_dump()
        end = request.packet.opportunities[0].scan.carry_terms.exit_at
        out.update(
            version="option-entry-plan-carry-v1",
            horizon_seconds=int((end - request.packet.as_of).total_seconds()),
            underlying_target=D(605 if right == "CALL" else 595),
        )
        return result.model_copy(update={"plan": CarryEntryPlan.model_validate(out)})

    return fake_model(monkeypatch, c, changes=carry)


def fresh(f, at, *, price=None):
    q = f.quotes[1].model_copy(update={"source_at": at, "received_at": at})
    u = f.underlyings[0].model_copy(
        update={
            "source_at": at,
            "received_at": at,
            **({"bid": D(price), "ask": D(price) + D(".01")} if price else {}),
        }
    )
    return q, u


def entered(c, v, f):
    result = asyncio.run(c.cycle(f))
    assert result["status"] == "OPEN", result
    i = intent_for(c.engine, result["client_id"])
    v.fill(i, i.quantity, f.quotes[1], AT, fill_id="carry-entry")
    assert c.engine.reconcile(v.snapshot(AT), now=AT)["reconciled"]
    return i


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("ai", [False, True])
def test_carry_entry_day_order_deadline_and_next_session_protection(
    tmp_path, monkeypatch, right, ai
):
    with carry_owner(tmp_path, right, ai=ai) as (c, v, t):
        calls = model(monkeypatch, c, right) if ai else []
        f = carry_frame(right)
        i = entered(c, v, f)
        assert i.swing_carry and i.exit_at.date().isoformat() == "2026-10-12"
        assert i.order_expires_at == AT.replace(hour=20)
        assert i.approval_expires_at <= AT + timedelta(seconds=5)
        end = AT.replace(hour=20)
        t[0] = end
        q, u = fresh(f, end)
        assert c.engine.reconcile(v.snapshot(end), now=end)["reconciled"]
        assert c.engine.assess(q, u, now=end)["exit_reason"] is None
        assert ledger(c.engine).position.swing_carry == i.swing_carry
        from app.options.observer import OptionObserver

        report = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=lambda: end
        ).report()
        assert report["strategy"]["families"]["SWING"] == "BOUNDED_CARRY_FIXTURE"
        assert report["position"]["swing_carry"] == i.swing_carry.model_dump(mode="json")
        nextday = AT + timedelta(days=3)
        t[0] = nextday
        q, u = fresh(f, nextday, price="590" if right == "CALL" else "610")
        result = asyncio.run(c.supervise((q,), (u,)))
        assert result["status"] == "OPEN", result
        close = intent_for(c.engine, result["client_id"])
        assert close.side == "SELL" and close.closing_entry_client_id == i.client_id
        assert close.exit_at == i.exit_at
        assert len(calls) == int(ai)


def test_restart_retains_carry_and_missing_quote_latches_final_deadline(tmp_path):
    with carry_owner(tmp_path) as (c, v, _t):
        f = carry_frame()
        i = entered(c, v, f)
        deadline = i.exit_at
    with carry_owner(tmp_path, create=False, at=deadline) as (c, v, _t):
        assert c.engine.assess(None, None, now=deadline)["exit_reason"] == "TIME_EXIT"
        assert ledger(c.engine).position.swing_carry == i.swing_carry
        q, u = fresh(f, deadline)
        result = asyncio.run(c.supervise((q,), (u,)))
        assert result["status"] == "OPEN", result
        close = intent_for(c.engine, result["client_id"])
        v.fill(close, close.quantity, q, deadline, fill_id="carry-close")
        assert c.engine.reconcile(v.snapshot(deadline), now=deadline)["reconciled"]
        assert ledger(c.engine).position is None


def test_original_t1_exits_without_model_and_does_not_roll_deadline(tmp_path):
    with carry_owner(tmp_path) as (c, v, t):
        f = carry_frame()
        i = entered(c, v, f)
        t[0] = AT + timedelta(days=3)
        q, u = fresh(f, t[0], price="605")
        result = asyncio.run(c.supervise((q,), (u,)))
        assert result["status"] == "OPEN", result
        assert ledger(c.engine).position.exit_reason == "UNDERLYING_TARGET"
        assert ledger(c.engine).position.exit_at == i.exit_at


@pytest.mark.parametrize("bad", ["horizon", "clearance", "owner"])
def test_carry_requires_complete_frozen_enrollment_and_clearance(tmp_path, bad):
    if bad == "owner":
        r, s, e = settings()
        e = e.model_copy(update={"swing_carry": None})
        v = DurableOptionVenue(tmp_path / "venue.db", limits=r.limits, capital=e.capital)
        with (
            OptionExecution.open(
                tmp_path / "options.db", r.limits, e, v, now=AT, create=True
            ) as engine,
            pytest.raises(ValueError, match="Matching frozen"),
        ):
            DegenCoordinator(engine, *policies(), create=True, swing_policy=s)
        return
    with carry_owner(tmp_path) as (c, _v, _t):
        f = carry_frame()
        item = f.swing[0]
        if bad == "horizon":
            item = item.model_copy(
                update={"seed": item.seed.model_copy(update={"carry_exit_session": None})}
            )
        else:
            item = item.model_copy(
                update={
                    "catalyst": item.catalyst.model_copy(
                        update={"valid_through": AT.replace(hour=20)}
                    )
                }
            )
        f = f.model_copy(update={"swing": (item,)})
        plan = c.quote_plan(f.histories, f.inventories, f.swing)
        scan = next(s for s in plan["scans"] if s.version == "swing-next-session-v1")
        assert scan.issues and scan.carry_terms is None


@pytest.mark.parametrize("action", ["MAINTAIN", "TIGHTEN", "EXIT_ALL"])
def test_next_session_management_retains_original_context_and_all_costs(
    tmp_path, monkeypatch, action
):
    from test_degen_options import frame
    from test_option_position_coordination import model as manager

    from app.options.attribution import decision_attribution

    with carry_owner(tmp_path, ai=True, management=True) as (c, v, t):
        model(monkeypatch, c)
        f = carry_frame()
        entry = entered(c, v, f)
        t[0] = AT + timedelta(days=3)
        q, u = fresh(f, t[0])
        h = frame().histories[0]
        h = h.model_copy(
            update={
                "source_at": t[0],
                "received_at": t[0],
                "bars": tuple(
                    b.model_copy(update={"begins_at": b.begins_at + timedelta(days=3)})
                    for b in h.bars
                ),
            }
        )
        f = f.model_copy(
            update={
                "histories": (h,),
                "quotes": (q,),
                "underlyings": (u,),
                "swing": (),
                "inventories": (),
            }
        )
        calls = manager(monkeypatch, c, action)
        result = asyncio.run(c.cycle(f))
        assert (
            result["status"]
            == {"MAINTAIN": "MAINTAIN", "TIGHTEN": "TIGHTENED", "EXIT_ALL": "OPEN"}[action]
        ), result
        assert len(calls) == 1
        packet = calls[0][0].packet
        assert packet.carry_context.original_scan.seed.target_session == AT.date()
        assert packet.carry_context.overnight_coverage == "NOT_CONTINUOUSLY_OBSERVED"
        assert packet.position.swing_carry == entry.swing_carry
        with c.engine.journal.read() as db:
            attr = decision_attribution(db, result["cycle_key"], result, c.engine.policy)
            assert attr.swing_carry == entry.swing_carry
            assert attr.entry_client_id == entry.client_id
            assert [D(r[0]) for r in db.execute("SELECT cost FROM execution_model_calls")] == [
                D(".00015"),
                D(".00015"),
            ]
        assert asyncio.run(c.cycle(f)) == result and len(calls) == 1
        if action == "EXIT_ALL":
            sell = intent_for(c.engine, result["client_id"])
            v.fill(sell, sell.quantity, q, t[0], fill_id="monday-close")
            assert c.engine.reconcile(v.snapshot(t[0]), now=t[0])["reconciled"]
            with c.engine.journal.read() as db:
                outcomes = db.execute("SELECT * FROM execution_option_loss_outcomes").fetchall()
                assert len(outcomes) == 1
                from app.options.position_outcome import native_position_outcome

                outcome = native_position_outcome(
                    db, entry.client_id, c.engine.limits.population_id
                )
                assert outcome["known_model_cost"] == "0.00030"
                assert outcome["status"] == "COMPLETE"
            assert c.engine.reconcile(v.snapshot(t[0]), now=t[0])["reconciled"]


def test_partial_entry_observed_day_remainder_cannot_reopen_or_extend(tmp_path):
    with carry_owner(tmp_path) as (c, v, t):
        f = carry_frame()
        result = asyncio.run(c.cycle(f))
        entry = intent_for(c.engine, result["client_id"])
        assert entry.quantity > 1
        v.fill(entry, 1, f.quotes[1], AT, fill_id="partial-carry")
        assert c.engine.reconcile(v.snapshot(AT), now=AT)["reconciled"]
        t[0] = entry.order_expires_at
        v.record_terminal(entry.client_id, "CANCELED", t[0])
        assert c.engine.reconcile(v.snapshot(t[0]), now=t[0])["reconciled"]
        held = ledger(c.engine).position
        assert held.quantity == 1 and held.swing_carry == entry.swing_carry
        assert held.exit_at == entry.exit_at
        assert v.submit_count == 1


@pytest.mark.parametrize("field", ["swing_carry", "exit_at"])
def test_stored_carry_tampering_is_rejected_by_reconciliation(tmp_path, field):
    import json

    with carry_owner(tmp_path) as (c, v, _t):
        entry = entered(c, v, carry_frame())
        with c.engine.journal.write() as db:
            row = db.execute(
                "SELECT intent_json FROM execution_orders WHERE client_id=?", (entry.client_id,)
            ).fetchone()
            raw = json.loads(row[0])
            if field == "swing_carry":
                raw.pop(field)
            else:
                raw[field] = (entry.exit_at - timedelta(minutes=1)).isoformat()
            db.execute(
                "UPDATE execution_orders SET intent_json=? WHERE client_id=?",
                (json.dumps(raw), entry.client_id),
            )
        result = c.engine.reconcile(v.snapshot(AT), now=AT)
        assert not result["reconciled"], result


def test_model_horizon_cannot_cross_closed_session_target_or_original_exit(tmp_path, monkeypatch):
    from app.options.entry_reasoning import review_entry_plan

    with carry_owner(tmp_path, ai=True) as (c, v, _t):
        calls = model(monkeypatch, c)
        entered(c, v, carry_frame())
        import json

        from app.options.entry_judgment import EntryResult

        request_ = calls[0]
        with c.engine.journal.read() as db:
            raw = json.loads(
                db.execute("SELECT result_json FROM execution_option_opportunities").fetchone()[0]
            )
        result = EntryResult.model_validate(raw["entry_result"])
        packet = request_.packet
        from test_execution_judgment import response, sdk_client

        from app.options.entry_judgment import create_request
        from app.options.entry_judgment_worker import perform

        live_request = create_request(packet, request_.configuration, request_id="c" * 32, now=AT)
        output = response()
        output["output"][0]["content"][0]["text"] = result.plan.model_dump_json()
        client, sdk_calls = sdk_client(output=output)
        with client:
            receipt = perform(live_request, client)
        assert receipt.error is None and receipt.plan == result.plan
        assert len(sdk_calls) == 2 and sdk_calls[-1][1]["tools"] == []
        o = packet.opportunities[0]
        for changes, reason in (
            ({"horizon_seconds": 86400}, "CARRY_HORIZON_NOT_TRADING_SESSION"),
            ({"horizon_seconds": 279660}, "HORIZON_OUTSIDE_FROZEN_ENVELOPE"),
            ({"underlying_target": D("605.1")}, "CARRY_TARGET_WIDENS_ORIGINAL"),
        ):
            review = review_entry_plan(
                packet,
                result.plan.model_copy(update=changes),
                quote=o.quote,
                underlying=o.underlying,
                account=packet.account,
                now=packet.as_of,
            )
            assert review.outcome == "REJECTED" and reason in review.reasons
        shorter = result.plan.model_copy(update={"horizon_seconds": 600})
        review = review_entry_plan(
            packet,
            shorter,
            quote=o.quote,
            underlying=o.underlying,
            account=packet.account,
            now=packet.as_of,
        )
        assert review.outcome == "ELIGIBLE" and review.exit_by == AT + timedelta(seconds=600)


def test_legacy_model_contract_hashes_remain_identical():
    from app.options import entry_judgment, position_judgment
    from app.options.engine import fingerprint

    costs = CostPolicy(total_budget="1", daily_budget=".1")
    entry = entry_judgment.configuration(costs, JudgmentLimits(), packet_for().policy)
    position = position_judgment.configuration(
        costs, JudgmentLimits(), PositionReasoningPolicy(max_lease_seconds=5)
    )
    assert fingerprint(entry) == "45ae9898f10115d34c8b50d0cfc0058cd1500bf5849bba451da3a7c805740aa8"
    assert (
        fingerprint(position) == "272a49a0ecce4858d256f6ab23ccf24b9f95916e745d5dd537cd5c736e0e44c4"
    )


def test_degen_in_carry_owner_still_expires_intraday(tmp_path):
    from test_degen_options import frame

    with carry_owner(tmp_path) as (c, _v, _t):
        f = carry_frame()
        item = f.swing[0]
        history = item.seed.history.model_copy(
            update={
                "bars": tuple(
                    b.model_copy(
                        update={k: getattr(b, k) + 10 for k in ("open", "high", "low", "close")}
                    )
                    for b in item.seed.history.bars
                )
            }
        )
        item = item.model_copy(
            update={
                "seed": item.seed.model_copy(update={"history": history, "first_target": D(615)})
            }
        )
        result = asyncio.run(c.cycle(frame().model_copy(update={"swing": (item,)})))
        assert result["status"] == "OPEN", result
        entry = intent_for(c.engine, result["client_id"])
        assert entry.swing_carry is None and entry.exit_at.date() == AT.date()
        assert entry.entry_lineage.family == "DEGEN"
