# Quote-driven simulated fills and dashboard correction

The continuous mixed runtime previously accepted normalized market packets but its
tests supplied fills manually. A newly frozen mixed runtime can now explicitly set
`simulated_fills` to `mixed-quote-fills-v1`. This consumes the same delivered packet
and existing native venue; it does not introduce a second execution engine.
Existing policies omit the field and retain their prior serialization and behavior.

After native delivery validation, acknowledged OPEN/PARTIAL orders may receive a
later executable quote before the usual reconciliation and independent protection
tick. Original fixed limits, source and receipt clocks, instrument identity,
entitlement, displayed size, slippage and fees are checked by the existing replay
and native fill rules. The source observation must be later than the native
attempt. Missing size, delayed/stale quotes, an unexecutable price or an unresolved
attempt cannot manufacture a fill. A repeated packet or new receipt timestamp for
the same source quote does not replenish displayed size. Conflicting source prices
halt entry; reconciliation and independent protection still run. An ambiguous
attempt may be resolved only by the existing native reconciliation path; this
helper neither resubmits it nor clears the halt.

Partial fills use remaining observed size. New native exit orders wait for a later
quote just like entries. Available matching underlying evidence accompanies option
receipts; unavailable evidence remains absent. Acknowledged expired orders become
EXPIRED without proceeds. Settlement stays explicit: closing a simulated position
does not make its proceeds immediately settled. Approval, source retirement,
strategy selection, loss control and native deadlines are unchanged.

## What still prevents connected PAPER testing

This change is tested with normalized offline packets. It is not a Robinhood feed
or a claim that Monday's connected test is ready. The repository has a legacy stock
reader and a bounded six-tool schema/sample capture command; the mixed owner still
needs exact provider response mapping and an ongoing normalized delivery loop.
The current workspace contains the retained discovery digest and receipt, but not
the actual six-tool schema export or authenticated market samples. Old stock quote
conversion is not proof of the metadata, size, timestamps, entitlement, completed
history and options coverage required by the mixed engine. Those fields must not
be inferred or relabeled to make admission pass.

The next concrete input is the schemas-only export from the existing discovery
artifact in `/root/trade-bot-options-auth-BqLFmz`. The actual filename is not known
here. [Offline export instructions](OPTIONS_READ_CAPTURE.md#export-retained-schemas-without-a-provider-call)
extract only the reviewed schema object, with no OAuth access or network calls.
Review that export, prepare an exact bounded read plan, and retain actual response
samples before implementing and verifying the provider mapper. Authentic reads and
prospective PAPER activation remain separate from this authorized offline work;
no such call or activation occurred in this revision. The old SHADOW deployment
and its credentials are not a shortcut for this missing acceptance.

## Dashboard changes

The operator's October 24 21:07 desktop screenshot shows the deployed e6fd353
layout and confirms the overlapping price labels and disconnected known equity
endpoints. Missing intermediate valuations remain null in the underlying data and
exact-value table. Dashed links now connect the known endpoints visually, with an
explicit unavailable-valuation caption; solid measured segments still break at
missing values. No intermediate equity or return is calculated.

Exact trade labels now flow beneath the rail in a responsive list keyed to compact
numbered markers. Original stop, active stop, entry, saved bid and target values
remain visible without competing for absolute-positioned text space. Page reads
still perform no provider, model, fill or trading work.

The guarded `refresh ui-review-v2` action requires the deployed e6fd353 reader and
retains it as `trade-bot-dashboard-before-chart`. It reuses the existing frozen v2
journal read-only. V1, v2, both older rollback readers and the original SHADOW
worker/observer remain preserved. Do not rerun fixture preparation.

## Evidence

[Installed verification](MIXED_QUOTE_FILLS_PROOF.json) records the wheel digest,
source/wheel/installed byte identities, exact test cases and screenshot hash.
Tests run serially from copied tests outside checkout with a noneditable wheel,
Python `-I`, warnings as errors, plugin autoload disabled and explicit anyio.
No dependency changed. Host Docker acceptance of this revision and actual browser
review/screenshots remain pending. The supplied screenshot is baseline evidence,
not visual acceptance of these changes.
