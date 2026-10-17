"""Dashboard evidence stages, uncertainty and stored protection stay distinct."""

from html.parser import HTMLParser

import pytest
from options_dashboard_examples import examples, render
from test_option_execution import owned
from test_option_health_management import POLICY, assess, start
from test_option_observer import digest

from app.options.observer import OptionObserver
from app.web.options import templates


class Outline(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.ids = []
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.links.append(attrs["href"][1:])


@pytest.fixture(scope="module")
def states(tmp_path_factory):
    return examples(tmp_path_factory.mktemp("dashboard"))


@pytest.mark.parametrize(
    "state",
    ["populated", "empty", "unavailable", "stale", "halted", "unknown", "long-text", "hold"],
)
def test_rendering_drill_retains_truth_and_accessible_navigation(states, state):
    html = render(states[state])
    outline = Outline(html)
    assert len(outline.ids) == len(set(outline.ids))
    assert set(outline.links) <= set(outline.ids)
    assert not {"script", "form", "button", "iframe"} & set(outline.tags)
    assert "LIVE DISABLED" in html and "Read-only stored evidence" in html
    if state in {"empty", "unavailable"}:
        assert "Current equity estimate" not in html
        assert "No zero balance, flat position or healthy trader is inferred" in html
    if state == "stale":
        assert "STALE" in html and "Unavailable" in html
    if state == "halted":
        assert "ENTRY HALTED" in html and "OPERATOR_REVIEW_REQUIRED" in html
    if state == "unknown":
        assert "UNKNOWN" in html and "MODEL_COST_UNKNOWN" in html
        assert 'Current equity estimate</div><div class="value">Unavailable' in html
        assert "does not match this population" in html
    if state == "long-text":
        assert "&lt;script&gt;" in html and "UncertainEvidence" in html
    if state == "hold":
        assert states["hold"]["opportunities"][0]["attribution"]["proposal_action"] == "HOLD"
        assert "HOLD" in html
        assert "No linked order" in html and "No linked fills" in html


def test_native_entry_and_management_keep_stages_costs_and_uncertainty(states):
    data = states["populated"]
    html = render(data)
    assert {i["attribution"]["role"] for i in data["opportunities"]} == {"ENTRY", "MANAGEMENT"}
    assert all(
        phase in html for phase in ("01 · Proposal", "02 · Review", "03 · Order", "04 · Fills")
    )
    assert "No guaranteed fill or outcome" in html
    assert html.count("$0.00015") >= 2
    management = data["opportunities"][0]["attribution"]
    assert management["proposal_action"] == "TIGHTEN" and management["client_id"] is None
    assert data["fills"] and data["opportunities"][1]["attribution"]["filled_quantity"] > 0
    assert "No linked order" in html  # Applying a stop never invents an order.


def test_stored_native_health_shows_stale_label_without_rewriting_assessment(tmp_path):
    from datetime import timedelta

    from test_option_admission import NOW

    with owned(tmp_path, **POLICY) as (engine, venue, data):
        start(engine, venue, data)
        assess(engine, venue, data, 1, iv=".34")
        paths = [engine.journal.path, venue.path]
        before = digest(paths)
        for seconds, label in [
            (1, "Within recorded observation window"),
            (60, "Observations stale or incomplete"),
        ]:
            view = OptionObserver(
                engine.journal.path,
                engine.limits.population_id,
                clock=lambda seconds=seconds: NOW + timedelta(seconds=seconds),
            ).report()
            assert view["status"] == "OK", view
            html = render(view)
            assert "Stored health assessment" in html and "CAUTION" in html
            assert "PRETARGET_HEALTH_STOP" in html and label in html
            if seconds == 60:
                assert 'Current equity estimate</div><div class="value">Unavailable' in html
        assert digest(paths) == before


def test_unestablished_floors_and_unknown_pressure_are_not_zero_or_healthy():
    html = templates.env.get_template("options_protection.html").module.protection(
        {
            "trade_floor": {"minimum_exit_fill_price": None},
            "premium_trail": {"floor_original_quantity_premium": None},
            "greek_pressure": {
                "status": "INCOMPLETE",
                "evaluated_at": "fixture-time",
                "iv_change_pct": None,
                "absolute_delta_change_pct": None,
                "reference_hourly_theta_pct": None,
                "reasons": ["CURRENT_GREEKS_MISSING"],
            },
        }
    )
    assert html.count("Not established") == 2
    assert html.count("Unknown") == 3
    assert "$0" not in html and "CURRENT_GREEKS_MISSING" in html
