# Continuous strategy and protection delivery

This slice fixes two transport failures exposed while tracing the remaining
catalyst connection. It adds no provider, account, trading permission or activation.

## Prepared sources between cycles

A valid prepared Swing source can accompany a five-minute strategy cycle. The
intervening quote polls are MARKET deliveries, whose native schema forbids Swing
seeds, batches, stock sources and catalysts. The previous normalizer removed only
histories and inventories when choosing MARKET. Once a source was prepared and
current evidence supplied, those remaining attachments could make a quote poll
fail packet validation and prevent publication.

All MARKET conversion now uses one projection that preserves stock, candidate,
held and underlying quotes while removing every CYCLE-only strategy attachment.
The original source binding remains stored separately and is reused in the next
complete cycle without changing creation times or targets. The oversized-packet
fallback uses the same projection. Native runtime schemas remain strict.

Tests exercise stock-only, option-only, single-seed and complete-batch enrollment
through CYCLE, MARKET and CYCLE again. A collector publication/restart test supplies
a separately native-validated synthetic source at the loader boundary. This is
explicit offline isolation: actual normalized history stays UNKNOWN and cannot
produce a prepared source. It is not evidence of eligible connected history.

## Failed historical reads

The fixed collector requests current equity/option books before intraday history.
If that strategy-history read fails after quotes have completed, those books now
remain deliverable. Missing, failed, schema-invalid or unusable planned intraday
history produces INTRADAY_HISTORY_UNAVAILABLE and a MARKET packet. Optional
pre-open history keeps its existing separate SWING_HISTORY_UNAVAILABLE reason.
A failed capture with completed observations, such as a close-stage failure,
produces CAPTURE_INCOMPLETE and cannot become an entry cycle.

Original captured receipts, including FAILED status and malformed raw history,
remain unchanged in the durable attempt. The collector's DELIVERED status means
a normalized market packet was published, not that every source read succeeded.
A required quote call that did not complete still fails the delivery; an optional
history call cannot conceal missing required market receipts. Existing per-subject
unavailable-book handling and source-clock regression checks remain authoritative.

## Explicit Scope coverage

When Scope is enrolled but the collector has no current Scope input, it records
SCOPE_CURRENT_INPUT_UNAVAILABLE and publishes MARKET. It cannot silently evaluate
an incomplete enrolled strategy universe as an entry cycle. Available SPY/QQQ
quotes still reach native protection. This does not provide missing SPX books,
Scope context, watch creation or advancement; those adapters remain unfinished.

## What still blocks the provider work

The reviewed gateway exposes exactly six market-read tools: equity quotes and
history, option chains and instruments, option quotes and history. None provides
catalyst/news clearance or the required Scope context. A real catalyst adapter
needs a reviewed source schema and original response evidence. No fake CLEAR,
entitlement override, invented endpoint or generic file bypass was added.

Other offline implementation remains possible, including operational host setup
and explicit original carry-intent delivery. Contract/data eligibility, stock
sizes, dynamic candidates and market acceptance also remain outstanding. The
accepted regular-session quote proof does not need repeating for these fixes.

CONTINUOUS_STRATEGY_DELIVERY_PROOF.json records isolated installed validation.
The publication stops at a **slice end**; the specific catalyst provider adapter
has a **missing reviewed feed/schema blocker**. Server and frozen a653cc7 review
remain unchanged. Connected simulation is inactive and LIVE stays disabled.
