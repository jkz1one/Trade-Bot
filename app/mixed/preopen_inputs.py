"""One bounded pre-open collection and source binding, with a read-only owner."""
import argparse
import asyncio
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from app.domain.models import utc_now
from app.mixed.connected_runtime import check
from app.mixed.continuous_feed import ContinuousFeed, held_from_observer
from app.mixed.swing_feed import planned_history, target_session
from app.options.engine import fingerprint
from app.options.read_capture import collect
from app.options.venue import private_path
from app.robinhood.schedule import XNYSCalendar


@contextmanager
def stopped_owner(directory):
    # flock on the existing inode also excludes the native writable owner. No
    # creation, journal opening, migration, reconciliation or halt amendment.
    path = Path(directory) / "options.db.runtime.lock"
    private_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


async def prepare(directory, feed_directory, policy_file, schemas_file, target,
                  *, clock_source=utc_now, reader=collect):
    now = clock_source()
    if target_session(now, XNYSCalendar()) != target:
        raise ValueError("PREOPEN_TARGET_WINDOW_REQUIRED")
    with stopped_owner(directory):
        report, settings, policy, schemas, observer = check(
            directory, feed_directory, policy_file, schemas_file, clock_source=clock_source)
        if report["owner_state"]["runtime_status"] not in ("ENROLLED", "STOPPED", "FAILED"):
            raise ValueError("STOPPED_OWNER_REQUIRED")
        if held_from_observer(observer):
            raise ValueError("FLAT_OWNER_REQUIRED")
        feed = ContinuousFeed(feed_directory, policy, schemas)
        try:
            effective = feed.policy_for(target)
            if effective.swing_history is None:
                raise ValueError("SWING_HISTORY_NOT_ENROLLED")
            selected, calls = planned_history(effective.swing_history,
                                             tuple(i.symbol for i in policy.stocks), now)
            if selected != target or not calls:
                raise ValueError("COMPLETED_DAILY_DATE_REQUIRED")
            # A repeat verifies the original binding without refreshing its time
            # or spending another provider call.
            captured = {"status": "RETAINED_HISTORY"}
            if feed.swing_snapshot(target) is None:
                captured = await feed.tick(now=now, reader=reader, source_settings=settings)
            bound = feed.bind_swing_sources(settings, now=clock_source())
            if bound is None or bound["target_session"] != target.isoformat():
                raise ValueError("PREOPEN_BINDING_UNAVAILABLE")
            ready = bound["status"] == "PREPARED"
            return {
                "version": "connected-preopen-inputs-v1",
                "status": "PREOPEN_INPUTS_PREPARED" if ready else "PREOPEN_INPUTS_BLOCKED",
                "target_session": target.isoformat(), "collection": captured,
                "swing_binding": bound, "policy_sha256": fingerprint(effective),
                "owner_state": report["owner_state"], "owner_modified": False,
                "model_calls": 0, "orders_submitted": 0, "workers_started": False,
                "live_enabled": False, "trading_ready": False,
            }
        finally:
            feed.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("directory", "feed-directory", "policy", "schemas"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--target-session", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(prepare(args.directory, args.feed_directory, args.policy,
                                     args.schemas, args.target_session))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PREOPEN_INPUTS_PREPARED" else 2
    except (OSError, ValueError, RuntimeError) as exc:
        # Never expose provider exception messages or credentials.
        allowed = {"PREOPEN_TARGET_WINDOW_REQUIRED", "STOPPED_OWNER_REQUIRED", "FLAT_OWNER_REQUIRED",
                   "SWING_HISTORY_NOT_ENROLLED", "COMPLETED_DAILY_DATE_REQUIRED", "PREOPEN_BINDING_UNAVAILABLE"}
        reason = str(exc) if str(exc) in allowed else "PREOPEN_INPUTS_UNAVAILABLE"
        print(json.dumps({"status": "UNAVAILABLE", "reason": reason,
                          "error_class": type(exc).__name__, "live_enabled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
