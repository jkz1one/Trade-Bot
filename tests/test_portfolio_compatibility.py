"""Binary upgrades preserve historical enrollment and byte-exact restore bundles."""

from test_mixed_native_owner import enter, owned_mixed

from app.mixed.portfolio_compatibility import preserve
from app.options.engine import OptionExecution


def test_legacy_held_play_backup_keeps_ids_cash_thesis_and_remains_v1(tmp_path):
    with owned_mixed(tmp_path) as (e, v):
        entry, at = enter(e, v)
        path, limits, policy = e.journal.path, e.limits, e.policy
        before = e.journal.report(now=at)
    manifest = preserve(path, v.path, tmp_path / "backup")
    assert manifest["original_enrollment"] == "LEGACY_V1" and not manifest["rewritten_ids"]
    with OptionExecution.open(
        tmp_path / "backup/options.db",
        limits,
        policy,
        v,
        now=at,
    ) as restored:
        assert restored.portfolio_policy is None
        after = restored.journal.report(now=at)
        assert after["stock_position"] == before["stock_position"]
        assert after["stock_position"]["entry"]["client_id"] == entry.client_id
        assert after["stock_position"]["entry"]["thesis"] == entry.thesis
        assert after["ledger"] == before["ledger"]
    with OptionExecution.open(path, limits, policy, v, now=at) as e:
        assert e.portfolio_policy is None
        assert e.journal.report(now=at)["stock_position"] == before["stock_position"]
