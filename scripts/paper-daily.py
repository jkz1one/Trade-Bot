#!/usr/bin/env python3
"""Install or control the persistent, bounded daily PAPER schedule."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HOME = Path('/var/lib/trade-bot-paper-daily')
UNIT_HOME = Path('/etc/systemd/system')
UNIT = 'trade-bot-paper-daily'
MARKER = '# Managed by Trade-Bot paper-daily-v1\n'
NY = ZoneInfo('America/New_York')


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


starter = module('paper_daily_starter', 'paper-session-start.py')
host = module('paper_daily_host', 'connected-session-host.py')


def private(path, directory=False):
    host.private(path, directory)


def save(path, value):
    """Atomic replacement; durable markers precede any external mutation."""
    if path.exists() or path.is_symlink():
        private(path)
    fd, temp = tempfile.mkstemp(prefix='.daily-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read(path, default=None):
    if not path.exists() and not path.is_symlink():
        return default
    private(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('DAILY_STATE_TOO_LARGE')
    return json.loads(path.read_text())


def stamp():
    return datetime.now(timezone.utc)


def parsed(value):
    return datetime.fromisoformat(value)


def status(state, name, reasons=()):
    state.update(status=name, reasons=list(reasons), live_enabled=False, trading_ready=False)
    return state


class Backend:
    def __init__(self, config, home=HOME):
        self.config, self.home = config, home

    def enabled(self):
        return not (self.home / 'paused.json').exists()

    def verify(self):
        if (host.h.command(['git', 'rev-parse', 'HEAD']).stdout.strip() != self.config['release']
                or host.h.command(['git', 'status', '--porcelain']).stdout):
            raise ValueError('SCHEDULE_RELEASE_CHANGED_REINSTALL_REQUIRED')
        if host.image(self.config['release']) != self.config['image_id']:
            raise ValueError('SCHEDULE_IMAGE_CHANGED_REINSTALL_REQUIRED')

    def invoke(self, args):
        if args[0] not in {'daily-info', 'status', 'stop'} and not self.enabled():
            raise ValueError('DAILY_PAUSED')
        return starter.invoke_host(ROOT, args)

    def info(self):
        return self.invoke(['daily-info'])

    def active(self):
        return host.h.docker('ps', '--filter', 'label=' + host.LABEL,
                             '--format', '{{.Names}}').stdout.splitlines()

    def container(self, run_id, *, image_id=None):
        item = host.h.container('trade-bot-connected-' + run_id, missing=True)
        if item is None:
            # A failed inspect can also mean Docker is unavailable. Only a
            # successful exact-name listing can establish absence after dispatch.
            name = 'trade-bot-connected-' + run_id
            found = host.h.docker('container', 'ls', '--all', '--filter', 'name=^/' + name + '$',
                                  '--format', '{{.Names}}').stdout.strip()
            if found:
                raise ValueError('DAILY_CONTAINER_INSPECTION_UNAVAILABLE')
        if item and (not (item['Config'].get('Labels') or {}).get(host.LABEL)
                     or item['Image'] != (image_id or self.config['image_id'])):
            raise ValueError('DAILY_CONTAINER_IDENTITY_CHANGED')
        return item

    def stop(self, run_id, identity, *, image_id=None):
        # A dirty/changed checkout must not prevent the persistent stop control.
        # Inspection still binds the label, pinned image, name and exact ID.
        item = self.container(run_id, image_id=image_id)
        if item is None or item['Id'] != identity:
            raise ValueError('DAILY_CONTAINER_IDENTITY_CHANGED')
        host.h.docker('stop', '--time', '45', identity, timeout=55)
        return {'status': 'SESSION_STOPPED', 'container_id': identity}

    def report(self, run_id):
        output = subprocess.run(['python3', str(ROOT / 'scripts/paper-session-report.py'),
                                 '--run-id', run_id], capture_output=True, text=True,
                                timeout=40, check=True, cwd=ROOT)
        if len(output.stdout) > 1024 * 1024:
            raise ValueError('DAILY_REPORT_TOO_LARGE')
        result = json.loads(output.stdout)
        save(self.home / (run_id + '-report.json'), result)
        return result

    def prepare(self, day, info):
        return starter.launch(day['degen_capture'], info['target_session'],
                              day['run_id'] + '-prep-' + str(day['failures']), 600,
                              invoke=self.invoke, session_root=host.PROFILE_HOME / 'sessions',
                              today=info['target_session'], prepare_only=True,
                              observed_swing_history=info['swing_history_enrolled'],
                              swing_capture_directory=day.get('swing_capture'))

    def preopen(self, target):
        # A precise missing-history diagnostic is retained without preventing DEGEN.
        try:
            return self.invoke(['preopen-inputs', '--target-session', target])
        except starter.StepFailed:
            return {'status': 'PREOPEN_INPUTS_BLOCKED', 'details': 'SEE_SERVICE_JOURNAL'}

    def launch(self, day, info, now, before_run):
        seconds = int((parsed(info['close_at']) - now).total_seconds()) - 120
        # Review and launch must fit inside the cushion. No late session extension.
        def invoke(args):
            if args[0] == 'run':
                if stamp().timestamp() + seconds > parsed(info['close_at']).timestamp():
                    raise ValueError('DAILY_LAUNCH_WINDOW_EXPIRED')
                if not self.enabled():
                    raise ValueError('DAILY_PAUSED')
                before_run()
            report = self.invoke(args)
            if args[0] == 'review-run':
                owner = report.get('binding', {}).get('owner_state')
                if (owner != info['owner_state'] or not isinstance(owner, dict)
                        or owner.get('runtime_status') != 'STOPPED'
                        or owner.get('halt_reason') != 'OPTION_RUNTIME_STOPPED'
                        or report.get('image_id') != self.config['image_id']):
                    raise ValueError('DAILY_REVIEW_BINDING_CHANGED')
            return report
        return starter.run_prepared(day['receipt'], day['run_id'], seconds,
                                    invoke=invoke, today=info['target_session'],
                                    max_feed_recoveries=self.config['max_feed_recoveries'])


def tick(state, backend, persist, now):
    """One bounded step. Never replay a launch after uncertain delivery or failure."""
    state.setdefault('days', {})
    # Always reconcile a persisted launch before selecting a new calendar date.
    for target, day in sorted(state['days'].items(), reverse=True):
        if not day.get('launch_attempted') or day.get('done'):
            continue
        item = backend.container(day['run_id'], image_id=day.get('image_id'))
        if item is None:
            day['awaiting_container'] = True
            state['attention'] = 'LAUNCH_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY'
            return status(state, 'FAILED', [state['attention']])
        if day.get('container_id') and item['Id'] != day['container_id']:
            raise ValueError('DAILY_CONTAINER_IDENTITY_CHANGED')
        if day.pop('awaiting_container', False) and state.get('attention') == 'LAUNCH_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY':
            state.pop('attention')
        day['container_id'] = item['Id']
        active = item['State']['Status'] == 'running'
        if active and (not backend.enabled() or now >= parsed(day['close_at'])):
            backend.stop(day['run_id'], item['Id'], image_id=day.get('image_id'))
            return status(state, 'STOPPING', ['PAUSE_REQUESTED' if not backend.enabled() else 'SESSION_CLOSED'])
        report = backend.report(day['run_id'])
        day['operation'] = report['operation']
        day['fills'] = report.get('account_total_fills')
        if 'run_execution' in report:
            day['run_execution'] = report['run_execution']
        if not active:
            day['done'] = True
            if (item['State'].get('ExitCode') != 0
                    or report['operation']['state'] == 'FAILED'
                    or 'BOUNDED_SESSION_ENDED' not in report['operation'].get('reasons', [])):
                state['attention'] = 'SESSION_STOPPED_REVIEW_REQUIRED'
            return status(state, 'PAUSED' if not backend.enabled() else 'STOPPED',
                          [state['attention']] if state.get('attention') else report['operation'].get('reasons', []))
        return status(state, report['operation']['state'], report['operation'].get('reasons', []))
    if not backend.enabled():
        return status(state, 'PAUSED', ['MANUAL_PAUSE'])
    if state.get('attention'):
        return status(state, 'FAILED', [state['attention']])
    backend.verify()
    if backend.active():
        return status(state, 'STOPPED', ['EXISTING_MANUAL_WORKER'])
    if (state.get('status') == 'WAITING_NEXT_SESSION' and state.get('schedule')
            and now < parsed(state['schedule']['prepare_at'])):
        return state
    info = backend.info()
    target = info['target_session']
    state['schedule'] = {k: info[k] for k in ('target_session', 'prepare_at', 'start_at', 'close_at')}
    if now < parsed(info['prepare_at']):
        return status(state, 'WAITING_NEXT_SESSION')
    day = state['days'].setdefault(target, {'run_id': 'daily-' + target.replace('-', ''), 'failures': 0})
    if day.get('done'):
        return status(state, 'STOPPED', ['DAILY_SESSION_ALREADY_FINISHED'])
    if now >= parsed(info['close_at']) - timedelta(minutes=15):
        return status(state, 'STOPPED', ['TOO_LATE_TO_START'])
    previous = info.get('last_runtime_started_at')
    if previous and parsed(previous).astimezone(NY).date().isoformat() == target:
        day['done'] = True
        return status(state, 'STOPPED', ['SESSION_ALREADY_RUN_TODAY'])
    if info['start_blockers']:
        return status(state, 'MISSING_INPUTS', info['start_blockers'])
    # Enrollment is the authority, including recovery after a receipt-write crash.
    day['receipt'] = info.get('receipt')
    if not day.get('receipt'):
        if info['automatic_catalog_blockers']:
            return status(state, 'MISSING_INPUTS', info['automatic_catalog_blockers'])
        if day['failures'] >= 3:
            return status(state, 'MISSING_INPUTS', ['PREPARATION_RETRY_LIMIT', day.get('last_error', '')])
        # Reserve before the action so crashes cannot reset the attempt allowance.
        day['failures'] += 1
        persist(state)
        if not day.get('degen_capture'):
            result = backend.invoke(['capture-session', '--target-session', target])
            day['degen_capture'] = result['evidence_directory']
        elif info['swing_history_enrolled'] and not day.get('swing_capture'):
            result = backend.invoke(['capture-session', '--target-session', info['swing_expiration']])
            day['swing_capture'] = result['evidence_directory']
        else:
            backend.prepare(day, info)
        day['failures'] -= 1  # Successful stages do not consume the failure allowance.
        return status(state, 'PREPARING')
    if info['swing_history_enrolled'] and not day.get('preopen_attempted') and now < parsed(info['open_at']):
        day['preopen_attempted'] = True
        persist(state)
        day['preopen'] = backend.preopen(target)
        return status(state, 'READY', [day['preopen']['status']])
    if now < parsed(info['start_at']):
        return status(state, 'READY', ['WAITING_FOR_SIX_COMPLETED_BARS'])
    if day.get('review_attempts', 0) >= 3:
        return status(state, 'MISSING_INPUTS', ['LAUNCH_REVIEW_RETRY_LIMIT'])
    day['review_attempts'] = day.get('review_attempts', 0) + 1
    persist(state)

    def before_run():
        day.update(launch_attempted=True, close_at=info['close_at'], image_id=backend.config['image_id'])
        persist(state)

    result = backend.launch(day, info, now, before_run)
    day['container_id'] = result['container_id']
    return status(state, 'RUNNING', ['WAITING_FOR_FIRST_REPORT'])


def units(root):
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(root)):
        raise ValueError('SYSTEMD_CHECKOUT_PATH_UNSUPPORTED')
    service = (MARKER + '[Unit]\nDescription=Trade-Bot daily PAPER controller\n'
               'After=docker.service network-online.target\nWants=network-online.target\n'
               '[Service]\nType=oneshot\nUser=root\nUMask=0077\n'
               f'WorkingDirectory={root}\nExecStart=/usr/bin/python3 {root}/scripts/paper-daily.py tick\n'
               'TimeoutStartSec=900\n')
    timer = (MARKER + '[Unit]\nDescription=Trade-Bot daily PAPER schedule\n'
             '[Timer]\nOnCalendar=*-*-* *:*:00\nPersistent=true\nAccuracySec=5s\n'
             '[Install]\nWantedBy=timers.target\n')
    return {UNIT + '.service': service, UNIT + '.timer': timer}


def install():
    # Reject foreign units before building or writing configuration.
    for name in units(ROOT):
        path = UNIT_HOME / name
        if path.is_symlink() or (path.exists() and not path.read_text().startswith(MARKER)):
            raise ValueError('EXISTING_UNMANAGED_SYSTEMD_UNIT')
    old = read(HOME / 'config.json')
    if host.h.command(['git', 'status', '--porcelain']).stdout:
        raise ValueError('CLEAN_RELEASE_CHECKOUT_REQUIRED')
    host.no_active_session()
    release = host.h.command(['git', 'rev-parse', 'HEAD']).stdout.strip()
    try:
        image_id = host.image(release)
    except (ValueError, RuntimeError):
        subprocess.run(['python3', str(ROOT / 'scripts/connected-session-host.py'), 'build'],
                       check=True, cwd=ROOT, timeout=960)
        image_id = host.image(release)
    config = {'version': 'paper-daily-v1', 'release': release, 'image_id': image_id,
              'max_feed_recoveries': 2}
    info = Backend(config).info()
    if 'DAILY_PROFILE_MISMATCH' in info['start_blockers']:
        raise ValueError('DAILY_PROFILE_MISMATCH')
    save(HOME / 'config.json', config)
    for name, body in units(ROOT).items():
        path = UNIT_HOME / name
        fd, temporary = tempfile.mkstemp(prefix='.paper-unit-', dir=UNIT_HOME)
        with os.fdopen(fd, 'w') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    subprocess.run(['systemctl', 'enable', '--now', UNIT + '.timer'], check=True, timeout=30)
    return {'status': 'DAILY_SCHEDULE_INSTALLED', 'paused': not Backend(config).enabled(),
            'schedule': {k: info[k] for k in ('target_session', 'prepare_at', 'start_at', 'close_at')},
            'release': release, 'image_id': image_id, 'updated': old is not None,
            'live_enabled': False, 'trading_ready': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('install', 'tick', 'status', 'pause', 'resume'))
    args = p.parse_args(argv)
    if os.geteuid() != 0:
        raise ValueError('ROOT_HOST_OPERATOR_REQUIRED')
    os.chdir(ROOT)
    os.umask(0o077)
    HOME.mkdir(mode=0o700, exist_ok=True)
    private(HOME, True)
    if args.operation == 'status':
        config = read(HOME / 'config.json')
        return {'config': config, 'paused': (HOME / 'paused.json').exists(),
                'operation': read(HOME / 'state.json', {'status': 'WAITING_FIRST_TICK' if config else 'NOT_INSTALLED'}),
                'observed_at': stamp().isoformat()}
    if args.operation == 'pause':
        save(HOME / 'paused.json', {'requested_at': stamp().isoformat()})
    lock_fd = os.open(HOME / 'controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        private(HOME / 'controller.lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'PAUSE_REQUESTED' if args.operation == 'pause' else 'CONTROLLER_BUSY'}
        if args.operation == 'install':
            return install()
        config = read(HOME / 'config.json')
        if not config:
            raise ValueError('SCHEDULE_NOT_INSTALLED')
        if args.operation == 'resume':
            backend = Backend(config)
            backend.verify()
            info = backend.info()
            if info['start_blockers'] or backend.active():
                raise ValueError('RESUME_REQUIRES_NORMALLY_STOPPED_FLAT_OWNER')
            state = read(HOME / 'state.json', {'version': 'paper-daily-state-v1'})
            for day in state.get('days', {}).values():
                if day.get('awaiting_container') and not day.get('done'):
                    if backend.container(day['run_id'], image_id=day.get('image_id')) is not None:
                        raise ValueError('RESUME_REQUIRES_SAVED_WORKER_REPORT')
                    day.update(done=True, awaiting_container=False)
            state.pop('attention', None)
            save(HOME / 'state.json', status(state, 'STOPPED', ['EXPLICIT_SCHEDULE_RESUME']))
            (HOME / 'paused.json').unlink(missing_ok=True)
            return {'status': 'SCHEDULE_RESUMED', 'automatic_failure_retry': False}
        state = read(HOME / 'state.json', {'version': 'paper-daily-state-v1'})
        persist = lambda value: save(HOME / 'state.json', value)
        backend = Backend(config)
        try:
            tick(state, backend, persist, stamp())
        except (ValueError, RuntimeError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            reason = str(exc) if type(exc) is ValueError and re.fullmatch('[A-Z_]+', str(exc)) else type(exc).__name__
            for day in state.get('days', {}).values():
                if not day.get('done'):
                    day['last_error'] = reason
            status(state, 'FAILED', [reason])
        finally:
            state['updated_at'] = stamp().isoformat()
            persist(state)
            # A pause arriving during a capture/review/launch takes effect before
            # releasing the controller lock, using the exact inspected identity.
            if not backend.enabled():
                for day in state.get('days', {}).values():
                    if day.get('launch_attempted') and not day.get('done'):
                        item = backend.container(day['run_id'], image_id=day.get('image_id'))
                        if item and item['State']['Status'] == 'running':
                            if day.get('container_id') and item['Id'] != day['container_id']:
                                raise ValueError('DAILY_CONTAINER_IDENTITY_CHANGED')
                            backend.stop(day['run_id'], item['Id'], image_id=day.get('image_id'))
        return {k: state[k] for k in ('status', 'reasons', 'updated_at', 'schedule', 'live_enabled', 'trading_ready') if k in state}


if __name__ == '__main__':
    try:
        print(json.dumps(main(), sort_keys=True))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'FAILED', 'reason': str(exc) if type(exc) is ValueError else type(exc).__name__,
                          'live_enabled': False}))
        raise SystemExit(2)
