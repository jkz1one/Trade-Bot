# Daily PAPER operation

Use the existing `local-simulation` account and population
`connected-simulation-1000-v1`: $1,000 initial virtual capital, maximum two plays,
$1/day and $5 total AI spending. Balances, positions, journals, halts and enrollment
persist. Robinhood supplies read-only data; execution is local simulation. LIVE
remains disabled. No separate broker paper account is used.

## Current host and November 6 evidence

The host has built `840255127c8d895fd6bc22dab9410bb7f6ec48a0` as image
`sha256:3b5a3344fc30b4d5450aa719450ef79554845063d24e4a705f862fa8f5e13bf6`.
The November 6 receipt is already enrolled:
`/etc/trade-bot-connected/sessions/2026-11-06-friday-ready`, policy
`b511b0df3552f505c9d5c0e01385a9b2502976652a41f56c10b9fe308586f162`.
It combines four November 6 DEGEN contracts from
`/root/trade-bot-options-proof-8zyypx4s` and four November 13 Swing contracts from
`/root/trade-bot-options-proof-zm26sb07`. The eight-contract catalog is full.
Do not repeat authorization, capture, preparation, enrollment or dashboard activation.
This receipt must not run on another date.

Run `paper-1106-151939-cd07ea` stopped normally at 10:31 New York on November 6.
It delivered 23 packets, had five read timeouts, used both bounded feed recoveries,
and ended with zero fills and zero model calls/costs. Accepted sequence was 678;
collected sequence was 679. Final fresh heartbeat/feed is a terminal observation.

Two cycle records completed, but only the second contained strategy scans. The
first stopped at `AUTHORITATIVE_RECONCILIATION_REQUIRED / PORTFOLIO_READ_SUPERSEDED`.
The second scanned SPY/QQQ: twelve WATCHING setups, none confirmed, with volume
confirmation absent throughout. VWAP pullback also lacked 25 completed bars.
`INVENTORY_BINDING_COVERAGE_OR_FRESHNESS` remained an independent entry blocker.
Ten skipped records are historical/unobserved; one active slot expired without feed.
The slot repair enabled connected scan progress; contract admission and a connected
entry-to-exit lifecycle remain unverified.

The five timeout diagnostics show DISCOVER twice, SERIALIZE twice and CLOSE once.
A last reached phase does not prove its elapsed time or root cause. The current
code removes repeated checks of identical schema definitions and improves reports;
it does not claim that those host timeouts or snapshot supersession are fixed.
No freshness limit, deadline, recovery cap, risk check or enrollment is changed.

## Next action: inspect the existing run

After updating the detached checkout to the supplied tested release, read the
**same stopped run**, without collecting more data:

```bash
cd /opt/trade-bot-dashboard &&
python3 scripts/paper-session-report.py \
  --run-id paper-1106-151939-cd07ea --format text
```

The report now projects original inventory source/receive/evaluation clocks and
its enrolled metadata-age limit from saved decision inputs. Missing clocks remain
unavailable. It also shows entry blockers, actual scan evidence and all retained
read-failure phases. This host-side reporting update needs no image rebuild.
The schema optimization requires one build before a subsequent worker launch;
combine it with the next deployment, with workers stopped. Do not launch another
market run solely to reproduce these reporting or schema-overhead defects.

## Remaining work and evidence

- **Implemented offline:** current-slot recovery, bounded scan attempts across
  restart, schema-definition reuse, explicit scan/input/stop/failure reporting,
  retained-clock inspection, Scope owned-play routing, pacing and setup review.
- **Still unresolved:** the host's snapshot supersession, exact inventory rejection
  and variable read/processing latency. Use retained evidence first; this release
  is not a claim that daily PAPER is dependable yet.
- **Requires valid original inputs:** Swing daily history and usable SPX history,
  exact reviewed Scope contract/session/pattern terms and explicit catalog space.
  Saved interpolated Swing bars remain rejected. No SPY substitution or ninth slot.
- **Requires connected acceptance:** an admitted simulated entry, fill, management
  and exit. No such connected lifecycle or fill has been observed.

## Optional Scope paid-read handoff

The original reviewed `post_cost_refresh: "bounded-paid-refresh-v1"` binding keeps
its one-shot handoff and ordinary cadence. The new
`post_cost_refresh: "paced-paid-refresh-v2"` selection explicitly adds twenty-second
ordinary capture **start spacing** and a read-budget check before Scope is offered
to the paid selector. Neither mode is added to an existing binding implicitly.
Absent fields preserve legacy serialization; changing modes changes the play/hash
and requires a new exact-session review. Do not edit enrolled bindings in place.

The actual collector loop reproduced a greater-than-30-second gap with ordinary
polling under six reads/capture and 24 reads/minute. Paced fixtures collect at
0, 20 and 40 seconds, leaving six reads for one paid refresh. The request wakes the
same sole writer immediately and remains MARKET-only. Every read, including failed
reads and held-overflow requests, still consumes the original persisted sliding
quota. The eight-call capture ceiling and frozen `poll_seconds` are unchanged.
Optional Swing backfill is omitted while this paced Scope session is active; its
pre-open source preparation remains separate.

The native Scope candidate is withheld before model spending when the collector
is busy, its accepted packet differs, or its known next read cannot fit the quota.
The rejection is retained in `scope_rejections`; independent DEGEN selection can
continue. This is a conservative restriction, not a quota reservation or admission
permission. Holdings and elapsed time can still change before the actual read,
which repeats the quota check. Seven-read captures may not leave a refresh allowance;
held-book overflow must be considered when selecting the catalog. If a new held
book costs more than the last capture, ordinary quota retries wait at least one
second; paid-request and stop signals still wake immediately.

Native acceptance and independent protection still precede the paid admission.
Original source advancement, quote/size checks, exact terms, budgets and the
five-second original deadline remain enforced. Failed, stale, delayed or unfundable
reads cannot enter. Caller timeout does not cancel independent collection, and
interrupted requests cannot replay on restart. No automatic entry recovery is added.

The full scheduled fixture runs native supervision between captures and exercises
paid entry, a later fill, restart and exit. A second fixture refuses Scope before
any model call when quota is exhausted. These are synthetic offline proofs; variable
Robinhood latency, usable original SPX history, exact SPXW/session/pattern bindings
and a connected lifecycle remain unverified. See [validation](PAPER_DAILY_TOOLS_PROOF.json).

## Read-only Scope setup review

The installed helper can inspect retained evidence
without stopping workers, opening credentials, collecting data or enrolling:

```bash
python3 scripts/connected-session-host.py review-scope-setup \
  --target-session 2026-11-06 \
  --capture-directory /root/trade-bot-options-proof-8zyypx4s \
  --observed-swing-history \
  --swing-capture-directory /root/trade-bot-options-proof-zm26sb07
```

It lists the original contracts, selected/omitted IDs, missing Scope binding fields,
original contract/index evidence and slot requirements. It also estimates the
regular-session read cost flat and with one additional held contract; it does not
inspect or change holdings. The current eight candidates leave no ninth slot.

When actual evidence is available, optional inputs are `--scope-binding`,
`--scope-contract-capture` and `--scope-input`. The binding must name exact reviewed
SPXW cash/European/PM terms, session, previous session, pattern/right and refresh mode.
The contract file is compared using its canonical JSON fingerprint with
`contract_capture_sha256`; **hash equality does not verify brokerage terms**. Inspect
the original document against the binding. Index input accepts original `SCOPE_INPUT`
or combined `CAPTURE` receipts and uses the existing pinned SPX validator/mapper.
Historical mapping time and current source age are reported separately; stale
originals remain stale. Missing fields never receive invented defaults.

To make room, repeat `--candidate-id ACTUAL_ID` for every retained DEGEN contract.
The subset must contain only unique original DEGEN IDs and retain each enrolled
symbol. All four supplied Swing contracts remain intact. Omissions are explicit;
there is no automatic ranking, substitution or truncation. The same flags pass
through `paper-session-start.py --prepare-only` to the existing review/enroll path.
They cannot alter `--prepared-session`. Do not change November 6's enrolled receipt
merely to try this helper. `INPUTS_REVIEWED` is not trading readiness or term verification.

## Compact operator report

Detailed JSON remains the default. Read the same running/stopped evidence as
bounded text with:

```text
python3 scripts/paper-session-report.py --run-id RETURNED_RUN_ID --format text
```

It shows operation state/reason, original heartbeat/feed freshness, collected versus
accepted sequence, each family's blockers, last decision, account-total fills,
run cycles and settled AI costs. Cycle outcomes distinguish complete, skipped,
waiting, started and interrupted work, with retained reasons and recovery counts.
Collection totals and the last available read phase remain visible. No decision
means scan not established; terminal fresh data does not erase earlier outages.
Run costs, New York calendar-day costs and account costs are separate; daily/total limits come from the enrolled cost policy. Unknown
or invalid charges remain counted explicitly. Missing cost evidence is unavailable,
not zero. Account totals may include other runs; source snapshots are independent.

Append `--report-format text` to a launch using
`--wait` for the same short report at exit. Stop/failed-run reporting still retains
its error status and never starts a replacement worker. Use `--format json` for
full retained diagnostics. A normal stop, no reported family blocker, or a passing
fixture is not a trading-readiness claim.

## Deployment of the current repair

Update the detached dashboard checkout to the supplied tested commit. The report
can immediately inspect saved runs. Build the schema-efficiency image once before
its next worker launch, with connected workers stopped. Do not switch the branch
already owned by `/opt/trade-bot`, reset the account or repeat enrollment. Scope
pacing remains inactive without its explicitly reviewed exact-session binding.

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
| Scope timing | Explicit paced mode tests the full collector schedule, native supervision, one-shot refresh and entry/fill/restart/exit. Unfundable Scope reads are excluded before paid selection; peers remain independent. | Actual Robinhood/model latency, held-overflow capacity and connected acceptance inside the original deadline. |
| Daily operation | Unique bounded launches, exact stop, optional bounded recovery, read-only Scope setup review with explicit catalog selection, and compact reports with exact cost/unknown-charge handling. | Host authorization passes. Schema compatibility is deployed and November 5 contracts were captured. November 5 enrollment is confirmed. Two checks stopped without fills; the second recovered twice but skipped all slots. The handoff repair is offline-tested; actual timeout causes and connected lifecycle remain unverified. |

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
