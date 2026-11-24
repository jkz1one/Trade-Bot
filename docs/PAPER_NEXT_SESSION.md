# Daily PAPER operation

## Current action: offline protection-latency repair; no host changes

The operator's detached `20923e2` test was OOM-killed after 37m 19s, exit 1 with
zero restarts. It recorded 445 native snapshots without timeout, but its stale
RUNNING progress has no final coverage, execution or accounting. The duration
gate FAILED. Retain its evidence at
`/var/lib/trade-bot-paper-soak/trade-bot-offline-soak-20923e2e823d-iftsm6k7`.
[Incident and candidate proof](PAPER_MEMORY_20261124_PROOF.json).

The cache repair replaces obsolete encodings for each changing table/batch. Its
300-update reproduction ended at 368 MiB versus 528 MiB with the preceding policy,
while preserving the canonical authority hash. The installed-system suite passed
976 tests with one unmapped-reader-UID skip. The new offline runner also records
cgroup memory counters, including file/tmpfs charges and OOM events.

The larger protection test blocks qualification: stock took 6.13 seconds and
options 7.95 seconds against the unchanged five-second whole-case target. Both
positions exited and accounting verified flat. The preceding cache policy also
misses the target in the same environment; full-journal verification dominates
repeated owner commits. Preserve these failed results. Finish the offline latency
gate before asking the operator to spend another session on a duration test.

Keep the installed `2d538b7` checkout, account, retained connected worker, timer,
risk/model limits and `SESSION_STOPPED_REVIEW_REQUIRED` hold unchanged. No deploy,
resume, restart, halt clearing or memory increase is proposed. The server is
operator-managed; local checks do not establish its current state.

When local qualification passes, the next host gate is a fresh isolated Docker
soak using one CPU, 1 GiB with no swap, 128 PIDs, no network/credentials and a new
synthetic evidence directory. Review its actual progress after 45 minutes and its
final receipts after the full duration. No new start command is recommended yet.
A passing synthetic run would still leave real-provider connection health and
connected R4 unverified. Earlier host commands below are historical.

The final 335-second loaded fixture also FAILED: 101 native snapshots completed
without failure (maximum 0.303 seconds), but native acceptance exhausted its
remaining 1.240-second transport budget. No round trip completed, and only one
of two scheduled decision slots was measured. Sampled process-tree peak was
489,492,480 bytes; cgroup counters are unavailable locally. Reduced memory and
successful snapshot reads do not override the failed lifecycle gate.

## Prior November 20 installation and schedule check

Installed release: `2d538b7f32afa7b6df09e7af0d3534e9e27f71e5`.
The operator supplied `RELEASE_INSTALLED`, stage `reader`, with no reported failure.
Evidence: `/root/trade-bot-release-zk5617xi/release.json`.
[Qualification, deployment and open gates](PAPER_CATALOG_CAPTURE_20261120_PROOF.json).

The release workflow reached installation only after its real provider capture and
stopped-account publication gates passed, with an unchanged owner and matching
installed release/image. The summary does not expose individual capture counts,
selected strikes, fallback usage or the current timer state. These are not inferred.
The prior `9a140b8` attempt stopped on two empty December 4 exact-strike probes;
that failed attempt is preserved in the evidence record.

`scheduler_resumed: false` means this deployment did not clear a pause or review
hold. It does not mean the scheduler is necessarily paused. The command preserves
account state, enrollment, limits and retry counts. It restores a previously
active timer after success; the timer's current state needs the check below.
Do not repeat deployment or issue a resume based only on this flag.

Run this read-only block on the operator-managed server and paste the output:

```bash
cd /opt/trade-bot-dashboard
date -u '+UTC: %Y-%m-%d %H:%M:%S'
systemctl is-active trade-bot-paper-daily.timer
python3 scripts/paper-diagnose.py --target-session 2026-11-23
```

November 23 is the expected next session from the earlier qualification. Confirm
it against `controller_target_session`; the latest summary does not state a date.
A missing November 23 worker before its scheduled launch is expected. The report
includes installed release/image, UTC observation time, controller target/status,
pause state, original failure, worker start/end/restarts, feed/decision evidence
and immutable display publication time. A missing worker differs from a failed
Docker inspection. The command makes no provider calls or account/worker changes;
display receipt inspection does not claim to reverify accounting.

R4 requires the same scheduled run at launch, 30 minutes, two hours and close.
The default profile launches at 10 a.m. New York time: expected Monday checks are
10 a.m., 10:30 a.m., noon and 4 p.m., subject to the confirmed schedule. Check
advancing feed and decision evidence, original quote freshness, due/missed slots,
family blockers, recovery counts and publication, then clean closure/accounting.
Zero fills alone is not failure; a running container alone is not a healthy feed.
Diagnose a failed early check then, rather than waiting until close.
Provider CONNECT failures, publication under load, Scope inputs and Swing geometry
remain open until actual evidence resolves them.

## November 20 incident before this candidate

At this earlier checkpoint, `c03b628` was installed and the operator confirmed
`SCHEDULE_RESUMED`. The
November 20 worker never launched: three preparation attempts rejected the
optional historical-output `notice` addition at `VALIDATE_PLAN`. The controller
reports `PREPARATION_RETRY_LIMIT`; the older worker report is November 18.
The earlier deployment and resume blocks below are historical, not the next action.

The user requested a process correction before more isolated fixes, then
authorized implementation. The supplied schema difference was sufficient for
local reconstruction; no further raw schema dump is needed. The new handoff
above implements [R1-R3](DELIVERY_PLAN.md#november-20-work-order-repair-the-delivery-process-first)
without resetting the failed day's retry count. Real-host qualification and
installation are now confirmed above; sustained observation remains pending.
[Confirmed receipts and audit](PAPER_PROCESS_REVIEW_20261120.json).

## November 18 failed session review

The deployed `220da15` worker lasted nearly six hours but completed only two
cycles. One publisher timeout at 10:07:14 a.m. permanently fenced entries and
feed recovery for the run. The controller is stopped for session review.
Published repair `c03b628` passes 623 installed-system tests (one environment
skip) and three additional damaged-account checks. It was subsequently deployed
as recorded in the current checkpoint.
Keep the retained display, native account and daily evidence. Deployment must
recover the display, verify a normally stopped flat owner and preserve all limits
before an explicit scheduler resume. Do not reuse the November 10 timeout
approval for this different failure. Provider connection failures are unresolved.
[Detailed evidence](PAPER_SESSION_REPAIR_20261118_PROOF.json).

### Verify the repair on the stopped host

This checks the candidate against the existing account and recovers the display.
It preserves the installed release and scheduler halt. The timer cannot launch
while its recorded session-review requirement remains in place. A running worker
makes this preflight stop. Candidate code is checked out only
in a separate temporary Git worktree; the original failed display is archived
by `recover-snapshot` after a successful replacement.

```bash
(
  set -eu
  cd /opt/trade-bot-dashboard
  release=c03b6282fed59e48f113b06f4bc02f53b50410d0
  git fetch origin slice2/robinhood-read-shadow
  git merge-base --is-ancestor HEAD "$release"
  git merge-base --is-ancestor "$release" FETCH_HEAD
  test -z "$(git status --porcelain)"
  active=$(docker ps --filter label=trade-bot.connected-session-v1 --format '{{.Names}}')
  test -z "$active" || { echo "A PAPER worker is running."; exit 1; }
  candidate=$(mktemp -d)
  git worktree add --detach "$candidate" "$release"
  trap 'git worktree remove "$candidate"' EXIT
  python3 "$candidate/scripts/connected-session-host.py" build
  python3 "$candidate/scripts/connected-session-host.py" daily-info
  python3 "$candidate/scripts/connected-session-host.py" recover-snapshot
)
```

Success requires `DAILY_INFO` with the expected stopped flat owner and
`PUBLISHED` with `source_modified: false`. A new capture is not required to
verify accounting publication. This preflight does not fix or establish the
cause of provider connection timeouts, authorize new entries or prove a full day.

## Wednesday, November 18

Historical pre-session checkpoint; superseded by the failed-session review above.

The host is confirmed on `220da15` after the completed installation below.
At 11:44 p.m. New York time on November 17, its catalog capture completed
eight provider calls and selected four candidates. Both `daily-info` checks
passed. The scheduler is unpaused, the daily timer is active and the dashboard
reader was updated. The build and installed scheduler report image
`sha256:07236964d00d18448c531e4ca84326a4c4eec1cf3a878d95a489363a5e40ec05`.

| Wednesday step | New York time | UTC |
| --- | --- | --- |
| Preparation | 9:00 a.m. | 14:00 |
| Launch review | 10:00 a.m. | 15:00 |
| Session close | 4:00 p.m. | 21:00 |

The successful capture reports `all_fresh_at_capture: false`,
`trading_ready: false` and `workers_started: false`. Wednesday still needs
current inputs and a successful launch review. Its owner remains at the
November 10 failure with revision 5453, feed sequence 1432 and runtime
generation 15, matching the previously saved timeout review. The controller
rechecks the complete owner state before preparation and launch. The two
successful `daily-info` calls do not establish the cause of its earlier
intermittent failures.

The next acceptance check is Wednesday's day record and worker creation after
10:00 a.m. A session report is available only after its worker exists. Keep
the installed release; the following deployment block is completed history.
[Operator receipts and remaining acceptance checks](PAPER_SCHEMA_CONTRACT_20261117_PROOF.json).

## November 17 capture repair

Tuesday's preparation failed three times on `fd7ff01`. Every saved context
stopped at `VALIDATE_PLAN` with zero market reads. The provider changed one
historical-tool description. The complete input and output structures match
the reviewed contract. The day has no session receipt or worker container.
Its after-hours `WAITING_NEXT_SESSION` status describes the scheduler's next
date. The saved owner review still matches revision 5453 and feed sequence 1432.

`220da15` compares the reviewed wire contract independently of descriptions.
It accepts later description edits while validating the original complete
metadata digest and every response. Fixed tool names, permission annotations,
argument rules and response constraints remain part of the contract.
The host reports capture failure stages and identifies the module and exit
code for failed offline commands. A daily-plan exception also reports its
class and application frames. Tuesday's separate intermittent `daily-info`
failures still require host evidence with those diagnostics.

The operator completed the following block from the stopped host on November
17, New York time. It built the candidate, paused the timer and checked the
current owner before capturing Wednesday's catalog. Both checks passed and
installation completed. The exit trap restored the timer and removed the
temporary checkout.

```bash
(
  set -eu
  cd /opt/trade-bot-dashboard
  release=220da15acec2bf0ff76cbf7354c7385992af644b
  prior=$(git rev-parse HEAD)
  git fetch origin slice2/robinhood-read-shadow
  git merge-base --is-ancestor "$prior" "$release"
  git merge-base --is-ancestor "$release" FETCH_HEAD
  test -z "$(git status --porcelain)" || { echo "Checkout has local changes."; exit 1; }
  candidate=$(mktemp -d)
  git worktree add --detach "$candidate" "$release"
  trap 'git worktree remove "$candidate"' EXIT
  python3 "$candidate/scripts/connected-session-host.py" build

  timer=trade-bot-paper-daily.timer
  systemctl is-active --quiet "$timer" || { echo "Daily timer is inactive."; exit 1; }
  trap 'systemctl start "$timer"; git worktree remove "$candidate"' EXIT
  systemctl stop "$timer"
  flock -w 120 /var/lib/trade-bot-paper-daily/controller.lock true
  state=$(systemctl show -p ActiveState --value trade-bot-paper-daily.service)
  case "$state" in
    inactive|failed) ;;
    *) echo "Controller is busy. Retry after it finishes."; exit 1 ;;
  esac
  active=$(docker ps --filter label=trade-bot.connected-session-v1 --format '{{.Names}}')
  test -z "$active" || { echo "A PAPER worker is running."; exit 1; }

  python3 "$candidate/scripts/connected-session-host.py" daily-info
  python3 "$candidate/scripts/connected-session-host.py" capture-session --target-session 2026-11-18
  test "$(git rev-parse HEAD)" = "$prior"
  git switch --detach "$release"
  if ! python3 scripts/paper-daily.py install; then
    git switch --detach "$prior"
    python3 scripts/paper-daily.py install
    exit 1
  fi
  python3 scripts/connected-dashboard-host.py update-reader --snapshot-name connected-price-options-v1
  systemctl start "$timer"
  systemctl is-active "$timer"
)
```

The host returned two successful `DAILY_INFO` receipts, `CATALOG_CAPTURED`,
`DAILY_SCHEDULE_INSTALLED`, `DASHBOARD_READER_UPDATED` and a final `active`.
Preparation and launch remain subject to the next session's current inputs
and account review.
[Incident, offline proof and host receipts](PAPER_SCHEMA_CONTRACT_20261117_PROOF.json).
[Previous deployment receipts](PAPER_SNAPSHOT_RECOVERY_20261116.json).

## November 16 dashboard snapshot recovery

Monday's captures and preopen preparation succeeded on `39d8e48`. At
10:00:56 a.m. New York time the dashboard snapshot exceeded its deadline.
The next two attempts found a retained failed snapshot. The controller
exhausted its three reviews before starting a worker. The host log does
not identify the stage of the first timeout.

At 10:30 p.m. New York time on November 16, the operator built `fd7ff01`
in a separate checkout and recovered the host display. It published feed
sequence 1432 with zero held plays, retained the failed files under
`.retained-snapshot-fd01-35ac8e` and left the account source intact.
The operator then installed the recovered release for the scheduler and reader.
[Host receipts and offline recovery tests](PAPER_SNAPSHOT_RECOVERY_20261116.json).

### Recover the display

The operator completed this block on November 16. It builds the tested
image in a separate checkout. The candidate uses the same bound source and
reader identity as the existing publisher. It validates a fresh copy within
the original five-second budget. After that verified display is durable,
it retains the failed file and any SQLite companions under the private
directory named in its reply. The native account is mounted read-only.

```bash
(
  set -eu
  cd /opt/trade-bot-dashboard
  release=fd7ff0186690fc5192fb93f959087acbec28f74c
  git fetch origin slice2/robinhood-read-shadow
  git merge-base --is-ancestor HEAD "$release"
  git merge-base --is-ancestor "$release" FETCH_HEAD
  candidate=$(mktemp -d)
  git worktree add --detach "$candidate" "$release"
  trap 'git worktree remove "$candidate"' EXIT
  python3 "$candidate/scripts/connected-session-host.py" build
  python3 "$candidate/scripts/connected-session-host.py" recover-snapshot
)
```

Success returns `PUBLISHED`, the checkpoint, `source_modified: false` and
`retained_directory`. An already cleared directory returns a fresh verified
publication with `retained_directory: null`. If recovery fails, keep its
`reason` and `stage`. A copy or verification deadline preserves the original
pending file and prior completed display. If the last stage `RETAIN_PENDING`
is interrupted, the new verified display may already be present. A retry
continues moving the original files under the same publisher lock.

### Install after successful recovery

The operator completed this installation after `PUBLISHED`, outside the PAPER
session with the daily timer enabled. The block waits for the controller lock
before switching the detached checkout. The installer preserves the daily
record, account halt, saved review and limits. Tuesday gets its own
date-specific preparation and launch review.

```bash
(
  set -eu
  cd /opt/trade-bot-dashboard
  release=fd7ff0186690fc5192fb93f959087acbec28f74c
  prior=$(git rev-parse HEAD)
  git merge-base --is-ancestor "$prior" "$release"
  changes=$(git status --porcelain)
  test -z "$changes"
  timer=trade-bot-paper-daily.timer
  systemctl is-active --quiet "$timer"
  trap 'systemctl start "$timer"' EXIT
  systemctl stop "$timer"
  flock -w 120 /var/lib/trade-bot-paper-daily/controller.lock true
  state=$(systemctl show -p ActiveState --value trade-bot-paper-daily.service)
  case "$state" in
    inactive|failed) ;;
    *) echo "Controller is still busy. Retry installation after it finishes."; exit 1 ;;
  esac
  active=$(docker ps --filter label=trade-bot.connected-session-v1 --format '{{.Names}}')
  test -z "$active" || { echo "A PAPER worker is running."; exit 1; }
  git switch --detach "$release"
  if ! python3 scripts/paper-daily.py install; then
    git switch --detach "$prior"
    python3 scripts/paper-daily.py install
    exit 1
  fi
  python3 scripts/connected-dashboard-host.py update-reader --snapshot-name connected-price-options-v1
)
```

The host returned `DAILY_SCHEDULE_INSTALLED` and `DASHBOARD_READER_UPDATED`
for `fd7ff01`. The final timer check returned `active`.
Monday's run ID and retry count remain part of its finished calendar date.

## November 14 installation history

On November 14 the host installed `39d8e48`, enabled the daily schedule and
updated the dashboard reader. Its diagnostic catalog capture succeeded. The
scheduler set Monday's preparation for 9:00 a.m. ET and launch review for
10:00 a.m. ET.
[Deployment receipt](PAPER_HOST_DEPLOYMENT_20261114.json).

## November 11 installation history

The operator completed the d2046f6 recovery installation on November 11,
including snapshot publication, the existing dashboard reader update and
`resume --after-read-timeout daily-20261110`. The final result was
`SCHEDULE_RESUMED`. [PAPER_HOST_DEPLOYMENT_20261111.json](PAPER_HOST_DEPLOYMENT_20261111.json)
records the exact image, checkpoint and receipt. Do not repeat that completed
deployment or resume.

For November 11, preparation is scheduled for **9:00 a.m.**, startup for
**10:00 a.m.**, and close for **4:00 p.m.**, all America/New_York. No worker start
has yet been reported. The saved-timeout review allows the next eligible launch
against the original owner state; startup still requires fresh native
reconciliation and valid data. The old failed runtime history is not erased.

The dashboard reader now includes the independent operating-status implementation.
A saved prior failure is not evidence that today's worker has started or failed.
Controller freshness, worker state and account freshness remain separate.
No manual market capture or launch is required by this receipt.

The current work order is [DELIVERY_PLAN.md](DELIVERY_PLAN.md). The recovered offline
system-check code is published as `29ef510`; [PAPER_SYSTEM_CHECK.md](PAPER_SYSTEM_CHECK.md)
records its proof and limits. It has not been deployed; the existing confirmed
host installation and scheduled session remain unchanged.

## Completed November 11 recovery procedure — reference only

The operator has already completed this block for d2046f6. Retain it as historical
reference; a new failure requires its own evidence and review. Do not run it again
as a routine daily step.

The original stopped-host upgrade block follows. The reader update upgrades the already
connected dashboard, retaining the current login, binding, listener and previous
reader container. The final command reviews this specific saved runtime timeout
and authorizes one subsequent daily launch from the exact current owner revision.
It verifies flat accounting and the saved worker's identity and exit. A later
owner change invalidates the review. Initial runtime startup still requires a
fresh native venue reconciliation and valid market input before resuming entries.

```bash
cd /opt/trade-bot-dashboard &&
git fetch origin slice2/robinhood-read-shadow &&
release=TESTED_RELEASE_SHA &&
git merge-base --is-ancestor HEAD "$release" &&
git merge-base --is-ancestor "$release" FETCH_HEAD &&
git switch --detach "$release" &&
python3 scripts/paper-daily.py install &&
python3 scripts/connected-session-host.py snapshot &&
python3 scripts/connected-dashboard-host.py update-reader --snapshot-name connected-price-options-v1 &&
python3 scripts/paper-daily.py resume --after-read-timeout daily-20261110
```

Omit the final line if you intentionally want the daily schedule paused. Existing
same-day launch guards still apply. Other failures, exposure, uncertain orders,
unknown model cost or intervening operator halts require their own review.

## Dashboard operating status

The authenticated page shows the controller state, its last check time, the last
worker result and duration, local process failures, feed/heartbeat health at the
report cutoff, scan totals, fills and retained strategy blockers. The daily
controller publishes this small status file every tick independently of the worker
and the SQLite account publisher. It has an explicit 180-second freshness bound.
Lost controller updates or browser requests display unknown health. An unavailable
account snapshot displays unknown positions and balances while keeping operating
status accessible. The account APIs continue rejecting invalid or stale snapshots.

The ordinary report also retains the saved local subprocess phase and fixed child
stages. No new market read is needed to inspect Tuesday's error.

## Remaining evidence

- Tuesday's saved terminal traceback establishes a local runtime timeout. The
  supplied text does not establish which subprocess stage consumed the deadline.
- Repeated Robinhood capture failures and full-session completion require host
  observation after the contention fixes.
- A connected simulated entry, exit and complete round trip remain unobserved.
- Scope needs original usable index history and exact reviewed session/contract
  bindings. Swing input blockers remain tied to original history and target
  validation. The eight-contract capacity and original-data checks still apply.

Use the existing `local-simulation` account and population
`connected-simulation-1000-v1`: $1,000 initial virtual capital, maximum two plays,
$1/day and $5 total AI spending. Robinhood supplies read-only data; execution is
local simulation. LIVE remains disabled. Balances, positions, journals, halts and
enrollment persist. No additional data provider or broker account is needed.

## Install once

Use the tested commit supplied with the release. With connected workers stopped:

```bash
cd /opt/trade-bot-dashboard &&
git fetch origin slice2/robinhood-read-shadow &&
git merge-base --is-ancestor HEAD TESTED_RELEASE_SHA &&
git switch --detach TESTED_RELEASE_SHA &&
python3 scripts/paper-daily.py install
```

The dashboard checkout is a detached worktree; do not switch it to a branch already
owned by `/opt/trade-bot`. Installation builds this pinned image only if missing,
checks the existing owner read-only, and enables `trade-bot-paper-daily.timer`.
It does not reset/re-enroll the owner or activate the dashboard again. Upgrades
preserve a previous pause. Neither the timer nor its worker depends on SSH staying
connected. There is no automatic Git pull, rebuild or unbounded worker restart.
Changing the checkout/image requires reinstalling the schedule explicitly.

On an eligible exchange session with the schedule enabled, the controller performs these steps automatically:

1. At 09:00 New York, reuse an exact already-enrolled session. If Monday's prior
   preparation completed, it is adopted from the validated enrollment chain even
   if its local receipt was lost. No recapture or second enrollment occurs.
2. Otherwise capture original SPY/QQQ same-day contracts and a separate weekly
   Swing expiry at least seven days out. For November 9 that is November 20.
   Original chain evidence must advertise those actual contracts. Review and
   enroll the new date-specific catalog through the existing exact-hash APIs.
   Completed capture stages persist. Failed/interrupted preparation stages share
   a maximum of three reserved attempts per date, surviving reboot.
3. Before the open, attempt Swing source preparation once if enrolled. Reuse valid
   retained sources. An original-data failure stays recorded and does not prevent
   independent DEGEN operation. No repeated overnight collection of interpolated
   evidence, fabricated bars or changed source clocks.
4. At 10:00 New York (open plus 30 minutes), launch one bounded PAPER worker after
   six completed five-minute bars can exist. It runs until approximately two minutes
   before exchange close. The controller also enforces the close using the exact
   container identity. Exchange holidays, DST and early closes come from the pinned
   exchange calendar. Installing late can start the remaining session only if at
   least fifteen minutes remain. A manual run already started that day prevents
   another automatic run.
5. Save current reports each minute and the final report automatically. A healthy
   worker can still be waiting for a setup or blocked by missing original inputs.
   The two reviewed flat-feed recoveries are the entire per-run allowance.

The timer performs no market capture outside the preparation/run window. It never
reuses Friday's preparation on Monday. Visible option chains after hours do not
extend this bot's enrolled regular-session policy.

## Status and persistent stop

These are optional controls, not daily launch instructions:

```bash
python3 scripts/paper-daily.py status
python3 scripts/paper-daily.py pause
```

`pause` records a durable pause first and stops the exact managed worker. If a
capture/review/launch is in progress, it returns `PAUSE_REQUESTED`; the controller
checks the pause before its next mutation and drains any newly started worker
before releasing its lock. The next one-minute tick enforces a pause arriving after
that final check or across a crash. A restarted timer also honors it. Disabling the timer
alone does not stop a running Docker worker; use `pause`.

Explicit `python3 scripts/paper-daily.py resume` requires a normally stopped, flat
owner with no unresolved orders/costs or other halt. It clears the controller's
attention latch and pause, but never clears native halts or replays a same-day
launch. Unresolved native failures must first be reviewed/reconciled through the
existing owner controls. Do not delete the daily state to force a retry.

Status includes the exchange schedule, update time, day/run ID and reported
operation. States distinguish `WAITING_NEXT_SESSION`, `PREPARING`, `READY`,
`RUNNING`, `WAITING_FOR_SETUP`, `MISSING_INPUTS`, `STOPPING`, `STOPPED`, `FAILED`
and `PAUSED`. The update time matters: saved state alone is not a live heartbeat.
The systemd journal (`journalctl -u trade-bot-paper-daily.service`) retains exact
structured step diagnostics. Private daily state and per-run JSON reports live in
`/var/lib/trade-bot-paper-daily`; native journals and enrollment remain in their
existing directories. Reports retain the exact family blockers, original quote
ages, fills, decisions, costs and collection failures.

A persisted launch intent precedes Docker startup. After a crash the controller
adopts the exact existing container; an uncertain missing container or failed run
requires review rather than another launch. It does not interfere with an existing
manual worker. Holdings, unresolved orders, unknown costs, exhausted budgets and
non-stop halts block automatic new-day preparation/start. Automatic resumption is
restricted to the existing normal stop and the two native flat-feed recoveries.

## Working branch changes after installation

The November 9 host ran f6493b5 with the following entry and supervision changes.

- A confirmed shared shortlist uses one scan evaluation time for the original
  account projection, option admission and stock alternatives. The account
  snapshot and market quotes retain their original clocks. The paid model gate
  checks the actual time after saving the request. Expiry before that gate
  produces a HOLD with zero model attempts.
- After a paid DEGEN or Swing option selection, the mixed runtime checks the
  selected contract and underlying from its latest completed delivery. The
  decision records the feed sequence used. If the updated evidence qualifies,
  the shared reservation respects the reviewed quantity, premium and loss
  limits. Fills still require a subsequent executable quote.

- The scheduler reserves a maximum of three launch-review attempts for the date.
  It checks the same owner state and image at final review and records its dispatch
  marker immediately before the run command. After a possible dispatch it checks
  the original container identity. A temporary Docker read failure keeps the run
  under supervision. A later appearance of that worker can be adopted without
  another launch. On the tested branch a created or restarting worker reports
  `STARTING`. A paused, removing or unrecognized Docker state reports the worker
  condition and remains under inspection. Only an exited or dead container can
  finish the day. An abnormal exit is reported as failed on that tick. Final
  reports compare Docker's original start and finish times with the duration
  in the worker command. An early clean exit or an unverifiable duration
  requires review. A dead worker without a valid time window yields a failure
  receipt with unknown run metrics.
- Portfolio reconciliation journals each recovered unknown attempt once and
  reports how many remain unresolved. Native broker order and client identities
  must be unique. Run reports expose matched attempts and unresolved attempts at
  the last applicable snapshot.
- Scope setup checks retained Robinhood chain and instrument rows and uses
  published Cboe terms for the standard product. It can inspect a retained SPX
  input probe independently of the selected contract. The October 29 record has
  78 session bars and zero confirmed original bars.

The optional Robinhood order-history reader is for investigating a known brokerage
order ID. The scheduled simulator needs no brokerage history capture or separate
account. [Order recovery instructions](OPTIONS_EXECUTION.md#robinhood-option-order-history)

## Current evidence and remaining requirements

The confirmed host release is `f6493b5afa670d4f9ceb16e25a70376de30da118`,
image `sha256:7682c2d6c4c239323f62237531efd01fddb383c58b70694ba7ae797ee9b81df6`.
At installation the owner was normally stopped at revision 3259, generation 13,
feed sequence 678. The November 9 policy SHA is
`391f87e90a639f4923d72b632e925b81f1e7c8a25af67ed6cf6fe08e6757f149`.
The installer found no start blockers. That enrollment applied only to November 9.

The newer branch reporter can read the portfolio journals written by that release.
Its JSON `run_execution` and text summary count entry and exit fills in the
container's time window. A completed round trip requires the same play to have
its first entry and its full sale inside that window. Fully sold positions
carried into the run appear separately. This measures recorded buy/sell fills.
Exercise, expiry and cash settlement require their own native receipt evidence.
Older journals missing the necessary bindings show unavailable run counts.
The host begins saving the new summary automatically upon a future scheduled-release
upgrade. The installed timer already saves the evidence needed for retrospective
reporting.

Run `paper-1106-151939-cd07ea` ended normally at 10:31 New York: 23 delivered packets,
five read timeouts, two recoveries, zero fills and zero model cost. Two completed
cycle records contained one actual scan: twelve WATCHING setups, none confirmed.
Original inventory age was 26.297 seconds for SPY and 25.798 for QQQ against the
strict <10-second admission limit. Fresh terminal heartbeat/feed did not establish
fresh inventory at selection.

The preceding timing repair is included: completed native protection can be reused
only for the exact frame/owner epoch while its original account snapshot remains
fresh. Changed/stale state and a second entry require fresh protection. Intraday
history is read before executable books. Failed history can deliver only validated
MARKET protection; it cannot fabricate a CYCLE. Quote, account, setup and spending
validation remain unchanged. See [entry timing proof](PAPER_ENTRY_TIMING_PROOF.json)
and [daily controller proof](PAPER_DAILY_AUTOMATION_PROOF.json).

| Area | Implemented and tested offline | Still requires host/provider evidence |
| --- | --- | --- |
| Daily operation | Calendar-driven preparation, exact enrollment adoption, one launch per date, persistent retry/stop state, reporting and systemd installation. | First automatic launch observed November 9. The worker exited early. A complete scheduled session with sustained feed coverage remains unverified. |
| DEGEN | Shared simulation, collection/scanning, two entries, later fills, protective exits and restart/accounting fixtures; prior timing repair included. | Authentic qualifying setup, accepted original quotes, model response and a complete connected simulated lifecycle. |
| Swing | Native source preparation and execution; invalid originals remain isolated. | Valid original daily history. Saved interpolated bars cannot establish readiness. |
| Scope | Collector/watch/admission/owned-play management and synthetic lifecycle coverage exist. | Usable original SPX history and exact reviewed SPXW contract/session/pattern bindings, with a reserved catalog slot. |

The catalog capacity remains eight. Automatic catalog preparation refuses to drop
reviewed Scope, company-earnings or carry bindings silently; an exact reviewed
session must be supplied for such configurations. It never substitutes SPY for
SPX or invents contract terms. Model spend, entry frequency and fills are not
scheduled targets: entries require real confirmed setups and all native gates.
