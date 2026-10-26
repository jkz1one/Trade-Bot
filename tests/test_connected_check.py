"""Real runtime configuration is cross-checked before any collector is opened."""

from datetime import timedelta

import pytest
from test_portfolio_replay import request
from test_robinhood_read_mapping import AT, instrument
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed.connected_check import connection_report
from app.mixed.continuous_feed import FeedPolicy
from app.options.read_capture import CapturePolicy
from app.options.runtime_models import RuntimeSettings


def configuration(tmp_path):
    value = request(tmp_path).settings.model_dump(mode="json")
    value["limits"].update(
        provider="robinhood", option_source="robinhood-mcp", underlying_source="robinhood-mcp"
    )
    value["execution"]["mixed_owner"]["stocks"].update(
        provider="robinhood", quote_source="robinhood-mcp"
    )
    value["setup"]["history_source"] = "robinhood-mcp"
    value["selection"]["metadata_source"] = "robinhood-mcp"
    value["runtime"].update(feed_file=str(tmp_path / "feed/feed.json"), feed_max_age_seconds=30)
    for stock in value["stock_policy"]["instruments"]:
        stock["provider"] = "robinhood"
    settings = RuntimeSettings.model_validate(value)
    feed = FeedPolicy(
        population_id=settings.limits.population_id,
        stocks=settings.stock_policy.instruments,
        candidates=(instrument(),),
        capture=CapturePolicy(oauth_file="/unopened/private", timeout_seconds=5.0),
    )
    return settings, feed


def report(tmp_path, schemas, settings, feed, now=AT):
    return connection_report(
        settings,
        feed,
        schemas,
        journal=tmp_path / "owner/options.db",
        directory=tmp_path / "feed",
        now=now,
    )


def test_matching_wiring_does_not_claim_entitlement_or_open_credentials(tmp_path, schemas):
    settings, feed = configuration(tmp_path)
    before = settings.model_dump_json(), feed.model_dump_json()
    result = report(tmp_path, schemas, settings, feed)
    assert result["collector_can_start"] and not result["wiring_errors"]
    assert not result["trading_ready"] and not result["credentials_opened"]
    assert "ENTITLEMENT_NOT_ESTABLISHED" in result["entry_blockers"]
    assert not (tmp_path / "feed").exists()
    assert before == (settings.model_dump_json(), feed.model_dump_json())


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("population_id", "another-account", "POPULATION_MISMATCH"),
        ("poll_seconds", 30, "POLL_INTERVAL_EXCEEDS_FEED_FRESHNESS"),
    ],
)
def test_mismatched_owner_or_cadence_blocks_collector(tmp_path, schemas, field, value, reason):
    settings, feed = configuration(tmp_path)
    feed = FeedPolicy.model_validate({**feed.model_dump(), field: value})
    result = report(tmp_path, schemas, settings, feed)
    assert reason in result["wiring_errors"] and not result["collector_can_start"]


def test_expired_candidates_reported_without_removing_held_protection(tmp_path, schemas):
    settings, feed = configuration(tmp_path)
    now = feed.candidates[0].contract.last_trading_at + timedelta(seconds=1)
    result = report(tmp_path, schemas, settings, feed, now)
    assert "OPTION_LAST_TRADING_PASSED" in result["option_candidates"][0]["blockers"]
    assert result["collector_can_start"]  # Reads/protection must continue for any held contract.
    from app.mixed.continuous_feed import planned

    empty, catalog = planned(feed, (), now, None, cycle=False)
    assert not empty.instrument_ids and not catalog
    held, catalog = planned(feed, feed.candidates, now, None, cycle=False)
    assert held.instrument_ids == (feed.candidates[0].instrument_id,)
    assert catalog == feed.candidates


def test_wrong_feed_file_and_stock_identity_are_rejected(tmp_path, schemas):
    settings, feed = configuration(tmp_path)
    value = settings.model_dump()
    value["runtime"]["feed_file"] = str(tmp_path / "somewhere-else.json")
    settings = RuntimeSettings.model_validate(value)
    stock = feed.stocks[0].model_copy(update={"instrument_id": "different"})
    feed = FeedPolicy.model_validate({**feed.model_dump(), "stocks": (stock, feed.stocks[1])})
    result = report(tmp_path, schemas, settings, feed)
    assert set(result["wiring_errors"]) >= {
        "RUNTIME_FEED_PATH_MISMATCH",
        "STOCK_INSTRUMENTS_MISMATCH",
    }


def test_cli_mismatch_returns_before_opening_feed_or_owner(tmp_path, schemas, monkeypatch, capsys):
    from app.mixed import feed_cli

    settings, feed = configuration(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    paths = {
        owner / "runtime.json": settings,
        tmp_path / "policy.json": feed.model_copy(update={"population_id": "other"}),
        tmp_path / "schemas.json": schemas,
    }
    for path, value in paths.items():
        path.write_text(value.model_dump_json())
        path.chmod(0o600)
    monkeypatch.setattr(
        feed_cli, "ContinuousFeed", lambda *a, **k: pytest.fail("Must not open collector")
    )
    monkeypatch.setattr(
        feed_cli, "MixedObserver", lambda *a, **k: pytest.fail("Must not open owner")
    )
    assert (
        feed_cli.main(
            [
                "--policy",
                str(tmp_path / "policy.json"),
                "--schemas",
                str(tmp_path / "schemas.json"),
                "--journal",
                str(owner / "options.db"),
                "--directory",
                str(tmp_path / "feed"),
                "--create",
            ]
        )
        == 2
    )
    assert "POPULATION_MISMATCH" in capsys.readouterr().out
