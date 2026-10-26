# Swing runtime delivery and contract routing

The collector now joins verified original Swing sources with current option
metadata, exact quote identities and explicitly supplied typed catalyst records.
The same frozen runtime settings reach normalization from both collector run paths.
This implements assembly and routing, not a catalyst provider or trading approval.
The reviewed read gateway has no catalyst/news tool, and current mapped history
entitlement remains UNKNOWN. The connected simulator is still inactive.

## Strategy routing

Degen inventories contain only contracts expiring on the current New York date,
as required by native Degen selection. A catalog can contain those contracts and
later Swing expiries without rejecting the entire delivery. All available candidate
quotes remain in the frame; held contracts outside the catalog remain in the
separate held quote collection. Shared reads are still deduplicated. This changes
no native admission, ranking, exposure, bankroll or two-play limits.

Swing metadata is joined by exact instrument identity to the original single
seed or CALL/PUT batch. It retains the current read's delta, volume, open interest,
source clock, receipt clock, completeness and entitlement. No contract replacement,
metadata repair or entitlement promotion occurs. Original sources, targets and
creation times come from the collector's raw-capture-verified binding loader.

## Evidence assembly

`app/mixed/swing_delivery.py` provides `SwingCycleEvidence` and `assemble`.
Stock and option catalysts are explicit separate records because their policies
may use different sources. Neither record has an assumed CLEAR or REALTIME value.
Duplicate and unexpected subjects are rejected. An assembled frame preserves the
exact source, seed, targets, metadata and catalyst records. Native strategy gates
still reject stale, UNKNOWN, BLOCKED, wrong-source or insufficient-horizon evidence.
Future/unordered catalyst clocks cannot enter the runtime packet; they produce an
explicit delivery blocker and retain the original market frame.

The original binding must match the full enrolled policy hash, current New York
session, exact stock universe and required single/batch source coverage. Every
required contract must match a current metadata record and candidate quote.
Missing originals, catalysts, metadata or quote identities return explicit reasons
without a partial Swing strategy set. The collector publishes MARKET instead of
CYCLE, keeping available stock, candidate and held quotes for native protection.
It does not silently remove an enrolled family to permit another entry path.

The collector's `tick` accepts typed `swing_evidence` as an internal assembly input.
There is deliberately no host file override or fabricated provider default. The
installed `run` path currently has no catalyst adapter and therefore supplies none.
A real adapter with reviewed source provenance and durable original receipts is
still required before that path can assemble complete eligible Swing cycles.
Current raw-normalized UNKNOWN history produces its retained source blockers
before the catalyst stage. Those blockers survive delivery and collector restart.

## Continuous delivery follow-up

[Continuous delivery fixes](CONTINUOUS_STRATEGY_DELIVERY.md) remove every
CYCLE-only attachment from ordinary MARKET polls and failed-history deliveries.
Prepared sources remain available for the next complete cycle. Optional intraday
history failure preserves completed books and its original failed raw receipt.
Enrolled Scope without current input now produces an explicit entry-cycle blocker.

## Delivery bounds and compatibility

Packets retain their existing version and hashes for unchanged payloads. The
coverage-reason bound expands from 10 to 64 so combined source and market omissions
do not discard available protection evidence. No stored packet or enrollment is
rewritten. The runtime's 256 KiB limit remains unchanged. Oversized strategy
context is reduced to MARKET with an explicit capacity reason, preserving quotes
and stripping strategy histories, inventories and Swing attachments. The original
capture and source binding remain retained separately. Oversized market evidence
itself is rejected; the reader's size limit is never bypassed.

Long enrolled lookbacks can still exceed the packet budget. The fallback is honest
protection-only delivery, not acceptance of that strategy configuration. A future
compact source-reference transport would need its own verified runtime contract.

## Validation and remaining work

SWING_RUNTIME_DELIVERY_PROOF.json records isolated installed-wheel tests. They
cover mixed expiries, exact single targets and complete batches, two independent
underlyings, native catalyst rejection, missing-input CYCLE-to-MARKET conversion,
retained blocker/quote delivery across restart, diagnostic capacity and oversized
packet fallback. Existing native selection, batch, runtime, connection, source
binding and collector suites run against the same wheel.

Explicit [carry-intent schedules](CONNECTED_CARRY_INTENT.md) now reach source
binding and runtime assembly. Remaining work: reviewed catalyst/news ingestion and
provenance, operational schedule rollover, Scope SPX/context delivery, data entitlement and stock
sizes, complete reviewed contract terms, candidate replacement, operational host
enrollment and dashboard activation. Actual daily/hourly response acceptance and
ongoing market execution/reconnect evidence remain pending. The accepted October
26 quote proof does not need repeating to continue offline implementation.

This publication stops at a **slice end**. More offline coding is possible. No
server changes, provider/model calls, credential access, new account or live order
routing occurred. The dashboard still runs the a653cc7 frozen review image.
