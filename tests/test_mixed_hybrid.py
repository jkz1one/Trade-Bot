"""Hybrid display contracts: exact joins, preserved chart gaps and read-only inspection."""

import copy
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from test_mixed_native_owner import NOW, enter, owned_mixed
from test_mixed_observer import render, view
from test_option_observer import digest

from app.web.mixed_view import evidence_id, mixed_view


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids, self.targets, self.panels = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and a.get("href", "").startswith("#"):
            self.targets.append(a["href"][1:])
        if "data-panel" in a:
            self.panels.append(a["data-panel"])


def test_paged_decision_never_adopts_latest_unrelated_order(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        _, at = enter(e, v)
        data = view(e, at)
        data["decisions"] = [
            {
                "key": "older-unrelated-cycle",
                "status": "COMPLETE",
                "started_at": NOW.isoformat(),
                "proposal": {"action": "HOLD"},
            }
        ]
        before = copy.deepcopy(data)
        mapped = mixed_view(data)
        assert mapped["key"] == "older-unrelated-cycle"
        assert mapped["stages"][0]["value"] == "HOLD"
        assert mapped["stages"][2]["value"] == "Not recorded in this view"
        assert mapped["stages"][3]["value"] == "Coverage unavailable"
        assert data == before


def test_incomplete_accounting_never_projects_fill_activity(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        _, at = enter(e, v)
        data = view(e, at)
        assert any(x["kind"] == "FILL" for x in mixed_view(data)["activity"])
        data["accounting"] = "UNAVAILABLE"
        mapped = mixed_view(data)
        assert not any(x["kind"] == "FILL" for x in mapped["activity"])
        assert mapped["stages"][3]["value"] == "Coverage unavailable"


def test_each_record_range_preserves_null_boundaries_and_isolated_points():
    points = [
        {"at": NOW.isoformat(), "equity": "1000", "reason": "FLAT_FULL_COST_BOUNDARY"}
        for _ in range(60)
    ]
    points[-2]["equity"] = None
    data = {"points": points}
    before = copy.deepcopy(data)
    for item, length in zip(mixed_view(data)["ranges"], (20, 50, 60), strict=True):
        assert len(item["points"]) == length
        assert item["points"][-2]["equity"] is None
        assert len(item["chart"]["segments"]) == 2
        assert len(item["chart"]["gaps"]) == 1
        assert len(item["chart"]["dots"]) == length - 1
    assert data == before


@pytest.mark.parametrize("reason", ["DATABASE_NOT_CREATED", "INVALID_EVIDENCE"])
def test_unavailable_page_retains_layout_without_fabricated_values(reason):
    html = render(
        {
            "status": "UNAVAILABLE",
            "reason": reason,
            "observed_at": NOW.isoformat(),
            "population_id": "no-account",
        }
    )
    assert 'id="balance"' in html and 'id="trade-card"' in html
    assert "No equity history yet" in html and "No decisions available yet" in html
    assert (
        "No PAPER account connected" in html
        if reason == "DATABASE_NOT_CREATED"
        else "Position unavailable" in html
    )
    assert "<polyline" not in html
    page = Page(html)
    assert len(page.ids) == len(set(page.ids))
    assert set(page.targets + page.panels) <= set(page.ids)


def test_populated_nested_tabs_links_exact_identity_and_escaping(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        data = view(e, at)
        data["position"]["thesis"] = "<script>bad()</script>"
        before = digest([e.journal.path, v.path])
        html = render(data)
        assert "<script>bad()</script>" not in html and "&lt;script&gt;" in html
        page = Page(html)
        assert len(page.ids) == len(set(page.ids))
        assert set(page.targets + page.panels) <= set(page.ids)
        assert evidence_id(entry.client_id) in page.ids
        assert {"trade-summary", "trade-thesis", "trade-protection", "trade-fills"} <= set(
            page.panels
        )
        assert digest([e.journal.path, v.path]) == before


def test_diagnostic_reads_copied_venue_without_dispatch_or_source_changes(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        enter(e, v)
        # Inspector intentionally accepts only its dedicated UI population; this
        # normal fixture must fail before launching a native child operation.
        script = Path(__file__).resolve().parents[1] / "scripts/dashboard-review-diagnose.py"
        before = digest([e.journal.path, v.path])
        result = subprocess.run(
            [sys.executable, "-I", "-W", "error", str(script), "--source", str(tmp_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            env={k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ},
        )
        assert result.returncode != 0
        assert "Expected isolated UI review population required" in result.stderr
        assert digest([e.journal.path, v.path]) == before
