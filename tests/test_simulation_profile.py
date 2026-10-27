"""The deployable profile preserves budgets/families and never fabricates eligibility."""

import asyncio
import json
import os
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from test_connected_runtime import state
from test_portfolio_feed import reader
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed import connected_owner, connected_runtime, simulation_profile
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.dashboard_reader import create_app
from app.mixed.dashboard_snapshot import DashboardPublisher
from app.mixed.observer import MixedObserver
from app.options.runtime_models import RuntimeSettings


def test_review_binds_native_budget_and_keeps_missing_inputs_blocked(schemas):
    settings, feed = simulation_profile.configuration()
    review = simulation_profile.review(schemas, now=AT)
    assert review["collector_can_start"] and not review["trading_ready"]
    assert review["families"] == ["DEGEN", "SWING", "SCOPE"]
    assert settings.execution.capital == Decimal(1000)
    assert settings.execution.cost_policy.daily_budget == Decimal(1)
    assert settings.execution.cost_policy.total_budget == Decimal(5)
    assert settings.execution.mixed_owner.portfolio.max_plays == 2
    assert settings.scope_policy and settings.swing_policy and settings.stock_policy.swing
    assert not feed.candidates and all(
        not s.metadata_complete and not s.tradable for s in feed.stocks
    )
    assert set(review["entry_blockers"]) >= {
        "ENTITLEMENT_NOT_ESTABLISHED",
        "STOCK_EXECUTABLE_SIZES_UNAVAILABLE",
        "STOCK_CATALOG_UNREVIEWED",
        "NO_REVIEWED_OPTION_CANDIDATES",
        "SCOPE_CONTEXT_AND_SPX_MAPPING_UNAVAILABLE",
        "SWING_CATALYST_FEED_UNAVAILABLE",
    }
    assert not review["workers_started"] and not review["credentials_opened"]
    assert settings.limits.mode == "PAPER"


def test_profile_create_stale_hash_and_overwrite_leave_existing_inputs(tmp_path, schemas):
    dest = tmp_path / "inputs"
    with pytest.raises(ValueError, match="changed"):
        simulation_profile.create(dest, schemas, "0" * 64)
    assert not dest.exists()
    result = simulation_profile.create(
        dest, schemas, simulation_profile.review(schemas)["review_sha256"]
    )
    before = {p.name: p.read_bytes() for p in dest.iterdir()}
    with pytest.raises(FileExistsError):
        simulation_profile.create(dest, schemas, result["review_sha256"])
    assert before == {p.name: p.read_bytes() for p in dest.iterdir()}
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in dest.iterdir())


def test_full_profile_enrolls_consumes_publishes_and_restarts_same_owner(
    tmp_path, schemas, monkeypatch
):
    report = simulation_profile.review(schemas)
    inputs = tmp_path / "inputs"
    simulation_profile.create(inputs, schemas, report["review_sha256"])
    # Test namespace only: same native strategy, synthetic secret never transmitted.
    key = tmp_path / "model-key"
    key.write_text("synthetic-never-transmitted-key")
    key.chmod(0o600)
    runtime = inputs / "runtime.json"
    value = json.loads(runtime.read_text())
    value["key_file"] = str(key)
    value["runtime"]["feed_file"] = str(tmp_path / "collector/feed.json")
    settings = RuntimeSettings.model_validate(value)
    runtime.write_text(settings.model_dump_json())
    schema_file = inputs / "schemas.json"
    schema_file.write_text(schemas.model_dump_json())
    schema_file.chmod(0o600)
    args = tmp_path / "owner", tmp_path / "collector", runtime, inputs / "policy.json", schema_file
    native_review = connected_owner.review(*args, clock_source=lambda: AT)[0]
    result = connected_owner.enroll(
        *args, expected_review=native_review["review_sha256"], clock_source=lambda: AT
    )
    assert result["status"] == "OWNER_AND_COLLECTOR_ENROLLED"
    view = MixedObserver(
        args[0] / "options.db", settings.limits.population_id, clock=lambda: AT
    ).report()
    assert view["cash"] == "1000" and view["fill_count"] == 0 and not view["positions"]
    assert not result["workers_started"]
    snapshot = tmp_path / "snapshot"
    times = [AT]
    pub = DashboardPublisher(
        args[0], snapshot, os.getuid(), os.getgid(), create=True, clock_source=lambda: times[0]
    )
    try:
        pub.publish()
        binding = pub.binding
    finally:
        pub.close()

    async def capture(self, stop, *, clock_source, held_source, calendar, source_settings=None):
        delivered = await self.tick(
            now=times[0],
            held=held_source(),
            reader=reader(times[0], [], source_shift=int((times[0] - AT).total_seconds())),
        )
        assert delivered["status"] == "DELIVERED"
        times[0] += timedelta(seconds=2)
        for _ in range(150):
            if state(args[0])[0]["feed_sequence"] == delivered["sequence"]:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("Profile runtime did not consume feed")
        stop.set()

    async def no_model(*a, **kw):
        pytest.fail("Unavailable inputs must not trigger model spending")

    from app.options.coordinator import DegenCoordinator

    monkeypatch.setattr(DegenCoordinator, "_model_run", no_model)
    monkeypatch.setattr(ContinuousFeed, "run", capture)
    identity = (args[0] / "options.db").stat().st_ino
    for generation in (1, 2):
        stopped = asyncio.run(
            connected_runtime.run(
                args[0],
                args[1],
                args[3],
                args[4],
                asyncio.Event(),
                clock_source=lambda: times[0],
                snapshot_directory=snapshot,
                reader_uid=os.getuid(),
                reader_gid=os.getgid(),
            )
        )
        assert stopped["status"] == "STOPPED" and stopped["dashboard_published"]
        assert state(args[0])[0]["generation"] == generation
        assert (args[0] / "options.db").stat().st_ino == identity
        with TestClient(
            create_app(snapshot, binding, str(key), clock_source=lambda: times[0])
        ) as client:
            client.auth = ("trader", key.read_text())
            response = client.get("/api/mixed")
            assert response.status_code == 200
            assert response.json()["cash"] == "1000" and response.json()["fill_count"] == 0
        times[0] += timedelta(seconds=20)


def test_unknown_costs_rejected_before_any_native_owner_is_created(tmp_path, schemas):
    settings, feed = simulation_profile.configuration()
    value = settings.model_dump(mode="json")
    value["execution"]["mixed_owner"]["daily_host_cost"] = None
    value["runtime"]["feed_file"] = str(tmp_path / "collector/feed.json")
    settings = RuntimeSettings.model_validate(value)
    paths = [tmp_path / name for name in ("runtime.json", "policy.json", "schemas.json")]
    for p, v in zip(paths, (settings, feed, schemas)):
        p.write_text(v.model_dump_json())
        p.chmod(0o600)
    with pytest.raises(ValueError, match="operating cost"):
        connected_owner.review(tmp_path / "owner", tmp_path / "collector", *paths)
    assert not (tmp_path / "owner").exists() and not (tmp_path / "collector").exists()
