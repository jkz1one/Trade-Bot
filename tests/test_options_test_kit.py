"""The offline test entry point must never turn incomplete verification into a pass."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "options_test_kit", Path(__file__).resolve().parents[1] / "scripts/options-test-kit.py"
)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


@pytest.mark.parametrize(
    "body",
    [
        "<testsuites/>",
        '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>',
        '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0"/></testsuites>',
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="1"/></testsuites>',
    ],
)
def test_missing_empty_failed_or_skipped_summary_is_not_success(tmp_path, body):
    path = tmp_path / "result.xml"
    path.write_text(body)
    with pytest.raises(ValueError):
        kit.counts(path)


def test_existing_result_is_never_adopted_or_overwritten(tmp_path):
    marker = tmp_path / "report.json"
    marker.write_text("original")
    with pytest.raises(FileExistsError):
        kit.run(tmp_path, "a" * 64)
    assert marker.read_text() == "original"


def test_wrong_installed_build_stops_before_fixture_work(tmp_path, monkeypatch):
    monkeypatch.setattr(
        kit,
        "release",
        lambda *_: {
            "application_sha256": "0" * 64,
            "wheel_sha256": "a" * 64,
        },
    )
    output = tmp_path / "new"
    assert kit.run(output, "a" * 64) == 2
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "FAILED" and report["phases"] == {}
    assert not (output / "tests").exists()
    assert "PASSED_OFFLINE_FIXTURES" not in (output / "index.html").read_text()


def test_zero_exit_without_completed_summary_retains_failed_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(
        kit,
        "release",
        lambda *_: {
            "application_sha256": kit.application_digest(kit.application_manifest(kit.ROOT)),
            "wheel_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(kit, "command", lambda *a, **kw: 0)
    output = tmp_path / "new"
    assert kit.run(output, "a" * 64) == 2
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "FAILED"
    assert report["phases"]["runtime-recovery"]["status"] == "FAILED"
    assert report["visual_acceptance"] == report["host_acceptance"] == "PENDING"
    assert report["execution_authority"] is False


def test_isolated_copied_tests_load_package_imports_and_required_plugin(tmp_path):
    copied = tmp_path / "tests"
    copied.mkdir()
    for path in (kit.ROOT / "tests").glob("*.py"):
        (copied / path.name).write_bytes(path.read_bytes())
    result = kit.run_tests(
        tmp_path,
        "native-imports",
        [
            "test_option_runtime.py::test_runtime_html_reads_only_stored_state",
            "test_option_operator.py::test_observer_html_reads_capability_without_signing_key_access",
        ],
    )
    assert result == {"tests": 2, "failures": 0, "errors": 0, "skipped": 0}


def review_inputs(path):
    dashboard = path / "dashboard"
    dashboard.mkdir()
    for name in kit.STATES:
        for suffix in ("", "-desktop", "-mobile"):
            (dashboard / (name + suffix + ".html")).write_text("<!doctype html><p>fixture</p>")
    return {
        "status": "PASSED_OFFLINE_FIXTURES",
        "dashboard": "GENERATED",
        "phases": {
            name: {"status": "PASSED", "tests": 1, "failures": 0, "errors": 0, "skipped": 0}
            for name in kit.PHASES
        },
        "release": {"application_sha256": "a" * 64, "wheel_sha256": "b" * 64},
        "harness_sha256": "c" * 64,
        "private_extra": "not-for-export",
    }


def test_portable_review_exports_only_fixed_pages_and_limited_evidence(tmp_path):
    import zipfile

    report = review_inputs(tmp_path)
    (tmp_path / "secret.key").write_text("not-for-export")
    (tmp_path / "dashboard" / "private.db").write_text("not-for-export")
    archive = kit.package_review(tmp_path, report)
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist()) == 27 and z.testzip() is None
        assert not any(name.endswith((".db", ".key", ".log")) for name in z.namelist())
        assert not any(b"not-for-export" in z.read(name) for name in z.namelist())
        evidence = json.loads(z.read("evidence.json"))
        assert evidence["visual_acceptance"] == "PENDING"
        assert evidence["execution_authority"] is False and evidence["live_enabled"] is False
        for name, expected in evidence["page_sha256"].items():
            assert kit.digest(z.read(name)) == expected
    before = archive.read_bytes()
    with pytest.raises(FileExistsError):
        kit.package_review(tmp_path, report)
    assert archive.read_bytes() == before


@pytest.mark.parametrize("damage", ["running", "failed_phase", "skip", "missing", "symlink"])
def test_incomplete_review_cannot_be_exported(tmp_path, damage):
    report = review_inputs(tmp_path)
    page = tmp_path / "dashboard" / "populated.html"
    if damage == "running":
        report["status"] = "RUNNING"
    elif damage == "failed_phase":
        report["phases"]["accounting"]["status"] = "FAILED"
    elif damage == "skip":
        report["phases"]["accounting"]["skipped"] = 1
    else:
        page.unlink()
        if damage == "symlink":
            page.symlink_to(tmp_path / "dashboard" / "empty.html")
    with pytest.raises(ValueError):
        kit.package_review(tmp_path, report)
    assert not (tmp_path / "Trade-Bot-UI-Review.zip").exists()
