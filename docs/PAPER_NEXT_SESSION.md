# Daily PAPER operation

The host's last confirmed run is stopped, with **zero connected fills**. Manual
bounded launch helpers existed; a persistent daily controller did not. The new
`paper-daily.py` installs that controller. Installation on the host, real quote
latency and a connected entry-to-exit lifecycle are still unverified.

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

On the next exchange session, normally Monday November 9 after the November 6
close, the controller performs these steps automatically:

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

## Current evidence and remaining requirements

Last confirmed host build: `840255127c8d895fd6bc22dab9410bb7f6ec48a0`, image
`sha256:3b5a3344fc30b4d5450aa719450ef79554845063d24e4a705f862fa8f5e13bf6`.
The operator subsequently checked out `b2436f3` for reporting; no later successful
host build/start output has been supplied. The November 6 prepared directory is
`/etc/trade-bot-connected/sessions/2026-11-06-friday-ready`; it is expired after
that session and must not be reused. A November 9 preparation was suggested but
its completion has not been confirmed.

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
| Daily operation | Calendar-driven preparation, exact enrollment adoption, one launch per date, persistent retry/stop state, reporting and systemd installation. | One host installation, an automatically launched session and real sustained read latency. |
| DEGEN | Shared simulation, collection/scanning, two entries, later fills, protective exits and restart/accounting fixtures; prior timing repair included. | Authentic qualifying setup, accepted original quotes, model response and a complete connected simulated lifecycle. |
| Swing | Native source preparation and execution; invalid originals remain isolated. | Valid original daily history. Saved interpolated bars cannot establish readiness. |
| Scope | Collector/watch/admission/owned-play management and synthetic lifecycle coverage exist. | Usable original SPX history and exact reviewed SPXW contract/session/pattern bindings, with a reserved catalog slot. |

The catalog capacity remains eight. Automatic catalog preparation refuses to drop
reviewed Scope, company-earnings or carry bindings silently; an exact reviewed
session must be supplied for such configurations. It never substitutes SPY for
SPX or invents contract terms. Model spend, entry frequency and fills are not
scheduled targets: entries require real confirmed setups and all native gates.
