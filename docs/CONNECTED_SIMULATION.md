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

These are interface placeholders, not a host deployment command. The complete
reviewed configuration and guarded launch procedure remain to be prepared.
The feed CLI keeps its explicit --create/--run semantics; default validation
does not read providers, and wiring failure returns code 2 before opening state.

Candidate checks report missing reviewed metadata/tradability, unsupported mapping,
owner-universe conflicts and last-trading times already passed. The collector no
longer requests expired unheld candidates. Held instruments remain requested,
including contracts past their last-trading cutoff, to preserve available evidence.
This does not synthesize replacement contracts or approve expiration handling.

## Remaining implementation and evidence

Current transport supplies SPY/QQQ quotes and intraday five-minute equity history.
It does not supply Swing daily/hourly/catalyst inputs or Scope SPX/context inputs.
Connection checks expose those omissions for enrolled strategies; do not silently
disable a family or describe those feed paths as completed.

Complete reviewed contract and data-eligibility binding, appropriate dynamic
candidate updates, missing strategy inputs, an operational launch/restart path,
and the dashboard switch to the running journal. Preserve old review fixtures.
Existing risk/protection/recovery rules remain authoritative. No fresh sample can
by itself fill missing entitlement, stock size or contract terms.

Installed validation is in CONNECTED_SIMULATION_PROOF.json. No broker/provider,
model, credential or host access occurred from the workspace. LIVE stays off.
