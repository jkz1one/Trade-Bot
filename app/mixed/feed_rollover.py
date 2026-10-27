"""Append-only future-session feed catalogs and carry intent. No worker startup."""

import argparse
import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import Field

from app.domain.models import utc_now
from app.mixed.continuous_feed import FeedPolicy, planned
from app.options.engine import clock, fingerprint
from app.options.models import OptionRecord
from app.options.operator_inbox import read
from app.options.venue import private_path
from app.robinhood.schedule import XNYSCalendar

PROTOCOL = "session-feed-rollover-v1"
MAX_ROLLOVERS = 256
DIGEST = r"^[a-f0-9]{64}$"


class FeedRollover(OptionRecord):
    version: Literal["session-feed-rollover-v1"] = PROTOCOL
    sequence: int = Field(strict=True, ge=1, le=MAX_ROLLOVERS)
    target_session: date
    created_at: datetime
    base_sha256: str = Field(pattern=DIGEST)
    previous_sha256: str = Field(pattern=DIGEST)
    owner_configuration_sha256: str = Field(pattern=DIGEST)
    owner_revision: int = Field(strict=True, ge=0)
    review_sha256: str = Field(pattern=DIGEST)
    policy: FeedPolicy


def base_hash(policy, schemas):
    return fingerprint({"policy": policy, "schemas": schemas})


def configuration_hash(policy, schemas, *, rolled):
    value = {"policy": policy, "schemas": schemas}
    if rolled:
        value["rollover_protocol"] = PROTOCOL
    return fingerprint(value)


def validate_policy(base, proposed, target, created_at):
    immutable = {"candidates", "carry_intents"}
    if base.model_dump(exclude=immutable) != proposed.model_dump(exclude=immutable):
        raise ValueError("Rollover cannot change frozen transport, universe or history settings")
    now = clock(created_at)
    if not 0 < (target - now.astimezone(ZoneInfo("America/New_York")).date()).days <= 60:
        raise ValueError("Rollover requires a future session within sixty days")
    cal = XNYSCalendar().calendar
    if not cal.is_session(target.isoformat()):
        raise ValueError("Exact exchange session required")
    if len(proposed.carry_intents) > 1 or any(
        i.target_session != target for i in proposed.carry_intents
    ):
        raise ValueError("Only the exact target session carry intent may be supplied")
    opened = cal.session_open(target.isoformat()).to_pydatetime()
    for i in proposed.candidates:
        if (
            not i.metadata_complete
            or not i.option_tradable
            or i.provider != "robinhood"
            or i.contract.underlying not in {s.symbol for s in base.stocks}
            or i.contract.last_trading_at <= opened
        ):
            raise ValueError("Explicit reviewed unexpired target-session contracts required")
    return opened


def identities(policies, held=()):
    by_id, by_contract = {}, {}
    for i in (
        *[i for p in policies for i in p.candidates],
        *[i for i in held if hasattr(i, "contract")],
    ):
        if (i.instrument_id in by_id and by_id[i.instrument_id] != i.contract) or (
            i.contract.contract_id in by_contract
            and by_contract[i.contract.contract_id] != i.instrument_id
        ):
            raise ValueError("Retained contract identity cannot be replaced or aliased")
        by_id[i.instrument_id] = i.contract
        by_contract[i.contract.contract_id] = i.instrument_id
    for p in policies:
        if len({i.instrument_id for i in p.candidates}) != len(p.candidates):
            raise ValueError("Unique candidate identities required")


def load_rollovers(db, base, schemas):
    """Verify the whole bounded chain and its committed head before using any row."""
    tables = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('feed_rollovers','feed_rollover_control')"
        )
    }
    if tables and len(tables) != 2:
        raise ValueError("Incomplete rollover enrollment")
    expected = configuration_hash(base, schemas, rolled=bool(tables))
    frozen = db.execute("SELECT configuration FROM control WHERE id=1").fetchone()
    if frozen is None or frozen[0] != expected:
        raise ValueError("Frozen feed configuration changed")
    if not tables:
        return ()
    head = db.execute(
        "SELECT generation,head_hash FROM feed_rollover_control WHERE id=1"
    ).fetchone()
    rows = db.execute(
        "SELECT sequence,target_session,payload_json,payload_hash FROM feed_rollovers ORDER BY sequence LIMIT ?",
        (MAX_ROLLOVERS + 1,),
    ).fetchall()
    if head is None or not 0 < len(rows) <= MAX_ROLLOVERS or head[0] != len(rows):
        raise ValueError("Rollover head or capacity mismatch")
    result, targets = [], set()
    previous = base_hash(base, schemas)
    for seq, row in enumerate(rows, 1):
        if len(row[2].encode()) > 256 * 1024:
            raise ValueError("Bounded rollover receipt required")
        value = FeedRollover.model_validate_json(row[2])
        if (
            row[0] != seq
            or value.sequence != seq
            or row[1] != value.target_session.isoformat()
            or value.target_session in targets
            or value.base_sha256 != base_hash(base, schemas)
            or value.previous_sha256 != previous
            or fingerprint(value) != row[3]
            or (result and value.created_at < result[-1].created_at)
        ):
            raise ValueError("Rollover chain changed")
        validate_policy(base, value.policy, value.target_session, value.created_at)
        targets.add(value.target_session)
        result.append(value)
        previous = row[3]
    if head[1] != previous:
        raise ValueError("Rollover head changed")
    identities((base, *(r.policy for r in result)))
    return tuple(result)


def policy_for(base, rows, target):
    return next((r.policy for r in rows if r.target_session == target), base)


def verify_owner(rows, owner_hash):
    if any(r.owner_configuration_sha256 != owner_hash for r in rows):
        raise ValueError("Rollover belongs to another native owner")


def collector_state(db, rows):
    last = db.execute(
        "SELECT sequence,status,request_hash FROM attempts ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    return {
        "generation": len(rows),
        "head": fingerprint(rows[-1]) if rows else None,
        "last_attempt": list(last) if last else None,
    }


def review(
    directory,
    feed_directory,
    policy_file,
    schemas_file,
    next_policy_file,
    target,
    *,
    clock_source=utc_now,
):
    from app.mixed.connected_check import connection_report
    from app.mixed.connected_runtime import check
    from app.mixed.continuous_feed import held_from_observer
    from app.mixed.swing_binding import policy_from_settings
    from app.options.observer import OptionObserver

    paths = tuple(
        Path(p) for p in (directory, feed_directory, policy_file, schemas_file, next_policy_file)
    )
    if any(not p.is_absolute() or p.resolve() != p for p in paths):
        raise ValueError("Canonical absolute rollover paths required")
    directory, feed_directory, policy_file, schemas_file, next_policy_file = paths
    now = clock(clock_source())
    result, settings, base, schemas, observer = check(
        directory, feed_directory, policy_file, schemas_file, clock_source=lambda: now
    )
    state = result["owner_state"]
    if state["runtime_status"] not in {"ENROLLED", "STOPPED", "FAILED"}:
        raise ValueError("Stop the existing runtime before reviewing rollover")
    proposed = FeedPolicy.model_validate_json(read(next_policy_file, 256 * 1024))
    opened = validate_policy(base, proposed, target, now)
    report = connection_report(
        settings,
        proposed,
        schemas,
        journal=directory / "options.db",
        directory=feed_directory,
        now=now,
    )
    if report["wiring_errors"] or any(c["blockers"] for c in report["option_candidates"]):
        raise ValueError("Proposed catalog differs from native enrollment")
    held = held_from_observer(observer)
    planned(proposed, held, opened, None, cycle=False)
    if proposed.carry_intents:
        intent = proposed.carry_intents[0]
        binding = policy_from_settings(settings, proposed.candidates, intent)
        if intent.stock_exit_session:
            from app.mixed.carry import calendar_path

            calendar_path(binding.stock_carry, XNYSCalendar(), target, intent.stock_exit_session)
        if intent.option_exit_session:
            from app.options.swing_carry import calendar_path

            if not proposed.candidates:
                raise ValueError("Option carry requires explicit reviewed candidates")
            for i in proposed.candidates:
                calendar_path(
                    binding.option_policy.carry,
                    XNYSCalendar(),
                    target,
                    intent.option_exit_session,
                    i.contract,
                    binding.carry_expiry_guard_seconds,
                )
    with OptionObserver(feed_directory / "collector.db", base.population_id).read() as db:
        rows = load_rollovers(db, base, schemas)
        verify_owner(rows, state["owner_configuration_sha256"])
        if len(rows) >= MAX_ROLLOVERS or any(r.target_session == target for r in rows):
            raise ValueError("Session rollover already enrolled or capacity reached")
        if rows and now < rows[-1].created_at:
            raise ValueError("Rollover clock regressed")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("swing_history", "swing_source_bindings"):
            if (
                table in tables
                and db.execute(
                    f"SELECT 1 FROM {table} WHERE target_session=?", (target.isoformat(),)
                ).fetchone()
            ):
                raise ValueError("Original target-session preparation already exists")
        identities((base, *(r.policy for r in rows), proposed), held)
        feed_state = collector_state(db, rows)
    binding = {
        "version": PROTOCOL,
        "paths": [str(p) for p in paths],
        "target_session": target.isoformat(),
        "base_sha256": base_hash(base, schemas),
        "proposed_sha256": fingerprint(proposed),
        "owner_state": state,
        "collector_state": feed_state,
        "held_sha256": fingerprint(held),
    }
    report.update(
        status="ROLLOVER_REVIEWED_WITH_ENTRY_BLOCKERS",
        review_sha256=fingerprint(binding),
        binding=binding,
        state_modified=False,
        workers_started=False,
        automatic_resume=False,
    )
    return report, base, schemas, proposed


@contextmanager
def collector_lease(directory):
    path = private_path(Path(directory) / "collector.lock")
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def apply(
    directory,
    feed_directory,
    policy_file,
    schemas_file,
    next_policy_file,
    target,
    *,
    expected_review,
    clock_source=utc_now,
):
    from app.execution.runtime import runtime_lease

    args = directory, feed_directory, policy_file, schemas_file, next_policy_file, target
    result = review(*args, clock_source=clock_source)[0]
    if result["review_sha256"] != expected_review:
        raise ValueError("Rollover review changed")
    with runtime_lease(Path(directory) / "options.db"), collector_lease(feed_directory):
        result, base, schemas, proposed = review(*args, clock_source=clock_source)
        if result["review_sha256"] != expected_review:
            raise ValueError("Rollover review changed")
        state = result["binding"]["owner_state"]
        now = clock(clock_source())
        validate_policy(base, proposed, target, now)
        db = sqlite3.connect(
            "file:" + quote(str(Path(feed_directory) / "collector.db")) + "?mode=rw", uri=True
        )
        try:
            db.execute("BEGIN IMMEDIATE")
            rows = load_rollovers(db, base, schemas)
            if collector_state(db, rows) != result["binding"]["collector_state"]:
                raise ValueError("Collector changed during rollover")
            if rows and now < rows[-1].created_at:
                raise ValueError("Rollover clock regressed")
            record = FeedRollover(
                sequence=len(rows) + 1,
                target_session=target,
                created_at=now,
                base_sha256=base_hash(base, schemas),
                previous_sha256=fingerprint(rows[-1]) if rows else base_hash(base, schemas),
                owner_configuration_sha256=state["owner_configuration_sha256"],
                owner_revision=state["owner_revision"],
                review_sha256=expected_review,
                policy=proposed,
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS feed_rollovers(sequence INTEGER PRIMARY KEY,target_session TEXT UNIQUE NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS feed_rollover_control(id INTEGER PRIMARY KEY CHECK(id=1),generation INTEGER NOT NULL,head_hash TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO feed_rollovers VALUES(?,?,?,?)",
                (
                    record.sequence,
                    target.isoformat(),
                    record.model_dump_json(),
                    fingerprint(record),
                ),
            )
            db.execute(
                "INSERT INTO feed_rollover_control VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET generation=excluded.generation,head_hash=excluded.head_hash",
                (record.sequence, fingerprint(record)),
            )
            db.execute(
                "UPDATE control SET configuration=? WHERE id=1",
                (configuration_hash(base, schemas, rolled=True),),
            )
            db.commit()
        finally:
            db.close()
    result.update(
        status="SESSION_ROLLOVER_ENROLLED", state_modified=True, rollover_sha256=fingerprint(record)
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("review", "apply"))
    for name in (
        "directory",
        "feed-directory",
        "policy",
        "schemas",
        "next-policy",
        "target-session",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-review")
    args = parser.parse_args(argv)
    if (args.operation == "apply") != (args.expected_review is not None):
        parser.error("Only apply requires the exact --expected-review")
    try:
        paths = (
            args.directory,
            args.feed_directory,
            args.policy,
            args.schemas,
            args.next_policy,
            date.fromisoformat(args.target_session),
        )
        result = (
            review(*paths)[0]
            if args.operation == "review"
            else apply(*paths, expected_review=args.expected_review)
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "FEED_ROLLOVER_UNAVAILABLE",
                    "live_enabled": False,
                    "workers_started": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
