"""Continuous native cash, original stock carry and explicit session boundaries."""

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT
from test_mixed_native_owner import changed
from test_mixed_replay import request_for
from test_mixed_selection import quote, source_fixture, stock_frame, stock_policy
from test_mixed_stock_carry import carry_policy

from app.mixed.comparison import verify_mixed_comparison
from app.mixed.market_tape import MixedTapeRecorder, load_mixed_tape
from app.mixed.replay import MixedReplaySession, run_mixed_comparison
from app.mixed.sources import StockCycleInput, candidates
from app.options.coordinator import DegenFrame
from app.options.lifecycle import OptionReceipt
from app.options.replay import ScriptedSettlement
from app.robinhood.schedule import XNYSCalendar


def series_request(path, *, carry=False, settle=False):
    request = request_for(path)
    first = request.sessions[0].tape
    if carry:
        source, swing, item, _ = source_fixture()
        source = changed(source, carry_exit_session=date(2026, 10, 12))
        item = changed(item, swing=source)
        h = changed(first.header, stocks=stock_policy(swing=swing))
        accounts = []
        for account in request.accounts:
            owner = changed(
                account.execution.mixed_owner,
                stock_carry=carry_policy(),
                daily_data_cost=".01",
                daily_host_cost=".02",
                daily_operating_cost=".03",
            )
            execution = changed(account.execution, mixed_owner=owner)
            script = account.script
            if script is not None:
                proposed, _, _ = candidates(
                    item,
                    stock_frame().histories[0],
                    h.setup,
                    h.stocks,
                    execution,
                    XNYSCalendar(),
                    now=AT,
                )
                index = next(i for i, c in enumerate(proposed) if c.proposal.family == "SWING")
                script = changed(
                    script, decisions=(changed(script.decisions[0], candidate_index=index),)
                )
            accounts.append(changed(account, execution=execution, script=script))
        with MixedTapeRecorder(path / "carry.tape", h) as recorder:
            recorder.append(stock_frame(item=item), recorded_at=AT)
            for seconds in (1, 2):
                at = AT + timedelta(seconds=seconds)
                recorder.append(
                    DegenFrame(stocks=(StockCycleInput(quote=quote(at)),)),
                    recorded_at=at,
                    kind="MARKET",
                )
            recorder.seal()
        first = load_mixed_tape(path / "carry.tape")
        request = changed(request, accounts=tuple(accounts))
    shift = timedelta(days=3)
    h = changed(
        first.header,
        session_key="2026-10-12",
        opens_at=first.header.opens_at + shift,
        closes_at=first.header.closes_at + shift,
    )
    with MixedTapeRecorder(path / "monday.tape", h) as recorder:
        moments = [h.opens_at]
        if carry:
            deadline = h.closes_at - timedelta(minutes=15)
            moments.extend((deadline, deadline + timedelta(seconds=1)))
        for at in moments:
            recorder.append(
                DegenFrame(stocks=(StockCycleInput(quote=quote(at)),)),
                recorded_at=at,
                kind="MARKET",
            )
        recorder.seal()
    later = load_mixed_tape(path / "monday.tape")
    receipts = (
        tuple(
            ScriptedSettlement(
                arm=arm,
                receipt=OptionReceipt(
                    receipt_id="original-explicit-funds",
                    sequence=3,
                    kind="FUNDS_SETTLED",
                    occurred_at=h.opens_at - timedelta(hours=1),
                    cash_change="1",
                ),
            )
            for arm in "ABCD"
        )
        if settle
        else ()
    )
    return changed(
        request,
        sessions=(MixedReplaySession(tape=first), MixedReplaySession(tape=later)),
        settlements=receipts,
    )


@pytest.mark.parametrize("carry,settle", [(False, False), (False, True), (True, False)])
def test_native_session_cash_original_carry_and_explicit_settlement(tmp_path, carry, settle):
    request = series_request(tmp_path / "source", carry=carry, settle=settle)
    bundle = asyncio.run(run_mixed_comparison(request, tmp_path / "run"))
    report = verify_mixed_comparison(json.loads(json.dumps(bundle)), bundle["bundle_hash"])
    friday, monday = report["sessions"]
    for arm in "ABCD":
        before = friday["accounts"][arm]["accounting"]
        after = monday["accounts"][arm]["accounting"]
        if carry:
            entry = before["ledger"]["stock_position"]["entry"]
            assert before["net_after_all_costs"] is None
            assert entry["carry"]["sessions"][-1]["session"] == "2026-10-12"
            assert after["stock_orders"][0] == before["stock_orders"][0]
            assert after["ledger"]["stock_position"] is None
            assert after["outcomes"][0]["status"] == "COMPLETE"
            operating = [c for c in after["costs"] if c["kind"] in {"DATA", "HOST", "OPERATING"}]
            assert sum(Decimal(c["amount"]) for c in operating) == Decimal(".24")
        else:
            assert after["ledger"]["cash"] == before["ledger"]["cash"]
            assert Decimal(after["ledger"]["settled_cash"]) == Decimal(
                before["ledger"]["settled_cash"]
            ) + int(settle)
            assert after["outcomes"] == before["outcomes"]
        assert after["loss_control"]["state"]["consumed_entries"] == 1
    assert report["comparison_complete"]


@pytest.mark.parametrize(
    "damage", ["clock", "policy", "declaration", "settlement", "carry", "role"]
)
def test_mixed_series_rejects_changed_original_boundary_before_creation(tmp_path, damage):
    request = series_request(tmp_path / "source", carry=damage == "carry")
    raw = request.model_dump()
    if damage in {"clock", "policy", "declaration"}:
        # Rebuild a correctly sealed tape so the common series contract must reject it.
        h = request.sessions[1].tape.header
        h = changed(
            h,
            **{
                "clock": {
                    "session_key": request.sessions[0].tape.header.session_key,
                    "opens_at": h.opens_at - timedelta(days=3),
                    "closes_at": h.closes_at - timedelta(days=3),
                },
                "policy": {"stocks": changed(h.stocks, asset_priority=("OPTION", "STOCK"))},
                "declaration": {"declared_at": h.declared_at - timedelta(seconds=1)},
            }[damage],
        )
        with MixedTapeRecorder(tmp_path / "bad.tape", h) as recorder:
            recorder.seal()
        raw["sessions"] = (
            raw["sessions"][0],
            {"tape": load_mixed_tape(tmp_path / "bad.tape").model_dump()},
        )
    elif damage == "settlement":
        raw["settlements"] = [
            {
                "arm": "A",
                "receipt": {
                    "receipt_id": "within-session",
                    "sequence": 3,
                    "kind": "FUNDS_SETTLED",
                    "occurred_at": AT,
                    "cash_change": "1",
                },
            }
        ]
    elif damage == "carry":
        raw["accounts"][0]["execution"]["mixed_owner"]["stock_carry"] = None
    else:
        raw["accounts"][3]["position_policy"]["scope_management"] = "scope-fixed-position-v1"
    with pytest.raises(ValueError):
        type(request).model_validate(raw)
