#!/usr/bin/env python3
"""Qualify a clean candidate against real read-only inputs, optionally install it.

Run from a separate candidate worktree. No account reset, enrollment, worker
launch, scheduler resume or retry reset is performed. Receipts survive failure.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_daily', ROOT/'scripts/paper-daily.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)
TIMER = daily.UNIT + '.timer'
SERVICE = daily.UNIT + '.service'


class ReleaseStageFailed(ValueError):
    def __init__(self, detail):
        super().__init__('RELEASE_STAGE_FAILED')
        self.detail = detail


def command(args, *, cwd=ROOT, timeout=60, check=True):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=check)


def git(root, *args):
    return command(['git', *args], cwd=root).stdout.strip()


def structured(root, script, args, expected, *, timeout=300):
    output = command(['python3', str(root/'scripts'/script), *args], cwd=root, timeout=timeout, check=False)
    if len(output.stdout) + len(output.stderr) > 1024*1024:
        raise ValueError('RELEASE_REPORT_BOUND')
    result = None
    for raw in (output.stdout, output.stderr):
        for line in raw.splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict) and 'status' in value:
                    result = value
            except ValueError:
                pass
    if output.returncode or result is None or result.get('status') not in expected:
        raise ReleaseStageFailed(daily.step_failure(daily.starter.StepFailed(
            'release', step=args[0], report=result)))
    return result


@contextmanager
def quiesce(checkout, record, persist):
    active = command(['systemctl', 'is-active', '--quiet', TIMER], check=False).returncode == 0
    record['timer_was_active'] = active
    restore = True
    try:
        command(['systemctl', 'stop', TIMER])
        deadline = time.monotonic() + 60
        while command(['systemctl', 'show', '-p', 'ActiveState', '--value', SERVICE]).stdout.strip() not in {'inactive', 'failed'}:
            if time.monotonic() >= deadline:
                raise ValueError('CONTROLLER_STILL_BUSY')
            time.sleep(1)
        daily.host.no_active_session()
        yield
        restore = record.get('status') != 'ROLLBACK_FAILED'
    finally:
        if record.get('status') == 'ROLLBACK_FAILED':
            restore = False
        if active and restore:
            command(['systemctl', 'start', TIMER])
        record['timer_restored'] = active and restore
        persist()


def execute(checkout, *, deploy=False, output=None):
    checkout = Path(checkout).resolve()
    if checkout == ROOT.resolve() or not checkout.is_dir():
        raise ValueError('SEPARATE_INSTALLED_CHECKOUT_REQUIRED')
    if git(ROOT, 'status', '--porcelain') or git(checkout, 'status', '--porcelain'):
        raise ValueError('CLEAN_RELEASE_CHECKOUT_REQUIRED')
    release, prior = git(ROOT, 'rev-parse', 'HEAD'), git(checkout, 'rev-parse', 'HEAD')
    if not re.fullmatch('[a-f0-9]{40}', release) or not re.fullmatch('[a-f0-9]{40}', prior):
        raise ValueError('PINNED_RELEASE_REQUIRED')
    git(checkout, 'merge-base', '--is-ancestor', prior, release)
    git(ROOT, 'merge-base', '--is-ancestor', release, 'origin/slice2/robinhood-read-shadow')
    folder = Path(tempfile.mkdtemp(prefix='trade-bot-release-', dir='/root')) if output is None else Path(output)
    if output is not None:
        folder.mkdir(mode=0o700)
    record = {'version': 'paper-release-v1', 'release': release, 'prior_release': prior,
              'operation': 'deploy' if deploy else 'preflight', 'status': 'CHECKING',
              'started_at': datetime.now(timezone.utc).isoformat(), 'stages': [],
              'live_enabled': False, 'scheduler_resumed': False, 'account_reset': False}
    def persist():
        daily.save(folder/'release.json', record)
    def step(name, root, script, args, expected, timeout=300):
        record['stage'] = name
        persist()
        try:
            result = structured(root, script, args, set(expected), timeout=timeout)
        except ReleaseStageFailed as exc:
            record['last_failure'] = exc.detail
            persist()
            raise
        record['stages'].append({'step': name, 'result': result})
        persist()
        return result
    persist()
    try:
        with quiesce(checkout, record, persist):
            build = step('build', ROOT, 'connected-session-host.py', ['build'], ['IMAGE_BUILT'], 960)
            info = step('daily-info', ROOT, 'connected-session-host.py', ['daily-info'], ['DAILY_INFO'])
            if (info.get('start_blockers') != [] or info.get('automatic_catalog_blockers') != []
                    or info.get('live_enabled') is not False
                    or (info.get('owner_state') or {}).get('runtime_status') != 'STOPPED'
                    or (info.get('owner_state') or {}).get('halt_reason') != 'OPTION_RUNTIME_STOPPED'):
                raise ValueError('CANDIDATE_OWNER_BLOCKED')
            target = info['target_session']
            record['target_session'] = target
            dates = [target]
            if info.get('swing_history_enrolled'):
                dates.append(info['swing_expiration'])
            for day in dict.fromkeys(dates):
                step('capture-' + day, ROOT, 'connected-session-host.py', ['capture-session', '--target-session', day], ['CATALOG_CAPTURED'])
            snapshot = step('snapshot', ROOT, 'connected-session-host.py', ['recover-snapshot'], ['PUBLISHED'])
            if snapshot.get('source_modified') is not False or snapshot.get('held_plays') != 0:
                raise ValueError('CANDIDATE_ACCOUNT_CHECK_FAILED')
            after = step('owner-recheck', ROOT, 'connected-session-host.py', ['daily-info'], ['DAILY_INFO'])
            if (after.get('owner_state') != info.get('owner_state') or after.get('start_blockers') != []
                    or after.get('target_session') != target
                    or after.get('swing_expiration') != info.get('swing_expiration')):
                raise ValueError('CANDIDATE_OWNER_CHANGED')
            record.update(status='CANDIDATE_QUALIFIED', image_id=build['image_id'],
                          connected_health='UNVERIFIED', account_source_modified=False)
            persist()
            if deploy:
                if git(checkout, 'rev-parse', 'HEAD') != prior or git(checkout, 'status', '--porcelain'):
                    raise ValueError('INSTALLED_CHECKOUT_CHANGED')
                record['stage'] = 'activate'
                persist()
                original_config = daily.read(daily.HOME/'config.json')
                if not original_config or original_config.get('release') != prior:
                    raise ValueError('PRIOR_INSTALLED_RELEASE_MISMATCH')
                unit_files = {daily.UNIT_HOME/name: (daily.UNIT_HOME/name).read_bytes()
                              for name in daily.units(checkout)}
                if any(not raw.startswith(daily.MARKER.encode()) for raw in unit_files.values()):
                    raise ValueError('UNMANAGED_SYSTEMD_UNIT')
                try:
                    git(checkout, 'switch', '--detach', release)
                    result = step('install', checkout, 'paper-daily.py', ['install', '--keep-timer-stopped'], ['DAILY_SCHEDULE_INSTALLED'])
                    if result.get('release') != release or result.get('image_id') != build['image_id']:
                        raise ValueError('INSTALLED_RELEASE_IDENTITY_CHANGED')
                    step('reader', checkout, 'connected-dashboard-host.py',
                         ['update-reader', '--snapshot-name', 'connected-price-options-v1'],
                         ['DASHBOARD_READER_UPDATED', 'DASHBOARD_READER_CURRENT'])
                    record['status'] = 'RELEASE_INSTALLED'
                    persist()
                except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
                    record['activation_error_class'] = type(exc).__name__
                    record['failed_stage'] = record.get('stage')
                    try:
                        # Roll back while the timer is still stopped. Running the
                        # older installer would start it midway through rollback.
                        git(checkout, 'switch', '--detach', prior)
                        daily.save(daily.HOME/'config.json', original_config)
                        for path, raw in unit_files.items():
                            fd, temporary = tempfile.mkstemp(prefix='.paper-unit-', dir=path.parent)
                            with os.fdopen(fd, 'wb') as stream:
                                stream.write(raw)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.chmod(temporary, 0o644)
                            os.replace(temporary, path)
                        command(['systemctl', 'daemon-reload'])
                        step('rollback-reader', checkout, 'connected-dashboard-host.py',
                             ['update-reader', '--snapshot-name', 'connected-price-options-v1'],
                             ['DASHBOARD_READER_UPDATED', 'DASHBOARD_READER_CURRENT'])
                        record['status'] = 'ROLLED_BACK'
                    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError):
                        record['status'] = 'ROLLBACK_FAILED'
                    persist()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        record.update(status='FAILED', error_class=type(exc).__name__)
        persist()
    record['finished_at'] = datetime.now(timezone.utc).isoformat()
    persist()
    return {'status': record['status'], 'release': release, 'stage': record.get('stage'),
            'evidence_directory': str(folder), 'live_enabled': False,
            'connected_health': 'UNVERIFIED', 'scheduler_resumed': False,
            'last_failure': record.get('last_failure'), 'failed_stage': record.get('failed_stage')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['preflight', 'deploy'])
    parser.add_argument('--checkout', type=Path, default=Path('/opt/trade-bot-dashboard'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('ROOT_HOST_OPERATOR_REQUIRED')
    os.umask(0o077)
    with open('/run/lock/trade-bot-paper-release.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = execute(args.checkout, deploy=args.operation == 'deploy')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in {'CANDIDATE_QUALIFIED', 'RELEASE_INSTALLED'} else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'RELEASE_UNAVAILABLE', 'error_class': type(exc).__name__, 'live_enabled': False}))
        raise SystemExit(2)
