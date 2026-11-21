# Native two-play PAPER implementation

The v2 lifecycle is implemented in the existing native owner. It supports at most
two simultaneous plays sharing one bankroll across Degen, Swing and Scope. Two is
a ceiling, never a fill target. This supersedes the earlier order-free capacity
checkpoint. See [installed proof](TWO_PLAY_NATIVE_PROOF.json) and
[deployment/acceptance](TWO_PLAY_ACCEPTANCE.md). Connected market acceptance and
browser acceptance remain pending; LIVE remains disabled.

## Authoritative lifecycle

`mixed/portfolio_store.py`, `portfolio_execution.py`, `portfolio_options.py` and
`portfolio_venue.py` add explicitly enrolled v2 tables and snapshots to the existing
SQLite journal, runtime lease and restore authority. The original BUY client ID is
the play ID. Native options require their retained original strategy selection.
One transaction replays all receipts, reviews shared risk, claims capacity and
funds, and saves the complete approval. Per-play active-order uniqueness permits
independent exits without competing account owners. No strategy wallets exist.

Partial entry fills transfer only actual filled debit into invested basis; the
unfilled reservation remains. Only terminal evidence releases its unfilled part.
Uncertain attempts, pending exits and held runners retain capacity. A durable
SUBMITTING marker becomes UNKNOWN after restart; retries do not resubmit. Repeated
receipts cannot duplicate balances. Reconciliation verifies the complete original
order/fill prefix and every held identity. Original stops, theses, quantities,
target schedules and model receipts remain separately bound to each entry.

Same instrument/underlying overlap is blocked. SPY/QQQ/SPX/SPXW share the frozen
index-exposure cap and the account loss budget. Adding a slot does not increase
risk limits. Remaining cash, invested loss, unfilled debit, exit fees, settled
funds, known model/operating costs and unknown-cost blockers are reconstructed
inside the owner. Sale proceeds retain the existing settlement treatment.
Contract settlement names an exact play; account funds settlement remains global.
Physical exercise remains unsupported account exposure, never a new strategy play.

`portfolio_protection.py`, `portfolio_targets.py` and `portfolio_loss.py` supervise
every held play before optional entries. Stale or absent evidence blocks only the
unsupported action; another play still receives supported mandatory management.
Target exits use original cumulative allocations and actual sales. Full-cost
floors, trailing protection, time exits and independent invalidations retain their
native rules. Completed loss outcomes charge every cost once and preserve account
and family pauses. Unknown outcomes cannot silently become profitable outcomes.

## Selection and model protocols

`portfolio_selection.py` admits deterministic choices sequentially, following the
configured family priorities and rechecking after each reservation. A held Swing
play does not globally occupy the account. HOLD, stale data, funds, capacity and
exposure reasons remain distinct. Scope still needs fresh source observations;
the second slot does not waive original arming/admission rules.

Paid entry uses an explicit `portfolio-entry-packet-v2` with full shared history.
The existing one-call opportunity budget is preserved; no extra call is made to
fill the other slot. Degen/Swing retain original scans; Scope retains its full
original/fresh watch packets, settled usage, original ceiling and original expiry.
Each charge is linked to its actual selected play, including Scope's separate
native source key. Output remains advice, followed by native reapproval.

`portfolio_position.py` and `portfolio_management.py` add a versioned management
packet with exact play ID, original entry/context/decision, current completed
context, full history, protection and revision. Unknown, closed or changed IDs are
rejected. Full receipts and costs bind the native close/tightening. Optional
management rotates among eligible held plays and shares the existing opportunity
budget with paid entry. Mandatory protection continues after failed model calls.

## Feed, dashboard and controls

`continuous_feed.py` and `feed_cli.py` persist original read plans, captured results,
normalized packets, sequence gaps and delivery hashes. A single collector lease
and persisted read budget prevent duplicate collectors and restart quota resets.
Shared equity/option reads are batched; held contracts remain requested when no
longer candidates. Missing subjects do not remove healthy peer quotes. Source
clocks never advance merely because a packet is delivered, and regressions remain
rejected across missing deliveries. Interrupted reads are retained, not blindly
retried as the same request. Delivery is atomic and recoverable from durable data.

Current reviewed mapping covers SPY/QQQ equities/options. An unsupported held
mapping, including Scope/SPX, is explicit coverage evidence, never an invented
quote. Unknown entitlement, unreviewed contract metadata and missing equity sizes
remain blocking. This completes the available offline transport/mapping wiring;
it does not claim that these external evidence gaps are resolved.

The stored observer exposes complete cards for both held plays. A compact selector
shows symbol, family and per-play P&L; original thesis/protection/fills are scoped
to the selected identity. Polling preserves play/tab/disclosure/scroll/focus.
Closing a selected play cannot transfer its state to another card. Missing/stale
marks remain unknown. Account totals and option premium/underlying prices remain
separate. Relevant stream records include play IDs. All lower detail tabs retain
420px default height, internal scrolling and explicit Trades expansion.

The optional authenticated admin lightbox queues existing signed, expiring,
revision-bound operator commands. Server and owner enforce integer 0/1/2 limits;
replays and stale revisions cannot apply. Lowering a limit never closes holdings.
The lightbox appears only with explicit operator-inbox enrollment. A frozen review
has no control authority. Page reads never start provider/model/execution work.

## Deliberate compatibility and rollback

Existing databases and frozen review populations keep their original v1 enrollment.
New binaries read and execute that unchanged protocol. They do not silently turn
one-play fixtures into two-play accounts, rewrite IDs, change policy hashes, or
fabricate positions. There is intentionally no in-place conversion of a held v1
account: finish/preserve it under its original policy and enroll a separate v2
PAPER population. The original files remain inspectable.

Before a binary change, stop the owner and use the validated
`python -I -m app.mixed.portfolio_compatibility --journal ABS_JOURNAL --venue ABS_VENUE --output NEW_ABSOLUTE_BACKUP`
command. It takes the owner lease, verifies the matching journal authority and
venue, and copies all three SQLite files with exact hash proof, restrictive modes
and a manifest. It copies no credentials. The backup is evidence, not a relocated
population: the frozen configuration retains the original venue path. Restore all
three matching files to their original paths while stopped. Never combine a
journal with another authority/venue, or run an older binary against v2 storage.
A v2 rollback uses its matching v2-capable binary and matching backup; reverting
only the executable to a v1-only build is unsupported.

Legacy replay contracts reject v2 enrollment. `portfolio-native-replay-v2` explicitly
replays normalized packets through native reservation, simulated fills and
protection into a new directory, then freezes it. Original packet clocks and
request bytes are retained. It accepts no model/operator credentials. The new
`portfolio-dashboard-review.py` creates a separate two-held-play review with real
simulated fill receipts; it never changes the historical V1/V2 fixtures.
