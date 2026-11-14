"""Bounded online backup for disposable dashboard and report copies. Standard library only."""

import sqlite3
import time

# A continuously rewritten source can restart an incremental SQLite backup at
# page one. Only a restarted copy may briefly hold one consistent source view.
PINNED_COPY_SECONDS = 0.5


class _CopyRestarted(Exception):
    pass


def private_backup(source, target, *, deadline, max_bytes, capacity_error, deadline_error):
    """Release the native read lock between batches on the ordinary path."""
    def check(limit):
        if time.monotonic() >= limit:
            raise TimeoutError(deadline_error)

    def scalar(statement, limit):
        while True:
            check(limit)
            try:
                return source.execute(statement).fetchone()[0]
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise
                time.sleep(max(0, min(.01, limit - time.monotonic())))

    def copy(limit, *, allow_restart):
        page_size = scalar("PRAGMA page_size", limit)
        previous = None

        def progress(status, remaining, total):
            nonlocal previous
            if total * page_size > max_bytes:
                raise ValueError(capacity_error)
            check(limit)
            if status == sqlite3.SQLITE_OK:
                if allow_restart and previous is not None and remaining >= previous:
                    raise _CopyRestarted
                previous = remaining

        count = scalar("PRAGMA page_count", limit)
        progress(None, count, count)
        source.backup(target, pages=64, progress=progress, sleep=.01)

    # This intermediate file is private and is never resumed after a crash.
    # The dashboard's final publication performs its own commit and fsync.
    target.execute("PRAGMA synchronous=OFF")
    try:
        copy(deadline, allow_restart=True)
    except _CopyRestarted:
        limit = min(deadline, time.monotonic() + PINNED_COPY_SECONDS)
        source.execute("BEGIN")
        try:
            copy(limit, allow_restart=False)
        finally:
            source.rollback()
