# Arm D replay, export and stored attribution

P3 extension, 2026-10-12 UTC. A new comparison may explicitly enroll **A/B/C/D**.
D uses the full entry contract plus bounded MAINTAIN, TIGHTEN and EXIT_ALL management.
Legacy A/B/C requests remain supported. Existing populations cannot acquire a new
management policy on reopen. This is scripted local PAPER evidence, not authentic
model performance, prospective enrollment, broker execution or profitability.

## Independent accounts and matched entry

`ReplaySettings.managed` is an optional `ReplayScript(arm="D", decisions=...)`.
It must be paired with `position_policy` and a fourth distinct population in the
manifest. Entry script keys are `degen:<five-minute-slot>`; management script keys
are `position:<five-minute-slot>`. The coordinator still owns one ordinary durable
`degen:` cycle and one admitted call for whichever role its actual position requires.
The script never receives an engine, venue, tape, key or trading authority.

D's declared entry decisions must exactly match C's by slot, including delay,
usage and entry geometry. C/D model cost policies and exported entry-model/script
hashes must match. The common setup, selection, capital, limits and fill assumptions
remain bound. Each arm owns its own clock, cash, settled funds, reservations,
position, order history, model attempts and liquidity accounting. Management may
change which later entry opportunities are reached; unused scripts remain unused.
No arm borrows another arm's position, fill or funds.

The existing virtual scheduler now releases management responses too. Market
receipts precede same-time responses. Independent supervision runs while a response
is pending, and again before applying it. A mandatory exit, changed ownership or
expired original lease can reject discretionary advice without discarding its
known charge. Missing scripts and UNKNOWN responses leave unknown usage and block
new model risk. Approval is not execution: a close needs a subsequent eligible
quote and actual native fixture fill receipt. An unfilled close retains exposure.

Both single-session and series APIs/CLIs support four arms. Series retain the same
owners, saved closing snapshots, explicit funds settlement, prior cost uncertainty
and hash-linked history. No account resets or implicit settlement were added.
Requests retain their existing size bounds; comparison bundles retain the 16 MiB
cap, now allowing at most 240 arm/session rows for four arms over sixty sessions.
Per-arm/session call, cycle, order, fill, journal and wall-time bounds are unchanged.

## Stored decision and execution attribution

`app.options.attribution` reads the same bounded read-only SQLite snapshot as the
exporter or observer. It does not construct an owner, attach recovery authority,
read a venue, contact a provider or write records. It projects existing durable
records; no migration or new database schema is needed.

Each exported cycle and observer opportunity can show:

- Deterministic, selector, entry or management role; original source, packet and
  proposal hashes; action, thesis, requested geometry, change and uncertainty.
- Exact held entry and captured revision for management; stored review/reasons,
  application status and applied tighter invalidation where recorded.
- Whether a model attempt was admitted, its configured cost estimate or explicit
  unknown/not-called status. A preflight/budget rejection is not a paid attempt.
- A separately prepared order, approved quantity, attempted status and actual
  fill IDs/whole quantity. MAINTAIN/TIGHTEN have no invented order or fill.

Exported orders retain their stored origin and held-entry reference for managed
or native protective exits. The observer displays this distinction in its history
and order table. The stored JSON includes the detailed projection. Paid entry and
management receipts, decision consumption, review/plan binding, tightening events,
full managed-exit approval receipts and fill-table coverage must agree. Missing or
contradictory lineage fails export instead of silently assigning it to another arm.
Interrupted calls keep their original uncertainty and never become free decisions.
The evaluator checks projection/call/order/fill agreement as well as cash accounting.

Attribution follows stored evidence, not a claim that database-owner tampering is
impossible. Export hashes bind content; they are not independent provider witnesses.
The observer remains a bounded history page; export audits the complete bounded
session history. Browser visual acceptance and the finished dashboard remain open.

## Costs and comparison

Every admitted entry/selector and management call is counted once from the native
model-call ledger. `model_cost_by_role` separates ENTRY from MANAGEMENT with known
cost and unknown-call counts; `known_model_cost` is their sum. All known HOLD,
MAINTAIN, late and rejected-result charges remain included. A known completion
after session close retains its charge in its starting session, while
`MODEL_COMPLETION_AFTER_SESSION` prevents complete comparison totals. Missing or
foreign usage remains unknown. No charge is subtracted twice through attribution.

Venue fees, spread, adverse slippage and explicit data/host allocations retain the
existing accounting rules. The report adds D versus A and a descriptive
`management_net_difference_D_minus_C`. It reflects complete independent portfolios,
including management-induced differences in later opportunity use. It is not a
causal proof of management skill. Incomplete arms or sessions withhold totals;
`economic_conclusion` remains INCONCLUSIVE even with complete fixture arithmetic.

## Evidence and continuation

[Current measured proof](SLICE2_STATUS.md) records the installed-wheel tests and
remaining limitations. [Source of truth](SOURCE_OF_TRUTH.md) owns continuation.
Actual normalized market/model evidence and latency, eligible underlying baseline,
prospective comparison/statistical evidence, continuous options PAPER runtime/UI,
actual host lifecycle/alerts/off-host recovery, Swing/Scope/mixed ownership and the
finished dashboard remain open. LIVE stays disabled; no broker writes, model/API
calls, service changes or frozen deployed-experiment changes are part of this slice.
