# Paired options session ledger

First P3 accounting slice, 2026-10-11. `app.options.evaluation` is a pure replay
and descriptive comparison of supplied independent A/B/C ledger evidence. It does
not rerun strategies, collect market data, call a model, open a trader, submit to
a venue, restore authority or prove profitability. All accepted evidence is labeled
`LOCAL_FIXTURE`; no currently deployed experiment is enrolled or changed.

## Inputs and identity

`EvaluationBundle` contains a versioned `EvaluationManifest`, zero or more
`ArmSession` records, and optional `BenchmarkSession` pairs. The manifest fixes:

- Experiment ID, declared enrollment time, source-evidence kind, allocation-policy
  identifier, per-session dollar hurdle and minimum session count.
- Exactly A (deterministic), B (selector) and C (entry reasoning), with distinct
  virtual population IDs, full limits/execution policies and strategy hashes.
  Capital, calendar, risk and fill assumptions must match after removing population/
  account IDs and model-cost policy. B/C require explicit configured model costs;
  A has none. These are independent simulated ledgers, not extra funded owners.
- One to sixty complete, ordered XNYS sessions, including real DST/early-close
  boundaries, each with a recorder-tape hash. Declared enrollment must precede the
  first session. Every regular five-minute cycle belongs in the denominator,
  including warmup, HOLD, skips and errors.

Each arm/session binds its exact definition and tape hashes and supplies starting/
closing ledgers, complete orders/observations, settlement receipts, model attempts,
cycle outcomes/frame hashes, explicit data and host cost allocations, and closing
completeness. Money rejects floats, booleans, nonfinite values and excessive scale.
The bundle is capped at 16 MiB, 180 arm/session rows, 200 orders/receipts and 100
model attempts/cycles per row. Each session must have exactly the expected slots.

Hashes establish correspondence only. The declared timestamp, strategy identity,
frame hashes, completeness and allocations are supplied assertions. This API does
not authenticate a provider, prove enrollment happened before outcomes, verify that
a claimed strategy produced a decision, or establish omitted calls do not exist.
The optional [sealed common tape](OPTIONS_MARKET_TAPE.md) now checks recorded
content and timing. [Native first-session export](OPTIONS_EVALUATION_EXPORT.md)
now supplies automatic journal evidence. Full A/B/C replay scheduling and multi-
session export remain required.

## Replay and uncertainty

`evaluate(bundle)` revalidates all typed inputs and computes under a private Decimal
context. Each arm starts at its frozen capital. Subsequent sessions must continue
that arm's prior ledger and global receipt/fill sequence without a capital reset.
Missing or structurally invalid prior evidence prevents a later session from
silently restarting the comparison.

The evaluator reconstructs cash, settled cash, whole-contract lots, realized P&L,
fees and ownership using the same `apply_fill` / `apply_receipt` functions as the
engine. It shares the engine's extracted pure `fill_evidence.validate_fill` audit
for quote identity/freshness, observed-size reuse, slippage/tick rounding, limit
price and fees. The engine's validation behavior is unchanged by that extraction.

An observed fill must belong to the exact attempted order, fit its original
lifetime and debit, and use a quote whose source time is **strictly after decision
completion**. Model-funded entries require the corresponding model-completion
receipt. Old packet quotes cannot stand in for later executable evidence. Duplicate
IDs, missing/regressing sequences, overlapping attempts, changed terms, invalid
settlement, oversells, added positions or cash/ownership mismatches are excluded.
Between-session `FUNDS_SETTLED` receipts may appear before the next open, preserving
the prior closing ledger and global event sequence; they do not create cash profit.

HOLD calls remain charged. Every declared model-called cycle must have its attempt;
duplicate receipts are rejected. Missing/foreign usage or incomplete/late cost
receipts remain unknown. Missing data/host allocation is not zero. Recorded errors
are counted; an UNKNOWN cycle or unresolved order makes the session inconclusive.
Open boundary positions are unvalued rather than assigned a guessed liquidation.

Complete pairs require all three independently verified ledgers, matching cycle
frame maps and usable SPY boundary quotes. Every declared session appears in output.
If any pair is incomplete, overall totals and mean paired differences are withheld;
there is no complete-case profitability aggregate that drops inconvenient sessions.

## Report and CLI

The report includes:

- Accounting verification, reasons, price P&L, fees, turnover, venue cash change,
  model/data/host costs, unknown-call counts, cycle outcomes and deadline misses.
- Session net change and B/C dollar differences versus A after all supplied costs.
- Total net change/return, worst session and **session-boundary** drawdown when the
  entire declared comparison is complete. No intraday drawdown is inferred.
- SPY midpoint price returns and cash's zero price return. SPY boundary observations
  must be real-time/complete from the frozen source with at most five-second source
  distance from the session boundary and at most five-second receipt lag.
  Session-compounded SPY and corresponding net excess exclude overnight gaps,
  dividends and benchmark execution costs. They are not buy-and-hold total return.
- Manifest/evidence hashes, planned/complete session counts and whether the supplied
  minimum count was met. `economic_conclusion` always remains `INCONCLUSIVE`:
  arithmetic completeness, a hurdle or enough fixture rows cannot establish alpha.

The installed command is `python -I -m app.options.evaluation_cli --bundle PATH`.
Optional repeated `--tape PATH` inputs enable mandatory sealed-content checks for
every declared session. Reports distinguish supplied hashes from verified recorded
market content; neither is authentic provider or strategy provenance.
`PATH` must identify an already-created bounded regular JSON bundle; it is not a
journal, OAuth file or an enrollment command. No production bundle exists yet.
The CLI reads once, rejects symlinks/special/oversized/changing files, prints JSON
and writes no output file or execution state. Exit 0 means `COMPLETE_ARITHMETIC`,
1 means `INCONCLUSIVE`, and 2 means unavailable/invalid source evidence. Sensitive
validation details are not echoed. Input examples live in `tests/test_option_evaluation.py`.

## Remaining P3 work

The [shared tape and setup/shortlist replay](OPTIONS_MARKET_TAPE.md) are now
implemented, alongside [native first-session journal export](OPTIONS_EVALUATION_EXPORT.md).
Connect the independent strategy/portfolio replay scheduler and multi-session state
against that recorded availability, and attribute decisions/fills/costs visibly in the stored observer. Add the eligible
long-underlying baseline, exact-position management arm D, appropriate statistical
session-block analysis and prospective enrollment/coverage proof. These are not
implemented by this accounting kernel. Actual model/data acceptance, runtime,
complete UI and host deployment remain separate gates in
[the completion plan](AI_TRADER_RESEARCH_PLAN.md). Latest test proof and wheel digest
are in [status](SLICE2_STATUS.md). LIVE remains disabled.
