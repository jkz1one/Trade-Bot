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
a remote control service. The fixture engine still requires independently invoked
position supervision, refreshed account/market evidence and governed dispatch.
Actual authenticated API validation, discount/invoice adjustments, verified no-charge
resolution, deployed orchestration and independent supervision remain pending.
No new deployed cohort, API request or server update occurs when importing/enrolling
this opt-in interface. Tests and package proof use mocked SDK HTTP responses only.

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
