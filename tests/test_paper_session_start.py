import importlib.util
import json
import subprocess
from pathlib import Path
import pytest


def loader():
    p = Path(__file__).parents[1] / "scripts/paper-session-start.py"
    spec = importlib.util.spec_from_file_location("paper_start_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def helper(calls, *, ready=True):
    def invoke(args):
        calls.append(args)
        return {"status": "SESSION_ROLLOVER_ENROLLED" if args[0] == 'enroll-session' else 'OK',
                "review_sha256": args[0] + "-hash", "degen_option_configuration_ready": ready,
                "binding": {"policy_sha256": 'a' * 64, "proposed_sha256": 'a' * 64},
                "live_enabled": False}
    return invoke


def test_exact_reviews_flow_to_enrollment_snapshot_and_run(tmp_path):
    calls = []
    m = loader()
    m.launch("/captures", "2026-10-28", "paper-first", 600,
             invoke=helper(calls), session_root=tmp_path, today="2026-10-28")
    assert [c[0] for c in calls] == ["prepare-session", "review-session", "enroll-session", "snapshot", "review-run", "run"]
    assert calls[2][-1] == "review-session-hash"
    assert calls[-1][-1] == "review-run-hash"
    assert "--resume-flat" in calls[-1]
    with pytest.raises(FileExistsError):
        m.launch("/captures", "2026-10-28", "paper-first", 600,
                 invoke=helper(calls), session_root=tmp_path, today="2026-10-28")


def test_future_combined_prepare_and_next_day_start_do_not_reenroll(tmp_path):
    calls = []
    m = loader()
    result = m.launch('/captures', '2026-11-02', 'monday', 600, invoke=helper(calls),
                      session_root=tmp_path, today='2026-10-31', prepare_only=True,
                      observed_swing_history=True, swing_capture_directory='/swing',
                      scope_binding='/scope.json', earnings_probe='/earnings.json')
    assert [c[0] for c in calls] == ['prepare-session', 'review-session', 'enroll-session', 'snapshot']
    assert '--observed-swing-history' in calls[0] and '/swing' in calls[0] and '/scope.json' in calls[0]
    assert result['workers_started'] is False
    calls.clear()
    m.launch(None, None, 'monday-run', 600, invoke=helper(calls), session_root=tmp_path,
             today='2026-11-02', prepared_session=result['prepared_session'])
    assert [c[0] for c in calls] == ['snapshot', 'review-run', 'run']


@pytest.mark.parametrize('change', ['date', 'policy', 'live', 'ready'])
def test_prepared_start_refuses_wrong_date_policy_live_or_blocked(tmp_path, change):
    calls = []
    m = loader()
    receipt = {'target_session': '2026-11-02', 'policy_sha256': 'a' * 64}
    def invoke(args):
        result = helper(calls)(args)
        if change == 'policy': result['binding']['policy_sha256'] = 'b' * 64
        if change == 'live': result['live_enabled'] = True
        if change == 'ready': result['degen_option_configuration_ready'] = False
        return result
    with pytest.raises(ValueError):
        m.run_prepared(receipt, 'monday', 600, invoke=invoke,
                       today='2026-11-03' if change == 'date' else '2026-11-02')
    assert 'run' not in [c[0] for c in calls]


def test_snapshot_failure_retains_prepared_receipt_for_retry(tmp_path):
    m = loader()
    def invoke(args):
        if args[0] == 'snapshot': raise m.StepFailed('snapshot')
        return helper([])(args)
    with pytest.raises(m.StepFailed):
        m.launch('/captures', '2026-11-02', 'monday', 600, invoke=invoke,
                 session_root=tmp_path, today='2026-10-31', prepare_only=True)
    assert json.loads((tmp_path / '2026-11-02-monday/prepared.json').read_text())['policy_sha256'] == 'a' * 64


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_failed_subprocess_reports_structured_error_without_traceback(capsys, stream):
    m = loader()
    def runner(*args, **kwargs):
        assert kwargs['check'] is False
        message = json.dumps({'status': 'UNAVAILABLE', 'reason': 'Session name already exists', 'live_enabled': False})
        return subprocess.CompletedProcess(args, 2, message if stream == 'stdout' else '',
                                           message if stream == 'stderr' else 'PRIVATE_TRACEBACK')
    with pytest.raises(m.StepFailed, match='review-run'):
        m.invoke_host(Path('/repo'), ['review-run'], runner=runner)
    out = capsys.readouterr().out
    assert 'Session name already exists' in out and 'PRIVATE_TRACEBACK' not in out


def test_catalog_report_without_status_is_accepted():
    m = loader()
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, '{"version":"intraday-simulation-catalog-v1","live_enabled":false}', '')
    assert m.invoke_host(Path('/repo'), ['prepare-session'], runner=runner)['live_enabled'] is False


def test_existing_run_refused_before_preparation():
    m = loader()
    def runner(args, **kwargs):
        assert args[1:4] == ['container', 'ls', '-a']
        return subprocess.CompletedProcess(args, 0, 'trade-bot-connected-used\n', '')
    with pytest.raises(ValueError, match='already exists'):
        m.unused_run_id('used', runner=runner)


@pytest.mark.parametrize('exit_code', ['0', '2'])
def test_wait_reports_even_failed_runtime_and_does_not_restart(exit_code, capsys):
    m = loader()
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        out = exit_code if args[0] == 'docker' else '{"status":"SAVED_SESSION_REPORT","account_total_fills":0}'
        return subprocess.CompletedProcess(args, 0, out, '')
    if exit_code == '2':
        with pytest.raises(m.StepFailed, match='stopped with an error'):
            m.wait_report(Path('/repo'), 'paper-first', 600, runner=runner)
    else:
        m.wait_report(Path('/repo'), 'paper-first', 600, runner=runner)
    assert len(calls) == 2 and calls[0][1] == 'wait'
    assert 'SAVED_SESSION_REPORT' in capsys.readouterr().out
