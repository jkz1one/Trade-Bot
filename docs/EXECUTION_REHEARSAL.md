# Execution lifecycle rehearsal

Implemented 2026-10-06 alongside the deployed Slice 2 experiment. This is an offline
foundation for a future deterministic executor. It does not implement LIVE, change
the current SHADOW/synthetic runner, or prove any Robinhood execution capability.

## Integration boundary

`app.execution.engine.ExecutionEngine` consumes the existing `TradeDecision` and
`MarketPacket`, rebuilds account authority from its reconciled journal, and calls
the existing deterministic governor itself. Caller-supplied buying power or a
caller-supplied approval cannot authorize an order. It retains the configured
universe, XNYS regular-session boundary, share precision, entry limits, cooldown,
original invalidation and one-position restrictions. HOLD creates an audit event
and no order. The Trader Agent still receives no execution tools.

Only the built-in in-memory `LocalFixtureVenue` and isolated `DurableFixtureVenue`
test drivers can be attached. There is no generic network transport,
broker submission/cancellation method, credential loading or deployment switch.
The constructor requires PAPER and LIVE disabled. The standalone fixture command
also fixes those values even if environment variables request LIVE.

The separate `execution-rehearsal.db` is not `robinhood.db`, `trader.db`, or a
synthetic experiment. The journal refuses a database containing the existing
application's tables. Capital, risk settings, universe and risk-policy hash are
immutable for a journal. Fixture cash/positions/fills are never promoted into
Robinhood ownership or mixed into `virtual-v1` performance.

## Durable lifecycle

### Frozen account and dollar envelope

Each new rehearsal journal also freezes an `ExecutionLimits` envelope: the expected
local fixture account identity, maximum entry and position commitment, total dollar
loss limit and daily realized dollar loss limit. Explicit limits must be finite and
positive; entry ceiling cannot exceed position ceiling and the total loss allowance
cannot exceed allocated starting capital. Defaults use starting capital for all four
dollar limits and the `execution-rehearsal` fixture identity. These defaults are
offline guardrails, not a selected LIVE bankroll or loss policy. The existing governor
may impose tighter bounds.

Model account proposals cannot change these ceilings. Matching cash balances cannot
authorize a different account. Foreign snapshots fail reconciliation and foreign
fixture dispatch latches a halt before an attempt. Runtime changes to capital,
limits, universe, risk settings or mode fail closed against the journal configuration.
Increasing profits cannot raise the frozen entry ceiling. Position appreciation does
not force a sale; this cap bounds new entry commitments. Limits never clip an owned
position's protective sale.

The total entry-loss gate uses cash plus the current bid-marked position versus
allocated starting capital, including fees already paid and current unrealized loss.
It does not estimate a future exit fee. The daily entry gate
uses realized net P&L on each fill's New York date, including entry and exit fees.
The daily map persists atomically with ledger/fills and is not incremented by repeated
evidence. Daily wins offset that day's losses; this is a net-loss cap, not cumulative
gross losses. The total gate persists into later sessions; the daily gate checks the
current session date. These gates block new entries without disabling protective
closes. Operator resume cannot waive a loss limit or change its frozen value.

Journals created before this envelope remain readable with `report`, but reopening
them for execution is rejected as an immutable-configuration mismatch. Use a new
offline journal with explicitly selected limits; no automatic authority migration
or server experiment reset is provided.

1. Persist a governor-approved intent with a stable source identity, proposal/input
   fingerprint, quantity, limit, expiry, original stop and complete approval inputs.
   Conflicting reuse of a source key fails closed. One active reservation blocks
   additional orders, including while an entry is only partially filled.
2. Require a separately supplied `packet=` for a PREPARED dispatch. Check fresh,
   nonregressing packet/quote times, unique symbols, finite values and intact bid/ask
   evidence; never reuse the saved approval packet as current market truth. Rerun
   the governor using the saved decision and current reconciled account/market truth.
   The model cannot rewrite the approved stop or terms during dispatch. For a buy,
   risk sizing covers at least the original limit price even when the new ask falls.
   Save observed and governed packets, risk and snapshot identity with the attempt.
   Reduced buying power cannot inherit an older, larger approval;
   reject the unattempted intent if its fixed terms no longer fit. Then commit
   SUBMITTING and the attempt timestamp before invoking the local fixture.
   Every attempted/terminal identity is ineligible for another submission. A lost
   acknowledgment becomes UNKNOWN and latches a halt. A SUBMITTING record found at
   startup becomes UNKNOWN, retaining its reservation and requiring recovery.
3. Reconcile complete order/fill/account evidence. Match client and venue identity,
   symbol, side, original quantity and limit; check cumulative fills, immutable fill
   identities, timestamps, fees, approved buy budget and executable limit prices.
   Repeated cumulative evidence applies each fill once. Decimal JSON avoids SQLite
   floating-point money conversion.
4. Atomically commit new fills, cash/position transitions, order state, snapshot and
   audit events. Compare the resulting exact cash, quantity and entry basis with
   fixture account truth. Any mismatch latches a halt and applies none of the fills.
   Persistence errors roll back the whole transaction and retain the active attempt.
5. Release a dispatched reservation only after observed FILLED, CANCELED, REJECTED
   or EXPIRED evidence. A missing open order or elapsed local intent expiry cannot
   establish a terminal broker outcome. Partial cancellation retains the acquired
   position and only releases the remaining order reservation.

An unattempted PREPARED intent can expire or be explicitly abandoned with a recorded
reason. Attempted orders cannot use this shortcut. Manual halt/resume reasons are
audited and survive restart; resume requires fresh reconciled evidence and no active
order. Valid reconciliation can account for a late fill while halted, but does not
automatically clear the halt. A late acknowledgment cannot regress a reconciled
partial or terminal order.

The fixture halt is a persistent dispatch block, not liquidation or broker
cancellation. An already accepted order can still fill. This module does not provide
external alert delivery or a deployed operator control surface.

## Deterministic position supervision

The offline engine persists each filled entry's original stop, session, horizon and
explicit overnight permission from its saved governor-approved inputs. Older journals
recover this policy only from a proven filled entry; missing lineage halts execution.
SignalFlow's stop-authority contract informs this boundary, using Decimal and one
long position. No model can widen or clear the original stop.

`supervise(packet, now=...)` checks fresh reconciled account evidence and fresh,
nonregressing bid/ask quotes during the actual XNYS regular session. A bid at or
below the original stop latches INVALIDATION. Without overnight permission, the
last 15 minutes of the actual session latch SESSION_EXIT; a position carried into
a later session latches MISSED_SESSION_EXIT. A rebound, restart or model HOLD cannot
clear the requirement. Valid observations update the position mark and high watermark.
Unusable quotes, unavailable calendar/account evidence or unknown entry policy latch
a persistent halt. Recovery from a supervision halt requires fresh supervision and
explicit operator resume.

`prepare_protective_exit(packet, now=...)` creates a CLOSE proposal without a model,
through the existing governor and intent journal. It does not dispatch. Repeated or
concurrent preparation reuses the active sell identity. A partially filled entry
with an unresolved buy remainder blocks exit preparation until definitive terminal
evidence resolves that remainder. A known canceled partial sell can produce a new
intent for the remaining owned shares; ambiguous attempts cannot be replayed.
Entries are rejected at preparation and dispatch if already invalidated or inside
the final 15 minutes of the session.

This is sampled quote supervision, not a standing broker stop, guaranteed exit price,
continuous monitor or deployed service. The offline caller must supply observations
and perform the distinct fixture dispatch/reconciliation steps. No broker cancellation,
network calls or current experiment policy changes are introduced.

## Isolated durable-venue deadline rehearsal

`dispatch_async` accepts only the exact built-in `DurableFixtureVenue` class. It uses
the same saved decision, fresh-market reapproval, fixed limits and write-ahead attempt
as the in-memory harness. A dedicated fake-venue SQLite file persists acceptance and
complete order/fill/account truth independently of the executor process. Creation is
exclusive/private; existing application or journal databases cannot become venues.
The journal binds one immutable venue UUID/account identity before isolated operations.
A replacement database, transport switch or synchronous bypass is rejected.

The worker receives only one validated local fake operation and its fixed intent,
clock, venue identity and acceptance deadline. It has no brokerage transport or
model tools. Its environment excludes model/broker secrets, OAuth/settings variables
and LIVE flags. Startup, operation and bounded response parsing share one monotonic
deadline, frozen in the envelope (default 10 seconds, maximum 30). Submission is
further bounded by the admitted intent's remaining lifetime. The saved attempt receipt
includes the adapter, venue UUID, effective timeout and monotonic deadline. The child
checks that lease after acquiring its SQLite transaction, immediately before acceptance.
These monotonic values are local process evidence, not replayable admission on restart.

Timeout, malformed/oversized output, lost acknowledgment, process crash and cancellation
retain uncertainty and reservation ownership. Cleanup signals only the isolated child's
process group, escalates from SIGTERM to SIGKILL after one second, drains stdout and
reaps before returning. Repeated cancellation and cancellation during launch cannot
skip cleanup; cancellation is propagated after persisting uncertainty. Fake workers
also check parent identity before acceptance and during diagnostic stalls, so parent
death cannot leave a stalled fake child indefinitely. This does not cancel an accepted
order. Accepted fake orders remain durable and can later fill.

`reconcile_fixture` performs a bounded isolated complete-history read. Failed reads
latch a halt without changing prior ledger/snapshot evidence. A later valid read
accounts for truth but does not automatically resume execution. Missing attempted
orders are still insufficient to release a reservation, even after a known local
timeout. Reopen/reconcile both databases, prove terminal outcomes, supervise owned
risk and explicitly resume. The existing in-memory sync API remains a scripted test
harness; it cannot bypass a journal bound to the process driver.

The deadline applies to isolated fixture I/O; serialized local journal transactions
retain their 10-second SQLite lock timeout. OS launch/reaping failures must remain
blocking rather than permit another attempt with an unowned process. These tests
prove the local fixture boundary, not actual broker SDK deadlines or order semantics.
New timeout policy fields require a fresh offline journal; prior journals remain
read-only reportable without an authority migration.

## Standalone verification

From the updated development checkout:

```bash
python -m app.execution.cli run --db execution-rehearsal.db
python -m app.execution.cli report --db execution-rehearsal.db

# Use a different new file for the durable, bounded-process scenario.
python -m app.execution.cli deadline-run --db execution-deadline.db
python -m app.execution.cli report --db execution-deadline.db
```

`run` exclusively creates a new private file and refuses to overwrite one. It uses
a fixed historical session clock and scripted quotes, loses an acknowledgment,
reopens the journal, proves no retry, reconciles a partial fill, repeats that fill
evidence, observes a locally scripted canceled remainder, explicitly resumes and
closes the acquired shares. No API calls or model credits are needed. The final
scripted cash increase is not evidence of trading signal or profitability.

`report` opens the journal read-only without initialization or network calls. A
missing database is not created. Reports include the persisted control state,
orders, fills and the last 100 audit events.

`deadline-run` also exclusively creates `execution-deadline.db.venue.db`, then times
out after durable fake acceptance, reopens both stores, proves no retry, reconciles
a partial fill and scripted canceled remainder, supervises a stop and explicitly
resumes before a bounded protective close. Both resulting fills are simulated.
Neither file is the server experiment or a live account.

Tests cover duplicate/concurrent dispatch, crash/lost-ack recovery, partial/terminal
outcomes, immutable evidence, quote/session checks, fees/cash, one position, entry
limits/cooldown across restarts, manual halt, rollback, network-free CLI operation,
database isolation, read-only reports, immutable dollar/account limits, entry-loss
gates, daily fee/P&L persistence and fresh-market dispatch reapproval. Admission and
dispatch blocks retain audited reasons without creating an attempt. See
SLICE2_STATUS.md for executed results.

## Authenticated local recovery and alert outbox

The isolated engine now has an explicitly enrolled operator capability. A random
key of at least 32 bytes remains with trusted operator code; the journal stores
only its SHA-256 fingerprint and a generated journal UUID. Enrollment is explicit,
idempotent for the same active key, and rejects implicit replacement. Explicit
rotation/revocation are described below; per-person login, remote transport and
deployment are future work. A shared key
authenticates the capability; the signed actor field is an audit label, not proof
of a separately authenticated person. Existing Python engine methods remain a
trusted local API. These controls are not a sandbox against code or filesystem
owners, and the model receives neither the key nor a command tool.

`OperatorControl.review()` returns one read-only journal snapshot and its audit
revision. `OperatorCommand` freezes a stable ID, journal UUID, actor, bounded
reason, exact action/target, expected revision, credential generation and aware
issue/expiry times. Its
lifetime is positive and at most five minutes. `sign_command` uses HMAC-SHA256
over the canonical revalidated envelope. Application authenticates before any
write and rechecks enrollment inside the write transaction. Neither raw key nor
signature is stored in the audit. Signed command bodies and outcome receipts are.

The only actions are HALT, RESUME, ABANDON_PREPARED, ACK_ALERT, ROTATE_KEY and
REVOKE_KEY. None submits,
reviews or cancels a broker order, changes cash/limits, edits evidence or clears a
stop. New commands from the future or at/after expiry receive a durable rejection.
Recovery, abandonment and acknowledgment require the exact reviewed revision;
any new reconciliation, fill, supervision or command invalidates that review.
HALT can reduce authority even after revision/config changes. Every mutation,
audit record and receipt commits atomically. Storage failure rolls back all three.

An authenticated repeat of the exact ID/content returns its original receipt even
after expiry, without reapplying or changing current state, while its credential
is still active. Retired/revoked credentials cannot even obtain replay receipts.
Reusing an ID with
different signed content fails. Concurrent identical requests apply once; distinct
requests against one review serialize, with the second requiring a new review.
Rejected requests also have stable receipts: retrying the same ID after obtaining
better evidence cannot silently turn the rejection into an approval.

RESUME retains the existing complete/fresh account reconciliation and no-active-
order requirements. It additionally requires fresh, nonfuture position supervision
and quotes for an owned position. Unknown/partial orders cannot be released by a
command; only definitive complete venue evidence releases attempted reservations.
ABANDON_PREPARED expires only an unattempted local intent. Frozen risk envelopes
and latched original-stop exits remain in force after recovery.

Critical events and changed blocked/exit-required supervision observations create
an alert row in the same transaction as the originating event. Repeated identical
supervision does not create repeated alerts. `ExecutionJournal.alerts(after=...,
limit=...)` pages the durable local outbox in event order; report exposes the first
100 alerts and an exact count of all unacknowledged alerts. ACK_ALERT records the
signed actor, command ID and time. It does not mean an external message was sent,
resolve risk, clear a halt or release a reservation. There is no automatic delivery
or Slack/email integration. Alert rows apply to new events after this feature;
historical events are not retrospectively declared delivered or acknowledged.

Opening a compatible current journal for execution adds operator/receipt/alert and
retired-key tables, plus credential generation/revocation fields, without changing
its frozen envelope. Read-only reports of prior
journals do not initialize or enroll anything. Journals lacking earlier frozen
limits remain incompatible with execution as before.

Run the new exclusive-file, network-free proof:

```bash
python -m app.execution.cli operator-run --db execution-operator.db
python -m app.execution.cli report --db execution-operator.db
```

It uses an ephemeral random capability and scripted fake outcomes: lost ack,
rejected recovery, alert acknowledgment while still halted, reopen, definitive
canceled outcome and explicit signed recovery. It proves no retry, not brokerage
or trading performance. No server update or deployment key is needed.

## Credential lifecycle and journal restore fence

ROTATE_KEY requires a current signed review and an exact replacement key
fingerprint. It advances the credential generation, retires the old key and
latches a dispatch halt. The new key must be supplied independently to construct
an operator control; no key material is sent through the command or stored in
audit. REVOKE_KEY can reduce authority even after the review changes. It advances
the generation, retires the key, disables all commands/review by that capability
and halts dispatch. Both operations preserve uncertain orders and owned positions.

`OperatorControl.recover_revoked` is an explicit trusted local provisioning API,
not a remotely signed override. It requires a different, never-retired key and a
bounded reason, advances generation and retains a halt. It cannot resume, release
a reservation, repair evidence or reset a stop. Generations also prevent re-signing
an earlier command envelope under a newer key. Older command wire signatures
without the generation field are rejected, rather than silently migrated.
Current operators must still obtain fresh evidence and use normal signed RESUME.

The optional `ExecutionJournal.enable_restore_fence(now=...)` exclusively creates
`<journal>.authority.db` with permissions 600. Provisioning is local and explicit;
existing unfenced rehearsals report UNFENCED, and no server state is enrolled.
The separate authority binds a UUID, monotonically advanced commit generation and
SHA-256 hash of complete logical journal schema/state, including ledger, orders,
fills, snapshots, operator credentials, retired keys, receipts, alerts and events.
The journal keeps the matching binding/generation. Every fenced write attaches
the current authority, locks both files, verifies their exact state before any
mutation, then advances their checkpoint in the same transaction.

Both files must use DELETE rollback journals; each writer sets synchronous FULL.
WAL or other unsupported modes are rejected without changing persistent mode.
This follows [SQLite's documented ATTACH transaction requirements](https://www.sqlite.org/lang_attach.html).
The authority is opened in existing-file mode and is never guessed or recreated.
Missing/foreign authority, changed state at the same audit revision, journal-only
rollback or a restore predating fence enrollment blocks every engine write before
attempt preparation or dispatch. A read-only report shows BLOCKED with the reason
while leaving both files unchanged. Even HALT or local credential recovery cannot
rewrite an untrusted restored journal. A failed provisioning transaction leaves
its exclusively reserved authority file blocked rather than automatically rebound.

This is rollback detection against a separately retained current file, not an
off-host monotonic witness or protection against filesystem owners. Rolling back
both files together, losing both files or copying a valid pair to another machine
cannot establish which history is newest or enforce single-host ownership. Keep
the current authority outside journal-only restore operations; secure off-host
checkpoint retention, fencing across machines and a verified restoration workflow
remain required before deployment. There is no reset/rebind/resume bypass for a
mismatched pair. The full-state digest also scales with retained history; production
growth and latency have not been measured.

```bash
python -m app.execution.cli recovery-run --db execution-recovery.db
python -m app.execution.cli report --db execution-recovery.db
```

This exclusive-file proof uses ephemeral fixture keys, lost acknowledgment,
rotation, revocation, local re-enrollment and rejected recovery while the attempt
remains active. Definitive scripted CANCELED evidence then permits a signed RESUME.
It deliberately restores old bytes of its new fixture journal, proves a duplicate
dispatch is blocked, and puts back the exact known-current fixture bytes without
changing authority. It is not a utility for restoring arbitrary/user databases.
Only one fake submission occurred; no broker/model calls or deployment changes.

## Opt-in model receipts and economic authority

`CostAccounting(engine, CostPolicy(...))` enrolls an immutable offline cost policy
before any order preparation. It freezes model identity, configured standard token
rates, total/daily model budgets and a per-call cost reservation. The defaults reuse
the project's configured `gpt-6-luna` $0.10/M input and $0.50/M output assumptions;
they are not a new assertion about current provider pricing. The rates, receipt
state and costs belong only to this rehearsal journal, never a deployed population.
Existing unenrolled rehearsals report UNCONFIGURED and retain their earlier gates.

`begin(source_key, packet, now=...)` commits a durable potentially billed receipt
before a future model invocation. It requires current reconciled account truth,
an open market session, valid fresh packet/quotes, no active order and room for the
entire per-call reservation in both budgets. There can be only one uncosted call.
Repeated exact source/packet identity returns `invoke_model: false`, including
after restart; source reuse with changed packet data fails. A crash after receipt
commit cannot hide potentially billed work or trigger automatic model replay.
This API does not call a model, and real request/token limits must still be verified
in orchestration before its per-call assumption can be trusted against API billing.

`settle` accepts revalidated usage with positive input tokens, nonnegative output
tokens, pinned model and unique provider request identity, plus the exact decision.
It calculates Decimal cost from frozen rates and atomically stores usage, decision
fingerprint, amount and audit evidence. Repeated identical settlement is a no-op;
conflicting counts/decisions or reused request IDs fail. Zero/missing usage is not
invented for failures. The caller is trusted local orchestration; fixture records
are not provider billing proof. Known noncharge evidence/resolution of failed calls
remains future engineering. Operator resume cannot waive unknown costs.

Usage that exceeds the assumed per-call bound is recorded at its full estimated
amount and creates a durable alert. It permanently blocks new model calls/entries
under that policy rather than truncating cost or discarding billing evidence.
Budget gates apply to known cumulative charges; daily attribution uses the New
York date of the original attempt, even if evidence arrives later. The next day's
daily allowance resets, while total charges and bounds remain in force.

With a policy enrolled, BUY admission requires a settled receipt whose decision
and original packet fingerprints match the proposal. Fresh dispatch reruns cost
and risk checks against that immutable decision and updated market/account data.
Unknown cost, exhausted model budgets or exceeded per-call bounds block entry.
The total dollar-loss test uses current trading equity minus known model charges;
the daily test subtracts that day's model charges from fee-adjusted realized P&L.
Model costs do not debit simulated/brokerage cash, alter fill conservation or raise
buying-power ceilings. The governor's other broker-account values remain trading
values, with explicit additional economic entry gates.

HOLD judgment counts toward cost. Deterministic CLOSE/prepared protective exits
need no model receipt and remain available under unknown/exhausted cost conditions,
subject to the existing reconciliation, quote, ownership and dispatch-halt rules.
Reports show known cost, uncosted attempts, daily charges and bound violations.
Cost-adjusted equity/return is available only with complete usage and fresh matching
account evidence; owned positions also require fresh valid supervised bid marks.
Missing usage, stale marks/account or reconciliation issues suppress net metrics.
Gross reported trading equity remains the stored trading ledger mark.

```bash
python -m app.execution.cli economics-run --db execution-economics.db
python -m app.execution.cli report --db execution-economics.db
```

The exclusive-file proof uses scripted token counts and two fake fills. It opens
through matching usage evidence, starts an uncosted HOLD attempt, makes a sampled
deterministic protective exit, then settles HOLD cost and verifies net equity.
The report embeds that historical fixture valuation; subsequent current-clock
reports suppress stale net metrics. The proof needs no model API credits or broker
connection and is not trading signal/performance evidence. This engine report does
not add a SPY portfolio, corporate actions, taxes, hosting/setup costs or real invoice
adjustments. The deployed synthetic experiment's paired SPY economics stay separate.

## Bounded model judgments for the fixture engine

`JudgmentCoordinator(costs, JudgmentLimits(...))` optionally connects the cost
authority above to a private OpenAI Responses subprocess. It uses the existing
Trader instructions and `AgentOutputSchema(TradeDecision)` strict wire schema,
then applies the same post-parse runtime validation. The current deployed Agents
SDK adapter, SHADOW population, scheduler and observer are unchanged. There is no
broker client, order preparation/dispatch or database handle in the model child.

Enrollment precedes every model receipt and freezes the cost-policy hash, prompt
version/content hash, output schema hash, token ceilings and process/request
deadlines. Changed runtime configuration or a reopened policy cannot loosen it.
Default ceilings are 16,000 input tokens and 1,024 output tokens, a 30-second whole
process and 20-second SDK request timeout. Both token ceilings, at the configured
rates, must fit the existing per-call cost reservation. These are engineering
bounds; authenticated model support and practical output headroom remain to be
verified before adoption.

`await coordinator.decide(source_key, packet, api_key=..., now=..., clock=...)`
rebuilds the model's account from reconciled journal truth and supplies current
regular-session context. A reviewed audit revision is checked atomically when the
durable receipt commits, before the child can launch. Invalid keys, oversized
requests, changed account review, storage failure or missing authority cannot grant
invocation. Stable source reuse never invokes again, including after restart.
The returned packet is the original model/cost lineage for later governed admission;
the coordinator returns evidence only and does not prepare or dispatch any order.

The child receives only the explicitly supplied model credential and basic locale/
path environment, no Robinhood credentials, OAuth paths or parent API-origin overrides.
Its API origin is pinned to `https://api.openai.com/v1`, retries are disabled and
stdout/stderr logs are suppressed. There is no SDK agent tracing. It counts the
exact instruction/input/tool/schema payload through `responses.input_tokens.count`,
rejects unavailable/invalid/excessive input counts, then performs at most one
`responses.create` with `tools=[]`, `tool_choice=none`, disabled truncation, bounded
output, no background execution, no streaming and `store=false`. Count and generation
share their request content; no token-count request grants trading authority.

The [official input-token guidance](https://developers.openai.com/api/docs/guides/token-counting)
documents counting request structure, tools and schemas, and that the output cap
includes generated reasoning/non-visible tokens. The pinned SDK exposes both
endpoints; native SDK tests exercise their exact serialized requests through a
local mock transport. This does not prove the endpoint/model combination is
accepted by the user's actual API project. A provider response's `id` is saved in
the existing usage `request_id` field; this is the response object identity, not the
HTTP request header identity.

Valid response usage is captured before decision parsing. Incomplete output,
refusal, invalid decision JSON/runtime validation or unexpected tool output becomes
auditable HOLD while retaining valid reported input/output cost. Missing usage,
request failure, timeout, malformed/oversized protocol or child crash retains an
uncosted receipt and blocks further calls/entries; failures are never invented as
free calls. Cancellation propagates after termination/escalation/draining/reaping.
A child watchdog also exits on parent death or its absolute monotonic deadline.
Killing a child cannot prove a remotely started generation stopped or was unbilled.

Exact model identity, usage ceilings and counted-versus-returned input tokens are
checked in the parent. Violations yield HOLD and permanently block new judgments/
entries under the enrolled policy; full valid pinned-model usage is still charged.
Foreign-model usage remains auditable but uncosted under the pinned rates. Cost,
decision audit and evidence-violation state commit atomically. An enrolled bounded
policy requires its matching recorded judgment for BUY approval, so directly
supplied token settlement alone cannot grant entry. Resume cannot waive this gate.
Normal deterministic protective closes remain available under cost/evidence gates,
subject to the existing account/ownership/quote/halt requirements.

The child never receives broker tools or engine/operator signing authority. Trusted
local orchestration supplies the API credential and completion clock; this is not
a remote control service. The fixture engine requires refreshed account/market
evidence and governed dispatch. The optional independent loop below supplies local
fixture supervision without awaiting model reasoning.
Actual authenticated API validation, discount/invoice adjustments, verified no-charge
resolution, deployed orchestration and independent supervision remain pending.
No new deployed cohort, API request or server update occurs when importing/enrolling
this opt-in interface. Tests and package proof use mocked SDK HTTP responses only.

## Independent fixture supervision loop

`DurableQuoteFeed(path, symbols=...)` exclusively creates a private local SQLite
market fixture. `publish(sample_id, packet)` appends a bounded, validated packet;
exact sample replay is idempotent and changed content under the same identity fails.
Universe, aware clocks and nonregressing packet/quote timestamps are checked.
`DurableQuoteFeed(path).latest()` opens an existing feed read-only without creating
or migrating it. Feed identity is pinned, payloads are capped at 256 KiB, and the
supervisor rejects sequence rollback or changed content at its last observed sequence.
This is a manually supplied fixture feed, not a broker or market-data adapter.

`ExecutionSupervisor(engine, durable_venue, feed, limits=..., clock=...)` optionally
enrolls before any order preparation. Exact built-in fixture types, feed/venue/account
identities, paths, universe and limits are frozen in the execution journal. Defaults
are a 5-second poll, 10-second whole-tick deadline and 20-second health lease. Poll
plus deadline must fit the lease, which cannot exceed the engine's quote-age limit.
`await supervisor.run(stop_event)` holds a single-host POSIX lifetime file lock;
duplicate runners cannot claim ownership or advance the durable owner generation.

Every active-session tick performs a bounded child-process complete-history read,
checks fresh sane market evidence, runs deterministic position supervision and,
when required, prepares/reuses a governed protective SELL. It never creates BUY
intents, supplies model judgments, cancels orders or invents fills. Original stop,
session-exit policy, active-order ownership and quantity rounding remain in the
existing engine. Unknown/rejected outcomes block health. An unresolved partial BUY
halts rather than selling through the outstanding remainder. A definitively terminal
partial SELL permits only a newly governed residual exit. Flat closed sessions are
IDLE and do not launch fixture reads or grant entry health.

The loop can continue while the model is awaiting its private child, including an
uncosted in-flight model receipt. Protective closes remain subject to ownership,
fresh account/quotes, frozen limits and the dispatch halt; cost/health entry gates
do not grant permission to bypass those controls. No broker credential or live
placement/cancellation capability enters this loop.

Each read optionally captures an account/order/fill epoch before awaiting its child.
If those records change before reconciliation commits, the transaction discards the
superseded read and records `FIXTURE_READ_SUPERSEDED`. It neither applies older
account evidence nor renews supervision health, and the loop polls fresh truth again.
Unchanged-epoch mismatches still halt through the existing full reconciliation.
Heartbeat/quote-management audit churn alone does not invalidate the account epoch.

The heartbeat renews only after reconciliation, quote checks, position supervision
and any governed fake dispatch finish. Account and quote freshness are checked again
at completion. `ExecutionJournal.report(now=...)` exposes policy, generation,
completion time/age, last feed sequence and last result through read-only access.
After enrollment, new model receipts and BUY preparation/dispatch require a RUNNING,
OK result within the frozen lease. STOPPING revokes this gate before read cleanup
finishes. Failed ticks retain a halt, stopping with owned risk halts, and an interrupted
STARTING/RUNNING/IDLE/STOPPING owner requires explicit reasoned review before resume.
Valid reads/ticks never clear a halt. Failed/changed blocked tick results enter the
local alert outbox; unchanged blocked results do not repeat the alert.

This is opt-in library infrastructure, not a deployed daemon or broker stop order.
Trusted local orchestration provides quote samples, fixture fills, the clock and stop
signal. Model work is isolated; synchronous local SQLite/filesystem/calendar work
can still stall the parent event loop. The sampled poll/deadline is not a hard real-time
or host-survival guarantee. Secure deployed supervision, external alerts, host-failure
proof, off-host fencing and actual broker semantics remain required. The existing
SHADOW worker, observer and synthetic experiment are unchanged.

## Isolated native-TLS operator transport

`app.execution.control_api.create_control_app(engine, config, operator_key_file=...,
read_token_file=..., clock=...)` optionally creates a separate FastAPI application
for the fixture engine. It does not enroll keys, migrate a journal, create an engine,
resume execution or call a broker/model. Startup requires an already enrolled signing
capability and a VERIFIED journal/authority pair. No route is added to the existing
PAPER application or deployed read-only SHADOW observer.

| Endpoint | Authority |
| --- | --- |
| `GET /v1/review` | Read token; bounded, authenticated review of current revision, operator generation, cash/position, active intent, snapshot freshness timestamp, supervisor and oldest 25 unacknowledged alert summaries. |
| `POST /v1/commands` | Read token plus an exact signed `OperatorCommand`; only HALT, RESUME, ABANDON_PREPARED, ACK_ALERT, ROTATE_KEY and REVOKE_KEY. |

The review's binding, revision and evidence share one read-only SQLite snapshot.
Prompts, full order/fill history, event payloads and signing fingerprints/keys are
not included. Restore status must be VERIFIED; the response has a 64 KiB ceiling.
Commands retain the core's journal identity, credential generation, expiry, exact
reviewed revision, ownership/freshness and atomic action/audit/receipt rules. A
signed replay returns the original APPLIED/rejected result; it never reapplies the
action or turns a rejection into approval. Replays may advance restore bookkeeping
inside the existing fenced transaction, without changing command audit revision.

`ControlAPIConfig(origin="https://control.example:9443")` requires one exact HTTPS
origin. Serve this app with **native ASGI-server TLS and proxy-header handling
disabled**, for example `uvicorn.run(control_app, host="127.0.0.1", port=9443,
ssl_certfile=..., ssl_keyfile=..., proxy_headers=False, ws="none", access_log=False)`.
This describes the interface contract, not a deployment instruction for the current
server. Clients must validate its certificate. This app rejects plaintext, mismatched
Host/Origin, cross-site fetches, forwarding headers and duplicate security/body
headers. Forwarding headers cannot grant TLS/origin authority. WebSockets, forms,
cookie authentication, CORS access, documentation and enrollment/recovery/order/LIVE
routes are not provided. The existing Caddy observer configuration is unchanged;
this native-TLS API is not intended to be attached to its forwarding route.

Both credential files contain an independently generated 32-byte lowercase hex
secret, optionally followed by one newline, and must be regular, current-user-owned
files with mode 0600. The final file component cannot be a symlink. The read token
must differ from the signing key. Requests use `Authorization: Bearer <read-token>`;
clients sign the command locally and send `{"command": ..., "signature": ...}`.
No raw signing key is accepted in a request. Files are checked again per request;
missing/changed permissions or retired capability fail closed. Signed rotation keeps
the halt and requires trusted local replacement of the signing file to the new key.
Revocation recovery remains trusted-local only. The shared signing capability still
does not separately authenticate the actor label as a person.

Command parsing caps known-length and chunked bodies at 16 KiB and body reception
at 5 seconds by default. JSON is UTF-8 without compression; duplicate fields,
nonfinite numbers, extra fields and bad signed-envelope shapes are rejected without
echoing request/validation details. Up to four requests are admitted by default
(configurable to eight); excess returns 429 rather than queuing unbounded work.
No-store/privacy headers apply to all responses. Rejected/stale signed commands
return 409 with the durable core receipt; invalid authority returns a sanitized
403, and unavailable state/credentials return a sanitized 503.

The pure ASGI boundary retains admission while a cancelled request drains its local
thread, even after repeated cancellation. A lost HTTP response cannot prove whether
a command committed. Inspect/replay the **same signed command ID/content** while its
capability remains active, rather than generating a new command. Core transactions
and receipts remain the authority after process death. Local SQLite/hash work has
no hard real-time completion guarantee; body timeout does not abort a committing
command. Runtime TLS/host limits, OS ownership, certificate lifecycle, secure key
provisioning, actual deployed recovery, external alerts and off-host restore proof
remain deployment requirements. No actual host or experiment is changed by this
factory or the fixture tests.

## Bounded HTTPS alert delivery

`app.execution.alerts.AlertDelivery` is opt-in fixture-engine infrastructure, separate
from the deployed SHADOW worker. Enrollment requires the exact built-in PAPER engine,
a VERIFIED journal/authority pair, explicit `AlertConfig(origin=...)`, a dedicated
private token file and enrollment before any order preparation. Destination, limits,
token path, optional CA path/hash and journal identity are frozen in the restore-fenced
journal. Reopening requires the same policy; runtime changes fail before sending.

`await delivery.deliver_once()` sends one due alert; `await delivery.run(stop_event)`
polls independently. A private single-host nonblocking file lock covers admission,
child work and cancellation cleanup. A duplicate runner receives BUSY. An idle poll
verifies authority and changes neither journal nor authority bytes. This lock cannot
coordinate multiple hosts or protect against a privileged filesystem owner.

The sink contract is deliberate and provider-neutral:

| Request or receipt | Contract |
|---|---|
| Destination | Exact HTTPS origin, fixed `POST /v1/alerts`; no URL credentials, query, fragment or redirect following. |
| Authentication | Dedicated 32-byte lowercase hex Bearer token, optional trailing LF, in a regular owner-only mode-0600 file; no final symlink, FIFO or oversized secret reads. Rechecked by each child, so local token replacement can rotate it. |
| Payload | `schema_version`, restore authority UUID as `journal_id`, original event sequence/time/kind and stable SHA-256 `delivery_id`. No account, order, money, prompt, thesis, event payload or credential. |
| Idempotency | `Idempotency-Key` equals delivery ID, derived from journal identity and event sequence. Retries use the identical serialized payload and SHA-256. |
| Confirmation | HTTP 200 or 202, JSON content type, uncompressed body no larger than 1 KiB; strict `{delivery_id, payload_sha256, accepted: true}` matching the exact request. Duplicate fields, extra fields, false acceptance or foreign bindings fail. |
| Sink responsibility | Authenticate, durably store/deduplicate `(delivery_id, payload_sha256)` before replying, reject changed payloads for an existing ID, and return the original receipt on replay. Route any human notification separately. |

TLS verifies the endpoint hostname using system trust. An optional explicitly supplied
CA file is bounded to 1 MiB, rejects final symlinks/nonregular files, and is hash-pinned
at enrollment and rechecked before each authenticated request. No proxy environment
or SDK retries are used. The implementation is not a drop-in Slack, email or generic
webhook integration: a sink must implement this receipt contract. Neither acceptance
nor delivery means a person received, read or resolved an alert.

Each attempt is committed IN_FLIGHT before process creation, with stable payload/hash,
unique claim, total/batch attempt counts and conservative retry time. Attempt, result
and explicit rearm events remain in the audit. Default process deadline is 10 seconds
(maximum 30), retry delays are 60 then 120 seconds, maximum three attempts per batch,
and the run loop polls every five seconds. The wall-clock retry lease includes at
least process deadline plus five seconds. Retries are bounded best effort with possible
duplicates, not a guarantee of delivery or exactly-once human notification. A lost
reply, timeout, cancellation or parent crash can leave a delivered alert unconfirmed.
Such claims retain their ID and wait for the lease before retrying; a final interrupted
claim expires to EXHAUSTED without another automatic send. Other due alerts can
continue while an earlier alert waits for retry or is exhausted.

A fixed child receives only the sink configuration, minimal alert and sink credential
path, with a whitelisted environment excluding model/broker secrets and proxies. It
receives no engine database path or handles. Input/output pipes are bounded. Parent
cancellation drains TERM/KILL cleanup and reaps the child before releasing the lock;
a child watchdog exits on parent death or monotonic deadline. Synchronous SQLite,
restore hashing, local CA work and process spawning remain local host operations,
not hard real-time guarantees. Killing a client cannot retract a request already
accepted by the remote sink.

Once enrolled, undelivered alerts older than the frozen default 120 seconds (maximum
300), future/invalid event clocks or an exhausted attempt block new BUY admission and
new model-call receipts. The health report uses a bounded aggregate and is visible in
journal and authenticated operator review. Fresh quote/account reads cannot erase this
gate. HOLD remains auditable and protective SELL admission retains the existing
ownership, halt, freshness, account and governor requirements.

`delivery.rearm(event_sequence, reason, now=...)` is an explicit trusted-local recovery
operation for EXHAUSTED alerts only. It audits the reason, keeps the exact ID/payload
and cumulative attempt history, and grants one more bounded batch. There is no HTTP
rearm route or automatic rearm. An overdue alert stays entry-blocking until its exact
receipt is confirmed. This action cannot acknowledge alerts, clear a dispatch halt,
release orders, change policy or call the model. Operator ACK_ALERT remains separate
and does not suppress delivery; delivery does not automatically acknowledge or resume.

Verification adds **59 tests**, including actual loopback verified-TLS child calls,
lost/foreign/duplicate/malformed/oversized receipts, redirects, retry spacing and caps,
private tokens, CA verification/change rejection, duplicate owners, repeated
cancellation, actual parent crash/watchdog cleanup, leases, storage failures, restart,
read-only idle polling, audited rearm, backlog/model/BUY gates and protective exits.
The installed wheel also passed a native HTTPS sink/journal restart proof under
optimized Python and warnings as errors: two identical requests yielded one durable
sink receipt, both children were reaped, restore authority stayed VERIFIED, private
files and read-only bytes passed, and halt/ack state stayed unchanged. There were zero
broker/model calls. Deployed sink provisioning, real notification routing, credential
lifecycle and off-host alert/restore availability remain unproven.

## Private execution evidence checkpoints

See [EXECUTION_CHECKPOINTS.md](EXECUTION_CHECKPOINTS.md) for the opt-in paired export,
strict independent-pin verification, bounded isolated archive client and quarantine-only
recovery commands. The tool copies journal/authority under retained writer locks without
advancing source authority, preserves unresolved orders/costs/halt/credential evidence,
and never produces a normal executable restore pair. A separate installed TLS archive
proof deletes all original state before retrieval; this is simulated source loss.
Actual off-host deployment, latest-generation witness retention, host power-loss behavior
and authenticated active-state recovery remain unproven. The deployed SHADOW database,
backup cron and credential files are not altered by these commands.

## SignalFlow adaptation and remaining engineering

Fresh GitHub inspection confirms SignalFlow `main` remains
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Relevant primary sources:

- [Broker capability and snapshot contract](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/portfolio_brokerage.py).
- [Order reservations and reconciliation](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/portfolio_reconciliation.py).
- [Durable broker ledger](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/portfolio_broker_store.py).
- [Partial-fill and rejection/recovery tests](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/tests/test_roadmap_phase20_broker_reconciliation.py).
- [Stop authority](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_stop_authority.py).

The implementation adapts persistent reservation ownership, capability separation
and authoritative reconciliation. It strengthens the missing-order boundary:
elapsed reservation time never releases an attempted order without terminal evidence.
It uses Decimal, one long equity/ETF position and the current governor rather than
SignalFlow's float-based option/multi-bot coordination or AI narration rules. There
is no SignalFlow runtime import, second worker or change to that repository/server.

Before this can back any real executor, prove actual Robinhood identity/idempotency,
order precision/minimums, status and fill-history coverage, partial fills, rejection,
cancellation and ambiguous-response semantics. A fresh open-orders list alone is
insufficient. This fixture snapshot requires complete history for all attempted
orders and known fills, including terminal outcomes; a future adapter must supply
and prove that evidence without truncation or guessed identities. The in-memory
fixture survives journal reopen only within its process; the separate durable fixture
persists independently. Neither is real brokerage capability evidence.

Then verify deadlines with the actual broker adapter and implement independent live enablement, actual-account
identity pinning and verified bankroll controls, real-adapter owned-position reconciliation,
deployed stop/session supervision, authenticated verification/adoption of model receipts,
invoice/noncharge recovery, external alert delivery and
deployed authenticated operator recovery. The local capability/outbox above must
also gain secure transport, off-host/multi-host restore fencing and host failure
verification before use.
Test these independently before connecting them to a live capability.
The deployed SHADOW worker and its continuing market-session verification stay on
their current release; no server update is needed for this offline slice.

## Scheduled fixture PAPER service

The opt-in [PAPER runtime](PAPER_RUNTIME.md) connects the exact durable fixture engine,
quotes, independent supervision, bounded judgment and fake dispatch under one lifetime
lease. Claims persist before model calls, current slots are attempted once, and unknown
or interrupted evidence never replays. Stopped/stale runtime authority blocks entries
and model receipts while protective SELL retains its existing guard policy. Native
CLI initialization, fixture publication, run and read-only reporting are separate from
the deployed SHADOW worker; no real broker write adapter or automatic fills exist.
