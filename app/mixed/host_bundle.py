"""Review and freeze supplied native configuration at fixed host container paths."""

import argparse
import json
from pathlib import Path

from app.domain.models import utc_now
from app.mixed.connected_check import connection_report
from app.mixed.continuous_feed import FeedPolicy
from app.options.engine import fingerprint
from app.options.operator_inbox import private_directory, read, save, sync_directory
from app.options.read_gateway import ReadSchemas
from app.options.runtime_cli import load
from app.options.runtime_models import RuntimeSettings

STATE = Path("/state")


def prepared(settings_file, policy_file, schemas_file, *, clock_source=utc_now):
    original = load(settings_file)
    original_policy = FeedPolicy.model_validate_json(read(policy_file, 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(schemas_file, 256 * 1024))
    value = original.model_dump(mode="json")
    value["runtime"]["feed_file"] = str(STATE / "collector/feed.json")
    secrets = {}
    if original.key_file:
        secrets["model"] = original.key_file
        value["key_file"] = "/run/secrets/model"
    if original.runtime.operator_key_file:
        secrets["operator"] = original.runtime.operator_key_file
        value["runtime"]["operator_key_file"] = "/run/secrets/operator"
    for path in secrets.values():
        p = Path(path)
        if not p.is_absolute() or "," in path or "\n" in path or "\x00" in path:
            raise ValueError("Absolute existing secret file paths required")
    settings = RuntimeSettings.model_validate(value)
    policy = FeedPolicy.model_validate(
        original_policy.model_dump()
        | {
            "capture": original_policy.capture.model_dump()
            | {"oauth_file": "/auth/robinhood-oauth.json"}
        }
    )
    report = connection_report(
        settings,
        policy,
        schemas,
        journal=STATE / "owner/options.db",
        directory=STATE / "collector",
        now=clock_source(),
    )
    if not report["collector_can_start"] or settings.execution.mixed_owner.portfolio.max_plays == 0:
        raise ValueError("Valid native first-owner wiring and positive initial capacity required")
    if settings.limits.population_id.startswith("ui-review-"):
        raise ValueError("Frozen review identity cannot be deployed")
    binding = {
        "version": "connected-host-bundle-v1",
        "original_settings_sha256": fingerprint(original),
        "original_policy_sha256": fingerprint(original_policy),
        "settings_sha256": fingerprint(settings),
        "policy_sha256": fingerprint(policy),
        "schemas_sha256": fingerprint(schemas),
        "secret_files": secrets,
    }
    return (
        report
        | {
            "binding": binding,
            "review_sha256": fingerprint(binding),
            "initial_virtual_capital": str(settings.execution.capital),
            "maximum_plays": settings.execution.mixed_owner.portfolio.max_plays,
            "families": list(settings.stock_policy.family_priority),
            "workers_started": False,
            "credentials_opened": False,
        },
        settings,
        policy,
        schemas,
    )


def create(
    directory, settings_file, policy_file, schemas_file, *, expected_review, clock_source=utc_now
):
    directory = Path(directory)
    if not directory.is_absolute() or directory.resolve() != directory:
        raise ValueError("Canonical new bundle directory required")
    private_directory(directory.parent)
    result, settings, policy, schemas = prepared(
        settings_file, policy_file, schemas_file, clock_source=clock_source
    )
    if result["review_sha256"] != expected_review:
        raise ValueError("Bundle review changed")
    directory.mkdir(mode=0o700)
    for name, value in (
        ("runtime.json", settings),
        ("policy.json", policy),
        ("schemas.json", schemas),
    ):
        save(directory / name, value.model_dump(mode="json"))
    save(directory / "manifest.json", result)
    sync_directory(directory)
    sync_directory(directory.parent)
    return result | {"status": "HOST_BUNDLE_CREATED"}


def verify(directory, *, clock_source=utc_now):
    directory = Path(directory)
    private_directory(directory)
    manifest = json.loads(read(directory / "manifest.json"))
    settings = load(directory / "runtime.json")
    policy = FeedPolicy.model_validate_json(read(directory / "policy.json", 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(directory / "schemas.json", 256 * 1024))
    binding = manifest["binding"]
    if (
        binding["version"] != "connected-host-bundle-v1"
        or fingerprint(binding) != manifest["review_sha256"]
    ):
        raise ValueError("Bundle manifest changed")
    if any(
        fingerprint(v) != binding[k + "_sha256"]
        for k, v in (("settings", settings), ("policy", policy), ("schemas", schemas))
    ):
        raise ValueError("Frozen host configuration changed")
    if (
        settings.runtime.feed_file != str(STATE / "collector/feed.json")
        or policy.capture.oauth_file != "/auth/robinhood-oauth.json"
    ):
        raise ValueError("Host path binding changed")
    expected = {}
    for role, path in (
        ("model", settings.key_file),
        ("operator", settings.runtime.operator_key_file),
    ):
        if path:
            if path != "/run/secrets/" + role:
                raise ValueError("Host key binding changed")
            expected[role] = binding["secret_files"][role]
    if expected != binding["secret_files"]:
        raise ValueError("Unexpected host secret mount")
    report = connection_report(
        settings,
        policy,
        schemas,
        journal=STATE / "owner/options.db",
        directory=STATE / "collector",
        now=clock_source(),
    )
    if not report["collector_can_start"]:
        raise ValueError("Host configuration no longer validates")
    facts = {
        "population_id": settings.limits.population_id,
        "initial_virtual_capital": str(settings.execution.capital),
        "maximum_plays": settings.execution.mixed_owner.portfolio.max_plays,
        "families": list(settings.stock_policy.family_priority),
        "workers_started": False,
        "credentials_opened": False,
        "live_enabled": False,
        "trading_ready": False,
    }
    if any(manifest.get(key) != value for key, value in facts.items()):
        raise ValueError("Bundle review facts differ from native configuration")
    return manifest | {
        "status": "HOST_BUNDLE_VERIFIED",
        "entry_blockers": report["entry_blockers"],
        "option_candidates": report["option_candidates"],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("review", "create", "verify"))
    for name in ("directory", "settings", "policy", "schemas", "expected-review"):
        p.add_argument("--" + name)
    a = p.parse_args(argv)
    if a.operation == "verify":
        if not a.directory or any((a.settings, a.policy, a.schemas, a.expected_review)):
            p.error("Verify requires only --directory")
    elif not all((a.settings, a.policy, a.schemas)) or (a.operation == "create") != bool(
        a.directory and a.expected_review
    ):
        p.error("Review requires inputs; create also requires directory and exact review")
    try:
        if a.operation == "verify":
            result = verify(a.directory)
        elif a.operation == "review":
            result = prepared(a.settings, a.policy, a.schemas)[0]
        else:
            result = create(
                a.directory, a.settings, a.policy, a.schemas, expected_review=a.expected_review
            )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "HOST_BUNDLE_UNAVAILABLE",
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
