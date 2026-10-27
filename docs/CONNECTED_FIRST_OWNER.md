# First native simulation owner and coordinated dashboard publication

The first owner now has a create-only review/enrollment interface. It initializes
one native virtual-money bankroll and its collector from explicitly supplied
settings, policy and read schemas. It creates no brokerage or external PAPER
account. It does not convert the frozen dashboard fixture into a running owner,
choose capital/risk rules, infer contract terms or clear missing data eligibility.

The existing connected runner can now supervise the runtime, collector and an
already enrolled dashboard publisher together. An unexpected publisher return or
failure sets the same stop event as runtime/collector failures. Restart preserves
the same native account, positions, feed history and publisher binding.

## First-owner review and enrollment

All five paths must be canonical and absolute. Owner and collector directories
must not exist and must have private current-user-owned parent directories. Their
paths cannot nest. Supplied JSON files must pass existing private-file and native
schema checks. The runtime feed path, stock universe, provider/schema mappings,
optional carry schedule and native quote-fill mode must agree. Frozen `ui-review-`
population identifiers are rejected. No operational default configuration is
silently derived from test fixtures.

Interface examples, not commands ready for the current host:

```text
python -I -m app.mixed.connected_owner review \
  --directory ABSOLUTE_NEW_NATIVE_OWNER \
  --feed-directory ABSOLUTE_NEW_COLLECTOR \
  --settings ABSOLUTE_RUNTIME_SETTINGS_JSON \
  --policy ABSOLUTE_BASE_FEED_POLICY_JSON \
  --schemas ABSOLUTE_EXPORTED_SCHEMAS_JSON
```

Review is read-only and opens no credentials. It reports the configured virtual
capital, play limit, model/operator enrollment flags, native wiring checks and
remaining entry blockers. Its exact hash binds complete settings, collector
policy/schema and all paths. It does not assert that every native enrollment or
host credential check has already run. Native initial strategy enrollment requires
positive capacity; zero is rejected before creating files. Existing native
controls can still reduce an enrolled owner's capacity later.

```text
python -I -m app.mixed.connected_owner enroll \
  --directory ABSOLUTE_NEW_NATIVE_OWNER \
  --feed-directory ABSOLUTE_NEW_COLLECTOR \
  --settings ABSOLUTE_RUNTIME_SETTINGS_JSON \
  --policy ABSOLUTE_BASE_FEED_POLICY_JSON \
  --schemas ABSOLUTE_EXPORTED_SCHEMAS_JSON \
  --expected-review EXACT_REVIEW_SHA256
```

Enrollment repeats the review under a private stable parent lease before native
initialization. It then rechecks the collector inputs against the original hash
and delegates to guarded first-collector enrollment under the native owner lease.
The new `connected-enrollment.json` receipt binds the original review, native
configuration and collector review. It is written only after both enrollments
complete. No feed packet, runtime heartbeat, order, fill or model call is created.

When explicitly configured, native enrollment validates existing private model
and operator key files. It does not read the broker OAuth file, submit broker
orders, request market data or call a model. The result distinguishes configured
credential validation from read-only review. No credentials are copied or emitted.

Creation is deliberately not a cross-database transaction. A failure after owner
creation retains that owner; a later failure can retain both owner and collector
without the final receipt. No automatic delete, adoption, balance reset, retry or
resume occurs. Preserve partial evidence for inspection. An existing owner must
use its existing collector or the earlier guarded first-collector path where
appropriate, not this new-owner command.

## Coordinated runtime, collector and publisher

Prepare the [dashboard snapshot](DASHBOARD_SNAPSHOT.md) separately after enrollment.
The connected runner then accepts these additional arguments for both `check`
and explicitly bounded `run`:

```text
--snapshot-directory ABSOLUTE_EXISTING_SNAPSHOT_DIRECTORY \
--reader-uid NUMERIC_READER_UID --reader-gid NUMERIC_READER_GID
```

Omitting all three preserves the previous runtime/collector behavior. Partial
arguments are rejected. `check` verifies the stored snapshot binding and reports
publication age without opening execution or credentials. Retained pending-copy
evidence blocks startup. An old completed publication may be refreshed by `run`;
it is not relabeled fresh by `check`. Future clocks or mismatched readers fail.

Run reuses existing owner, collector and publisher leases. All three are acquired
before asynchronous work starts. Native reconciliation/protection runs first;
collector reads and dashboard publication wait for that first tick. Publication
uses a background thread so bounded SQLite backup/validation does not block the
native async supervisor. The cadence is five seconds after each completed copy.

If any component fails or returns unexpectedly, the common stop event fences new
entry. Native runtime/provider/model cleanup follows the existing grace period.
Cancellation, including repeated cancellation, drains the actual publication
thread before its task returns and before ownership descriptors can close. The
copy retains the publisher's existing size/time checks and atomic replacement.

After orderly runtime and collector shutdown, the runner publishes one final
copy of the stopped native state while all leases remain held. Failed-component
shutdown does not retry a failed snapshot or erase pending evidence. The last
complete copy remains on disk and the reader's normal freshness guard eventually
returns 503. Stopping this session does not switch the dashboard back to the
frozen view; display rollback remains an explicit independent operation.

The coordinated path must use the exact same owner/snapshot path mapping as
snapshot enrollment. In the existing host helper those aliases are `/source` and
`/exports/connected-v1`. Future host launch wiring must retain these bindings,
private UID ownership, required copy capabilities, read-auth mount and explicit
run duration. Do not run an independent publisher against the same destination
at the same time. The publisher lease prevents dual writers.

## Evidence and remaining work

`CONNECTED_FIRST_OWNER_PROOF.json` records installed-wheel validation. Native
restart tests cover empty and two-held-play accounts, including an unreconciled
durable fill. They compare the final dashboard copy with the source account after
two consecutive sessions, preserving cash, entries, fills and delivery sequence.
Failure/cancellation tests verify component cleanup and draining the actual copy
thread. Enrollment tests retain original inputs and partial failures.

The first test run exposed native rejection of initial zero capacity. The review
now rejects that setting before creating an owner; no native strategy gate was
relaxed. Cross-user publication remains unverified in this ID-0-only sandbox.
No Docker/server activation, real credential access or provider/model call was
performed during implementation.

Concrete operational settings/catalog and a reviewed host launcher are still
needed. Eligible catalyst/Scope inputs, complete contract/data eligibility,
operator-command transport and connected market acceptance remain unfinished.
The server is unchanged on frozen a653cc7, connected simulation inactive, LIVE
disabled. This is a slice end; more offline coding remains possible.
