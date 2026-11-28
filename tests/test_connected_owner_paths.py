"""Keep the frozen execution path while publishing through a verified file alias."""

import os

import pytest
from test_connected_runtime import digest, enrolled
from test_robinhood_read_mapping import AT
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.mixed.connected_runtime import check, dashboard_source
from app.options.runtime_cli import existing_runtime


def alias_owner(owner, alias):
    # Hard links reproduce two canonical names for the same native files without
    # requiring a privileged bind mount in the offline test environment.
    alias.mkdir(mode=0o700)
    for path in owner.iterdir():
        if path.is_file():
            os.link(path, alias / path.name)
    return alias


def test_original_launcher_alias_reproduces_frozen_path_failure(tmp_path, schemas):
    args, _, _ = enrolled(tmp_path, schemas)
    alias = alias_owner(args[0], tmp_path / "display-source")
    before = digest(args[0])
    with (
        pytest.raises(ValueError, match="configuration"),
        existing_runtime(alias, clock=lambda: AT),
    ):
        pytest.fail("An execution alias must not bypass the frozen venue path")
    assert digest(args[0]) == before


def test_preflight_rejects_execution_alias_without_changing_state(tmp_path, schemas):
    args, _, _ = enrolled(tmp_path, schemas)
    alias = alias_owner(args[0], tmp_path / "display-source")
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="Execution owner path"):
        check(alias, *args[1:], clock_source=lambda: AT)
    assert digest(tmp_path) == before


@pytest.mark.parametrize("name", ["runtime.json", "options.db", "venue.db"])
def test_identical_copied_file_is_not_an_owner_alias(tmp_path, schemas, name):
    args, _, _ = enrolled(tmp_path, schemas)
    alias = alias_owner(args[0], tmp_path / "display-source")
    assert dashboard_source(args[0], alias) == alias
    contents = (alias / name).read_bytes()
    (alias / name).unlink()
    (alias / name).write_bytes(contents)
    (alias / name).chmod(0o600)
    before = digest(tmp_path)
    with pytest.raises(ValueError, match="same execution owner"):
        dashboard_source(args[0], alias)
    assert digest(tmp_path) == before


def test_display_symlink_is_rejected(tmp_path, schemas):
    args, _, _ = enrolled(tmp_path, schemas)
    alias = tmp_path / "display-source"
    alias.symlink_to(args[0], target_is_directory=True)
    with pytest.raises(ValueError, match="Canonical absolute"):
        dashboard_source(args[0], alias)
