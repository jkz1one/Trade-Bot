# Event awareness baseline — observation only

Feature branch: `feat/event-awareness-baseline`. Remote base verified on
2026-10-27: `slice2/robinhood-read-shadow` at
`19616d78546f62d6233d39c2d98055ed8a4da76a`, matching the supplied SHA.
Development used an isolated clone; existing checkouts, base, main and PR #1
were not changed. Main was `b5359aaf396e692d2142d7e02908f1544e045ee6`.

Status: **fixture verified**, independently testable first implementation.
Provider and host acceptance are outstanding. No deployment, server workers,
model calls, subscription purchases, enforcement or LIVE enablement occurred.

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
decisions. The real `source_key` is the decision ID; family and holding horizon
are explicit caller context, labelled in the audit rather than inferred from a
calendar. Rejected/HOLD rows without saved instrument evidence retain
`native_instrument_verified=false`. Management-consumption events and observation
of every rejected candidate/opportunity are not automatically tailed in this slice.

The consumer selects only an event snapshot published by the native decision time.
No later revisions are backfilled into an earlier outcome. The native result is
retained separately from `EVENT_OBSERVATION_ONLY`; it is never rewritten. Event
audit export does not enter native execution/accounting exports.

An integration should enqueue a bounded reference after native decision commit or
consume the published copy in a separate process, retain/detect observation gaps,
and call this API there. Do not synchronously wait for audit persistence. Automatic
consumer scheduling, durable delivery/backlog policy and host mounting/UID setup
remain integration work; this first slice supplies the tested API, not a deployed
always-on observer. Do not create another native owner or change simulation settings.

## Verification and remaining acceptance

See [source/access review](EVENT_AWARENESS_SOURCES.md) and
[machine-readable offline evidence](EVENT_AWARENESS_PROOF.json).

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
