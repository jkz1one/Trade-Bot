# First connected simulation configuration

The user selected $1,000 virtual capital and a $1/day AI ceiling for simulation.
The separate $5/day preference for future real trading does not authorize LIVE,
set real capital, or change this profile. Real capital would need authoritative
available buying power in a separately reviewed live implementation.

`app.mixed.simulation_profile` supplies a complete native configuration for the
first bounded connected check. It preserves one owner, at most two plays, Degen,
Swing and Scope, and native independent protection. Option preference is explicit.
It generates no market evidence, quotes, contracts, entitlement or catalyst clearance.
SPY/QQQ stock metadata remains unreviewed. The option catalog is empty until actual
current contracts are reviewed; Scope's unavailable sources are named as unavailable.
All Swing setup families are configured. This initial profile closes at session end;
overnight carry is not enrolled. A ten-minute run cannot promise session-end exits.

## Explicit simulation assumptions

| Setting | Value |
|---|---|
| Starting virtual cash | $1,000, user selected |
| AI daily ceiling | $1, user selected; America/New_York accounting day |
| Total AI allowance | $5 for this initial enrollment, additional cumulative ceiling |
| Per-call AI reservation | $0.01 |
| Maximum concurrent plays | 2, a ceiling rather than a target |
| Per-entry debit / full premium envelope | $250 |
| Aggregate and shared index exposure | $500 |
| Daily / cumulative loss ceilings | $250 / $500 |
| Modeled option fees | $0.65/contract/side plus $1/order |
| Modeled stock fees | $1/order |
| Modeled slippage | 5 basis points |
| Modeled daily overhead | $1 host, $0 additional data, $0 other operations |
| Model | Existing project default `gpt-6-luna` |

Except the explicitly selected bankroll, daily AI budget and established two-play
design, these are visible **simulation assumptions for review**, not observed bills,
broker fee claims, optimized strategies, or recommended real-money risk settings.
Replace modeled expenses with measured costs before claiming actual profitability.
Unknown costs cannot enroll a native strategy: review now rejects them before
creating owner files instead of failing partway through enrollment.

The model rates retained in this profile are standard short-context $0.10 input
and $0.50 output per million tokens, checked against the
[official model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
on October 27, 2026. Native token, per-call, daily and cumulative guards remain in
force; unknown usage blocks further spending. This is the simulator's application
budget, not an account-wide OpenAI billing cap. Existing SHADOW/model workers have
their own accounting. No model or provider call was made during this change.

## Host sequence

Build the pinned feature release, then run the profile review:

```bash
python3 scripts/connected-session-host.py build
python3 scripts/connected-session-host.py review-profile
```

Review prints the exact native configuration hashes, budget, all assumptions and
remaining blockers. The complete generation logic is in `simulation_profile.py`.
With its printed review hash, create the private inputs:

```text
python3 scripts/connected-session-host.py prepare-profile --expected-review PROFILE_REVIEW_SHA256
```

This creates only `/etc/trade-bot-connected/profiles/initial/{runtime,policy,review}.json`.
It refuses an existing destination, runs without network or OAuth, and never
mounts the model-key directory into its profile-generation container.

The host's `discovery.json` is the complete `read_cli discover` report, with its
schemas under `result.schemas`. Both profile review and host bundle preparation
now accept that completed report as well as an exported `ReadSchemas` object.
The loader validates the full discovery envelope/result, rejects duplicate keys,
retains the private-file bounds and checks the existing exact reviewed wire hash.
It never rewrites the original discovery artifact. Prepared bundles still store
only the native schema object, so downstream enrollment/runtime formats do not change.

The observed SHADOW model key is UID/GID 10001, mode 0600. Native root-owned
simulation requires its own root-owned 0600 file. This explicit host operation
copies the existing key locally without changing the SHADOW source:

```bash
python3 scripts/connected-session-host.py prepare-model-key
```

Source: `/etc/trade-bot/openai_api_key`. Destination:
`/etc/trade-bot-connected/model_key` under root-owned 0700 parent. It accepts only
the expected private UID-10001 regular source, rejects symlinks/hardlinks and
changed reads, validates the native bounded ASCII format, and creates exclusively.
It never emits the key or its digest, overwrites a destination, changes the
source permissions, contacts a provider, or restarts SHADOW. Preserve a partial
destination on failure for inspection. Run only on the host; do not share key files.

Continue with the existing bundle review:

```bash
python3 scripts/connected-session-host.py review-config \
  --settings /etc/trade-bot-connected/profiles/initial/runtime.json \
  --policy /etc/trade-bot-connected/profiles/initial/policy.json
```

Use that separate hash for `prepare`, followed by `review-enroll` / `enroll`, then
`review-run --run-id first-check --seconds 600` / `run`. The exact command sequence,
retained state rules and separate dashboard switch are in
[the host runbook](CONNECTED_HOST_RUNBOOK.md). Profile review, bundle review,
enrollment and launch each have their own hash; they are not interchangeable.

## What remains

This profile enables host/runtime/feed/dashboard acceptance with entries blocked
by real missing inputs. It does not claim trading readiness. Current reviewed
option contracts, entitlement, stock size/catalog evidence, catalyst sources and
Scope/SPX coverage remain necessary for eligible trades. Full native enrollment,
two offline feed-consumption sessions, authenticated dashboard snapshots and
same-owner restart are tested with synthetic inputs and a synthetic model key.
Actual UID-10001 copying, Docker permissions, model latency, live feed acceptance
and dashboard activation still need host evidence.

Host evidence so far: `a05da9f` image built successfully as
`sha256:fa2780a53cd496072a44dc07d69704a1342d378fe51e8c5a1d5f9160a193f88e`.
SHADOW and its observer remain running, dashboard remains frozen on ui-review-v3,
and connected state/publisher directories were absent. No server action was
performed by this coding turn.

The user subsequently built `19616d7` as
`sha256:17f0fe5dd73e0f136b730d911c1dfa552cac6fd21789f5c9988234810917ed4a`.
Profile review failed before state creation because it parsed the discovery
envelope as bare schemas. A direct offline diagnostic confirmed that exact
validation error; the compatibility loader above fixes both affected consumers.
See `SCHEMA_ARTIFACT_PROOF.json` for the installed regression check. No new
collection, authentication or changes to existing services are needed for this fix.
