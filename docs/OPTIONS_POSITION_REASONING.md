# Position reasoning: reviewed proposals and bounded model worker

P3 management contract and native-worker slice, 2026-10-12 UTC. The model can
propose **MAINTAIN, EXIT_ALL or TIGHTEN** for one exact held option position.
Deterministic review and a bounded native worker are implemented. Durable management
attempt admission, cost settlement, revision consumption and action application
are the next slice. No coordinator, replay arm or deployed service invokes this
worker yet. Existing A/B/C behavior and frozen populations remain unchanged.

## Trusted packet and strict output

`PositionPacket` binds the original entry intent/thesis, exact current position,
original and effective invalidation, target/time protection, current account,
option/underlying quotes and completed Degen context. Six supplied evidence IDs
identify position, entry, account, option quote, underlying quote and scan. It
also freezes limits, execution policy, management policy, model-configuration
hash, decision ID, position revision and original five-minute slot/deadline.

Construction revalidates exact entry/position/instrument identity, authoritative
holding correspondence, healthy reconciled account and fresh executable market
evidence. Completed context must be current and free of scan issues. A confirmed
new entry setup is not required to reconsider an existing thesis. Independent
mandatory protection is evaluated before a packet can become usable. The lease
is at most the explicit policy limit (maximum 30 seconds), the end of its original
slot and the earlier position/expiry protection deadline. Packet size is capped
at 256 KiB. Caller-supplied evidence hashes bind content, not provider authenticity.

`PositionPlan` is strict structured output containing the exact packet/decision,
entry client ID and position revision; evidence references; bounded thesis,
change since entry and uncertainty. Only TIGHTEN carries an underlying USD
invalidation price. MAINTAIN and EXIT_ALL carry no price terms. Quantity, new
contracts, targets, horizons, scale-in, partial exit and risk overrides are not
fields. Prices use the existing bounded Decimal format; floats, booleans,
nonfinite values and excessive precision/exponents are rejected.

## Fresh deterministic review

`review_position_plan(packet, plan, position=..., position_revision=...,
account=..., quote=..., underlying=..., now=...)` revalidates packet and output,
including unchecked model copies. It requires matching lineage and references
to both owned position and completed context. Fresh trusted inputs are supplied
by the caller after cost settlement; this pure function cannot verify a durable
cost receipt or acquire authoritative broker data itself.

Wrong/closed/revised ownership rejects old advice. For matching ownership,
mandatory stop, premium catastrophe, time, expiry and target checks precede any
advisory result. Those checks now live in `app.options.protection`, shared with
the existing durable supervisor. The original latch, timestamp, precedence and
stale-data behavior are preserved. MAINTAIN cannot clear a prior exit or override
a newly due one. A time/expiry exit remains due even without executable quotes;
the review does not invent a sale or mutate the stored latch.

Any other position-state change, expired lease, halted/unknown account, unresolved
order, missing/stale/delayed quote, foreign instrument or regressed evidence blocks
discretionary changes. Halt handling stays with independent software; it is not
permission to dispatch a model exit. Fresh lower account balances do not grant
additional exposure, and missing model costs do not become zero.

- MAINTAIN returns no action and no authority.
- TIGHTEN must strictly improve the current effective stop, which is itself
  bounded by the original invalidation. CALL stops rise below current underlying
  bid; PUT stops fall above ask. Equal, wider or crossed stops reject.
- EXIT_ALL produces a CLOSE proposal only after fresh existing option admission.
  Approved quantity must equal the authoritative held quantity. Insufficient
  displayed size rejects this discretionary full-exit proposal instead of turning
  it into an unrequested partial scale-out. Approval lifetime cannot exceed the
  original packet lease. Independent mandatory exits retain their existing rules.

Results are MAINTAIN, REJECTED, ELIGIBLE or MANDATORY_EXIT, always with
`execution_authority=false`. No order, stop mutation, reservation, journal write,
reconciliation, recovery or network call occurs in pure review. Repeating a review
is intentionally not durable revision consumption. The next integration must
commit that consumption and action evidence atomically and reject replay/races.

## Native model boundary

`position_judgment.configuration` freezes model/token prices, token/process/cost
ceilings, management policy and prompt/schema hashes. Maximum configured token
charge must fit the per-call reservation. `create_request` requires matching
native execution cost policy, remaining original lease, unique request ID and
parent PID. It neither admits a durable attempt nor settles a charge.

`run_position_process` starts the installed `app.options.position_judgment_worker`
with `-I`, a separate process group and only the model key plus basic locale/path
variables. The child has no tools, broker credentials or journal handles. This
is a process/protocol boundary, not an OS filesystem/network sandbox. The SDK
origin is fixed, retries disabled and the same full strict-schema payload is
counted before one generation. No tools, streaming, background work or storage.

The 256 KiB request and 128 KiB response pipes, original deadline, parent watchdog
and process-group cleanup bound failures, overflow and repeated cancellation.
Binding hashes/IDs are supplied to copy, not assigned as a model hashing task.
Success requires matching position/request/configuration, bounded matching usage
and original-evidence review. That review never replaces fresh post-cost review.

Refusal, invalid geometry, malformed/incomplete output and late completion yield
a bound MAINTAIN with an error class only. Already observed usage is retained,
including unusable/foreign usage as evidence rather than settled cost. Missing
usage or an undecodable/lost child remains unknown. Error MAINTAIN grants no
permission to skip protection, resume an engine or retry a billable attempt.

## Proof and next integration

Tests exercise CALL/PUT actions, effective versus original stops, revision/state
changes, all mandatory triggers against each action, account/market blockers and
strict SDK serialization with fake responses. Native process tests cover the
worker entry point, credential-environment separation, overflow, timeout, malformed
output and repeated cancellation. Actual installed-package results are recorded
in [status](SLICE2_STATUS.md). No authentic model/provider call or profitability
claim is made.

Next: opt-in new-cohort durable management enrollment and bounded attempt/cost
accounting; atomic once-per-revision action consumption with mandatory-exit
precedence; arm D replay/export and stored proposal/approval/fill attribution.
Actual market/model acceptance, continuous options runtime, visual dashboard,
prospective evaluation and host/recovery gates remain in the
[source of truth](SOURCE_OF_TRUTH.md). LIVE remains disabled.
