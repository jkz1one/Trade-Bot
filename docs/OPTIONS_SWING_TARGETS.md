# Original Swing target derivation

New PAPER cohorts may enroll `SwingPolicy.target_derivation="original-risk-ladder-v1"`
together with `unfilled_lifecycle="observed-lifecycle-v3"`. This prepares the existing
next-session daily-breakout seed with original 1R/2R/3R objectives. It connects seed
preparation, native admission, runtime retirement, carry and independent replay/export.
A separate [daily-base enrollment](OPTIONS_SWING_BASE.md) now derives geometry
from complete daily/hourly base evidence. The existing small daily-breakout
adaptation stays frozen. MA-pullback and higher-timeframe break/retest families remain open.

## Frozen geometry and source

The source rule is SignalFlow commit `f9eaf2c1b5d13dca287ee7138126883065b00395`,
`backend/platform/setup_engine.py`, blob `af7912bc06dbf0bee94c148cfe7fb1540842d85b`,
`_targets`: signed objectives at one, two and three times original trigger-to-stop risk.
Trade-Bot applies that rule to its existing native reference and stop. A CALL uses
the last completed daily high and buffered low; a PUT uses the low and buffered high.
The stop keeps native conservative 12-decimal rounding. Target arithmetic uses the
isolated exact Decimal context; the source's float/4-decimal implementation is not
imported. Nonpositive risk or any nonpositive objective rejects the seed, without
shrinking the ladder or substituting targets.

`SwingTargetGeometry` retains the reference, invalidation, risk, all three objectives,
complete frozen policy hash and original seed-input hash. The latter binds source
bars/clocks, creation time, target session, exact instrument and optional carry exit
session. `first_target` must equal derived T1. Targets never move with a later quote,
paid decision, revised history, restart or session rollover.

## Preparing a seed

Construct `SwingSeedBuildRequest` with the enrolled policy, allowed symbols, original
creation and target-session clocks, completed `SwingHistory`, exact `OptionInstrument`
and optional carry-exit session. `build_swing_seed(request)` derives the objectives
and applies existing source, actual-XNYS-session, contract, completed-bar and seed
validation. There is no caller-supplied target field in this request. Feed its returned
`SwingSeed` into the existing `SwingInput` and runtime/tape path; later metadata,
catalyst, current price, account risk and native approval remain independently required.

An installed, offline CLI accepts the same request JSON and creates a new portable
seed envelope:

```sh
/absolute/env/bin/python -I -W error -m app.options.swing_targets \
  --request /absolute/request.json --output /absolute/new-seed.json
```

Inputs are bounded to 2 MiB. Output is create-only. `build_seed_bundle` retains the
request, derived seed, `authority=false` and content hash. `verify_seed_bundle(bundle,
expected_hash)` independently rebuilds the seed and checks the exact envelope against
the retained hash. This is public market/setup evidence, not execution authority.

## Native ownership and compatibility

Seed locking, scanning, selected-entry review and common-tape validation reject a
missing, altered or unenrolled geometry proof. Native entry review also binds the
scan's reference/stop to the original geometry. The existing observed lifecycle
permanently retires an unfilled seed once original T1 or invalidation is observed;
recovery and restart do not revive it. Paid decisions retain their actual charge
even when fresh observations block admission. Unknown usage remains unknown.

T2/T3 are retained original objectives, not a new automatic scale-out policy or a
replacement for a fully validated AI entry plan. Native premium/time/underlying
protection, actual fills, current post-cost risk checks and original deadlines stay
in force. Carry retains original T1 and seed hash. Separate A/B/C/D owners retain
their own cash, reservations, fills, fees, model charges, operating costs and loss
controls; portable native exports reconstruct the same original geometry. Native
reconstruction compares the full stored seed JSON and selected scan, checks their
hash and rederives the objectives from frozen inputs; an unchanged stored hash does
not conceal altered target fields.

Old policies and seeds omit the new optional fields byte-for-byte. Their explicit
first targets and frozen behavior stay unchanged. Existing owners cannot silently
add or remove enrollment. No provider/model/broker call or deployment is part of
this builder. LIVE remains disabled; authentic data/model and PAPER acceptance
remain open after the remaining family and mixed stock/options plumbing.

Installed proof and exact case counts are recorded in [Slice 2 status](SLICE2_STATUS.md).
Focused tests: `test_option_swing_target_derivation.py` and
`test_option_swing_target_replay.py`; regressions include original Swing lifecycle,
native execution and common market tapes.
