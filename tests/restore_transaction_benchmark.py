"""Alternate full scans and transaction reuse on new, disposable retained history."""

import argparse
import json
import os
from pathlib import Path
import resource
import statistics
import time

from app.execution import restore
from soak_worker import seed_capacity
from test_option_execution import NOW, owned
from test_restore_encoding import legacy_digest


def run(output, mib=112):
    if not output.is_absolute() or output.resolve() != output or not 1 <= mib <= 256:
        raise ValueError('New absolute output and 1..256 MiB required')
    output.mkdir(mode=0o700)
    affinity = {min(os.sched_getaffinity(0))}
    os.sched_setaffinity(0, affinity)
    original = restore.TimingSnapshot

    class FullScan(original):
        def __init__(self):
            super().__init__()
            self.invalidate()

    result = {'version': 'restore-transaction-benchmark-v1', 'synthetic': True,
              'cpu_affinity': sorted(affinity), 'seed_mib': mib, 'trials': [],
              'provider_calls': False, 'live_enabled': False,
              'scope': 'Same process, alternating transaction policies; no host latency claim'}
    try:
        with owned(output) as (engine, _, _):
            with engine.journal.write() as db:
                db.execute('CREATE TABLE execution_runtime_timings('
                           'id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,payload_json TEXT NOT NULL)')
            result['seed_rows'] = seed_capacity(engine.journal, mib)
            result['database_bytes'] = engine.journal.path.stat().st_size
            engine.journal.enable_restore_fence(now=NOW)
            for trial, policy in enumerate(('full_scan', 'transaction_reuse') * 2):
                restore.TimingSnapshot = FullScan if policy == 'full_scan' else original
                samples = []
                for index in range(6):
                    start, cpu = time.monotonic(), time.process_time()
                    with engine.journal.write() as db:
                        payload = json.dumps({'trial': trial, 'sample': index})
                        db.execute('UPDATE execution_control SET halt_reason=? WHERE id=1', (payload,))
                        # Every actual owner write can flush newly completed timing rows.
                        db.execute('INSERT INTO execution_runtime_timings(started_at,payload_json) VALUES(?,?)',
                                   (NOW.isoformat(), payload))
                        db.execute('UPDATE execution_runtime_timings SET started_at=? WHERE id=?',
                                   (NOW.isoformat(), index + 1))
                    samples.append({'wall_seconds': time.monotonic() - start,
                                    'cpu_seconds': time.process_time() - cpu})
                with engine.journal.read(verify_restore=True) as db:
                    assert restore._digest(db) == legacy_digest(db)
                result['trials'].append({'policy': policy, 'samples': samples,
                    'warm_median_seconds': statistics.median(s['wall_seconds'] for s in samples[1:]),
                    'canonical_v1_hash_matches': True, 'restore_status': 'VERIFIED'})
    finally:
        restore.TimingSnapshot = original
    result['peak_process_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result['status'] = 'RECORDED'
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mib', default=112, type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.mib), sort_keys=True))
