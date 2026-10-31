# Current data proof and dashboard price formatting

## Latest acceptance: regular session and successful refresh

The operator subsequently deployed a653cc7 successfully: all 283 application
files match, health and authentication pass, frozen V3 still has two fills, and
the price-formatting change is installed. before-price-format is now consumed.
Do not rerun the historical refresh instructions below.

The 09:33 EDT run in /root/trade-bot-market-proof-01Ccjk reports all three samples
fresh and advancing for both equity and option subjects. The supplied sample-3
raw file independently matches hash
12922ab55470cdfb6768b926227af81beedce693aa206520a6cd8e154f2bce29 and validates
the exact capture plan, pinned input/output schemas, identities, nonfuture clocks,
positive uncrossed books and regular-session time. SPY/QQQ underlyings normalize;
both option responses contain sizes, volume/open interest and finite Greeks.
See [REGULAR_SESSION_QUOTE_PROOF.json](REGULAR_SESSION_QUOTE_PROOF.json).

The uploaded raw file is one of the three samples; full sequence advancement is
still evidence from the operator's report. No further bounded quote capture is
needed merely to repeat this accepted result. This is a historical observation at
09:33, not perpetual permission to call later quotes fresh. The response has no
equity sizes, explicit entitlement or full exercise/deliverable/settlement terms.
No fields are filled from guesses and no connected simulator is activated.

## Earlier attempt (superseded deployment state)

October 26 host update: the first bounded premarket capture completed all three
samples without errors. SPY/QQQ equity clocks advanced and latest quotes were
1.691/0.691 seconds old. Options retained Friday timestamps. This establishes
fresh premarket equity observations, not regular-session option or trading
acceptance. The operator then attempted the dceb64e display refresh: all 283 files
and the fixture verified, but six health probes failed. The helper restored the
previous acabf4a dashboard. No successful rounding deployment is claimed.

The corrected helper waits up to approximately 90 seconds while requiring a
running, nonrestarting container. It aborts on exit, restart or OOM and preserves
bounded startup logs and sanitized container state before rollback. The actual
reason for the earlier startup failure is unknown because its failed container
was removed without preserving logs. Slow startup is a possibility, not a diagnosis.
After checking out the corrected release supplied in chat, retry only
`refresh ui-review-v3`; never rerun prepare/activate. The previous rollback was
renamed back to trade-bot-dashboard, so the helper can safely check the expected
acabf4a image and unused before-price-format name again.

Goal: use real incoming market data to simulate trades with virtual money inside
this bot and show them on the existing dashboard. No separate brokerage account
is needed. The collector, simulator and dashboard still need connected acceptance
before any unattended run can be claimed. This release provides a useful bounded
next step without pretending a frozen demonstration is current trading.

## Confirmed host state

The operator supplied successful acabf4a deployment output: 283 installed files
match, two native simulated fills, authenticated FROZEN_OFFLINE_UI_FIXTURE and
health OK. Container ID:
21a1f38862409cdad78ba6cc70fa7203aba4d9022ac3ba358a85084359632f30.
The previous d2092f1 dashboard is retained as before-two-play. V1, V2 and V3 fixtures
remain preserved. Do not rerun V3 prepare/activate. No collector/runtime/model
worker started. The screenshot identifies trailing stop-price padding such as
599.940000000000; it does not prove full browser or connected-feed acceptance.

## Run the bounded data check first

After fetching and checking out the exact published release supplied in chat:

```bash
bash scripts/market-data-proof-host.sh
```

The helper reuses the already installed acabf4a image and mounts the new proof
script read-only. No image build, dashboard restart, strategy enrollment or
broker order or model call is performed. It makes three captures, separated by 20
seconds, each with a 30-second capture deadline. Each capture rediscovers the
pinned schemas, then requests SPY/QQQ equity quotes and the two exact October 26
option UUIDs from accepted discovery. Maximum: six market read calls and three
tool-discovery requests. No chain scan, retry loop or automatic pagination.
Outside October 26 the expired fixed option subjects are omitted explicitly.
These are diagnostic samples, not a complete universe or strategy shortlist.

It uses the existing private /var/lib/trade-bot-read-auth through the established
capture CLI. Only that process can perform ordinary OAuth refresh under the
existing lock. The helper does not print, copy or export credentials and no
model key is mounted. Output goes to a new private
/root/trade-bot-market-proof-XXXXXX directory. Old output is never overwritten.

Share report.json or its terminal output. It records original source times,
receipt times, ages at capture, bid/ask sizes, source-clock advancement/regression,
regular-session status, and hashes of retained samples. Keep sample-*.json and
plan-*.json for follow-up validation. On auth/capture failure it stops immediately
and records the bounded failure classification. The capture summaries contain
existing sanitized error codes, never raw OAuth responses.

FRESH_ADVANCING_QUOTES requires all three samples to have complete supported
subjects, positive uncrossed books, nonfuture source clocks within 30 seconds of
receipt, and monotonic advancing source clocks. The 30-second threshold is a
diagnostic criterion, not a replacement for engine admission limits. Regular
session proof additionally requires all samples and their receipts to be inside
the exchange-calendar session. Premarket results remain useful read evidence;
stale option timestamps before the regular session do not prove a broken feed.
Prices need not change for source timestamps to advance.

This does not certify entitlement, complete option terms, stock executable sizes,
SPX/Scope coverage, long-duration continuity, simulated fills or runtime recovery.
Those restrictions remain explicit, and paper_trading_ready stays false. A failed
or stale quote check is retained evidence, not permission to invent a fill.

## Apply the display fix

After the data check, on the same clean published checkout:

```bash
bash scripts/dashboard-review-host.sh refresh ui-review-v3
```

This expects the confirmed acabf4a running image and unused
trade-bot-dashboard-before-price-format rollback name. It builds the release,
verifies installed bytes and the existing V3 journal, then replaces only the
dashboard reader. V3 is reused read-only. No new simulated fills are generated.
The previous before-two-play rollback is preserved. On success, do not rerun the
refresh with its consumed rollback name.

Stop/target/rail/order prices now retain significant fractional precision with at
least two decimal places and no redundant trailing zeros. Money totals retain
their existing two-decimal display. Stored exact quantities, stops, prices and
accounting are unchanged. Full raw entry/order JSON remains available for audit.

Installed-wheel validation and artifact hashes are recorded in
[MARKET_DATA_PROOF_VALIDATION.json](MARKET_DATA_PROOF_VALIDATION.json). Actual
provider reads and Docker execution of these new helpers require operator output;
none were performed from the development workspace.
