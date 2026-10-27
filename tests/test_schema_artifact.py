"""Actual discovery-envelope shape is accepted without weakening schema pins."""

import json

import pytest
from test_host_bundle import inputs
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed import host_bundle, simulation_profile
from app.options.read_gateway import schema_digest
from app.options.schema_artifact import load_reviewed_schemas


def artifact(schemas):
    return {
        "capture_id": "a" * 32,
        "operation": "discover",
        "status": "COMPLETE",
        "execution_authority": False,
        "normalized_data_verified": False,
        "result": {
            "request_id": "b" * 32,
            "policy_sha256": "c" * 64,
            "operation": "DISCOVER",
            "started_at": schemas.captured_at.isoformat(),
            "collected_at": schemas.captured_at.isoformat(),
            "elapsed_seconds": 0.0,
            "status": "COMPLETE",
            "execution_authority": False,
            "normalized_data_verified": False,
            "schemas": schemas.model_dump(mode="json"),
            "plan": None,
            "observations": [],
            "error_class": None,
        },
    }


def write(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def test_both_host_consumers_accept_discovery_and_preserve_same_review(tmp_path, schemas, capsys):
    paths, _, _ = inputs(tmp_path, schemas)
    plain = host_bundle.prepared(*paths)[0]
    before = paths[2].read_bytes()
    assert load_reviewed_schemas(paths[2]) == schemas
    assert paths[2].read_bytes() == before
    write(paths[2], artifact(schemas))
    before = paths[2].read_bytes()
    assert load_reviewed_schemas(paths[2]) == schemas
    wrapped = host_bundle.prepared(*paths)[0]
    assert wrapped == plain
    assert simulation_profile.main(["review", "--schemas", str(paths[2])]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == simulation_profile.review(schemas)
    destination = tmp_path / "bundle"
    host_bundle.create(destination, *paths, expected_review=wrapped["review_sha256"])
    assert json.loads((destination / "schemas.json").read_text()) == schemas.model_dump(mode="json")
    assert host_bundle.verify(destination)["status"] == "HOST_BUNDLE_VERIFIED"
    assert paths[2].read_bytes() == before


@pytest.mark.parametrize(
    "damage",
    [
        "outer_failed",
        "inner_failed",
        "operation",
        "extra",
        "missing",
        "no_schema",
        "bad_digest",
        "unreviewed",
        "authority",
    ],
)
def test_reject_bad_or_unreviewed_discovery(tmp_path, schemas, damage):
    value = artifact(schemas)
    if damage == "outer_failed":
        value["status"] = "FAILED"
    elif damage == "inner_failed":
        value["result"].update(status="FAILED", error_class="ValueError")
    elif damage == "operation":
        value["operation"] = "capture"
    elif damage == "extra":
        value["unrecognized"] = True
    elif damage == "missing":
        del value["status"]
    elif damage == "no_schema":
        value["result"]["schemas"] = None
    elif damage == "authority":
        value["execution_authority"] = True
    else:
        s = value["result"]["schemas"]
        s["sha256"] = "0" * 64
        if damage == "unreviewed":
            next(iter(s["tools"].values()))["description"] = "changed wire metadata"
            s["sha256"] = schema_digest(s["tools"])
    path = write(tmp_path / "discovery.json", value)
    with pytest.raises(ValueError):
        load_reviewed_schemas(path)


def test_duplicate_keys_and_public_file_rejected(tmp_path, schemas):
    path = write(tmp_path / "schemas.json", schemas.model_dump(mode="json"))
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_reviewed_schemas(path)
    path.chmod(0o600)
    path.write_text('{"result":null,"result":null}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_reviewed_schemas(path)
