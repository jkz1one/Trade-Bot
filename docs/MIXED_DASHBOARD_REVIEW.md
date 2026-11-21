# Paused offline dashboard review

This is a historical UI fixture, not a prospective PAPER experiment or evidence of
current market performance. The explicit seed in
[mixed-dashboard-review.json](../examples/mixed-dashboard-review.json) uses $1,000
of virtual capital and artificial SPY prices. Its loss limits are fixture inputs,
not operating recommendations. No paid model, real market data or credentials are
used. Existing native engine terms and strategy decisions are unchanged.

[mixed-dashboard-review.py](../scripts/mixed-dashboard-review.py) requires a
noneditable installed package and a new absolute output directory. It uses native
approval, dispatch, later simulated fills, reconciliation and protection: buy,
close, then buy and tighten the active stop. It retains three native simulated fill
receipts, cash $803.64 and full-cost fixture-time equity $1,001.87. The open position
has original stop $90, active stop $95 and original target $120. The chart retains
only verified flat boundaries and gaps at open positions. Neither proposals nor
targets are relabeled as fills. Daily host/data/operating allocations and execution
fees remain included. Scripted results are not AI recommendations.

The owner closes after generating the journal. There is no ongoing worker. A
manifest binds the seed and journal hashes. Partial or completed directories are
never overwritten. The script and seed are mounted separately from the installed
wheel; their hashes are retained in [verification proof](MIXED_DASHBOARD_REVIEW_PROOF.json).

The observer's explicit `review_at` option accepts only mixed `ui-review-`
populations, a timezone-aware historical timestamp and its default clock. It
adds `FROZEN_OFFLINE_UI_FIXTURE` metadata and a prominent **Paused historical UI
fixture** banner. The fixed observation time is `2026-10-09T15:00:06+00:00`.
Stored source clocks, deadlines, approvals and account revisions are untouched.
Freshness is evaluated at that historical instant, never represented as freshness
today. Reading the same journal with the ordinary clock yields stale evidence and
withholds equity. HTTP reads cannot create the fixture, trade or call providers.

## Operator deployment already observed

On October 24 the operator created `/opt/trade-bot-dashboard` detached at
`cc990cf5dd1b29f14449b3e4b59b98a13b5ead4c`, built `trade-bot-dashboard:cc990cf`
and started a separate read-only observer on `127.0.0.1:8790`. Its private data
directory was empty. The existing SHADOW worker and old observer remained on
`de5dd1c7bd3a2d3b85a2d6bb7f624e0d3a3f9245`, with the old reader on port 8787.
The initial curl reset cleared after startup; later local health returned OK with
`trader_health=NOT_CHECKED`, and unauthenticated access returned 401.

Caddy was validated and reloaded to send `signalflow.duckdns.org` to port 8790;
the health-path 404 rule remained. Backup:
`/etc/caddy/Caddyfile.before-dashboard-20261024T062743`. Public HTTPS returned 401.
The operator then supplied a 2048×1152 authenticated desktop screenshot showing
`DATABASE_NOT_CREATED` for `mixed-paper-pending`. This proves the deployed empty
state was viewed; it does not establish populated, mobile, keyboard, contrast or
interaction acceptance. No password was supplied to this workspace.

## Preparation failure: inspect before any further activation

The operator's 77e69c6 preparation failed on its first native dispatch. Retained
journal and venue evidence show an accepted OPEN simulated order, zero fills,
UNKNOWN parent status and `FixtureProcessTimeout`. The old reader still runs;
activation never executed. **Do not rerun the commands below on the partial
`ui-review-v1` directory.** Preserve it unchanged. See the
[incident and snapshot-only diagnostic](MIXED_HYBRID_DASHBOARD.md#retained-host-failure).
The operator subsequently measured full imports at 4.831 seconds and a read-only
snapshot child at 4.540 seconds, including an unnecessary Agents SDK import.
The correction defers the unchanged owner lease import until owner entry; native
children no longer initialize that model runtime. No engine deadline or approval
safeguard has been weakened. [Correction proof](MIXED_CHILD_IMPORT_PROOF.json).

## Activated v2 and layout refresh

The operator completed v2 preparation and activation at `c2ad7ca` on October 24.
The host verified all 254 installed application files and three simulated fills.
Cash was $803.64 and historical equity $1,001.87. Journal SHA-256:
`141c3a6ef3d8aeaa47c7919f0bb053810ce6930f3102e639cb22c33b3451b705`.
Health/authentication checks passed after startup connection resets, and the
original SHADOW service identity/start-time checks passed. The old cc990cf reader
remains retained as `trade-bot-dashboard-before-review`. The two operator desktop
screenshots show the populated account and activity; they precede the layout fix.

The operator subsequently refreshed successfully to e6fd353, verifying all 254
installed application files, three fills and private authenticated frozen content.
The next refresh addresses the chart and trade labels shown in the new screenshot.
After fetching and checking out the new revision, update only the reader:

```bash
bash scripts/dashboard-review-host.sh refresh ui-review-v2
```

This builds the new image and reuses the existing frozen v2 journal read-only.
It does not prepare or replay a fixture. It requires the running e6fd353 reader,
preflights the same seed/journal/native evidence, retains that reader separately
as `trade-bot-dashboard-before-chart` and uses the existing activation/rollback
and authentication checks. V1 and both prior rollback containers remain untouched.
Do not run preparation again. Review the refreshed desktop/mobile layout and
activity expansion before accepting this visual revision.

## Successful chart-label refresh

The operator completed the a3216b6 refresh: 255 installed matches, three historical
fills, authenticated frozen content and successful health checks after startup
retries. e6fd353 remains as `trade-bot-dashboard-before-chart`. This establishes
Docker host acceptance for a3216b6; browser/screenshots remain pending. Do not rerun
refresh or preparation. The subsequent Robinhood mapping work changes no UI.

## Prepare and activate the populated fixture

After fetching and checking out the published release in the separate dashboard
worktree, run as root:

```bash
bash scripts/dashboard-review-host.sh prepare ui-review-v2 &&
bash scripts/dashboard-review-host.sh activate ui-review-v2
```

[The host helper](../scripts/dashboard-review-host.sh) requires a clean checkout
and the existing mode-0700 UID/GID-10001 data directory. Prepare builds an image
tagged with the full commit SHA, then runs the native fixture once with no network,
no secrets and a new `/var/lib/trade-bot-dashboard/ui-review-v2` directory.
For this recovery, the explicit second argument is required: the default v1 target
continues to reject the retained partial directory. The helper requires v1 to
exist for v2 recovery and mounts v1 read-only inside the preparation container.
V2 is a separate historical fixture with the same fixed scenario, not a resumed
owner or new live account. Existing v2 output is also refused; inspect any failure
without retrying or deleting it. The
default SHADOW image command is always overridden. Activation preflights installed
application bytes, seed/journal identity, native accounting and private password
permissions without network or writable data.

Activation requires the current dashboard image to be exactly
`trade-bot-dashboard:cc990cf` and no existing rollback container. It retains the old
reader as `trade-bot-dashboard-before-review`, stops that reader, and starts only
the new read-only observer on the same loopback port. It checks health, unauthenticated
401, authenticated API and HTML, and unchanged original SHADOW container IDs,
image IDs and start times. Password bytes stay inside the container. Any activation
failure after renaming invokes rollback to the previous reader. Caddy is unchanged.
If preparation fails, inspect the retained partial directory; do not reuse it or
automatically delete evidence. If activation fails, preserve its output for diagnosis.

After success use the same HTTPS URL and login. Review desktop and mobile layouts,
the balance graph, open trade/protection, local tabs and keyboard behavior; retain
screenshots before claiming visual acceptance. A deliberate rollback after success
stops/removes only `trade-bot-dashboard`, renames `trade-bot-dashboard-before-review`
back, and starts it. Keep the fixture data for audit. The host helper's shell syntax
is checked; its actual Docker activation and rollback remain operator acceptance
steps until the operator supplies their results.

## Verification and remaining acceptance

156 distinct installed Python cases passed, including six new guard/end-to-end
cases, plus seven JavaScript unit cases. Native tests ran serially with copied
tests outside the checkout, Python `-I`, warnings as errors, disabled plugin
autoload and explicit anyio. All 247 application/template files match source,
wheel and installed bytes; only the web factory and mixed template differ from
`cc990cf`. Source/wheel identities and exact test IDs are in the new proof; prior
proof manifests are unchanged. No dependencies changed.

Populated host activation, actual browser screenshots, separately bound mixed
benchmark presentation, and authentic provider/normalization/model/host/economic/
PAPER acceptance remain open. This review starts no PAPER runtime, collector or
model worker and does not authorize those later acceptance calls. LIVE remains disabled.
