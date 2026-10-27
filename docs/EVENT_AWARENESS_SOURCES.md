# Event source/access review — 2026-10-27

Existing code inspected first: `scope_context.py`, `scope_quality.py`, `swing.py`,
`swing_carry.py`, `swing_execution.py`, `simulation_profile.py`,
`continuous_feed.py`, native journals and dashboard publication. The existing
six-tool Robinhood read gateway does not provide broad catalyst/news clearance.
SPY/QQQ equities lack executable size/explicit entitlement in the reviewed capture.
No existing credential was opened, changed or assumed valid for another provider.

## Primary/documented sources

| Source | Coverage, clocks and update behavior | Access/cost and implementation |
| --- | --- | --- |
| [BLS calendar documentation](https://www.bls.gov/help/hlpiCAL.htm), [ICS](https://www.bls.gov/schedule/news_release/bls.ics) | BLS national releases; not all US macro. Documentation says tentative Friday 15:30 ET calendar updates and updates as needed. Preserve UID, SEQUENCE, DTSTAMP/LAST-MODIFIED, original timezone and event interval. | Public endpoint with no key or advertised API charge. `ICalendarAdapter` implements bounded GET and strict parsing; authenticated/host collection not accepted. BLS ICS could not be rendered by the research browser's content-type handler. |
| [BEA calendar](https://www.bea.gov/news/schedule/icalendar), [ICS](https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics) | BEA releases including GDP, income/outlays and trade; not all macro. Retrieved published ICS structure includes UID, SEQUENCE, DTSTAMP, UTC DTSTART and durations. No revision timeliness SLA established. | Public no-key calendar. Shared ICS adapter handles folded lines, durations and revisions. Research retrieval is not operational ingestion/acceptance. |
| [Federal Reserve FOMC schedule](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [monthly events](https://www.federalreserve.gov/newsevents/calendar.htm) | Scheduled meetings, decisions, projections, minutes, speeches and press conferences have distinct coverage. The official October calendar lists the decision/meeting at 14:00 and press conference at 14:30. Do not infer the latter from a decision row. | Public human-readable reference, no purchase. No unreviewed DOM scraper or invented regular-time schedule is shipped. Direct Fed machine-feed parsing remains unsupported; broader documented adapter below can ingest distinct actual provider records. |
| [Trading Economics calendar schema](https://docs.tradingeconomics.com/economic_calendar/schema/), [country endpoint](https://docs.tradingeconomics.com/economic_calendar/country/), [authentication](https://docs.tradingeconomics.com/get_started/), [limits](https://docs.tradingeconomics.com/get_started/rate-limits/) | Broader scheduled US economic categories. CalendarId, event Date (documented UTC), DateSpan precision, Importance and LastUpdate. Separate IDs remain separate. A 1,000-row response is rejected as possible truncation. No synthetic cancellation or complete coverage inferred from omitted rows. | Requires a developer API key and plan entitlement to the economic calendar. GET interface/parser/offline tests complete; credentials/access were not provided. [Pricing](https://tradingeconomics.com/analytics/pricing.aspx) exposes plan/request allowances, but retrieved price labels were inconsistent; exact applicable API cost is **unverified**, not zero. Confirm plan/quote before any purchase. No subscription purchased. |
| [Finnhub earnings documentation](https://finnhub.io/docs/api/earnings-calendar), [provider SDK field definitions](https://pkg.go.dev/github.com/Finnhub-Stock-API/finnhub-go#EarningRelease), [pricing](https://finnhub.io/pricing) | Company earnings dates plus `bmo`/`amc`/`dmh` buckets, fiscal year/quarter. These are not exact timestamps. The documented row has no original update timestamp or complete catalyst guarantee. Calendar may change; update SLA not established. | Requires Finnhub API key and access to `/calendar/earnings` for selected symbols/date range. GET/interface/parser/offline tests complete. Official pricing did not render usable plan details; exact current entitlement/cost is **unverified**. No assumption of a free operational quota. Date-only full-local-day risk intervals remain tentative and partial. |
| [Cboe historical VIX](https://www.cboe.com/tradable-products/vix/vix-historical-data/) | Daily closing observations, updated daily; not real-time stress. Parser retains observation date without inventing a source timestamp. Same/future-day rows are rejected until publication availability is established. | Public download, no key; daily CSV adapter/offline tests complete. Download/redirect/schema acceptance on target host remains pending. Stale daily records are labelled historical only and never activate live VIX thresholds. |
| [Cboe Global Indices Feed](https://www.cboe.com/data/global-indices-feed/) | Real-time VIX/SPX and other index channels; documented direct/vendor/cloud delivery. | Licensed feed with custom pricing and onboarding. No entitlement, vendor schema or credential supplied. Intraday volatility adapter/thresholds are **not implemented**; daily VIX is not a substitute. |
| [NYSE hours/holidays](https://www.nyse.com/trade/hours-calendars), [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars) | Reuses installed native XNYS calendar; holidays, DST and actual early closes. Materializes explicit bounded future coverage. NYSE lists 2026-11-27 and 2026-12-24 at 13:00 ET. | Existing local dependency, no new subscription or dependency. Local sessions are fixture verified; not an emergency-closure/venue-halt feed or complete option settlement/broker-cutoff authority. |

Trading Economics Date is explicitly UTC. Interpreting a timezone-less LastUpdate
in that same clock convention is an adapter assumption requiring provider
acceptance; raw source values remain retained and coverage stays PARTIAL. Future
or missing source clocks cannot create complete evidence. BLS/BEA schedules can
change because of postponements; their old events remain recorded until an
explicit revision/cancellation is received. The current adapters intentionally
do not attest all-macro absence, so missing broad coverage remains UNKNOWN.

## Unsupported coverage

Baseline normalization accepts arbitrary macro/company categories and explicit
instrument scopes. Actual providers delivered in this slice cover the subsets
above. Company events other than earnings (investor days, product announcements,
shareholder meetings, regulatory decisions, corporate actions, etc.) need reviewed
sources; an earnings calendar does not cover them. No operational synthetic events
or hand-invented schedules are supplied.

Unscheduled news, geopolitical interpretation, currency/cross-asset stress,
intraday volatility, emergency closures, exchange halts, full order-book depth
and broad catalyst interpretation are unsupported. Normalized quotes support
observable spread, displayed-size, price-movement and freshness checks only.
The existing individual-stock candidate contracts can be assessed by symbol;
the current connected profile/feed still only supplies its reviewed SPY/QQQ set.

## Exact outstanding dependencies

1. Trading Economics calendar key + appropriate subscribed entitlement, reviewed
   rate/request budget, original LastUpdate timezone, revision/cancellation and
   coverage acceptance. Or a separately reviewed complete macro source.
2. Finnhub key + earnings endpoint/symbol coverage entitlement, applicable costs,
   and review of date-only/missing-revision-clock limitations. Broader company
   categories need additional documented sources.
3. Public BLS/BEA/Cboe host network/redirect/schema acceptance, without treating
   a successful fetch as complete catalyst coverage.
4. Any desired intraday volatility feed needs Cboe/vendor entitlement, reviewed
   schema/clock/cost, and a future typed adapter. It is not required to use the
   baseline price/spread/freshness observations.
5. A later observation consumer uses the existing published native snapshot,
   same population and same bankroll, plus source workers and an in-memory loader.
   Host supervision, source budgets, observation delivery/backlog and retention
   rotation are not activated here.
