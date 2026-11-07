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
    assert not {"form", "iframe"} & set(outline.tags)
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


@pytest.mark.parametrize("state", ["populated", "stale", "halted", "unknown", "hold"])
def test_briefing_preserves_clock_blockers_and_original_protection(states, state):
    data = states[state]
    html = render(data)
    briefing = html.split('<section id="briefing"', 1)[1].split("</section>", 1)[0]
    assert "Newest in this selected family/page. May be historical." in briefing
    assert "This snapshot grants no approval" in briefing
    assert str(data["account"]["age_seconds"]) in briefing
    for blocker in data["entry"]["recorded_blockers"]:
        assert blocker in briefing
    if data["position"]:
        assert data["position"]["exit_at"] in briefing
        assert str(data["position"]["tightened_invalidation"]) in briefing
        assert data["position"]["quote_status"] in briefing
    else:
        assert "Missing or unresolved evidence does not establish a flat account" in briefing
    assert html.index('id="position"') < html.index('id="opportunities"')


def test_scope_selection_does_not_link_hidden_option_decisions(states):
    html = templates.env.get_template("options.html").render(
        data=states["populated"], auto_refresh=False, family="SCOPE", comparison_chart=None
    )
    outline = Outline(html)
    assert set(outline.links) <= set(outline.ids)
    assert "No decision shown" in html
    assert "No model action or order is inferred" in html


def test_missing_ages_are_unknown_while_zero_age_remains_zero(states):
    import copy

    data = copy.deepcopy(states["populated"])
    data["account"]["age_seconds"] = None
    data["supervision"]["age_seconds"] = 0
    html = render(data)
    assert "Account age</dt><dd>Unknown</dd>" in html
    assert "Supervision age</dt><dd>0 seconds</dd>" in html


def test_mixed_owner_remains_unavailable_without_changing_native_evidence(tmp_path):
    from test_mixed_native_owner import NOW, owned_mixed

    with owned_mixed(tmp_path) as (engine, venue):
        paths = [engine.journal.path, venue.path]
        before = digest(paths)
        report = OptionObserver(
            engine.journal.path, engine.limits.population_id, clock=lambda: NOW
        ).report()
        assert report["status"] == "UNAVAILABLE"
        assert "account" not in report and "position" not in report
        html = render(report)
        assert "Stored evidence unavailable" in html
        assert 'id="briefing"' not in html
        assert digest(paths) == before


@pytest.mark.parametrize("state", ["populated", "stale", "unknown", "hold"])
def test_desk_keeps_trade_and_history_outside_detail_panels(states, state):
    html = render(states[state])
    assert html.index('id="comparison"') < html.index('data-tabs="desk"')
    assert html.index('id="trade-card"') < html.index('data-tabs="desk"')
    assert html.count('data-panel-group="desk"') == 5
    assert '<script src="/desk.js" defer></script>' in html
    assert 'data-panel="execution"' in html
    assert ' hidden' not in html  # No-JavaScript fallback exposes all evidence.
    card = html.split('id="trade-card"', 1)[1].split('</section>', 1)[0]
    if states[state]["position"]:
        assert "Target touches are not fills" in card
        if states[state]["position"]["gross_bid_mark"] is None:
            assert 'Gross bid value</span><strong>Unavailable' in card


def test_desk_asset_is_authenticated_and_does_not_read_execution(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_degen_options import owned_strategy
    from test_option_observer import app_for

    with owned_strategy(tmp_path) as (coordinator, *_):
        client, key = app_for(coordinator, tmp_path)
        paths = [coordinator.engine.journal.path]
        before = digest(paths)

        def forbidden(*args, **kwargs):
            pytest.fail("Presentation asset read account evidence")

        monkeypatch.setattr(OptionObserver, "report", forbidden)
        assert TestClient(client.app).get('/desk.js').status_code == 401
        response = client.get('/desk.js')
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/javascript')
        assert "script-src 'self'" in response.headers['content-security-policy']
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'fetch(' not in response.text and 'XMLHttpRequest' not in response.text
        assert digest(paths) == before
        key.unlink()
        assert client.get('/desk.js').status_code == 503
