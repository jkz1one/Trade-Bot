"""Missing Scope close evidence cannot create a flat balance at rollover."""

import asyncio
import json

from test_option_scope_market_tape import record
from test_option_scope_series import request

from app.options.scope_comparison import ScopeComparison
from app.options.scope_series import ScopeSeries, run_scope_series, verify_scope_series


def test_unfilled_original_scope_exit_stays_owned_across_sessions(tmp_path):
    req = request(tmp_path, settlement=False, unknown=True)
    first, later = req.sessions
    tape = first.baseline.tape
    unfilled = record(
        tmp_path / "unfilled.tape",
        tape.header,
        [
            (e.recorded_at, e.kind, e.frame)
            for e in tape.events
            if e.recorded_at < tape.header.scope.session.protect_at
        ],
    )
    first = ScopeComparison.model_validate(
        first.model_copy(
            update={
                name: getattr(first, name).model_copy(update={"tape": unfilled})
                for name in ("baseline", "shortlist", "entry", "managed")
            }
        ).model_dump()
    )
    req = ScopeSeries(sessions=(first, later))
    report = asyncio.run(run_scope_series(req, tmp_path / "run"))
    assert not report["comparison_complete"]
    assert report["net_difference_vs_a"] == dict.fromkeys("BCD")
    a, b = report["sessions"]
    for arm in "ACD":
        first = a["accounts"][arm]
        later = b["accounts"][arm]
        original = first["closing"]["position"]
        assert original is not None
        assert later["opening"] == first["closing"]
        held = later["closing"]["position"]
        assert held["entry_client_id"] == original["entry_client_id"]
        assert held["exit_at"] == original["exit_at"]
        assert held["contract"] == original["contract"]
        assert held["exit_reason"] == "TIME_EXIT"
        assert held["quantity"] == original["quantity"]
        assert len(later["native"]["orders"]) == 1
        assert later["native"]["net_after_all_costs"] is None
        assert "OPEN_POSITION" in later["native"]["reasons"]
    bundle = json.loads((tmp_path / "run/series.json").read_text())
    assert verify_scope_series(bundle, bundle["series_hash"])["report"] == report
