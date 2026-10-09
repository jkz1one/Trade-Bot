# Degen completed-evidence PAPER path

This is the first **M3 fixture implementation**, layered on the separate M2 local
options owner. It does not complete authenticated option collection, deploy an
options service, invoke a model or enable LIVE. The frozen deployed synthetic
experiment and existing equities services are unchanged.

## Delivered path

`app.options.degen` evaluates version `degen-completed-bars-v1` against the owner's
actual calendar window. Histories must contain contiguous regular-session,
non-interpolated five-minute OHLCV bars starting at the actual session open.
Source/receipt timestamps, completeness and REALTIME entitlement are explicit.
Only bars completed by both timestamps and the evaluation clock vote. Fifteen-minute
confirmation uses complete triplets. Forming bars cannot change completed evidence.

The opening-range continuation needs an observed break and subsequent close beyond
the first fifteen-minute range. The failed-break reversal needs an actual prior
close outside that range, a reclaim through the prior candle and directional
continuation. Being inside the range alone is insufficient. VWAP pullbacks require
at least 25 completed bars, 8/21 EMA alignment and slopes, prior VWAP separation,
an observed retest and a favorable candle. All three also require observed volume,
directional VWAP and completed fifteen-minute confirmation. Extension vetoes and
CALL/PUT underlying invalidations are explicit. Failed gates remain visible as
WATCHING or BLOCKED; they never become implied permission to trade.

The volume ratio compares the latest completed bar with the explicitly frozen
preceding-bar lookback. It is **not** same-slot relative volume from prior sessions.
Session VWAP uses typical price weighted by supplied whole observed volume. No
interpolation, estimated volume or current-chain historical reconstruction occurs.

The adapted concepts come from pinned SignalFlow `zero_dte.py`, `setup_engine.py`
and `play_contracts.py`. Their Git blob identities were rechecked against the
[source manifest](research/signalflow_options_sources.json), pinned to
`f9eaf2c1b5d13dca287ee7138126883065b00395`. This is an explicit smaller ruleset,
not a claim to reproduce SignalFlow's entire strategy graph or profitability.

`app.options.selection` first filters a bounded supplied inventory of exact 0DTE
contracts. Standard supported identities, complete fresh metadata, correct delta
direction/range, **OBSERVED** Greek provenance and supplied volume/open interest
are required. Selection is stable by delta distance, strike distance and canonical
identity, with a frozen quote capacity. Duplicate/conflicting identities block the
inventory. Missing chain or metadata retains an explicit reason. Up to 32 inventory
contracts and eight quotes are allowed; the coordinator also enforces the total
quote bound across its one or two frozen SPY/QQQ symbols.

Only that exact shortlist may supply entry quotes. M1's deterministic governor
admits each setup/contract against authoritative account/cost authority and actual
session limits. Ordered first-approved selection is deterministic, not a model
ranking, probability or return prediction. M2 prepares the fixed DAY limit intent,
then independently re-admits current evidence before its single native local-venue
attempt. Quantity, full-premium funding, fees and maximum loss remain software-owned.

## Owned use and durable evidence

Open a separate `OptionExecution` population as described in
[OPTIONS_EXECUTION.md](OPTIONS_EXECUTION.md), reconcile its local venue and assess
flat supervision. Construct `DegenCoordinator(engine, setup_policy,
selection_policy, create=True)` once before any decisions, orders or model attempts.
All strategy thresholds and collection capacities are supplied explicitly through
`DegenPolicy` and `ContractSelectionPolicy`. The test policies are disposable fixture
values, not a newly selected live trading configuration.

1. `quote_plan(histories, inventories)` performs local planning with zero provider,
   model or order calls. Owned or pending contract identity takes precedence over
   chain membership and comes from the journal. Stale/unhealthy account authority
   suppresses new-entry planning.
2. `await cycle(DegenFrame(...))` claims one durable five-minute entry opportunity
   before native venue reads. It retains normalized inputs, fingerprints, scans,
   shortlist exclusions, candidate admissions, HOLD reasons and execution outcome.
   Failed evidence consumes that opportunity. Repeat and concurrent requests return
   the stored outcome or IN_PROGRESS without another attempt. Interruption retains
   selected evidence, halts entry and never replays the slot. M2 independently
   preserves attempted-order uncertainty and fixed intent authority.
3. `await supervise(quotes, underlyings)` is the **separate fast path**. It accepts
   only the owned contract evidence and delegates to M2's deterministic protective
   tick. It remains callable inside an already claimed entry slot, so stop handling
   never waits for the next five-minute opportunity. A real scheduler must call it
   at the accepted supervision cadence even when entry logic is idle or blocked.
4. `report()` reads stored evidence only. It cannot collect data, invoke a model,
   supervise or submit. It returns the latest 100 durable cycles with truthful
   fixture mode. It is an API foundation for M4, not a delivered dashboard.

On reopening, use exactly the same policies with `create=False`. Policy changes,
reenrollment and adopting an already traded population are rejected. Strategy and
opportunity tables participate in existing paired restore fencing. Stock journals
still reject these option tables; old M2 option owners can reopen without enrollment.

## Evidence and next gate

`tests/test_degen_options.py` verifies positive CALL/PUT opening-range, failed-break
and VWAP rules, invalid history, forming-bar exclusion, stable bounded selection,
metadata exclusions, native PAPER entry and protective exits, fast in-slot stops,
durable HOLD, concurrent deduplication, frozen policy, cancellation and interrupted
restart without replay. Full installed-package results are recorded in
[SLICE2_STATUS.md](SLICE2_STATUS.md).

The [private headless schema/sample acquisition](OPTIONS_READ_CAPTURE.md) now has
fixture/native proof and an operator procedure. It produces evidence only and is not
a normalized feed or deployment.

**Next M3 gate:** obtain actual artifacts and implement normalized options collection from actual
read-tool schemas and responses, with bounded native process/output/latency, exact
source/universe/entitlement/metadata identity and held-contract coverage. This code
accepts normalized fixture evidence; it does not guess Robinhood wire schemas or
claim authenticated option reads. The legacy broker firewall has not been expanded.
Then test the optional bounded tool-less model selector on exactly the same admitted
candidates and account for actual usage. M4 observer/cohort evaluation, mixed
stock/options runtime integration and M5 actual host/alert/archive/source-loss
acceptance remain open. Broker writes, review calls and LIVE are absent here.
