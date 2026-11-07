"""Reviewed Scope pacing under the existing sliding read quota.

Twenty-second start spacing leaves one six-read refresh after three ordinary
captures per minute. It does not reserve or grant quota: every read is charged,
including failures, held overflow and post-cost reads, across restart.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.mixed.scope_refresh import paced


def spacing(feed, now):
    binding = feed.policy_for(now.astimezone(ZoneInfo('America/New_York')).date()).scope_binding
    if paced(binding) and binding.session.opens_at <= now < binding.session.closes_at:
        return max(20, feed.policy.poll_seconds)
    return feed.policy.poll_seconds


def budget(feed, now, calls):
    rows = feed.db.execute('SELECT started_at,calls FROM attempts WHERE started_at>? ORDER BY started_at',
                          ((now - timedelta(minutes=1)).isoformat(),)).fetchall()
    used = sum(row['calls'] for row in rows)
    if used + calls <= feed.policy.calls_per_minute:
        return True, now
    if calls > feed.policy.calls_per_minute:
        return False, now + timedelta(minutes=1)
    for row in rows:
        used -= row['calls']
        if used + calls <= feed.policy.calls_per_minute:
            return False, datetime.fromisoformat(row['started_at']) + timedelta(minutes=1)
    return False, now + timedelta(minutes=1)


def wait_seconds(feed, now):
    interval = spacing(feed, now)
    row = feed.db.execute('SELECT started_at,calls FROM attempts ORDER BY sequence DESC LIMIT 1').fetchone()
    if row is None:
        return interval
    due = datetime.fromisoformat(row['started_at']) + timedelta(seconds=interval)
    _, quota_at = budget(feed, now, row['calls'])
    # The prior call count can underestimate a new held-book batch. Bound that
    # retry to one second instead of busy-polling until more quota expires.
    # Re-evaluate holdings/window at least once per interval. Wakeups for paid
    # requests and stop remain immediate, even while ordinary polling is paced.
    return min(interval, max(1, (max(due, quota_at) - now).total_seconds()))
