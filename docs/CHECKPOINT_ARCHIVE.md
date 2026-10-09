# Independent checkpoint archive receiver

`app.execution.archive_cli` implements the native HTTPS archive contract in
[EXECUTION_CHECKPOINTS.md](EXECUTION_CHECKPOINTS.md). It retains opaque checkpoint
bytes and never opens their databases, attaches an engine, restores authority or
connects to a broker. It is separate from the PAPER services, deployed SHADOW
checkout and its local nightly backup. No receiver is deployed by this change
and no upload is scheduled automatically.

## Explicit provisioning

Use a separately provisioned host/storage failure domain and the verified installed
wheel. A directory on the trader host is only local evidence. The archive owner
provisions a dedicated non-root UID, protected parents, persistent storage with a
filesystem quota, encryption at rest, native TLS certificate/private key, exact
HTTPS origin, network controls and a separate random 32-byte lower hex bearer token.
Token/private key files must be current-owner mode-600 regular files; certificates
must be bounded current-owner regular files. Final symlinks/FIFOs and interactive
TLS key passwords are rejected.

The receiver does not create users, issue certificates, change firewalls, install
systemd units or accept TLS termination/forwarded authority from a proxy. Do not add
it to frozen SHADOW or share its UID/secrets with trader, model, market, operator or
alert roles. Use a separately reviewed host lifecycle, with only its archive
directory/token/TLS material available. Initialize once as the archive UID; the
parent must already exist:

```bash
python -I -m app.execution.archive_cli init \
  --directory /var/lib/trade-bot-archive/objects --max-objects 90
python -I -m app.execution.archive_cli serve \
  --directory /var/lib/trade-bot-archive/objects \
  --origin https://archive.example.net:8790 \
  --token-file /etc/trade-bot-archive/archive.token \
  --certfile /etc/trade-bot-archive/archive.crt \
  --keyfile /etc/trade-bot-archive/archive.key \
  --host 0.0.0.0 --port 8790 --timeout-seconds 30
```

These are examples, not an available endpoint. Supply the actual independent origin.
There is no environment-selected listener, default token, plaintext listener or
proxy fallback. TLS requires 1.2 or newer. Request/access/exception logging does not
expose tokens, object bytes or paths; startup errors emit only a sanitized class.

## Storage and failures

Initialization exclusively creates a mode-700 store with private frozen capacity
configuration. Existing directories are never adopted/reinitialized. Explicit
capacity ranges from 1 through 1,000 admissions. Each holds at most 64 MiB; 90 slots
permit 5,760 MiB of object bytes plus small filesystem metadata. Provision quota/free
space for the chosen capacity. There is no automatic retention deletion, capacity
increase, pruning, upload or recovery.

A lifetime nonblocking lease permits one receiver or report process per store.
Root/admission directory descriptors remain open; relative file opens do not follow
final symlinks. Directories must remain current-owner mode 700 and files mode 600.
Unrecognized root entries, changed permissions, invalid config or excess admissions
fail closed.

Authenticated PUT durably admits a new SHA-256 directory before receiving bytes.
Its exclusive private `incoming` file is bounded by exact Content-Length. The entire
body must match the URL/idempotency-key SHA-256. Only then are file bytes fsynced,
exclusively linked as `checkpoint.tbcp`, and admission/store directories fsynced.
Publication never replaces an object. The staging alias is removed after durable
publication; a crash there can leave both names pointing to the same retained inode.

Interrupted/bad-digest uploads retain incomplete admissions and partial bytes. Each
consumes one slot even if no bytes survive. Retrying an incomplete/corrupt identity
is rejected without overwrite, repair or replay; retain it for review and explicitly
choose a distinct future capture. There is no deletion endpoint. Actual SIGKILL tests
prove process-loss admission retention/lease release, not power-loss durability of
an independently hosted filesystem.

Retry after complete publication checks existing object size/hash and fsyncs its
file/admission/store before confirmation. It also consumes/hashes the retry body.
Matching bytes return HTTP 200 without replacement; first publication returns 201.
If publication completed but durability/reply failed, the client can remain UNKNOWN
although a complete object exists. Only the client's explicit same-identity `--retry`
can seek confirmation; an interrupted request is not acceptance.

GET checks original object size/hash before returning bounded uncompressed bytes.
The existing client independently verifies downloaded bytes against a separately
retained trusted pin before publishing/staging. Archive UID/host administrators are
a trust boundary: they can alter/remove files outside the append-only HTTP interface.
Retain pins separately. A trusted older pin selects older evidence, not the latest
generation. Receipts/local reports do not prove future retention.

## Protocol and lifecycle

Only authenticated exact `PUT` and `GET /v1/checkpoints/<lowercase-sha256>` operate
on objects. Duplicate/oversized metadata, foreign Host, forwarded headers, browser
Origin, transfer encodings, Expect, changed idempotency identity, oversized/empty
body and unsupported body encodings are rejected. Traversal, query strings and
encoded identities cannot select an object. Other methods have no write action.

One connection at a time shares one socket deadline, maximum 30 seconds, across
TLS handshake, headers, body and reply. A watchdog shuts down the socket even if
bytes trickle in. This small manual-transfer service is not a general high-throughput
object store. Hashing/fsync and hardware stalls remain cooperative filesystem work,
not hard real-time deadlines. SIGTERM ends the request loop, drains its current
bounded request and then releases listener/lease. SIGKILL leaves evidence for review.
Restart does not retry uploads, delete evidence or resume trading.

Stop the receiver before its exclusive source-independent report:

```bash
python -I -m app.execution.archive_cli report \
  --directory /var/lib/trade-bot-archive/objects
```

Reports separate VERIFIED, INCOMPLETE and UNAVAILABLE objects, always retaining
`off_host_protection=UNVERIFIED` and `execution_authority=false`. They expose hashes,
sizes/capacity, not object bytes or credential paths. Full reporting hashes all
admitted objects and takes time proportional to bounded stored bytes.

## Actual acceptance still required

Local tests run the installed receiver in a distinct native TLS process with the
existing isolated upload/download client, deduplication, fsync failures, SIGKILL/
restart, stalled TLS/headers/body and SIGTERM. Source-loss testing deletes original
journal/authority/bundle, restarts the receiver, retrieves the object and stages
evidence; engine attachment still fails `RESTORE_AUTHORITY_MISSING`. This is simulated
source loss in one workspace.

Actual acceptance requires a separately hosted receiver with reviewed independent
storage/retention/encryption/access/lifecycle, an authenticated upload receipt and
later successful download using a separately held pin after source-host loss.
Preserve incomplete admissions and unresolved order/model evidence. Quarantine is
the terminal action: no promotion, authority import, replay, automatic RESUME or LIVE.
