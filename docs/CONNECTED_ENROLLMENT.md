# Guarded first collector enrollment

`app.mixed.connected_enrollment` reviews and creates the first continuous collector
for an already enrolled native simulation owner. It uses that owner's one shared
bankroll and population. It does not create another account, reset cash, migrate
the frozen dashboard, resume entry or start provider/model/runtime workers.

This is an offline-verified setup interface, not a host activation instruction.
The host remains on the a653cc7 frozen V3 review. No real configuration or carry
dates were selected for the user. Host configuration and deployment still need work.

## Review and create

The owner must have native runtime status ENROLLED, generation zero and feed
sequence zero. Previously started owners must restore/reuse their existing
collector; this command cannot recreate missing delivery history. Frozen replay
populations are rejected. The existing journal, venue and runtime configuration
must be private and readable. Owner and collector paths must be canonical,
absolute and non-nested; the new collector's parent must be a private directory.
The collector destination must not exist, even as an empty directory or symlink.

The read-only review validates owner, strategy, runtime, feed, schema and optional
carry enrollment together. It compares the complete strategy identity against
both stored enrollments, using the same pure serializer as native enrollment.
Model identity verification does not open its key file. Native strategy hashes
and replay identities retain their original format.

Interface examples only, with unresolved paths:

```bash
python -I -m app.mixed.connected_enrollment review \
  --directory ABSOLUTE_EXISTING_OWNER \
  --feed-directory ABSOLUTE_NEW_COLLECTOR \
  --policy ABSOLUTE_FEED_POLICY_JSON \
  --schemas ABSOLUTE_EXPORTED_SCHEMAS_JSON
```

Review returns `review_sha256`, binding canonical paths, full runtime settings,
collector policy/schema hashes, stored owner configuration, revision, halt,
generation and sequence. A valid review still reports entry blockers and
`trading_ready: false`. It is not data entitlement or trading permission.

```bash
python -I -m app.mixed.connected_enrollment enroll \
  --directory ABSOLUTE_EXISTING_OWNER \
  --feed-directory ABSOLUTE_NEW_COLLECTOR \
  --policy ABSOLUTE_FEED_POLICY_JSON \
  --schemas ABSOLUTE_EXPORTED_SCHEMAS_JSON \
  --expected-review EXACT_REVIEW_SHA256
```

Enrollment repeats review before and after taking the existing native owner
lease. A changed review or held lease prevents collector creation. Creation uses
the existing create-only collector and freezes its exact policy/schema hash,
including carry dates. No new owner or alternate ledger is opened. The owner
database, cash, positions, fills, halt and runtime generation remain unchanged.
No feed packet is fabricated. The original supplied policy/schema files remain
the inputs to later `connected_runtime check` and explicitly bounded `run`.

If creation fails after making the destination, retain it for inspection. Retry
refuses existing evidence; no cleanup, adoption, reset or rollback is automatic.
A lost command response is not permission to recreate the collector. Use the
existing read-only connected-runtime check to inspect completed enrollment.

## Existing CLI and compatibility

`feed_cli --create` now requires the same `--expected-review` and delegates to
this enrollment path. Combining `--create` with `--run` is rejected. Existing
standalone collector reopening also verifies the native owner and rejects frozen
review populations before opening collector state. Use `connected_runtime check`
for a fully read-only existing-enrollment check; ordinary collector reopening
retains its existing interrupted-attempt recovery behavior.

There is no database/schema migration and no change to legacy collector hashes.
Existing valid collectors keep their delivery sequences, budgets and source
receipts. Runtime preflight now rejects changed strategy settings before opening
writable execution state, rather than waiting for native startup to reject them.
Native restore and execution gates still run when the runtime is explicitly opened.

## Validation and boundaries

CONNECTED_ENROLLMENT_PROOF.json records installed-wheel validation. It covers
create/restart with and without explicit carry, unchanged native owner bytes,
changed configuration/revision, owner-lease conflicts, recheck under the lease,
used-runtime/reset refusal, private paths, frozen/inconsistent enrollment,
retained failures, CLI review binding, paid identity without secrets, and native
runtime/replay compatibility.

This completes guarded first-collector enrollment, including an already supplied
carry schedule. Updating an enrolled schedule or candidate catalog is still not
implemented. Do not edit their frozen configurations in place. Full host setup,
dashboard activation, actual ongoing feed acceptance, catalyst/Scope ingestion,
entitlement, stock sizes and reviewed contract terms remain unresolved.

Stopping reason: **slice end**. More offline coding remains possible. No provider
or paid model calls, credentials, server changes, dependency changes or LIVE
routing occurred during implementation.
