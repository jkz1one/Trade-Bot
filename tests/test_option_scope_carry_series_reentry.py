"""A later paid Scope call cannot erase the prior closed loss in a carry series."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

from test_option_scope_carry_series import request
from test_option_scope_context import bind
from test_option_scope_market_tape import record
from test_option_scope_series import shifted
from test_option_scope_structure import bind as bind_structure

from app.options.coordinator import DegenFrame
from app.options.market_tape import TapeHeader
from app.options.scope_carry_series import (
    ScopeCarryComparison,
    ScopeCarrySeries,
    run_scope_carry_series,
    verify_scope_carry_series,
)
from app.options.scope_tape_watch import ScopeTapeWatchAction


def test_later_scope_entry_retains_prior_loss_and_each_account_charge(tmp_path):
    original = request(tmp_path, family="SCOPE")
    first = original.sessions[0]
    tape = first.baseline.tape
    shift = timedelta(days=7)
    header = TapeHeader.model_validate(shifted(tape.header.model_dump(mode="json"))).model_copy(
        update={"declared_at": tape.header.declared_at}
    )
    frames = []
    for event in tape.events:
        frame = DegenFrame.model_validate(shifted(event.frame.model_dump(mode="json")))
        if frame.scope:
            frame = frame.model_copy(
                update={
                    "scope": frame.scope.model_copy(
                        update={
                            "frame": bind(bind_structure(frame.scope.frame), frame.scope.context)
                        }
                    )
                }
            )
        frames.append((event.recorded_at + shift, event.kind, frame))
    later = record(tmp_path / "reentry.tape", header, frames)
    actions = tuple(
        ScopeTapeWatchAction.model_validate(
            shifted(a.model_dump(mode="json")) | {"key": a.key + "-later"}
        )
        for a in first.baseline.watch_actions
    )
    arms = {}
    for name in ("baseline", "shortlist", "entry", "managed"):
        r = getattr(first, name)
        if name != "baseline":
            decisions = r.script.decisions
            additional = tuple(
                d.model_copy(
                    update={
                        "cycle_key": d.cycle_key.split(":")[0]
                        + ":"
                        + str(int(d.cycle_key.split(":")[1]) + int(shift.total_seconds()) // 300)
                    }
                )
                for d in decisions
            )
            r = r.model_copy(
                update={"script": r.script.model_copy(update={"decisions": decisions + additional})}
            )
        arms[name] = r
    first = ScopeCarryComparison(**arms)
    second = ScopeCarryComparison(
        **{
            name: r.model_copy(update={"tape": later, "watch_actions": actions})
            for name, r in arms.items()
        }
    )
    req = ScopeCarrySeries(
        sessions=(first, second),
        gaps=(original.gaps[0].model_copy(update={"ends_at": header.opens_at}),),
    )
    result = asyncio.run(run_scope_carry_series(req, tmp_path / "run"))
    assert result["comparison_complete"], result
    bundle = json.loads((tmp_path / "run/series.json").read_text())
    for arm in "ABCD":
        earlier, last = [b[arm] for b in bundle["boundaries"]]
        old = earlier["report"]["outcomes"][0]
        outcomes = last["report"]["outcomes"]
        assert len(outcomes) == 2
        assert old in outcomes
        assert last["report"]["loss_control"]["state"]["locked"]
        assert last["report"]["loss_control"]["state"]["consecutive_losses"] == 2
        calls = last["evidence"]["execution_model_calls"]
        assert len(calls) == (0 if arm == "A" else 2)
        assert Decimal(last["report"]["model_costs"]["known_cost"]) == (
            Decimal(0) if arm == "A" else Decimal(".00030")
        )
        assert last["report"]["ledger"]["position"] is None
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == result
