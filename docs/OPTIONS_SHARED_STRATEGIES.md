# Shared Degen and Swing PAPER owner

This opt-in P7 slice implements a shared candidate boundary for the first Swing
adaptation and the existing Degen setups. One `OptionExecution`, lifetime lease,
virtual cash ledger, reservation, five-minute decision claim and model budget own
both families. The full entry model receives both families in one packet and may
choose one supplied candidate or HOLD. Families never launch separate execution
workers or divide the same bankroll into hidden subaccounts. Independent research
comparison accounts remain independent.

The user reinforced this shared-engine direction on October 12. It follows the
existing one-trader contract in [the source of truth](SOURCE_OF_TRUTH.md), rather
than creating a second autonomous Swing trader.

New native entries now freeze their selected strategy/setup and candidate hash in
intent and approval. Dispatch and stored attribution verify that identity; exact
closes and management charges inherit it from the buy. See
[frozen strategy entry identity](OPTIONS_POSITION_OUTCOME.md#frozen-strategy-entry-identity).
Historical unlabeled orders remain unlabeled, and family loss/reset enforcement
is delivered through the separately enrolled [native loss guard](OPTIONS_NATIVE_LOSS_CONTROL.md).

## Delivered family and evidence

`app.options.swing` defines `swing-next-session-v1`, an explicitly smaller
`SWING_DAILY_BREAKOUT` adaptation. It requires a frozen lookback of three to twenty
complete consecutive regular-session daily OHLCV bars, with observed positive
volume and split-adjustment identity. Actual XNYS opens/closes validate every bar,
including holidays, DST and early closes. Daily closes must progress strictly in
the purchased CALL/PUT direction. The final daily high/low supplies the breakout
reference; its opposite extreme and frozen buffer supply original invalidation.

A `SwingSeed` contains that history, the exact option instrument, creation time
and next actual exchange session. The final completed bar must belong to the
immediately previous exchange session. Source/receipt/creation clocks must place
the recorded seed after that close and before the target open. A new strike,
expiry, provider mapping or history cannot replace a seed once recorded in a
cycle for that symbol/session. The full seed and hash persist inside the existing
paired restore fence. These are supplied fixture timestamps, not proof that an
external provider actually captured them at those instants.

Each entry cycle also needs valid current completed five-minute evidence. At least
six completed bars and the last two closes beyond the daily boundary confirm a
break and hold. The current price must remain within the frozen chase limit.
Fresh, complete, REALTIME catalyst evidence must explicitly say CLEAR through the
current exchange close; missing, blocked, unknown or expired clearance cannot
supply a Swing candidate. There is no inferred earnings clearance for a stock and
no assumption that missing ETF catalyst coverage means clear.

Only the locked contract is requested. Frozen minimum/maximum calendar DTE,
standard supported identity, observed correctly signed delta, quote/metadata
freshness, strike distance, volume/open interest and all existing whole-contract
funding/risk rules apply. Current chain contents cannot substitute a contract.
The shared quote ceiling remains eight: each frozen symbol reserves its configured
Degen shortlist capacity plus one locked Swing contract. One or two frozen SPY/QQQ
symbols remain supported in this first adaptation.

## Shared execution and AI

`DegenCoordinator` retains its historical API name and accepts optional
`swing_policy`; this is the same coordinator and journal, not a second worker.
`DegenFrame.swing` carries one `SwingInput` per frozen symbol. `quote_plan` takes
that tuple as its third optional argument and remains read-only. Missing entire
seed coverage blocks the joint cycle explicitly. A supplied but ineligible Swing
seed retains its blockers while valid Degen candidates may still compete.

Scans and read plans stay paired by family and symbol; a Swing scan cannot replace
Degen's scan merely because both concern SPY. Frozen family priority determines
model-off ordering. AI mode requires the full entry-reasoning contract, not the
old Degen-only SELECT/HOLD prompt. It receives a single bounded packet containing
family-specific scans, exact evidence IDs, quotes and reproducible admissions.
No candidate grants quantity or independent execution authority.

Preparation and dispatch both recheck stored selected-candidate membership. Swing
also rechecks its persisted seed lock, target session, current break/chase and
catalyst expiry. A completed model call remains charged if fresh review rejects
its proposal. Unknown cost fences the common account, so another family cannot
bypass the loss/budget halt. All entry and management charges retain the existing
accounting and proposal/review/fill attribution. Venue fees remain in the same
cash-conserving ledger; data/host allocations and unknown expenses retain the
existing evaluation rules. There is no per-family fee-free alternate route.

A held or unresolved contract takes precedence over candidate collection. One
working order reserves the common account. Faster deterministic supervision still
runs independently of the model and rejects closes without authoritative ownership.
The stored observer exposes joint cycles and filtered Swing/Degen candidates;
family filtering never performs market/model/order work or removes common costs.

## Enrollment and installed use

### Terminal completed-bar invalidation

New populations may explicitly set
`SwingPolicy.unfilled_lifecycle="completed-invalidation-v1"`. This closes a
reproduced pre-entry lifecycle gap: the earlier scanner could confirm a recovered
breakout even when a completed target-session bar had already crossed the original
daily invalidation. The pinned [next-session promotion contract](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/swing-next-session-promotion.md)
makes invalidation terminal. This adaptation uses the existing validated completed
five-minute evidence, without another provider or execution worker.

For a CALL, a completed bar's low at or below the original buffered daily stop
retires the seed; for a PUT, its high at or above that stop does so. The first
qualifying bar wins. The original rounded stop, seed/history hashes, bar completion
time and observation time are retained. Stale, foreign, gapped, interpolated or
uncompleted evidence cannot establish an invalidation. Missing catalyst clearance
still blocks entry, but does not erase an otherwise observed structural failure.

Read planning projects this evidence without writing. An unheld native cycle
retains it in `execution_option_swing_terminals` and a `SWING_SEED_TERMINAL` event,
inside the same fenced journal, before quote-coverage review or any paid entry
call. Both preparation and dispatch reject a terminal selected Swing seed. A
previously paid call stays charged when this guard rejects its proposal. Retained
invalidation survives restart, price recovery and later revised history; it is
never replaced by a later expiry. Another family or independent population does
not inherit that seed's block. A fresh actual-session seed has its own identity;
the existing same-session contract/history lock remains mandatory.

When an unheld cycle revisits a valid supplied seed at or after its target XNYS
close, seed locking records `EXPIRED` if no earlier terminal evidence exists.
This uses the actual exchange close, including half days. It does not create a
background expiry service or process absent seeds; calendar admission already
blocks entries outside that target session. Held or unresolved orders continue
through the existing ownership/protection path.

Stored opportunity observations expose the terminal reason, trigger/observation
times and original stop in the authenticated observer. The retained cycle input
contains the corresponding history. These are historical observations, not live
signals or provider attestations. Shortlist replay rebuilds invalidations from
only the visible cycle prefix, preventing revised later histories from reviving a
seed. That account-free market diagnostic does not reconstruct ownership; native
A/B/C/D replay retains each actual owner's journal and every entry/management cost.

This policy does **not** add quote-tick invalidation latching, an unfilled T1
consumption rule (the current seed has no frozen T1), new setup families or
overnight holding. Current quote/chase checks and mandatory filled-position exits
remain independent. These remaining Swing requirements must not be inferred from
this narrower completed-bar lifecycle proof.

The option is omitted from legacy serialization when absent; existing population
and tape hashes remain unchanged. Enabling or changing it requires a new frozen
population. It is not automatically enabled in examples or the deployed experiment.

### Observed quote invalidation

A separate new-population policy,
`SwingPolicy.unfilled_lifecycle="observed-invalidation-v2"`, includes the completed-bar
behavior and closes the between-bar quote gap. An observed price breach can no
longer disappear when price recovers before the next completed-bar entry cycle.
The original v1 policy keeps its original behavior and serialized records.

The quote must be complete, REALTIME, from the owner's frozen underlying source,
for the exact seed symbol and target XNYS session. Source/receipt clocks must pass
the existing quote-age and receive-lag limits; future, stale, crossed, below-floor,
foreign and duplicate-symbol evidence cannot establish retirement. CALLs use bid
at or below the original buffered daily stop; PUTs use ask at or above it. Exact
touches count. The retained terminal contains the full typed quote, original stop,
seed hash, source trigger time and observation time. It has no fabricated completed
bar/history hash. First retained terminal evidence still wins.

The existing fast coordinator supervision path observes supplied underlying quotes
before its asynchronous protection work. Native entry cycles also observe their
frame after locking seeds and before candidate/model work. A stored position or an
already-attempted/uncertain active order keeps its existing ownership/protection
path; its seed is not retired by this unfilled observer. An unattempted PREPARED
intent can lose seed eligibility, so its later dispatch is rejected. This introduces
no cancellation, resubmission, synthetic fill or assertion that an unresolved order
is flat. Filled-position mandatory exits remain independent.

Preparation and dispatch also inspect their fresh underlying quote against the
original daily stop. A newly observed breach is committed with the terminal evidence
and rejection inside the existing native transaction. A completed paid model call
stays charged even when this last review rejects its proposal. No new model call,
provider request or execution worker is introduced.

Native replay delivers newly recorded MARKET quotes to the same unfilled observer;
it does not manufacture observations from timer wakes or cached quotes. Account-free
shortlist replay reconstructs quote retirement only from its visible input prefix,
including MARKET events between cycles. That diagnostic has no ownership ledger
and cannot decide whether a native account was already held or attempted. Native
replay retains those independent account differences and all actual recorded costs.

Between-cycle quote evidence is retained immediately in the native terminal/event
journal. Subsequent stored opportunity scans and observer history include the full
terminal; historical opportunity rows remain observations from their own cycle.
Reading the dashboard does not sample quotes or advance lifecycle state. Authentic
provider data and actual browser visual acceptance remain separate gates.

This closes observed-quote invalidation for the existing session-close Swing
adaptation. Unfilled T1 consumption, new setup families, overnight lifecycle and
full Swing acceptance remain open. Missing observations never imply an unbroken
live price path or a proven trading edge.

### Population creation

Only a new population may enable or change `swing_policy`. Existing frozen Degen
settings and frames omit the optional fields, preserving their serialized hashes.
Existing A/B/C/D replay cohorts are unchanged. New optional
[joint-family replay enrollment](OPTIONS_SHARED_REPLAY.md) freezes Swing policy in
the common tape and compares independent accounts without changing old cohorts.

[options-local-runtime-shared.json](../examples/options-local-runtime-shared.json)
is a model-off configuration example with explicit fixture values. Replace paths,
population identity, evidence sources and approved PAPER policies before enrollment.
It supplies no market data and must not be used as a statement of live limits.

```bash
python -I -m app.options.runtime_cli init \
  --settings /absolute/private/shared-settings.json \
  --directory /absolute/private/new-shared-population
python -I -m app.options.runtime_cli run \
  --directory /absolute/private/new-shared-population --seconds 60
```

The same optional operator capability and full-entry/position model settings are
available as described in [local runtime](OPTIONS_LOCAL_RUNTIME.md) and
[reviewed recovery](OPTIONS_OPERATOR_RECOVERY.md). Model and operator credentials
remain separate; none belongs in packets, fixture examples or Git.

## Acceptance boundaries

This is **session-close PAPER fixture capability**, not complete Swing acceptance.
`holding_policy` accepts only `SESSION_CLOSE`. Existing deterministic close/expiry
and model target/horizon cutoffs still apply even when the locked option expires
later. No overnight position, holiday carry, exercise funding or overnight risk
policy is granted. Broader Swing families, authentic daily/catalyst/option inputs,
overnight lifecycle/evaluation, Scope/SPXW and mixed stock/options arbitration
remain separate P7 work. The first next-session family shares Degen's current
intraday management context; it does not claim an implemented overnight Swing
management model or replicated SignalFlow economics.

The separate [Scope preflight](OPTIONS_SCOPE_PREFLIGHT.md) now checks required
coverage and exact SPXW identity. It does not enroll Scope in this shared owner,
change the existing candidate universe or implement Scope setup/management.

The reference is the already pinned SignalFlow
[`swing_entry_selection.py`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/swing_entry_selection.py),
blob `07530bd70832835389f683a6cac49aea5982d3a2`, re-read for this implementation.
Its contract lock, chase, completed confirmation and catalyst concepts are adapted;
weekday/clock shortcuts and floating-point authority are not copied. This is not
another strategy research pass or a performance claim.

`tests/test_option_shared_strategy.py` covers shared native entry/protection,
CALL/PUT geometry, AI choice of either family, known/unknown model costs, bounded
worker and installed CLI, immutable locks, calendar edges, evidence failures,
current dispatch gates, frozen enrollment and stored family filtering. Exact final
installed regression evidence is in [status](SLICE2_STATUS.md). Provider, host,
prospective economics and dashboard visual acceptance remain open. Main, PR draft,
LIVE-disabled state and the deployed frozen experiment are preserved.
