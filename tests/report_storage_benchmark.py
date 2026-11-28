"""Compare the same disposable report copy on tmpfs and an explicit disk directory.

Requires a new output directory and an existing tmpfs root; no account, network,
runtime or credentials are used. This measures storage allocation, not causality
for an earlier worker failure or a cgroup memory/latency qualification.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]


def run(output, tmpfs):
    if output.exists() or output.is_symlink() or output.resolve() != output or not output.is_absolute():
        raise ValueError('NEW_ABSOLUTE_OUTPUT_REQUIRED')
    if any(line.split(':')[0].strip() != 'lo'
           for line in Path('/proc/net/dev').read_text().splitlines()[2:]):
        raise ValueError('NETWORK_NAMESPACE_REQUIRED')
    mounts = [line.split() for line in Path('/proc/mounts').read_text().splitlines()]
    if not any(row[1] == str(tmpfs) and row[2] == 'tmpfs' for row in mounts):
        raise ValueError('EXPLICIT_TMPFS_MOUNT_REQUIRED')
    output.mkdir(mode=0o700)
    disk = output / 'copies'
    disk.mkdir(mode=0o700)
    source = output / 'source.db'
    with closing(sqlite3.connect(source)) as db:
        db.execute('CREATE TABLE capacity(id INTEGER PRIMARY KEY, payload BLOB)')
        db.executemany('INSERT INTO capacity VALUES(?,zeroblob(3840))', ((i,) for i in range(53300)))
        db.commit()
    def digest():
        with source.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    before = digest()
    spec = importlib.util.spec_from_file_location('report_storage', ROOT / 'scripts/paper-session-report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {'version': 'report-storage-comparison-v1', 'synthetic': True,
              'source_bytes': source.stat().st_size, 'source_sha256': before,
              'sample_scope': 'Full-copy allocation, no trading or cgroup qualification',
              'provider_calls': False, 'live_enabled': False, 'samples': []}
    original_tempdir = tempfile.tempdir
    try:
        with tempfile.TemporaryDirectory(prefix='paper-copy-comparison-', dir=tmpfs) as old:
            tempfile.tempdir = old
            for label, scratch in (('DEFAULT_TMPFS', None), ('EXPLICIT_DISK', disk)):
                started = time.monotonic()
                with closing(module.connection(source, scratch_directory=scratch)) as db:
                    target = Path(db.execute('PRAGMA database_list').fetchone()[2])
                    size = target.stat().st_blocks * 512
                    rows = db.execute('SELECT count(*) FROM capacity').fetchone()[0]
                    result['samples'].append({
                        'storage': label, 'copy_seconds': time.monotonic() - started,
                        'copied_rows': rows, 'allocated_bytes': size,
                        'copy_is_on_tmpfs': target.is_relative_to(Path(old)),
                        'tmpfs_copy_allocated_bytes': size if target.is_relative_to(Path(old)) else 0,
                    })
                assert not target.exists()
                assert not list(disk.iterdir()) and not list(Path(old).iterdir())
    finally:
        tempfile.tempdir = original_tempdir
    result['source_unchanged'] = digest() == before
    assert result['source_unchanged']
    assert result['samples'][0]['copied_rows'] == result['samples'][1]['copied_rows'] == 53300
    assert result['samples'][0]['tmpfs_copy_allocated_bytes'] >= result['source_bytes']
    assert result['samples'][1]['tmpfs_copy_allocated_bytes'] == 0
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tmpfs', type=Path, required=True)
    args = parser.parse_args()
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    print(json.dumps(run(args.output, args.tmpfs), indent=2))
