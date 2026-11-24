#!/usr/bin/env python3
"""One bounded read-only report. Never runs a worker, capture, resume or build."""
import argparse
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sqlite3
import stat
import time
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('diagnose_daily', ROOT / 'scripts/paper-daily.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


def run_command(args, *, limit=2 * 1024 * 1024, timeout=45):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    if len(result.stdout.encode()) > limit:
        raise ValueError('DIAGNOSTIC_OUTPUT_BOUND')
    return result


def journal_failure(target, runner):
    result = runner(['journalctl', '--utc', '-u', daily.UNIT + '.service', '--since', target + ' 00:00:00 UTC',
                     '--no-pager', '-o', 'cat', '-n', '12', '--grep', '"status": "(CAPTURE_FAILED|UNAVAILABLE)"'])
    if result.returncode:
        return None
    found = None
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get('step'):
                item = daily.step_failure(daily.starter.StepFailed('saved', step=row['step'], report=row.get('report')))
                if item:
                    found = item
        except (ValueError, TypeError, AttributeError):
            continue
    return found


def evidence_changes(directory):
    # The evidence file contains metadata, not the private OAuth file. Never
    # accept an arbitrary file path from a log or follow a symlink.
    if not isinstance(directory, str) or not re.fullmatch(r'/root/trade-bot-options-proof-[A-Za-z0-9_-]{1,80}', directory):
        return None
    folder = Path(directory)
    daily.private(folder, True)
    path = folder / 'context.json'
    daily.private(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('CAPTURE_EVIDENCE_BOUND')
    raw = json.loads(path.read_text())
    actual = (raw.get('result') or raw).get('schemas', {}).get('tools')
    baseline = json.loads((ROOT / 'app/options/read_contract.json').read_text())
    if not isinstance(actual, dict):
        return None
    changes = []
    def visit(a, b, path=()):
        if len(changes) >= 20 or len(path) > 24:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                safe = key if re.fullmatch(r'[A-Za-z_$][A-Za-z_0-9$-]{0,63}', key) else 'OTHER_FIELD'
                if key not in a or key not in b:
                    if len(changes) < 20:
                        changes.append({'path': list((*path, safe)), 'change': 'ADDED' if key not in a else 'REMOVED'})
                else:
                    visit(a[key], b[key], (*path, safe))
        elif type(a) is not type(b) or a != b:
            changes.append({'path': list(path), 'change': 'CHANGED'})
    visit(baseline, actual)
    return {'changes': changes, 'limit_reached': len(changes) >= 20,
            'comparison': 'PACKAGED_BASELINE_INCLUDING_DESCRIPTIONS'}


def display_receipt(now):
    """Inspect the immutable published copy, not the native account database."""
    path = daily.host.EXPORTS/'connected-price-options-v1/options.db'
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.resolve() != path or info.st_size > 512*1024*1024:
            raise ValueError('DISPLAY_FILE_BOUND')
        deadline = time.monotonic()+5
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True, timeout=1)) as db:
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            raw = db.execute('SELECT payload FROM dashboard_snapshot WHERE id=1 AND length(payload)<=4096').fetchone()
            receipt = json.loads(raw[0])
            at = datetime.fromisoformat(receipt['published_at'])
            age = (now-at).total_seconds()
            runtime = db.execute('SELECT status FROM execution_option_runtime WHERE id=1').fetchone()
        after = path.lstat()
        if (info.st_ino, info.st_mtime_ns, info.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
            raise ValueError('DISPLAY_REPLACED')
        return {'status': 'RECEIPT_READ', 'published_at': at.isoformat(), 'age_seconds': age,
                'stored_runtime': runtime[0] if runtime and runtime[0] in {'RUNNING', 'STOPPED', 'FAILED', 'STARTING'} else 'UNKNOWN',
                'accounting_reverified': False}
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return {'status': 'UNAVAILABLE', 'accounting_reverified': False}


def diagnose(target=None, *, runner=run_command, now=None):
    now = now or datetime.now(timezone.utc)
    target = target or now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    if date.fromisoformat(target).isoformat() != target:
        raise ValueError('EXACT_SESSION_DATE_REQUIRED')
    config = daily.read(daily.HOME / 'config.json') or {}
    state = daily.read(daily.HOME / 'state.json') or {}
    day = (state.get('days') or {}).get(target) or {}
    run_id = 'daily-' + target.replace('-', '')
    result = {'version': 'paper-diagnostic-v1', 'observed_at': now.isoformat(), 'target_session': target,
              'installed_release': config.get('release'), 'installed_image': config.get('image_id'),
              'paused': (daily.HOME / 'paused.json').exists(), 'controller_updated_at': state.get('updated_at'),
              'controller_status': state.get('status'), 'controller_reasons': state.get('reasons'),
              'controller_target_session': (state.get('schedule') or {}).get('target_session'),
              'run_id': run_id, 'preparation_failures': day.get('failures', 0), 'receipt_available': bool(day.get('receipt')),
              'launch_attempted': day.get('launch_attempted', False), 'state_modified': False,
              'provider_calls': False, 'live_enabled': False, 'issues': []}
    result['display_snapshot'] = display_receipt(now)
    failure = day.get('last_failure')
    if not failure and day.get('last_error'):
        try:
            failure = journal_failure(target, runner)
        except (OSError, ValueError, subprocess.SubprocessError):
            result['issues'].append('JOURNAL_UNAVAILABLE')
    result['last_failure'] = failure
    if failure and not (failure.get('failure') or {}).get('schema_changes'):
        try:
            result['schema_changes'] = evidence_changes(failure.get('evidence_directory'))
        except (OSError, ValueError, TypeError, KeyError):
            result['issues'].append('CAPTURE_EVIDENCE_UNAVAILABLE')
    backend = daily.Backend(config)
    try:
        item = backend.container(run_id, image_id=day.get('image_id'))
        result['worker_exists'] = item is not None
        if item is not None:
            state_info = item.get('State') or {}
            result['worker'] = {k: state_info.get(k) for k in ('Status', 'Running', 'StartedAt', 'FinishedAt', 'ExitCode', 'OOMKilled')}
            result['worker'].update(container_id=item['Id'], image_id=item['Image'], restart_count=item.get('RestartCount'))
            started = datetime.fromisoformat(state_info['StartedAt'].replace('Z', '+00:00'))
            ended = now if state_info.get('Running') else datetime.fromisoformat(state_info['FinishedAt'].replace('Z', '+00:00'))
            result['worker']['elapsed_seconds'] = max(0, (ended-started).total_seconds())
            output = runner(['python3', str(ROOT / 'scripts/paper-session-report.py'), '--run-id', run_id])
            report = json.loads(output.stdout)
            if output.returncode or report.get('run_id') != run_id:
                result['issues'].append('SESSION_REPORT_UNAVAILABLE')
            else:
                result['session'] = {k: report.get(k) for k in ('operation', 'runtime_evidence', 'cycle_count', 'cycle_outcomes',
                    'decision_count', 'run_execution', 'collection', 'publication_failures', 'worker_exit',
                    'collector_failures', 'collection_timing', 'runtime_failures', 'runtime_timing')}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        result['issues'].append('WORKER_INSPECTION_UNAVAILABLE')
    result['status'] = 'DIAGNOSTIC_RECORDED' if not result['issues'] else 'DIAGNOSTIC_PARTIAL'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-session')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('ROOT_HOST_OPERATOR_REQUIRED')
    print(json.dumps(diagnose(args.target_session), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'DIAGNOSTIC_UNAVAILABLE', 'error_class': type(exc).__name__,
                          'state_modified': False, 'provider_calls': False, 'live_enabled': False}))
        raise SystemExit(2)
