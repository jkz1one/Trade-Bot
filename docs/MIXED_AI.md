# Paid mixed entry and native position management

The create-only `mixed-paid-entry-v1` owner connects paid entry and management to
one native stock/options cash history. Its complete request, original evidence,
usage, native approval, attempt and actual fills remain separate durable records.
This is offline fixture implementation; provider/model acceptance, continuous
[mixed runtime](MIXED_RUNTIME.md) is separately enrolled; independent mixed A/B/C/D replay/export remains.

## Enrollment and original entry evidence

The native mixed owner, stock selection and full entry policy must all declare
`mixed-paid-entry-v1`. Model costs and bounded judgment limits are mandatory. A
fresh stock reader is required. Optional management declares
`mixed-stock-position-v1`; Scope and option Swing carry still require their existing
matching enrollment. Existing owners serialize without these absent fields and
retain their original deterministic or paid contracts. Old replay adapters remain
rejected; they cannot substitute a choice-only result for a full paid receipt.

One bounded, tool-less worker sees the complete admitted stock, native option and
Scope alternatives. `mixed-entry-thesis-v1` uses a strict `MixedEntryPlan`:

- HOLD retains the paid decision without an order.
- Stock ENTER selects one exact original source and admission. The model supplies
  thesis and uncertainty; original quantity/price ceilings, stop, all objectives,
  source clocks, carry and exit deadline remain native terms.
- Ordinary option ENTER retains the existing full entry-plan review and native
  approval contract.
- Scope ENTER retains the original fixed plan and requires a fresh owned admission
  after usage settlement. Its original approval/request deadlines still cap entry.

Each stock alternative includes the full original frame source, completed scanner,
policies, cash history, account snapshot/revision and original admission. Stored
verification reconstructs the source and admission and binds every alternative to
the frozen request and admitted call hash. Native selection receipts identify the
actual chosen asset/family. Scope's fresh source key replaces only that selected
receipt after full fresh admission; it does not rewrite the original model evidence.

Every call is admitted durably before generation. Known usage is retained even for
HOLD, rejected advice or late responses. Input count, usage/model identity, original
packet, configuration, proposal hash and exact configured charge are checked. A
missing or foreign receipt stays unknown and blocks entry. The worker has no broker,
journal or execution handles. Requests and responses remain bounded by the existing
256 KiB/128 KiB limits; excessive evidence cannot silently drop alternatives.

Stock preparation uses a bounded refreshed quote, exact original identity and
nonregressing source clock, then recomputes admission after the charge. Dispatch
checks fresh native state again. Neither step extends the original source, account,
request or approval deadline. Actual stock fills still need later executable quotes.

## Held stock management

`StockPositionPacket` carries real shares, the original native entry, complete
original source/admission, original paid thesis, current remaining position,
protection, full cash history, account revision, exact quote and completed scan.
It never fabricates an option contract. Stored current context is rebuilt from the
retained cycle and frozen scanner. The original stock source, carry and objective
ladder remain unchanged.

The existing bounded position worker and strict PositionPlan support MAINTAIN,
TIGHTEN and EXIT_ALL. A stock TIGHTEN only raises the native invalidation below the
current executable bid. EXIT_ALL requests the exact remaining shares. Management
cannot scale, increase exposure, widen protection, replace targets or extend time.

The owner supervises independently before and after paid reasoning. Current quote,
account, held quantity, protection, revision and the original short lease are
rechecked after cost settlement. Partial closes or changed position evidence during
the wait reject the obsolete proposal. Mandatory stop/target/time exits precede
advice, including failed or unknown-cost calls. An unavailable quote blocks an
executable exit without inventing a price or suppressing the latched protection.

Decision consumption, a tighter stop and its event share one journal transaction.
Full closes use the native preparation/attempt/fill path under the same transaction
and lease. Completed slots do not repeat calls after restart. An interrupted attempt
retains unknown cost and remains unavailable for retry. Original entry and management
receipts are verified during stored order/account reconstruction.

Ordinary option and Scope management retain their existing native position, partial
close, target, premium, time and carry rules. Scope's held context explicitly accepts
the full mixed entry plan while preserving the original fixed Scope selection.

## Costs and loss history

The mixed cash history reconstructs every admitted entry/management call from its
full stored request and usage. Lost calls, changed charges or altered paid proposals
cannot turn advice into a free decision. Unknown remains unknown. Broker cash stays
separate from economic cost, and all admitted charges reduce common loss headroom.

One allocator assigns a management charge to its exact native entry; other charges
belong to the holding at call time or the next actual filled entry. Idle charges
remain in the account ledger until then. The allocator covers both shares and
options, including HOLD and rejected entries, without subtracting a charge twice.
An entry call at the exact prior close clock belongs to the following actual entry;
management retains its explicit original holding. Pending management keeps the
affected trade incomplete until the cycle finishes.
All execution fees and explicit daily data/host/operating allocations remain in the
full-cost outcome and common global/family loss controls. Unknown allocations or
usage suppress net results. Native option outcome reads in this explicit paid mixed
cohort include the same full allocation as stock outcomes.

## Remaining plumbing and proof

[Continuous mixed runtime](MIXED_RUNTIME.md) now connects delivered sources,
independent protection, explicit settlement and session/restart recovery. The final
plumbing track is common mixed tapes, matched independent A/B/C/D native accounts
and portable replay/export, including every charge, fee, operating/overnight
allocation and unknown cost.

Legacy runtime envelopes, tape consumers and option-only exports still reject mixed
inputs. Bind complete new contracts before accepting them. Final UI/visual and
actual provider/model/host/economic/PAPER acceptance follow the plumbing. LIVE stays
disabled and deployment remains frozen.

`test_mixed_entry.py`, `test_mixed_position.py` and `test_mixed_paid_carry.py` exercise the real installed native
owner and local mock worker transports without authenticated calls. See the newest
[status receipt](SLICE2_STATUS.md) for distinct completed final-wheel cases and
[testing](OPTIONS_TESTING.md) for isolation and proof requirements.
