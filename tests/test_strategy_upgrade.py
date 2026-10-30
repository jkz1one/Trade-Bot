"""Same owner, append-only amendment and recoverable file publication."""
import json
import sqlite3

import pytest
from test_robinhood_read_mapping import schemas as schemas
from test_robinhood_read_mapping import AT

from app.mixed import host_bundle, simulation_profile, strategy_upgrade as upgrade
from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.connected_runtime import check
from app.mixed.observer import MixedObserver
from app.options.runtime_cli import initialize, load, existing_runtime
from app.options.runtime_models import RuntimeSettings
from app.options.engine import fingerprint


def prepared(tmp_path, schemas, monkeypatch):
    state = tmp_path / 'state'; state.mkdir(mode=0o700)
    monkeypatch.setattr(host_bundle, 'STATE', state)
    monkeypatch.setattr('app.options.runtime_cli.model_key', lambda *a: 'test-never-used')
    monkeypatch.setattr('app.options.coordinator.model_key', lambda *a: 'test-never-used')
    settings, policy = simulation_profile.configuration()
    paths = []
    for name, value in (('settings', settings), ('policy', policy), ('schemas', schemas)):
        p = tmp_path / (name + '.json'); p.write_text(value.model_dump_json()); p.chmod(0o600); paths.append(p)
    review = host_bundle.prepared(*paths, clock_source=lambda: AT)[0]
    host_bundle.create(state / 'config', *paths, expected_review=review['review_sha256'], clock_source=lambda: AT)
    settings = load(state / 'config/runtime.json')
    from app.mixed.continuous_feed import FeedPolicy
    policy = FeedPolicy.model_validate_json((state / 'config/policy.json').read_bytes())
    initialize(state / 'owner', settings, clock=lambda: AT)
    ContinuousFeed(state / 'collector', policy, schemas, create=True).close()
    return state, settings


def test_preserves_balance_identity_all_old_events_and_reopens(tmp_path, schemas, monkeypatch):
    state, old = prepared(tmp_path, schemas, monkeypatch)
    with sqlite3.connect(state / 'owner/options.db') as db:
        before = db.execute('SELECT * FROM execution_events').fetchall()
        control = db.execute('SELECT * FROM execution_control').fetchall()
    venue = (state / 'owner/venue.db').read_bytes()
    inode = (state / 'owner/options.db').stat().st_ino
    report, _ = upgrade.review(state, clock_source=lambda: AT)
    out = upgrade.apply(state, expected_review=report['review_sha256'], clock_source=lambda: AT)
    assert out['status'] == 'STRATEGY_UPGRADE_APPLIED' and not out['account_reset']
    assert (state / 'owner/options.db').stat().st_ino == inode
    assert (state / 'owner/venue.db').read_bytes() == venue
    new = load(state / 'owner/runtime.json')
    assert new.execution == old.execution and new.limits == old.limits
    with sqlite3.connect(state / 'owner/options.db') as db:
        assert db.execute('SELECT * FROM execution_events').fetchall()[:-1] == before
        assert db.execute('SELECT * FROM execution_control').fetchall() == control
    view = MixedObserver(state / 'owner/options.db', old.limits.population_id, clock=lambda: AT).report()
    assert view['status'] == 'OK', view
    assert view['cash'] == '1000' and view['fill_count'] == 0
    with existing_runtime(state / 'owner', clock=lambda: AT):
        pass
    with pytest.raises(ValueError, match='already'):
        upgrade.review(state, clock_source=lambda: AT)


@pytest.mark.parametrize("failure_at", [1, 2, 3])
def test_interrupted_publication_requires_original_review_and_recovers(tmp_path, schemas, monkeypatch, failure_at):
    state, _ = prepared(tmp_path, schemas, monkeypatch)
    report, _ = upgrade.review(state, clock_source=lambda: AT)
    original = upgrade.replace
    count = [0]
    def fail(*args):
        count[0] += 1
        if count[0] == failure_at:
            raise OSError('test interrupted publication')
        return original(*args)
    monkeypatch.setattr(upgrade, 'replace', fail)
    with pytest.raises(OSError):
        upgrade.apply(state, expected_review=report['review_sha256'], clock_source=lambda: AT)
    assert (state / upgrade.INTENT).exists()
    with pytest.raises(ValueError):
        check(state / 'owner', state / 'collector', state / 'config/policy.json', state / 'config/schemas.json', clock_source=lambda: AT)
    with pytest.raises(ValueError):
        with existing_runtime(state / 'owner', clock=lambda: AT):
            pass
    with pytest.raises(ValueError, match='Original pending'):
        upgrade.apply(state, expected_review='0'*64, clock_source=lambda: AT)
    monkeypatch.setattr(upgrade, 'replace', original)
    upgrade.apply(state, expected_review=report['review_sha256'], clock_source=lambda: AT)
    assert not (state / upgrade.INTENT).exists()
    with sqlite3.connect(state / 'owner/options.db') as db:
        assert db.execute('SELECT COUNT(*) FROM execution_events WHERE kind=?', (upgrade.KIND,)).fetchone()[0] == 1


def test_stale_review_never_writes_intent(tmp_path, schemas, monkeypatch):
    state, _ = prepared(tmp_path, schemas, monkeypatch)
    with pytest.raises(ValueError, match='review changed'):
        upgrade.apply(state, expected_review='0'*64, clock_source=lambda: AT)
    assert not (state / upgrade.INTENT).exists()


def test_existing_session_receipt_survives_owner_amendment(tmp_path, schemas, monkeypatch):
    from datetime import date
    from app.mixed import feed_rollover
    from app.mixed.continuous_feed import FeedPolicy
    state, _ = prepared(tmp_path, schemas, monkeypatch)
    base = FeedPolicy.model_validate_json((state / 'config/policy.json').read_bytes())
    next_policy = tmp_path / 'next.json'
    next_policy.write_text(base.model_dump_json())
    next_policy.chmod(0o600)
    args = (state / 'owner', state / 'collector', state / 'config/policy.json',
            state / 'config/schemas.json', next_policy, date(2026, 10, 26))
    reviewed = feed_rollover.review(*args, clock_source=lambda: AT)[0]
    feed_rollover.apply(*args, expected_review=reviewed['review_sha256'], clock_source=lambda: AT)
    with sqlite3.connect(state / 'collector/collector.db') as db:
        before = db.iterdump()
        original = '\n'.join(before)
    report, _ = upgrade.review(state, clock_source=lambda: AT)
    upgrade.apply(state, expected_review=report['review_sha256'], clock_source=lambda: AT)
    with sqlite3.connect(state / 'collector/collector.db') as db:
        assert '\n'.join(db.iterdump()) == original
    result = check(*args[:4], clock_source=lambda: AT)[0]
    assert result['rollover_sessions'] == ['2026-10-26']
    assert len(result['accepted_owner_hashes']) == 2
