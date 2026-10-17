# Stored options PAPER observer

First M4 surface, 2026-10-09 UTC. This separate authenticated app reads the existing
local options fixture population. It never opens an execution owner, attaches a
venue/model, checks restore authority, initializes or repairs evidence, or triggers
collection, supervision, recovery or orders. The stock runtime and frozen deployed
SHADOW observer remain separate. LIVE stays disabled.

## Local interface

Use the installed package and an existing explicit options journal/population.
Provide a separate absolute password-file path, owned by the observer user, regular
and mode `0600`, containing 24–512 visible ASCII characters with an optional final
newline. Generate that secret locally; never supply broker/model credentials here.

```sh
python -I -m app.options.observer_cli \
  --journal /absolute/private/options.db \
  --population-id your-existing-frozen-population \
  --password-file /absolute/private/observer.password \
  --port 8790
```

The server binds only `127.0.0.1`; the port must be nonprivileged. Basic auth user is
`trader`. The secret is reread per request, so rotation/revocation takes effect
without an execution action. Only authenticated GET `/` and `/api/options` expose
records. Unauthenticated `/healthz` describes observer availability and explicitly
does not check trader health. There are no trading or control routes. Responses use
no-store, restrictive CSP, frame denial and escaped HTML. Access logging is disabled.
Remote use requires separately reviewed secure transport; this slice installs no
service, proxy configuration or target-host listener.

The API and page accept `limit=1..100`, an optional positive `before` row ID and
`family=ALL|DEGEN|SWING|SCOPE`. History is newest first. Older-page selection does
not change the current-position projection. Latest HTML can opt into `refresh=true`
for a 30-second refresh; historical pages never auto-refresh. Refresh only reads.
Swing shows its explicit shared session-close enrollment. Scope now shows stored
research enrollment and watches in a separate section, with no invented opportunity,
order or fill rows.

## Scope research visibility

The report's `scope` section reads the same owned population and SQLite snapshot.
Absent enrollment is `NOT_ENROLLED`; a valid watch enrollment is `RESEARCH_ONLY`.
Incomplete tables, missing policy, owner mismatches, malformed or oversized JSON,
invalid timestamps and conflicting selected watch identities/statuses make the
report unavailable. Policy, frame, choice, geometry and admission data use their
existing validators. This is a bounded stored projection, not a replay or audit of
every historical action, and it grants no execution or restore authority.

The latest 25 stored watches appear newest first by session and insertion order.
The total count and truncation flag are explicit. The active record is fetched
separately so it cannot disappear beyond that history limit. Opportunity-family
filters and older-opportunity pages do not change this current research snapshot.
The HTML shows the research section whenever Scope is enrolled, including when no
calls exist. The authenticated API retains exact geometry and full stored admission
results, including debit, full-premium loss and reserved exit fees. Existing account,
entry/management costs, orders and fills remain separate and unchanged.

`recorded_status` and `recorded_eligible` describe saved evidence only. A watch is
not expired or reset by reading it. Separate labels show future timestamps, passage
of the entry cutoff and expiry of recorded arming/admission validity. Equality with
the validity deadline is expired. `WITHIN_RECORDED_WINDOW` describes only time bounds,
not fresh data, account eligibility or permission to act. An unfinished hold has no
invented sizing result. Earlier eligibility remains historical after a later arming
reset; neither is executable authority. No scanner, owner, venue, model or network
operation is started by this projection. Native Scope execution remains blocked.

The same authenticated GET-only API/page and private bounded database restrictions
apply. No new controls, background collector or host service are introduced.
Desktop/mobile browser visual acceptance remains open.

## Evidence and uncertainty

The overview shows the frozen cohort, stored cash/settled cash, owned position,
unresolved orders, known model costs, unknown calls, enrollment/version details,
account and supervision age, and retained entry blockers. Accepted orders and
authoritative local fixture fills appear separately. Missing evidence does not
imply a zero balance, flat account, successful fill or running trader.

Owned-position management retains the exact purchased contract, whole quantity,
basis, original thesis/invalidation, tightened invalidation, required exit time and
retained exit reason. Premium quote and underlying evidence remain separate.
Current marks use the latest exact stored contract bid only when source, metadata,
coverage, timestamps, entitlement and full bid size qualify. A newer invalid quote
cannot revive an older valid mark. Conflicting equal-time quotes, stale/missing
quotes or inadequate size leave the mark unavailable. The observer does not fetch
a replacement quote or substitute midpoint, last or entry price. Supervision alone
does not continuously save every observed quote; persisted decision inputs and
the enrolled local runtime's latest accepted frame are available to this projection.

Unresolved orders, incomplete/stale accounts, reconciliation issues or unsupported
exposure suppress equity estimates. Unknown model usage also suppresses the
after-model-cost estimate. Recorded fees and known configured-rate model costs are
visible. Current marks exclude exit/data/host costs. An optional
[historical comparison view](OPTIONS_COMPARISON_VIEW.md) now links an explicitly
generated full-cost research report through `--comparison-file`. Its session
boundaries, net equity, model-off A, SPY and cash display are separate from current
marks. Incomplete historical paths retain their uncertainty, and never convert a
current estimate into a complete net return or profitability proof.

For explicitly enrolled [local runtime populations](OPTIONS_LOCAL_RUNTIME.md),
runtime status/freshness, observed session and the latest accepted frame are read
from the same committed snapshot. Other populations keep worker/session unknown.
New runtime starts retain [installed-file identity](OPTIONS_LOCAL_RUNTIME.md#installed-release-identity)
with their generation. The observer reads that saved evidence without inspecting
its own package. Historical starts remain unknown; verified file consistency is
not worker liveness or release approval. Restore authority is **not checked by the observer**.
Local alert records do not establish independent options alert delivery. A fresh
stored heartbeat does not prove a running worker, and the page grants no entry
approval or recovery authority.

## Read boundary and verification

The journal must be an existing absolute owned regular `0600` file, bound to the
expected options schema and frozen population. Each response reads one committed
SQLite snapshot using read-only URI, query-only and untrusted-schema settings.
File identity is checked around the snapshot. Cooperative SQL/response deadlines
are two seconds; caps are 64 MiB database, 256 KiB stored JSON record, 10,000 model
attempts and 1 MiB response. History, fills, receipts and alerts are bounded.
These are local cooperative bounds, not OS isolation or target-host acceptance.
An absent journal yields EMPTY without creating a database. Invalid, incompatible,
oversized or unreadable evidence yields UNAVAILABLE without partial account metrics,
raw exception details or credential paths.

The 53 new test cases cover immutable repeated reads, concurrent committed
snapshots, interrupted opportunities without recovery, private auth and rotation,
unknown costs/orders, exact positions and invalid/stale/conflicting quotes,
pagination, unimplemented families, escaped model text and absence of trading
routes. Owner/venue/model entry points are forbidden during observer reads.
The installed full suite passed **1,810 tests in 438.47 seconds**, warnings as
errors. Actual installed isolated-mode native CLI checks additionally verify
loopback HTTP, authentication, EMPTY without source creation and clean shutdown.

Responsive CSS is included and server-rendered page branches have local test proof;
**desktop/mobile browser visual acceptance remains open**. The official browser
binary download returned an unusable empty archive. The remote browser could not
reach the fixture-only loopback preview. Neither attempt establishes rendered QA.

M4 is only partially implemented: this stored observer has local fixture/native
proof. Mixed stock/options ownership, authenticated normalized collection/model
acceptance, full cost/benchmark/cohort evaluation, visual acceptance and actual
isolated-host/off-host recovery gates remain open. No deployment, broker/model
provider call or experiment change is part of this slice.

## Entry and management attribution

The [arm D extension](OPTIONS_MANAGED_REPLAY.md) adds read-only proposal, review,
application, model-cost, order-attempt and actual-fill attribution to each stored
opportunity and order. Full held-entry/revision linkage and applied stop prices
remain available in JSON; the history table shows the concise sequence. No page
read starts management or grants execution authority. Desktop/mobile visual
acceptance remains a separate gate.

## Operator recovery evidence

The [optional signed local recovery capability](OPTIONS_OPERATOR_RECOVERY.md) adds
read-only enrollment/revocation status and the last 20 original command receipts to
JSON. The page identifies that capability separately from observer access. It never
reads the signing key, queues a command or resumes entry. Review and submission use
the separate installed local CLI; actor labels and APPLIED receipts are stored
evidence, not proof of current liveness or human review quality.

The opt-in [shared family path](OPTIONS_SHARED_STRATEGIES.md) now displays joint
cycles and filtered Degen/Swing candidates from the same stored account. Swing
status is `SESSION_CLOSE_FIXTURE` only when enrolled, otherwise `NOT_ENROLLED`.
Scope remains `NOT_IMPLEMENTED`. Filtering does not divide or hide common costs.


## Observed Greek pressure

When either the original entry quote or the latest stored quote carries Greek
observations, `position.greek_pressure` exposes [source-backed theta, IV and delta
diagnostics](OPTIONS_GREEK_HEALTH.md). It retains evidence hashes, provenance,
timestamps, null unknown signals and explicit reasons. The baseline must match the
original entry approval and preparation inputs; it is never reconstructed from a
later quote. Current quote conflicts and stale/estimated observations remain
incomplete. READY denotes available Greek inputs, not a healthy trade or order
permission. Reads use existing bounded stored evidence without mutation or network
calls. This API addition does not complete the dedicated dashboard visual pass.

## Stored progress diagnostics

`position.progress_health` exposes [durable observed progress](OPTIONS_PROGRESS_HEALTH.md)
when native supervision has recorded it. Original geometry, completed entry premium,
peaks, target stage and last-progress times survive partial sales and restart.
Current stall/divergence/giveback diagnostics retain explicit missing-data reasons;
insufficient observation coverage cannot establish a stall. The saved result must
match its entry's latest audit event. `stored_only=true` and `observations_fresh`
separate historical evaluation from current freshness. Premium metrics are before
costs, not net returns. Reads do not alter protection, consume calls or refresh
observations; historical journals without the table remain readable. Dedicated UI
visual treatment and health-driven action acceptance remain open.
