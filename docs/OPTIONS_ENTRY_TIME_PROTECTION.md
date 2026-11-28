# Deterministic entry deadlines

New native PAPER cohorts may enroll
`OptionExecutionPolicy.entry_time_protection="tighten-only-v1"`. Trusted
deterministic `OPEN_LONG` preparation can then supply
`EntryTimeProtection(exit_by=...)`. The deadline requires an aware timestamp and
freezes in the original decision, approval, buy intent and filled position.
Existing cohorts omit the optional field and cannot add it on reopen.

This closes a Scope execution prerequisite. The pinned SignalFlow approved V2
playbook at `f9eaf2c1b5d13dca287ee7138126883065b00395` requires remaining modeled
positions to exit by 15:45 ET. Previously deterministic native entries could use
only the owner's session/expiry cutoff; the separate AI entry-plan horizon also
required a model plan and target. A deterministic target-managed entry could not
bind its own earlier strategy deadline.

## Earlier deadlines only

The effective exit time is the earliest of:

- The entry's explicit `exit_by`.
- The owner's actual session close minus its frozen exit-cutoff interval.
- The exact contract's last trading instant minus the frozen expiry guard.

A later requested deadline never postpones a stricter owner/expiry cutoff. An
elapsed effective deadline rejects preparation without an order. The entry's
approval validity is shortened to this time, and the buy's DAY-order lifetime
ends there. Dispatch at the deadline rejects; an already attempted buy cannot
receive a fixture fill at or after its order deadline.

The parameter is not a model proposal field. MODEL/PROTECTIVE origins, HOLD/CLOSE
attachments and full model entry-plan combinations cannot use it. Existing model
horizons retain their own contract. Every successful deterministic deadline must
be explicitly enrolled by the frozen owner.

Dispatch and reconciliation verify the original decision/approval/intent binding,
owner enrollment and exact stricter session/expiry result. Changing both the intent
and approval cannot replace the original decision's deadline. Source-key retries
cannot change it. Accounting carries the original terms through partial buys,
whole-contract scales and remaining runners. Reconciliation rejects a changed
venue position deadline or binding, and restart retains the original terms.

## Mandatory exits and unresolved orders

With fresh reconciled account evidence, supervision latches the existing
`TIME_EXIT` at the effective deadline even if market quotes are missing. Missing
quotes cannot manufacture a sale. A later usable quote can drive the governed owned
exit; the sell's lifetime is not cut off by the already elapsed entry deadline.
Earlier expiry, stop, premium and other mandatory protections keep their existing
precedence. A timer trigger is not a guarantee of execution by that instant.

A mandatory deadline preempts an unattempted partial-close intent. An attempted or
unknown order keeps its reservation and must be reconciled. The deadline does not
invent a cancellation or terminal fill. The existing review requirement after a
canceled/failed attempted exit remains in force. Likewise, stale account evidence
still blocks supervision; reopening does not replace reconciliation.

No entry/exit fee, settled-funds restriction or entry/management model charge changes.
Known and unknown costs retain their existing treatment. Independent accounts can
hold different deadlines without sharing protection state. Failed native writes
roll back decision and order state together.

## Scope handoff and stored evidence

`ScopeWatchBook.entry_selection()` now includes `entry_time_protection` derived
from the original locked `ScopeSession.protect_at`, already covered by its original
watch and whole-record binding. The caller cannot supply a replacement deadline to
that read. The native owner still takes the earlier deadline when this handoff is
ultimately integrated with execution.

This does not enable Scope dispatch. The existing Scope entry guard remains in
force; order/fill linkage, full-cost Scope family loss/reset, path requirements and
runtime acceptance remain open. The four-contract missing-T3 blocker is unchanged.
The supplied index session is not authentic provider/calendar acceptance.

Stored order and decision attribution retain the original time terms. Owned closing
attribution inherits them from the exact entry without giving the sell a new entry
horizon. Native export carries the deadline and position evidence; portable accounting
checks owner enrollment, strict lifetime and exact reconstructed ownership. Changed
saved protection cannot disappear as a harmless management annotation. An open
position at an export boundary remains inconclusive, with no invented closing price
or net return.

Installed fixture checks cover both directions, exact deadline boundaries, missing
quotes and recovery, scale/runner/restart behavior, partial-entry expiry, attempted
reservations, stricter owner and expiry cutoffs, original-decision tampering,
independent owners, rollback, Scope handoff and portable export. Related regressions
retain every entry/management cost across independent A/B/C/D owners.

See [Scope entry binding](OPTIONS_SCOPE_ENTRY_BINDING.md),
[target exits](OPTIONS_TARGET_EXITS.md), [execution](OPTIONS_EXECUTION.md) and
[status](SLICE2_STATUS.md). Main untouched, PR #1 draft, LIVE disabled and deployment
frozen; UI and authentic provider/model/host/economic acceptance remain final passes.
