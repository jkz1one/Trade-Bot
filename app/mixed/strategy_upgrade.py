"""One reviewed, recoverable price/options amendment for an untraded PAPER owner.

The old enrollment and session receipts remain append-only. No cash, ledger,
limits, budgets, venue state, feed counter or halt is reset. A persisted intent
makes interrupted file publication recoverable by the same explicit command.
"""
import argparse
import json
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from app.domain.models import utc_now
from app.options.engine import fingerprint
from app.options.operator_inbox import read, save, sync_directory
from app.options.runtime_cli import load, strategy_identity
from app.options.runtime_models import RuntimeSettings
from app.mixed.price_options_profile import proposal

KIND = 'PAPER_PRICE_OPTIONS_UPGRADED'
INTENT = 'price-options-upgrade.json'


def amendment(db):
    rows = db.execute('SELECT payload FROM execution_events WHERE kind=? LIMIT 2', (KIND,)).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError('Unique strategy amendment required')
    value = json.loads(rows[0][0])
    old = RuntimeSettings.model_validate(value['old_settings'])
    new = RuntimeSettings.model_validate(value['new_settings'])
    if proposal(old)[0] != new or fingerprint(value['binding']) != value['review_sha256']:
        raise ValueError('Strategy amendment proposal changed')
    if value['binding']['old_settings_sha256'] != fingerprint(old) or value['binding']['new_settings_sha256'] != fingerprint(new):
        raise ValueError('Strategy amendment settings changed')
    frozen = json.loads(db.execute('SELECT config_json FROM execution_option_runtime WHERE id=1').fetchone()[0])
    prior = dict(frozen, strategy=json.loads(strategy_identity(old)))
    if (frozen['strategy'] != json.loads(strategy_identity(new))
            or fingerprint(frozen) != value['new_owner_sha256']
            or fingerprint(prior) != value['binding']['owner_state']['owner_configuration_sha256']):
        raise ValueError('Strategy amendment owner binding changed')
    return value


def accepted_owner_hashes(db, current):
    value = amendment(db)
    if value is None:
        return (current,)
    if current != value['new_owner_sha256']:
        raise ValueError('Amended owner configuration differs')
    return (current, value['binding']['owner_state']['owner_configuration_sha256'])


def untraded(db):
    # Deliberately narrow: previously traded accounts need a different migration.
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ('execution_orders', 'execution_fills', 'execution_model_calls',
                  'execution_option_scope_watches', 'execution_option_scope_entries'):
        if table in tables and db.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone():
            raise ValueError('Upgrade requires the existing never-traded account')
    state = db.execute('SELECT status FROM execution_option_runtime WHERE id=1').fetchone()
    if state is None or state[0] not in {'ENROLLED', 'STOPPED', 'FAILED'}:
        raise ValueError('Stop the runtime before strategy amendment')


def venue_identity(state):
    from app.options.venue import private_path
    path = Path(state) / 'owner/venue.db'
    private_path(path)
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT meta,state FROM option_fixture_control WHERE id=1').fetchone()
    meta, value = (json.loads(x) for x in row)
    if any(value.get(k) for k in ('position', 'stock_position', 'positions', 'orders', 'stock_orders', 'receipts', 'intents', 'submit_count')):
        raise ValueError('Untraded simulator state required, including unreconciled fills')
    return fingerprint({'meta': meta, 'state': value})


def review(state, *, clock_source=utc_now):
    from app.mixed.host_bundle import verify
    from app.mixed.connected_runtime import check
    from app.options.observer import OptionObserver
    from app.mixed.feed_rollover import collector_state, load_rollovers
    state = Path(state)
    if not state.is_absolute() or state.resolve() != state:
        raise ValueError('Canonical existing state directory required')
    if (state / INTENT).exists():
        raise ValueError('Pending amendment must be completed with its original review')
    manifest = verify(state / 'config', clock_source=clock_source)
    report, old, policy, schemas, observer = check(state / 'owner', state / 'collector',
        state / 'config/policy.json', state / 'config/schemas.json', clock_source=clock_source)
    if load(state / 'config/runtime.json') != old:
        raise ValueError('Host and owner settings differ')
    if old.swing_policy.input_basis is not None or old.scope_policy.watch.context.structure.preflight.input_basis is not None:
        raise ValueError('Price/options variant already selected')
    with observer.read() as db:
        from app.execution import restore
        if restore.status(db, restore.authority_path(state / 'owner/options.db'))['status'] != 'VERIFIED':
            raise ValueError('Verified existing restore fence required')
        untraded(db)
        last_at = db.execute('SELECT occurred_at FROM execution_events ORDER BY sequence DESC LIMIT 1').fetchone()[0]
        from datetime import datetime
        if clock_source() < datetime.fromisoformat(last_at):
            raise ValueError('Strategy upgrade clock regressed')
        if amendment(db) is not None:
            raise ValueError('Account was already amended')
        frozen = json.loads(db.execute('SELECT config_json FROM execution_option_runtime WHERE id=1').fetchone()[0])
    with OptionObserver(state / 'collector/collector.db', old.limits.population_id).read() as db:
        feed = collector_state(db, load_rollovers(db, policy, schemas))
        if feed['last_attempt'] and feed['last_attempt'][1] in {'STARTED', 'NORMALIZED'}:
            raise ValueError('Collector has an unfinished delivery')
    new, details = proposal(old)
    binding = dict(version='paper-price-options-upgrade-v1', owner_state=report['owner_state'],
        collector_state=feed, old_settings_sha256=fingerprint(old), new_settings_sha256=fingerprint(new),
        bundle_sha256=manifest['review_sha256'], venue_sha256=venue_identity(state))
    new_frozen = dict(frozen, strategy=json.loads(strategy_identity(new)))
    value = dict(binding=binding, review_sha256=fingerprint(binding),
        old_settings=old.model_dump(mode='json'), new_settings=new.model_dump(mode='json'),
        old_manifest=json.loads(read(state / 'config/manifest.json')),
        new_owner_sha256=fingerprint(new_frozen))
    return details | dict(status='STRATEGY_UPGRADE_REVIEWED', binding=binding,
        review_sha256=value['review_sha256'], halt_preserved=True, account_reset=False), value


def replace(path, value):
    """Atomic publication; the journaled intent covers a crash between files."""
    path = Path(path)
    temporary = path.parent / ('.upgrade-' + os.urandom(12).hex())
    try:
        save(temporary, value)
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def write_owner(path):
    from app.execution import restore
    db = sqlite3.connect('file:' + str(path) + '?mode=rw', uri=True, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        if not restore.begin_fenced_write(db, restore.authority_path(path)):
            raise ValueError('Existing restore-fenced owner required')
        yield db
        restore.advance(db)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def apply(state, *, expected_review, clock_source=utc_now):
    from app.execution.runtime import runtime_lease
    from app.mixed.feed_rollover import collector_lease
    state = Path(state)
    with runtime_lease(state / 'owner/options.db'), collector_lease(state / 'collector'):
        path = state / INTENT
        if path.exists():
            value = json.loads(read(path, 512 * 1024))
            if value['review_sha256'] != expected_review:
                raise ValueError('Original pending strategy review required')
        else:
            report, value = review(state, clock_source=clock_source)
            if report['review_sha256'] != expected_review:
                raise ValueError('Strategy review changed')
            save(path, value)
        if (fingerprint(value['old_manifest']['binding']) != value['binding']['bundle_sha256']
                or value['old_manifest']['review_sha256'] != value['binding']['bundle_sha256']):
            raise ValueError('Original host manifest binding changed')
        from app.mixed.feed_rollover import collector_state, load_rollovers
        from app.mixed.continuous_feed import FeedPolicy
        from app.options.read_gateway import ReadSchemas
        from app.options.observer import OptionObserver
        base = FeedPolicy.model_validate_json(read(state / 'config/policy.json', 256 * 1024))
        schemas = ReadSchemas.model_validate_json(read(state / 'config/schemas.json', 256 * 1024))
        with OptionObserver(state / 'collector/collector.db', base.population_id).read() as feed_db:
            current_feed = collector_state(feed_db, load_rollovers(feed_db, base, schemas))
        if current_feed != value['binding']['collector_state']:
            raise ValueError('Collector changed after strategy review')
        old = RuntimeSettings.model_validate(value['old_settings'])
        new = RuntimeSettings.model_validate(value['new_settings'])
        if (proposal(old)[0] != new or fingerprint(value['binding']) != expected_review
                or fingerprint(old) != value['binding']['old_settings_sha256']
                or fingerprint(new) != value['binding']['new_settings_sha256']):
            raise ValueError('Pending strategy amendment changed')
        if venue_identity(state) != value['binding']['venue_sha256']:
            raise ValueError('Simulator changed after strategy review')
        for p in (state / 'owner/runtime.json', state / 'config/runtime.json'):
            if load(p) not in (old, new):
                raise ValueError('Concurrent strategy file change')
        with write_owner(state / 'owner/options.db') as db:
            existing = amendment(db)
            if existing is None:
                untraded(db)
                frozen = json.loads(db.execute('SELECT config_json FROM execution_option_runtime WHERE id=1').fetchone()[0])
                revision = db.execute('SELECT COALESCE(MAX(sequence),0) FROM execution_events').fetchone()[0]
                if (fingerprint(frozen) != value['binding']['owner_state']['owner_configuration_sha256']
                        or revision != value['binding']['owner_state']['owner_revision']):
                    raise ValueError('Native owner changed after review')
                strategy = strategy_identity(new)
                next_frozen = dict(frozen, strategy=json.loads(strategy))
                if fingerprint(next_frozen) != value['new_owner_sha256']:
                    raise ValueError('Amendment owner hash changed')
                db.execute('UPDATE execution_option_strategy SET policy_json=? WHERE id=1', (strategy,))
                db.execute('UPDATE execution_option_runtime SET config_json=? WHERE id=1', (json.dumps(next_frozen, sort_keys=True),))
                db.execute('UPDATE execution_option_scope_watch_policy SET config_json=? WHERE id=1', (new.scope_policy.watch.model_dump_json(),))
                db.execute('INSERT INTO execution_events(sequence,occurred_at,kind,payload) VALUES(?,?,?,?)',
                    (revision + 1, clock_source().isoformat(), KIND, json.dumps(value, sort_keys=True)))
            elif existing != value:
                raise ValueError('Native amendment differs from pending intent')
        manifest = value['old_manifest']
        manifest = dict(manifest, binding=dict(manifest['binding'], settings_sha256=fingerprint(new)))
        manifest['review_sha256'] = fingerprint(manifest['binding'])
        manifest['strategy_amendment_sha256'] = expected_review
        if json.loads(read(state / 'config/manifest.json')) not in (value['old_manifest'], manifest):
            raise ValueError('Concurrent host manifest change')
        for p, data in ((state / 'owner/runtime.json', value['new_settings']),
                        (state / 'config/runtime.json', value['new_settings']),
                        (state / 'config/manifest.json', manifest)):
            replace(p, data)
        # Check the full frozen owner/collector before removing the recovery intent.
        from app.mixed.connected_runtime import check
        check(state / 'owner', state / 'collector', state / 'config/policy.json',
              state / 'config/schemas.json', clock_source=clock_source, _upgrade_review=expected_review)
        from app.mixed.host_bundle import verify
        verify(state / 'config', clock_source=clock_source)
        path.unlink()
        sync_directory(state)
    return dict(status='STRATEGY_UPGRADE_APPLIED', review_sha256=expected_review,
        account_reset=False, halt_preserved=True, workers_started=False, provider_reads=False,
        live_enabled=False, trading_ready=False)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('review', 'apply'))
    p.add_argument('--state', required=True)
    p.add_argument('--expected-review')
    args = p.parse_args(argv)
    if (args.operation == 'apply') != bool(args.expected_review):
        p.error('Only apply requires --expected-review')
    result = review(args.state)[0] if args.operation == 'review' else apply(args.state, expected_review=args.expected_review)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
