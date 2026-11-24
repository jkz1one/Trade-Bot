import importlib.util
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "paper_soak", Path(__file__).resolve().parents[1] / "scripts/paper-soak.py"
)
soak = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(soak)


@pytest.mark.parametrize('field,message', [('native', 'Native acceptance failure'),
                                         ('runtime', 'Runtime failure'),
                                         ('publication', 'Publication failure')])
def test_soak_stops_on_recorded_failure_without_waiting_for_duration(field, message):
    from soak_worker import reject_recorded_failure
    report = {'runtime_timing': {'by_status': {}}, 'runtime_failures': [],
              'publication_failures': []}
    reject_recorded_failure(report)  # Missing fills alone are not a terminal failure.
    if field == 'native':
        report['runtime_timing']['by_status']['NATIVE_ACCEPT:FAILED'] = 1
    else:
        report[field + '_failures'] = [{'error_class': 'TimeoutError'}]
    with pytest.raises(AssertionError, match=message):
        reject_recorded_failure(report)


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(soak, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True)))


@pytest.mark.parametrize("seconds", [0, 59, 23401, True, 75.5])
def test_reject_invalid_duration_before_creating_state(isolated, tmp_path, seconds):
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="DURATION"):
        soak.run(output, seconds, 68)
    assert not output.exists()


def test_reject_existing_account_without_modification(isolated, tmp_path):
    evidence = tmp_path / "existing.db"
    evidence.write_bytes(b"retain")
    with pytest.raises(ValueError, match="EXISTING_OUTPUT"):
        soak.run(tmp_path, 75, 68)
    assert evidence.read_bytes() == b"retain"
    assert list(tmp_path.iterdir()) == [evidence]


def test_reject_symlink_and_checkout_output(isolated, tmp_path):
    output = tmp_path / "alias"
    output.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError, match="OUTPUT"):
        soak.run(output, 75, 68)
    with pytest.raises(ValueError, match="OUTSIDE_CHECKOUT"):
        soak.run(soak.ROOT / "new", 75, 68)


def test_reject_network_before_import_or_state_creation(isolated, tmp_path, monkeypatch):
    original = Path.read_text

    def read(path, *args, **kwargs):
        if str(path) == "/proc/net/dev":
            return "header\nheader\n lo: 0\n eth0: 0\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="NETWORK_NAMESPACE"):
        soak.run(output, 75, 68)
    assert not output.exists()


def test_reject_mismatched_proc_before_import_or_state_creation(isolated, tmp_path, monkeypatch):
    original = Path.read_text

    def read(path, *args, **kwargs):
        if str(path) == "/proc/net/dev":
            return "header\nheader\n lo: 0\n"
        if str(path) == "/proc/self/stat":
            return str(soak.os.getpid() + 1) + " (python) R 0"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="PID_NAMESPACE_REQUIRES_MATCHING_PROC_MOUNT"):
        soak.run(output, 75, 68)
    assert not output.exists()


def test_cgroup_memory_distinguishes_process_memory_from_file_and_tmpfs_charges(tmp_path):
    from soak_memory import cgroup_memory

    for name, value in {'current': '900', 'peak': '1024', 'max': '1073741824',
                        'events': 'oom 1\noom_kill 1\nunknown 99\n',
                        'stat': 'anon 600\nfile 250\nshmem 200\nslab 50\nunknown 0\n'}.items():
        (tmp_path / ('memory.' + name)).write_text(value)
    result = cgroup_memory(tmp_path)
    assert result['current_bytes'] == 900 and result['peak_bytes'] == 1024
    assert result['max_bytes'] == 1073741824
    assert result['events'] == {'oom': 1, 'oom_kill': 1}
    assert result['stat'] == {'anon': 600, 'file': 250, 'shmem': 200, 'slab': 50}
    (tmp_path / 'memory.max').write_text('max')
    assert cgroup_memory(tmp_path)['max_bytes'] is None
    (tmp_path / 'memory.events').write_text('oom_kill -1')
    assert cgroup_memory(tmp_path) == {'status': 'UNAVAILABLE'}
    assert cgroup_memory(tmp_path / 'absent') == {'status': 'UNAVAILABLE'}


@pytest.mark.parametrize("cpus", [0, 2, 3, True])
def test_cpu_comparison_cannot_expand_available_affinity(cpus, tmp_path, monkeypatch):
    monkeypatch.setattr(soak, "validate", lambda *_: {})
    monkeypatch.setattr(soak.os, "sched_getaffinity", lambda _: {7})
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="CPU_AFFINITY"):
        soak.run(output, 90, 68, cpus=cpus)
    assert not output.exists()


@pytest.mark.parametrize("cpus, percent", [(1, 60.0), (2, 30.0)])
def test_cpu_window_includes_reaped_child_and_excludes_setup(cpus, percent):
    from soak_worker import cpu_window

    result = cpu_window((100, 25, 20, 11, 5), (110, 28, 20.5, 13, 5.5), cpus)
    assert result == {
        "elapsed_seconds": 10, "worker_user_seconds": 3, "worker_system_seconds": .5,
        "reaped_child_user_seconds": 2, "reaped_child_system_seconds": .5,
        "average_busy_cores": .6, "average_allocated_cpu_percent": percent,
    }


def test_capacity_seed_uses_distinct_history_and_preserves_restore_verification(tmp_path):
    from soak_worker import seed_capacity
    from test_option_execution import NOW, owned

    with owned(tmp_path) as (engine, _, _):
        engine.journal.enable_restore_fence(now=NOW)
        with engine.journal.write() as db:
            db.execute("CREATE TABLE execution_runtime_timings("
                       "id INTEGER PRIMARY KEY,started_at TEXT,payload_json TEXT)")
        count = seed_capacity(engine.journal, 1)
        with engine.journal.read(verify_restore=True) as db:
            rows = db.execute("SELECT payload_json FROM execution_runtime_timings").fetchall()
        assert len(rows) == count > 200
        assert len({row[0] for row in rows}) == count
        assert sum(len(row[0].encode()) for row in rows) >= 1024**2
        assert all(json.loads(row[0])["version"] == "synthetic-capacity-padding-v2" for row in rows)


@pytest.mark.parametrize("allowance", [-1, 4, True, 1.5])
def test_invalid_recovery_allowance_leaves_output_absent(tmp_path, monkeypatch, allowance):
    monkeypatch.setattr(soak, "validate", lambda *_: {})
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="FEED_RECOVERY_ALLOWANCE"):
        soak.run(output, 90, 68, max_feed_recoveries=allowance)
    assert not output.exists()


def test_scan_coverage_needs_both_original_evaluations_in_the_expected_slot():
    from soak_worker import BASE, decision_coverage

    def scan(symbol, at):
        return {"version": "degen-completed-bars-v1", "symbol": symbol, "evaluated_at": at.isoformat()}

    first = int(BASE.timestamp()) // 300
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE execution_option_runtime_slots(slot,status)")
        db.execute("CREATE TABLE execution_option_opportunities(cycle_key,started_at,status,result_json)")
        for i in range(6):
            at = BASE + timedelta(minutes=5 * i)
            if i == 3:
                continue
            db.execute("INSERT INTO execution_option_runtime_slots VALUES(?,?)",
                       (first+i, "SKIPPED" if i == 2 else "COMPLETE"))
            values = [scan("SPY", at), scan("QQQ", BASE if i == 1 else at)]
            db.execute("INSERT INTO execution_option_opportunities VALUES(?,?,?,?)",
                       (f"degen:{first+i}:portfolio:0", at.isoformat(), "COMPLETE",
                        "damaged" if i == 4 else json.dumps({"status": "HOLD", "scans": values})))
        result = decision_coverage(db, BASE, 1500)
        assert (result["expected"], result["evaluated"], result["coverage_percent"]) == (5, 1, 20)
        assert [row["runtime_status"] for row in result["unmeasured_slots"]] == [
            "COMPLETE", "SKIPPED", "MISSING", "COMPLETE"]
        assert not result["target_met"]
        assert decision_coverage(db, BASE, 300)["target_met"]


def test_opening_restore_profile_clips_overlaps_and_counts_only_whole_call_cpu():
    from soak_restore_profile import OpeningRestoreProfile

    profile = OpeningRestoreProfile(None, [0])
    profile.spans = [(1, 3, .6, True, "earlier"), (3, 5, 1.5, True, "tick"),
                     (4, 5, .3, False, "reader"), (5.5, 8, 1., True, "later")]
    assert profile.window(2, 6) == {
        "window_seconds": 4, "wall_seconds_with_digest_running": 3.5,
        "wholly_contained_calls": 2, "owner_thread_cpu_seconds": 1.5,
        "background_cpu_seconds": .3, "owner_thread_calls": {"tick": 1},
    }


def test_opening_restore_profile_refuses_unverified_and_truncated_windows():
    from soak_worker import BASE
    from soak_restore_profile import OpeningRestoreProfile

    profile = OpeningRestoreProfile(BASE, [10.])
    assert profile.report(None, {"status": "PARTIAL"})["status"] == "UNMEASURED"
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE execution_events(kind,client_id,occurred_at,sequence)")
        db.execute("CREATE TABLE execution_portfolio_orders(client_id,play_id,approval_json)")
        quote = {"source_at": BASE.isoformat(), "received_at": (BASE + timedelta(seconds=1)).isoformat()}
        db.execute("INSERT INTO execution_portfolio_orders VALUES('op','op',?)",
                   (json.dumps({"inputs": {"quote": quote}}),))
        db.execute("INSERT INTO execution_events VALUES('PORTFOLIO_RESERVED','op',?,1)",
                   ((BASE + timedelta(seconds=4)).isoformat(),))
        profile.first_omitted = 13.
        assert profile.report(db, {"status": "OBSERVED"})["reason"] == "OPENING_OUTSIDE_PROFILE"
        profile.first_omitted = 15.
        result = profile.report(db, {"status": "OBSERVED"})
        assert result["status"] == "OBSERVED"
        assert result["source_to_reservation"]["window_seconds"] == 4
        assert result["receipt_to_reservation"]["window_seconds"] == 3
