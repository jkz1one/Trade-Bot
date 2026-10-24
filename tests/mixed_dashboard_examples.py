"""Create-only offline mixed desk review pages; no service or real account attached."""

import argparse
import asyncio
import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from test_mixed_entry import scope_owner
from test_mixed_native_owner import NOW, changed, close, enter, owned_mixed
from test_mixed_observer import render, view
from test_option_execution import intent_for

from app.web.options import templates


def examples(root):
    states = {}
    with owned_mixed(root) as (owner, venue):
        states["flat"] = view(owner)
        entry, at = enter(owner, venue)
        states["stock"] = view(owner, at)
        states["stale"] = view(owner, at + timedelta(minutes=5))
        _, at = close(owner, venue, entry, at + timedelta(seconds=1))
        states["closed"] = view(owner, at)
    for choice in ("OPTION", "SCOPE"):
        folder = root / choice.lower()
        folder.mkdir(mode=0o700)
        with (
            pytest.MonkeyPatch.context() as patch,
            scope_owner(folder, patch, choice) as (c, venue, times, frame),
        ):
            result = asyncio.run(c.cycle(frame))
            entry = intent_for(c.engine, result["client_id"])
            q, u = (
                (frame.scope.frame.quote, frame.scope.underlying)
                if choice == "SCOPE"
                else (frame.quotes[0], frame.underlyings[0])
            )
            q = changed(q, source_at=times[0], received_at=times[0])
            u = changed(u, source_at=times[0], received_at=times[0])
            venue.fill(entry, entry.quantity, q, times[0], fill_id="review", underlying=u)
            assert c.engine.reconcile(venue.snapshot(times[0]), now=times[0])["reconciled"]
            states[choice.lower()] = view(c.engine, times[0])
    folder = root / "unknown"
    folder.mkdir(mode=0o700)
    with owned_mixed(folder, daily_host_cost=None) as (owner, _):
        states["unknown-cost"] = view(owner)
    states["unavailable"] = {
        "status": "UNAVAILABLE",
        "reason": "DISPLAY_FIXTURE_UNAVAILABLE",
        "observed_at": NOW.isoformat(),
        "population_id": "display-fixture",
    }
    # Explicit presentation-only alteration for clipping and escaped-text review.
    states["long-text"] = copy.deepcopy(states["stock"])
    states["long-text"]["position"]["thesis"] = (
        '<script>alert("fixture")</script>' + "LongEvidence" * 100
    )
    return states


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error("Absolute new output directory required")
    args.output.mkdir(mode=0o700)
    state = args.output / "fixture-state"
    state.mkdir(mode=0o700)
    (args.output / "desk.js").write_text(
        templates.env.get_template("options_desk_script.html").render()
    )
    states = examples(state)
    for name, data in states.items():
        assert data["status"] == "OK" or name == "unavailable", (name, data)
        # Relative packaged script permits an extracted offline review pack.
        (args.output / f"{name}.html").write_text(
            render(data).replace('src="/desk.js"', 'src="desk.js"')
        )
        for size, width in (("desktop", 1360), ("mobile", 390)):
            (args.output / f"{name}-{size}.html").write_text(
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                "<title>Mixed desk display fixture</title></head><body>"
                f"<p>DISPLAY FIXTURE · {name} · {width}px · no trader attached</p>"
                f'<iframe title="{name} at {width}px" src="{name}.html" '
                f'width="{width}" height="1100"></iframe></body></html>'
            )
    print(
        json.dumps({"states": list(states), "viewports": [1360, 390], "visual_acceptance": False})
    )


if __name__ == "__main__":
    main()
