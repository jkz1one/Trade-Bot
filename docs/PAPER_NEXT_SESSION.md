# Prepare and run the next PAPER session

This workflow keeps the existing `local-simulation` account, its $1,000 starting
capital, two-play ceiling, journals and $1/day AI budget. It uses Robinhood reads
and local simulated orders. It never enables LIVE or resets the account.

The current software has passed synthetic two-play entry, fill, independent exit,
restart and accounting tests using the production profile. The actual host has
completed a ten-minute session and accepted live packets, but no connected model
call or simulated fill has yet been observed. A successful preparation is not
market acceptance or a promise that a setup will qualify.

## Recover the existing Monday preparation

The actual `monday-ready` host attempt enrolled the November 2 policy successfully
(`7242ac53faf4977e5430c3c49ea124df901d6a660703e3380bcdfc80e718c236`).
Its receipt remains under
`/etc/trade-bot-connected/sessions/2026-11-02-monday-ready/prepared.json`.
The subsequent snapshot failed because the host helper always requested a new
directory even when its bound publication already existed. Do not repeat the
captures or enrollment. With the repaired release built, run:

```bash
python3 scripts/connected-session-host.py snapshot &&
python3 scripts/connected-session-host.py preopen-report --sequence 132 &&
python3 scripts/connected-dashboard-host.py switch \
  --snapshot-name connected-price-options-v1
```

Snapshot refresh now uses the existing publisher, preserving its binding, receipt
checks, atomic replacement and retained failure files. The saved-history report
revalidates attempt 132 offline, at its original capture time and enrolled policy,
and reports all four series independently. Missing source coverage includes exact
counts and up to eight missing/unexpected bar labels. It neither fetches again nor
installs history. `history_mapped: false` still requires original usable history;
the report succeeding is not Swing acceptance.

The reader permits old **halted STOPPED/FAILED records**, with their original
timestamps and existing stale-account/last-available-records notice. Running and
unhalted snapshots still require publication within 30 seconds; future snapshots
are always rejected. This permits viewing a stopped account over the weekend
without claiming current feed or valuation.

## Before Monday, November 2, 2026

Deploy the reviewed commit and build **once**, using the pinned command supplied
with the release. These commands require that clean checkout and its built image.
Existing connected runtime sessions must be stopped.

Prepare the November 2 DEGEN catalog and a November 13 Swing catalog together:

```bash
cd /opt/trade-bot-dashboard &&
python3 scripts/paper-session-start.py \
  --capture-contracts \
  --target-session 2026-11-02 \
  --swing-expiration 2026-11-13 \
  --observed-swing-history \
  --prepare-only \
  --run-id monday-ready
```

This performs two bounded catalog captures (eight provider tool calls each), keeps
both original evidence directories, prepares/reviews/enrolls the combined policy,
and publishes the current real simulated-account snapshot. No model or trading
worker starts. Weekend quotes are retained catalog evidence; Monday's runtime
must independently accept fresh inputs. The chosen strikes are based on the
observed underlying midpoint; spread, affordability and setup gates still apply.

The final `SESSION_PREPARED` result identifies:
`/etc/trade-bot-connected/sessions/2026-11-02-monday-ready`.
The `prepared.json` receipt is saved immediately after enrollment. If snapshot
publication subsequently fails, preserve this directory; starting the prepared
session republishes the snapshot without trying to enroll the policy twice.
Do not repeat preparation with the same ID or delete old evidence.

Collect and bind original pre-open Swing history separately:

```bash
python3 scripts/connected-session-host.py preopen-inputs \
  --target-session 2026-11-02
```

This takes the native owner lock through a read-only descriptor and mounts the
entire owner read-only. Only the collector evidence and read-auth state are
writable; model secrets and dashboard exports are not mounted. It makes at most
one bounded native collection attempt, respecting the existing quota. A repeat
with retained history verifies the original binding without new provider reads.

`PREOPEN_INPUTS_PREPARED` means the source binding was prepared, not that a trade
was admitted. `PREOPEN_INPUTS_BLOCKED` retains the original attempt and identifies
the missing history/binding. Interpolated, missing, post-open or malformed bars
remain blocked. This is usable on the weekend after Friday's UTC daily date has
completed; no future time boundary is requested. The source must actually contain
the completed Friday daily bar and the full requested lookback.

Switch the public dashboard from its old frozen example to the real account:

```bash
python3 scripts/connected-dashboard-host.py switch \
  --snapshot-name connected-price-options-v1
```

This explicit switch prints its exact review and rechecks it before changing the
reader. It retains the old dashboard for rollback and verifies authentication,
accounting and the connected reader. It starts no collector, model or trader.
Until a market run publishes updates, the account correctly shows stopped state
and its recorded balance/positions. This command is for the first frozen-to-
connected switch; it does not silently replace an already connected reader.

## At Monday's open

The exchange calendar gives November 2 open as **9:30 a.m. New York / 14:30 UTC**
after the daylight-saving change. Launch the prepared session during regular
hours; setup evaluation needs completed bars, so an immediate fill is not expected:

```bash
cd /opt/trade-bot-dashboard &&
python3 scripts/paper-session-start.py \
  --prepared-session /etc/trade-bot-connected/sessions/2026-11-02-monday-ready \
  --seconds 600 \
  --wait
```

The run ID is generated uniquely. The launcher refreshes the snapshot, obtains a
fresh exact run review, verifies the effective policy matches the preparation
receipt, and starts a bounded run with reviewed flat recovery. It prints the
saved decisions after the container finishes, including when the container fails.
No review hash needs hand-copying. No run is automatically resumed or retried.
An interrupted terminal does not remove the bounded container or its evidence.

The resulting report distinguishes accepted feed, reviewed entry recovery,
completed cycles, setup/contract rejection reasons, cumulative actual portfolio
fills and bounded runtime/collector failure diagnostics. `WATCHING` or a specific
risk/contract rejection is a strategy result; `FAILED`, no accepted input, or a
missing required source is a remaining operational/input problem.

For an already-created run, inspect it rather than launching its ID again:

```text
python3 scripts/connected-session-host.py status --run-id RETURNED_RUN_ID
python3 scripts/paper-session-report.py --run-id RETURNED_RUN_ID
```

The report requires a finished container. Existing explicit `review-run` / `run`,
`review-session` / `enroll-session`, and dashboard `review` / `activate` commands
remain available for manual review.

## Remaining evidence boundaries

- DEGEN: the saved replay now passes completed-bar history freshness; its two
  recorded cycles did not qualify for entry. Monday must validate the corrected
  path with current quotes and, when an eligible setup exists, the real model
  service and simulated fill lifecycle.
- Swing: original complete pre-open histories and the derived session binding
  must be accepted. This variant uses price/options evidence, not a fabricated
  catalyst clearance. A Nov13 contract catalog alone does not supply history.
- Scope: the saved SPX histories contained interpolated or unclassified bars.
  An original usable history and reviewed exact SPXW contract/session/watch binding
  are still required. A fresh SPX reference quote alone does not satisfy them.
  No ETF is substituted for SPXW and no contract terms are invented.
- Stock trades: the populated book probe is evidence, not installed executable
  size/catalog wiring. Its blockers are separate from the option simulation path.

If valid Scope evidence becomes available, preparation accepts `--scope-binding`
with the original reviewed JSON and a catalog leaving one of the eight candidate
slots for Scope. The full eight-contract DEGEN/Swing catalog above cannot add that
extra slot unchanged; no family is silently dropped. Existing retained captures can be supplied with
`--capture-directory` and `--swing-capture-directory` instead of making new reads.
The workflow does not weaken gates to force a demonstration trade.
