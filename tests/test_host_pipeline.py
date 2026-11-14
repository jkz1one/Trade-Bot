"""Full native bundle/enroll/publish/run/read/stop/restart with synthetic capture."""

import asyncio
import os
from datetime import timedelta

from fastapi.testclient import TestClient
from test_connected_runtime import digest, state
from test_host_bundle import inputs
from test_portfolio_feed import reader
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed import connected_owner, connected_runtime, host_bundle
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.dashboard_reader import create_app
from app.mixed.dashboard_snapshot import DashboardPublisher
from app.mixed.observer import MixedObserver


def test_full_native_pipeline_restarts_same_owner_and_preserves_original_inputs(
    tmp_path, schemas, monkeypatch
):
    paths, settings, _ = inputs(tmp_path, schemas)
    deployment = tmp_path / "deployment"
    deployment.mkdir(mode=0o700)
    monkeypatch.setattr(host_bundle, "STATE", deployment)
    originals = {str(p): p.read_bytes() for p in paths}
    reviewed = host_bundle.prepared(*paths, clock_source=lambda: AT)[0]
    config = deployment / "config"
    host_bundle.create(
        config, *paths, expected_review=reviewed["review_sha256"], clock_source=lambda: AT
    )
    assert host_bundle.verify(config, clock_source=lambda: AT)["status"] == "HOST_BUNDLE_VERIFIED"
    owner, collector = deployment / "owner", deployment / "collector"
    args = (
        owner,
        collector,
        config / "runtime.json",
        config / "policy.json",
        config / "schemas.json",
    )
    review = connected_owner.review(*args, clock_source=lambda: AT)[0]
    connected_owner.enroll(*args, expected_review=review["review_sha256"], clock_source=lambda: AT)
    snapshot = tmp_path / "snapshot"
    times = [AT]
    pub = DashboardPublisher(
        owner, snapshot, os.getuid(), os.getgid(), create=True, clock_source=lambda: times[0]
    )
    try:
        pub.publish()
        binding = pub.binding
    finally:
        pub.close()
    observations = []

    async def capture(self, stop, *, clock_source, held_source, calendar, source_settings=None):
        assert state(owner)[0]["heartbeat_at"] is not None
        result = await self.tick(
            now=times[0],
            held=held_source(),
            reader=reader(
                times[0], observations, source_shift=int((times[0] - AT).total_seconds())
            ),
        )
        assert result["status"] == "DELIVERED"
        times[0] += timedelta(seconds=2)
        for _ in range(150):
            if state(owner)[0]["feed_sequence"] == result["sequence"]:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("Native runtime did not consume the captured packet")
        stop.set()

    monkeypatch.setattr(ContinuousFeed, "run", capture)
    key = tmp_path / "password"
    key.write_text("offline-pipeline-test-password")
    key.chmod(0o600)
    initial = MixedObserver(
        owner / "options.db", settings.limits.population_id, clock=lambda: times[0]
    ).report()
    identity = os.stat(owner / "options.db").st_ino
    for generation in (1, 2):
        run_args = (owner, collector, config / "policy.json", config / "schemas.json")
        result = asyncio.run(
            connected_runtime.run(
                *run_args,
                asyncio.Event(),
                clock_source=lambda: times[0],
                snapshot_directory=snapshot,
                reader_uid=os.getuid(),
                reader_gid=os.getgid(),
            )
        )
        assert result["status"] == "STOPPED" and result["dashboard_published"]
        runtime, _ = state(owner)
        assert runtime["generation"] == runtime["feed_sequence"] == generation
        assert runtime["status"] == "STOPPED"
        source = MixedObserver(
            owner / "options.db", settings.limits.population_id, clock=lambda: times[0]
        ).report()
        assert source["cash"] == initial["cash"] and source["fill_count"] == 0
        before = digest(deployment)
        with TestClient(
            create_app(snapshot, binding, str(key), clock_source=lambda: times[0])
        ) as client:
            assert client.get("/api/mixed").status_code == 401
            client.auth = ("trader", key.read_text())
            response = client.get("/api/mixed")
            assert response.status_code == 200
            data = response.json()
            assert not data.pop("admin_enabled")
            assert data == source
            assert client.post("/api/mixed").status_code == 405
        assert digest(deployment) == before
        assert os.stat(owner / "options.db").st_ino == identity
        times[0] += timedelta(seconds=20)
    assert len(observations) == 2
    assert {str(p): p.read_bytes() for p in paths} == originals
