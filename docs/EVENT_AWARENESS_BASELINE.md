# Event awareness baseline — observation only

Feature branch: `feat/event-awareness-baseline`. Remote base verified on
2026-10-27: `slice2/robinhood-read-shadow` at
`19616d78546f62d6233d39c2d98055ed8a4da76a`, matching the supplied SHA.
Development used an isolated clone; existing checkouts, base, main and PR #1
were not changed. Main was `b5359aaf396e692d2142d7e02908f1544e045ee6`.

Continuation started from feature HEAD `f39a106639bbb1a66c85a75a7737f216b2a87fd6`.
The remote base was rechecked on 2026-10-27 EDT and had advanced six commits to
`de201bd686c37d71fbd93c287595c8e4b922ab8d`. Reviewed changes cover discovery/schema
compatibility, enrolled owner paths, failure diagnostics, CPU allowance, cold
read-worker imports and captured option catalogs. They do not change the native
dashboard publication, checkpoint or decision schemas used here. They have not
been merged or rebased into this isolated feature branch. Base/main/PR #1 are
managed by the separate paper-trading work and were not modified by this slice.
During verification the base advanced again to
`f305ea19bef3fdfb5aec04c51aa431f32dc2b694` (bounded after-close Swing history proof).
That helper/docs/tests change was also reviewed; no application contract changed.

Current reconciliation: the feature now incorporates base
`f305ea19bef3fdfb5aec04c51aa431f32dc2b694` in a merge **into the feature branch only**.
The paragraphs above describe earlier checkpoints. The sole documentation conflict
was resolved by retaining the full latest base status and a current event summary.
Native application paths outside `app.events` match that base exactly. See
[combined-tree offline proof](EVENT_RECONCILIATION_PROOF.json). No host action or
runtime connection is performed by this reconciliation.

Status: **fixture verified**, independently testable first implementation.
Provider and host acceptance are outstanding. No deployment, server workers,
model calls, subscription purchases, enforcement or LIVE enablement occurred.

## Earnings/IV continuation

The native audit observer now records a separate earnings-linked option-volatility
diagnostic. See [contract, settings and limits](EARNINGS_IV_AWARENESS.md) and
`EVENT_IV_PROOF.json`. This adds advisory earnings proximity and IV-evidence
checks, not a crush forecast or live VIX policy. The original event policy and
all native trading behavior remain unchanged.

## Public-source continuation

Actual workspace captures and a fixed-child capture/replay command now cover BLS,
BEA and daily VIX schema checks. Coverage remains partial; these are not host or
complete calendar acceptance. See [source evidence and usage](EVENT_SOURCE_ACCEPTANCE.md)
and `EVENT_SOURCE_PROOF.json`. Reviewed base f25efaa (following 988ff86) was incorporated into the
feature only; prior reconciliation paragraphs describe historical checkpoints.

## Delivered boundary

`app.events` is one shared deterministic component for Degen, Swing and Scope.
It has no account, bankroll, order writer or model client. Its separate SQLite
file stores observations about the existing population; it is not a trading
account. The current simulation configuration remains $1,000 virtual capital,
$1/day AI ceiling, at most two plays, no overnight carry and LIVE disabled.

The core path is `prepare(snapshot, policy)` in a background loader, then
`assess(view, request)` against an immutable in-memory view. Collection, parsing,
snapshot validation/indexing, hashing and audit IO stay off the trading path.
`assess` performs no network, disk, model, refresh, sleep or lock operation.
Windows activate from stored event times even after a provider stops responding.

No existing runtime, continuous feed, strategy, eligibility, management or
accounting code is changed. The component is ready for a separately reviewed
connection after paper-trading plumbing is operational. It is not already wired
into that host session.

## Assessment contract

`Request` identifies the existing population, actual decision/source key,
family, exact instrument, underlying symbol/kind, assessment clock and requested
holding horizon. `Assessment` retains:

- `CLEAR`, `CAUTION`, `BLOCK_NEW_ENTRIES` or `UNKNOWN`, with separate market and
  symbol states, reasons, evidence references and a validity deadline.
- Policy version/hash and snapshot sequence/hash. Original normalized source
  versions and revisions are reachable through the retained snapshot.
- Separate advisory outcomes for entry, exposure, held-position review and carry.
- `OBSERVATION_ONLY`, false authority, false trade approval and false LIVE flags.
- Explicit unsupported categories. CLEAR means no finding within the configured
  supported coverage; it is never broad news/catalyst clearance or trade approval.

Missing/stale/partial/conflicting coverage cannot produce CLEAR. An explicit
known block outranks UNKNOWN, while both findings remain available; UNKNOWN
outranks CAUTION. `would_block_new_entries` means an explicit block was observed.
UNKNOWN still sets exposure/review restrictions; future entry handling of UNKNOWN
needs its own reviewed enforcement contract. No advisory flag is consumed by the
native governor. Symbol uncertainty is not promoted to a market restriction.

Future enforcement must have separate boundaries: entry admission, incremental
exposure, held-position review and carry approval. This implementation cannot
liquidate, change size, widen stops, extend deadlines or enable carry. Carry is
always advisory-restricted under this profile, even when other checks are CLEAR.
Mandatory position protection keeps its existing independent cadence/authority.

The calendar is not converted into `CatalystEvidence` or `ScopeEventContext`.
Swing requires its existing source, completeness, entitlement, freshness and
valid-through checks. Scope requires its existing bound context/preflight inputs,
including broad-market news. A successful calendar collection satisfies none of
those other requirements. Current missing catalyst/Scope blockers remain intact.

## Explicit provisional settings

`Policy()` emits `event-awareness-research-v1`, labelled
`PROVISIONAL_RESEARCH_NOT_VALIDATED`. All values below are research settings,
not validated trading policy. The complete JSON can be printed offline with
`python -m app.events.cli policy`.

| Setting | Initial value |
| --- | --- |
| Macro window | 15 minutes before through 30 minutes after the event interval |
| Company window | 60 minutes before through 60 minutes after the event interval |
| Window boundaries | Start inclusive, end exclusive |
| Stock/index spread caution / block | 0.5% / 1% of bid-ask midpoint |
| Option spread caution / block | 10% / 20% of bid-ask midpoint |
| Absolute price movement caution / block | 1% / 2% against a same-instrument/source reference no older than 300 seconds |
| Quote maximum age / receive lag | 10 seconds / 2 seconds |
| Displayed size minimum | 1 in native share/contract units; absence remains unknown |
| Market stress proxies | SPY and QQQ stock/underlying quotes; configurable |
| Opening caution / entry-close buffer | 5 minutes / 30 minutes before actual close |
| Assessment validity ceiling | 10 seconds, shortened to the next known transition |
| Event evaluation capacity | 256 relevant events per market/symbol scope; overflow explicitly UNKNOWN |
| Calendar poll freshness | SourceSpec default 6 hours; local session materialization 24 hours |
| Daily volatility context age | At most 4 calendar days; never a live volatility signal |

Policy windows accept category prefixes with the longest match taking priority.
Macro/company source categories are not limited to a fixed FOMC/earnings list.
Any new policy values change the hash; an existing audit directory refuses policy
drift. BLS/BEA releases are conservatively classified HIGH in adapter v1; this
overinclusive classification also needs research. Source settings, retrieval
times and freshness bounds remain in the audit independently of quote clocks.

## Collection, revisions and local publication

`collect_once(store, adapter)` is a background-worker entry point. Run source
workers in separate processes, outside the connected runtime's failure group;
do not await them from entry, management or protection. No worker is installed or
started automatically. HTTPS GETs use a 10-second socket timeout, bounded 8 MiB
responses, no automatic retries and no redirects. A timeout is not a guaranteed
wall-clock deadline for a stalled external process; process isolation is the
protection boundary. Source failure publishes unavailable coverage while retaining
last known events. Other sources can continue independently.

The audit retains original raw and normalized collection records, every revision,
sanitized failure class, collection duration, all snapshot versions and every
linked assessment. API credentials are passed in headers, never stored in URLs
or exception messages. Missing source revision clocks remain null. Same-source
revisions use iCalendar SEQUENCE when available, then source/receipt chronology;
older arrivals cannot resurrect earlier schedules. Same-revision conflicts remain
explicit. Absence from a later response is not inferred cancellation.

Duplicate sources can share an explicitly reviewed `canonical_key`. Conflicting
times/statuses then produce UNKNOWN while known danger windows remain advisory.
There is deliberately no fuzzy title matching: a policy decision and its press
conference have different IDs. Automatic cross-provider equivalence mapping is
not supplied; unmapped sources retain independent events and their provenance.

Publication commits a version to the evidence journal, fsyncs a complete private
temporary file, atomically replaces `risk.json`, then records publication. A crash
before replacement keeps the previous complete file; an interrupted publication
without a receipt cannot be used for historical decision replay. A crash between
replacement and receipt can leave a valid local view unavailable to historical
replay, which returns UNKNOWN rather than inventing publication evidence.
Writer leases reject overlap; recovery is explicit and never changes a bankroll.
Readers reject corruption, policy mismatch, future clocks and in-process sequence
regression. A restarted loader begins from disk; rollback detection across loader
restarts requires the audit's retained sequence/high-water evidence during host
acceptance. No cross-host anti-rollback guarantee is claimed.

Calendar freshness uses last successful retrieval plus its own TTL. A calendar's
old revision timestamp is not a stale quote. Scope-wide coverage and future
holding-period coverage are separate from a list of observed events. Public
calendar adapters currently return PARTIAL coverage; a complete response is not
assumed to prove that every relevant event is present.

## Native evidence connection

`native_sample` maps existing normalized stock, option and underlying quotes
without a new market read. It preserves original clocks, source, entitlement,
completeness, exact identity and absent sizes. An optional price reference must
have the same instrument/source. The current Robinhood equity response lacks
sizes and explicit entitlement, so that absence remains visible.

`observe_decision` consumes the **existing dashboard publisher's atomic native
journal copy**, with its exact `snapshot_binding`. It refuses the active owner
journal path before opening SQLite. It verifies the publication receipt/checkpoint,
population, real decision row, original event time, and saved instrument context
when present. Immutable reads cannot take SQLite locks on the trading owner.
The source owner and venue are not opened by this consumer.

Supported native decision tables are option, stock and two-play portfolio proposal
decisions. The real `source_key` is the decision ID. The bounded consumer uses the
original saved intent's family (including option entry lineage) and `exit_at`, or
complete retained proposal context. An explicit caller request may supply missing
context; any known native instrument, family or horizon must agree exactly.
The audit labels the context origin. Rejected/HOLD rows without saved instrument evidence retain
`native_instrument_verified=false`. Management-consumption events and observation
of every rejected candidate/opportunity are not automatically tailed in this slice.

The consumer selects only an event snapshot published by the native decision time.
No later revisions are backfilled into an earlier outcome. The native result is
retained separately from `EVENT_OBSERVATION_ONLY`; it is never rewritten. Event
audit export does not enter native execution/accounting exports.

`consume_once` now scans a bounded batch of the existing published journal. Host
integration must invoke it in a separate process. It commits observation records, unique decision delivery receipts
and its cursor together in the evidence journal. A restart resumes that cursor;
repeating a successful invocation does not produce another observation. Missing
context or conflicting caller context remains a retained GAP, never CLEAR or an
invented family/horizon. Bounded oldest-attempt-first retries let later gaps make
progress. Original gaps and every successful/failed batch remain in export even
after resolution. No evidence is deleted automatically.

The consumer stores the full native publisher binding, policy identity, publication
checkpoint and last scanned event hash. It rejects source rebinding, publication
clock/checkpoint regression across observer restarts, sequence holes, changed cursor
anchors and changed gap evidence. This is continuity detection for the retained
append-only native journal, not a full historical tamper-proof ledger or cross-host
rollback guarantee. Atomic replacement during a read discards the whole attempted
batch. A failed SQLite transaction leaves observations, delivery receipts and cursor
unchanged. If even the evidence journal cannot persist a failure, the invocation
raises rather than claiming that the failure was retained.

`ObserverBatch` defaults to 100 native events and 25 gap retries per invocation
(both bounded at 1,000). A publication older than 60 seconds is unavailable; the
explicit batch setting allows 1–3,600 seconds. This is observer delivery freshness,
separate from calendar and quote freshness; it is not trading policy. Results report
pending **native events**, scanned count, new observations, gap retries and unresolved
gaps. `CAUGHT_UP_WITH_GAPS` means scanning caught up but evidence remains missing.
`BACKLOG` means more native events remain; `UNAVAILABLE` never advances the cursor.
The batch bound limits records processed, not total SQL work or wall-clock time.
The provisional 5 ms local assessment target does not apply to collection or audit IO.
Successful observation with an UNKNOWN assessment counts as delivered and keeps that
original result; later provider revisions never overwrite a historical assessment.

The consumer only assesses the three `*_PROPOSAL_RECORDED` event kinds. Management
consumption, opportunity selection and other native event kinds are scanned for
continuity but not assessed. An explicit context file cannot invent a native event.
The single-decision API remains available; its ad hoc records are separate from
the consumer's exactly-once delivery receipts. Running both can create distinct
audit records for the same decision, so use one delivery route in a host integration.

The command below illustrates the one-shot interface using an already enrolled
event evidence directory and the **existing publisher's exact binding file**:

```sh
python -m app.events.cli observe-once \
  --directory /event-evidence --population EXISTING_POPULATION \
  --policy /reviewed/event-policy.json \
  --snapshot-binding /published/binding.json \
  --observer-batch /reviewed/observer-batch.json
```

The optional batch JSON contains `version`, `max_events`, `max_gap_retries`,
`max_publication_age_seconds` and `contexts` (default empty). Each supplied context
is `{ "kind": "PORTFOLIO", "request": <complete Request JSON> }`. Invalid bounds,
duplicate IDs or a different population are rejected. The CLI returns 2 on an
unavailable operation. This command is documentation, not an executed host command.

No scheduler or permanent consumer was installed or started. Host scheduling,
mounts/UID isolation, durable sidecar delivery for otherwise missing candidate
context, backlog alerts and long-term retention/archival remain acceptance work.
Do not synchronously await this consumer from trading/protection, create another
native owner or change simulation settings.

## Verification and remaining acceptance

See [source/access review](EVENT_AWARENESS_SOURCES.md) and
[machine-readable offline evidence](EVENT_AWARENESS_PROOF.json).
The [observer continuation proof](EVENT_OBSERVER_PROOF.json) records the subsequent
installed-package tests and exact application identity for durable delivery.

Focused tests cover half-open event windows, independently timed related events,
calendar versus quote freshness, DST ambiguity/nonexistent times, date-only DST
days, holidays/early closes, future holding coverage, cancellations/reschedules,
duplicate/conflicting revisions, malformed data, source outages, restart, atomic
publication/interruption and reader corruption. Actual native two-play fixtures
prove that advisory blocks leave decisions/accounting untouched. Separate blocked
and failed collector processes do not delay either native mandatory exit.

The latency probe reports p50/p95/p99/max for local assessment separately from
background preparation. It includes 10,000 stored events and an overlapping-event
capacity case. Under 5 ms remains a provisional target, not a real-time guarantee.
Initial unindexed 10,000-event p99 was 124.198 ms; indexing moved that work off-path.
Final installed measurements are in the proof file. Collection duration,
source-to-receipt age, source-to-detection age, scheduled-window-to-decision delay
and decision-to-audit delay are distinct fields. Calendar source-age numbers may
span days; they are not network latency. Real provider/host distributions have
not been measured.

One later host acceptance session should verify: authorized endpoint/plan access;
original provider schemas, dates, revisions and coverage; native quote freshness
and source identity; atomic publication/restart/outage recovery; exact native
decision linkage on the published copy; observation backlog; p50/p95/p99/max local
checks and separate source-detection delays under host load; and unchanged native
entries, sizing, costs and independent protection. No server command is required
to finish this offline slice, and no deployment is authorized by this document.
