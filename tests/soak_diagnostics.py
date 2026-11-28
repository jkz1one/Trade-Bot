"""Bounded read-only evidence for a disposable fixture's original entry deadline."""

import json
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from soak_memory import cgroup_memory


def counters(path, allowed):
    result = {}
    for line in path.read_text().splitlines():
        key, raw = line.split()
        if key in allowed:
            value = int(raw)
            if value < 0:
                raise ValueError('Negative counter')
            result[key] = value
    if not result:
        raise ValueError('Missing counters')
    return result


def resources(directory=Path('/sys/fs/cgroup')):
    """Counters are cumulative for the mounted cgroup, not per-phase attribution."""
    result = {'monotonic_seconds': time.monotonic(), 'observed_at': datetime.now(UTC).isoformat(),
              'scope': 'mounted cgroup v2; includes worker children',
              'memory': cgroup_memory(directory)}
    try:
        quota, period = (directory / 'cpu.max').read_text().split()
        quota, period = None if quota == 'max' else int(quota), int(period)
        if period <= 0 or (quota is not None and quota <= 0):
            raise ValueError('Invalid CPU quota')
        result['cpu'] = {'status': 'OBSERVED', 'quota_usec': quota, 'period_usec': period,
                         'counters': counters(directory / 'cpu.stat', {
                             'usage_usec', 'user_usec', 'system_usec', 'nr_periods',
                             'nr_throttled', 'throttled_usec'})}
    except (OSError, ValueError):
        result['cpu'] = {'status': 'UNAVAILABLE'}
    try:
        devices = {}
        for line in (directory / 'io.stat').read_text().splitlines():
            device, *fields = line.split()
            values = dict(field.split('=') for field in fields)
            values = {k: int(v) for k, v in values.items()
                      if k in {'rbytes', 'wbytes', 'rios', 'wios', 'dbytes', 'dios'}}
            if any(v < 0 for v in values.values()) or len(devices) >= 128:
                raise ValueError('Invalid I/O counters')
            devices[device] = values
        result['io'] = {'status': 'OBSERVED', 'devices': devices}
    except (OSError, ValueError):
        result['io'] = {'status': 'UNAVAILABLE'}
    return result


def resource_window(start, end):
    def delta(a, b):
        if set(a) != set(b) or any(b[k] < v for k, v in a.items()):
            return {'status': 'UNAVAILABLE', 'reason': 'COUNTER_SET_CHANGED_OR_RESET'}
        return {'status': 'OBSERVED', 'counters': {k: b[k] - v for k, v in a.items()}}

    cpu = {'status': 'UNAVAILABLE'}
    if (start['cpu'].get('status') == end['cpu'].get('status') == 'OBSERVED'
            and all(start['cpu'][k] == end['cpu'][k] for k in ('quota_usec', 'period_usec'))):
        cpu = delta(start['cpu']['counters'], end['cpu']['counters'])
    io = {'status': 'UNAVAILABLE'}
    if start['io'].get('status') == end['io'].get('status') == 'OBSERVED':
        a, b = start['io']['devices'], end['io']['devices']
        # A newly appearing device is not a proven zero baseline.
        if a.keys() == b.keys():
            io = {'status': 'OBSERVED', 'devices': {k: delta(a[k], b[k]) for k in a}}
    return {'scope': 'worker start to diagnostic read; not isolated entry-phase CPU or I/O',
            'elapsed_seconds': end['monotonic_seconds'] - start['monotonic_seconds'],
            'cpu': cpu, 'io': io, 'start': start, 'end': end}


def entry_diagnostic(path, cycle_key, profile=None):
    """Read saved clocks for this exact fixture decision, including rejected entries."""
    if cycle_key is None:
        return {'status': 'PENDING', 'reason': 'FIXTURE_ENTRY_NOT_REQUESTED'}
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            row = db.execute(
                'SELECT started_at,status,result_json FROM execution_option_opportunities '
                'WHERE cycle_key=?', (cycle_key,)).fetchone()
            if row is None:
                return {'status': 'PENDING', 'reason': 'FIXTURE_DECISION_NOT_SAVED'}
            evidence = json.loads(row[2])
            packet = evidence.get('entry_request', {}).get('packet')
            if not packet:
                return {'status': 'PENDING', 'reason': 'FIXTURE_REQUEST_NOT_SAVED'}
            if packet['cycle_key'] != cycle_key:
                raise ValueError('Cycle identity mismatch')
            slot = int(datetime.fromisoformat(row[0]).timestamp()) // 300
            timing = db.execute(
                "SELECT started_at,payload_json FROM execution_runtime_timings "
                "WHERE json_extract(payload_json,'$.kind')='CYCLE' "
                "AND json_extract(payload_json,'$.slot')=? ORDER BY id LIMIT 1", (slot,)).fetchone()
        clocks = {'as_of': packet['as_of'], 'deadline': packet['valid_until'],
                  'account_captured_at': packet['account']['captured_at'],
                  'account_max_age_seconds': packet['limits']['account_max_age_seconds'],
                  'quote_max_age_seconds': packet['limits']['quote_max_age_seconds'],
                  'model_completed_at': evidence.get('entry_completed_at'),
                  'review_at': evidence.get('entry_review_at')}
        clocks['options'] = [{'source_at': o['quote']['source_at'],
                             'received_at': o['quote']['received_at'],
                             'admission_deadline': o['candidate']['admission']['valid_until']}
                            for o in packet['opportunities']]
        result = {'status': 'RECORDED', 'evidence_clock': 'ORIGINAL_SYNTHETIC_CLOCKS',
                  'cycle_key': cycle_key, 'started_at': row[0], 'stored_status': row[1],
                  'decision_status': evidence.get('status'), 'reason': evidence.get('reason'),
                  'clocks': clocks,
                  'cycle_timing': ({'started_at': timing[0], **json.loads(timing[1])} if timing else None)}
        end = clocks['review_at']
        if profile is not None and end and clocks['options']:
            low = min(datetime.fromisoformat(o['source_at']) for o in clocks['options'])
            high = datetime.fromisoformat(end)
            result['restore_to_review'] = profile.original_window(low, high)
        return result
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        return {'status': 'UNAVAILABLE', 'error_class': type(exc).__name__}
