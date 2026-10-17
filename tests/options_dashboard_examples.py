"""Offline dashboard rendering drill. Synthetic presentation examples, never a worker."""

import argparse
import asyncio
import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from test_option_comparison_view import result_for
from test_option_entry_coordination import cycle, fake_model, owned_entry
from test_option_position_coordination import (
    enter_position,
    management_frame,
    model,
    owned_manager,
)

from app.options.comparison_view import build_comparison, chart_data
from app.options.observer import OptionObserver
from app.web.options import templates


def examples(root):
    """Native entry/management/fill baseline plus explicitly altered display states."""
    with pytest.MonkeyPatch.context() as patch, owned_manager(root) as (c, venue, times):
        enter_position(c, venue, times, patch)
        model(patch, c, action="TIGHTEN")
        assert asyncio.run(c.cycle(management_frame()))["status"] == "TIGHTENED"
        observer = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        )
        populated = observer.report()
        assert populated["status"] == "OK"
        stale = OptionObserver(
            c.engine.journal.path,
            c.engine.limits.population_id,
            clock=lambda: times[0] + timedelta(minutes=5),
        ).report()
        empty = OptionObserver(root / "absent.db", "not-created", clock=c.clock).report()
        unavailable = OptionObserver(
            c.engine.journal.path, "wrong-population", clock=c.clock
        ).report()

    # Comparison is a publication-unit fixture, not linked native economic acceptance.
    populated["comparison"] = {
        "status": "AVAILABLE",
        **build_comparison(result_for(), "B").model_dump(mode="json"),
    }
    halted = copy.deepcopy(populated)
    halted["entry"].update(halted=True, halt_reason="OPERATOR_REVIEW_REQUIRED")
    halted["entry"]["recorded_blockers"].append("ENTRY_HALTED")
    unknown = copy.deepcopy(populated)
    unknown["active_orders"] = 1
    unknown["orders"][0].update(status="UNKNOWN", unresolved=True)
    unknown["model"].update(unknown_calls=1, cost_status="UNKNOWN")
    unknown["economics"].update(
        equity_before_exit_costs=None, equity_after_known_model_cost_before_exit_costs=None
    )
    unknown["entry"]["recorded_blockers"].extend(["ORDER_UNRESOLVED", "MODEL_COST_UNKNOWN"])
    unknown["opportunities"][0]["attribution"].update(model_cost=None, cost_status="UNKNOWN")
    unknown["comparison"] = {"status": "UNAVAILABLE"}
    long_text = copy.deepcopy(populated)
    long_text["population_id"] = "long-population-" + "X" * 110
    long_text["opportunities"][0]["attribution"]["thesis"] = (
        '<script>alert("fixture")</script> ' + "LongUnbrokenEvidence" * 90
    )
    long_text["opportunities"][0]["attribution"]["uncertainty"] = "UncertainEvidence" * 30
    hold_path = root / "hold-state"
    hold_path.mkdir()
    with pytest.MonkeyPatch.context() as patch, owned_entry(hold_path) as (c, _, _, _):
        fake_model(patch, c, action="HOLD")
        assert cycle(c)["status"] == "HOLD"
        hold = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
    return {
        "populated": populated,
        "empty": empty,
        "unavailable": unavailable,
        "stale": stale,
        "halted": halted,
        "unknown": unknown,
        "long-text": long_text,
        "hold": hold,
    }


def render(data):
    return templates.env.get_template("options.html").render(
        data=data,
        auto_refresh=False,
        family="ALL",
        comparison_chart=chart_data(data.get("comparison", {"status": "NOT_CONFIGURED"})),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error("Absolute new output directory required")
    args.output.mkdir(mode=0o700)
    source = args.output / "fixture-state"
    source.mkdir(mode=0o700)
    states = examples(source)
    for name, data in states.items():
        (args.output / (name + ".html")).write_text(render(data))
        for size, width in (("desktop", 1360), ("mobile", 390)):
            (args.output / f"{name}-{size}.html").write_text(
                '<!doctype html><html lang="en"><meta charset="utf-8"><title>Dashboard rendering drill</title>'
                "<style>body{margin:0;background:#060a10;color:#d6dfec;font:13px system-ui}"
                "p{margin:10px 16px}iframe{display:block;border:0}</style>"
                f"<p>DISPLAY FIXTURE · {name} · {width}px viewport · no trader attached</p>"
                f'<iframe src="{name}.html" title="{name} dashboard at {width}px" '
                f'width="{width}" height="1100"></iframe></html>'
            )
    print(
        json.dumps({"states": list(states), "viewports": [1360, 390], "execution_authority": False})
    )


if __name__ == "__main__":
    main()
