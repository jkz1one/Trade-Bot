# Sequential synthetic portfolio experiment

This opt-in profile tests a separate virtual bankroll using the existing safe Robinhood
READ worker, one tool-less Trader Agent and the deterministic governor. It does not
execute orders or call `review_equity_order`. The default profile remains real-account
SHADOW, and the application's default mode remains PAPER. LIVE stays disabled.

## Separate populations and authority

Real-account SHADOW proposals and their forward quote marks remain unchanged.
Selecting a synthetic experiment replaces that worker's model input account with its
virtual cash, position and cost reserve. `session_context` explicitly identifies
`SYNTHETIC_PAPER`, the experiment ID and execution policy. This produces a different
population of model decisions, so its journal, simulated fills and model costs are
stored in separate tables and reported separately. The worker does not run a second
real-account model alongside it.

Actual Robinhood/local reconciliation still runs against real ownership. A virtual
position is never written into real ownership, orders, fills, account snapshots or
model-usage tables. A mismatch blocks model judgment and virtual transitions. The
synthetic gateway rejects reviews as well as placements, cancellations and writes.
The Trader Agent still receives no tools and makes at most one structured model turn.

The common lifetime lock and persistent 15-minute XNYS slot claims serialize both
profiles. Switching profiles cannot replay an already attempted slot. A synthetic
cycle has its own ID; the scheduler's real SHADOW cycle reference remains empty.
A cancelled cycle leaves its claim active until explicit inspection and abandonment.
Model errors persist HOLD and halt the existing service until explicit recovery.

## Initialize and select

Initialization is local and requires no API calls. IDs contain 1–64 letters, digits,
underscores or hyphens, beginning with a letter or digit. Existing IDs cannot be reset.
Configuration freezes initial capital, per-side slippage, per-fill fee, SPY benchmark,
model identity/pricing, market universe/bar settings, prompt identity/hash and risk
settings/policy hash. Changing those requires a new experiment ID. Each cycle also
records the running release SHA.

For a local OpenAI profile:

```bash
python -m app.robinhood.cli synthetic-init --id virtual-v1 --capital 10 --slippage-bps 5 --fee-per-fill 0
TRADER_SYNTHETIC_EXPERIMENT_ID=virtual-v1 python -m app.robinhood.cli shadow-run --agent openai --once
python -m app.robinhood.cli synthetic-report --id virtual-v1 --limit 25
```

A stub profile must be initialized separately with `--agent stub` and run with
`--agent stub`; it is never pooled with OpenAI evidence. An unscheduled `shadow-cycle`
is rejected when an experiment is selected. Closed-market scheduled ticks make no
broker/model calls. Continuous operation uses the existing detached `shadow-service`.

On the prepared server, stop the worker before choosing a profile:

```bash
./scripts/shadow-server.sh stop
./scripts/shadow-server.sh synthetic-init virtual-v1 --capital 10 --slippage-bps 5 --fee-per-fill 0
```

Set `TRADE_BOT_EXPERIMENT_ID=virtual-v1` in `/etc/trade-bot/worker.env`, then run the
existing preflight/start sequence. The helper automatically loads that private file,
so selection survives SSH sessions and updates. `prepare` creates the file with a
blank selection without replacing existing settings. Blank selection keeps the
real-account SHADOW profile. Preflight validates the frozen configuration before
remote calls. Operate one worker, including across machines.

```bash
./scripts/shadow-server.sh synthetic-report virtual-v1
```

The private observer adds a separate synthetic section with assumptions, virtual
cash/position, pending intent, fees, costs, equity, SPY excess, observed drawdown,
recent decisions and simulated fills. Authenticated `/api/synthetic/virtual-v1`
returns up to 100 cycles/fills; it only reads committed SQLite data. Opening the
observer never advances the experiment. Existing SHADOW audit/history/outcome
commands continue to describe the real-account population only.

## Version 1 execution policy

Policy: `v1-next-quote-paper`. Decimal accounting uses share quantities rounded down
to eight decimal places. Defaults are five basis points of slippage on each side and
zero fixed fee; fees and slippage are assumptions, not brokerage guarantees.

1. Read and reconcile real broker truth; build fresh market evidence during a
   regular session. Mark the existing virtual position and process deterministic
   exits or a previously queued intent before forming the model's account input.
2. The model may propose HOLD, OPEN_LONG or CLOSE. Software rejects REDUCE,
   averaging down, additional positions, poor quotes and risk violations. It reserves
   reported model costs and assumed fees, and sizes using the original governor.
3. An approved intent queues without a fill. A later scheduled packet must contain a
   quote timestamp strictly after model completion, at most 90 seconds old by default,
   timezone-aware, not future-dated and not crossed. Revalidate sizing, tradability,
   original invalidation, daily entry limits, drawdown and cooldown at the later quote.
   Entry size can shrink; it cannot exceed the original approved notional.
4. Buy at ask plus slippage, sell at bid minus slippage and charge the configured
   fee. Below-minimum rounded fills are rejected. Intents expire after 20 minutes
   or regular close, whichever comes first, and cannot cross sessions. No stale
   intent or missed schedule slot is backfilled.
5. Software closes a long at the observed bid when it reaches or gaps through the
   original invalidation. The original stop cannot widen. A position without
   `hold_overnight=true` exits in the last 15 minutes of the session when a fresh
   quote is observed. If that observation is missed, it exits at the first fresh
   next-session observation and records `MISSED_SESSION_EXIT`. It never fabricates
   an earlier close or stop-price fill. The last slot skips new model calls because
   it has no later scheduled quote for an intent.

Stops are sampled every 15 minutes; these are not continuously monitored executions.
A missing/stale position quote prevents a new model judgment and makes equity marks
unavailable until a fresh quote arrives. Stops and session exits require an actual
fresh observation. Overnight permission does not remove the original stop.

Trading state, cycle, fill records, linked costs and slot completion commit atomically
with a revision check. A late failure rolls back the entire portfolio transition.
A durable receipt is saved before each paid model attempt. Cancellation or a crash
before accounting leaves potentially billed usage unknown even after slot recovery;
it cannot disappear from the economic report or enable another entry.

## Economic reporting

Trading cash conserves initial capital plus realized price P&L minus trading fees;
API costs are a separate economic overlay. Reported usage from every attempted
model decision, including HOLD and failures with usage, is priced using frozen
standard input/output rates. The governor reserves those costs before approving a
new intent. Observer/report values include:

- Gross liquidation equity: cash plus the position's bid-minus-slippage value,
  less an assumed exit fee while held.
- Net equity and return: gross liquidation equity minus all reported experiment
  model costs, relative to the original bankroll.
- SPY benchmark: a fractional buy-and-hold portfolio with the same initial capital,
  first fresh experiment quotes, quantity rounding, spread, slippage and fees. It
  retains rounding cash and reserves its exit fee. It does not pay trader API costs.
- Net excess: net strategy equity minus benchmark liquidation equity, divided by
  initial capital. Observed maximum drawdown uses net equity and the persistent
  high watermark.

Missing usage is unknown, not zero. A failed paid call with no tokens or an unaccounted
pre-model receipt makes net equity/return/excess and drawdown unavailable and blocks
new entries/model judgments. Deterministic exits can still reduce existing exposure.
The UI preserves gross cash/fill history with that limitation. There is no automatic
billing reconciliation or cost reset in this version; an affected cohort stays
unresolved until a future explicit reconciliation feature. A newly named experiment
is a separate cohort and does not erase the previous costs or failure evidence.

Stale benchmark quotes make the benchmark and excess unavailable; stale position
quotes also make strategy equity unavailable. Saved marks are timestamped, never
advertised as live. Drawdown is sampled and cannot capture unobserved intraday lows.
Price dividends, splits, other corporate actions, taxes, hosting and setup/smoke-call
costs are not modeled. Review those assumptions before interpreting a sustained run;
corporate actions can invalidate raw quote accounting. There is no claim of realistic
fills, demonstrated signal or profitability. Backup/export includes the complete
synthetic journal and receipts without changing broker state.

## Verification and merge gate

Offline tests cover sequential proposals/fills, cash conservation, costs, fees,
rounding, benchmark pairing, invalid/stale quotes, gap stops, session exits, one
position, cooldown, daily limits, profile immutability, restart/duplicate claims,
transaction rollback, unaccounted model attempts, cancellation, persistent halt,
read-only gateway, private observer and backup restoration. They use injected clocks
and synthetic broker/model fixtures; they do not establish broker/API availability
or trading performance.

Keep PR #1 draft and `main` untouched until target-host image/permission/startup,
authenticated reads/model cycle, restart/recovery and private desktop/mobile
inspection pass. Then collect real regular-session synthetic evidence before
making any decision about LIVE; this slice contains no live execution capability.
