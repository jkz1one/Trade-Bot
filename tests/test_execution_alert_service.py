"""Independent sender composition; all network evidence uses a local TLS fixture."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.execution import alert_cli, alerts
from app.execution.alerts import (
    AlertAlreadyRunning,
    AlertDelivery,
    AlertLimits,
    alert_delivery_lease,
)
from app.execution.control_cli import control_lease
from app.execution.engine import ExecutionEngine
from app.execution.runtime import runtime_lease
from app.execution.runtime_cli import initialize
from tests.test_execution_alert_delivery import TOKEN, emit, setup
from tests.test_execution_alert_delivery import certificate as certificate
from tests.test_execution_alert_delivery import sink as sink
from tests.test_execution_rehearsal import NOW, decision, packet


def pair(engine):
    path = engine.journal.path
    return path.read_bytes(), Path(str(path) + ".authority.db").read_bytes()


def attached(c):
    return AlertDelivery.attach_existing(
        ExecutionEngine.attach_existing(c.engine.journal.path), clock=lambda: c.clock[0]
    )


@pytest.mark.parametrize("status", ["PREPARED", "SUBMITTING", "UNKNOWN"])
def test_attachment_and_report_preserve_trading_state_and_pair(tmp_path, sink, status):
    c = setup(tmp_path, sink)
    c.engine.prepare("pending", decision(), packet(), now=NOW)
    with c.engine.journal.write() as db:
        db.execute("UPDATE execution_orders SET status=?", (status,))
        c.engine._halt(db, "RETAINED_HALT", NOW)
    before = pair(c.engine)
    c.token.unlink()  # Reporting does not need to read the sink credential.
    report = attached(c).report()
    assert report["restore_fence"]["status"] == "VERIFIED"
    assert pair(c.engine) == before and not sink.calls
    engine = c.engine.journal.report(now=NOW)
    assert engine["halted"] and engine["orders"][0]["status"] == status


@pytest.mark.parametrize(
    "fault", ["missing", "attempts", "oversized", "origin", "binding", "extra"]
)
def test_attachment_rejects_missing_or_changed_enrollment_without_repair(tmp_path, sink, fault):
    c = setup(tmp_path, sink)
    with c.engine.journal.write() as db:
        if fault == "missing":
            db.execute("DROP TABLE execution_alert_delivery")
        elif fault == "attempts":
            db.execute("DROP TABLE execution_alert_attempts")
        elif fault == "oversized":
            db.execute("UPDATE execution_alert_delivery SET policy_json=?", ("x" * 16385,))
        else:
            policy = json.loads(
                db.execute("SELECT policy_json FROM execution_alert_delivery").fetchone()[0]
            )
            if fault == "origin":
                policy["origin"] = "http://127.0.0.1"
            elif fault == "binding":
                policy["journal_id"] = "foreign"
            else:
                policy["extra"] = "unrecognized"
            db.execute(
                "UPDATE execution_alert_delivery SET policy_json=?",
                (json.dumps(policy, sort_keys=True),),
            )
    before = pair(c.engine)
    with pytest.raises(ValueError):
        attached(c)
    assert pair(c.engine) == before and not sink.calls


def test_attachment_rejects_replaced_ca_and_lost_authority(tmp_path, sink):
    c = setup(tmp_path, sink)
    ca = tmp_path / "local.pem"
    ca.write_bytes(sink.ca.read_bytes())
    # Model a frozen policy with a separately retained local CA copy.
    with c.engine.journal.write() as db:
        policy = json.loads(c.delivery._policy())
        policy["ca_file"] = str(ca)
        db.execute(
            "UPDATE execution_alert_delivery SET policy_json=?",
            (json.dumps(policy, sort_keys=True),),
        )
    assert attached(c).ca_file == str(ca)
    ca.write_bytes(b"replaced")
    before = pair(c.engine)
    with pytest.raises(ValueError):
        attached(c)
    assert pair(c.engine) == before
    Path(str(c.engine.journal.path) + ".authority.db").unlink()
    retained = c.engine.journal.path.read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        attached(c)
    assert c.engine.journal.path.read_bytes() == retained and not sink.calls


@pytest.mark.parametrize(
    "options",
    [
        {"alert_origin": "https://example.test"},
        {"alert_token_file": "absent"},
        {"alert_ca_file": "absent"},
        {"alert_origin": "http://example.test", "alert_token_file": "absent"},
    ],
)
def test_invalid_init_options_do_not_create_population(tmp_path, options):
    directory = tmp_path / "population"
    with pytest.raises(ValueError):
        initialize(directory, capital=Decimal(10), symbols=["SPY"], **options)
    assert not directory.exists()


@pytest.mark.parametrize("fault", ["mode", "symlink", "malformed", "ca"])
def test_invalid_alert_credentials_fail_before_initialization(tmp_path, sink, fault):
    token = tmp_path / "token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    path = token
    if fault == "mode":
        token.chmod(0o644)
    elif fault == "symlink":
        path = tmp_path / "link"
        path.symlink_to(token)
    elif fault == "malformed":
        token.write_text("bad")
    ca = tmp_path / "ca"
    ca.write_text("invalid CA")
    directory = tmp_path / "population"
    with pytest.raises((ValueError, OSError)):
        initialize(
            directory,
            capital=Decimal(10),
            symbols=["SPY"],
            alert_origin=sink.origin,
            alert_token_file=path,
            alert_ca_file=ca if fault == "ca" else None,
        )
    assert not directory.exists() and not sink.calls


def test_new_population_enrollment_is_explicit_immutable_and_network_free(tmp_path, sink):
    token = tmp_path / "token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    directory = tmp_path / "enrolled"
    result = initialize(
        directory,
        capital=Decimal(10),
        symbols=["SPY"],
        alert_origin=sink.origin,
        alert_token_file=token,
        alert_ca_file=sink.ca,
    )
    assert result["network_calls"] is False
    engine = ExecutionEngine.attach_existing(directory / "execution.db")
    before = pair(engine)
    delivery = AlertDelivery.attach_existing(engine)
    assert delivery.config.origin == sink.origin
    assert delivery.report()["status"] == "OK" and pair(engine) == before
    with pytest.raises(FileExistsError):
        initialize(
            directory,
            capital=Decimal(10),
            symbols=["SPY"],
            alert_origin=sink.origin,
            alert_token_file=token,
            alert_ca_file=sink.ca,
        )
    default = tmp_path / "default"
    initialize(default, capital=Decimal(10), symbols=["SPY"])
    with pytest.raises(ValueError, match="enrollment"):
        AlertDelivery.attach_existing(ExecutionEngine.attach_existing(default / "execution.db"))
    assert not sink.calls


def test_lifetime_sender_lease_blocks_idle_duplicate_but_not_trader_or_control(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(poll_seconds=1))

    async def proof():
        stop = asyncio.Event()
        task = asyncio.create_task(c.delivery.run(stop))
        try:
            await asyncio.sleep(0.05)
            before = pair(c.engine)
            assert await attached(c).deliver_once() == {"status": "BUSY"}
            with pytest.raises(AlertAlreadyRunning):
                await attached(c).run(asyncio.Event())
            with runtime_lease(c.engine.journal.path), control_lease(c.engine.journal.path):
                assert pair(c.engine) == before
        finally:
            stop.set()
            await asyncio.wait_for(task, 1)
        with alert_delivery_lease(c.engine.journal.path):
            pass

    asyncio.run(proof())
    assert not sink.calls


def test_service_continues_after_exhaustion_and_halt_without_ack_or_resume(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(poll_seconds=1, max_attempts=1))
    sink.mode = "lost"
    emit(c)

    async def wait_status(status):
        for _ in range(500):
            rows = c.delivery.report()["attempts"]
            if rows and rows[-1]["status"] == status:
                return
            await asyncio.sleep(0.01)
        pytest.fail("delivery did not settle")

    async def proof():
        stop = asyncio.Event()
        task = asyncio.create_task(c.delivery.run(stop))
        try:
            await wait_status("EXHAUSTED")
            c.clock[0] += timedelta(seconds=300)
            c.engine.halt("fixture stopped trader", now=c.clock[0])
            sink.mode = "ok"
            await wait_status("DELIVERED")
            await asyncio.sleep(1.05)
        finally:
            stop.set()
            await asyncio.wait_for(task, 1)

    asyncio.run(proof())
    rows = c.delivery.report()["attempts"]
    assert [row["status"] for row in rows] == ["EXHAUSTED", "DELIVERED"]
    assert len(sink.calls) == 2
    report = c.engine.journal.report(now=c.clock[0])
    assert report["halted"] and not report["orders"]
    assert c.delivery.report()["status"] == "BLOCKED"
    assert all(row["acknowledged_at"] is None for row in c.engine.journal.alerts())


def test_repeated_cancellation_retains_lease_until_send_cleanup(tmp_path, sink, monkeypatch):
    c = setup(tmp_path, sink)
    emit(c)

    async def proof():
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def send(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                cleanup = asyncio.create_task(release.wait())
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        continue

        monkeypatch.setattr(alerts, "_send", send)

        async def owner():
            with alert_delivery_lease(c.engine.journal.path):
                await alert_cli._serve_owned(c.delivery, asyncio.Event())

        task = asyncio.create_task(owner())
        await entered.wait()
        task.cancel()
        await cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert await attached(c).deliver_once() == {"status": "BUSY"}
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        with alert_delivery_lease(c.engine.journal.path):
            pass

    asyncio.run(proof())
    assert c.delivery.report()["attempts"][0]["status"] == "IN_FLIGHT"
    assert not sink.calls


def cli(c, command, *options):
    return [
        sys.executable,
        "-m",
        "app.execution.alert_cli",
        command,
        "--journal",
        str(c.engine.journal.path),
        *options,
    ]


def test_native_service_delivers_after_halt_and_restart_does_not_replay(tmp_path, sink):
    c = setup(tmp_path, sink)
    c.engine.prepare("in-flight", decision(), packet(), now=NOW)
    with c.engine.journal.write() as db:
        db.execute(
            "UPDATE execution_orders SET status='SUBMITTING',attempted_at=?", (NOW.isoformat(),)
        )
    c.engine.halt("fixture failure while submitting", now=NOW)
    before = c.engine.journal.report(now=NOW)
    process = subprocess.Popen(cli(c, "run"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(500):
            if (
                c.delivery.report()["attempts"]
                and c.delivery.report()["attempts"][0]["status"] == "DELIVERED"
            ):
                break
            if process.poll() is not None:
                pytest.fail("native service exited before delivery")
            time.sleep(0.01)
        else:
            pytest.fail("native delivery did not settle")
        retained = pair(c.engine)
        duplicate = subprocess.run(cli(c, "run"), capture_output=True, timeout=5, check=False)
        assert duplicate.returncode == 1
        assert json.loads(duplicate.stdout)["error_class"] == "AlertAlreadyRunning"
        once = subprocess.run(cli(c, "once"), capture_output=True, timeout=5, check=True)
        assert json.loads(once.stdout)["status"] == "BUSY"
        assert pair(c.engine) == retained and len(sink.calls) == 1
        process.send_signal(signal.SIGTERM)
        output, errors = process.communicate(timeout=5)
        assert process.returncode == 0 and not errors
        assert json.loads(output)["status"] == "STOPPED"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    with alert_delivery_lease(c.engine.journal.path):
        pass
    once = subprocess.run(cli(c, "once"), capture_output=True, timeout=5, check=True)
    assert json.loads(once.stdout)["status"] == "IDLE" and len(sink.calls) == 1
    after = c.engine.journal.report(now=NOW)
    assert after["halted"] and after["orders"] == before["orders"]
    assert after["restore_fence"]["status"] == "VERIFIED"
    retained = pair(c.engine)
    c.token.unlink()
    report = subprocess.run(cli(c, "report"), capture_output=True, timeout=5, check=True)
    assert json.loads(report.stdout)["network_calls"] is False
    assert pair(c.engine) == retained
    assert TOKEN not in report.stdout.decode() and "private-thesis" not in report.stdout.decode()


def test_native_sigterm_drains_current_bounded_attempt(tmp_path, sink):
    c = setup(tmp_path, sink, limits=AlertLimits(timeout_seconds=1))
    emit(c)
    sink.mode = "stall"
    process = subprocess.Popen(cli(c, "run"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert sink.started.wait(5)
        process.send_signal(signal.SIGTERM)
        output, errors = process.communicate(timeout=5)
        assert process.returncode == 0 and not errors
        assert json.loads(output)["status"] == "STOPPED"
        assert c.delivery.report()["attempts"][0]["status"] == "RETRY"
        assert len(sink.calls) == 1
        with alert_delivery_lease(c.engine.journal.path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("fault", ["missing", "symlink", "fifo", "public"])
def test_alert_lease_rejects_invalid_journal_before_creating_lock(tmp_path, fault):
    path = tmp_path / "journal"
    if fault == "symlink":
        target = tmp_path / "target"
        target.write_text("")
        path.symlink_to(target)
    elif fault == "fifo":
        os.mkfifo(path, 0o600)
    elif fault == "public":
        path.write_text("")
        path.chmod(0o644)
    with pytest.raises((ValueError, OSError)):
        with alert_delivery_lease(path):
            pytest.fail("invalid journal accepted")
    assert not Path(str(path) + ".alerts.lock").exists()


def test_empty_explicit_alert_origin_is_not_silently_omitted(tmp_path):
    with pytest.raises(ValueError):
        initialize(
            tmp_path / "population",
            capital=Decimal(10),
            symbols=["SPY"],
            alert_origin="",
            alert_token_file="unused",
        )
    assert not (tmp_path / "population").exists()


def test_cli_init_flags_and_report_are_network_free(tmp_path, sink, capsys):
    from app.execution.runtime_cli import main

    token = tmp_path / "token"
    token.write_text(TOKEN)
    token.chmod(0o600)
    directory = tmp_path / "population"
    assert (
        main(
            [
                "init",
                "--directory",
                str(directory),
                "--capital",
                "10",
                "--symbols",
                "SPY",
                "--alert-origin",
                sink.origin,
                "--alert-token-file",
                str(token),
                "--alert-ca-file",
                str(sink.ca),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["network_calls"] is False
    engine = ExecutionEngine.attach_existing(directory / "execution.db")
    before = pair(engine)
    assert alert_cli.main(["report", "--journal", str(engine.journal.path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["network_calls"] is False and report["mode"] == "FIXTURE_PAPER"
    assert pair(engine) == before and not sink.calls


def test_startup_bad_token_is_sanitized_and_preserves_claims(tmp_path, sink):
    c = setup(tmp_path, sink)
    emit(c)
    c.token.write_text("private-invalid-secret")
    before = pair(c.engine)
    process = subprocess.run(cli(c, "run"), capture_output=True, timeout=5, check=False)
    assert process.returncode == 1 and not process.stderr
    assert json.loads(process.stdout)["error_class"] == "ValueError"
    assert "private-invalid-secret" not in process.stdout.decode()
    assert pair(c.engine) == before and not sink.calls
    with alert_delivery_lease(c.engine.journal.path):
        pass


def test_missing_cli_journal_creates_nothing(tmp_path, capsys):
    path = tmp_path / "absent.db"
    for command in ("run", "once", "report"):
        assert alert_cli.main([command, "--journal", str(path)]) == 1
        assert json.loads(capsys.readouterr().out)["status"] == "ERROR"
    assert list(tmp_path.iterdir()) == []
