"""Installed-file evidence and stored runtime attribution without observer work."""

import asyncio
import base64
import csv
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys

import pytest
from test_degen_options import AT, owned_strategy
from test_option_observer import app_for
from test_option_runtime import policy

from app.options import release_identity as identity
from app.options.observer import OptionObserver
from app.options.runtime import OptionRuntime


def installation(path):
    root = path / "site-packages"
    package = root / "app"
    metadata = root / "autonomous_compounding_trader-0.1.0.dist-info"
    package.mkdir(parents=True)
    metadata.mkdir()
    (package / "__init__.py").write_bytes(b'"""fixture"""\n')
    (package / "module.py").write_bytes(b"VALUE = 1\n")
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: autonomous-compounding-trader\nVersion: 0.1.0\n"
    )
    (metadata / "direct_url.json").write_text(
        json.dumps(
            {
                "url": "https://example.test/private?token=DO_NOT_PRINT",
                "archive_info": {"hashes": {"sha256": "a" * 64}},
            }
        )
    )
    records = []
    for p in sorted(package.iterdir()):
        raw = p.read_bytes()
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        records.append([str(p.relative_to(root)), "sha256=" + digest, str(len(raw))])
    save_record(metadata, records)
    return root, package, metadata, records


def save_record(metadata, rows):
    with (metadata / "RECORD").open("w", newline="") as stream:
        csv.writer(stream).writerows(rows)


def inspect(monkeypatch, package, metadata):
    monkeypatch.setattr(
        identity.importlib.metadata,
        "distribution",
        lambda _: importlib.metadata.PathDistribution(metadata),
    )
    monkeypatch.setattr(identity.app, "__file__", str(package / "__init__.py"))
    return identity.inspect_release(now=AT)


def test_installed_file_digest_is_reproducible_and_contains_no_private_url(tmp_path, monkeypatch):
    _, package, metadata, _ = installation(tmp_path)
    result = inspect(monkeypatch, package, metadata)
    assert result.status == "VERIFIED_FILES" and result.file_count == 2
    assert result.wheel_sha256 == "a" * 64 and result.package_version == "0.1.0"
    assert result.execution_authority is False and result.observed_at == AT
    assert result == identity.inspect_release(now=AT)
    assert (
        "DO_NOT_PRINT" not in result.model_dump_json()
        and str(tmp_path) not in result.model_dump_json()
    )
    # Interpreter caches do not change the source/template identity.
    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-312.pyc").write_bytes(b"fixture-cache")
    assert result == identity.inspect_release(now=AT)


@pytest.mark.parametrize(
    "damage,status,reason",
    [
        ("content", "MISMATCH", "APPLICATION_CONTENT_CHANGED"),
        ("extra", "MISMATCH", "APPLICATION_INVENTORY_CHANGED"),
        ("missing", "MISMATCH", "APPLICATION_INVENTORY_CHANGED"),
        ("unhashed", "UNAVAILABLE", "INSTALLATION_HASH_UNAVAILABLE"),
        ("editable", "UNAVAILABLE", "EDITABLE_INSTALLATION"),
        ("symlink", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
        ("fifo", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
        ("oversize", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
        ("record_oversize", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
        ("duplicate", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
        ("traversal", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
        ("wrong_package", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
        ("bad_origin", "UNAVAILABLE", "INSTALLATION_INSPECTION_FAILED"),
    ],
)
def test_damaged_or_unverifiable_installations_never_get_a_verified_digest(
    tmp_path, monkeypatch, damage, status, reason
):
    root, package, metadata, rows = installation(tmp_path)
    target = package / "module.py"
    if damage == "content":
        target.write_bytes(b"VALUE = 2\n")
    elif damage == "extra":
        (package / "unrecorded.py").write_bytes(b"extra")
    elif damage == "missing":
        target.unlink()
    elif damage == "unhashed":
        rows[-1][1] = ""
        save_record(metadata, rows)
    elif damage == "editable":
        (metadata / "direct_url.json").write_text('{"dir_info":{"editable":true}}')
    elif damage in {"symlink", "fifo"}:
        target.unlink()
        if damage == "symlink":
            target.symlink_to(package / "__init__.py")
        else:
            os.mkfifo(target)
    elif damage == "oversize":
        target.write_bytes(b"x" * (1024 * 1024 + 1))
    elif damage == "record_oversize":
        (metadata / "RECORD").write_bytes(b"x" * (256 * 1024 + 1))
    elif damage == "duplicate":
        save_record(metadata, rows + [rows[0]])
    elif damage == "traversal":
        save_record(metadata, rows + [["app/../secret", "sha256=fake", "1"]])
    elif damage == "wrong_package":
        (metadata / "METADATA").write_text("Name: unrelated\nVersion: 0.1.0\n")
    else:
        (metadata / "direct_url.json").write_text("[]")
    result = inspect(monkeypatch, package, metadata)
    assert result.status == status and result.reason == reason
    assert result.application_sha256 is result.wheel_sha256 is None and result.file_count == 0
    assert str(root) not in result.model_dump_json()


def test_source_import_cannot_report_an_unrelated_installed_release(tmp_path, monkeypatch):
    root, _, metadata, _ = installation(tmp_path)
    result = inspect(monkeypatch, root / "checkout/app", metadata)
    assert result.status == "UNAVAILABLE" and result.reason == "IMPORT_OUTSIDE_INSTALLED_PACKAGE"


def test_install_without_installer_archive_pin_still_has_exact_application_identity(
    tmp_path, monkeypatch
):
    _, package, metadata, _ = installation(tmp_path)
    (metadata / "direct_url.json").unlink()
    result = inspect(monkeypatch, package, metadata)
    assert result.status == "VERIFIED_FILES" and result.wheel_sha256 is None


def test_file_inventory_bound(tmp_path, monkeypatch):
    _, package, metadata, rows = installation(tmp_path)
    save_record(
        metadata,
        rows + [[f"app/extra{i}.py", "sha256=fake", "1"] for i in range(identity.MAX_FILES)],
    )
    result = inspect(monkeypatch, package, metadata)
    assert result.status == "UNAVAILABLE" and result.reason == "INSTALLATION_INSPECTION_FAILED"


def test_runtime_retains_its_own_release_and_observer_never_inspects_its_installation(
    tmp_path, monkeypatch
):
    with owned_strategy(tmp_path) as (c, venue, *_):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        stop = asyncio.Event()
        stop.set()
        asyncio.run(r.run(stop))
        with c.engine.journal.read() as db:
            recorded = identity.stored_release(db, 1)
        assert recorded["status"] == "VERIFIED_FILES"
        assert recorded["application_sha256"] == identity.inspect_release(now=AT).application_sha256

        def forbidden(**kwargs):
            raise AssertionError("Observer must not inspect its own package")

        monkeypatch.setattr(identity, "inspect_release", forbidden)
        observer = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        )
        before = observer.report()
        assert before["release"] == recorded and before["runtime"]["generation"] == 1
        client, _ = app_for(c, tmp_path)
        with client:
            page = client.get("/")
        assert recorded["application_sha256"] in page.text and "not process liveness" in page.text
        assert observer.report()["revision"] == before["revision"] and venue.submit_count == 0


def test_new_start_records_new_identity_without_relabeling_old_event(tmp_path, monkeypatch):
    with owned_strategy(tmp_path) as (c, _, *_):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        first = identity.inspect_release(now=AT)
        monkeypatch.setattr(identity, "inspect_release", lambda **kw: first)
        stop = asyncio.Event()
        stop.set()
        asyncio.run(r.run(stop))
        second = first.model_copy(update={"application_sha256": "b" * 64})
        monkeypatch.setattr(identity, "inspect_release", lambda **kw: second)
        asyncio.run(r.run(stop))
        with c.engine.journal.read() as db:
            rows = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM execution_events WHERE kind='OPTION_RUNTIME_STARTED' ORDER BY sequence"
                )
            ]
            assert identity.stored_release(db, 2)["application_sha256"] == "b" * 64
        assert rows[0]["release"] == first.model_dump(mode="json") and rows[0]["generation"] == 1
        assert rows[1]["release"] == second.model_dump(mode="json") and rows[1]["generation"] == 2


def test_legacy_start_has_unknown_release_and_wrong_generation_is_rejected(tmp_path):
    with owned_strategy(tmp_path) as (c, _, *_), c.engine.journal.write() as db:
        assert identity.stored_release(db, 0) is None
        c.engine.journal.event(db, AT, "OPTION_RUNTIME_STARTED", {})
        assert identity.stored_release(db, 1) is None
        c.engine.journal.event(
            db,
            AT,
            "OPTION_RUNTIME_STARTED",
            {
                "generation": 2,
                "release": identity.inspect_release(now=AT).model_dump(mode="json"),
            },
        )
        with pytest.raises(ValueError, match="different runtime generation"):
            identity.stored_release(db, 1)


def test_unavailable_release_is_visible_but_cannot_change_execution_authority(
    tmp_path, monkeypatch
):
    with owned_strategy(tmp_path) as (c, venue, *_):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        unavailable = identity.InstalledRelease(
            status="UNAVAILABLE",
            observed_at=AT,
            python_version="3.12.14",
            reason="PACKAGE_NOT_INSTALLED",
        )
        monkeypatch.setattr(identity, "inspect_release", lambda **kw: unavailable)
        stop = asyncio.Event()
        stop.set()
        asyncio.run(r.run(stop))
        report = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
        assert (
            report["release"]["status"] == "UNAVAILABLE"
            and not report["release"]["execution_authority"]
        )
        assert report["entry"]["halted"] and venue.submit_count == 0


def test_installed_cli_identifies_package_without_population_or_credentials():
    result = subprocess.run(
        [sys.executable, "-I", "-m", "app.options.runtime_cli", "release"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "VERIFIED_FILES" and report["execution_authority"] is False
    assert report["application_sha256"] == identity.inspect_release().application_sha256


def test_release_cli_reports_unavailable_with_nonzero_exit(monkeypatch, capsys):
    from app.options.runtime_cli import main

    unavailable = identity.InstalledRelease(
        status="UNAVAILABLE",
        observed_at=AT,
        python_version="3.12.14",
        reason="PACKAGE_NOT_INSTALLED",
    )
    monkeypatch.setattr(identity, "inspect_release", lambda: unavailable)
    assert main(["release"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("damage", ["root_shape", "boolean_generation", "authority"])
def test_invalid_stored_release_cannot_be_reported_as_current(tmp_path, damage):
    with owned_strategy(tmp_path) as (c, _, *_), c.engine.journal.write() as db:
        release = identity.InstalledRelease(
            status="UNAVAILABLE",
            observed_at=AT,
            python_version="3.12.14",
            reason="PACKAGE_NOT_INSTALLED",
        ).model_dump(mode="json")
        payload = {"generation": 1, "release": release}
        if damage == "root_shape":
            payload = []
        elif damage == "boolean_generation":
            payload["generation"] = True
        else:
            release["execution_authority"] = True
        c.engine.journal.event(db, AT, "OPTION_RUNTIME_STARTED", payload)
        with pytest.raises((ValueError, TypeError)):
            identity.stored_release(db, 1)


def test_unexpected_inspection_failure_still_cleans_up_runtime(tmp_path, monkeypatch):
    with owned_strategy(tmp_path) as (c, venue, *_):
        r = OptionRuntime(c, policy(tmp_path), create=True)

        def failed(**kwargs):
            raise RuntimeError("fixture inspection failure")

        monkeypatch.setattr(identity, "inspect_release", failed)
        with pytest.raises(RuntimeError, match="fixture inspection"):
            asyncio.run(r.run(asyncio.Event()))
        assert r.running is False and r.task is None and venue.submit_count == 0
        report = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
        assert report["runtime"]["status"] == "FAILED" and report["entry"]["halted"]
        assert report["release"] is None
