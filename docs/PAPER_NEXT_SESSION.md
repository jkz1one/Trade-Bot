# Daily PAPER operation

Use the existing `local-simulation` account and population
`connected-simulation-1000-v1`: $1,000 initial virtual capital, maximum two plays,
$1/day and $5 total AI spending. Balances, positions, journals, halts and enrollment
persist. Robinhood supplies read-only data; execution is local simulation. LIVE
remains disabled. No separate broker paper account is used.

## Current host and November 5 preparation

The operator deployed `adb453fabeb626e50a3ae6a372979e3b4e06483c` as image
`sha256:e4171d8d03eacac853c5e7dfd1b13f8491d2eda548627ba5a072d455d8e2e66a`.
Authorization already passed. The narrow reviewed schema compatibility fix is now
on the host; no additional login, schema replacement, discovery or build is needed
for the next DEGEN check. The optional Scope handoff below has not been deployed.

November 5 contract capture succeeded with eight Robinhood reads and no worker or
model call. The original directory is `/root/trade-bot-options-proof-nxgh8bvl`.
`all_fresh_at_capture` is false, with no future quote samples. These are historical
contract/quote receipts, not executable prices or a readiness claim.

Tuesday's original operator log establishes the retained Swing directory as
`/root/trade-bot-options-proof-zm26sb07`, with four November 13 contracts. They are
eight calendar days from November 5 and remain within the native 7–45-day range.
Reuse this original evidence; do not recapture it or reuse November 3's same-day
DEGEN contracts. The following command was supplied; completion is not yet observed:

```bash
cd /opt/trade-bot-dashboard &&
python3 scripts/paper-session-start.py \
  --capture-directory /root/trade-bot-options-proof-nxgh8bvl \
  --target-session 2026-11-05 \
  --observed-swing-history \
  --swing-capture-directory /root/trade-bot-options-proof-zm26sb07 \
  --prepare-only \
  --run-id thursday-ready
```

This reviews/enrolls the new session through the existing append-only path and
publishes its snapshot. It starts no worker, makes no provider/model request and
preserves the existing account, balances, journals, halts, limits and population.
It selects the observed Swing mapping; it does not supply missing original history.
Do not repeat preparation after `SESSION_PREPARED`. If publication fails after
`prepared.json` was saved, use that receipt rather than re-enrolling.

Only after successful preparation, on **November 5 after 10:00 a.m. New York**:

```bash
cd /opt/trade-bot-dashboard &&
python3 scripts/paper-session-start.py \
  --prepared-session /etc/trade-bot-connected/sessions/2026-11-05-thursday-ready \
  --seconds 600 --wait
```

This is a bounded ten-minute run, not a scheduled task or a two-hour wait. DEGEN
still requires six delivered completed five-minute bars. Original quote validation
and native risk limits remain authoritative. Swing and Scope may remain blocked
independently. Never reuse the receipt on November 6 or later.

## Optional Scope paid-read handoff

The new code adds `post_cost_refresh: "bounded-paid-refresh-v1"` to an explicitly
reviewed `ScopeFeedBinding`. The default is absent and preserves old serialized
bindings and play identities. Opting in changes the binding/play hash and must be
part of a new exact-session review. Do not edit an enrolled binding in place.
No current host Scope binding or spare catalog slot has been established.

After one complete settled, timely Scope ENTER decision, the connected runtime
queues one durable read request for that cycle. The existing collector is the only
writer and wakes from its normal sleep to serve it. This is a narrowly reviewed
exception to the ordinary minimum poll spacing, not a change to `poll_seconds`.
The same frozen per-minute quota and eight-call capture limit remain enforced;
requests that cannot fit the quota produce a paid HOLD without increasing limits.
No Swing backfill is added to this urgent read. Successful delivery is MARKET-only,
never another scan or a producer-supplied watch/admission action.

The caller waits for native acceptance and completion of independent protection.
Raw clocks, source advancement, original five-second admission deadline, exact
terms, post-cost account checks and unknown-cost blocks remain unchanged. Slow or
invalid reads cannot enter. A timed-out caller cannot cancel independent collection
or protection; the bounded read may finish as original evidence. Interrupted read
requests cannot be replayed on restart. Expected quota/failure/expiry conditions
are specific HOLD/input reasons, not automatic global entry recovery.

This completes an offline-tested collection/delivery handoff, not measured Robinhood
latency or full connected Scope readiness. The success fixture has spare read quota;
the saturated-quota fixture refuses. Actual read plus model plus native acceptance
must still fit the original deadline. Exact SPXW/session/pattern evidence, usable
original SPX bars and seven candidates plus one Scope slot remain required.
Validation covers 457 distinct passing installed-package cases after a fixture
correction; 318 application files and 60 runtime pins match. See
[the proof](PAPER_SCOPE_REFRESH_PROOF.json). The already deployed image can
continue the next DEGEN check; do not rebuild it solely for this unconfigured path.

## Historical November 3 preparation

Already enrolled:
`/etc/trade-bot-connected/sessions/2026-11-03-tuesday-ready`.
Policy SHA: `8136af394ef61ac8546010d7d69811110f417b7b800a3b7191535e13688c4f51`.
The last reported runtime is STOPPED with `OPTION_RUNTIME_STOPPED`, accepted
feed sequence 472 and zero fills after the two-hour run.
The connected dashboard is already active; do not switch it again.

Attempts 168–170 establish the original daily-history blocker. Attempt 168 had
54 mapped hourly bars per SPY/QQQ but both November 2 daily bars were interpolated.
169 independently confirmed the SPY daily blocker; 170 failed SOURCE_CLOCK_CHECK
and independently returned INTERPOLATED_BAR. The quote-clock recovery is deployed
in dfe3bf0. Replaying these attempts, rebuilding, or repeating overnight collection
cannot make their daily bars original. The required input is valid original daily
history. DEGEN can run independently while Swing remains blocked.

## Deploy once, with connected workers stopped

For future application changes, use the supplied tested release SHA on a clean
checkout. `/opt/trade-bot-dashboard` is a detached worktree; the working branch is
already checked out at `/opt/trade-bot`:

```bash
cd /opt/trade-bot-dashboard &&
git fetch origin slice2/robinhood-read-shadow &&
git merge-base --is-ancestor HEAD TESTED_RELEASE_SHA &&
git switch --detach TESTED_RELEASE_SHA &&
python3 scripts/connected-session-host.py build
```

Replace `TESTED_RELEASE_SHA` with the supplied full SHA. This deliberately refuses
a divergent checkout rather than discarding newer work. Do not reset, clean,
re-enroll, recapture contracts or recreate the account. A build does not start a
worker or refresh provider data. The new image is used on the next explicit run.

For a later day's reviewed preparation, an explicit ten-minute check is:

```bash
cd /opt/trade-bot-dashboard &&
python3 scripts/paper-session-start.py \
  --prepared-session /etc/trade-bot-connected/sessions/REVIEWED_CURRENT_DATE_SESSION \
  --seconds 600 --wait
```

Replace the directory placeholder with that day's reviewed receipt. DEGEN requires
at least six completed five-minute bars; VWAP_PULLBACK requires 25 (earliest
11:35 New York on a normal session). Time alone does not prove that the provider
delivered them. The launcher refreshes the snapshot, verifies the exact
prepared policy, performs bounded reviewed flat recovery and chooses a new run ID.
It does not bypass held-position, unknown-cost, order or halt checks.

Prepared receipts are date-specific. **On November 4 or later, do not reuse this
November 3 directory.** Prepare/review that day's explicit catalog/session using
[session preparation](SWING_SCOPE_ROBINHOOD.md#session-inputs) and the existing
`--prepare-only` workflow. Previously captured exact inputs can be supplied; an
unrelated date's receipt cannot be relabeled.

## Status, stop and longer runs

The launcher prints the exact status and stop commands for its run. The same
report works while running and after exit, without a build or provider request:

```text
python3 scripts/paper-session-report.py --run-id RETURNED_RUN_ID
```

| `operation.state` | Meaning |
| --- | --- |
| RUNNING | Fresh native heartbeat/input evidence; first scan pending or active processing. No readiness or fill claim. |
| WAITING_FOR_SETUP | Fresh accepted input and a completed HOLD decision without a reported input blocker. Specific setup/contract reasons remain visible. |
| MISSING_INPUTS | Missing/stale/future heartbeat or feed, incomplete history/quotes, ENTRY_HEALTH_BLOCKED, or a retained entry halt. Read the reasons and family issues. |
| STOPPED | Container ended successfully or the current native worker is stopping/stopped. |
| FAILED | Container exited nonzero or native runtime recorded FAILED. |

Scope/Swing input issues are separate from DEGEN's decision. The report distinguishes
the latest collected packet from the packet actually accepted by the native owner.
It preserves original timestamps and frozen freshness bounds, shows the latest
five detailed decisions and 25 cycle records, and explicitly counts omitted older
records. First decisions and collector failures are also retained in bounded
summaries, with run-wide decision reason counts and halt history. `run_issues`
survives terminal STOPPED status: a process can end normally after input failures.
Model-call counts distinguish the selected run from the current account total;
an unsettled call is a stored NULL cost, not permission to clear it or retry.
Account-total fills are cumulative, not new fills attributed to this run.
The two databases are read-only snapshots taken independently; this is observation,
never a trading authority or an atomic cross-database checkpoint.

Stop early using the exact `stop_command` returned by the launcher. It includes
the inspected container ID, requests orderly shutdown, and preserves state and
evidence. An interrupted terminal does not delete or restart the container. If
waiting/reporting fails after startup, inspect that run; do not start another one
just to retrieve its report.

The launcher now accepts an explicit bounded duration of **60–23,400 seconds**
(up to 6.5 hours). The existing 600-second default is unchanged. For a longer
supervised run after reviewing the short run, change only `--seconds`; omit
`--wait` to return immediately. Native calendar/cutoff/protection gates remain in
force, including shortened sessions. Duration is an upper bound, not an extension
of entry hours or a guarantee that positions are flat at shutdown. There is no
scheduler, automatic restart or daily enrollment. Mid-run recovery is disabled
unless explicitly included in that launch's review as described below.

## Optional bounded recovery during one run

After building the runtime update, `--max-feed-recoveries 1` (or 2 or 3) on
`paper-session-start.py` explicitly authorizes that many successful recoveries
from temporary native feed halts within the reviewed run. The default is **0**;
existing commands retain their behavior. This option does not alter or re-enroll
the prepared session. The host review binds the allowance and the launch output
truthfully sets `automatic_resume` to true only for a nonzero allowance. There
is no automatic process restart or reuse on another date.

Recovery requires two newly accepted packets with fresh, advancing original
underlying source clocks, fresh native heartbeat and account reconciliation, a
flat account, no pending orders and no unknown costs. Existing quote, setup,
budget and loss gates still control every entry. Manual/other halts, unresolved
feed faults and an exhausted allowance stay blocked. Held-play protection keeps
running; this option never clears a halt while positions or pending orders exist.
Each successful recovery remains in the journal and the host report's
`flat_feed_recoveries` count. The supplied stop command ends the run and leaves
the normal stop halt in place.

## Remaining work and evidence

| Area | Implemented / offline evidence | Remaining requirement |
| --- | --- | --- |
| Shared owner / DEGEN | Production-profile raw collection, scanning, two paid entries, later fills, independent exits, restart and accounting fixtures. | Authentic qualifying setup, real model response and complete connected simulated lifecycle. No connected fill has been observed. |
| Swing | Source preparation/recovery and native shared scanning/execution fixtures; missing family remains isolated. | Valid original daily history and complete connected lifecycle. Saved interpolated bars remain rejected. |
| Scope | Collector-to-native watch routing corrected; native sampled arming, exact paid admission, later-quote fill, restart and exit regression. Owned plays stay out of new-entry admission while exact-play management remains available. Terminal watches cannot be revived by retained ARMED evidence. | Original usable SPX history, exact reviewed SPXW terms/session/pattern binding, a catalog with a reserved slot, and connected lifecycle. No SPY substitution or invented contract terms. |
| Scope timing | Reviewed one-shot paid-read handoff wakes the actual collector, charges its existing quota and waits for native acceptance. Offline success, quota, stale, late, failed and cancelled read cases retain the original deadline and model cost. | Actual Robinhood/model latency and sufficient quota inside the original five-second deadline remain unverified. |
| Daily operation | Unique bounded launches, exact stop, retained reports and optional reviewed flat feed recovery capped at three per run; native timeout/recovery/stop/restart fixtures. Two-hour host run stopped on schedule. | Host authorization passes. Schema compatibility is deployed and November 5 contracts were captured. The combined preparation command was supplied but not yet confirmed; actual model timing and connected lifecycle remain unverified. |

Scope bindings consume one of the **eight** candidate slots. The current eight
DEGEN/Swing contracts cannot silently gain a ninth contract or drop a family.
Scope execution/watch/management code already exists; missing reviewed evidence
and session configuration are distinct from the corrected delivery defect.

The [historical proof](PAPER_SCOPE_OPERATION_PROOF.json) recorded 237 passing
installed cases and a legacy five-second worker timeout. That unchanged case passes
in the current installed run. A separate SDK-worker test also passed with the
unchanged production 15-second process budget and 20-second management lease.
These environment-specific results do not establish real model latency or timely
connected admission.

The November 4 host-only diagnostic update separately passes 51 report/launcher
tests, including failure-window scoping, early/late evidence, private-field
exclusion and read-only database preservation. It changes no application file.

That earlier host-only update is followed by the optional runtime recovery and
original-capture diagnostics release. Its tests and installed-file verification
are recorded in [PAPER_FEED_RECOVERY_PROOF.json](PAPER_FEED_RECOVERY_PROOF.json).
Neither synthetic recovery nor a clean process exit establishes trading readiness.

## Authorization recovery reference (already deployed; do not repeat now)

The saved report from checkout `1922b0e` now identifies the latest ten failed
captures (587–596): `CONNECT` → `ReadAuthorizationRequired`, with no schemas.
The headless worker was asked to enter interactive authorization. This does not
prove a revoked/expired refresh token. No market read was reached in those attempts.

An offline reproduction using the pinned MCP 2.3.0 SDK found a restart defect:
a saved access token rejected with 401 goes through issuer discovery and then
straight to login, without attempting its saved refresh grant. The application
now attempts that grant once, after the SDK validates the resource/issuer and
credential binding. Rejected grants still require login; changed issuers and
403 scope escalation retain native authorization checks. Token rotation and
omitted refresh-token/scope handling use the SDK's existing private persistence.
This fixes a reproducible implementation gap; only a host check can establish
whether the currently saved grant is still usable.

With connected workers stopped, use the tested release SHA supplied with this
update. This builds the accumulated runtime fixes once, then performs one bounded
headless **schema-only** discovery. No market bars, quote capture, model call,
trader start, account mutation or current-day preparation is involved:

```bash
cd /opt/trade-bot-dashboard &&
git fetch origin slice2/robinhood-read-shadow &&
git merge-base --is-ancestor HEAD TESTED_RELEASE_SHA &&
git switch --detach TESTED_RELEASE_SHA &&
python3 scripts/connected-session-host.py build &&
python3 scripts/connected-session-host.py check-read-auth
```

- `READ_AUTH_VERIFIED`: the saved/refreshed authorization completed headless
  discovery. No manual login is needed. This is not trading readiness.
- `READ_AUTHORIZATION_REQUIRED`: run the following explicit operator login once.
  It backs up the current OAuth file privately under the native read lease,
  performs interactive discovery, then checks headless discovery automatically.
- `READ_AUTH_CHECK_FAILED`: inspect the new private discovery receipt; do not
  assume a transport or schema failure is fixed by login.

```bash
python3 scripts/connected-session-host.py login-read-auth
```

Complete the printed Robinhood login URL in your browser. If the localhost
callback page does not load, paste its full address into the waiting **server
terminal**, never chat. Keep the URLs, credential backup, private output directory
and login log private. Share only the final JSON status. The login has a ten-minute
human-input limit; the headless check retains its 30-second limit. Both helpers
refuse an active connected session, mount no owner/model keys and leave the
existing discovery/enrollment unchanged. They do not schedule or start trading.

The November 3 two-hour run `paper-1103-174343-7ae3b7` ended on schedule at 14:45
New York with zero fills, 266 delivered captures and 127 failed captures. A 13:10
read timeout latched the native feed halt; eleven later decisions were health
blocked. The separate bounded flat-feed recovery fix is included in this build,
but remains explicitly opt-in. Model attempts and unsettled costs were zero.
The host's last built image was `0a4e4e4` /
`sha256:29df9b86c2874a930166aaffef4118e74d37eec45b3c4f9728b6fa4615102cdb`.
The deployed image hash above is historical; use the new build's returned hash.
See [authorization regression proof](PAPER_AUTH_REFRESH_PROOF.json).
