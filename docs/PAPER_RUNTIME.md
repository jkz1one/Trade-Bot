# Isolated fixture PAPER service

`app.execution.runtime.PaperRuntime` connects durable local fixture quotes/account
truth, independent supervision, scheduled judgment, deterministic admission and
bounded fake dispatch. It is separate from the deployed Robinhood READ/SHADOW
worker and `virtual-v1`. It has no real broker placement/cancellation adapter.
Default agent is an explicit, auditable stub HOLD. PAPER and LIVE-disabled settings
are supplied explicitly; trading-mode environment variables cannot promote it.

## Ownership and scheduling

A private lifetime POSIX file lock owns one journal on one host. The CLI acquires
it before opening any writable engine, including interrupted-attempt startup
recovery. Duplicate starts fail without changing the journal or its authority pair.
This is not a multi-host ownership witness or protection against the host owner.

Enrollment freezes the engine, supervisor, venue/feed IDs and paths, runtime limits,
15-minute XNYS current-slot policy, agent and optional bounded judgment/key path.
It requires a verified paired execution authority and must precede any order/model
attempt. Run/restart never enrolls a new policy or resets an experiment. Initial
creation is exclusive; failed provisioning can leave an incomplete directory for
inspection and must not silently reuse it.

Three supervised tasks share the exact engine: independent position supervision,
runtime heartbeat and scheduled decisions. A cycle requires fresh successful
supervision of its exact quote sequence/hash, reconciled account truth and entry
health. Before any model invocation it atomically claims the current regular-session
slot and saves its governed account packet and quote lineage. It never backfills
missed slots. Every completed HOLD, approved fake order and admission rejection
keeps its decision/result; model receipts, usage, risk and dispatch remain in their
existing audit tables/events. A delayed decision crossing its slot cannot prepare
or dispatch an order, though its known usage is still charged.

CLAIMED/interrupted cycles are never automatically retried. Shutdown/cancellation
interrupts unfinished cycles, preserves unknown model receipts/order reservations
and halts. A restart after an unclean RUNNING/STOPPING owner halts and marks orphaned
claims INTERRUPTED; unresolved claims block later slots even after a manual engine
resume. Signed RESOLVE_CYCLE can record reviewed abandonment as described below;
it never enables replay or automatically resumes.

Runtime STOPPING/stopped/stale/failed health blocks BUY admission/dispatch and new
model receipts. HOLD stays auditable. Existing protective SELL checks remain in
charge. A heartbeat continues while bounded judgment waits, and protective
supervision runs independently. Failure of any component ends the service and
persists a halt. Shutdown revokes entry health, drains/cancels decision children,
then finishes bounded supervision; repeated cancellation cannot release the lifetime
lease before cleanup. A draining supervisor tick cannot renew stopped entry health.
Stopping with a position or unresolved order retains the existing risk halt.

A fenced supervisor read defers while a bounded order submission is SUBMITTING:
it cannot interpret pre-acceptance absence as definitive missing-order evidence.
It does not renew account evidence or supervisor heartbeat. After the attempt
settles or becomes UNKNOWN, normal complete-history reconciliation applies again.
Existing superseded-read, missing-order, partial-fill and uncertainty guards remain.

## Signed interruption resolution

`RESOLVE_CYCLE` is an additional existing-control-transport command with an exact
`cycle_slot` target. It requires prior operator enrollment, the current credential
generation, HMAC-bound journal/actor/reason/target, an exact fresh reviewed revision
and a maximum-five-minute command lifetime. Existing six-action envelopes/signatures
and saved replay receipts remain compatible: absent/null cycle_slot is omitted from
the canonical body for those actions. No new HTTP endpoint or model tool exists.

Resolution requires all of the following in one fenced SQLite transaction:

- VERIFIED retained execution authority and a halted, STOPPED/FAILED runtime; its
  lifetime lease must be free through commit, including any failed-owner cleanup.
- An exact completed INTERRUPTED claim, with no remaining CLAIMED cycles, no prior
  resolution and no future-dated start/completion. An orphan CLAIMED row first needs
  normal startup review, which marks it interrupted and preserves its halt.
- Fresh complete current-account reconciliation, no issues or active reservations,
  and fresh owned-position supervision when a position remains.
- No unknown model costs or judgment evidence violations. A linked model receipt
  must match frozen policy, original packet, provider usage/identity, decision/audit,
  token ceilings and exact pinned-rate cost. No model call is allowed for a stub
  claim. A claim interrupted before invocation can have no receipt/decision.
- Any linked order is already definitively terminal. An attempted order needs its
  matching terminal observation in fresh complete account history. Unattempted
  PREPARED intents must first be explicitly abandoned; resolution cannot release
  them. Known fills/owned positions remain intact.

Success adds a separate immutable resolution record with original-cycle hash,
command identity and reviewed snapshot/ledger/model/order evidence. The original
cycle remains INTERRUPTED; packet, decision, model receipt/cost, orders/fills, alert
acknowledgments and halt are preserved. Scheduling ignores only a hash-matched
resolved interruption. Same-slot attempts remain forbidden; modified resolution
lineage remains blocking. Another unresolved claim continues blocking later slots.

The existing control API's GET review exposes bounded runtime health, counts and
latest 20 cycle/resolution summaries without packets/prompts. Submit the usual
signed POST command using action RESOLVE_CYCLE and the reviewed exact cycle_slot;
there is no unauthenticated CLI bypass. A lost response repeats the same signed
command for its original receipt; changed evidence requires a newly reviewed command.
Resolution, event, receipt and authority advance commit together or all roll back.

Resolution does not resume, acknowledge alerts, clear stop requirements, cancel
orders, change account/model evidence or limits, or claim a potentially billed call
was free. RESUME is a separate reviewed command with its existing risk guards; fresh
runtime/supervisor health still gates new entries/judgments. Missing usage remains a
blocker requiring future verified provider evidence, not an operator assertion.

## Local use

Use a new disposable directory outside the deployed state. Initialization makes
no network calls and does not publish fabricated market prices:

```bash
python -m app.execution.runtime_cli init \
  --directory /private/fixture-paper --capital 10 --symbols SPY
python -m app.execution.runtime_cli publish \
  --directory /private/fixture-paper --sample-id sample-001 \
  --packet-file /private/current-fixture-packet.json
python -m app.execution.runtime_cli run --directory /private/fixture-paper
python -m app.execution.runtime_cli report --directory /private/fixture-paper
```

`publish` accepts an existing bounded MarketPacket JSON as trusted local fixture
input, with stable sample IDs and the feed's existing universe/time constraints.
A regular-session run needs fresh packets throughout operation; missing/stale
samples fail closed. The CLI is a foreground process suitable for a future service
wrapper; it handles SIGINT/SIGTERM and returns nonzero on component failure.
Flat closed sessions wait without quote reads or model/venue child calls. Reporting
is read-only and makes no model/broker calls; it shows runtime/supervisor health,
latest 20 cycle summaries, counts and existing journal/economic evidence.

The durable venue accepts fake orders but does not automatically invent fills.
Explicit scripted fixture fills test execution/reconciliation; they are not a
synthetic next-quote performance policy or broker fills. SPY/performance experiment
machinery remains the separate frozen `virtual-v1` implementation.

For explicit OpenAI opt-in on a *new* population, add `--key-file`, `--total-budget`
and `--daily-budget` to init. The key must be a private mode-600 current-owner regular
file, containing one bounded ASCII API key with at most one trailing newline; final
symlinks/FIFOs/broad permissions are rejected. Only the path is frozen, and it is
rechecked before each model call. Do not put a key in arguments or packet JSON.
The existing bounded Responses coordinator owns token/process/request ceilings,
cost reservations and fail-closed HOLD. Its fixed child receives no broker tools or
credentials. Authenticated provider/model validation is still required separately.

This runner does not provision an operator API, external alert/archive sink, daemon
wrapper, market-data collector or real broker adapter. Those contracts are separate
components and production integration gates. Do not pull/rebuild the deployed
SHADOW image for this fixture-only follow-up. It neither deploys this runner nor
changes the active experiment's population/policy. Engineering completeness does
not establish LIVE readiness, provider billing correctness or trading signal.
