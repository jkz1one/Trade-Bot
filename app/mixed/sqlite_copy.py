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

    def copy(limit, *, pinned=False, retry_while_advancing=False):
        page_size = scalar("PRAGMA page_size", limit)
        previous = None
        furthest_page = 0
        last_restart_page = -1

        def progress(status, remaining, total):
            nonlocal previous, furthest_page, last_restart_page
            if total * page_size > max_bytes:
                raise ValueError(capacity_error)
            check(limit)
            if status == sqlite3.SQLITE_OK and not pinned:
                if previous is not None and remaining >= previous:
                    if not retry_while_advancing or furthest_page <= last_restart_page:
                        raise _CopyRestarted
                    last_restart_page = furthest_page
                if retry_while_advancing:
                    furthest_page = max(furthest_page, total - remaining)
                previous = remaining

        count = scalar("PRAGMA page_count", limit)
        progress(None, count, count)
        source.backup(target, pages=64, progress=progress, sleep=.01)

    # This intermediate file is private and is never resumed after a crash.
    # The dashboard's final publication performs its own commit and fsync.
    target.execute("PRAGMA synchronous=OFF")
    try:
        copy(deadline)
    except _CopyRestarted:
        limit = min(deadline, time.monotonic() + PINNED_COPY_SECONDS)
        source.execute("BEGIN")
        try:
            copy(limit, pinned=True)
        except TimeoutError:
            if not limit <= time.monotonic() < deadline:
                raise
        else:
            return
        finally:
            source.rollback()
        # Let writers commit between batches while the copy reaches new pages.
        # Repeated rewinds at the same point stop without another pinned read.
        try:
            copy(deadline, retry_while_advancing=True)
        except _CopyRestarted:
            raise TimeoutError(deadline_error) from None
