# Execution evidence checkpoints

The optional [native TLS archive receiver](CHECKPOINT_ARCHIVE.md) implements the
transfer contract below on separately provisioned private storage. Its installed
entry point is `app.execution.archive_cli`; no endpoint is provisioned or scheduled
by this tool, and local fixture retention does not prove off-host protection.

This opt-in tool preserves the fixture execution engine's journal and separately
retained authority as one private checkpoint. It does not operate on the deployed
SHADOW database, credential files or observer. It does not enroll, migrate, initialize,
resume or dispatch an engine. Every result declares `execution_authority: false`.

## Export a consistent pair

The existing source must be a current compatible execution journal with VERIFIED
restore authority. Both files must be current-owner mode-0600 regular files; final
symlinks, FIFOs, directories, empty and oversized inputs are rejected. Export does
not create missing authority or adopt a journal-only rollback.

Export attaches the authority, acquires/checks both SQLite RESERVED locks, and copies
each database using separate read connections and SQLite's backup API while both
locks remain held. A concurrent writer waits until both copies complete. Export
rolls back the lock transaction without mutating the source or advancing its
restore generation. Copies pass integrity and logical authority checks. Tests prove
paired consistency while another thread attempts to halt the source, plus unchanged
source bytes during ordinary export.

Primary SQLite references: [backup API](https://www.sqlite.org/c3ref/backup_finish.html)
and [rollback-journal locking](https://www.sqlite.org/lockingv3.html). These describe
why the implementation uses separate source-read connections under retained writer
locks. Actual export/failure behavior is tested independently.

The fixed uncompressed `.tbcp` envelope contains only a bounded JSON manifest followed
by the journal and authority bytes. It has no arbitrary archive paths or executable
extraction instructions. The manifest records creation time, authority UUID/generation,
logical state hash, each member's size/hash and schema version. Total artifact size
is capped at 64 MiB; manifest size is capped at 4 KiB. No OAuth, model API, operator
signing or read-token files are bundled. The journal still contains private audit,
account, model-decision and credential-fingerprint evidence, so archive storage must
remain private. The envelope is not encrypted at rest by this tool.

A private temporary file is fsynced and published by an exclusive hard link, then
the containing directory is fsynced. Existing files and final symlinks are never
overwritten. A failed copy leaves no published checkpoint; a failure after publication
can leave the complete file even if no success response reaches the caller. Inspect
that file before choosing another export path. The default cooperative export deadline
is 10 seconds, maximum 30. SQLite progress/backup checks bound ordinary work, but
blocking filesystem operations, Python logical-state hashing and hardware stalls are
not hard real-time guarantees. The export locks can delay engine/supervisor writes;
this is not wired into a deployed scheduler.

Export, archive receipt admission, download and quarantine staging now prepare their
output parent hierarchies durably. The existing anchor directory and its parent are
flushed first, including an anchor left by a failed earlier preparation. Each new
mode-700 ancestor is then flushed together with the parent entry naming it before
evidence work or an archive child is admitted. Existing directory modes and unrelated
files are unchanged. Preparation failure can leave private empty ancestors for review;
it does not automatically remove or reuse execution state. This addresses directory
entry durability separately from file bytes, as described by
[Linux fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html).

Example against explicitly provisioned fixture evidence:

```bash
python -m app.execution.checkpoint_cli export \
  --journal /private/fixture/execution.db \
  --output /private/checkpoints/execution-001.tbcp
```

Retain the returned `checkpoint_sha256` independently of the source host and backup
object. Inspection, retrieval and recovery require that exact lowercase SHA-256 pin:

```bash
python -m app.execution.checkpoint_cli inspect \
  --bundle /private/checkpoints/execution-001.tbcp \
  --sha256 RETAINED_CHECKPOINT_SHA256
```

Hashing happens before parsing the envelope or opening its SQLite contents. Wrong pins,
trailing/truncated bytes, duplicate/extra/misbound manifest fields, corrupt members,
invalid integrity or journal/authority mismatches are rejected. Choosing a pin supplied
by the same untrusted backup is not independent verification. Choosing an older trusted
pin deliberately selects older historical evidence; this is not an online monotonic
witness or an automatic assertion of the latest generation.

The exact header and database bytes consumed during extraction are also hashed
against that independent pin, with a final end-of-file check, before opening either
SQLite member. The first hash scan does not freeze an owner-writable inode: an
in-place rewrite could otherwise substitute another valid pair between scanning
and extraction. Changed consumed bytes or newly appended trailing bytes fail
inspection/staging and cannot publish a verification marker. A later change to
bytes already consumed does not invalidate the original verified snapshot; the
report describes those extracted bytes, not ongoing retention of the source path.
This is evidence integrity, not a host-owner sandbox or execution recovery authority.

## Opt-in bounded local capture catalog

An explicitly initialized private catalog freezes the canonical source journal,
its verified authority UUID, a cooperative capture timeout (default 10 seconds,
maximum 30), and a capacity (default 30 admitted captures, maximum 90). Initialization
is exclusive and never adopts or resets an existing directory. Use the installed
package and the source's owning UID:

```bash
python -I -m app.execution.checkpoint_cli capture-init \
  --journal /var/lib/trade-bot-paper/population/execution.db \
  --directory /var/lib/trade-bot-paper/checkpoints \
  --max-captures 30
python -I -m app.execution.checkpoint_cli capture \
  --directory /var/lib/trade-bot-paper/checkpoints
python -I -m app.execution.checkpoint_cli capture-report \
  --directory /var/lib/trade-bot-paper/checkpoints --limit 25
```

Each activation retains a nonblocking catalog lease through source validation,
paired export and receipt publication. It uses a new private UUID directory, fsynced
before export, followed by an exclusive mode-600 checkpoint and fsynced receipt.
Completed source generations may advance under the same frozen authority UUID;
foreign/unverified/missing sources fail before admitting a capture. Capture's source
check and export share one cooperative deadline. Slow hardware and filesystem calls
remain subject to the export limitations above. No runtime/control/alert service
lease is acquired. Paired SQLite locks can briefly delay their writes.

An admitted directory without a completed receipt is INCOMPLETE, including a crash
after bundle publication. It consumes capacity and is never automatically completed,
replayed, overwritten or pruned. A later activation admits a separate capture of
current evidence; it does not backfill the failed time. Capacity exhaustion fails
the next job. After review and separately retained evidence, an operator can explicitly
provision another catalog; there is no automatic retention deletion or rotation.
The space check requires at least 128 MiB plus 8 KiB free before admission, covering
the bounded temporary pair/bundle. It does not reserve disk space against other writers.

Reporting reads only the catalog, even after source loss. It counts all admitted
jobs and returns at most 25 rows by default (maximum 100), checks bounded private
receipts, source-UUID/directory bindings, whole-artifact size/digest, and the embedded
manifest against the receipt. Corrupt or unexpected catalog entries fail closed.
It does not reopen source databases, recheck every archived SQLite member, prove
source freshness, or certify that a host condition skipped by systemd was healthy.
Completed-row ordering uses checkpoint creation times; incomplete rows have no
completed capture time and remain visible in aggregate counts.

Every result declares `off_host_protection: false` and `execution_authority: false`.
A local receipt/digest is a corruption check, **not an independently retained pin**:
the host owner or a whole-catalog rollback can replace both evidence and receipt.
Retain the pin separately before remote transfer or quarantine recovery. Staging
remains the existing explicit `stage` operation and never restores execution authority.
The optional [isolated host timer](PAPER_HOST.md#optional-local-checkpoint-timer)
captures locally only; it has no network or credential access and does not alter
the deployed SHADOW backup cron.

## Explicit remote retention and retrieval

Archive operations use a separate HTTPS origin and dedicated private 32-byte lowercase
hex Bearer token file. They are explicit one-request operations; there are no SDK
retries, redirect following, proxy discovery or automatic schedules. An optional
CA file is bounded/hash-pinned in the transfer configuration and rechecked in the
child; native TLS verifies hostname/trust. Commands below are a contract for a
separately provisioned archive service, not a server deployment instruction.

| Operation | Archive contract |
|---|---|
| Upload | `PUT /v1/checkpoints/<sha256>`, `application/octet-stream`, exact Content-Length and `Idempotency-Key: <sha256>`. |
| Retention receipt | HTTP 200 or 201; uncompressed JSON no larger than 1 KiB; strict `{checkpoint_sha256, byte_count, retained: true}` matching the exact artifact. |
| Retrieval | `GET /v1/checkpoints/<sha256>`; HTTP 200, uncompressed `application/octet-stream`, exact bounded Content-Length, downloaded SHA-256 matching the independent pin. |
| Archive responsibility | Authenticate; durably store/hash/private-retain the complete object before replying; reject changed bytes for an ID; deduplicate uploads; serve original retained bytes; protect retention, access and encryption at rest. |

```bash
python -m app.execution.checkpoint_cli upload \
  --bundle /private/checkpoints/execution-001.tbcp \
  --sha256 RETAINED_CHECKPOINT_SHA256 \
  --origin https://archive.example \
  --token-file /private/archive.token \
  --receipt-file /private/receipts/execution-001.json
```

A private nonblocking receipt-file lock prevents duplicate local owners. The
configuration/destination and checkpoint identity are bound to that receipt. A
fsynced IN_FLIGHT attempt commits before spawning the fixed child. Only an exact
receipt becomes REMOTE_ACCEPTED; failures become UNKNOWN, and cancellation/crash
retains IN_FLIGHT. Neither means the upload did not reach the archive. After review,
`--retry` explicitly reuses the same ID/bytes/destination; retargeting an existing
receipt is rejected. Attempts accumulate rather than reset. A saved confirmation
returns EXISTING_RECEIPT without contacting the archive again; it records historical
acceptance, not continuing retention. Retrieval separately checks stored bytes.

The child receives only artifact/staging path, pin, dedicated archive-token path and
transport configuration. It receives no engine handles, broker/model secrets or
proxy environment. Input/output pipes are bounded. A maximum-30-second monotonic
process deadline includes spawning; repeated cancellation drains TERM/KILL and
reaps the child. A watchdog exits on parent death/deadline. A remote acceptance
cannot be revoked by killing the client. Cancellation cannot retract already
transmitted private evidence. The parent cleans download staging only after child
cleanup; failed/truncated/corrupt/older downloads are never published.

```bash
python -m app.execution.checkpoint_cli download \
  --output /private/recovery/execution-001.tbcp \
  --sha256 RETAINED_CHECKPOINT_SHA256 \
  --origin https://archive.example \
  --token-file /private/archive.token
```

This is a specific immutable archive protocol. It is not a direct S3/Spaces,
SSH, Drive or generic webhook adapter. A real independent archive endpoint, credentials,
retention policy and independently retained pin still need provisioning and testing.
No external archive or message recipient was contacted by development verification.

## Recovery is quarantine only

```bash
python -m app.execution.checkpoint_cli stage \
  --bundle /private/recovery/execution-001.tbcp \
  --sha256 RETAINED_CHECKPOINT_SHA256 \
  --output /private/recovery/review-001
```

Staging creates a new private directory containing `execution.evidence.db`,
`authority.evidence.db` and a final `verified-evidence.json` marker. Existing recovery
directories are never replaced. Missing final markers represent incomplete staging.
Failure cleanup removes only the new directory created by that call.

Before reporting QUARANTINED_EVIDENCE, staging flushes the member files and final
marker, the new quarantine directory, and its parent entry. A parent flush error
returns failure and follows the existing cleanup path. Storage/interruption failures
still require inspection; cleanup is not a guarantee against evidence reappearing
after power loss. These filesystem-call/order and failure checks do not substitute
for a target-host power-loss drill, storage durability verification or independent
off-host retention. No recovery authority or promotion path is added.

Member bytes retain original orders, fills, reservations, costs, model receipts,
halts, operator generations/retired fingerprints, commands, alerts, supervisor and
policies. The bounded summary reports the checkpoint revision, original halt,
active orders, unresolved attempts and unknown model-call count. No terminal order,
model usage, risk resolution or fresh account truth is invented. There is no normal
`<journal>.authority.db` sidecar, so ordinary engine opening fails before mutation
with RESTORE_AUTHORITY_MISSING; the operator API also cannot obtain VERIFIED authority.
Successful evidence verification cannot approve, replay, release, re-enroll or resume
anything. Trusted filesystem owners can manually rearrange files and remain outside
this boundary; the tool does not provide an active-state import or a paired-rollback
cure. Any future execution recovery needs separate fresh authoritative reconciliation,
current independent generation evidence and authenticated reasoned enablement.

Verification covers concurrent pair capture, source byte preservation, pins/format/
private files, old-pair substitution, copy/deadline/storage failures, strict TLS archive
receipts, explicit same-ID retry, corrupt/older retrieval rejection, source-loss evidence
recovery, cancellation, actual child-parent death and execution denial. Installed-wheel
verification uses a separate durable native-TLS archive process and deletes all
original source state/bundle before retrieval. This simulates source loss, not actual
host power failure, cross-host storage durability or deployed backup protection.
