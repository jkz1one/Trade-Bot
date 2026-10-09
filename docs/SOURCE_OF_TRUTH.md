# Autonomous Compounding Trader: source of truth

Version 1.1. Adopted product direction and working delivery contract, 2026-10-09 UTC.
M1 offline admission is fixture verified; next is M2. Scope and milestone order unchanged.

## Goal and definition of completion

Build one autonomous reasoning trader that can select **US stocks/ETFs or purchased
options**, manage one position and remain in cash when evidence is weak. Adapt
SignalFlow's Degen/0DTE, Swing and Scope Wizard strategies and interface into this
smaller auditable engine. Deliver PAPER validation, then a concrete governed path
to limited LIVE operation. Trading capability and profitability are separate:
completion means verified bounded operation, not guaranteed gains or a promised
daily income. SPY remains the economic benchmark.

The user approved the expanded stocks/options and eventual LIVE goal. The initial
single-leg options scope, milestone contracts and UI layout below are working
engineering decisions for delivering it. Actual LIVE capital/loss limits, account
capability and activation remain unresolved. This document does not authorize real
broker writes or silently replace the deployed experiment's configuration.

This document owns current scope and implementation order. Latest explicit user
instructions take precedence. README is the entry point, research explains the
decisions, and status/evidence documents record observations. Older stock-only
continuations remain historical. Code describes delivered behavior; a future goal
in this file must never be reported as implemented code. Record any discrepancy as
a blocker instead of quietly changing the plan or relabeling results.

## Rules that stay settled

1. HOLD is an ordinary, auditable decision. No minimum trade count, forced entry or
   threshold relaxation to make the bot look active.
2. The model proposes from supplied evidence. Deterministic software owns approval,
   rejection, quantity, exposure and exits. The Trader Agent has no broker tools,
   credentials, recovery authority or permission to alter risk settings.
3. One trader, one bankroll, one brokerage and one position across all setup families
   and instrument types. Several contracts of one approved option identity can be
   one position; different strikes, expiries or stock/options holdings cannot become
   hidden extra positions. Unresolved orders retain reservations and block new entry.
4. Initial options support is fully paid **long calls or long puts**, with sells
   limited to closing owned contracts. Bearish underlying direction is not short
   stock or permission to sell an opening option. No naked selling, multi-leg spreads,
   borrowing, averaging down, futures, crypto, OTC or penny stocks. Purchased options
   still have embedded exposure and can lose their entire premium.
5. Default PAPER; existing LIVE remains disabled. Real-account SHADOW retains its
   governed equity-review-only boundary. Options previews need their own validated
   schemas, account capability and deterministic admission. No generic tool allowlist
   expansion or automatic promotion to real orders.
6. Original invalidation cannot widen. Model HOLD, timeout, service restart or a
   rebound cannot erase an exit requirement. Supervision, halt controls and alerts
   operate independently of model judgment. Unknown fills/costs never become zero
   or assumed success; ambiguous attempts never automatically replay.
7. Freeze population identity, prompt/model, setup, selection, money/risk policy,
   execution assumptions and measurement versions. Changes create reviewed new
   populations or explicitly versioned future cohorts. Do not optimize from one day.

## Current delivered state and populations

| Population/surface | Actual state | What it cannot establish |
| --- | --- | --- |
| Deployed `virtual-v1` | Frozen $10 synthetic stock experiment on release `de5dd1c7bd3a2d3b85a2d6bb7f624e0d3a3f9245`; operator provides regular-session decisions, usage and simulated fills | Real broker fills, options behavior, useful signal, newer engine acceptance or profitability |
| Isolated execution engine | Durable fake-venue orders/model attempts, reconciliation, budgets, supervision, reviewed control/recovery, alerts, checkpoints and archive contracts implemented and tested locally | Actual target-host installation, authenticated full-universe/model evidence, independent archive retention or host-loss acceptance |
| Options foundation | M1 exact contract identity and deterministic whole-contract admission implemented and fixture verified; no option execution implementation yet | Options runtime PAPER readiness, provider/host acceptance or live safety |
| SignalFlow reuse | 60 pinned reference files audited; reusable strategy/UI concepts; draft management fixes distinguished from main | A ready live adapter, healthy deployed options feed or a replicated profitable strategy |

The legacy $10 population remains untouched. New options PAPER execution uses a
separate named identity and databases, with explicit virtual capital and limits.
Research comparisons may use separate simulated ledgers; they never grant several
owners access to a funded brokerage account. Do not reset, retune, pull or rebuild
the deployed SHADOW checkout. Its helper selects images by HEAD.

The [second operator report](SHADOW2_EVIDENCE.md) shows cumulative net equity
$9.95992452597485, net return -0.4007547402515%, SPY -0.453936060819% and net excess
+0.0531813205675 percentage points. It contains one new XLE round trip with
$0.0004482945831 price profit, while cumulative model costs increase $0.0139332.
Latest state is flat. This is another operational sample, not a reason to promote
or modify the frozen experiment.

## Instrument, evidence and risk contracts

Keep existing equity types compatible. Introduce explicit option identity containing
broker-independent contract ID, underlying, call/put, strike, expiry, multiplier,
deliverable, exercise style, settlement type/time and last trading instant. Provider
and broker identifiers map to that identity; a ticker or OCC string alone cannot
override conflicting metadata. Initially reject unsupported adjusted deliverables.

Quotes bind that exact contract and source feed, bid/ask/size, source and receipt
times, entitlement, coverage and delay status. Store underlying evidence separately.
Reject stale, future, crossed, missing or unsynchronized inputs using frozen limits.
Observed and estimated IV/Greeks remain labeled. No timestamp invented from the
current clock, indicative quote presented as executable truth, or current chain
substituted into historical evidence.

Money uses Decimal and option quantities are whole contracts. Software selects the
largest integer quantity that fits **all** frozen quantity, entry debit, available
settled funds, full-premium loss and account exposure caps, including conservative
fees/slippage. A planned stop-loss estimate is a separate diagnostic, never a
guaranteed worst-case loss. Quantity zero means HOLD/rejection; never round up to
afford one contract. Do not copy the legacy MICRO tier's 8% modeled risk and 50%
drawdown shutdown into LIVE options as presumed approved limits.

Underlying bullish/call and bearish/put geometry differ. Freeze original underlying
invalidation separately from premium catastrophe/time rules. One contract cannot
partially scale out. Stops and MFE defense may tighten under deterministic rules;
neither a target touch nor an estimated Greek creates a fill. PAPER buys at eligible
ask plus configured adverse slippage, sells at eligible bid minus slippage and
accounts for observable size. Missing bids retain unpriced exposure and alert/halt
state. Protective handling must follow the reviewed venue policy, not fabricate
a close or wait for the model to become available.

Expiry requires actual exchange calendars and broker cutoffs, including half days
and AM/PM settlement. Separate expiration, cash settlement, broker liquidation and
exercise-created holdings from ordinary fills. A put cannot silently become short
stock; a call cannot create an unaffordable stock holding. Any unexpected exposure
halts admission and needs authoritative reconciliation. No real exercise/cancel/
placement action is added under this documentation task.

## Strategy and model contract

Degen, Swing and Scope feed one candidate selection boundary. They do not control
bankrolls, quantity or independent execution workers. First adapt a small liquid
SPY/QQQ Degen set: opening-range continuation, VWAP/trend pullback and explicitly
confirmed failed-break reversal. Use completed 5-minute/15-minute structure for
initial signal evidence; faster position supervision is a separate safety cadence.
Freeze both cadences in the new cohort. Do not change the old 15-minute scheduler.

Swing retains completed higher-timeframe bars, exact contract locking, next actual
exchange session, catalyst/earnings clearance, chase and invalidation geometry.
Scope retains the approved V2 SPX/SPXW identity: exact 0DTE, SPX setup authority,
SPY/QQQ confirmation and its documented continuation/reversal modules. Missing SPXW
capability or data blocks Scope; no disguised SPY or 1DTE fallback. Source score,
time, debit and loss settings are research baselines, not automatically suitable
live bankroll limits.

Initial option order intents are single-leg DAY limits with valid contract tick
increments and a fixed approved price/quantity ceiling. A timeout cannot trigger
automatic market conversion, cancellation/replacement or a second submission.
Any later repricing workflow needs separate deterministic authority and evidence.

Store setup observations, eligibility, input availability and exact blockers.
The current legacy collector deliberately omits relative volume; the new cohort
needs real point-in-time volume evidence if an ORB rule requires it. Optional flow/
dealer features remain optional until coverage and incremental value are measured.
Do not import the entire SignalFlow OPRA/Redis service graph to add a few features.

Start with a deterministic selector and one bounded tool-less model choosing among
the same evidence candidates or HOLD. Compare them with equivalent capital, timing,
governor and execution assumptions. No model name is adopted as a proven profitable
trader. Its subjective confidence is not win probability or risk permission. Late
model output cannot renew stale contract approval. Preserve all calls, including
HOLD/error costs; do not switch the frozen legacy model as part of this work.

## Milestones, dependencies and acceptance

M1 is fixture verified; [its implementation contract](OPTIONS_ADMISSION.md) records
the offline API and limits. **Next work is M2.** Each milestone
ends with reviewed code, meaningful tests, status proof, commit and branch push.
Milestones are acceptance contracts, not fixed session or calendar promises.

| ID | Deliverable | Required proof before marking delivered |
| --- | --- | --- |
| M0 | Source audit and authoritative scope | Pinned SignalFlow sources, primary broker/data/strategy research, evidence limits and this document. Complete at this checkpoint; not a runtime gate. |
| M1 | Broker-neutral option identity and deterministic admission | Positive call/put approval plus rejection of identity/expiry mismatch, bad timestamps/quotes, unsupported deliverables, fractional/unaffordable quantity, wrong-side closes, duplicate position and exceeded full-premium/account caps. Equities regressions pass. No broker writes. |
| M2 | Option PAPER lifecycle in the durable engine | Cash/contract conservation, whole partial fills, unknown acknowledgments, no replay, restart/reconciliation, original-stop and model-independent exits, single-contract allocation, half-day/expiry/settlement and unexpected underlying exposure. No assumed flat state from missing history. |
| M3 | Degen candidates and real option-read boundary | Versioned setup/contract selection and HOLD reasons; candidate-first bounded collection and held-contract supervision. Fixture proof first, then authenticated exact-universe/source/latency/entitlement evidence. Optional governed preview is separate from writes. |
| M4 | Integrated observer and experiment evaluation | Read-only stored opportunities/position/health/history, truthful stale/unknown/error states, visible mode/cohort/costs, desktop/mobile checks. Browser reads cause zero model/provider/order work. Model-off/on and SPY/cash/eligible-underlying comparisons preserve point-in-time inputs and all costs. |
| M5 | Actual isolated-host PAPER acceptance | Installed verified package on a separate namespace/population, boot/lifetime ownership/shutdown/orphan tests, independently delivered alerts, actual off-host archive retrieval and source-host-loss evidence. Matching metadata or local TLS/process fixtures cannot close it. |
| M6 | Concrete single-broker LIVE release review and bounded canary | Account identity/product/settled funds/fee/cutoff/approval settings; reviewed order identity and authoritative partial/terminal/unknown evidence; explicit capital/per-trade/full-premium/daily/drawdown limits; independent supervision and halt/alerts; approved release and explicit real-write authorization. LIVE stays disabled until these are satisfied. |
| M7 | Swing and Scope completion on the shared foundation | Each family's frozen setup/contract/management and UI behavior, authentic required data, calendar/overnight or SPXW cutoff/exposure proof, separately measured cohort and explicit mode eligibility. Family-specific failure never redirects into a different strategy. |

Dependencies: M1 before M2; M1/M2 support M3; M4 consumes their stored evidence.
Prepare the existing M5 host acceptance procedure while offline implementation
continues, rather than making more host abstractions. M6 requires the selected
family's M1–M5 operational gates. M7 can develop after M2 in parallel with later
acceptance work; completing every strategy family does not gate a first reviewed
Degen canary. The complete requested product includes all three families and the UI,
with each live-enabled family separately accepted. This turn does not enable them.

Robinhood remains the first capability investigation because it is the existing
brokerage. Current documentation is recorded in the [research](OPTIONS_LIVE_PIVOT_RESEARCH.md).
If it cannot provide the needed account/product/data/order semantics, record the
specific failed requirement and select one alternative before funded integration.
Do not build several live adapters or switch brokers on outdated public assumptions.

## UI acceptance contract

Reuse SignalFlow's information hierarchy, not its whole frontend/runtime:

- Overview: mode, actual release/population, bankroll/net equity, one owned position,
  pending/unknown orders, session, worker/supervisor heartbeat and alert health.
- Opportunities: Degen/Swing/Scope families, exact candidate contract and setup,
  eligibility, evidence time and reason for HOLD. No fake default opportunities.
- Position: strike/call/put/expiry/multiplier/settlement, underlying invalidation,
  premium bid/ask/size/age, whole quantity, debit, full-premium exposure and stop estimate.
- Management: distinct thesis, contract and execution/data health, original/tightened
  stop, time/expiry requirements and deterministic action reason. Main SignalFlow's
  midpoint/last fallback must not be copied as executable sale truth; draft #102's
  principles require deliberate adaptation and testing.
- History/evidence: proposals versus approvals versus fills, scheduler coverage,
  HOLD/reject/error counts, all model/venue/data/host expenses, net results versus
  SPY and immutable versions. Stale last-known values keep a visible timestamp.

Viewing the observer reads bounded persisted records only. Research runs and signed
operator actions are separate explicit controls with receipts. A dashboard demo,
saved automation setting or healthy web process does not certify trader health.

## Economic evaluation and live progression

Keep an experiment ledger of every planned/completed/missed slot and candidate,
including HOLD, missing data, rejected entries and unknown receipts. Cost estimates
and invoices are different evidence. Exclude incomplete option paths from measured
returns without hiding the excluded denominator. Store every attempted research
configuration and use chronological development/validation/untouched evaluation,
avoiding leakage across overlapping holding periods.

Report net cash-conserving returns versus matching SPY and cash, model-off results
and eligible underlying-only signals; include spread, slippage, venue fees, all model
calls and allocated data/host costs. Separate setup selection, option selection and
management contributions. Report session drawdown/tail losses, regime/time
concentration, uncertainty and coverage. Never infer option alpha from stock OHLC,
score saturation or a profitable-looking mark.

Funding and withdrawals are external capital flows, never strategy profit or a
reason to erase losses. Freeze the cohort's funding policy; if flows are allowed,
use a contribution-adjusted benchmark or suppress the raw return comparison until
it is valid. Do not quietly increase funding to make a one-contract trade eligible.

Operational acceptance can support review of a small supervised live **research
canary**, with explicit loss limits and acknowledgement that profitability is
unproven. It does not justify autonomous scaling or a claim of demonstrated alpha.
Broader production/scale needs credible held-out net economic evidence and a
separate reviewed decision. No automatic transition, magic trade-count threshold
or model-led capital increase. Concrete broker actions, real-write code and release
activation require explicit instructions beyond this plan-only turn.

## Open inputs and stop conditions

Missing inputs for later LIVE review: the intended funded bankroll and acceptable
full-premium/per-trade/session/drawdown losses; actual account options permissions
and account restrictions; required real-time data entitlement; secure target-host
and independent archive/alert access. The remembered personal trading balance and
the frozen $10 simulator are not approved new funding amounts. Credentials never
belong in chat or Git. Offline M1/M2 work can proceed without these inputs.

Stop new entries on incompatible identity, stale/incomplete data, exhausted or
unknown budgets, unresolved orders, mismatched account truth, failed supervision,
alert backlog, ownership/recovery fence or unsupported exposure. Retain the reason
and unresolved evidence, alert independently, and apply only already approved
protective handling. Reopening a page or restarting a process cannot resume trading.

## Continuation discipline and completion reporting

Before editing, recover fresh GitHub branch/main/PR references and relevant current
code/documents. Use `slice2/robinhood-read-shadow`; main stays untouched and PR #1
draft until its verification gates are satisfied. Keep the frozen deployment separate.
Read this file first after README, then current status and the next milestone's code.
Do not restart strategy/broker research unless a specific implementation question or
changed primary evidence requires it.

Every slice must deliver a milestone capability or reproduce and close a concrete
blocker to it. Record the failing case, fix and acceptance evidence. Generic
hardening without such a requirement leaves the queue. Avoid micro-check turns,
repeated approvals, whole-suite reruns for document-only edits and setup churn.
For application changes, run appropriate behavioral/regression and installed-package
checks, broaden only for unresolved concerns, and push verified branch changes.
If credentials/host access block acceptance, bundle the necessary operator evidence
into one useful procedure and continue independent code work.

Update milestone status as **not implemented**, **fixture verified**, **provider
verified**, **host verified**, or **live canary accepted**, with commit/test/evidence
references. These states are not interchangeable. A passing local test never grants
provider, deployment or profitability proof. Preserve source/operator evidence
separately from our own observations and record failures openly.

Current milestone state: M0 research complete; **M1 fixture verified** with
`app.options.models`, `app.options.governor` and `tests/test_option_admission.py`.
M2–M7 are not delivered for options. The current runtime still executes equities
only; M1 cannot submit, reserve or settle an option order.
Some underlying stock-engine/host procedures already exist and are reused, but do
not mark an options milestone complete from that prior work. The older isolated
PAPER engine estimate remains approximately **89%**, excluding LIVE/profitability.
Expanded options and LIVE readiness are unassessed. Show concrete completed gates
and the next blocker instead of inventing a percentage for the expanded product.

## References and evidence checkpoint

- [Options/SignalFlow/broker/model research](OPTIONS_LIVE_PIVOT_RESEARCH.md) and
  [pinned source manifest](research/signalflow_options_sources.json).
- [Latest engineering and historical operator status](SLICE2_STATUS.md).
- [Second printed operator report](SHADOW2_EVIDENCE.md); first report remains in status.
- [M1 delivered options admission](OPTIONS_ADMISSION.md).
- [Isolated runtime](PAPER_RUNTIME.md), [host acceptance](PAPER_HOST.md),
  [bounded model acceptance](PAPER_MODEL_ACCEPTANCE.md),
  [evidence checkpoints](EXECUTION_CHECKPOINTS.md) and
  [independent archive host](CHECKPOINT_ARCHIVE_HOST.md).

Initial planning checkpoint: pre-edit branch/PR head
`a55b6bcf512669a8ebb0afa84fd271ff4deca1ad`, tree
`9399594922eea2ba59a5759281fb0d1ff72e3af2`; main
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft. Source-of-truth/evidence
work changed documentation only. It did not install services, alter application
code, call a model/broker/provider or validate profitability. The current M1
implementation and verification checkpoint is recorded at the top of status.
