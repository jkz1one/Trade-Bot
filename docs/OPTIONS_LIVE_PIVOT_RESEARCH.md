# Options and eventual LIVE pivot research

Reviewed 2026-10-09 UTC. Product direction: stocks **and options**, borrowing
SignalFlow's Degen/0DTE, Swing and Scope Wizard work and UI, with eventual governed
LIVE execution. This records the user's scope correction. Earlier stock-only
continuations describe the historical experiment, not the complete product goal.
The options implementation sequence below is an engineering recommendation, not
proof of a profitable strategy or authorization to activate real orders.

## What the research changes

We have substantial strategy and interface code to adapt. We do not have a verified
live options engine to copy. Trade-Bot's durable execution, deterministic authority,
uncertainty handling, protective supervision and operator controls remain useful.
The next implementation should add options capability, rather than another generic
infrastructure feature. Target-host evidence remains necessary in parallel.

Keep one trader, one bankroll, one brokerage and one position across stocks and
options. Degen, Swing and Scope are candidate families for that trader, not three
independently funded bots. HOLD remains first-class. The model proposes; software
approves and sizes. The model receives no broker tools. Recommended initial options
scope is a single purchased call or put, closing only owned contracts. No naked
selling, spreads, short stock, averaging down, leverage, futures, crypto or penny
stocks are introduced by this research.

Purchased options have embedded market exposure. The no-leverage implementation
policy here means fully funded premium with no margin borrowing or uncovered
obligation; it does not pretend options have stock-like risk.

PAPER remains default. LIVE remains disabled. No placement, cancellation, exercise
or other brokerage write is implemented or called here. Do not add option review to
the existing SHADOW firewall just because the public tool name exists. A separate,
governed options preview requires validated schemas and account capability first.

The deployed $10 `virtual-v1` experiment stays frozen and separate. A new options
population needs its own explicit capital, limits and versions. At the Scope
playbook's $0.20 minimum ask and standard 100 multiplier, even one contract costs
$20 before fees. The $10 experiment cannot fund that trade. A $0.50 premium costs
$50 and a $1.25 premium costs $125. Never round an unaffordable position up to one.

## Canonical evidence and review limits

Before editing, GitHub and local Trade-Bot matched
`607ab623191e70716a3086d5a967571f60d460ce`, tree
`678c4251ea55e26ec28bb3db8d6d9f0ef1850db5`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft. The supplied older
`952f992...` checkpoint is historical. SignalFlow main still resolves to
`f9eaf2c1b5d13dca287ee7138126883065b00395`.

Recovered 54 selected SignalFlow main documents/modules/components, then three
unchanged tests and three storage dependencies. All 60 local file bytes match their
canonical Git blob hashes. [Source manifest](research/signalflow_options_sources.json)
records paths and hashes. This is targeted source research, not a full repository,
deployment or UI rendering audit. No SignalFlow files were changed.

SignalFlow draft [PR #102](https://github.com/jkz1one/SignalFlow/pull/102) is still
open, unmerged and draft at `3cd8015da171e272ac25617f2b7ae459e41da00f`.
Its management module was read separately from main. Its improvements cannot be
described as accepted main or deployed behavior.

An isolated reference run of the 16 selected Scope/Swing tests produced **15 passes
and one failure** after the dependency closure was recovered. The failure is the
Scope store test's fixed August 3 timestamp: `save()` prunes evidence older than
45 days using actual current time. On October 9 the first saved row is already
deleted, so a second save is not a duplicate and the list is empty. A diagnostic
reproduced those facts without changing source. The 15 decision/evidence tests
passed again in 0.08 seconds with warnings as errors; the retention test was
explicitly deselected. Do not report a clean SignalFlow suite. This also argues
against copying that automatic pruning policy into Trade-Bot's evidence ledger.

## SignalFlow reuse map

Every source in this section is pinned to the SignalFlow commit above.

| Surface | Implemented source behavior | Adaptation for Trade-Bot |
| --- | --- | --- |
| Degen / 0DTE | Opening-range breaks and failures, VWAP reclaim/rejection, level acceptance, trend pullback and compression families; exact option contract selection before modeled entry | Extract deterministic setup evidence and bounded selection. Keep CALL/PUT separate from underlying bullish/bearish direction. A bearish put is a long option, not permission to short stock. |
| Swing | Completed-bar scanning, next-session candidates, locked expiry/strike, fresh quote revalidation, chase/invalidation/target/earnings checks | Preserve candidate identity and next actual exchange session. The standalone entry selector uses weekdays and clock times; replace that shortcut with holiday/half-day calendars. Promotion is not a fill. |
| Scope Wizard | Approved V2 SPX/SPXW specialist, continuation/reversal modules, confirmation and loss controls; candidate-only automation | Preserve exact SPXW 0DTE identity and SPX setup authority. SPY/QQQ are confirmations. Do not silently turn it into a SPY strategy or substitute 1DTE when data is missing. |
| Contract selection | Delta/DTE, spreads, volume/OI, liquidity and provenance; provider Greek preservation and labeled estimated Greeks recovery | Preserve observed versus estimated status. Use Decimal money, strict timestamps, actual contract metadata and whole quantities. BSM sensitivities do not constitute a price forecast. |
| Sizing | `risk-sized-options-v3`, risk/debit constraints, regime/time/quality reductions and whole target allocation | Add a hard full-premium debit/loss cap independently of estimated stop loss. No fractional option fills, implicit 100 multiplier on adjusted contracts, or minimum-one rounding through a hard limit. |
| Management | Original stop authority, premium ladders, MFE defense and deterministic lifecycle | Underlying invalidation and option liquidation price are distinct. One contract cannot scale out in fractions. Session/expiry protection runs independently of model HOLD or failure. |
| Outcomes | Immutable entry snapshots, executable contract P&L separated from underlying R, missing evidence exclusion, rejection/replay infrastructure | Retain every HOLD/rejection/failure, with coverage denominators. Do not infer option returns from the underlying path or current quotes. |
| Brokerage | Paper portfolio reservation, ledger, reconciliation and capability contracts | Reuse concepts. Current default adapters are unavailable and capability audits unproven. These are not an existing verified live broker implementation. |

Primary code: [0DTE](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/zero_dte.py),
[contract selection](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_contracts.py),
[sizing](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_sizing.py),
[Swing entry](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/swing_entry_selection.py),
[Scope policy](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard_policy.py),
[paper brokerage](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/portfolio_brokerage.py).

### Preserve the approved Scope identity

The [approved V2 playbook](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/SCOPE_WIZARD_SPXW_PLAYBOOK_V2.md)
specifies calls to action between 09:45 and 14:30 ET and modeled exit at 15:45 ET;
these are strategy windows, not proof of broker cutoff compatibility. Maximum debit
$500, maximum four contracts, ask range $0.20 to $5.00, two called Plays per session,
two consecutive losses and 30-minute post-loss cooldown are source settings. They
are not automatically approved Trade-Bot capital limits. Quality thresholds
80/90/94/97 classify setup states, not probabilities of winning. A failed
continuation must invalidate, return neutral and confirm anew before reversal.

The current policy's 90-second contract-age default and float money are not suitable
defaults to import blindly into a live 0DTE governor. Freeze explicit strategy
freshness, synchronization, spread and expiry requirements after provider evidence.
If a required input is unavailable, preserve an exact blocker rather than inventing
data or lowering thresholds to force trades.

### Important unfinished work and unsafe assumptions

The [master roadmap](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/CURRENT_MASTER_ROADMAP.md)
still records C2 market-hours OPRA throughput/coverage as active, Swing F2 and Scope
F3 health follow-ons, and cohort tuning dependent on healthy collection. Historical
125-contract protection still had roughly 40-second receive lag. Earlier larger
stream tests missed most prints despite safe quote coverage among captured data.
Off-hours stability after separating diagnostics does not close this gate.

The [R8.5 Degen audit](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/audits/phase29b/PHASE29B_R8_5_PIPELINES_PRODUCT_DEGEN_INTEGRITY.md)
is an acceptance candidate. Score saturation/calibration, management attribution,
state hysteresis, runner health and controlled paired management evaluation remain
unfinished. A v1 decision comparator is not an independent P&L control.

In main, `play_management.executable_mark()` can fall back from bid to midpoint or
last. Draft #102 changes it to bid-only and separates thesis, contract and execution
health, but is not merged. Adapt those principles deliberately; do not transplant
main's fallback or assume the draft has production proof. Missing bids cannot
produce invented sale proceeds, and an underlying target hit cannot become an
option fill without contract evidence.

SignalFlow's AI boundary permits narration, whereas Trade-Bot tests a model's
proposal judgment. Keep that distinction. Borrow deterministic candidate evidence
and management, not a second risk authority or the full multi-bot orchestration.

## Broker and data research, checked October 9

These are current public capabilities, **not this user's authenticated account
entitlements or tested adapters**. No broker session was opened for this review.

| Candidate | Official evidence | Consequence |
| --- | --- | --- |
| Robinhood Agentic/MCP | Current support lists external-agent option chain/instrument/quote/position/order reads, order review and real-order tools, plus index reads. External-agent trade approvals are documented as off by default. [R1] | Verify Robinhood first, preserving the existing single brokerage. Public tools do not prove SPXW entitlement, input schemas, bounded latency, history completeness or safe retry identity. Existing Trade-Bot firewall remains unchanged and blocks writes. |
| Alpaca | Options API supports paper/live; September 2 announcement adds live SPX/SPXW and other index options. Index underlying market data is not supplied. [R2, R3] | Credible alternative if Robinhood cannot meet account/execution gates. Needs an independently verified SPX feed for Scope. July paper-only announcements are superseded; do not assume index options are still paper-only. |
| Tradier | US equity/options API and sandbox. Sandbox data and production index data are 15 minutes delayed; no delayed sandbox stream. [R5] | Useful adapter rehearsal, not sufficient standalone real-time SPX/0DTE evidence. Separate fresh source required. |
| IBKR | Web API trading and contract/data surfaces; retail authentication uses Client Portal Gateway, with subscription requirements documented separately. [R6] | Possible if existing account access makes it practical. More session/data provisioning to verify; do not implement multiple production brokerages to avoid making the decision. |

Recommendation: retain Robinhood as the first capability investigation. Do not
purchase feeds, migrate the bankroll or provision another account based solely on
this matrix. Build broker-neutral option contracts so an evidence-driven switch
does not require rewriting the governor.

Alpaca Basic options are indicative rather than OPRA; Plus provides OPRA and broader
stock coverage, currently listed at $99/month. [R4] A subscription may dominate a
small bankroll's strategy profit. Budget feed, model and host costs explicitly.
Inspect timestamps, feed entitlement, pagination, complete contract coverage,
bid/ask sizes and synchronization on the actual strategy universe. A small fresh
sample does not prove full-universe completeness or execution quality. Prefer a
bounded candidate-first fetch plus a reliable held-contract feed, not SignalFlow's
entire expensive streaming graph.

### Expiry, settlement and account rules

SPX/SPXW have a 100 multiplier; expiring SPXW ordinarily stops trading at 16:00 ET,
or 13:00 on half days, while standard SPX has different cessation rules. [R7] Keep
exercise style, AM/PM settlement, exchange calendar and last trading instant in
metadata. An expiry date alone is insufficient. Broker cutoffs can be earlier.

Physically settled ETF/equity options can create underlying exposure through
exercise. A long put must not create short stock, nor a call an unaffordable stock
position. FINRA describes broker liquidation before the close; it is not a reliable
bot exit strategy. [R8] Require earlier close supervision, authoritative expiration/
exercise/settlement events, and a halt on residual or unexpected exposure. Missing
quotes or failed close acknowledgments retain uncertainty, not a locally assumed
flat state. Do not automatically exercise or expire a real account position.

Alpaca documents automatic exercise and paper non-trade activities arriving the
following day. [R2] Thus paper event timing is not equivalent to a real-time live
exercise feed. An adapter needs explicit event reconciliation, including broker-
initiated liquidation, expiration and cash settlement, not just BUY/SELL fills.

FINRA's replacement intraday margin rules became effective June 4, 2026 with firms
allowed transition through October 20, 2027. [R9] Do not hardcode either universal
$25,000 PDT enforcement or universal removal. Verify the selected account's actual
regime and restrictions. No leverage is permitted by project policy regardless.
T+1 settlement and cash-account available/settled funds must also be represented;
total buying power is not automatically safe spendable cash. [R10]

## What “profitable models” can support

No source reviewed establishes that this bot, SignalFlow, or a particular LLM will
make money. Published results supply hypotheses and test methods. We did not
reproduce their backtests or independently audit their datasets.

| Research | Evidence and limitation | Project use |
| --- | --- | --- |
| Zarattini, Barbon, Aziz, opening-range breakout | Authors study over 7,000 stocks, 2016–2023, with strongest reported results concentrated in unusually active stocks. Their portfolio includes long/short equities, $25,000 starting capital and up to 4x leverage. [S1] | Test relative-volume/catalyst-conditioned ORB versus plain ORB. Their headline returns cannot transfer to one long option position, our capital or no-leverage rules. |
| Zarattini, Aziz, Barbon, SPY intraday momentum | Reported backtest of time-of-day noise boundaries and trend-following exits, with costs/slippage analysis. Uses SPY stock exposure, not proof of option implementation. [S2] | Strong simple deterministic comparator for Degen/VWAP continuation. Test trend/no-trade separation before adding opaque features. |
| Vilkov, 0DTE Trading Rules | Author's updated replication text finds tail-heavy, regime-dependent payoffs; conditional rules fare better than unconditional exposure. Includes multi-leg and short structures, interpolation and holding to settlement. [S3] | Evaluate conditional direction and net economics separately. Do not import ratio spreads, naked selling or claim its positive results validate Scope's managed long contracts. |
| O'Donovan and Yu, option anomalies | University abstract reports 17 significant gross portfolios out of 24, none profitable after original trading costs; mitigation restores seven. Delta-hedged long/short portfolios. [S4] | Test actual spreads and turnover. This is a cost warning and research result, not a ready retail long-options strategy. |
| LiveOption, September 2026 preprint | Structured options benchmark covers overlays, earnings and 0DTE; many agents fail to produce competitive returns. [S5] | Evaluate validity, risk and economics separately. It does not rank our frozen model/prompt or establish durable model alpha. |
| To Trade or Not to Trade, 2025 preprint | Authors report improvements from model-informed risk estimates in backtests and synthetic market simulation. [S6] | Motivate a model-on/model-off ablation. Do not give the model authority to invent risk rules or deploy self-discovered models. |
| Bailey et al., backtest overfitting | Research studies selection bias from searching many strategies. [S7] | Record every attempted configuration; preserve untouched chronological evaluation rather than choosing whichever backtest wins. |

First research candidates: ORB with relative volume, VWAP/trend pullback and explicit
failed-break reversal, then Swing's higher-timeframe continuation and exact Scope
modules. Each needs its own frozen cohort. Flow/dealer nodes are optional research
features until their coverage and incremental value are measured. A dealer exposure
estimate is not an observed inventory or guaranteed turning point.

For LLMs, retain frozen `gpt-6-luna` in the old experiment. In the new population,
compare the deterministic selector to one bounded, tool-less model selecting among
the same approved evidence candidates or HOLD. Keep governor, capital, data, prices
and eligible times comparable. Report model latency and all call costs. Choose any
future model challenger through measured incremental net value, output validity and
deadline completion, not vendor leaderboard rank or a single profitable session.

### Evaluation contract for the new population

1. Freeze setup, selection, sizing, management, prompt/model, capital and fee/feed
   versions before collection. Record planned slots, completed slots and reasons
   for every HOLD, rejection, timeout and missing-input event.
2. Store point-in-time underlying and exact-contract evidence with source/receipt/
   decision times. Preserve bids, asks, sizes and complete coverage. Never replay
   today's chain into yesterday's decision or synthesize option returns from stock
   OHLC. Missing history makes a counterfactual unavailable.
3. Model buys at available ask plus configured adverse slippage, sales at available
   bid minus adverse slippage, limited by observable size and order rules. Broker
   paper fills are a separate evidence class. Include commissions, exchange/regulatory
   fees, all model calls, data and host cost allocations. Mark uncertain fees/costs
   as incomplete. Midpoint performance may be diagnostic only.
4. Report cash-conserving net equity versus matching SPY and cash, plus the same
   signal traded in eligible underlying stock and model-off baseline. This separates
   direction skill, option selection, management and AI contribution.
5. Use chronological development/validation/untouched evaluation sessions; exclude
   leakage across overlapping holding windows and preserve a research-trial ledger.
   Summarize drawdown, worst session, tail loss, coverage, net expectancy, turnover
   and time/regime concentration. Estimate uncertainty by session blocks rather
   than pretending correlated same-day trades are independent.
6. Promotion requires both operational acceptance and adequate economically credible
   evidence with a reviewed risk budget. No automatic promotion, score-as-win-rate,
   arbitrary small trade-count green light or profit guarantee.

## UI reuse and product behavior

Reviewed source: [TradeDesk](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/app/trade-desk/TradeDesk.tsx),
[ZeroDteLab](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/app/trade-desk/ZeroDteLab.tsx),
[SwingLab](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/app/trade-desk/SwingLab.tsx),
[Scope panel](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/app/trade-desk/ScopeWizardPanel.tsx),
plus exact-contract, sizing, progress, dynamic management, history and outcome
components in the manifest. No authenticated UI or rendered mobile QA was performed.

Reuse the hierarchy in a smaller Trade-Bot observer:

| View | Required information |
| --- | --- |
| Overview | PAPER/SHADOW mode, actual release/cohort, heartbeat, session, bankroll, one owned position, pending/unknown orders and alert delivery. Future LIVE must be unmistakable and separately gated. |
| Opportunities | Degen, Swing and Scope family filters; setup quality, freshness and exact blocker; candidate generation is not an order or healthy execution claim. Empty/partial feeds remain visibly empty/partial. |
| Position | Locked underlying, call/put, strike, expiry, multiplier and settlement; premium bid/ask and age separate from underlying invalidation; whole quantity, total debit, full-premium exposure and modeled stop risk. |
| Management | Original thesis, tightened invalidation, premium risk, time/expiry exit, thesis versus contract versus data health, and exact deterministic action reason. |
| Evidence | Fills versus marks, net costs versus SPY, full scheduler coverage, HOLD/reject/error counts and cohort versions; stale saved data retains timestamps and warning. |

Opening or refreshing the observer must only read persisted state. SignalFlow has
interactive research/run controls; copying them into an observer could trigger
provider/model work. Keep signed operator actions separate from browsing. Do not
import the full Next/Redis application or relabel Trade-Bot's fixture demo as live.
Show confidence as subjective setup judgment unless a separately defined calibrated
probability is actually measured. Audit source behavior before styling it as truth.

## Ordered delivery toward trading capability

This is the implementation queue following research. Continue directly at item 1.

| Order | Bounded deliverable | Acceptance evidence |
| --- | --- | --- |
| 1 | **Broker-neutral options contracts and deterministic admission** beside existing equity types: locked identity, metadata, exact synchronized quotes, whole quantities, Decimal debit/full-premium caps and correct bullish/bearish underlying invalidation | Offline tests reject expiry/identity mismatch, stale/future/crossed quotes, nonstandard unsupported deliverables, unaffordable one-contract entries, fractional quantities, wrong-side closes and second positions. Existing equities behavior stays unchanged. No broker writes. |
| 2 | Options PAPER lifecycle using existing durable execution/uncertainty/supervision; explicit expiration/settlement events and one-contract exits | Cash/quantity conservation, partial whole fills, restart and uncertain acknowledgment, original-stop preservation, half-day expiry, exercise-created exposure rejection, absent bid and no duplicate action. New population only. |
| 3 | Candidate-first SignalFlow adaptations: Degen on liquid SPY/QQQ contracts, Swing next-session geometry, exact SPXW Scope modules; observer cards alongside stored evidence | Versioned setup evidence and honest blocker/HOLD states; model-off baseline and no data/model calls from page reads. Scope cannot silently fall back to another instrument/expiry. Numeric source settings remain explicit until approved for the new cohort. |
| 4 | One selected broker's authenticated read/schema/capability and optional governed preview path; real quote/chain/held-position capture | Account identity/permission, actual product entitlement, complete paginated history, source timing, fees, cutoffs, partial fills and stable order identity. Measure real strategy-universe latency and bounded model completion. Read/preview evidence is not submission proof. |
| 5 | Actual isolated-host lifecycle, alert and independent archive/host-loss acceptance with the options PAPER cohort | Install/boot/namespace/process ownership, fail-closed restart, independent alert receipt and recoverable evidence from another host. Reuse existing procedures; do not spend more slices creating new recovery abstractions without a demonstrated missing requirement. |
| 6 | Reviewed single-broker live adapter proposal and limited canary only after implementation/account/host/risk gates are met and real writes are explicitly authorized | Authoritative fill and terminal/unknown-order handling, governed exits and halt/kill controls, explicit capital/loss limits, independent monitoring and a concrete reviewed release. LIVE activation is a separate action, not an environment toggle in this research. |

Items 1–3 are useful work without account credentials. Provider/account access,
intended options capital and loss limits are genuinely missing inputs for later
live acceptance, not reasons to stop implementing the offline option foundation.
Execution correctness and profitability are separate gates; decide explicitly
whether a future small supervised canary is an experiment, never market it as a
proven compounding strategy.

## Completion reporting

The recurring 89% describes the older isolated PAPER equities engine. It excludes
LIVE and profitability and is not a percentage for this expanded goal. Keep it
approximately 89% until actual integration gates change. Report options separately:
research/source audit complete; contract admission, PAPER lifecycle, adapted
candidates/UI, authenticated broker evidence and live adapter are not yet implemented
or accepted. Report deployment separately: frozen old synthetic path continues;
new isolated host/archive services are not installed or accepted.

This research changes documentation only. The previous 1,340-case installed suite
and verified wheel remain historical proof for unchanged application code, not a
fresh options test run. The source-test exception above is retained openly.

## External primary sources

Retrieved 2026-10-09. Sources establish documentation/research claims only. Linked
pages can change; recheck broker terms, entitlements, pricing and rules before use.
Paper abstracts or selected methods were inspected as described above; no claim of
full independent replication is made. Initial SSRN retrieval was blocked, so author
and university copies supplied readable research evidence.

- R1: [Robinhood external-agent tools and approvals](https://robinhood.com/us/en/support/articles/trading-with-your-agent/).
- R2: [Alpaca options API and non-trade events](https://docs.alpaca.markets/us/docs/options-trading).
- R3: [Alpaca live index options, September 2, 2026](https://alpaca.markets/blog/alpaca-launches-index-options-via-trading-api/).
- R4: [Alpaca market-data feeds and subscription limits](https://docs.alpaca.markets/us/docs/about-market-data-api).
- R5: [Tradier sandbox and index data FAQ](https://docs.tradier.com/docs/faq).
- R6: [IBKR Web API and retail connectivity](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/).
- R7: [Cboe SPX/SPXW specifications](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications/).
- R8: [FINRA 0DTE exercise and liquidation risks](https://www.finra.org/investors/insights/zeroing-in-options-trading-strategy).
- R9: [FINRA intraday margin transition](https://syndication.finra.org/content/understanding-new-intraday-margin-requirements).
- R10: [SEC T+1 investor bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin).
- S1: [ORB paper, author-hosted PDF](https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf).
- S2: [SPY intraday momentum paper, author-hosted PDF](https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf).
- S3: [Vilkov's annotated replication paper](https://github.com/vilkovgr/0dte-strategies/blob/main/docs/paper/paper-annotated.md), linked from the author's replication repository; readable revision uses January 2026 endpoint, whereas SSRN's indexed abstract lists February 2. Do not merge sample descriptions or transfer results to our strategy.
- S4: [Option anomalies, university abstract](https://ink.library.smu.edu.sg/lkcsb_research/7872/).
- S5: [LiveOption preprint](https://arxiv.org/abs/2609.33470) and [full text](https://arxiv.org/html/2609.33470v1).
- S6: [Model-informed risk preprint abstract](https://arxiv.org/abs/2507.08584).
- S7: [Backtest overfitting, author-hosted paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
