# Durable unfilled Scope watches

Current extension: [native Scope execution/loss integration](OPTIONS_SCOPE_EXECUTION.md)
is available only to explicitly enrolled new PAPER owners. Existing research versions
retain the boundaries below. The native extension supports responsive/balanced
one-to-three-contract plans; convexity and missing-T3 four-contract plans stay blocked.

`app.options.scope_watch.ScopeWatchBook` persists the first called-play layer in
an existing `OptionExecution` journal. This is an explicitly enrolled **research
watch workflow**, with false trade/LIVE authority. Its research admission, management
and replay paths do not enroll Scope in the trading runtime or native entry dispatch.

`ScopeWatchPolicy` freezes the complete context/structure/preflight policy and an
explicit daily call ceiling of one or two. The source ceiling is two called plays,
including watched plays that never fill. See the pinned
[Scope V2 playbook](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/SCOPE_WIZARD_SPXW_PLAYBOOK_V2.md).
Research configuration does not approve LIVE limits.

## Enrollment and ownership

The book requires the built-in lifetime-owned PAPER engine, SPX in its allowed
universe, and matching provider/option-quote source. Enrollment requires a healthy,
fresh, reconciled, funded and supervised empty account without an entry halt,
unsupported exposure, unknown budgets or exhausted global loss allowance.

It is available only before native orders, model calls, option decisions,
opportunities or runtime records exist. Subsequent watch mutations reject such
history too: this version cannot safely link a watch to a native entry or claim
that a traded position remained unfilled. Reopening for inspection does not erase
history. Existing Degen/Swing populations are not enrolled or migrated.

The Scope calendar stays the explicit reviewed index-calendar input. Matching the
owner's provider does not authenticate this calendar or silently substitute the
owner's XNYS calendar for SPXW acceptance.

Three `execution_option_scope_watch_*` tables live in the same journal, under the
existing lifetime lease, SQLite transaction and paired restore fence. There is no
second worker, cash ledger, account or cost calculator. A journal-only rollback
is rejected while the current authority file survives; simultaneous rollback of
both files and hostile filesystem access remain outside that mechanism.

## Calls and locked evidence

`call(key, choice, frame, context, expected_revision=..., now=...)` recomputes the
complete [context review](OPTIONS_SCOPE_CONTEXT.md) at the supplied aware clock.
The exact pattern, parent and CALL/PUT alternative must be uniquely `DETECTED`,
with no global context issues. This is sufficient for cohorts without quality enrollment.
[Optional quality review](OPTIONS_SCOPE_QUALITY.md) now gates new explicitly frozen
watch cohorts and locks its complete original scan. It must share the exact context
policy; older cohorts remain unchanged. [Optional sampled arming](OPTIONS_SCOPE_ARMING.md)
now persists fresh-evidence holds for explicitly enrolled cohorts. Complete obstruction
coverage and execution admission are still required to trade.
[Optional contract profiles](OPTIONS_SCOPE_CONTRACTS.md) now add current exact-contract
checks to calls and arming samples for newly enrolled cohorts.

The record locks the full original frame, typed context, scan, geometry, exact
instrument, session and called time. A context variant retains its parent. The
state is `WATCHING`; no size, order price, fill, P&L or win/loss is inferred.

Only one watch may be active. Every successful call consumes that session's count,
even when later invalidated or expired without a fill. There is no delete/reset or
manual cancellation API that refunds calls. A new call in the same session must
retain the exact session and all previously reviewed bars, and use a strictly
later completed bar than every previous watch's reviewed endpoint. Correlated
variants cannot repeatedly reuse an already reviewed bar as new opportunities.

Without explicit `direction_reset` enrollment, opposite-direction calls retain
`SCOPE_WATCH_DIRECTION_RESET_NOT_IMPLEMENTED`. Omitting this optional policy keeps
the original serialized policy and behavior. Existing populations cannot enable
it on reopen; it belongs to a new frozen research cohort.

## Optional durable direction reset

`ScopeDirectionResetPolicy` requires explicit `cooldown_seconds` (600–3600) and
`confirmation_bars` (2–5). These preserve the pinned ten-minute/two-bar source
baselines as minimums. The cooldown starts when neutral is actually recorded,
not at a backdated price crossing. This is a conservative unfilled-watch adaptation;
source quality/arming hold rules and filled-position loss controls remain separate.

After `INVALIDATED_UNFILLED`, `neutralize(key, play_key, frame,
expected_revision=..., now=...)` records a separate software state with no retained
directional permission. Neutral does not claim a particular price zone. It requires
no active watch, the latest play in that session, unchanged instrument/session and
history, fresh structure coverage, and a completed bar later than the time the
invalidation was processed. A bar already complete at invalidation cannot perform
this step. Expired, objective-consumed or still-active watches cannot be neutralized.

The neutral frame, structure scan and actual recorded time persist in the original
record. Its invalidation classification, original geometry and called-play count
remain intact. An exact retry returns its original receipt; a second neutral
transition is rejected. Cleanup can record neutral while halted, but cannot clear
the halt or grant permission for another call.

An opposing call then requires the full current context review and a selected
`REVERSAL` parent/class, elapsed cooldown, and the configured number of completed
SPX bars **whose start is at or after the recorded neutral time**. A bar already
underway at reset does not count. Current completed structure and SPY/QQQ
confirmation still determine whether the reversal is detected; merely waiting or
supplying more bars does not create one. Context variants retain the same reversal
parent requirement. The exact cooldown boundary is allowed. Daily call limits,
all prior history prefixes, fresh owner readiness and global controls still apply.
No order or filled-position direction flip is enabled by this research state.

## Advancing a watch

`advance(key, play_key, expected_revision=..., now=..., frame=...)` accepts no
caller-supplied status, P&L, outcome or replacement geometry.

Before the original exclusive entry cutoff, it requires a fresh complete frame,
recomputed structure coverage and technical/confirmation payload bindings, the
same exact instrument/session, unchanged SPX/SPY/QQQ history prefixes and at least
one new completed bar. It reviews **every** new SPX bar in chronological order
against the original geometry:

| Observation | Persisted state |
| --- | --- |
| CALL low at/below original invalidation, or PUT high at/above it | `INVALIDATED_UNFILLED` |
| CALL high at/above original second objective, or PUT low at/below it | `OBJECTIVE_CONSUMED_UNFILLED` |
| Neither | `WATCHING` |
| Clock at/after the original entry cutoff | `EXPIRED_UNFILLED` |

The first crossing's bar end and the time the evidence was processed are stored
separately. If invalidation and objective occur in the same bar, invalidation wins;
OHLC evidence cannot establish their intrabar ordering. A later rebound cannot
hide an earlier crossing. These are watch classifications, never simulated fills
or profitable/loss-making outcomes. The review does not reevaluate current
flow/news to grant an entry; it only consumes bound completed price evidence.

Cutoff expiry needs no fresh feed and remains possible during an account halt.
It takes precedence over a supplied frame, records no inferred crossing bar, and
makes no claim about the missing market path. Missing/stale data before cutoff
leaves the watch active. Native execution history blocks advancement rather than
falsely marking a potentially traded watch unfilled.

## Optional observed-quote lifecycle

New watch cohorts may freeze `quote_lifecycle="scope-observed-quotes-v1"`.
Omitting it preserves existing completed-bar behavior and serialization; a book
cannot enable or change this policy on reopen. This closes a reproduced admission
gap: a fresh quote at the original invalidation previously rejected sizing but
left the watch active, allowing later recovery samples to re-arm the same play.

`observe_quote(key, play_key, underlying, expected_revision=..., now=...)` records
one supplied SPX quote without requesting a provider, account refresh, option quote,
model call or order. Enrolled `review_admission()` performs the same observation
before account readiness, arming or context checks. A valid original-price breach
therefore persists even when admission cannot proceed. Native trading/model history
still blocks these unfilled-watch mutations; this never relabels a held trade.

Only complete REALTIME SPX quotes from the owner's frozen underlying source are
accepted, with uncrossed positive prices, existing age/receipt-lag bounds and source
time no earlier than both the call and last reviewed completed bar. Accepted source
clocks cannot rewind. Identical original quotes may be reread while still fresh;
changed content at the same source timestamp is rejected, and later receipt times
cannot make an old source observation new.

| Fresh observed boundary | Terminal status |
| --- | --- |
| CALL bid at/below the original stop, or PUT ask at/above it | `INVALIDATED_UNFILLED` |
| CALL bid at/above the locked second objective, or PUT ask at/below it | `OBJECTIVE_CONSUMED_UNFILLED` |
| Clock at/after the locked entry cutoff, even without a quote | `EXPIRED_UNFILLED` |

The first objective retains its separate current-price admission gate; this does
not replace Scope's settled second-objective terminal rule. A wide spread cannot
establish a target using only CALL ask or PUT bid. Cutoff takes precedence over a
supplied quote. Terminal quote evidence retains the exact quote, original geometry,
owner-limit hash and actual observation time, with no fabricated crossing bar.
The first recorded terminal state cannot be revived, overwritten or refunded.
A new call key in the same session must use a completed bar strictly later than
the recorded terminal quote time. Changing the key cannot reuse a bar that was
already complete when the prior watch was invalidated.
Existing neutral/reset rules still require a later completed bar, cooldown and
fresh reversal confirmation; the original quote remains attached through neutral.

Missing/stale/foreign/conflicting quote evidence records a rejection and resets
an enrolled arming hold without fabricating a price terminal. A quote-only action
removes an earlier admission review, and never extends or progresses the hold.
A valid nonterminal quote preserves only the existing dated hold state. Later
admission still requires all fresh frame/context/account/quote/path checks.

Action receipts, quote watermark, terminal state, active lock and audit commit
atomically. Exact retries retain historical receipts; current state is read through
`snapshot()`. Stored observer output exposes `quote_review` and `terminal_quote`
with historical/future labels after validating their original record/action binding.
Reads never poll, advance, re-arm or approve the watch. The research replay accepts
`OBSERVE_QUOTE` steps, and its portable verifier reproduces them from the frozen
request hash without changing the original files.

No called-play count, cash, fees, fills, entry/management charges or native execution
authority changes. This is observed fixture lifecycle evidence, not proof of an
uninterrupted market path or authentic feed acceptance.

## Durable actions and reads

Every action carries the exact journal revision. Successful action keys bind the
full request, including time, evidence and revision. An identical retry returns
its **original historical receipt**, even after subsequent state transitions;
`snapshot()` supplies current stored state. Changed reuse conflicts. New actions
reject stale revisions and clocks earlier than the book's last successful action.
State, call count, receipt and audit event commit atomically. Rejected requests
consume no call or event. Arming observations with valid request envelopes persist
evidence failures as reset events; they never consume another called play. Concurrent writers cannot both claim the same revision.

The unique active row, full records, action receipts and frozen policy survive
owner restart. A later explicitly supplied session starts its own count while
retaining old records; an old active watch must first be expired explicitly.
`snapshot()` reads stored state only. It never polls a provider, advances time,
expires a watch or mutates journal/authority files.
The separate [stored observer](OPTIONS_OBSERVER.md#scope-research-visibility) now
projects selected original/latest quality and contract evidence after checking each
visible watch against its latest action and receipt. Its missing/stale labels and
collapsed decision details grant no fresh eligibility or execution authority.

The [research lifecycle replay](OPTIONS_SCOPE_REPLAY.md) now exercises these native
watch methods from frozen ordered fixtures in a new isolated owner, with saved
receipts and explicit rejection/interruption evidence. It does not create fills or
enable Scope trading runtime enrollment.

## Still required for Scope execution

Filled-position direction handling, actual position linkage, full-cost native
outcome attribution, consecutive-loss/cooldown and reviewed family-reset controls,
complete obstruction coverage, shared-owner admission/management, runtime enrollment,
stored dashboard integration and full-cost replay remain open. Loss controls must
use verified native fills plus **all entry and management charges**; watch states
cannot substitute for that evidence. Existing independent A/B/C/D accounting is
unchanged, and unknown costs remain unknown.

Authentic normalized provider data, reviewed SPXW calendars, host acceptance and
prospective economics remain separate gates. See [status](SLICE2_STATUS.md) and
[source of truth](SOURCE_OF_TRUTH.md). Main stays untouched, PR #1 draft, LIVE
disabled and the deployed experiment frozen.

[Optional owned admission review](OPTIONS_SCOPE_OWNED_ADMISSION.md) now refreshes
armed evidence and records common-governor sizing from the same account. It adds
no order, reservation, native execution linkage or trade authority.

The [native execution boundary](OPTIONS_SCOPE_OWNED_ADMISSION.md#native-execution-boundary)
now rejects generic native OPEN_LONG preparation and dispatch while a Scope research
book is enrolled. HOLD and owned/protective exits retain their existing rules.
