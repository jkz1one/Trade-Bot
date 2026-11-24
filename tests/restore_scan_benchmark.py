"""Compare cache policies on disposable varied history; never open a host account.

Run with the repository test environment:
  python tests/restore_scan_benchmark.py --output /absolute/new/directory
"""

import argparse
from collections import OrderedDict
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


class OriginalLRU(OrderedDict):
    def popitem(self, last=True):
        return super().popitem(last=False)


def run(output, mib=112):
    if not output.is_absolute() or output.resolve() != output:
        raise ValueError("New absolute output required")
    if type(mib) is not int or not 1 <= mib <= 256:
        raise ValueError("Capacity must be 1..256 MiB")
    output.mkdir(mode=0o700)  # Refuse an existing account or previous evidence.
    affinity = {min(os.sched_getaffinity(0))}
    os.sched_setaffinity(0, affinity)
    original_cache, original_prefixes = restore._TEXT_ENCODINGS, restore._prefixes
    result = {"version": "restore-scan-benchmark-v1", "synthetic": True,
              "provider_calls": False, "live_enabled": False,
              "cpu_affinity": sorted(affinity), "seed_mib": mib, "trials": []}
    try:
        with owned(output) as (engine, _, _):
            with engine.journal.write() as db:
                db.execute("CREATE TABLE execution_runtime_timings("
                           "id INTEGER PRIMARY KEY,started_at TEXT,payload_json TEXT)")
            result["seed_rows"] = seed_capacity(engine.journal, mib)
            result["database_bytes"] = engine.journal.path.stat().st_size
            engine.journal.enable_restore_fence(now=NOW)
            # Alternate policies so a one-off load difference cannot select the winner.
            for policy in ("original_lru", "scan_mru", "original_lru", "scan_mru"):
                cache = restore._TextEncodingCache()
                if policy == "original_lru":
                    cache.values = OriginalLRU()
                restore._TEXT_ENCODINGS, restore._prefixes = cache, ()
                samples = []
                for index in range(5):
                    start, cpu = time.monotonic(), time.process_time()
                    with engine.journal.write() as db:
                        db.execute("UPDATE execution_control SET halt_reason=? WHERE id=1",
                                   (f"DISPOSABLE_PROFILE_{policy}_{index}",))
                    samples.append({"wall_seconds": time.monotonic() - start,
                                    "cpu_seconds": time.process_time() - cpu})
                with engine.journal.read() as db:
                    matches = restore._digest(db) == legacy_digest(db)
                with engine.journal.read(verify_restore=True):
                    pass
                assert matches
                result["trials"].append({"policy": policy, "samples": samples,
                    "warm_median_seconds": statistics.median(s["wall_seconds"] for s in samples[1:]),
                    "canonical_v1_hash_matches": matches, "restore_status": "VERIFIED",
                    "cache_entries": len(cache.values), "cache_bytes": cache.size})
    finally:
        restore._TEXT_ENCODINGS, restore._prefixes = original_cache, original_prefixes
    result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["status"] = "RECORDED"
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mib", default=112, type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.mib), sort_keys=True))
