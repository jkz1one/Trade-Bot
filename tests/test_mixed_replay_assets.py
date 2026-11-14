"""A common owner preserves option and fixed Scope authority beside stock inputs."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT, frame
from test_mixed_native_owner import changed, settings
from test_mixed_replay import request_for
from test_mixed_selection import quote, stock_policy

from app.mixed.comparison import verify_mixed_comparison
from app.mixed.market_tape import MixedTapeHeader, MixedTapeRecorder, load_mixed_tape
from app.mixed.replay import (
    MixedComparison,
    MixedReplayAccount,
    MixedReplaySession,
    run_mixed_comparison,
)
from app.mixed.replay_model import MixedReplayScript, MixedScriptedDecision
from app.mixed.sources import StockCycleInput
from app.options.coordinator import DegenFrame


def option_request(path, *, partial=False):
    request = request_for(path)
    first = request.sessions[0].tape.events[0]
    h = changed(request.sessions[0].tape.header, stocks=stock_policy(asset="OPTION"))
    original = frame()
    with MixedTapeRecorder(path / "options.tape", h) as recorder:
        recorder.append(first.frame, recorded_at=AT)
        # A retains four one-contract entry fills and four later close fills.
        # A stop does not manufacture cancellation, liquidity or a completed exit.
        for seconds in range(1, 9) if partial else (1, 2, 3, 4, 5):
            at = AT + timedelta(seconds=seconds)
            underlying = changed(
                original.underlyings[0],
                source_at=at,
                received_at=at,
                **({"bid": "599.8", "ask": "599.81"} if seconds >= 3 else {}),
            )
            q = changed(original.quotes[0], source_at=at, received_at=at)
            if partial:
                q = changed(q, bid_size=1, ask_size=1)
            recorder.append(
                DegenFrame(
                    quotes=(q,),
                    underlyings=(underlying,),
                    stocks=(StockCycleInput(quote=quote(at)),),
                ),
                recorded_at=at,
                kind="MARKET",
            )
        recorder.seal()
    accounts = []
    for account in request.accounts:
        if account.script is not None:
            decision = changed(
                account.script.decisions[0],
                asset="OPTION",
                **(
                    {
                        "condition": "NOW",
                        "underlying_invalidation": "600",
                        "underlying_target": "602",
                        "horizon_seconds": 600,
                    }
                    if account.arm != "B"
                    else {}
                ),
            )
            account = changed(account, script=changed(account.script, decisions=(decision,)))
        accounts.append(account)
    return changed(
        request,
        accounts=tuple(accounts),
        sessions=(MixedReplaySession(tape=load_mixed_tape(path / "options.tape")),),
    )


@pytest.mark.parametrize("partial", [False, True])
def test_native_options_keep_proposals_actual_partial_fills_and_costs(tmp_path, partial):
    request = option_request(tmp_path / "source", partial=partial)
    bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "run"))
    report = verify_mixed_comparison(json.loads(json.dumps(bundle)), bundle["bundle_hash"])
    for arm, item in report["sessions"][0]["accounts"].items():
        account = item["accounting"]
        assert not account["stock_orders"]
        assert account["ledger"]["position"] is None
        assert len(account["outcomes"]) == 1
        assert account["outcomes"][0]["status"] == "COMPLETE"
        assert Decimal(account["execution_fees"]) > 0
        calls = [c for c in account["costs"] if c["kind"] == "ENTRY_MODEL"]
        assert len(calls) == int(arm != "A")
        if partial and arm == "A":
            orders = [
                json.loads(row[3])
                for row in bundle["boundaries"][0][arm]["evidence"]["execution_orders"]
            ]
            entry = next(order for order in orders if order["side"] == "BUY")
            quantity = Decimal(account["outcomes"][0]["entry_quantity"])
            assert quantity == entry["quantity"] == 4
            attribution = {order["client_id"]: order for order in account["option_orders"]}
            assert len(attribution[entry["client_id"]]["fill_ids"]) == 4
            closes = [order for order in orders if order["side"] == "SELL"]
            assert len(closes) == 4
            assert all(
                order["quantity"] == attribution[order["client_id"]]["filled_quantity"] == 1
                and len(attribution[order["client_id"]]["fill_ids"]) == 1
                for order in closes
            )
    assert report["comparison_complete"]


@pytest.mark.parametrize("asset", ["STOCK", "OPTION"])
def test_missing_executable_exit_preserves_native_open_exposure(tmp_path, asset):
    request = (request_for if asset == "STOCK" else option_request)(tmp_path / "source")
    tape = request.sessions[0].tape
    with MixedTapeRecorder(tmp_path / "source/open.tape", tape.header) as recorder:
        for event in tape.events[:3]:
            recorder.append(event.frame, recorded_at=event.recorded_at, kind=event.kind)
        recorder.seal()
    request = changed(
        request, sessions=(MixedReplaySession(tape=load_mixed_tape(tmp_path / "source/open.tape")),)
    )
    bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "run"))
    report = verify_mixed_comparison(json.loads(json.dumps(bundle)), bundle["bundle_hash"])
    for value in report["sessions"][0]["accounts"].values():
        account = value["accounting"]
        assert "OPEN_POSITION" in account["reasons"]
        assert account["ledger"]["stock_position" if asset == "STOCK" else "position"] is not None
        assert account["net_after_all_costs"] is None
    assert not report["comparison_complete"]


def scope_request(path, *, fresh=True):
    from test_option_scope_comparison import request as scope_comparison

    path.mkdir(mode=0o700)
    old = scope_comparison(path)
    # Both sides use the same original tape and watch actions. Choice-only B
    # retains the fixed plan; C/D receive the complete paid entry contract.
    stock = settings()[1].mixed_owner
    stock = changed(
        stock,
        stocks=changed(stock.stocks, provider=old.baseline.limits.provider, share_step=".1"),
        daily_data_cost=".01",
        daily_host_cost=".02",
    )
    stocks = changed(
        stock_policy(),
        instruments=(
            changed(stock_policy().instruments[0], provider=old.baseline.limits.provider),
        ),
        family_priority=("SCOPE", "DEGEN"),
    )
    h = MixedTapeHeader.model_validate(
        old.baseline.tape.header.model_dump()
        | {"version": "mixed-market-tape-v1", "stock_limits": stock.stocks, "stocks": stocks}
    )
    first = next(e for e in old.baseline.tape.events if e.kind == "CYCLE")
    with MixedTapeRecorder(path / "mixed-scope.tape", h) as recorder:
        for event in old.baseline.tape.events:
            if not fresh and event.recorded_at == first.recorded_at + timedelta(seconds=1):
                continue
            current = event.frame
            kind = event.kind
            if not fresh and event.kind == "CYCLE" and event != first:
                current, kind = DegenFrame(scope=current.scope), "SCOPE"
            if kind == "CYCLE":
                current = changed(
                    current,
                    stocks=(
                        StockCycleInput(
                            quote=changed(
                                quote(event.recorded_at), instrument=stocks.instruments[0]
                            )
                        ),
                    ),
                )
            recorder.append(current, recorded_at=event.recorded_at, kind=kind)
        recorder.seal()
    accounts = []
    for arm, account in zip(
        "ABCD", (old.baseline, old.shortlist, old.entry, old.managed), strict=True
    ):
        paid = arm != "A"
        decisions = (
            tuple(
                MixedScriptedDecision(
                    cycle_key=d.cycle_key,
                    delay_seconds=d.delay_seconds,
                    action="SELECT" if arm == "B" and d.action == "ENTER" else d.action,
                    asset="SCOPE" if d.scope else None,
                    underlying_invalidation=getattr(d, "underlying_invalidation", None),
                )
                for d in account.script.decisions
                if fresh or d.cycle_key.startswith("degen:")
            )
            if paid
            else ()
        )
        accounts.append(
            MixedReplayAccount(
                arm=arm,
                limits=account.limits,
                execution=changed(
                    account.execution,
                    mixed_owner=changed(stock, reasoning="mixed-paid-entry-v1" if paid else None),
                    loss_control=settings()[1].loss_control,
                ),
                scope=account.scope,
                judgment_limits=account.judgment_limits if paid else None,
                entry_policy=changed(
                    account.entry_policy,
                    mixed_selection="mixed-paid-entry-v1",
                    mixed_shortlist="mixed-choice-only-v1" if arm == "B" else None,
                    scope_selection="scope-fixed-plan-v1",
                )
                if paid
                else None,
                position_policy=changed(
                    account.position_policy, mixed_management="mixed-stock-position-v1"
                )
                if arm == "D"
                else None,
                script=MixedReplayScript(arm=arm, decisions=decisions) if paid else None,
            )
        )
    return MixedComparison(
        sessions=(
            MixedReplaySession(
                tape=load_mixed_tape(path / "mixed-scope.tape"),
                watch_actions=old.baseline.watch_actions,
            ),
        ),
        accounts=tuple(accounts),
    )


@pytest.mark.parametrize("kind", ["option", "partial", "scope", "scope_stale"])
def test_complete_asset_request_is_predeclared_and_reconstructable(tmp_path, kind):
    request = (
        option_request(tmp_path / "source", partial=kind == "partial")
        if kind in {"option", "partial"}
        else scope_request(tmp_path / "source", fresh=kind != "scope_stale")
    )
    assert MixedComparison.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("fresh", [True, False])
def test_scope_replay_requires_fresh_post_cost_original_admission(tmp_path, fresh):
    request = scope_request(tmp_path / "source", fresh=fresh)
    bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "run"))
    report = verify_mixed_comparison(json.loads(json.dumps(bundle)), bundle["bundle_hash"])
    for arm, item in report["sessions"][0]["accounts"].items():
        account = item["accounting"]
        assert not account["stock_orders"]
        if fresh or arm == "A":
            assert account["status"] == "COMPLETE_FLAT_ACCOUNTING"
            assert account["scope"]["watches"][0]["recorded_status"] == "CLOSED"
            assert account["outcomes"][0]["entry_lineage"]["family"] == "SCOPE"
        else:
            assert not account["option_orders"]
            assert any(c["kind"] == "ENTRY_MODEL" for c in account["costs"])
    assert report["comparison_complete"]
