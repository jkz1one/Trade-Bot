"""Create-only reviewed enrollment of one native virtual owner and its collector.

Configuration is supplied explicitly. No broker account, reads or worker starts.
"""

import argparse
import json
import sqlite3
from itertools import combinations
from pathlib import Path

from app.domain.models import utc_now
from app.execution.runtime import runtime_lease
from app.mixed.connected_check import connection_report
from app.mixed.connected_enrollment import enroll as enroll_collector
from app.mixed.connected_enrollment import review as review_collector
from app.mixed.continuous_feed import FeedPolicy
from app.options.engine import fingerprint
from app.options.operator_inbox import private_directory, read, save
from app.options.read_gateway import ReadSchemas
from app.options.runtime_cli import initialize, load


def review(
    directory, feed_directory, settings_file, policy_file, schemas_file, *, clock_source=utc_now
):
    paths = tuple(
        Path(p) for p in (directory, feed_directory, settings_file, policy_file, schemas_file)
    )
    if any(not p.is_absolute() or p.resolve() != p for p in paths):
        raise ValueError("Canonical absolute first-owner paths required")
    owner, feed, settings_path, policy_path, schemas_path = paths
    for dest in (owner, feed):
        private_directory(dest.parent)
        if dest.exists() or dest.is_symlink():
            raise ValueError("First enrollment is create-only; preserve existing state")
    if any(a.is_relative_to(b) or b.is_relative_to(a) for a, b in combinations((owner, feed), 2)):
        raise ValueError("Separate non-nested owner and collector directories required")
    settings = load(settings_path)
    policy = FeedPolicy.model_validate_json(read(policy_path, 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(schemas_path, 256 * 1024))
    if settings.limits.population_id.startswith("ui-review-"):
        raise ValueError("Dedicated native population required, not the frozen review identity")
    result = connection_report(
        settings, policy, schemas, journal=owner / "options.db", directory=feed, now=clock_source()
    )
    if not result["collector_can_start"]:
        raise ValueError("Native owner and collector configuration differ")
    if settings.execution.mixed_owner.portfolio.max_plays == 0:
        raise ValueError("Native first strategy enrollment requires positive capacity")
    binding = {
        "version": "connected-first-owner-v1",
        "paths": [str(p) for p in paths],
        "runtime_settings_sha256": fingerprint(settings),
        "collector_configuration_sha256": fingerprint({"policy": policy, "schemas": schemas}),
    }
    result.update(
        version=binding["version"],
        status="REVIEWED_WITH_ENTRY_BLOCKERS",
        binding=binding,
        review_sha256=fingerprint(binding),
        initial_virtual_capital=str(settings.execution.capital),
        maximum_plays=settings.execution.mixed_owner.portfolio.max_plays,
        model_configured=settings.key_file is not None,
        operator_configured=settings.runtime.operator_key_file is not None,
        credentials_opened=False,
        state_modified=False,
        workers_started=False,
        owner_enrolled=False,
        collector_enrolled=False,
        automatic_resume=False,
    )
    return result, settings


def enroll(
    directory,
    feed_directory,
    settings_file,
    policy_file,
    schemas_file,
    *,
    expected_review,
    clock_source=utc_now,
):
    if (
        not isinstance(expected_review, str)
        or len(expected_review) != 64
        or any(c not in "0123456789abcdef" for c in expected_review)
    ):
        raise ValueError("Exact first-owner review hash required")
    args = directory, feed_directory, settings_file, policy_file, schemas_file
    report, _ = review(*args, clock_source=clock_source)
    if report["review_sha256"] != expected_review:
        raise ValueError("First-owner review changed")
    # The stable parent lease serializes creation before the native journal exists.
    # Existing native owner/collector enrollment keep their own leases as well.
    with runtime_lease(Path(directory).parent / "connected-first-owner"):
        report, settings = review(*args, clock_source=clock_source)
        if report["review_sha256"] != expected_review:
            raise ValueError("First-owner review changed under lease")
        initialize(directory, settings, clock=clock_source)
        # Re-read the supplied collector inputs and bind them to the original review
        # before delegating to guarded native collector enrollment.
        collector_args = directory, feed_directory, policy_file, schemas_file
        collector_review, policy, schemas = review_collector(
            *collector_args, clock_source=clock_source
        )
        if (
            fingerprint({"policy": policy, "schemas": schemas})
            != report["binding"]["collector_configuration_sha256"]
        ):
            raise ValueError("Collector inputs changed after owner creation; preserve evidence")
        enrolled = enroll_collector(
            *collector_args,
            expected_review=collector_review["review_sha256"],
            clock_source=clock_source,
        )
        receipt = {
            "version": "connected-first-owner-receipt-v1",
            "review_sha256": expected_review,
            "binding": report["binding"],
            "collector_review_sha256": collector_review["review_sha256"],
            "owner_configuration_sha256": enrolled["binding"]["owner_state"][
                "owner_configuration_sha256"
            ],
            "population_id": settings.limits.population_id,
            "created_at": clock_source().isoformat(),
        }
        save(Path(directory) / "connected-enrollment.json", receipt)
    report.update(
        status="OWNER_AND_COLLECTOR_ENROLLED",
        state_modified=True,
        owner_enrolled=True,
        collector_enrolled=True,
        credentials_opened=bool(settings.key_file or settings.runtime.operator_key_file),
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("review", "enroll"))
    for name in ("directory", "feed-directory", "settings", "policy", "schemas"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-review")
    args = parser.parse_args(argv)
    if (args.operation == "enroll") != (args.expected_review is not None):
        parser.error("Only enroll requires the exact --expected-review")
    try:
        paths = args.directory, args.feed_directory, args.settings, args.policy, args.schemas
        report = (
            review(*paths)[0]
            if args.operation == "review"
            else enroll(*paths, expected_review=args.expected_review)
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "FIRST_OWNER_ENROLLMENT_UNAVAILABLE",
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
