# Explicit connected carry intent

The collector can now receive an optional frozen schedule of original Swing exit
dates. It uses the existing owner and native carry policies. It does not create
another account, choose a holding period, change limits or extend an existing play.

## Input and binding

`FeedPolicy.carry_intents` accepts at most 32 unique target-session records. Each
record names `target_session` and an explicit `stock_exit_session`,
`option_exit_session`, or both. Dates must be later than the target and within
sixty calendar days. The existing native policies can impose stricter limits.
History enrollment is required. There is no default holding date or inference
from a policy's maximum carry allowance. All symbols in the enrolled stock/option
Swing universe use the specified date for that asset class on that session.

The stock and option dates can differ. An option-only intent leaves stock sources
at their original session-close behavior. An option policy requiring carry still
blocks preparation when its matching option date is absent. The schedule cannot
enable an unenrolled asset's carry policy. The read-only connection check rejects
that mismatch before opening collector state or credentials.

The collector selects the exact target session during preparation, restart
verification and current packet assembly. The intent and native stock carry
policy/option expiry guard become part of the source-binding policy hash. They
flow unchanged into stock sources, single option seeds or complete batch roots.
The original creation time and derived targets remain unchanged on reuse.

## Native calendar authority

Stock preparation reuses the native stock calendar path. Option preparation uses
the native structural carry path, now shared with the existing carry preflight.
It checks actual sessions, calendar/session limits, half-day exit windows, each
original contract's expiry-session buffer and its explicit last-trading cutoff
with the owner's expiry guard. Conflicting legacy and scheduled dates are blocked.
No catalyst record is invented to perform these structural checks.

The original carry preflight still separately requires catalyst coverage through
the exit. Runtime admission and execution retain all source, quote, catalyst,
account, risk and ownership checks. A scheduled date does not extend catalyst
validity or promote UNKNOWN history. Current normalized history remains blocked.

## Restart and compatibility

The schedule is frozen in collector enrollment. Restarting with edited dates
fails the existing configuration fingerprint check. Source receipt verification
rebuilds from the original capture, intent and creation time; it cannot restamp
or rewrite the first per-session result, including blocked receipts.

Absent schedules serialize exactly as before, preserving legacy collector and
binding hashes. No existing journal, fixture or enrolled collector is migrated.
Adding or rolling a schedule requires a separately reviewed enrollment/rollover
procedure. That operational workflow remains unfinished; do not edit the frozen
review or existing collector configuration in place. No real dates have been
selected or enrolled on the host by this change.

## Validation and remaining work

CONNECTED_CARRY_INTENT_PROOF.json records isolated installed-wheel tests. New
coverage includes distinct asset dates through native batch preparation and
runtime assembly, invalid calendar/expiry/session bounds, missing/enrollment
mismatches, omitted schedules, no implicit stock carry, retained UNKNOWN-history
blockers across restart and rejection of changed frozen dates. Existing single
seed/batch binding, transport, native stock/option carry and coordinated-runtime
suites run against the same wheel.

This completes the bounded explicit carry-input path, not operational activation.
Catalyst ingestion still requires a reviewed source/schema absent from the six
market-read tools. Scope feeds, entitlement, stock sizes, complete contract terms,
dynamic candidates, schedule rollover and guarded host setup remain work.

Stopping reason: **slice end**. More offline implementation is possible. No
provider/model calls, credentials, server changes or live routing occurred.
