# Daily PAPER operation

Use the existing `local-simulation` account and population
`connected-simulation-1000-v1`: $1,000 initial virtual capital, maximum two plays,
$1/day and $5 total AI spending. Balances, positions, journals, halts and enrollment
persist. Robinhood supplies read-only data; execution is local simulation. LIVE
remains disabled. No separate broker paper account is used.

## Current November 3 preparation

Already enrolled:
`/etc/trade-bot-connected/sessions/2026-11-03-tuesday-ready`.
Policy SHA: `8136af394ef61ac8546010d7d69811110f417b7b800a3b7191535e13688c4f51`.
The last operator-reported owner was revision 1032, generation 8, feed 166,
STOPPED with `OPTION_RUNTIME_STOPPED` and zero fills. No Tuesday worker was reported.
The connected dashboard is already active; do not switch it again.

Attempts 168–170 establish the original daily-history blocker. Attempt 168 had
54 mapped hourly bars per SPY/QQQ but both November 2 daily bars were interpolated.
169 independently confirmed the SPY daily blocker; 170 failed SOURCE_CLOCK_CHECK
and independently returned INTERPOLATED_BAR. The quote-clock recovery is deployed
in dfe3bf0. Replaying these attempts, rebuilding, or repeating overnight collection
cannot make their daily bars original. The required input is valid original daily
history. DEGEN can run independently while Swing remains blocked.

## Deploy once, with connected workers stopped

Use the tested release SHA supplied with the release, on a clean working branch:

```bash
cd /opt/trade-bot-dashboard &&
git fetch origin slice2/robinhood-read-shadow &&
git switch slice2/robinhood-read-shadow &&
git merge --ff-only TESTED_RELEASE_SHA &&
python3 scripts/connected-session-host.py build
```

Replace `TESTED_RELEASE_SHA` with the supplied full SHA. This deliberately refuses
a divergent checkout rather than discarding newer work. Do not reset, clean,
re-enroll, recapture contracts or recreate the account. A build does not start a
worker or refresh provider data. The new image is used on the next explicit run.

After **10:00 a.m. New York on November 3**, the pending ten-minute check remains:

```bash
cd /opt/trade-bot-dashboard &&
python3 scripts/paper-session-start.py \
  --prepared-session /etc/trade-bot-connected/sessions/2026-11-03-tuesday-ready \
  --seconds 600 --wait
```

DEGEN requires six completed five-minute bars; time alone does not prove that the
provider delivered them. The launcher refreshes the snapshot, verifies the exact
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
| MISSING_INPUTS | Missing/stale/future heartbeat or feed, incomplete history/quotes, or a retained entry halt. Read the reasons and family issues. |
| STOPPED | Container ended successfully or the current native worker is stopping/stopped. |
| FAILED | Container exited nonzero or native runtime recorded FAILED. |

Scope/Swing input issues are separate from DEGEN's decision. The report distinguishes
the latest collected packet from the packet actually accepted by the native owner.
It preserves original timestamps and frozen freshness bounds, shows the latest
five detailed decisions and 25 cycle records, and explicitly counts omitted older
records. Account-total fills are cumulative, not new fills attributed to this run.
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
scheduler, automatic restart, daily enrollment or automatic resume loop.

## Remaining work and evidence

| Area | Implemented / offline evidence | Remaining requirement |
| --- | --- | --- |
| Shared owner / DEGEN | Production-profile raw collection, scanning, two paid entries, later fills, independent exits, restart and accounting fixtures. | Authentic qualifying setup, real model response and complete connected simulated lifecycle. No connected fill has been observed. |
| Swing | Source preparation/recovery and native shared scanning/execution fixtures; missing family remains isolated. | Valid original daily history and complete connected lifecycle. Saved interpolated bars remain rejected. |
| Scope | Collector-to-native watch routing corrected; native sampled arming, exact paid admission, later-quote fill, restart and exit regression. Owned plays stay out of new-entry admission while exact-play management remains available. Terminal watches cannot be revived by retained ARMED evidence. | Original usable SPX history, exact reviewed SPXW terms/session/pattern binding, a catalog with a reserved slot, and connected lifecycle. No SPY substitution or invented contract terms. |
| Scope timing | Original five-second admission and fresh advancing post-cost evidence remain enforced; late scripted responses retain their cost and cannot enter. | Post-cost delivery under the real continuous run-loop cadence remains unresolved. The favorable synthetic test drives explicit tick times; ten-second polling does not guarantee delivery inside five seconds. Valid history alone does not fix this integration limitation. |
| Daily operation | Unique bounded launches, current/saved status, exact stop, retained reports, unchanged recovery and budgets. | Longer host run, actual model timing and lifecycle evidence; daily preparations remain explicit. |

Scope bindings consume one of the **eight** candidate slots. The current eight
DEGEN/Swing contracts cannot silently gain a ninth contract or drop a family.
Scope execution/watch/management code already exists; missing reviewed evidence
and session configuration are distinct from the corrected delivery defect.

[Offline verification](PAPER_SCOPE_OPERATION_PROOF.json) records 237 passing
installed cases and an unresolved legacy five-second worker timeout in this
environment. A separate real SDK-worker test passed with the unchanged production
15-second process budget and 20-second management lease. Neither result establishes
real model latency or timely connected admission.
