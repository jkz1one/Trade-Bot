"""Combined Scope/option carry keeps original horizons in the mixed native accounts."""

import asyncio
import json
from decimal import Decimal

import pytest
from test_mixed_native_owner import changed, settings
from test_mixed_selection import quote, stock_policy
from test_option_scope_carry_series import request as original_request

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


def combined_request(path, family):
    path.mkdir(mode=0o700)
    old = original_request(path, family=family)
    first = old.sessions[0]
    owner = settings()[1].mixed_owner
    owner = changed(
        owner,
        stocks=changed(owner.stocks, provider=first.baseline.limits.provider, share_step=".1"),
        daily_data_cost=".01",
        daily_host_cost=".02",
        daily_operating_cost=".03",
    )
    stocks = changed(
        stock_policy(asset="OPTION"),
        instruments=(
            changed(stock_policy().instruments[0], provider=first.baseline.limits.provider),
        ),
        family_priority=first.baseline.scope.family_priority,
    )
    sessions = []
    for index, session in enumerate(old.sessions):
        original = session.baseline
        h = MixedTapeHeader.model_validate(
            original.tape.header.model_dump()
            | {
                "version": "mixed-market-tape-v1",
                "stock_limits": owner.stocks,
                "stocks": stocks,
            }
        )
        location = path / ("mixed-" + str(index) + ".tape")
        with MixedTapeRecorder(location, h) as recorder:
            for event in original.tape.events:
                frame = event.frame
                if event.kind == "CYCLE":
                    frame = changed(
                        frame,
                        stocks=(
                            StockCycleInput(
                                quote=changed(
                                    quote(event.recorded_at),
                                    instrument=stocks.instruments[0],
                                )
                            ),
                        ),
                    )
                recorder.append(frame, recorded_at=event.recorded_at, kind=event.kind)
            recorder.seal()
        sessions.append(
            MixedReplaySession(tape=load_mixed_tape(location), watch_actions=original.watch_actions)
        )
    accounts = []
    for arm, a in zip(
        "ABCD", (first.baseline, first.shortlist, first.entry, first.managed), strict=True
    ):
        paid = arm != "A"
        decisions = []
        if paid:
            for d in a.script.decisions:
                select = d.action in {"ENTER", "SELECT"}
                values = d.model_dump(exclude={"scope"})
                values["asset"] = ("SCOPE" if d.scope else "OPTION") if select else None
                decisions.append(MixedScriptedDecision.model_validate(values))
        accounts.append(
            MixedReplayAccount(
                arm=arm,
                limits=a.limits,
                execution=changed(
                    a.execution,
                    mixed_owner=changed(owner, reasoning="mixed-paid-entry-v1" if paid else None),
                ),
                scope=a.scope,
                judgment_limits=a.judgment_limits if paid else None,
                entry_policy=changed(
                    a.entry_policy,
                    mixed_selection="mixed-paid-entry-v1",
                    mixed_shortlist="mixed-choice-only-v1" if arm == "B" else None,
                    scope_selection="scope-fixed-plan-v1",
                    scope_carry_shortlist=None,
                )
                if paid
                else None,
                position_policy=changed(
                    a.position_policy, mixed_management="mixed-stock-position-v1"
                )
                if arm == "D"
                else None,
                script=MixedReplayScript(arm=arm, decisions=tuple(decisions)) if paid else None,
            )
        )
    return MixedComparison(sessions=tuple(sessions), accounts=tuple(accounts))


@pytest.mark.parametrize("family", ["SWING", "SCOPE"])
def test_combined_carry_request_keeps_original_complete_contracts(tmp_path, family):
    request = combined_request(tmp_path / "source", family)
    assert MixedComparison.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("family", ["SWING", "SCOPE"])
def test_native_combined_carry_and_scope_reconstruct_independent_costs(tmp_path, family):
    request = combined_request(tmp_path / "source", family)
    bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "run"))
    report = verify_mixed_comparison(json.loads(json.dumps(bundle)), bundle["bundle_hash"])
    for arm, value in report["sessions"][-1]["accounts"].items():
        account = value["accounting"]
        assert not account["stock_orders"]
        assert account["ledger"]["position"] is None
        buys = [
            json.loads(row[3])
            for row in bundle["boundaries"][-1][arm]["evidence"]["execution_orders"]
            if json.loads(row[3])["side"] == "BUY"
        ]
        assert len(buys) == 1 and buys[0]["entry_lineage"]["family"] == family
        if family == "SWING":
            assert buys[0]["exit_at"] == buys[0]["swing_carry"]["exit_at"]
            gap = report["overnight_intervals"][0]["accounts"][arm]
            assert gap["ownership_status"] == "ORIGINAL_SWING_CARRY"
            assert gap["overnight_drawdown"] is None
        else:
            assert buys[0].get("swing_carry") is None
            assert (
                report["overnight_intervals"][0]["accounts"][arm]["ownership_status"]
                == "NO_HELD_POSITION"
            )
        calls = [c for c in account["costs"] if c["kind"] in {"ENTRY_MODEL", "MANAGEMENT_MODEL"}]
        assert len(calls) == (0 if arm == "A" else 2 if arm == "D" and family == "SWING" else 1)
        operating = [c for c in account["costs"] if c["kind"] in {"DATA", "HOST", "OPERATING"}]
        assert sum(Decimal(c["amount"]) for c in operating) == Decimal(".24")
        assert account["loss_control"]["state"]["consumed_entries"] == 1
    assert report["comparison_complete"]
