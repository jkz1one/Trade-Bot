#!/usr/bin/env python3
"""Replay only publication from a stopped offline owner; never run trading or install."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER_FILES = ('runtime.json', 'options.db', 'options.db.authority.db', 'venue.db',
               'options.db.runtime.lock')


def source_identity(source):
    """Hash only known disposable owner files, never a credential path from config."""
    if source.resolve(strict=True) != source or {p.name for p in source.iterdir()} != set(OWNER_FILES):
        raise ValueError('EXACT_PRIVATE_OFFLINE_OWNER_REQUIRED')
    result = {}
    for name in OWNER_FILES:
        path = source / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 512 * 1024**2:
            raise ValueError('BOUNDED_REGULAR_OWNER_FILES_REQUIRED')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result[name] = {'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns, 'sha256': digest}
    return result


def replay(source, output):
    """Container entry point: one real publisher invocation into a fresh directory."""
    from app.execution.failure import failure_details
    from app.mixed import dashboard_snapshot as snapshot
    from app.options.runtime_cli import load

    if (output.exists() or output.is_symlink() or not source.is_absolute() or not output.is_absolute()
            or output.resolve() != output):
        raise ValueError('NEW_ABSOLUTE_REPLAY_OUTPUT_REQUIRED')
    if source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('SEPARATE_REPLAY_OUTPUT_REQUIRED')
    identity = source_identity(source)
    if load(source / 'runtime.json').limits.population_id != 'offline-duration-capacity-v1':
        raise ValueError('DISPOSABLE_OFFLINE_POPULATION_REQUIRED')
    output.mkdir(mode=0o700)
    result = {'version': 'paper-publisher-replay-v1', 'status': 'RUNNING',
              'source_identity_before': identity, 'source_modified': None,
              'source_database_bytes': identity['options.db']['bytes'],
              'display_limit_bytes': snapshot.MAX_DATABASE_BYTES,
              'publication_deadline_seconds': snapshot.BACKUP_SECONDS,
              'phases': {}, 'last_projection_table': None, 'calls': 0,
              'execution_authority': False, 'credentials_opened': False,
              'provider_calls': False, 'live_enabled': False, 'connected_health': 'UNVERIFIED',
              'scope': 'Single stopped-owner publication; no runtime/collector contention or trading qualification'}
    original_copy, original_project = snapshot.copy_source, snapshot.copy_display_tables
    def timed_copy(*args):
        started = time.monotonic()
        try:
            return original_copy(*args)
        finally:
            result['phases']['COPY_SOURCE'] = time.monotonic() - started
    def project(db):
        def trace(statement):
            match = re.match(r'INSERT INTO main\.(execution_[a-z0-9_]+)\(', statement)
            if match:
                result['last_projection_table'] = match.group(1)
        db.set_trace_callback(trace)
        started = time.monotonic()
        try:
            return original_project(db)
        finally:
            db.set_trace_callback(None)
            result['phases']['PROJECT_DISPLAY'] = time.monotonic() - started
    publisher = None
    started = time.monotonic()
    try:
        snapshot.copy_source, snapshot.copy_display_tables = timed_copy, project
        publisher = snapshot.DashboardPublisher(source, output / 'display', os.getuid(), os.getgid(), create=True)
        result['calls'] = 1
        result['publication'] = publisher.publish()
        result['status'] = 'STATIC_PUBLICATION_PASSED'
    except Exception as exc:
        result.update(status='PUBLICATION_FAILED', failure=failure_details(exc))
        if isinstance(exc, sqlite3.Error):
            result['failure'].update(sqlite_errorcode=getattr(exc, 'sqlite_errorcode', None),
                                     sqlite_errorname=getattr(exc, 'sqlite_errorname', None))
    finally:
        result['elapsed_seconds'] = time.monotonic() - started
        result['stage'] = publisher.stage if publisher is not None else 'OPEN_PUBLISHER'
        snapshot.copy_source, snapshot.copy_display_tables = original_copy, original_project
        if publisher is not None:
            publisher.close()
        result['source_modified'] = source_identity(source) != identity
        if result['source_modified']:
            result['status'] = 'SOURCE_IDENTITY_CHANGED'
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def launcher():
    spec = importlib.util.spec_from_file_location('paper_soak_host', ROOT / 'scripts/paper-soak-host.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_args(host, name, receipt, source, data, script):
    # Reuse the existing constrained profile; replace only its executable and mounts.
    args = host.create_args(name, receipt['release'], receipt['image_id'], data, profile='entry')
    index = args.index(receipt['image_id'])
    return [*args[:index], '--entrypoint', 'python',
            '--mount', f'type=bind,src={source},dst=/source,readonly',
            '--mount', f'type=bind,src={script},dst=/probe.py,readonly',
            receipt['image_id'], '-I', '-W', 'error', '/probe.py', 'child',
            '--source', '/source', '--output', '/evidence/replay']


def start(evidence, checkout):
    if os.geteuid() != 0:
        raise ValueError('ROOT_HOST_OPERATOR_REQUIRED')
    host = launcher()
    evidence, checkout = evidence.resolve(strict=True), checkout.resolve(strict=True)
    with host.LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = json.loads((evidence / 'host.json').read_text())
        items = json.loads(host.command(['docker', 'container', 'inspect', receipt['container_id']]))
        if len(items) != 1 or not host.isolation_matches(items[0], receipt):
            raise ValueError('EXACT_RETAINED_OFFLINE_CONTAINER_REQUIRED')
        if items[0]['State']['Running'] or items[0]['State']['Status'] != 'exited':
            raise ValueError('RETAINED_WORKER_MUST_BE_STOPPED')
        if Path(receipt['data']) != evidence / 'data' or evidence.parent != host.EVIDENCE:
            raise ValueError('DEDICATED_RETAINED_EVIDENCE_REQUIRED')
        source = evidence / 'data/run/owner'
        source_identity(source)
        host.idle(checkout)
        output = Path(tempfile.mkdtemp(prefix='trade-bot-publisher-replay-', dir=host.EVIDENCE))
        data = output / 'data'
        data.mkdir(mode=0o700)
        script = output / 'probe.py'
        shutil.copyfile(__file__, script)
        report = {'version': 'paper-publisher-replay-host-v1', 'status': 'STARTING',
                  'source_evidence': str(evidence), 'evidence_directory': str(output),
                  'image_id': receipt['image_id'], 'source_release': receipt['release'],
                  'source_mount': 'READ_ONLY', 'connected_health': 'UNVERIFIED', 'live_enabled': False,
                  'limits': {'cpus': 1, 'memory_bytes': host.MEMORY, 'swap_bytes': 0, 'pids': 128}}
        host.save(output / 'replay.json', report)
        container = None
        try:
            container = host.command(create_args(host, output.name, receipt, source, data, script))
            if not re.fullmatch(r'[0-9a-f]{64}', container):
                raise ValueError('NEW_CONTAINER_ID_REQUIRED')
            report['container_id'] = container
            with (output / 'worker.log').open('w') as log:
                try:
                    result = subprocess.run(['docker', 'start', '--attach', container],
                        stdout=log, stderr=subprocess.STDOUT, timeout=45)
                    report['attach_exit_code'] = result.returncode
                except subprocess.TimeoutExpired:
                    # Only this new diagnostic process can be stopped. Preserve the old worker.
                    host.command(['docker', 'stop', '--time', '5', container])
                    report['status'] = 'REPLAY_DEADLINE'
            item = json.loads(host.command(['docker', 'container', 'inspect', container]))[0]
            report['worker'] = item['State']
            report['restart_count'] = item['RestartCount']
            report['result'] = host.load_optional(data / 'replay/result.json')
            if report['status'] != 'REPLAY_DEADLINE':
                report['status'] = ('REPLAY_RECORDED' if item['State']['Status'] == 'exited'
                                    and report['result'] else 'REPLAY_INCOMPLETE')
        finally:
            host.save(output / 'replay.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    host_parser = sub.add_parser('start')
    host_parser.add_argument('--evidence', type=Path, required=True)
    host_parser.add_argument('--checkout', type=Path, required=True)
    child = sub.add_parser('child')
    child.add_argument('--source', type=Path, required=True)
    child.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = (start(args.evidence, args.checkout) if args.operation == 'start'
             else replay(args.source, args.output))
    print(json.dumps(value, indent=2))
    raise SystemExit(0 if value['status'] in {'REPLAY_RECORDED', 'STATIC_PUBLICATION_PASSED'} else 1)
