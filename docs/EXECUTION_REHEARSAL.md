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

Only `LocalFixtureVenue` can be attached. There is no generic network transport,
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

## Standalone verification

From the updated development checkout:

```bash
python -m app.execution.cli run --db execution-rehearsal.db
python -m app.execution.cli report --db execution-rehearsal.db
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

Tests cover duplicate/concurrent dispatch, crash/lost-ack recovery, partial/terminal
outcomes, immutable evidence, quote/session checks, fees/cash, one position, entry
limits/cooldown across restarts, manual halt, rollback, network-free CLI operation,
database isolation, read-only reports, immutable dollar/account limits, entry-loss
gates, daily fee/P&L persistence and fresh-market dispatch reapproval. Admission and
dispatch blocks retain audited reasons without creating an attempt. See
SLICE2_STATUS.md for executed results.

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
fixture venue survives journal reopen only within the rehearsal process and is not
a broker restart simulator or a persistent brokerage service.

Then implement bounded executor deadlines, independent live enablement, actual-account
identity pinning and verified bankroll controls, real-adapter owned-position reconciliation,
deployed stop/session supervision, model-cost integration, alerts and authenticated operator
recovery. Test these independently before connecting them to a live capability.
The deployed SHADOW worker and its continuing market-session verification stay on
their current release; no server update is needed for this offline slice.
