# Continuous local options PAPER runtime

First P4 runner slice, 2026-10-12. The installed `app.options.runtime_cli` owns one
new Degen options fixture population continuously. It uses the existing native
venue workers, execution journal, exclusive owner lease and restore fence. A
five-minute decision task runs separately from faster reconciliation/protection
ticks. Optional selection, full-entry and position models retain the existing
bounded workers, deterministic reviews and durable known/unknown usage costs.

This is a local normalized-fixture input path. Authenticated provider normalization,
continuous collection and authentic model latency remain P1 acceptance work. The
runner performs no broker writes and supplies no automatic market fills or
settlement credits. Existing stock services and the deployed experiment are separate.

## Explicit enrollment and installed interface

Start with [the deterministic fixture settings example](../examples/options-local-runtime.json).
It declares synthetic account/population/source identities, capital and limits; it
contains no model or provider credentials. Choose a separate absolute feed path
and new population identity before enrollment. Save the settings as an owned
regular `0600` file. All settings, native venue identity, strategy versions, feed
path and runtime cadence become immutable for this population.

```sh
python -I -m app.options.runtime_cli init \
  --settings /absolute/private/options-runtime-settings.json \
  --directory /absolute/private/new-options-population

python -I -m app.options.runtime_cli run \
  --directory /absolute/private/new-options-population
```

`init` requires a nonexistent directory and never overwrites/adopts an old
population. It creates private settings, venue and execution journals with their
restore authority. A failed initialization is not silently reset; use a separately
reviewed new directory. `run --seconds 60` is a bounded fixture invocation; omit
the duration for continuous operation. SIGINT/SIGTERM request clean shutdown.
Successful enrollment/shutdown exits 0; unavailable/invalid evidence exits 2 with
a bounded JSON error. This installs no host unit, proxy or deployment.

Runtime settings contain `limits`, `execution`, `setup`, `selection` and `runtime`.
Optional `key_file`, `judgment_limits` and execution model cost policy must be
paired. Full entry requires that model configuration; management also requires
full entry. Model key paths are absolute and separate from the feed. Credential
environment isolation stays in the existing fixed workers. The example is model
off. This slice's tests use explicit local model fixtures, never authentic calls.

Protection tick cadence is 0.2–5 seconds; heartbeat age is 2–30 seconds and packet
age 1–30 seconds. The native process timeout plus tick interval must fit all
heartbeat, account and supervision freshness ceilings. These are configured
bounds, not measured host guarantees or an independent OS watchdog.

## Normalized input and authority

The fixture producer atomically replaces the explicit owned regular `0600` feed
file, bounded to 256 KiB, with a strict packet:

```json
{
  "version": "option-normalized-fixture-v1",
  "population_id": "options-runtime-fixture-v1",
  "sequence": 1,
  "recorded_at": "2026-10-12T19:00:00Z",
  "frame": {"histories": [], "inventories": [], "quotes": [], "underlyings": []}
}
```

The timestamp above is illustrative; a producer must supply its actual capture
time. Empty frames cannot create opportunities. Frames use the existing exact
`DegenFrame` contracts; no missing source, entitlement, contract, timestamp or
liquidity metadata is inferred. Held-contract quotes and underlying evidence must
be included for protection. The existing coordinator's quote planner determines
the exact held/pending contract or eligible candidate shortlist.

Sequences and capture times cannot move backwards. An unchanged sequence can be
reread only with the same packet hash and within its original age bound. The last
accepted sequence/time persists across restart. File absence, wrong ownership,
symlink/FIFO, oversize, bad identity, stale/future data or sequence conflict halts
entry **before** awaiting the next snapshot, fencing pending model results.
Protection still runs with unavailable market evidence and retains blocked exits;
it never invents an executable quote, flat position or fill.

## Scheduling, shutdown and stored UI

Only actual XNYS regular sessions get decision slots. Each observed five-minute
slot is claimed once. Earlier unobserved slots in that session are recorded as
SKIPPED. A still-running decision causes the next slot to be skipped instead of
queuing obsolete work. Closed sessions still receive protection ticks. This
latest-packet interface is not a complete recorder; skipped provider updates and
unobserved whole sessions remain a prospective coverage gap.

Runtime tables retain frozen owner binding, generation, heartbeat, feed sequence,
latest accepted frame, observed session and COMPLETE/SKIPPED/INTERRUPTED slots.
New entry additionally requires a fresh RUNNING runtime heartbeat. A requested
stop immediately blocks entry while a bounded protection read finishes. Shutdown first
halts entry, then cancels/drains the decision and its existing worker cleanup
before releasing ownership. Pending slots become INTERRUPTED; unreturned model
usage remains unknown. Crash recovery retains interruption evidence and halts.
Restart or a later good packet never resumes the entry halt. Existing explicit
revision-bound engine recovery is still required with fresh reconciled evidence.
For a new explicitly enrolled operator population, the [signed local recovery CLI](OPTIONS_OPERATOR_RECOVERY.md)
now submits halt/resume/revocation to the existing owner. It never silently refreshes
reviewed revisions or repairs unknown evidence. Other populations have no new resume route.

The [stored observer](OPTIONS_OBSERVER.md) reads runtime status/freshness/session
and the latest accepted frame from the same committed snapshot. It does no feed
read or worker operation. Fresh heartbeats are stored evidence, not proof of worker
liveness. Stale/future/missing records remain labeled; actual installed release is
still unknown. Old populations retain NOT_RECORDED fields without creating tables.

Remaining P4 acceptance: authenticated continuous exact data/model use, actual
isolated-host lifecycle/alerts/off-host recovery, installed release identity,
key rotation/reprovisioning, desktop/mobile visual acceptance and the full dashboard.
The separate local operator recovery surface is fixture implemented.
This local runner does not close those gates or prospective economic acceptance.
LIVE stays disabled and the deployed experiment remains frozen.

## Shared family enrollment

A new population may opt into [shared Degen/Swing selection](OPTIONS_SHARED_STRATEGIES.md)
with `RuntimeSettings.swing_policy` and one `SwingInput` per frozen symbol in
`DegenFrame.swing`. It uses the same runtime, lease, ledger, protection cadence and
optional signed operator inbox. This first Swing adaptation always retains
session-close protection; it adds no overnight authority or second account.
