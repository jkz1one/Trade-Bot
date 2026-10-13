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
