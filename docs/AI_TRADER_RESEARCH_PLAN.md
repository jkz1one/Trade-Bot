# Reasoning trader: research decisions and completion plan

Reviewed 2026-10-10. This is the design and acceptance specification supporting
[source of truth v1.19](SOURCE_OF_TRUTH.md), not a second roadmap or implemented
capability. The user requested a stronger research foundation before more coding.
The broader AI role below is the resulting working design. Funded limits, model
selection, cohort enrollment and LIVE activation are not approved by this document.

## Decision and purpose

Build one reasoning trader that forms an evidence-based trade thesis, chooses
among permitted opportunities, and reassesses its held position. Keep execution,
sizing, account truth and mandatory protection in deterministic software. The AI's
useful hypothesis is better selection, abstention and discretionary management
after its costs and delay. More agents, longer explanations or more trades are not
success criteria. A model must earn its operational cost through measured value.

The original comparison arm is narrower: `CandidateChoice` in `app/options/judgment.py` accepts
only SELECT of an already admitted candidate or HOLD, plus a 500-character thesis.
It cannot propose a trade plan or manage a position. Preserve that implementation
as a frozen comparison arm. The durable engine, governor, process bounds, costs,
reconciliation, supervisor and stored observer are foundations to extend, not
replace. The initial planning checkpoint changed no application behavior. The subsequent
[P2 entry contract, bounded native worker and durable coordination](OPTIONS_ENTRY_REASONING.md)
have local installed-package proof with fake provider responses. A newly enrolled
cohort can opt into full entry plans with independently enforced target/horizon;
existing selector cohorts remain unchanged. The [P3 management path](OPTIONS_POSITION_REASONING.md)
now adds durable attempts/costs, atomic decision consumption and fresh stop/full-exit
application in a separate opt-in cohort. Authentic model/feed acceptance and prospective
evaluation remain open.

## Research findings and limits

Targeted source inspection, not a full security audit or performance replication:

| Primary source | What was inspected and learned | Decision for Trade-Bot |
| --- | --- | --- |
| TradingAgents, commit `1394a3f72aa4393e1a98f51b382434c4b4c2d972` [A1] | README, trader and portfolio-manager modules. Trader receives research and technical reports and proposes action/levels; the final manager is another LLM. The manager has a free-text fallback. README describes simulated exchange execution. | Borrow evidence synthesis and explicit thesis/invalidation. Do not copy LLM final risk authority, text parsing fallback, debate fan-out or adding to positions. These files do not prove profitable real options execution. |
| AI Hedge Fund, commit `78b779c1389e2d1452dc29606d2c4126d859b964` [A2] | Vision, portfolio construction and risk limits. Signals become targets through deterministic arithmetic, then caps shrink exposure and leave removed exposure in cash. Vision distinguishes shipped daily backtest/paper from future LIVE. | Preserve opinion versus enforceable authority. Its portfolio allocation and next-day-close cadence do not fit one-position intraday options directly. No claim of audited funded performance. |
| FinMem [A3] | Abstract and architecture description: profiling, layered memory and decision-making; reported stock experiments. | Keep bounded, timestamped thesis context. Defer self-tuning memory and strategy changes; stock results do not establish options alpha. |
| LiveOption [A4] | Methods, conclusion and limitations: options tasks, state dependence, execution-cost sensitivity; selected completed rollouts and limited universe restrict inference. | Test account/position awareness, participation, tails and end-to-end failures, not just average returns or valid responses. Published model ranking is not our model selection. |
| Financial LLM bias review [A5] and backtest overfitting [A6] | Bias taxonomy and abstract/method motivation for trial-selection bias. | Separate structural validity from return; preserve failed trials and prospective evidence. Timestamped prompts alone cannot remove a model's memorized future facts. |
| Robinhood agent documentation [A7] and actual supplied schemas | Public read/write capabilities exist; our authenticated artifact contains six read tools. Tool discovery made zero market calls. | Reuse the selected brokerage and read-only gateway. Schemas establish interface shape, not account permissions, quote entitlement, freshness, fills or safe live order identity. |
| FINRA 0DTE guidance [A8] | Expiration, exercise and broker liquidation exposure. | Independent earlier exit/cutoff handling and authoritative reconciliation remain essential even for fully paid long options. Do not rely on broker liquidation as the strategy. |

No reviewed source proves this bot will be profitable. No external repository was
executed or copied into the application. Numerical trading limits remain project
policy, never values borrowed from a paper's best result. Earlier ORB, intraday
momentum and options-cost research remains in [the options research](OPTIONS_LIVE_PIVOT_RESEARCH.md).
It motivates hypotheses; leveraged/short equity results cannot be transferred to
long single-leg option returns. Do not reopen that strategy search without a
specific failed requirement or new evidence.

## SignalFlow reuse stays concrete

Fresh GitHub check: main remains `f9eaf2c1b5d13dca287ee7138126883065b00395`;
management PR #102 remains open/draft/unmerged at
`3cd8015da171e272ac25617f2b7ae459e41da00f`. Reuse the existing
[60-file manifest](research/signalflow_options_sources.json) and targeted audit;
this pass does not claim another full audit. Main's `executable_mark()` still
falls back from bid to midpoint/last. That is unsuitable as executable sale evidence.

| Family/surface | Reuse | Remaining deliverable |
| --- | --- | --- |
| Degen/0DTE | Completed ORB, VWAP pullback and failed-break observations; contract/liquidity filters | Authentic normalized SPY/QQQ inputs, a broader thesis proposal and measured PAPER run. Existing smaller ruleset is already fixture verified. |
| Swing | Completed higher-timeframe structure, next-session identity, catalyst/chase checks | Holiday/half-day calendars, overnight evidence and distinct frozen family evaluation under M7. |
| Scope/Voodoo | Approved V2 SPX/SPXW specialist modules and SPY/QQQ confirmation | Exact SPXW capability, data and cutoff proof; no SPY or 1DTE substitution. Separate M7 acceptance. |
| UI | Opportunities, exact contract, position management, history and outcome hierarchy | Stored AI proposal versus engine decision versus fill, visible stale/unknown data, matched evaluation and desktop/mobile acceptance. No provider work on page refresh. |

One Degen options PAPER path is the first vertical delivery. Completing Swing and
Scope is part of the final product, but neither blocks the first accepted Degen
research canary. Mixed stock/options support still needs one shared owner; existing
separate engines must never be connected to one bankroll as two traders.

## Proposed AI decision contract

These describe the complete planned contract. Entry types, review, native model
and durable coordination are implemented in [OPTIONS_ENTRY_REASONING.md](OPTIONS_ENTRY_REASONING.md).
[Position proposal/review, native worker and durable management](OPTIONS_POSITION_REASONING.md)
are implemented with local fixture/native-process proof. Arm D replay/export has local fixture proof; prospective evaluation remains open.

| Boundary | Model may propose | Software must decide |
| --- | --- | --- |
| Context | Regime interpretation, directional thesis, conflicting evidence and reasons to wait | Source validity, completed bars, admissible families, calendars, data coverage and account health |
| Flat account | HOLD or ENTER: supplied setup/contract IDs, entry condition, target, underlying invalidation and holding horizon within the frozen family envelope | Validate every reference/level/unit; recompute eligibility, price/tick, deadline, fees, settled funding and whole quantity before any intent |
| Owned position | MAINTAIN, EXIT_ALL or TIGHTEN: exact position/revision, evidence for changed thesis and permitted tighter invalidation | Reject wrong/stale position, widened risk or duplicate action; arbitrate with mandatory exits and unresolved orders; close no more than authoritative owned quantity |
| Explanation | Short evidence-linked thesis, alternative considered, uncertainty and change since prior decision | Store facts/references and rejection reasons; do not treat rationale or subjective confidence as proof, probability or sizing permission |

First version chooses only among a bounded verified contract inventory and defined
setup families. It can choose geometry within their permitted envelopes, not invent
an instrument, strategy, indicator formula or execution program. Direction must
match the setup and purchased CALL/PUT. Any proposed entry condition must be from
an explicit finite vocabulary, evaluated deterministically. Unmet conditions end
that opportunity as HOLD; do not create an unbounded standing instruction.

Required envelope: decision ID, packet hash, policy/model/schema versions, as-of
time, opportunity ID, account/position revision, validity deadline, evidence IDs,
action-specific fields and bounded thesis. Reject unknown fields, conflicting
actions, nonfinite prices, unsupported units and evidence not present in the packet.
Use precise serialized Decimal levels. No generated code, free-text order parsing,
model quantity, confidence sizing, broker tools or model-controlled retries.

For entry, preflight data/account/cost eligibility precedes reasoning. The wider
proposal then receives full deterministic admission; the old selector's already
approved candidate cannot be assumed to cover new geometry. Bind a fixed maximum
envelope before the call and perform fresh admission afterward. New geometry may
not raise that envelope or extend its deadline. Test both bullish and bearish
invalidation, target ordering and units separately from premium risk.

For management, first deliver entry reasoning with existing deterministic exits;
then add the management proposal as a distinct comparison arm. One accepted
position revision can produce at most one governed discretionary action. Mandatory
stop/time/expiry/halt handling always wins a race with model advice. TIGHTEN is
monotone against both original and effective invalidation; it cannot remove a
premium/time rule or postpone a required exit. No scale-in or partial scale-out in
the first management version. EXIT_ALL still needs authoritative quantity and
venue reconciliation; absent executable data cannot manufacture a sale.

Entry reasoning remains aligned to completed five-minute evidence, with completed
fifteen-minute context. Management reasoning occurs only at frozen decision slots
or explicitly versioned thesis events, coalesced into one bounded attempt. Fast
protection remains a separate cadence. Freeze call count, token, money and latency
budgets before enrollment. No per-tick debate, unlimited reflection or fallback
model after an uncertain call. Timeout/unknown usage blocks new risk while existing
protective handling remains independent.

## Data and model selection before enrollment

First mandatory packet: completed underlying OHLCV, exact contract metadata,
bid/ask/size and source times, observed Greeks where required, session/cutoff,
account costs/reservations and current thesis/position. Derived indicators retain
their input lineage. Quote marks and provider chance-of-profit are not executable
prices or calibrated model probabilities. All external text is untrusted data.

News/catalysts are a later optional feature only with an identified source,
publication and receipt times, licensing/access and coverage evidence. No such
feed is currently accepted. First acceptance must work with an explicitly labeled
price/structure-only packet. A missing optional source is visible; a required
missing source blocks that family. Do not add web tools to the trader.

Discovery is now observed: capture `bc8356d41540421d903e5fe8295c1542`, schema SHA-256
`d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15`,
captured 2026-10-10T20:00:43.613542Z, six tools with both schemas and read-only
annotations, zero market reads. See [status](SLICE2_STATUS.md) for provenance.
Next collect a bounded quote/history/chain sample, then instrument/quote/history
samples for actual returned IDs. The schema offers five-minute, not fifteen-minute
bars; aggregate complete triplets. Nullable fields, pagination and missing exercise/
deliverable/last-trade/entitlement metadata need explicit mapping or a blocker.
Saturday schema/quote samples cannot establish regular-session real-time acceptance.

Select the new model through a bounded bake-off: current selector model as a
reference and at most one reasoning challenger, with frozen versions/settings and
equivalent packets. Measure schema/evidence validity, HOLD behavior, deadline
completion and total call cost before economics. Make the first selection on
development data, then freeze it for untouched forward evaluation. No model vendor
or larger model is assumed superior. Preserve the old deployed model/configuration.
Actual model identity, rates and deadlines must be verified at enrollment; this
plan neither makes paid calls nor asserts a current price.

## Evaluation that can reject the AI hypothesis

Use one recorder and independent simulated ledgers, never extra funded owners.

The [first P3 paired accounting evaluator](OPTIONS_EVALUATION.md) now reconstructs
supplied A/B/C fixture session ledgers and refuses incomplete comparison totals.
The [sealed common tape](OPTIONS_MARKET_TAPE.md) now verifies recorded cycle/fill/
benchmark content and reruns the existing setup/contract-planning stage.
[Native first-session export](OPTIONS_EVALUATION_EXPORT.md) extracts independent
A/B/C journals. The [first-session scheduler](OPTIONS_REPLAY.md) now runs those
owners with independent clocks, scripted model delays and subsequent tape fills.
[Multi-session replay/export](OPTIONS_REPLAY_SERIES.md) now preserves native
accounts, explicit settlement and saved closing evidence. Authenticated collection
and prospective proof remain open. [Arm D replay/export and stored attribution](OPTIONS_MANAGED_REPLAY.md)
now preserve four independent accounts, matched entry scripts and all model costs.

| Arm | Difference under test |
| --- | --- |
| A | Existing deterministic setup/contract selector and deterministic management |
| B | Current narrow SELECT/HOLD model; same candidate evidence and management |
| C | Broader entry thesis/geometry, deterministic management |
| D | C plus bounded discretionary management after its separate correctness gate |

Keep data availability, starting capital, limits, eligible times and fill assumptions
matched. Each arm owns its own resulting position, reservations and costs. Comparing
proposals on one shared position is not a portfolio-return comparison. Preserve
selection and management ablations so gains cannot be attributed to the wrong change.
Report SPY, cash and eligible underlying-only exposure separately; a bearish PUT
cannot become a short-stock baseline under this mandate.

Use point-in-time quotes after actual decision completion, not the earlier packet's
price. A limit needs subsequent eligible price/size evidence within its validity;
otherwise unfilled. Retain absent/ambiguous paths and their denominator. Include
spread, adverse slippage, observed size, fees, every model call and allocated feed/
host costs. Unobserved fills or unknown costs make the result incomplete, not zero.
Simulated fills are never broker fills or proof of queue priority/market impact.

Before prospective enrollment, freeze a machine-readable experiment manifest with
all arm versions, virtual capital, limits, fee/latency/fill assumptions, collection
calendar, exclusions, primary endpoint, economic hurdle and review dates. The first
20 completed market sessions are a proposed feasibility pilot, not a LIVE or alpha
threshold. Use its paired session variability to design a separately frozen,
untouched evaluation duration and precision target. Do not tune on that evaluation
or repeatedly peek until significance appears. The evaluator must emit INCONCLUSIVE
when coverage or uncertainty cannot support a conclusion.

Primary AI endpoint: paired session net-equity difference versus A after all costs.
Also report net results versus SPY/cash, max drawdown, worst session, full-premium
exposure, turnover, HOLD/reject/error counts, deadline miss rate and uncertainty.
Report whole-session blocks and time/regime concentration, not independent-trade
confidence intervals for correlated trades. Log all model/prompt/strategy trials;
multiple comparisons and repeated selection must be disclosed. Historical LLM
backtests are diagnostics because training contamination may remain; prospective
frozen decisions are the primary economic evidence.

A broader AI arm that cannot beat its predeclared net-value hurdle with adequate
evidence stays research-only or is retired. A costlier model needs incremental
net value, not prettier reasoning. An operationally accepted small LIVE research
canary may still investigate unproven economics under separately approved losses;
it is distinct from profitability claims or permission to scale.

## Bounded delivery queue and done criteria

These packages refine the existing milestones; they do not reopen completed gates.
The user subsequently added P8/M8 for a dedicated visually polished dashboard.

| Order | Deliverable and owner | Done evidence / stop condition |
| --- | --- | --- |
| P0 | This research/design pass, engineering | Source pins, actual capability gap, authority contract, comparison protocol and ordered queue recorded. Done as documentation; subsequent P2 implementation evidence is recorded separately. |
| P1 | Verified data packet, engineering + operator capture | Actual bounded responses mapped with no guessed metadata; installed normalizer rejects stale/future/interpolated/mismatched/partial inputs; held-contract priority and market-hours read coverage/latency receipts. Missing provider semantics become a named blocker. |
| P2 | Broader entry reasoning, engineering | Versioned packet/proposal/admission, native bounded worker and durable full-plan execution now have local fixture proof, including target/horizon protection and preserved old cohorts. Authentic model completion/latency with P1 evidence remains required before accepted use. |
| P3 | Comparative ledgers and position reasoning, engineering | Paired accounting, sealed common tape and setup/shortlist replay have fixture proof. Native first-session A/B/C export is fixture verified. First-session independent replay scheduling with scripted models is fixture verified. Multi-session state/export with explicit funds settlement is fixture verified. Position proposal/review, native worker and opt-in durable management have fixture proof, including cost/uncertainty retention, atomic revision consumption, monotone stops, full PAPER exits and mandatory-exit precedence. Arm D replay/export and stored observer attribution are implemented with independent accounts, matched entry configuration and all entry/management charges. The eligible long-underlying comparator now follows A-approved CALL opportunities with a separate continuous account, sized later quotes, explicit settlement and all costs. Optional manifest-frozen whole-session block diagnostics and time/regime concentration are implemented; see [analysis contract](OPTIONS_SESSION_ANALYSIS.md). Inferential adequacy and prospective evidence remain open. |
| P4 | Integrated options PAPER runtime and UI, engineering + operator | [Continuous local normalized-fixture runtime](OPTIONS_LOCAL_RUNTIME.md) now has one owner, independent protection, scheduled decisions, interruption-safe shutdown and stored runtime/slot observer integration. [Signed local operator recovery](OPTIONS_OPERATOR_RECOVERY.md) adds reviewed halt/resume/revocation with exact revisions and durable receipts. [Installed-file identity](OPTIONS_LOCAL_RUNTIME.md#installed-release-identity) is now recorded for each runtime start and read from stored observer evidence; it does not grant release approval or prove liveness. [Historical comparison views](OPTIONS_COMPARISON_VIEW.md) now bind full-cost reports to stored population history and display net equity/SPY/cash with explicit gaps. Authentic collection/model, host and visual acceptance remain open. One owner, continuous exact data, independent supervision, scheduled decisions, restart/unknown recovery, installed entry point and desktop/mobile observer. Exercise actual fixed host topology, boot/orphan behavior, independent alert receipt and off-host archive/source-loss drill under M5. Existing equity units alone do not close this. |
| P5 | Prospective PAPER evidence, operator + engineering analysis | Freeze enrollment manifest, then collect planned/missed slots and complete quote/decision/cost/fill paths; issue operational and economic reports with PASS/FAIL/INCONCLUSIVE separately. No silent tuning or automatic promotion. |
| P6 | Concrete LIVE adapter/canary review, engineering + user | M6 account/order semantics, explicit capital/loss limits, broker reconciliation/exits, reviewed release and separate real-write authorization. No implementation/call of broker writes under this plan. |
| P7 | Swing, Scope and combined stock/options completion | [Shared Degen/Swing PAPER arbitration](OPTIONS_SHARED_STRATEGIES.md) now implements one owner/model packet and a locked next-session daily-breakout family with session-close protection. [Shared-family replay/export](OPTIONS_SHARED_REPLAY.md) now preserves independent A/B/C/D accounts, frozen common tapes and all costs across sessions. [Scope preflight](OPTIONS_SCOPE_PREFLIGHT.md) now checks required evidence coverage and exact SPXW identity without trading authority. [Scope structure](OPTIONS_SCOPE_STRUCTURE.md) adds nine price-derived patterns, directional confirmation and exact-strike reachability diagnostics. [Scope context review](OPTIONS_SCOPE_CONTEXT.md) adds six anchored variants and bound context-risk checks. [Durable unfilled Scope watches](OPTIONS_SCOPE_WATCHES.md) now retain called-play limits, locked evidence and invalidation/expiry. Opt-in watch neutral resets now require cooldown and fresh post-reset reversal bars. [Scope quality review](OPTIONS_SCOPE_QUALITY.md) now adds auditable scoring and known-level path checks with optional frozen watch integration. Opt-in completed SPX path checks add opening-range levels, confirmed pivots and exact session VWAP; complete path proof remains open. [Scope sampled arming](OPTIONS_SCOPE_ARMING.md) now requires bounded fresh observations across a durable hold, with no execution authority. [Scope contract profiles](OPTIONS_SCOPE_CONTRACTS.md) now gate exact supplied contracts and enrolled watches; convexity remains blocked without full path evidence. [Scope owned admission review](OPTIONS_SCOPE_OWNED_ADMISSION.md) now persists common-governor sizing with all fees and owned account limits, without dispatch. Fresh Scope admission reviews now apply the approved ask-price quantity tiers through the same fee-inclusive governor. The common engine enforces the research-only entry boundary at preparation and dispatch. [Stored native position outcomes](OPTIONS_POSITION_OUTCOME.md) now supply verified fill/fee/model-cost evidence without Scope execution authority. Native cash settlement and worthless expiry now retain exact entry attribution through complete accounting replay. An opt-in [native account loss guard](OPTIONS_NATIVE_LOSS_CONTROL.md) now enforces cooldown and persistent threshold lock from verified outcomes. Signed revision-bound account-wide loss reset now preserves history and global limits. The native guard now blocks paid entry-model admission during loss pauses while preserving owned management; expected pauses complete as HOLD without a new global halt. The stored observer now exposes research watches, arming and full-cost sizing with separate validity labels and no execution authority. Native selected entries now freeze verified Degen/Swing identity through dispatch, exact closes and management-cost attribution; old unlabeled orders are not backfilled. New frozen cohorts can now add independent Degen/Swing loss streaks, cooldowns and signed family resets while preserving account-wide guards, other families and every cost. Paid entry calls pause when all stored candidate families are paused; mixed packets remain subject to preparation/dispatch guards. Scope watch/family loss linkage and Scope family reset, complete obstruction coverage, overnight Swing, Scope execution and mixed stock/options remain open. Family-specific M7 proof and single-owner arbitration before each mode is enabled. Can progress after the common foundation without holding the first Degen acceptance hostage. |
| P8 | Strong visual dashboard finish, engineering + user visual review | Cohesive dark styling, charts and hierarchy for bankroll/benchmark, opportunities, AI thesis, exact position/protection and decision/fill history. Functional UI in P4; dedicated desktop/mobile, keyboard, contrast and populated/empty/stale/error screenshot acceptance in M8. Stored data remains truthful and page reads cause no trading work. |

Do not wait for every real-market result before useful offline implementation.
Do not resume generic hardening: every new change must close a named queue gate,
with failing evidence or a missing acceptance requirement. Reopen research only
for changed source facts, an explicit user direction, or a recorded failed
hypothesis. Research/design P0 ends here; provider measurement and economic
validation remain implementation/acceptance work, not reasons for endless planning.

## Primary sources

Retrieved 2026-10-10. Repository references are pinned; web documentation can change.

- A1: [TradingAgents trader](https://github.com/TauricResearch/TradingAgents/blob/1394a3f72aa4393e1a98f51b382434c4b4c2d972/tradingagents/agents/trader/trader.py), [portfolio manager](https://github.com/TauricResearch/TradingAgents/blob/1394a3f72aa4393e1a98f51b382434c4b4c2d972/tradingagents/agents/managers/portfolio_manager.py), [README](https://github.com/TauricResearch/TradingAgents/blob/1394a3f72aa4393e1a98f51b382434c4b4c2d972/README.md).
- A2: [AI Hedge Fund vision](https://github.com/virattt/ai-hedge-fund/blob/78b779c1389e2d1452dc29606d2c4126d859b964/VISION.md), [construction](https://github.com/virattt/ai-hedge-fund/blob/78b779c1389e2d1452dc29606d2c4126d859b964/hedge_fund/portfolio/construction.py), [hard limits](https://github.com/virattt/ai-hedge-fund/blob/78b779c1389e2d1452dc29606d2c4126d859b964/hedge_fund/risk/limits.py).
- A3: [FinMem, v2](https://arxiv.org/abs/2311.13743v2).
- A4: [LiveOption, v1, especially limitations](https://arxiv.org/html/2609.33470v1).
- A5: [Evaluating LLMs in Finance Requires Explicit Bias Consideration, v1](https://arxiv.org/abs/2602.14233v1).
- A6: [Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
- A7: [Robinhood external-agent tools](https://robinhood.com/us/en/support/articles/trading-with-your-agent/).
- A8: [FINRA 0DTE guidance](https://www.finra.org/investors/insights/zeroing-in-options-trading-strategy).
