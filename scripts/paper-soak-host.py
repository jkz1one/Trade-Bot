#!/usr/bin/env python3
"""Detached, credential-free offline qualification; never install or resume PAPER."""

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path('/var/lib/trade-bot-paper-soak')
LOCK = Path('/run/lock/trade-bot-paper-soak.lock')
LABEL = 'trade-bot.offline-soak-v1'
SECONDS = 21480
PROFILES = {'entry': 335, 'entry-repeat': 1005, 'duration': SECONDS}
MEMORY = 1024**3
BUILD_INPUTS = ('Dockerfile.paper-soak', 'Dockerfile.paper-soak.dockerignore',
                'requirements-runtime.lock', 'requirements-build.lock', 'requirements-dev.lock',
                'pyproject.toml', 'README.md', 'app', 'tests', 'scripts', 'examples')
RUN_ARGS = ['--output', '/evidence/run', '--seconds', str(SECONDS), '--seed-mib', '112',
            '--cpus', '1', '--profile-opening-restore']


def run_args(profile):
    if profile not in PROFILES:
        raise ValueError('KNOWN_QUALIFICATION_PROFILE_REQUIRED')
    args = list(RUN_ARGS)
    args[args.index('--seconds') + 1] = str(335 if profile == 'entry-repeat' else PROFILES[profile])
    if profile == 'entry-repeat':
        args.append('--repeat-entry')
    return args


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30, **kwargs)
    if result.returncode:
        raise ValueError('COMMAND_FAILED:' + ':'.join(args[:2]))
    return result.stdout.strip()


def save(path, value):
    temporary = path.with_suffix('.pending')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def idle(checkout):
    """Refuse contention; never stop a worker or change a controller hold."""
    for label in ('trade-bot.connected-session-v1', LABEL):
        if command(['docker', 'ps', '--filter', 'label=' + label, '--format', '{{.ID}}']):
            raise ValueError('WORKER_ALREADY_RUNNING')
    value = json.loads(command([sys.executable, str(checkout / 'scripts/paper-daily.py'), 'status']))
    operation = value.get('operation') or {}
    held = operation.get('status') == 'FAILED' and (
        'SESSION_STOPPED_REVIEW_REQUIRED' in (operation.get('reasons') or [])
    )
    if value.get('paused') is not True and not held:
        raise ValueError('SCHEDULER_NOT_PAUSED_OR_REVIEW_HELD')


def create_args(name, release, image, data, *, profile='duration'):
    return ['docker', 'create', '--name', name, '--label', LABEL + '=true',
            '--label', 'trade-bot.offline-soak.release=' + release,
            '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--user', '0:0', '--init',
            '--cpus', '1', '--memory', str(MEMORY), '--memory-swap', str(MEMORY),
            '--pids-limit', '128', '--restart', 'no',
            '--log-driver', 'local', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=2',
            '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=268435456',
            '--mount', f'type=bind,src={data},dst=/evidence', image, *run_args(profile)]


def start(checkout, *, profile='duration'):
    run_args(profile)  # Reject unknown profiles before creating evidence or a container.
    if os.geteuid() != 0:
        raise ValueError('ROOT_HOST_OPERATOR_REQUIRED')
    checkout = checkout.resolve(strict=True)
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'])
        if not re.fullmatch(r'[0-9a-f]{40}', release):
            raise ValueError('COMMIT_ID_REQUIRED')
        if command(['git', '-C', str(ROOT), 'status', '--porcelain']):
            raise ValueError('CLEAN_CANDIDATE_REQUIRED')
        idle(checkout)
        EVIDENCE.mkdir(mode=0o700, parents=True, exist_ok=True)
        if EVIDENCE.is_symlink() or EVIDENCE.resolve() != EVIDENCE:
            raise ValueError('CANONICAL_EVIDENCE_DIRECTORY_REQUIRED')
        output = Path(tempfile.mkdtemp(prefix='trade-bot-offline-soak-' + release[:12] + '-',
                                       dir=EVIDENCE))
        name = output.name  # Each attempt retains its own proof, even after a failed build.
        data = output / 'data'
        data.mkdir(mode=0o700)
        shutil.copyfile(__file__, output / 'check.py')
        manifest = {str(p.relative_to(ROOT / 'app')): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((ROOT / 'app').rglob('*'))
                    if p.is_file() and '__pycache__' not in p.parts}
        receipt = {'version': 'paper-soak-host-v1', 'release': release, 'name': name,
                   'status': 'BUILDING', 'created_at': datetime.now(UTC).isoformat(),
                   'profile': profile, 'seconds': PROFILES[profile], 'seed_mib': 112, 'data': str(data),
                   'application_manifest_sha256': hashlib.sha256(
                       json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                   'connected_health': 'UNVERIFIED', 'synthetic': True,
                   'provider_calls': False, 'model_service_calls': False, 'live_enabled': False}
        save(output / 'host.json', receipt)
        try:
            # Only committed files enter the build. No working-directory secrets.
            archive = output / 'source.tar'
            command(['git', '-C', str(ROOT), 'archive', '--format=tar', '-o', str(archive),
                     release, *BUILD_INPUTS])
            with archive.open('rb') as source, (output / 'build.log').open('w') as log:
                build = subprocess.run(
                    ['docker', 'build', '-f', 'Dockerfile.paper-soak', '--iidfile',
                     str(output / 'image-id'), '--build-arg', 'TRADE_BOT_RELEASE=' + release, '-'],
                    stdin=source, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
            if build.returncode:
                raise ValueError('IMAGE_BUILD_FAILED')
            image = (output / 'image-id').read_text().strip()
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
                raise ValueError('IMMUTABLE_IMAGE_REQUIRED')
            receipt['image_id'] = image
            idle(checkout)  # Building must not conceal a newly launched worker.
            container = command(create_args(name, release, image, data, profile=profile))
            if not re.fullmatch(r'[0-9a-f]{64}', container):
                raise ValueError('CONTAINER_ID_REQUIRED')
            receipt.update(status='CREATED', container_id=container)
            save(output / 'host.json', receipt)
            command(['docker', 'start', container])
            receipt['status'] = 'STARTED'
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            receipt.update(status='START_FAILED', failure_class=type(exc).__name__)
            raise
        finally:
            save(output / 'host.json', receipt)
            print(json.dumps({'evidence_directory': str(output), 'launch_status': receipt['status'],
                              'check_command': f'python3 {output}/check.py status --evidence {output}'}))
        return status(output)


def load_optional(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def session_report(directory, observed_at=None, *, finished):
    """Read retained test evidence; its synthetic clocks never imply current host health."""
    path = directory / 'report.json'
    if not finished or not path.exists():
        path = directory / 'latest-report.json'
    try:
        with path.open() as stream:
            # The atomic file's own mtime belongs to these exact bytes, even if
            # the running worker replaces the path during this read.
            saved_at = os.fstat(stream.fileno()).st_mtime
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('REPORT_TOO_LARGE')
        report = json.loads(raw)
        start = datetime.fromisoformat(report['window_start'])
        end = datetime.fromisoformat(report['window_end'])
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            raise ValueError('REPORT_WINDOW_REQUIRED')
        timing = report.get('runtime_timing') or {}
        if not isinstance(timing, dict):
            raise ValueError('REPORT_TIMING_OBJECT_REQUIRED')
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'UNAVAILABLE', 'source': path.name}
    observed_at = observed_at or datetime.now(UTC)
    age = observed_at.timestamp() - saved_at
    return {'status': 'RECORDED', 'source': path.name,
            'observed_at': observed_at.isoformat(),
            'saved_at': datetime.fromtimestamp(saved_at, UTC).isoformat(),
            'receipt_age_seconds': age,
            'receipt_freshness': 'FUTURE' if age < 0 else 'STALE' if age > 90 else 'CURRENT',
            'evidence_clock': 'SYNTHETIC_REPORT_WINDOW',
            'runtime_evidence_at_cutoff': report.get('runtime_evidence'),
            'timing_coverage': timing.get('coverage'),
            **{k: report.get(k) for k in (
                'window_start', 'window_end', 'current_runtime', 'accepted_packet',
                'cycle_count', 'cycle_outcomes', 'decision_count', 'decision_reason_counts',
                'run_execution', 'collection', 'run_issues', 'runtime_failures',
                'publication_failures')}}


def failure_detail(value):
    """Project stored application diagnostics, never messages or arbitrary paths."""
    if not isinstance(value, dict):
        return {'evidence_available': False}
    result = {'evidence_available': True, 'frames': []}
    error = value.get('error_class')
    if isinstance(error, str) and error in {
        'ValueError', 'TypeError', 'KeyError', 'RuntimeError', 'TimeoutError',
        'OSError', 'PermissionError', 'FileNotFoundError', 'MemoryError',
        'FixtureProcessTimeout', 'FixtureProcessFailed', 'FixtureProcessProtocolError',
        'OperationalError', 'DatabaseError', 'IntegrityError', 'ProgrammingError',
        'CancelledError', 'ExecutionBlocked', 'OTHER_ERROR',
    }:
        result['error_class'] = value['error_class']
    code, name = value.get('sqlite_errorcode'), value.get('sqlite_errorname')
    if (error in ('OperationalError', 'DatabaseError', 'IntegrityError', 'ProgrammingError')
            and type(code) is int and 0 < code <= 65535 and isinstance(name, str)
            and name.startswith('SQLITE_') and len(name) <= 80 and getattr(sqlite3, name, None) == code):
        result.update(sqlite_errorcode=code, sqlite_errorname=name)
    if isinstance(value.get('stage'), str) and value['stage'] in {'STARTUP', 'RUNNING'}:
        result['stage'] = value['stage']
    frames = value.get('frames')
    for frame in frames[-8:] if isinstance(frames, list) else []:
        if not isinstance(frame, dict):
            continue
        path, line = frame.get('file'), frame.get('line')
        if (isinstance(path, str) and len(path) <= 240
                and re.fullmatch(r'app/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py', path)
                and type(line) is int and 0 < line <= 1000000):
            result['frames'].append({'file': path, 'line': line})
    return result


def retained_publication_failures(output, item, receipt, *, trial=None):
    """Read a stopped disposable journal even when its final report was not saved."""
    unavailable = {'status': 'UNAVAILABLE', 'accounting_reverified': False}
    if item['State']['Running'] or item['State']['Status'] != 'exited':
        return {**unavailable, 'reason': 'WORKER_NOT_STOPPED'}
    if not isolation_matches(item, receipt):
        return {**unavailable, 'reason': 'CONTAINER_IDENTITY_OR_ISOLATION_MISMATCH'}
    relative = f'data/run/trial-{trial}/owner/options.db' if trial in (1, 2, 3) else 'data/run/owner/options.db'
    path = output / relative
    try:
        if (Path(receipt['data']) != output / 'data' or path.resolve(strict=True) != path
                or not path.is_file() or not 100 <= path.stat().st_size <= 1024**3):
            raise ValueError('DEDICATED_RETAINED_JOURNAL_REQUIRED')
        # This is a stopped rollback-journal database, never a live WAL view.
        # Immutable read mode cannot create sidecars, acquire writer locks or recover it.
        if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('RETAINED_SQLITE_SIDECARS_REQUIRE_REVIEW')
        with path.open('rb') as stream:
            header = stream.read(20)
        if header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
            raise ValueError('STOPPED_ROLLBACK_JOURNAL_REQUIRED')
        deadline = time.monotonic() + 2
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=0)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            rows = db.execute(
                "SELECT occurred_at,CASE WHEN length(CAST(payload AS BLOB))<=16384 THEN payload END "
                "FROM execution_events WHERE kind='CONNECTED_PUBLICATION_FAILED' "
                "ORDER BY sequence DESC LIMIT 10").fetchall()
        failures = []
        for at, raw in rows:
            try:
                value = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                value = None
            # Timestamps are original synthetic evidence, not current server health.
            try:
                stamp = datetime.fromisoformat(at) if isinstance(at, str) and len(at) <= 64 else None
                at = stamp.isoformat() if stamp is not None and stamp.utcoffset() is not None else None
            except ValueError:
                at = None
            failures.append({'at': at, **failure_detail(value)})
        return {'status': 'STORED_EVENTS_READ', 'source': relative,
                'evidence_clock': 'ORIGINAL_SYNTHETIC_CLOCKS', 'accounting_reverified': False,
                'publication_failures': failures}
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {**unavailable, 'reason': 'RETAINED_JOURNAL_UNREADABLE', 'error_class': type(exc).__name__}


def memory_pressure(memory):
    """Separate a recorded limit event from OOM and from post-exit usage."""
    if not isinstance(memory, dict) or memory.get('status') != 'OBSERVED':
        return {'status': 'UNAVAILABLE'}
    events = memory.get('events')
    limit, peak = memory.get('max_bytes'), memory.get('peak_bytes')
    if (not isinstance(events, dict) or type(limit) is not int or limit <= 0
            or type(peak) is not int or peak < 0
            or any(type(events.get(k)) is not int or events[k] < 0 for k in ('max', 'oom', 'oom_kill'))):
        return {'status': 'UNAVAILABLE'}
    status = ('OOM_KILL_RECORDED' if events['oom_kill'] else 'OOM_RECORDED' if events['oom']
              else 'LIMIT_REACHED' if events['max'] or peak >= limit else 'NO_LIMIT_EVENT_RECORDED')
    return {'status': status, 'scope': 'container lifetime; not failure-phase attribution',
            'limit_bytes': limit, 'peak_bytes': peak,
            'peak_headroom_bytes': max(0, limit - peak),
            'events': {k: events[k] for k in ('max', 'oom', 'oom_kill')},
            'failure_causality': 'UNDETERMINED'}


def isolation_matches(item, receipt):
    profile = receipt.get('profile', 'duration')  # Older retained receipts were duration only.
    if profile not in PROFILES or receipt.get('seconds', PROFILES[profile]) != PROFILES[profile]:
        return False
    host, config = item['HostConfig'], item['Config']
    binds = [m for m in item['Mounts'] if m['Type'] != 'tmpfs']
    labels = config.get('Labels') or {}
    return (item['Id'] == receipt['container_id'] and item['Name'] == '/' + receipt['name']
            and item['Image'] == receipt['image_id'] and config['Image'] == receipt['image_id']
            and config['User'] == '0:0' and config['Cmd'] == run_args(profile)
            and config['Entrypoint'] == ['python', '-I', '-W', 'error', '/opt/trade-bot/scripts/paper-soak.py']
            and labels.get(LABEL) == 'true'
            and labels.get('trade-bot.offline-soak.release') == receipt['release']
            and host['NetworkMode'] == 'none' and host['ReadonlyRootfs']
            and host['NanoCpus'] == 1000000000 and host['Memory'] == MEMORY
            and host['MemorySwap'] == MEMORY and host['PidsLimit'] == 128
            and host['RestartPolicy']['Name'] == 'no'
            and not host['Privileged'] and not host.get('CapAdd') and host['CapDrop'] == ['ALL']
            and any(x in ('no-new-privileges', 'no-new-privileges:true')
                    for x in host['SecurityOpt'])
            and len(binds) == 1 and binds[0]['Type'] == 'bind' and binds[0]['RW']
            and binds[0]['Source'] == receipt['data'] and binds[0]['Destination'] == '/evidence')


def classify(item, receipt, summary, progress):
    if not isolation_matches(item, receipt):
        return 'UNVERIFIED', 'CONTAINER_IDENTITY_OR_ISOLATION_MISMATCH'
    state = item['State']
    if state['OOMKilled']:
        return 'FAILED', 'CONTAINER_OOM'
    if item['RestartCount']:
        return 'FAILED', 'CONTAINER_RESTARTED'
    if state['Running']:
        return 'RUNNING', None
    if state['Status'] != 'exited':
        return 'INCOMPLETE', 'CONTAINER_NOT_COMPLETED'
    if state['ExitCode'] != 0 or 'FAILED' in (summary.get('status'), progress.get('status')):
        return 'FAILED', 'SOAK_EXIT_OR_ASSERTION_FAILURE'
    return completion(receipt, summary, progress)


def completion(receipt, summary, progress):
    """Evidence checks shared by single runs and each independently retained trial."""
    elapsed = progress.get('elapsed_seconds')
    profile = receipt.get('profile', 'duration')
    seconds = PROFILES[profile]
    duration = 'OBSERVED' if profile == 'duration' else 'NOT_RUN'
    valid = (summary.get('status') == progress.get('status') == 'PASSED'
             and summary.get('child_exit_code') == 0 and summary.get('seconds') == seconds
             and summary.get('seed_mib') == 112
             and summary.get('application_manifest_sha256') == receipt['application_manifest_sha256']
             and summary.get('wall_clock_soak') == progress.get('wall_clock_full_duration') == duration
             and type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= seconds
             and progress.get('planned_seconds') == seconds and progress.get('logical_cpus') == 1
             and progress.get('final_accounting') == 'VERIFIED_FLAT'
             and progress.get('children_reaped') is True
             and progress.get('native_snapshot_failures') == 0
             and progress.get('native_headroom_target_met') is True
             and (progress.get('decision_coverage') or {}).get('target_met') is True
             and (progress.get('execution') or {}).get('completed_round_trips', 0) >= 1)
    return (('PASSED' if profile == 'duration' else 'ENTRY_GATE_PASSED'), None) if valid else (
        'INCOMPLETE', 'COMPLETE_DURATION_EVIDENCE_REQUIRED' if profile == 'duration'
        else 'COMPLETE_ENTRY_GATE_EVIDENCE_REQUIRED')


def entry_margin(diagnostic):
    """A series needs measured acceptance margin, not only a lucky fill."""
    if not (diagnostic.get('status') == 'RECORDED' and diagnostic.get('decision_status') == 'OPEN'
            and diagnostic.get('stored_status') == 'COMPLETE' and diagnostic.get('clocks')
            and (diagnostic.get('cycle_timing') or {}).get('status') == 'COMPLETE'):
        return {'status': 'UNVERIFIED'}
    spans = (diagnostic.get('cycle_timing') or {}).get('spans') or []
    spawn = [s for s in spans if s.get('phase') == 'NATIVE_ACCEPT_SPAWN']
    transport = [s for s in spans if s.get('phase') == 'NATIVE_ACCEPT_TRANSPORT']
    if len(spawn) != 1 or len(transport) != 1 or any(s.get('status') != 'COMPLETE' for s in spawn + transport):
        return {'status': 'UNVERIFIED'}
    budget, elapsed = spawn[0].get('remaining_at_start_seconds'), transport[0].get('elapsed_seconds')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (budget, elapsed)):
        return {'status': 'UNVERIFIED'}
    return {'status': 'MET' if budget >= 2 * elapsed else 'INSUFFICIENT',
            'remaining_at_spawn_seconds': budget, 'transport_seconds': elapsed,
            'margin_seconds': budget - elapsed, 'minimum_budget_to_transport_ratio': 2}


def repeat_status(output, item, receipt):
    root = output / 'data/run'
    series = load_optional(root / 'series.json')
    trials = []
    for index in range(1, 4):
        directory = root / f'trial-{index}'
        summary = load_optional(directory / 'summary.json')
        progress = load_optional(directory / 'progress.json')
        diagnostic = load_optional(directory / 'entry-diagnostic.json')
        if not summary:
            trials.append({'trial': index, 'status': 'NOT_STARTED'})
            continue
        phase, reason = completion(receipt | {'profile': 'entry'}, summary, progress)
        margin = entry_margin(diagnostic)
        if phase == 'ENTRY_GATE_PASSED' and margin['status'] != 'MET':
            phase, reason = 'INCOMPLETE', 'ENTRY_MARGIN_NOT_QUALIFIED'
        memory = memory_pressure(summary.get('cgroup_memory') or progress.get('cgroup_memory'))
        if phase == 'ENTRY_GATE_PASSED' and memory['status'] != 'NO_LIMIT_EVENT_RECORDED':
            phase, reason = 'INCOMPLETE', 'MEMORY_HEADROOM_NOT_QUALIFIED'
        if 'FAILED' in (summary.get('status'), progress.get('status')):
            phase, reason = 'FAILED', progress.get('failure') or 'TRIAL_FAILED'
        elif progress.get('status') == 'RUNNING':
            phase, reason = 'RUNNING', None
        incidents = retained_publication_failures(output, item, receipt, trial=index)
        if incidents.get('publication_failures'):
            phase, reason = 'FAILED', 'RETAINED_PUBLICATION_FAILURE'
        report = session_report(directory, finished=summary.get('status') != 'RUNNING')
        trials.append({'trial': index, 'status': phase, 'reason': reason,
                       'elapsed_seconds': progress.get('elapsed_seconds'),
                       'execution': progress.get('execution'), 'final_accounting': progress.get('final_accounting'),
                       'runtime_evidence_at_cutoff': report.get('runtime_evidence_at_cutoff'),
                       'decision_count': report.get('decision_count'), 'collection': report.get('collection'),
                       'entry_margin': margin, 'memory_pressure': memory,
                       'failure_evidence': progress.get('failure_evidence'),
                       'publication_failures': incidents.get('publication_failures'),
                       'entry_diagnostic': diagnostic if phase in ('FAILED', 'INCOMPLETE') else None})
    state = item['State']
    active = series.get('active_trial')
    current = root / f'trial-{active}/progress.json' if type(active) is int and 1 <= active <= 3 else root / 'series.json'
    age = max(0, time.time() - current.stat().st_mtime) if current.exists() else None
    outcome, reason = 'INCOMPLETE', 'THREE_COMPLETE_ENTRY_TRIALS_REQUIRED'
    if not isolation_matches(item, receipt):
        outcome, reason = 'UNVERIFIED', 'CONTAINER_IDENTITY_OR_ISOLATION_MISMATCH'
    elif state['OOMKilled'] or item['RestartCount']:
        outcome, reason = 'FAILED', 'CONTAINER_RESTART_OR_OOM'
    elif state['Running']:
        outcome, reason = (('RUNNING_STALE_PROGRESS', 'LAST_PROGRESS_OVER_90_SECONDS_OLD') if age is not None and age > 90
                           else ('RUNNING', None) if age is not None
                           else ('RUNNING_AWAITING_PROGRESS', 'NO_PROGRESS_RECEIPT_YET'))
    elif state['ExitCode'] != 0 or series.get('status') == 'FAILED':
        outcome, reason = 'FAILED', 'ENTRY_SERIES_FAILED'
    elif (state['Status'] == 'exited' and series.get('status') == 'PASSED'
          and series.get('repetitions') == 3 and series.get('seconds_each') == 335
          and series.get('application_manifest_sha256') == receipt['application_manifest_sha256']
          and all(t['status'] == 'ENTRY_GATE_PASSED' for t in trials)):
        outcome, reason = 'ENTRY_SERIES_PASSED', None
    return {'status': outcome, 'reason': reason, 'observed_at': datetime.now(UTC).isoformat(),
            'qualification_profile': 'entry-repeat', 'planned_seconds': 1005,
            'evidence_directory': str(output), 'release': receipt['release'], 'image_id': receipt['image_id'],
            'worker': {k: state.get(k) for k in ('Status', 'Running', 'StartedAt', 'FinishedAt', 'ExitCode', 'OOMKilled')},
            'restart_count': item['RestartCount'], 'active_trial': active, 'progress_age_seconds': age, 'trials': trials,
            'connected_health': 'UNVERIFIED', 'live_enabled': False, 'state_modified': False}


def status(output):
    receipt = json.loads((output / 'host.json').read_text())
    if 'container_id' not in receipt:
        return {'status': 'INCOMPLETE', 'launch_status': receipt['status'], 'evidence_directory': str(output)}
    items = json.loads(command(['docker', 'container', 'inspect', receipt['container_id']]))
    if len(items) != 1:
        raise ValueError('EXACT_CONTAINER_REQUIRED')
    item = items[0]
    if receipt.get('profile') == 'entry-repeat':
        return repeat_status(output, item, receipt)
    progress_path = Path(receipt['data']) / 'run/progress.json'
    summary = load_optional(progress_path.with_name('summary.json'))
    progress = load_optional(progress_path)
    diagnostic = load_optional(progress_path.with_name('entry-diagnostic.json'))
    outcome, reason = classify(item, receipt, summary, progress)
    if outcome == 'ENTRY_GATE_PASSED' and not (
        diagnostic.get('status') == 'RECORDED' and diagnostic.get('decision_status') == 'OPEN'
        and diagnostic.get('stored_status') == 'COMPLETE'
        and (diagnostic.get('cycle_timing') or {}).get('status') == 'COMPLETE'
        and diagnostic.get('clocks')
    ):
        outcome, reason = 'INCOMPLETE', 'ORIGINAL_ENTRY_DIAGNOSTIC_REQUIRED'
    observed_at = datetime.now(UTC)
    age = max(0, observed_at.timestamp() - progress_path.stat().st_mtime) if progress_path.exists() else None
    if outcome == 'RUNNING' and age is not None and age > 90:
        outcome, reason = 'RUNNING_STALE_PROGRESS', 'LAST_PROGRESS_OVER_90_SECONDS_OLD'
    elif outcome == 'RUNNING' and not progress:
        outcome, reason = 'RUNNING_AWAITING_PROGRESS', 'NO_PROGRESS_RECEIPT_YET'
    memory = summary.get('cgroup_memory') or progress.get('cgroup_memory')
    incidents = retained_publication_failures(output, item, receipt)
    if incidents.get('publication_failures') and outcome in {'PASSED', 'ENTRY_GATE_PASSED'}:
        outcome, reason = 'FAILED', 'RETAINED_PUBLICATION_FAILURE'
    return {'status': outcome, 'reason': reason, 'observed_at': observed_at.isoformat(),
            'qualification_profile': receipt.get('profile', 'duration'),
            'planned_seconds': receipt.get('seconds', SECONDS),
            'evidence_directory': str(output), 'release': receipt['release'], 'image_id': receipt['image_id'],
            'worker': {k: item['State'].get(k) for k in
                       ('Status', 'Running', 'StartedAt', 'FinishedAt', 'ExitCode', 'OOMKilled', 'Error')},
            'restart_count': item['RestartCount'], 'progress_age_seconds': age,
            'last_cgroup_memory': memory,
            'memory_pressure': memory_pressure(memory),
            'failure_evidence': progress.get('failure_evidence'),
            'retained_incidents': incidents,
            'entry_diagnostic': diagnostic,
            'worker_resource_window': progress.get('worker_resource_window'),
            'session_report': session_report(progress_path.parent,
                                             finished=item['State']['Status'] == 'exited'),
            'progress': {k: progress.get(k) for k in
                         ('status', 'elapsed_seconds', 'native_snapshot_calls', 'native_snapshot_failures',
                          'native_snapshot_max_seconds', 'capture_attempts', 'peak_tree_rss_bytes',
                          'source_database_bytes', 'report_copy_storage', 'decision_coverage', 'execution', 'final_accounting',
                          'failure_class', 'failure')},
            'connected_health': 'UNVERIFIED', 'live_enabled': False, 'state_modified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    launch = sub.add_parser('start')
    launch.add_argument('--checkout', type=Path, required=True)
    launch.add_argument('--profile', choices=tuple(PROFILES), default='duration',
                        help='entry: 335 seconds; entry-repeat: three fresh entry trials; duration: full window')
    sub.add_parser('status').add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = start(args.checkout, profile=args.profile) if args.operation == 'start' else status(args.evidence)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result = {'status': 'UNAVAILABLE', 'error_class': type(exc).__name__,
                  'reason': str(exc)[:160], 'live_enabled': False}
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] in (
        'RUNNING', 'RUNNING_STALE_PROGRESS', 'RUNNING_AWAITING_PROGRESS', 'PASSED', 'ENTRY_GATE_PASSED', 'ENTRY_SERIES_PASSED') else 1)
