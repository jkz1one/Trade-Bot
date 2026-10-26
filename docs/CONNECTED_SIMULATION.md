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
The feed CLI keeps its explicit --create/--run semantics; default validation
does not read providers, and wiring failure returns code 2 before opening state.

Candidate checks report missing reviewed metadata/tradability, unsupported mapping,
owner-universe conflicts and last-trading times already passed. The collector no
longer requests expired unheld candidates. Held instruments remain requested,
including contracts past their last-trading cutoff, to preserve available evidence.
This does not synthesize replacement contracts or approve expiration handling.

## Remaining implementation and evidence

Current transport supplies SPY/QQQ quotes and intraday five-minute equity history.
An optional [pre-open history transport](SWING_HISTORY_FEED.md) now captures and
retains native daily/hourly histories with original clocks and UNKNOWN entitlement.
Binding those histories into original Swing sources/seeds and fresh catalysts
remains unfinished. Scope SPX/context inputs remain absent. Connection checks
expose these omissions; do not silently disable a family or call its feed complete.

Complete reviewed contract and data-eligibility binding, appropriate dynamic
candidate updates, missing strategy inputs, operational enrollment/deployment,
and the dashboard switch to the running journal. The bounded coordinated runner
now supplies the existing-owner launch/restart path. Preserve old review fixtures.
Existing risk/protection/recovery rules remain authoritative. No fresh sample can
by itself fill missing entitlement, stock size or contract terms.

Installed validation is in CONNECTED_SIMULATION_PROOF.json. No broker/provider,
model, credential or host access occurred from the workspace. LIVE stays off.
