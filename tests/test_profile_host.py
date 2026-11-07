"""Host profile stages have no network/auth; explicit key copy never changes SHADOW."""

import os
from types import SimpleNamespace

import pytest
from test_session_host import IMAGE, RELEASE, load


def test_profile_stages_mount_only_schema_and_separate_input_parent(tmp_path, monkeypatch):
    m = load()
    auth, profile = tmp_path / "auth", tmp_path / "profile"
    auth.mkdir(mode=0o700)
    schema = auth / "discovery.json"
    schema.write_text("synthetic")
    schema.chmod(0o600)
    monkeypatch.setattr(m, "AUTH", auth)
    monkeypatch.setattr(m, "PROFILE_HOME", profile)
    monkeypatch.setattr(m, "image", lambda _: IMAGE)
    calls = []
    monkeypatch.setattr(m, "execute", lambda *a, **k: calls.append((a, k)))
    m.run(SimpleNamespace(operation="review-profile"), RELEASE)
    assert not profile.exists()
    m.run(SimpleNamespace(operation="prepare-profile", expected_review="a" * 64), RELEASE)
    assert (profile / "profiles").is_dir()
    assert "/profiles/initial" in calls[1][0][2]
    for args, _ in calls:
        assert args[1] == "app.mixed.simulation_profile"
        mounts = " ".join(args[3])
        assert "robinhood-oauth" not in mounts and "model_key" not in mounts
        assert f"src={profile}," not in mounts


def source(tmp_path, monkeypatch):
    m = load()
    key = tmp_path / "original"
    key.write_text("synthetic-private-key\n")
    key.chmod(0o600)
    monkeypatch.setattr(m, "MODEL_SOURCE", key)
    monkeypatch.setattr(m, "MODEL_SOURCE_UID", os.getuid())
    monkeypatch.setattr(m, "PROFILE_HOME", tmp_path / "profile")
    return m, key


def test_explicit_model_copy_is_private_create_only_and_source_unchanged(tmp_path, monkeypatch):
    m, key = source(tmp_path, monkeypatch)
    before = key.read_bytes(), key.stat()
    result = m.prepare_model_key()
    target = m.PROFILE_HOME / "model_key"
    assert target.read_bytes() == before[0]
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.stat().st_ino != key.stat().st_ino
    assert (key.stat().st_uid, key.stat().st_mode, key.stat().st_mtime_ns) == (
        before[1].st_uid,
        before[1].st_mode,
        before[1].st_mtime_ns,
    )
    assert "synthetic-private" not in str(result)
    with pytest.raises(FileExistsError):
        m.prepare_model_key()


@pytest.mark.parametrize(
    "damage", ["public", "symlink", "hardlink", "owner", "oversize", "multiline"]
)
def test_model_copy_rejects_unsafe_sources_before_creating_destination(
    tmp_path, monkeypatch, damage
):
    m, key = source(tmp_path, monkeypatch)
    if damage == "public":
        key.chmod(0o644)
    elif damage == "symlink":
        other = tmp_path / "link"
        other.symlink_to(key)
        monkeypatch.setattr(m, "MODEL_SOURCE", other)
    elif damage == "hardlink":
        os.link(key, tmp_path / "second")
    elif damage == "owner":
        monkeypatch.setattr(m, "MODEL_SOURCE_UID", os.getuid() + 1)
    else:
        key.write_text("x" * 4097 if damage == "oversize" else "one\ntwo")
    with pytest.raises(ValueError):
        m.prepare_model_key()
    assert not m.PROFILE_HOME.exists()
