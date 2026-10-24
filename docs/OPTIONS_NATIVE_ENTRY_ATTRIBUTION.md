# Native repeated-entry cost attribution

A new native full-entry PAPER owner can explicitly enroll
`execution.loss_control.entry_cost_attribution="later-flat-entry-v1"`.
This fixes a continuity blocker: while a second paid entry was pending, its
unallocated charge could make an already closed trade's loss outcome incomplete
and prevent fresh Scope admission. The original conservative behavior remains
unchanged for existing cohorts.

The marker belongs to the frozen native loss policy. Creation requires frozen
model costs, and the coordinator/runtime requires full-entry reasoning. It cannot
be attached to a replay adapter, added to an existing owner or removed on reopen.
Omitting it preserves historical serialization. The separate Scope series
enrollment keeps its own previously implemented attribution contract.

## Required evidence

Stored reconstruction still validates the complete original typed request, model
configuration and call/input binding. The new rule applies only to an ENTRY call
whose packet proves a complete, reconciled, flat account captured after the prior
trade closed. The packet's original observation time must also be after that
close and no later than the recorded call start. Native owner and stored loss
policy enrollment must agree.

This proves that the later call does not belong to the prior holding. Its cost
remains visible in unallocated account diagnostics until it gains its own entry
attribution, and remains in full account costs throughout. Known HOLD/rejected
advice is not free. Unknown usage remains unknown and keeps account-level net
results incomplete. Management, overlapping calls and unproven linkage retain
their existing conservative treatment.

The earlier trade retains its original cash flows, fees, entry/management costs
and loss record. No loss lock, cooldown, reservation, budget or cash restriction
is cleared. A new entry must still pass native full-cost review, delivered fresh
Scope admission, account revision checks and the original approval/model deadline.
Model proposals remain separate from approval, dispatch attempts and actual fills.

## Runtime and proof

The existing installed runtime settings transport this frozen loss policy; no new
provider, model or broker adapter is added. Runtime restarts use the exact same
owner policy. Scope's original targets and session protection remain intact,
including when the owner also enrolls native Swing carry.

For this new enrollment, a paid Scope refresh waits for the current protection tick
to complete before using its delivered packet. Failed/canceled ticks cannot supply
admission; canceling the model's refresh does not cancel independent protection.
The original fresh-evidence deadline still applies. Legacy runtime cohorts keep
their existing behavior and serialization.

Outcome reconstruction also reuses successful lineage validation for identical
arguments within that one synchronous call and its existing transaction. Every
unique intent/approval is still validated; any database write disables reuse.
Nothing is cached across calls, transactions, account revisions or owners. This
removes repeated work that could stall runtime supervision without extending any
deadline or weakening stored evidence checks.

Installed-wheel tests cover successive paid Scope entries, pending-call snapshots,
CALL/PUT, combined carry enrollment, cumulative loss locks, paid HOLD, unknown
usage, corrupted linkage, old-cohort behavior, runtime delivery, frozen reopen
and portable native export. See [testing](OPTIONS_TESTING.md) and
[latest measured proof](SLICE2_STATUS.md). These are supplied-fixture checks;
authentic provider/model/host/economic acceptance remains open.

Combined carry replay now has a [separate series contract](OPTIONS_SCOPE_CARRY_SERIES.md).
Remaining family integration and one mixed stock/options owner remain plumbing before final UI and authentic PAPER testing.
LIVE stays disabled and the deployed experiment stays frozen.
