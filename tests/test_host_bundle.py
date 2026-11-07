"""Host bundle preserves supplied trading rules and changes only deployment paths."""

import json

import pytest
from test_connected_check import configuration
from test_connected_runtime import digest
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed import host_bundle as bundle


def inputs(tmp_path, schemas):
    settings, policy = configuration(tmp_path)
    paths = tmp_path / "settings.json", tmp_path / "policy.json", tmp_path / "schemas.json"
    for p, v in zip(paths, (settings, policy, schemas)):
        p.write_text(v.model_dump_json())
        p.chmod(0o600)
    return paths, settings, policy


def test_review_remaps_only_paths_without_reading_oauth_or_enrolling(tmp_path, schemas):
    paths, original, original_policy = inputs(tmp_path, schemas)
    before = digest(tmp_path)
    report, settings, policy, _ = bundle.prepared(*paths, clock_source=lambda: AT)
    a, b = original.model_dump(), settings.model_dump()
    a["runtime"]["feed_file"] = b["runtime"]["feed_file"]
    assert a == b
    a, b = original_policy.model_dump(), policy.model_dump()
    a["capture"]["oauth_file"] = b["capture"]["oauth_file"]
    assert a == b
    assert report["families"] == list(original.stock_policy.family_priority)
    assert not report["credentials_opened"] and not report["workers_started"]
    assert not report["trading_ready"] and digest(tmp_path) == before


def test_bundle_create_verify_and_overwrite_refusal(tmp_path, schemas):
    paths, _, _ = inputs(tmp_path, schemas)
    review = bundle.prepared(*paths, clock_source=lambda: AT)[0]
    dest = tmp_path / "config"
    result = bundle.create(
        dest, *paths, expected_review=review["review_sha256"], clock_source=lambda: AT
    )
    assert result["status"] == "HOST_BUNDLE_CREATED"
    assert bundle.verify(dest, clock_source=lambda: AT)["review_sha256"] == review["review_sha256"]
    before = digest(tmp_path)
    with pytest.raises(FileExistsError):
        bundle.create(
            dest, *paths, expected_review=review["review_sha256"], clock_source=lambda: AT
        )
    assert digest(tmp_path) == before


@pytest.mark.parametrize(
    "changed", ["runtime.json", "policy.json", "schemas.json", "manifest.json"]
)
def test_changed_packaged_file_is_rejected(tmp_path, schemas, changed):
    paths, _, _ = inputs(tmp_path, schemas)
    review = bundle.prepared(*paths, clock_source=lambda: AT)[0]
    dest = tmp_path / "config"
    bundle.create(dest, *paths, expected_review=review["review_sha256"], clock_source=lambda: AT)
    value = json.loads((dest / changed).read_text())
    if changed == "runtime.json":
        value["execution"]["capital"] = "1001"
    elif changed == "policy.json":
        value["poll_seconds"] = 11
    elif changed == "schemas.json":
        value["captured_at"] = "2026-10-10T20:00:44Z"
    else:
        value["binding"]["secret_files"]["extra"] = "/never"
    (dest / changed).write_text(json.dumps(value))
    with pytest.raises(ValueError):
        bundle.verify(dest, clock_source=lambda: AT)


def test_stale_review_never_creates_bundle(tmp_path, schemas):
    paths, _, _ = inputs(tmp_path, schemas)
    dest = tmp_path / "config"
    with pytest.raises(ValueError, match="review changed"):
        bundle.create(dest, *paths, expected_review="0" * 64, clock_source=lambda: AT)
    assert not dest.exists()


def test_operator_secret_is_referenced_not_opened_or_copied(tmp_path, schemas):
    paths, settings, _ = inputs(tmp_path, schemas)
    value = settings.model_dump(mode="json")
    value["runtime"]["operator_key_file"] = "/host/existing-private-operator-key"
    paths[0].write_text(json.dumps(value))
    report, packaged, _, _ = bundle.prepared(*paths, clock_source=lambda: AT)
    assert packaged.runtime.operator_key_file == "/run/secrets/operator"
    assert report["binding"]["secret_files"] == {"operator": "/host/existing-private-operator-key"}
    assert not report["credentials_opened"]


def test_manifest_cannot_misrepresent_capital_or_families(tmp_path, schemas):
    paths, _, _ = inputs(tmp_path, schemas)
    review = bundle.prepared(*paths, clock_source=lambda: AT)[0]
    dest = tmp_path / "config"
    bundle.create(dest, *paths, expected_review=review["review_sha256"], clock_source=lambda: AT)
    manifest = json.loads((dest / "manifest.json").read_text())
    for field, value in (
        ("initial_virtual_capital", "1"),
        ("families", ["DEGEN", "SWING", "SCOPE"]),
        ("maximum_plays", 1),
    ):
        (dest / "manifest.json").write_text(json.dumps(manifest | {field: value}))
        with pytest.raises(ValueError, match="review facts"):
            bundle.verify(dest, clock_source=lambda: AT)
