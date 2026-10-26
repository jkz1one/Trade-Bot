# Connected simulation work

The intended operation is virtual-money trading in this bot, on the existing
dashboard, with one shared owner and at most two simultaneous plays. No external
brokerage account is required. The operator cannot access the server during
October 26 market hours; continue coding and testing offline for the next available
host session. No unattended activation or promise of next-session readiness.

## Implemented connection checks

The collector now loads the existing owner's runtime.json before opening any
collector database, journal reader or credentials. It rejects mismatched population,
stock identities, provider/source names, strategy universe, delivery filename,
nonportfolio owner, missing quote-driven fills and incompatible polling cadence.
It emits separate wiring errors and entry blockers. Correct wiring is not trading
permission: the mapper still produces UNKNOWN entitlement and missing stock sizes.

The same checks can be run without creating any state or starting any process:

```bash
python -I -m app.mixed.connected_check \
  --runtime-file ABSOLUTE_RUNTIME_JSON --policy ABSOLUTE_FEED_POLICY_JSON \
  --schemas ABSOLUTE_EXPORTED_SCHEMAS_JSON --journal ABSOLUTE_OPTIONS_DB \
  --directory ABSOLUTE_FEED_DIRECTORY
```

These are interface placeholders, not a host deployment command. A separately
implemented [coordinated runtime](CONNECTED_RUNTIME.md) now reopens an enrolled
owner and collector with first-tick recovery, shared shutdown and retained leases.
Complete reviewed host configuration and deployment remain to be prepared.
[Guarded first-collector enrollment](CONNECTED_ENROLLMENT.md) now provides a
read-only review and exact-hash create against an unused native runtime. The feed
CLI requires the same review for --create and rejects --create with --run. Existing
collector reopening still does not read providers unless --run is explicit;
wiring failure returns code 2 before opening state.

Candidate checks report missing reviewed metadata/tradability, unsupported mapping,
owner-universe conflicts and last-trading times already passed. The collector no
longer requests expired unheld candidates. Held instruments remain requested,
including contracts past their last-trading cutoff, to preserve available evidence.
This does not synthesize replacement contracts or approve expiration handling.

## Original carry intent

[Explicit carry schedules](CONNECTED_CARRY_INTENT.md) now bind bounded per-session
stock/option exit dates through source preparation, restart and runtime delivery.
They cannot enable unenrolled carry or extend existing originals. Schedule
rollover/enrollment on the host remains unfinished.

## Remaining implementation and evidence

Current transport supplies SPY/QQQ quotes and intraday five-minute equity history.
An optional [pre-open history transport](SWING_HISTORY_FEED.md) now captures and
retains native daily/hourly histories with original clocks and UNKNOWN entitlement.
Binding those histories into original Swing sources/seeds now has a
[native preparation path](SWING_SOURCE_BINDING.md). [Runtime assembly and expiry
routing](SWING_RUNTIME_DELIVERY.md) now join originals with explicit current
evidence, while missing inputs retain protection quotes and block entry cycles.
The catalyst provider/provenance path and Scope SPX/context inputs remain absent. Connection checks
expose these omissions; do not silently disable a family or call its feed complete.
[Continuous delivery fixes](CONTINUOUS_STRATEGY_DELIVERY.md) now preserve quote-only
polls after source preparation, retain books after optional intraday failure, and
explicitly block cycles with missing enrolled Scope input. The catalyst adapter
requires a reviewed source/schema beyond the current six tools.

Complete reviewed contract and data-eligibility binding, appropriate dynamic
candidate updates, missing strategy inputs, operational enrollment/deployment,
and the dashboard switch to the running journal. The bounded coordinated runner
now supplies the existing-owner launch/restart path. Preserve old review fixtures.
Existing risk/protection/recovery rules remain authoritative. No fresh sample can
by itself fill missing entitlement, stock size or contract terms.

Installed validation is in CONNECTED_SIMULATION_PROOF.json. No broker/provider,
model, credential or host access occurred from the workspace. LIVE stays off.
