"""Mixed paid entry uses complete native receipts and local scripted worker results."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal as D

import pytest
from test_degen_options import AT, policies
from test_mixed_native_owner import changed, intent_for, settings
from test_mixed_selection import quote, stock_frame, stock_policy
from test_option_entry_reasoning import packet_for, plan_for

from app.execution.economics import CostPolicy, UsageEvidence
from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.entry_judgment import hold, result_for, validate_result
from app.options.entry_reasoning import plan_class
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.venue import DurableOptionVenue


@contextmanager
def owner(
    path, monkeypatch, *, choice="STOCK", mode="ENTER", delay=1, fresh=True, management=False
):
    limits, p = settings()
    costs = CostPolicy(total_budget="10", daily_budget="2", max_call_cost=".01")
    p = changed(
        p,
        cost_policy=costs,
        mixed_owner=changed(
            p.mixed_owner,
            reasoning="mixed-paid-entry-v1",
            stocks=changed(p.mixed_owner.stocks, share_step=".1"),
        ),
    )
    sp = changed(stock_policy(), paid_selection="mixed-paid-entry-v1")
    ep = changed(packet_for().policy, mixed_selection="mixed-paid-entry-v1")
    v = DurableOptionVenue(
        path / "venue.db", limits=limits, stock_limits=p.mixed_owner.stocks, capital=p.capital
    )
    times, state = [AT], {}

    async def refresh(_instrument):
        return quote(times[0] if fresh else AT - timedelta(seconds=30))

    with OptionExecution.open(path / "engine.db", limits, p, v, now=AT, create=True) as e:
        assert e.reconcile(v.snapshot(AT), now=AT)["reconciled"]
        e.assess_stock(None, now=AT)
        setup, selection = policies()
        c = DegenCoordinator(
            e,
            setup,
            selection,
            stock_policy=sp,
            entry_policy=ep,
            judgment_limits=JudgmentLimits(process_timeout_seconds=5, request_timeout_seconds=3),
            key_file=path / "unused-private-key",
            stock_refresh=refresh,
            position_policy=PositionReasoningPolicy(
                max_lease_seconds=5, mixed_management="mixed-stock-position-v1"
            )
            if management
            else None,
            create=True,
            clock=lambda: times[0],
        )
        monkeypatch.setattr(c, "_model_secret", lambda: "fixture-never-transmitted")

        async def run(request, _secret, *, broad):
            state["request"] = request
            times[0] += timedelta(seconds=delay)
            if mode in {"HOLD", "ERROR", "UNKNOWN"}:
                plan = hold(request.packet)
            elif choice == "STOCK":
                o = request.packet.stocks[0]
                plan = plan_class(request.packet.policy)(
                    decision_id=request.packet.decision_id,
                    packet_hash=fingerprint(request.packet),
                    action="ENTER",
                    stock=True,
                    scope=False,
                    candidate_id=o.candidate.candidate_id,
                    evidence_ids=(fingerprint(o),),
                    thesis="Original fixed share source",
                    uncertainty="Observed source can fail",
                )
            else:
                values = plan_for(request.packet).model_dump()
                values.update(version="mixed-entry-plan-v1", stock=False, scope=False)
                plan = plan_class(request.packet.policy).model_validate(values)
            usage = (
                None
                if mode == "UNKNOWN"
                else UsageEvidence(
                    request_id="mixed-paid-" + str(len(state)),
                    model=costs.model,
                    input_tokens=100,
                    output_tokens=20,
                )
            )
            result = result_for(
                request,
                plan=plan,
                usage=usage,
                count=100 if usage else None,
                error="ValueError" if mode in {"ERROR", "UNKNOWN"} else None,
            )
            if mode == "UNKNOWN":
                result = result_for(request, error="TimeoutError")
            state["result"] = result
            return result

        monkeypatch.setattr(c, "_model_run", run)
        yield c, v, times, state


@pytest.mark.parametrize("choice", ["STOCK", "OPTION"])
def test_one_full_paid_mixed_choice_and_native_fill(tmp_path, monkeypatch, choice):
    with owner(tmp_path, monkeypatch, choice=choice) as (c, v, times, state):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        assert out["mixed_selection"]["selected"]["asset"] == choice
        validate_result(state["request"], state["result"])
        assert v.submit_count == 1
        if choice == "STOCK":
            entry = intent_for(c.engine, out["client_id"])
            times[0] += timedelta(seconds=1)
            v.fill_stock(
                entry, entry.quantity, quote(times[0]), times[0], fill_id="mixed-paid-filled"
            )
            assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
            assert entry.original_target == state["request"].packet.stocks[0].candidate.targets[0]
        with c.engine.journal.read() as db:
            rows = db.execute("SELECT * FROM execution_model_calls").fetchall()
            assert len(rows) == 1 and D(rows[0]["cost"]) == D(".00002")
        assert c.engine.mixed_account(now=times[0]).budgets_known


@pytest.mark.parametrize("mode", ["HOLD", "ERROR", "UNKNOWN"])
def test_paid_hold_rejection_and_unknown_cost(tmp_path, monkeypatch, mode):
    with owner(tmp_path, monkeypatch, mode=mode) as (c, v, times, _):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "HOLD", out
        assert v.submit_count == 0
        with c.engine.journal.read() as db:
            row = db.execute("SELECT * FROM execution_model_calls").fetchone()
            assert row is not None
            assert (row["cost"] is None) == (mode == "UNKNOWN")
        assert c.engine.mixed_account(now=times[0]).budgets_known == (mode != "UNKNOWN")


@pytest.mark.parametrize("delay,fresh", [(6, True), (1, False)])
def test_original_lease_and_fresh_stock_quote_keep_paid_rejection(
    tmp_path, monkeypatch, delay, fresh
):
    with owner(tmp_path, monkeypatch, delay=delay, fresh=fresh) as (c, v, _times, _):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "HOLD", out
        assert v.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is not None


@contextmanager
def scope_owner(tmp_path, monkeypatch, choice, *, management=False):
    import test_option_scope_arbitration as fixture
    import test_option_scope_watch as watch_fixture
    from test_option_scope_ai import ai_owner

    from app.mixed.sources import StockCycleInput
    from app.options.lifecycle import FamilyLossPolicy

    _, p = settings()
    mixed = changed(
        p.mixed_owner,
        reasoning="mixed-paid-entry-v1",
        stocks=changed(p.mixed_owner.stocks, provider="fixture-provider", share_step=".1"),
    )
    ep = fixture.execution_policy
    monkeypatch.setattr(fixture, "execution_policy", lambda: ep() | {"mixed_owner": mixed})
    loss = fixture.NativeLossPolicy

    def losses(**kw):
        if not any(f.family == "SWING" for f in kw["families"]):
            kw["families"] += (
                FamilyLossPolicy(family="SWING", max_consecutive_losses=2, cooldown_seconds=1800),
            )
        return loss(**kw)

    monkeypatch.setattr(fixture, "NativeLossPolicy", losses)
    venue = watch_fixture.DurableOptionVenue
    monkeypatch.setattr(
        watch_fixture,
        "DurableOptionVenue",
        lambda *a, **kw: venue(*a, **kw, stock_limits=mixed.stocks),
    )
    ctor = fixture.DegenCoordinator
    state = {}

    def make(*args, **kw):
        policy = changed(
            stock_policy(),
            family_priority=("SCOPE", "DEGEN"),
            paid_selection="mixed-paid-entry-v1",
            instruments=(changed(stock_policy().instruments[0], provider="fixture-provider"),),
        )
        kw["stock_policy"] = policy
        kw["entry_policy"] = changed(kw["entry_policy"], mixed_selection="mixed-paid-entry-v1")

        async def refresh(_instrument):
            return changed(quote(state["times"][0]), instrument=policy.instruments[0])

        kw["stock_refresh"] = refresh
        if management:
            kw["position_policy"] = PositionReasoningPolicy(
                max_lease_seconds=5,
                mixed_management="mixed-stock-position-v1",
                scope_management="scope-fixed-position-v1",
            )
        return ctor(*args, **kw)

    monkeypatch.setattr(fixture, "DegenCoordinator", make)
    with ai_owner(tmp_path, monkeypatch) as (c, v, times, frame, _state):
        state["times"] = times
        frame = changed(
            frame,
            stocks=(
                StockCycleInput(
                    quote=changed(quote(times[0]), instrument=c.stock_policy.instruments[0])
                ),
            ),
        )

        async def run(request, _secret, *, broad):
            times[0] += timedelta(seconds=1)
            if choice == "SCOPE":
                digest = fingerprint(request.packet.scope.model_dump(mode="json"))
                values = {
                    "action": "ENTER",
                    "scope": True,
                    "stock": False,
                    "candidate_id": digest,
                    "evidence_ids": (digest,),
                    "thesis": "Original Scope fixed plan",
                    "uncertainty": "Fixture only",
                }
            elif choice == "STOCK":
                o = request.packet.stocks[0]
                values = {
                    "action": "ENTER",
                    "scope": False,
                    "stock": True,
                    "candidate_id": o.candidate.candidate_id,
                    "evidence_ids": (fingerprint(o),),
                    "thesis": "Original stock source",
                    "uncertainty": "Fixture only",
                }
            else:
                values = plan_for(request.packet).model_dump(
                    exclude={"version", "decision_id", "packet_hash"}
                )
                values.update(scope=False, stock=False)
            plan = plan_class(request.packet.policy)(
                decision_id=request.packet.decision_id,
                packet_hash=fingerprint(request.packet),
                **values,
            )
            return result_for(
                request,
                plan=plan,
                count=100,
                usage=UsageEvidence(
                    request_id="scope-mixed-paid",
                    model=request.configuration.costs.model,
                    input_tokens=100,
                    output_tokens=20,
                ),
            )

        monkeypatch.setattr(c, "_model_run", run)
        yield c, v, times, frame


@pytest.mark.parametrize("choice", ["STOCK", "OPTION", "SCOPE"])
def test_paid_scope_stock_and_option_competition(tmp_path, monkeypatch, choice):
    with scope_owner(tmp_path, monkeypatch, choice) as (c, v, _times, frame):
        out = asyncio.run(c.cycle(frame))
        assert out["status"] == "OPEN", {
            k: v for k, v in out.items() if k not in {"candidates", "scans", "stock_candidates"}
        }
        selected = out["mixed_selection"]["selected"]
        assert selected["asset"] == ("STOCK" if choice == "STOCK" else "OPTION")
        assert (selected["family"] == "SCOPE") == (choice == "SCOPE")
        assert v.submit_count == 1


def test_stock_paid_charge_and_original_thesis_survive_close(tmp_path, monkeypatch):
    from test_mixed_native_owner import close

    from app.mixed.native_outcome import stock_outcome

    with owner(tmp_path, monkeypatch) as (c, v, times, state):
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "OPEN", out
        entry = intent_for(c.engine, out["client_id"])
        times[0] += timedelta(seconds=1)
        v.fill_stock(entry, entry.quantity, quote(times[0]), times[0], fill_id="costed-share")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        c.engine.assess_stock(quote(times[0]), now=times[0])
        close(c.engine, v, entry, times[0] + timedelta(seconds=1), bid="602")
        with c.engine.journal.read() as db:
            outcome = stock_outcome(c.engine, db, entry.client_id)
        assert outcome["status"] == "COMPLETE", outcome
        assert outcome["known_model_cost"] == "0.00002"
        assert len(outcome["model_calls"]) == 1
        assert outcome["entry_lineage"]["paid_entry"]["thesis"] == state["result"].plan.thesis
        assert len(outcome["entry_lineage"]["original_targets"]) == 3
        gross = D(outcome["exit_cash"]) - D(outcome["entry_cash"]) - D(outcome["execution_fees"])
        assert D(outcome["net_after_all_costs"]) == gross - D(".00002")


@pytest.mark.parametrize("choice", ["STOCK", "HOLD"])
def test_stock_only_packet_uses_real_worker_with_mock_transport(tmp_path, monkeypatch, choice):
    from test_execution_judgment import response, sdk_client

    from app.options.entry_judgment_worker import perform

    with owner(tmp_path, monkeypatch) as (c, v, _times, _):

        async def run(request, _secret, *, broad):
            assert not request.packet.opportunities and request.packet.stocks
            o = request.packet.stocks[0]
            plan = (
                hold(request.packet)
                if choice == "HOLD"
                else plan_class(request.packet.policy)(
                    decision_id=request.packet.decision_id,
                    packet_hash=fingerprint(request.packet),
                    action="ENTER",
                    stock=True,
                    scope=False,
                    candidate_id=o.candidate.candidate_id,
                    evidence_ids=(fingerprint(o),),
                    thesis="Original share source",
                    uncertainty="Fixture only",
                )
            )
            data = response()
            data["output"][0]["content"][0]["text"] = plan.model_dump_json()
            client, calls = sdk_client(output=data)
            with client:
                result = perform(request, client)
            assert result.error is None
            assert len(calls) == 2 and all(body["tools"] == [] for _, body in calls)
            return result

        monkeypatch.setattr(c, "_model_run", run)
        out = asyncio.run(c.cycle(changed(stock_frame(), inventories=(), quotes=())))
        assert out["status"] == ("OPEN" if choice == "STOCK" else "HOLD"), out
        assert v.submit_count == (choice == "STOCK")


@pytest.mark.parametrize("damage", ["result", "charge", "source", "deadline"])
def test_paid_stock_receipt_tampering_blocks_attempt(tmp_path, monkeypatch, damage):
    import json

    with owner(tmp_path, monkeypatch) as (c, v, times, _):
        dispatch = c.engine.dispatch_stock

        async def pause(*args, **kwargs):
            return "PREPARED"

        monkeypatch.setattr(c.engine, "dispatch_stock", pause)
        out = asyncio.run(c.cycle(stock_frame()))
        assert out["status"] == "PREPARED", out
        with c.engine.journal.write() as db:
            row = db.execute(
                "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
                (out["cycle_key"],),
            ).fetchone()
            data = json.loads(row[0])
            if damage == "charge":
                db.execute("UPDATE execution_model_calls SET cost='0'")
            elif damage == "result":
                data["entry_result"]["plan"]["thesis"] = "Changed after approval"
            elif damage == "source":
                data["entry_request"]["packet"]["stocks"][0]["account_revision"] += 1
            else:
                data["entry_request"]["packet"]["valid_until"] = "2026-10-09T14:04:00Z"
            db.execute(
                "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                (json.dumps(data), out["cycle_key"]),
            )
        assert asyncio.run(dispatch(out["client_id"], quote(times[0]), now=times[0])) == "REJECTED"
        assert v.submit_count == 0
