#!/usr/bin/env python3
"""Run installed-package, credential-free integrated PAPER fixtures off-market."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SUITES = ('connected_system', 'feed_timing', 'runtime_timing', 'option_read_capture', 'connected_runtime',
          'connected_feed_recovery', 'connected_cycle_handoff', 'connected_publisher',
          'dashboard_reader', 'paper_session_report', 'paper_daily', 'mixed_runtime',
          'option_runtime', 'portfolio_models', 'session_host', 'dashboard_snapshot',
          'protection_contention', 'swing_feed', 'swing_binding', 'portfolio_feed',
          'combined_session_feed')


def run(output):
    import app

    if not sys.flags.isolated:
        raise ValueError('Run this script with the installed interpreter and -I')
    installed = Path(app.__file__).resolve().parent
    if installed.is_relative_to(ROOT):
        raise ValueError('A noneditable installed package is required')
    sources = [p for p in (ROOT / 'app').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    manifest = {}
    for source in sources:
        name = source.relative_to(ROOT / 'app')
        original = source.read_bytes()
        if original != (installed / name).read_bytes():
            raise ValueError('Source and installed application differ')
        manifest[str(name)] = hashlib.sha256(original).hexdigest()
    pins = [line.split('==') for line in (ROOT / 'requirements-runtime.lock').read_text().splitlines()
            if line and not line.startswith('#')]
    if not all(importlib.metadata.version(name) == version for name, version in pins):
        raise ValueError('Runtime pins differ')
    if not output.is_absolute() or output.resolve().is_relative_to(ROOT):
        raise ValueError('Choose a new absolute output directory outside the checkout')
    output.mkdir(mode=0o700)  # Never adopt connected state or overwrite old proof.
    result = {'version': 'paper-system-check-v1', 'status': 'RUNNING',
              'synthetic': True, 'provider_calls': False, 'model_service_calls': False,
              'live_enabled': False, 'market_acceptance': 'UNVERIFIED',
              'wall_clock_soak': 'NOT_RUN', 'host_acceptance': 'UNVERIFIED',
              'application_files': len(manifest), 'runtime_pins': len(pins),
              'application_manifest_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
    summary = output / 'summary.json'
    summary.write_text(json.dumps(result, indent=2)+'\n')
    for name in ('tests', 'scripts', 'examples'):
        shutil.copytree(ROOT / name, output / 'stage' / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    health = output / 'stage/app/mixed'
    health.mkdir(parents=True)
    shutil.copy(ROOT / 'app/mixed/paper_health.py', health / 'paper_health.py')
    args = ['-q', '-p', 'anyio.pytest_plugin', '--tb=short', '-c', '/dev/null',
            '--basetemp='+str(output/'state'), '--junitxml='+str(output/'tests.xml'),
            *[str(output/'stage/tests'/('test_'+name+'.py')) for name in SUITES]]
    bootstrap = ('import sys,pytest;sys.path[:0]='
                 +repr([str(output/'stage'),str(output/'stage/tests')])
                 +';raise SystemExit(pytest.main('+repr(args)+'))')
    env = {k: os.environ[k] for k in ('PATH','LANG','LC_ALL') if k in os.environ}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', TRADE_BOT_OFFLINE_PROOF=str(output))
    child = None
    try:
        with (output/'tests.log').open('w') as log:
            child = subprocess.Popen([sys.executable, '-I', '-W', 'error', '-c', bootstrap],
                cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            code = child.wait(timeout=1800)
        result['status'] = 'PASSED' if code == 0 else 'FAILED'
        result['test_exit_code'] = code
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        result['status'] = 'FAILED'
        result['reason'] = 'TEST_RUNNER_TIMEOUT' if isinstance(exc, subprocess.TimeoutExpired) else 'TEST_RUNNER_INTERRUPTED'
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
        summary.write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.output)
    except (OSError, ValueError) as exc:
        print(json.dumps({'status':'UNAVAILABLE', 'reason':str(exc), 'live_enabled':False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
