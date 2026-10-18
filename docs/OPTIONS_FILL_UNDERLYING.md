# Underlying observations bound to option fills

Native PAPER receipts can now retain an optional `OptionFill.underlying` quote.
It is the supplied underlying observation available at the option fill time,
with its original source and receipt timestamps. It is **not an underlying
transaction price**, the setup reference, or the earlier approval quote.
This supplies the missing evidence needed for subsequent actual-entry management
binding without inventing a stop rule or granting new execution authority.

## Recording and validation

The local fixture venue accepts:

```python
venue.fill(intent, quantity, option_quote, filled_at,
           fill_id="unique-fill-id", underlying=observed_underlying_quote)
```

An explicitly supplied observation must match the exact option's underlying and
the owner's frozen source. It must be complete, REALTIME, uncrossed, above the
owner's minimum underlying price, fresh at the fill time and within the frozen
receipt-lag and option/underlying synchronization limits. Source and receipt times
cannot be in the future. These are the existing owner limits; no separate relaxed
fill-time limits are introduced. Invalid supplied evidence rejects the entire
fixture fill before mutation.

The same checks run independently during native reconciliation and portable
accounting replay. A venue cannot bypass them by constructing its own receipt.
Every partial fill retains its own exact quote. Complete receipt equality protects
accepted history: adding, removing or changing an underlying observation later is
a fill conflict, even if quantity, premium, fees and cash would remain identical.
Reconciliation retains the existing halt and accounting rollback behavior.

The field is optional and omitted from serialized receipts when absent. Historical
receipts preserve their original encoding and cannot be backfilled from approval
prices or a later observation. A mixture of observed and unobserved partial fills
remains a mixture; one quote does not establish coverage for the whole entry.
The code does not average quotes or select a favorable quote as the entry basis.

## Replay, export and stored attribution

The independent replay scheduler attaches the latest usable underlying quote
already delivered to that account at the fill instant. It checks the same source,
freshness and synchronization limits. Missing or unusable context is left absent;
it does not erase an otherwise valid option fill, its fees or its ownership.
A later event, including one delivered later at the same timestamp, cannot rewrite
that receipt. The existing rule that only newly delivered option quotes can fill
remains unchanged.

Native export retains the complete receipt. Sealed-tape verification additionally
requires each attached underlying quote to exist in the recorded prefix by its
fill time. Missing or late evidence makes the comparison inconclusive and withholds
net totals. Quote hashes establish content consistency, not provider authenticity.

Order and decision attribution optionally include `fill_underlyings`, one record
per evidenced fill: fill ID, quantity, occurrence time, complete fill hash and exact
underlying quote. The evaluator reconstructs this projection from the receipts;
removing or changing the projected evidence fails attribution validation. Compare
the sum of these quantities with `filled_quantity` to assess coverage. An omitted
list does not mean zero underlying price or complete evidence.

The stored observer exposes the same order attribution and an explicit nullable
`underlying_observation` for each displayed fill. Reads do not obtain new quotes,
refresh evidence or change journal state. Original proposal and approval evidence
remain separately stored. Independent accounts retain their own receipts and costs.

## Management and acceptance boundary

This is an evidence dependency for actual-entry target protection. It does not yet
convert the observations into a Scope entry reference or enable Scope orders.
The existing progress-health baseline still uses its documented original approval
reference; this change does not silently change that diagnostic or its frozen policy.
Scope still needs a reviewed fill-bound stop rule, watch/order/family-loss linkage,
complete path requirements, four-contract T3 resolution and runtime enrollment.

Option fill prices, conservative slippage, every entry/exit fee, all entry and
management model charges, and unknown-cost treatment are unchanged. Neither an
observed quote nor complete quote coverage is a profit, a guaranteed stop price,
a filled underlying trade or a reduction in full-premium risk.

Installed fixture validation covers both option directions, distinct partial-fill
observations, missing/invalid evidence, immutable history, restart, read-only
reporting, delivered-prefix replay, sealed-tape timing, attribution tampering and
independent A/B/C/D full-cost accounting. Authentic provider and final UI/data/host
acceptance remain separate. Main stays untouched, PR #1 draft, LIVE disabled and
the deployed experiment frozen.

See [execution](OPTIONS_EXECUTION.md), [Scope management](OPTIONS_SCOPE_MANAGEMENT.md),
[managed replay](OPTIONS_MANAGED_REPLAY.md) and [status](SLICE2_STATUS.md).
