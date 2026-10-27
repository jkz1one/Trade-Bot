# Earnings and option-volatility awareness — observation only

Continuation from feature `44d553536539a40089c2e9f253127bf84dfb7b2b`.
Remote base reverified unchanged at `f305ea19bef3fdfb5aec04c51aa431f32dc2b694`.
Native application code outside `app.events` remains byte-identical to that base.

## What the diagnostic means

`app.events.option_volatility` adds an earnings-linked volatility watch and
contract-IV evidence review for Degen, Swing and Scope. The one-shot native
observer automatically includes it for actual option decisions; stock observations
keep their existing payload. It uses the same event store, population and native
decision IDs, with no new account or trading-path hook.

An earnings interval within the watch window produces
`EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE`. An interval overlapping the intended hold
adds `EARNINGS_INTERVAL_OVERLAPS_HOLDING_PERIOD`. These are exposure warnings,
not claims that IV will drop, has dropped, or explains a price move. A future
scheduled release may be cancelled or delayed. Date-only earnings remain an
uncertain full local day; no invented release clock or catalyst clearance.

The report keeps an observed contract IV only when the retained native quote and
its exact-instrument Greek observation have complete, real-time, observed,
fresh and synchronized evidence. It does not recover IV from a midpoint, daily
VIX, another contract or an estimated Greek observation. Zero/missing IV is
unknown in this evidence review. Original quote/Greek clocks, units, provenance,
entitlement and values are retained alongside the quote hash.

`CLEAR` means only that this earnings-window and IV-availability review found no
restriction with adequate evidence. `crush_forecast_state` is always `UNKNOWN`;
expected IV decline and option-value impact remain null. There is no IV rank,
percentile, term-structure comparison, vega scenario or attribution model here.
The native Greek contract currently supplies delta, theta and IV, not vega.
ETF/index options still get the contract-IV review, with earnings applicability
false. Constituent earnings/ETF look-through and macro-related IV effects are
not implemented by this diagnostic; the existing general event assessment stays
separate.

## Existing IV and VIX work

The repository already contains `app.options.greek_health.review_greek_pressure`:
it compares actual original-entry and current observed IV, with existing relative
decline warnings at 15% and 25%. That diagnostic is not an earnings-crush forecast
or causal attribution. This feature does not change those thresholds, fabricate
an entry baseline, or rewire native management.

The Cboe daily VIX adapter remains historical market context. No live VIX feed,
spike/level policy or provider acceptance is added here. Daily index-level VIX is
not evidence of an individual option's current IV or earnings premium.

## Provisional research settings and validity

`OptionVolatilityPolicy` is `earnings-iv-research-v1`, labelled
`PROVISIONAL_RESEARCH_NOT_VALIDATED`, with mode fixed to `OBSERVATION_ONLY`.

| Setting | Default |
| --- | --- |
| Earnings watch | 259,200 elapsed seconds before through 86,400 after the stored interval |
| Boundary convention | Start inclusive, end exclusive; exact holding endpoint included |
| Quote/Greek age | Less than 10 seconds, using original source time |
| Receipt lag / quote-to-Greek source skew | At most 2 seconds each |
| Maximum validity | 10 seconds, shortened at known transitions |
| Local relevant-event capacity | 256; overflow is UNKNOWN |

These are elapsed-time research windows, not trading days or a calibrated
volatility forecast. For a clear equity watch, fresh COMPLETE symbol earnings
coverage must span from `now - after_seconds` through
`holding_until + before_seconds`. This is deliberately wider than an intraday
holding period, capped at the verified contract expiry. Events known to start
after that expiry are excluded; date-only intervals possibly overlapping expiry
remain uncertain. Missing/incomplete contract identity cannot justify exclusion.
Partial, stale, conflicting, unavailable or insufficient coverage
is UNKNOWN even with a known event warning. Cancelled events are omitted only
when their retained revisions agree; contradictory cancellations remain unknown.
Missing source times stay missing. Calendar freshness is independent of IV age.

Standalone callers may pass an explicit policy to
`prepare_option_volatility(prepared_risk, policy)` off-path, then call
`review_option_volatility(view, request, validated_option_quote)` locally. The
native audit observer uses the default version above and retains the complete
policy/hash in every option report. Changing its configured policy requires a
reviewed code/configuration update; the old base event-policy/store binding is
not silently migrated. Previously delivered audits remain immutable and are not
backfilled under a new policy.

## Audit and execution boundary

`option_event_volatility` is a separate field in `EVENT_OBSERVATION_ONLY` records,
with policy/version/hash, native quote/hash, snapshot sequence/hash, base policy
hash, actual population/decision IDs, symbol scope, validity, reasons and evidence
references. Original events/revisions and coverage remain in the existing store
and export. Base assessment and native results remain unchanged. Missing or
invalid option data produces UNKNOWN rather than failing open or inventing data.

The diagnostic proposes exposure restriction and held-position review for
CAUTION/UNKNOWN; it proposes no new entry block. Existing scheduled-event blocks
remain in the base assessment. Carry remains restricted. None of these advisory
fields authorizes a position-management action, liquidation, stop change,
deadline extension, sizing change or carry. This observer is not on the mandatory
protection path and starts no scheduler, provider or model client.

Preparation, native parsing, policy/quote hashing, snapshot loading and audit IO
are off-path. `option_volatility_local_check_ms` times only the additional local
review, separately from base `local_check_ms`. It is not source-to-detection delay
or end-to-end observer cost. In the 250-iteration synthetic probes, the additional
review had p99 at or below 0.471 ms and maximum 0.758 ms. Combined with the base
assessment, p99 was at or below 2.300 ms, but one sample reached 6.063 ms. The
under-5-ms target remains provisional and is not guaranteed. Preparation and IO
are excluded; no host latency or provider-detection guarantee is claimed.

## Verification and remaining acceptance

See `EVENT_IV_PROOF.json` for installed offline tests and the standalone latency
probe. Fixtures are explicitly synthetic. Tests cover watch activation without
refresh, boundaries, holding overlap, incomplete/date-only evidence, cancellation,
rescheduling, duplicates/conflicts, symbol separation, missing/future/stale IV,
source/entitlement/provenance/synchronization rejection, VIX non-substitution,
capacity, policy immutability, durable audit roundtrip, actual native option IDs
and unchanged accounts. Existing event outage/protection and native Greek tests
are included in the focused installed regression run.

Still required: Finnhub key and `/calendar/earnings` plan/symbol entitlement,
reviewed complete coverage/update semantics, real retained contract-IV availability
and entitlement, public-source/host acceptance, observer scheduling/isolation and
actual source-to-detection latency. The adapter intentionally reports partial
coverage; no new credential or operational calendar evidence was obtained here.
Broader unscheduled news and non-earnings company catalysts remain unsupported.
No deployment, worker enablement, enforcement, purchase or base/main/PR #1 write.
