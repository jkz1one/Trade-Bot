# Durable options PAPER lifecycle

M2 local lifecycle core, 2026-10-09 UTC. Builds on [M1 admission](OPTIONS_ADMISSION.md)
and reuses the existing SQLite journal, paired restore fence, lifetime ownership
lease, bounded child cleanup, exchange calendar and model usage contracts.
This is an isolated **local fake venue**, not a brokerage adapter or deployed service.

## Delivered API and authority

`app.options.lifecycle` defines explicit frozen `OptionExecutionPolicy`, DAY-limit
`OptionIntent`, whole-contract `OptionFill`, complete `OptionObservation`, FIFO
`OptionPosition`/`OptionLedger`, settlement receipts and fixture snapshots.
Money uses bounded Decimal inputs and independent arithmetic precision. Stock
quantity, ledger and journal schemas cannot adopt an option database.

Provision `DurableOptionVenue(path, limits=limits, capital=policy.capital)` once.
Enter `OptionExecution.open(journal_path, limits, policy, venue, now=now, create=True)`
for a new named population, then reopen with `create=False`. Provisioning refuses
existing journals/authority; reopening requires both private owned files and the
exact frozen configuration/venue binding. The lifetime lease precedes startup
recovery and remains held through child cleanup. A closed owner cannot mutate state.
Missing or stale authority is never silently recreated or rebound.

The engine's public methods are trusted **local orchestration APIs**. They are not
model tools or an authenticated network control surface. Use the executable examples
in `tests/test_option_execution.py` for complete explicit fixture configurations.

| Operation | Durable behavior |
| --- | --- |
| `reconcile_fixture(now=...)` | Bounded fixed native child reads the private fake venue; changed concurrent state supersedes the read |
| `reconcile(snapshot, now=...)` | Adopts only complete immutable binding, order, fill and receipt history that reconstructs exact cash/position truth |
| `assess(quote, underlying, now=...)` | Records independent fresh supervision, tightened/original invalidation, premium catastrophe and fixed time/expiry exits |
| `prepare(source, proposal, quote, underlying, now=..., origin=...)` | Persists HOLD/rejection or one fixed-price/quantity intent with its approval/evidence/reservation |
| `dispatch(client, quote, underlying, now=...)` | Re-admits fresh authoritative inputs, commits SUBMITTING before the one native attempt, never replays attempted clients |
| `protective_tick(quote, underlying, now=...)` | Reconciles, supervises, and prepares an eligible deterministic owned close without a model call |
| `tighten_invalidation(...)` | Preserves the original stop and rejects widening/crossing or erasure of a latched exit |
| `resume(reason, expected_revision=..., now=...)` | Explicit local reviewed recovery requires current revision, fresh reconciliation/supervision and no unresolved attempt/cost |
| `begin_model_attempt(...)` / `record_model_usage(...)` | Stores an attempt before external orchestration, retains unknown cost, binds immutable usage/proposal receipts and freezes configured cost budgets |

Model proposals cannot supply cash, sizing, limits or authority. MODEL-origin
decisions require the matching known usage/proposal receipt; all HOLD costs remain
recorded. This module does not call a model. Known costs reduce loss allowances,
remain separate from venue cash, and are not proof of provider billing. Unknown
costs block new entry. Flat healthy model admission also requires fresh account
truth and an actual eligible regular session.

## Fills, reconciliation and uncertainty

Entry consumes eligible ask plus adverse tick-rounded slippage; close uses bid
minus slippage. Whole partial fills retain complete quote evidence, source times,
size, fees and global sequence. One quote's observed size cannot be reused by
changing Decimal scale. Entry fees apply once per order plus per contract. Before
entry the governor reserves **one closing order fee per contract**, since the bid
may permit only one-contract closes. This is more conservative than M1's one-order
closing assumption and is stored as effective admission policy.

BUY debits settled funds; sale credits stay unsettled until an explicit authoritative
funds receipt. FIFO lots, gross realized P&L, every fee and daily net P&L reconstruct
from the frozen capital and complete chronological history. Actual fills from an
already-attempted partial BUY still must be accounted for after a stop latches;
they do not authorize a new buy or averaging down. Unknown or working orders keep
the single active reservation and block another attempt/entry.

The engine rejects changed/missing fill IDs, omitted attempted orders/receipts,
regressing/duplicate order identity, invalid sequence/time, changed exact terms,
unfunded or oversold quantity, invalid quote price/size/fee, and reconstructed
cash/settled cash/lot/position mismatch. Rejection preserves prior usable ledger and
records rejected snapshot evidence, halt and alert outbox. Absence never proves
an attempted order failed or a position became flat. Successful reconciliation
does not automatically clear a halt.

Attempts use only `python -I -m app.options.worker`, with a fixed private fixture
protocol, bounded input/output and stripped environment. The original approval's
remaining lease caps admission-to-child time; spawn delay cannot renew it. Native
timeouts, invalid/lost/oversized acknowledgments, crashes and cancellation retain
UNKNOWN and the reservation. Children are reaped before normal ownership release.
Startup converts interrupted SUBMITTING to UNKNOWN. No retry or live broker write
is hidden behind this state.

## Management and expiry boundaries

Call invalidation uses underlying bid; put invalidation uses underlying ask.
Premium catastrophe uses executable bid against owned premium basis. Original
invalidation, deterministic tightening, fixed exit time and expiry guard persist
independently of proposal HOLD, model availability, rebound and restart. Missing
or stale executable evidence records unpriced exposure and halt; it never fabricates
a fill. One contract cannot scale out fractionally. After a completed size-limited
close, a distinct close can address actual remaining ownership. A rejected,
canceled or expired close requires review, with no automatic reprice/replay.

The first cohort's frozen time rule is **intraday**. `XNYS_REGULAR_INTERSECTION_V1`
uses the actual XNYS holiday/DST/early-close calendar, then clamps the exact supplied
contract last-trading instant and configured cutoffs. It is a conservative regular
hours intersection, not authenticated CBOE/index session or brokerage cutoff proof.
AM/PM contract metadata and settlement receipts are explicit; exchange-specific
last-trading times must come from a subsequently accepted source. Overnight Swing
and authentic SPXW/Scope calendar/feed behavior remain separate M7 gates.

Time alone does not remove expired exposure. Only exact complete authoritative
worthless-expiry or cash-settlement receipts can close the ledger without trading.
Cash settlement checks intrinsic value, multiplier, owned quantity and explicit
settlement instant. Physical exercise is never requested. A scripted exercise-created
stock holding, negative funding or short stock is retained as rejected venue evidence,
halts new admission and preserves the prior option authority for review. It cannot
silently become permitted equity exposure.

## Proof and remaining integration

`tests/test_option_execution.py` exercises positive calls/puts, exact partial-fill
and settlement accounting, single-contract allocation, independent exits/restart,
bad/missing authority, model costs, short admission leases, native cancellation and
an actual SIGKILL owner/child recovery. The latest full installed-package counts and
wheel digest are in [SLICE2_STATUS.md](SLICE2_STATUS.md).

Local fixture acceptance does not close provider or host gates. No authenticated
option feed/account/preview, real model invocation, billing verification, real order,
exercise or cancellation occurred. Existing equity runtime/control/alert/checkpoint
commands are not option service adapters. M2 outbox is durable local evidence;
independent delivery and options archive/runtime enrollment remain unaccepted.
The mixed stock/options selector, Degen strategy, observer UI and actual-host
installation remain later milestones. Do not run this separate fixture owner against
an equity service's bankroll or claim shared live authority. The deployed synthetic
population stays frozen, LIVE disabled, main untouched and PR #1 draft.
