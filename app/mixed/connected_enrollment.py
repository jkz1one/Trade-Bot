"""Review and enroll the first collector for an existing native simulation owner.

No account creation, bankroll reset, fixture migration, reads or worker startup.
"""

import argparse
import json
import sqlite3
from pathlib import Path

from app.domain.models import utc_now
from app.execution.runtime import runtime_lease
from app.mixed.connected_check import connection_report
from app.mixed.connected_runtime import inspect_owner
from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
from app.options.engine import fingerprint
from app.options.operator_inbox import private_directory, read
from app.options.read_gateway import ReadSchemas
from app.options.runtime_cli import load


def review(directory, feed_directory, policy_file, schemas_file, *, clock_source=utc_now):
    paths = tuple(Path(p) for p in (directory, feed_directory, policy_file, schemas_file))
    if any(not p.is_absolute() or p.resolve() != p for p in paths):
        raise ValueError("Canonical absolute enrollment paths required")
    directory, feed_directory, policy_file, schemas_file = paths
    if directory.is_relative_to(feed_directory) or feed_directory.is_relative_to(directory):
        raise ValueError("Separate non-nested owner and collector directories required")
    private_directory(feed_directory.parent)
    if feed_directory.exists() or feed_directory.is_symlink():
        raise ValueError("Collector enrollment is create-only; preserve existing evidence")
    settings = load(directory / "runtime.json")
    policy = FeedPolicy.model_validate_json(read(policy_file, 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(schemas_file, 256 * 1024))
    result = connection_report(
        settings,
        policy,
        schemas,
        journal=directory / "options.db",
        directory=feed_directory,
        now=clock_source(),
    )
    if not result["collector_can_start"]:
        raise ValueError("Collector and runtime wiring differ")
    _, state = inspect_owner(directory, settings, clock_source=clock_source)
    if (
        state["runtime_status"] != "ENROLLED"
        or state["runtime_generation"] != 0
        or state["feed_sequence"] != 0
    ):
        raise ValueError(
            "First collector requires an unused enrolled runtime; restore existing feed"
        )
    binding = {
        "version": "connected-collector-enrollment-v1",
        "paths": [str(p) for p in paths],
        "runtime_settings_sha256": fingerprint(settings),
        "collector_configuration_sha256": fingerprint({"policy": policy, "schemas": schemas}),
        "owner_state": state,
    }
    result.update(
        version=binding["version"],
        status="REVIEWED_WITH_ENTRY_BLOCKERS",
        review_sha256=fingerprint(binding),
        binding=binding,
        state_modified=False,
        workers_started=False,
        collector_enrolled=False,
        dashboard_journal=str(directory / "options.db"),
        dashboard_population_id=settings.limits.population_id,
        automatic_resume=False,
    )
    return result, policy, schemas


def enroll(
    directory, feed_directory, policy_file, schemas_file, *, expected_review, clock_source=utc_now
):
    if (
        not isinstance(expected_review, str)
        or len(expected_review) != 64
        or any(c not in "0123456789abcdef" for c in expected_review)
    ):
        raise ValueError("Exact reviewed enrollment hash required")
    args = directory, feed_directory, policy_file, schemas_file
    # Fail malformed/missing/frozen configuration before even opening the lease.
    initial, _, _ = review(*args, clock_source=clock_source)
    if initial["review_sha256"] != expected_review:
        raise ValueError("Enrollment review changed")
    with runtime_lease(Path(directory) / "options.db"):
        result, policy, schemas = review(*args, clock_source=clock_source)
        if result["review_sha256"] != expected_review:
            raise ValueError("Enrollment review changed")
        feed = ContinuousFeed(feed_directory, policy, schemas, create=True)
        feed.close()
    # A failed creation leaves its directory for inspection. Never adopt, remove,
    # retry over or silently replace it, even if no successful report was emitted.
    result.update(status="COLLECTOR_ENROLLED", collector_enrolled=True, state_modified=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("review", "enroll"))
    for name in ("directory", "feed-directory", "policy", "schemas"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-review")
    args = parser.parse_args(argv)
    if (args.operation == "enroll") != (args.expected_review is not None):
        parser.error("Only enroll requires --expected-review from the read-only review")
    try:
        paths = args.directory, args.feed_directory, args.policy, args.schemas
        result = (
            review(*paths)[0]
            if args.operation == "review"
            else enroll(*paths, expected_review=args.expected_review)
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "CONNECTED_ENROLLMENT_UNAVAILABLE",
                    "workers_started": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
