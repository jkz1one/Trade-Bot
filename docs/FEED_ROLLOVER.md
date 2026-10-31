# Future-session catalog and carry rollover

The collector now supports an explicit, reviewed option catalog and carry intent
for a named future session. It keeps the original base policy, one native owner,
one bankroll, delivery sequence, read budgets, raw captures and original Swing
bindings. Enrollment does not start workers, open credentials or resume entry.

This is offline-verified implementation. The host remains the a653cc7 frozen V3
review. No actual catalog, carry dates or host activation were performed here.

## Scope and review

`app.mixed.feed_rollover review` takes the existing owner, collector, base policy
and exported schemas, plus a proposed full FeedPolicy and a target session.
Only `candidates`, `carry_intents`, and the explicitly versioned
`swing_history.bar_mapping` selector may differ from the base. History enrollment
and lookback sizes remain frozen; see NATIVE_SWING_BAR_MAPPING.md. Transport settings,
provider/schema identity, stock universe, limits and history enrollment stay fixed.

The target must be an exact exchange session after the current New York date and
within sixty calendar days. Same-day changes are rejected, including pre-open.
Each target can be enrolled once. The proposed carry schedule contains at most
one record, for that exact target. Omitting it does not infer a holding period.
Existing native asset enrollment, calendar/expiry guards and current catalyst
requirements still apply. Rollover cannot enable a strategy or supply clearance.

Proposed candidates must have explicit reviewed complete terms and tradability,
be in the enrolled stock universe and remain tradable after the target opens.
Existing instrument identities cannot acquire changed contract terms or aliases.
Held instruments and pending entries are checked separately from the new catalog.
Removing an instrument from candidates does not remove its protection quote read.
No contract discovery, automatic selection or provider metadata review is implied.

An existing target history or source-binding receipt prevents rollover, including
a blocked original receipt. Old preparation cannot be replaced or restamped.

The review is read-only and returns `review_sha256`. It binds the full proposed
policy, canonical paths, base configuration, native owner identity/revision/halt,
collector head and last attempt, and held-instrument identities. A valid review
still reports missing entitlement, stock sizes and other entry blockers, with
`trading_ready: false`.

Interface example only, not a host activation command:

```bash
python -I -m app.mixed.feed_rollover review \
  --directory ABSOLUTE_EXISTING_OWNER \
  --feed-directory ABSOLUTE_EXISTING_COLLECTOR \
  --policy ABSOLUTE_ORIGINAL_BASE_POLICY_JSON \
  --schemas ABSOLUTE_EXPORTED_SCHEMAS_JSON \
  --next-policy ABSOLUTE_REVIEWED_TARGET_POLICY_JSON \
  --target-session YYYY-MM-DD
```

## Apply and restart

Use the same arguments with `apply` and `--expected-review EXACT_REVIEW_SHA256`.
The runtime must be stopped. Apply takes the existing owner and collector leases,
repeats review under both locks and verifies the collector again inside its write
transaction. A changed review, busy owner or busy collector prevents the write.

One SQLite transaction appends the policy receipt, advances the retained hash
chain/head and installs the rollover protocol guard. A failure rolls all three
back. The operation does not reopen writable execution, reconcile, change cash,
alter fills or positions, clear halts, update quotes or start workers. Duplicate
retries are rejected; inspect the stored rollover sessions with the existing
read-only connected-runtime check if a command response was lost.

Keep using the original base policy file for collector/runtime startup. Do not
replace it with the proposed policy. The full approved policy is retained in the
collector database. On restart the complete bounded chain is verified before
collector recovery; the native owner binding is also checked in runtime preflight.
Missing, altered, incomplete or inconsistent receipts block startup.

The saved update applies only to its named session. Unscheduled dates use the
original base policy; there is no silent carry-forward of a prior session update.
Quote planning and runtime normalization select the target policy. Swing binding
creation and later verification select the policy for the original target date.
Earlier histories, source clocks, creation times and original targets remain
unchanged. Captures crossing New York midnight retain available quotes in a
MARKET packet and explicitly block an entry cycle until the next poll.

## Compatibility and rollback

Collectors without rollover retain their original configuration hash and schema.
The first explicit apply adds `feed_rollovers` and `feed_rollover_control` and
changes the collector configuration hash to include `session-feed-rollover-v1`.
An older binary rejects that hash rather than silently ignoring the session
policy. No native execution schema or owner configuration is migrated.

Do not roll an updated collector back to an older binary in place. Retain a
stopped, coherent backup of the owner and collector before operational changes;
rollback requires the matching compatible state and the existing native restore
procedure. Never restore only an old collector prefix against a newer running
owner, edit hashes, delete receipts, reset sequence numbers or discard failed
evidence to make a binary start. Host backup/activation procedures remain pending.

The receipt chain is bounded to 256 session updates. Reaching the limit blocks
additional enrollment; automatic pruning, amendment, cancellation and archival
are not implemented. Explicit future-session rollover is implemented, while
automatic candidate discovery and long-term retention remain separate work.

## Validation and remaining work

FEED_ROLLOVER_PROOF.json records 176 unique installed tests and 290 matching
application files. Coverage includes exact session activation, removed held
contract reads, unchanged owner bytes and earlier receipts, retained budgets and
sequences, raw-bound old/new carry binding, invalid settings/contracts/dates,
changed reviews, both leases, duplicate refusal, hash/head corruption, owner
binding, transaction rollback, midnight capture and credential-free CLI behavior.
Existing connected startup, two-play recovery, source preparation and delivery
suites also pass against the same wheel.

Actual eligible feeds, catalyst/Scope ingestion, automatic catalog discovery,
reviewed host settings, deployment/dashboard activation and market acceptance
remain unresolved. No new collection was needed for this slice. No provider or
paid model calls, credential access, server changes, dependency changes or LIVE
routing occurred. Stopping reason: **slice end**; more offline coding remains.
