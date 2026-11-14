"""Offline create-only collector enrollment against the same native owner."""

import json
import sqlite3
from contextlib import contextmanager

import pytest
from test_connected_check import configuration
from test_connected_runtime import digest
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.execution.runtime import RuntimeAlreadyRunning, runtime_lease
from app.mixed import connected_enrollment as enrollment
from app.mixed.connected_runtime import check, inspect_owner
from app.mixed.continuous_feed import ContinuousFeed
from app.options.runtime_cli import initialize, strategy_identity
from app.options.runtime_models import RuntimeSettings


def prepared(tmp_path, schemas, *, carry=False):
    if carry:
        from test_connected_carry_intent import configured

        settings, policy, _, _ = configured(tmp_path)

        def mapped(value):
            if isinstance(value, dict):
                return {
                    k: "robinhood-mcp" if k in {"history_source", "hourly_source"} else mapped(v)
                    for k, v in value.items()
                }
            if isinstance(value, (list, tuple)):
                return [mapped(v) for v in value]
            return value

        settings = RuntimeSettings.model_validate(mapped(settings.model_dump()))
    else:
        settings, policy = configuration(tmp_path)
    owner, feed = tmp_path / "owner", tmp_path / "feed"
    initialize(owner, settings, clock=lambda: AT)
    paths = tmp_path / "policy.json", tmp_path / "schemas.json"
    for path, value in zip(paths, (policy, schemas)):
        path.write_text(value.model_dump_json())
        path.chmod(0o600)
    return (owner, feed, *paths), settings, policy


def review(args):
    return enrollment.review(*args, clock_source=lambda: AT)[0]


def enroll(args, reviewed):
    return enrollment.enroll(
        *args, expected_review=reviewed["review_sha256"], clock_source=lambda: AT
    )


@pytest.mark.parametrize("carry", [False, True])
def test_review_enroll_and_restart_preserve_owner_and_schedule(
    tmp_path, schemas, monkeypatch, carry
):
    args, settings, policy = prepared(tmp_path, schemas, carry=carry)
    before = digest(tmp_path)

    def forbidden(*a, **k):
        pytest.fail("Enrollment must not open credentials or start a worker")

    monkeypatch.setattr("app.options.runtime_cli.model_key", forbidden)
    monkeypatch.setattr("app.options.coordinator.model_key", forbidden)
    monkeypatch.setattr(ContinuousFeed, "run", forbidden)
    monkeypatch.setattr("app.options.runtime.OptionRuntime.run", forbidden)
    reviewed = review(args)
    assert digest(tmp_path) == before
    assert not reviewed["state_modified"] and not reviewed["trading_ready"]
    owner_before = digest(args[0])
    result = enroll(args, reviewed)
    assert result["status"] == "COLLECTOR_ENROLLED"
    assert result["state_modified"] and result["collector_enrolled"]
    assert not result["workers_started"] and not result["credentials_opened"]
    assert not result["provider_reads"] and not result["automatic_resume"]
    assert not result["trading_ready"] and not result["live_enabled"]
    assert digest(args[0]) == owner_before
    assert result["dashboard_journal"] == str(args[0] / "options.db")
    assert result["population_id"] == settings.limits.population_id
    assert not (args[1] / "feed.json").exists()
    reopened = ContinuousFeed(args[1], policy, schemas)
    try:
        assert reopened.policy.carry_intents == policy.carry_intents
        assert reopened.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    finally:
        reopened.close()
    assert (
        check(*args, clock_source=lambda: AT)[0]["owner_state"]
        == reviewed["binding"]["owner_state"]
    )
    after = digest(tmp_path)
    with pytest.raises(ValueError, match="create-only"):
        enroll(args, reviewed)
    assert digest(tmp_path) == after


@pytest.mark.parametrize("damage", ["policy", "revision", "settings", "carry"])
def test_changed_review_never_creates_collector(tmp_path, schemas, damage):
    args, settings, policy = prepared(tmp_path, schemas, carry=damage == "carry")
    reviewed = review(args)
    if damage == "policy":
        args[2].write_text(policy.model_copy(update={"poll_seconds": 21}).model_dump_json())
    elif damage == "settings":
        value = settings.model_dump()
        value["setup"]["minimum_volume_ratio"] = "2.3"
        (args[0] / "runtime.json").write_text(
            RuntimeSettings.model_validate(value).model_dump_json()
        )
    elif damage == "carry":
        args[2].write_text(policy.model_copy(update={"carry_intents": ()}).model_dump_json())
    else:
        with sqlite3.connect(args[0] / "options.db") as db:
            db.execute(
                "INSERT INTO execution_events(occurred_at,kind,payload) VALUES(?,?,?)",
                (AT.isoformat(), "REVIEW_CHANGED", "{}"),
            )
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="changed|differ"):
        enroll(args, reviewed)
    assert not args[1].exists() and digest(tmp_path) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "STOPPED"),
        ("status", "RUNNING"),
        ("generation", 1),
        ("feed_sequence", 1),
    ],
)
def test_used_owner_cannot_reset_missing_collector(tmp_path, schemas, field, value):
    args, _, _ = prepared(tmp_path, schemas)
    with sqlite3.connect(args[0] / "options.db") as db:
        db.execute(f"UPDATE execution_option_runtime SET {field}=? WHERE id=1", (value,))
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="restore existing feed"):
        review(args)
    assert not args[1].exists() and digest(tmp_path) == before


def test_owner_lease_blocks_enrollment_and_release_allows_same_review(tmp_path, schemas):
    args, _, _ = prepared(tmp_path, schemas)
    reviewed = review(args)
    before = digest(tmp_path)
    with runtime_lease(args[0] / "options.db"), pytest.raises(RuntimeAlreadyRunning):
        enroll(args, reviewed)
    assert digest(tmp_path) == before and not args[1].exists()
    assert enroll(args, reviewed)["collector_enrolled"]


def test_review_is_repeated_after_owner_lease(tmp_path, schemas, monkeypatch):
    args, _, policy = prepared(tmp_path, schemas)
    reviewed = review(args)

    @contextmanager
    def changed(path):
        with runtime_lease(path):
            args[2].write_text(policy.model_copy(update={"poll_seconds": 21}).model_dump_json())
            yield

    monkeypatch.setattr(enrollment, "runtime_lease", changed)
    with pytest.raises(ValueError, match="review changed"):
        enroll(args, reviewed)
    assert not args[1].exists()


@pytest.mark.parametrize("damage", ["frozen", "strategy", "runtime_engine", "runtime_strategy"])
def test_frozen_or_inconsistent_owner_is_rejected_read_only(tmp_path, schemas, damage):
    args, _, _ = prepared(tmp_path, schemas)
    with sqlite3.connect(args[0] / "options.db") as db:
        if damage == "frozen":
            db.execute("UPDATE execution_control SET halt_reason='FROZEN_OFFLINE_UI_FIXTURE'")
        elif damage == "strategy":
            db.execute("UPDATE execution_option_strategy SET policy_json='{}'")
        else:
            raw = json.loads(
                db.execute("SELECT config_json FROM execution_option_runtime").fetchone()[0]
            )
            raw[damage.removeprefix("runtime_")] = {}
            db.execute("UPDATE execution_option_runtime SET config_json=?", (json.dumps(raw),))
    before = digest(tmp_path)
    with pytest.raises(ValueError):
        review(args)
    assert digest(tmp_path) == before


@pytest.mark.parametrize("target", ["existing", "symlink", "nested"])
def test_destinations_never_overwrite_or_adopt_existing_state(tmp_path, schemas, target):
    args, _, _ = prepared(tmp_path, schemas)
    if target == "existing":
        args[1].mkdir(mode=0o700)
        (args[1] / "retained").write_text("failed prior preparation")
    elif target == "symlink":
        args[1].symlink_to(tmp_path / "missing", target_is_directory=True)
    else:
        args = (args[0], args[0] / "nested", *args[2:])
    with pytest.raises(ValueError):
        review(args)
    if target == "existing":
        assert (args[1] / "retained").read_text() == "failed prior preparation"
    elif target == "symlink":
        assert args[1].is_symlink() and not (tmp_path / "missing").exists()
    else:
        assert not args[1].exists()


def test_failed_creation_retains_evidence_and_cannot_be_retried(tmp_path, schemas, monkeypatch):
    args, _, _ = prepared(tmp_path, schemas)
    reviewed = review(args)
    before = digest(args[0])

    def failed(directory, *a, **k):
        directory.mkdir(mode=0o700)
        (directory / "retained").write_text("failed creation")
        raise OSError("synthetic creation failure")

    monkeypatch.setattr(enrollment, "ContinuousFeed", failed)
    with pytest.raises(OSError):
        enroll(args, reviewed)
    with pytest.raises(ValueError, match="create-only"):
        enroll(args, reviewed)
    assert digest(args[0]) == before
    assert (args[1] / "retained").read_text() == "failed creation"


def test_cli_requires_exact_review_and_sanitizes_failure(tmp_path, schemas, capsys):
    args, _, _ = prepared(tmp_path, schemas)
    flags = [
        item
        for name, value in zip(("directory", "feed-directory", "policy", "schemas"), args)
        for item in ("--" + name, str(value))
    ]
    assert enrollment.main(["review", *flags]) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert enrollment.main(["enroll", *flags, "--expected-review", "private-invalid-value"]) == 2
    assert "private-invalid-value" not in capsys.readouterr().out
    assert not args[1].exists()
    assert enrollment.main(["enroll", *flags, "--expected-review", reviewed["review_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["collector_enrolled"]


def test_paid_strategy_identity_reuses_native_hash_without_opening_key(tmp_path, monkeypatch):
    from test_mixed_entry import owner
    from test_option_runtime import policy

    with owner(tmp_path, monkeypatch, management=True) as values:
        c = values[0]
        settings = RuntimeSettings(
            limits=c.engine.limits,
            execution=c.engine.policy,
            setup=c.policy,
            selection=c.selection,
            stock_policy=c.stock_policy,
            judgment_limits=c.judgment_limits,
            entry_policy=c.entry_policy,
            position_policy=c.position_policy,
            key_file=str(c.key_file),
            runtime=policy(tmp_path, mixed_inputs="mixed-runtime-inputs-v1"),
        )

        def forbidden(*a, **k):
            pytest.fail("Identity verification opened model credentials")

        monkeypatch.setattr("app.options.coordinator.model_key", forbidden)
        assert strategy_identity(settings) == c._frozen


def test_connected_check_rejects_strategy_drift_before_opening_runtime(tmp_path, schemas):
    args, settings, _ = prepared(tmp_path, schemas)
    enroll(args, review(args))
    value = settings.model_dump()
    value["setup"]["minimum_volume_ratio"] = "2.3"
    settings = RuntimeSettings.model_validate(value)
    (args[0] / "runtime.json").write_text(settings.model_dump_json())
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="Strategy"):
        check(*args, clock_source=lambda: AT)
    with pytest.raises(ValueError, match="Strategy"):
        inspect_owner(args[0], settings, clock_source=lambda: AT)
    assert digest(tmp_path) == before


def test_old_feed_cli_cannot_bypass_review_or_start_workers_during_enrollment(tmp_path, schemas):
    from app.mixed import feed_cli

    args, _, _ = prepared(tmp_path, schemas)
    reviewed = review(args)
    flags = [
        "--journal",
        str(args[0] / "options.db"),
        "--directory",
        str(args[1]),
        "--policy",
        str(args[2]),
        "--schemas",
        str(args[3]),
        "--create",
    ]
    with pytest.raises(SystemExit):
        feed_cli.main(flags)
    with pytest.raises(SystemExit):
        feed_cli.main([*flags, "--expected-review", reviewed["review_sha256"], "--run"])
    assert not args[1].exists()
    assert feed_cli.main([*flags, "--expected-review", reviewed["review_sha256"]]) == 0
    assert check(*args, clock_source=lambda: AT)[0]["owner_state"]["runtime_generation"] == 0
