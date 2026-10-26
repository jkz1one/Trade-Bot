# Pre-open Swing history transport

The continuous collector can now explicitly enroll `swing_history` with version
`preopen-swing-history-v1`, `daily_bars` (56..260, default 56) and `hourly_bars`
(54..260, default 54). This is a frozen collector configuration change, not an
in-place upgrade of an existing feed. An omitted policy serializes exactly as
before and preserves existing configuration hashes and database behavior.

The implementation uses the already captured, pinned get_equity_historicals
schema. No new tool capability, credentials, provider call, dependency or host
change was used during development. Actual daily/hourly responses have not yet
been captured and accepted. Tests use synthetic responses under the real schema.

## Collection and recovery

Preparation runs after the previous session's close and before the target
session's open. It uses the local XNYS calendar for holidays, daylight saving
changes, shortened sessions and the final short hourly segment. Mid-session
startup does not invent a pre-open source for today's Swing signals.

Each symbol has separate daily/hourly requests with exact regular-session bounds
and split adjustment. Responses must match symbol, interval, bounds and every
expected original bar. Missing, duplicate, reordered, interpolated, zero-volume,
unknown-session or incorrectly aligned bars are rejected. OHLC and volume are
never filled in or guessed. The calendar supplies each observed bar's end from its
verified left edge, rather than assuming a 24-hour trading day. Native histories
retain UNKNOWN entitlement. Their source_at is the last completed bar boundary;
received_at remains the capture time and is not refreshed by cache reuse.

In particular, ambiguous midnight daily labels or differently aligned hourly
labels are not silently rewritten. If real responses use those forms, their
semantics need review before this mapper can accept them.

A complete bundle is stored in collector.db with its target session, original
attempt sequence, capture hash and normalized hash. `ContinuousFeed.swing_snapshot`
revalidates it against the retained raw capture and exact requested histories.
The native daily/hourly objects are available to subsequent source binding.
Restart reuses that original bundle without duplicate reads or rewritten clocks.
The same durable transaction retains the normalized quote packet and history;
recovery republishes a committed packet after interrupted file publication.

Historical backfill shares the collector's existing call quota. It reserves
equity and held-option reads at every poll plus one intraday history cycle before
spending spare capacity on backfill. Failed history attempts remain charged across
restart. Existing response, aggregate capture and timeout bounds are unchanged.

If a history response is incomplete or a later history transport call fails,
successfully completed required quote reads can still be delivered. The raw
capture keeps its original FAILED status and the packet records
SWING_HISTORY_UNAVAILABLE. A missing or failed required market read still prevents
publication. No successful history bundle is stored for an incomplete capture.

## What this does and does not complete

This completes an offline-tested history capture, normalization and persistence
slice. It does not yet attach a native Swing source/seed or catalyst to the runtime
frame. No REALTIME entitlement is inferred, no catalyst CLEAR status is invented,
and a cached bundle does not grant entry permission. Connection checks retain
explicit source-binding/catalyst blockers and reject insufficient enrolled history
coverage or mismatched source names.

Remaining coding includes original Swing source/seed binding, reviewed evidence
delivery for catalysts and Scope, replacement contract candidates, and operational
enrollment/deployment. Actual catalyst/news and Scope/SPX/context evidence is absent
from the captured six-tool interface. Contract terms, entitlement and stock sizes
also remain unresolved. These are genuine connected-operation blockers; they do
not prevent continuing other offline implementation work.

The host remains on the frozen a653cc7 dashboard. No activation or collection
command is requested for this slice. Final installed validation is in
SWING_HISTORY_FEED_PROOF.json. Stopping after publication is a **slice end**, not a
claim that all remaining coding must wait for another collection run.
