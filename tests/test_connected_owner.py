"""Reviewed first native owner/collector enrollment without market transport."""

import json
from contextlib import contextmanager

import pytest
from test_connected_check import configuration
from test_connected_runtime import digest, state
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.execution.runtime import RuntimeAlreadyRunning, runtime_lease
from app.mixed import connected_owner as owner
from app.mixed.connected_runtime import check
from app.options.engine import fingerprint


def inputs(tmp_path, schemas, *, maximum=2):
    settings, policy = configuration(tmp_path)
    if maximum != 2:
        value = settings.model_dump()
        value["execution"]["mixed_owner"]["portfolio"]["max_plays"] = maximum
        settings = type(settings).model_validate(value)
    files = tmp_path / "settings.json", tmp_path / "policy.json", tmp_path / "schemas.json"
    for p, v in zip(files, (settings, policy, schemas)):
        p.write_text(v.model_dump_json())
        p.chmod(0o600)
    return (tmp_path / "owner", tmp_path / "feed", *files), settings, policy


def test_review_reads_no_secrets_and_freezes_full_configuration(tmp_path, schemas, monkeypatch):
    args, settings, _ = inputs(tmp_path, schemas)
    before = digest(tmp_path)
    monkeypatch.setattr(owner, "initialize", lambda *_a, **_k: pytest.fail("Native owner opened"))
    result, _ = owner.review(*args, clock_source=lambda: AT)
    assert result["initial_virtual_capital"] == str(settings.execution.capital)
    assert result["maximum_plays"] == 2
    assert result["binding"]["runtime_settings_sha256"] == fingerprint(settings)
    assert not result["trading_ready"] and not result["credentials_opened"]
    assert not result["workers_started"] and digest(tmp_path) == before


@pytest.mark.parametrize("maximum", [1, 2])
def test_create_one_native_bankroll_and_collector_without_starting(tmp_path, schemas, maximum):
    args, settings, _ = inputs(tmp_path, schemas, maximum=maximum)
    report, _ = owner.review(*args, clock_source=lambda: AT)
    result = owner.enroll(*args, expected_review=report["review_sha256"], clock_source=lambda: AT)
    assert result["status"] == "OWNER_AND_COLLECTOR_ENROLLED"
    assert result["maximum_plays"] == maximum
    assert not result["workers_started"] and not result["credentials_opened"]
    checked = check(args[0], args[1], args[3], args[4], clock_source=lambda: AT)[0]
    assert checked["owner_state"]["runtime_status"] == "ENROLLED"
    assert (
        checked["owner_state"]["runtime_generation"] == checked["owner_state"]["feed_sequence"] == 0
    )
    runtime, _ = state(args[0])
    assert runtime["heartbeat_at"] is None
    from app.mixed.observer import MixedObserver

    native = MixedObserver(
        args[0] / "options.db", settings.limits.population_id, clock=lambda: AT
    ).report()
    assert native["cash"] == str(settings.execution.capital)
    assert native["fill_count"] == 0 and not native["positions"]
    receipt = json.loads((args[0] / "connected-enrollment.json").read_text())
    assert receipt["review_sha256"] == report["review_sha256"]
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="create-only"):
        owner.enroll(*args, expected_review=report["review_sha256"], clock_source=lambda: AT)
    assert digest(tmp_path) == before


@pytest.mark.parametrize(
    "damage", ["settings", "policy", "existing_owner", "existing_feed", "symlink", "hash"]
)
def test_changed_or_existing_inputs_refused_before_owner_creation(tmp_path, schemas, damage):
    args, settings, policy = inputs(tmp_path, schemas)
    review, _ = owner.review(*args, clock_source=lambda: AT)
    expected = review["review_sha256"]
    if damage == "settings":
        args[2].write_text(
            settings.model_copy(
                update={
                    "execution": settings.execution.model_copy(
                        update={"capital": settings.execution.capital + 1}
                    )
                }
            ).model_dump_json()
        )
    elif damage == "policy":
        args[3].write_text(policy.model_copy(update={"poll_seconds": 11}).model_dump_json())
    elif damage == "existing_owner":
        args[0].mkdir(mode=0o700)
    elif damage == "existing_feed":
        args[1].mkdir(mode=0o700)
    elif damage == "symlink":
        args[0].symlink_to(tmp_path / "missing")
    else:
        expected = "0" * 64
    before = digest(tmp_path)
    with pytest.raises(ValueError):
        owner.enroll(*args, expected_review=expected, clock_source=lambda: AT)
    assert digest(tmp_path) == before
    assert not (args[0] / "options.db").exists()


def test_parent_lease_blocks_and_exact_review_repeats_under_lease(tmp_path, schemas, monkeypatch):
    args, settings, _ = inputs(tmp_path, schemas)
    review, _ = owner.review(*args, clock_source=lambda: AT)
    with runtime_lease(tmp_path / "connected-first-owner"), pytest.raises(RuntimeAlreadyRunning):
        owner.enroll(*args, expected_review=review["review_sha256"], clock_source=lambda: AT)
    assert not args[0].exists()

    @contextmanager
    def change(_path):
        args[2].write_text(
            settings.model_copy(
                update={
                    "execution": settings.execution.model_copy(
                        update={"capital": settings.execution.capital + 1}
                    )
                }
            ).model_dump_json()
        )
        yield

    monkeypatch.setattr(owner, "runtime_lease", change)
    with pytest.raises(ValueError, match="under lease"):
        owner.enroll(*args, expected_review=review["review_sha256"], clock_source=lambda: AT)
    assert not args[0].exists()


def test_partial_enrollment_retains_native_owner_and_refuses_retry(tmp_path, schemas, monkeypatch):
    args, _, _ = inputs(tmp_path, schemas)
    review, _ = owner.review(*args, clock_source=lambda: AT)

    def fail(*_a, **_k):
        raise RuntimeError("Synthetic failure after owner created")

    monkeypatch.setattr(owner, "enroll_collector", fail)
    with pytest.raises(RuntimeError):
        owner.enroll(*args, expected_review=review["review_sha256"], clock_source=lambda: AT)
    assert (args[0] / "options.db").is_file() and not args[1].exists()
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="create-only"):
        owner.enroll(*args, expected_review=review["review_sha256"], clock_source=lambda: AT)
    assert digest(tmp_path) == before


def test_collector_inputs_changed_after_owner_creation_retained_without_enrolling(
    tmp_path, schemas, monkeypatch
):
    args, _, policy = inputs(tmp_path, schemas)
    review, _ = owner.review(*args, clock_source=lambda: AT)
    native = owner.initialize

    def change(*a, **k):
        result = native(*a, **k)
        args[3].write_text(policy.model_copy(update={"poll_seconds": 11}).model_dump_json())
        return result

    monkeypatch.setattr(owner, "initialize", change)
    with pytest.raises(ValueError, match="after owner creation"):
        owner.enroll(*args, expected_review=review["review_sha256"], clock_source=lambda: AT)
    assert (args[0] / "options.db").exists() and not args[1].exists()


def test_zero_capacity_review_rejects_before_native_partial_creation(tmp_path, schemas):
    args, _, _ = inputs(tmp_path, schemas, maximum=0)
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="positive capacity"):
        owner.review(*args, clock_source=lambda: AT)
    assert digest(tmp_path) == before
    assert not args[0].exists() and not args[1].exists()


def test_cli_review_and_enroll_use_exact_hash_and_sanitize_failures(
    tmp_path, schemas, monkeypatch, capsys
):
    args, _, _ = inputs(tmp_path, schemas)
    native_review, native_enroll = owner.review, owner.enroll
    monkeypatch.setattr(
        owner, "review", lambda *a, **k: native_review(*a, **(k | {"clock_source": lambda: AT}))
    )
    monkeypatch.setattr(
        owner, "enroll", lambda *a, **k: native_enroll(*a, **(k | {"clock_source": lambda: AT}))
    )
    flags = [
        x
        for key, path in zip(("directory", "feed-directory", "settings", "policy", "schemas"), args)
        for x in ("--" + key, str(path))
    ]
    assert owner.main(["review", *flags]) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert owner.main(["enroll", *flags, "--expected-review", "private-invalid-hash"]) == 2
    out = capsys.readouterr()
    assert "private-invalid-hash" not in out.out + out.err
    assert not args[0].exists()
    assert owner.main(["enroll", *flags, "--expected-review", reviewed["review_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["owner_enrolled"]
