"""Disposable changing-journal memory comparison; no connected account inputs.

Run each policy in a fresh network-isolated process with the test environment:
  python -m tests.restore_memory_benchmark --policy versions --output /new/path
  python -m tests.restore_memory_benchmark --policy replace --output /another/path
"""

import argparse
import gc
import json
import os
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.execution import restore
from soak_worker import BASE, seed_capacity
from test_option_execution import NOW, owned
from test_restore_encoding import legacy_digest


class HistoricalVersions(restore.RowEncodings):
    """The preceding policy: content identity alone retains superseded batches."""
    def encode(self, rows, *, slot=None):
        return super().encode(rows)


def resident():
    return {key: int(value.split()[0]) * 1024
            for key, value in (line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines()
                               if line.startswith(('VmRSS:', 'RssAnon:', 'RssFile:')))}


def run(output, policy, count=400):
    if not output.is_absolute() or output.resolve() != output or output.exists():
        raise ValueError('New canonical output required')
    if any(line.split(':')[0].strip() != 'lo'
           for line in Path('/proc/net/dev').read_text().splitlines()[2:]):
        raise ValueError('Network-isolated process required')
    if policy not in ('versions', 'replace') or not 100 <= count <= 2000:
        raise ValueError('Explicit bounded comparison required')
    output.mkdir(mode=0o700)
    affinity = {max(os.sched_getaffinity(0))}
    os.sched_setaffinity(0, affinity)
    restore._ROW_ENCODINGS = HistoricalVersions() if policy == 'versions' else restore.RowEncodings()
    result = {'version': 'restore-memory-benchmark-v1', 'policy': policy, 'seed_mib': 112,
              'synthetic': True, 'provider_calls': False, 'live_enabled': False,
              'iterations': count, 'samples': [], 'status': 'RUNNING',
              'cpu_affinity': sorted(affinity)}
    began = time.monotonic()

    def sample(iteration):
        result['samples'].append({'iteration': iteration, 'seconds': time.monotonic() - began,
                                  'resident': resident(), 'row_cache_bytes': restore._ROW_ENCODINGS.size,
                                  'row_cache_entries': len(restore._ROW_ENCODINGS.values),
                                  'text_cache_bytes': restore._TEXT_ENCODINGS.size})
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result['samples'][-1]), flush=True)

    with owned(output) as (engine, _, _):
        with engine.journal.write() as db:
            db.execute('CREATE TABLE execution_runtime_timings('
                       'id INTEGER PRIMARY KEY,started_at TEXT,payload_json TEXT)')
        result['seed_rows'] = seed_capacity(engine.journal, 112)
        engine.journal.enable_restore_fence(now=NOW)
        result['initial_database_bytes'] = engine.journal.path.stat().st_size
        sample(0)
        for index in range(1, count + 1):
            with engine.journal.write() as db:
                db.execute('INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)',
                           (BASE.isoformat(), json.dumps({'version': 'memory-workload-v1',
                                                         'sequence': index, 'padding': str(index) * 3000})))
            if index % 25 == 0:
                sample(index)
        with engine.journal.read(verify_restore=True) as db:
            result['canonical_v1_hash_matches'] = restore._digest(db) == legacy_digest(db)
        assert result['canonical_v1_hash_matches']
        result['final_database_bytes'] = engine.journal.path.stat().st_size
        result['peak_process_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        gc.collect()
        sample('after_gc')
        result['status'] = 'RECORDED'
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', choices=('versions', 'replace'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=400)
    args = parser.parse_args()
    run(args.output, args.policy, args.count)
