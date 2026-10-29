# Robinhood observed-quote simulation

This opt-in PAPER mode uses actual observed Robinhood prices, timestamps, sizes,
Greeks and completed intraday bars while keeping `entitlement: UNKNOWN` in every
receipt. `simulation_basis: ROBINHOOD_OBSERVED_V1` is an explicit assumption for
local simulation, not proof of real-time entitlement, live execution quality, or
actual broker fills. DELAYED/INDICATIVE evidence is not promoted. Defaults retain
the previous entitlement requirement and serialized hashes.

Supported market records alone may carry the basis. News, catalyst, Scope context
and original Swing history do not gain eligibility. Existing freshness, source,
identity, spread, observed size, metadata, account, protection and risk checks
remain in force. Stock sizes absent from the feed remain absent and cannot fill.
The native option/portfolio limits accept only PAPER mode; LIVE is not enabled.

`simulation_catalog` reads retained, schema-verified contract and quote captures
and proposes up to six same-day SPY/QQQ contracts. Provider IDs, strike, right,
expiry date, multiplier, ticks and active tradability remain observed. Missing
terms are explicitly labeled `simulation_terms: STANDARD_ETF_INTRADAY_V1`:
standard unadjusted 100-share USD American physical ETF contracts. The session
close and next session open are conservative simulator lifecycle clocks, not
claims about exact legal expiry or settlement timestamps. Broker sellout is not
used as exchange close. The report states `broker_terms_verified: false`.
Metadata-complete means the simulated instrument model is populated.

General standard-contract references, checked 2026-10-28 (they do not verify each
captured contract or its adjustment history):
- https://www.theocc.com/clearance-and-settlement/clearing/etf-options
- https://www.cboe.com/tradable_products/sp_500/spx_weekly_options/specifications

Session policy enrollment is append-only. It preserves the owner/account,
transport and strategy settings. A current-day enrollment additionally refuses
held exposure or prior collector attempts that day, preventing reinterpretation
of previously collected data. Closed/past sessions, duplicate enrollments and
previously bound history remain refused. Existing immutable verified catalogs
can still be used without simulated terms.

`--resume-flat` is part of the exact host run review. It only starts from a
reviewed runtime stop/failure, checks the owner revision under its lease, waits
for a newly delivered fresh packet to be accepted by the native runtime, then
uses native recovery guards. It refuses held positions, unresolved active orders,
unknown costs and unrelated halts. A stale startup feed may have replaced the
previous runtime-stop reason; it can be cleared only after this fresh receipt.
Default runs still never resume automatically. End-of-run stop halts entry again.

## Host operation

Build the pinned release using `connected-session-host.py build`. Capture a new
session using the same Robinhood connection:

```sh
bash scripts/paper-contract-capture-host.sh 2026-10-29
```

The helper prints its private evidence directory. It makes eight market-tool calls:
underlying quotes, two chain lookups, two exact-strike ticker lookups and three
option quote samples. One whole-dollar strike per symbol is rounded from the
observed bid/ask midpoint. This is a bounded candidate probe, not a complete chain
scan, price recommendation or guarantee of an eligible/affordable trade. Stale
after-hours prices remain labeled with their original clocks. Empty, paginated,
untradable or chain-mismatched results refuse; the saved captures remain intact.
No owner/account or model key is mounted. It does not enroll or start a session.

On the target date, before the simulation cutoff, pass the printed directory to
`paper-session-start.py --capture-directory DIR --target-session YYYY-MM-DD
--run-id NEW-ID --seconds 600`. Current runtime data must independently pass
freshness and strategy/risk checks. A future-session policy can also be prepared
and reviewed through the existing `prepare-session` / `review-session` operations;
the one-command starter deliberately requires the target date itself.

Host evidence from October 28 established that ticker-only discovery returned
active/tradable October 29 contracts, while earlier chain-ID plus explicit
state/tradability requests were empty. The exact offending filter is unproven.
The catalog reader now supports ticker-bound exact-strike receipts while checking
the returned states, identities, expiry and complete quote coverage. Neither the
100-row first page nor expired October 28 captures should be enrolled directly.

Historical example (October 28 only): for the retained
October 27 capture directory with October 28 contracts, on October 28 only:

```sh
python3 scripts/paper-session-start.py \
  --capture-directory /root/trade-bot-options-proof-l2rQht \
  --target-session 2026-10-28 \
  --run-id paper-observed-1 --seconds 600
```

This prints each concrete review, passes its exact hash to enrollment/launch, and
starts one bounded run against the existing $1,000 account. No separate brokerage
account or additional provider is involved. It preserves the existing two-play
limit and $1/day AI budget. It does not replace the public frozen dashboard.

Keep the output and inspect:

```sh
python3 scripts/connected-session-host.py status --run-id paper-observed-1
docker logs --tail 100 trade-bot-connected-paper-observed-1
```

`degen_option_configuration_ready` means configuration can support that route;
`trading_ready: false` in a configuration/launch review remains intentional until
current runtime acceptance is inspected. Other families' and stocks' blockers
remain visible. No eligible setup means HOLD, not a forced fake trade. A stopped
container does not automatically restart. No current host acceptance has been
claimed from the offline tests.

Future dates require original captures for that session, not reusing expired
October 28 contracts. Repeated session preparation is create-only; preserve
existing evidence rather than deleting it to retry.

Validation completed locally: the broad regression run passed 483 tests and
identified one outdated test that treated the current session as a past date.
That assertion was corrected to an actual past date; all 33 rollover tests then
passed, including refusal to reinterpret current-day collection. The focused
116-test catalog/observer/session group passed. After adding bounded end-of-run
activity reporting, the final 40-test native startup/host group passed. All 301
installed application files match source. These are offline tests, not proof of
current provider acceptance. End-of-run logs now include session_activity counts
for delivered packets, completed cycles, simulated orders, model calls and
reviewed entry resumes.
