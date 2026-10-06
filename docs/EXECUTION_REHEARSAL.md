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

1. Persist a governor-approved intent with a stable source identity, proposal/input
   fingerprint, quantity, limit, expiry, original stop and complete approval inputs.
   Conflicting reuse of a source key fails closed. One active reservation blocks
   additional orders, including while an entry is only partially filled.
2. Rerun the governor against current reconciled account truth immediately before
   the attempt. Reduced buying power cannot inherit an older, larger approval;
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
database isolation and read-only reports. See SLICE2_STATUS.md for executed results.

## SignalFlow adaptation and remaining engineering

Fresh GitHub inspection confirms SignalFlow `main` remains
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Relevant primary sources:

- [Broker capability and snapshot contract](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/portfolio_brokerage.py).
- [Order reservations and reconciliation](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/portfolio_reconciliation.py).
- [Durable broker ledger](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/portfolio_broker_store.py).
- [Partial-fill and rejection/recovery tests](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/tests/test_roadmap_phase20_broker_reconciliation.py).

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

Then implement bounded executor deadlines, independent live enablement and bankroll
caps, account identity pinning, owned-position reconciliation, deterministic
stop/session supervision, model-cost integration, alerts and authenticated operator
recovery. Test these independently before connecting them to a live capability.
The deployed SHADOW worker and its continuing market-session verification stay on
their current release; no server update is needed for this offline slice.
