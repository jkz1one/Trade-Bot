# Daily PAPER operation

The host installed 7db7475, published the existing account snapshot and resumed
the daily schedule. The native journal measured 67,133,440 bytes and the display
27,361,280 bytes. Tuesday's daily-20261110 worker then failed after 802.3 of
21,475 planned seconds with a RUNTIME FixtureProcessTimeout. One scan completed,
one setup confirmed and the account recorded zero fills and zero AI spend.

## Install and recover Tuesday's failed read

Use one stopped-host upgrade block. The reader update upgrades the already
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
