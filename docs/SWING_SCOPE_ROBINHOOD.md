# Robinhood Swing and Scope PAPER integration

The explicitly selected `robinhood-price-options-v1` variants now have native
input, watch/admission, order, fill, protection and journal paths. They use the
existing local simulator and Robinhood read-only data. They do not require another
provider or brokerage PAPER account. Legacy strategy policies remain unchanged.

This is implementation and synthetic lifecycle validation, **not market acceptance**.
The saved provider evidence still cannot supply all required original inputs.
No host account has been upgraded, resumed or reset by this release.

## Explicit strategy definitions

Swing uses price/history and option evidence, with session-close holding only.
Its new policy does not use a catalyst verdict; supplying one to this variant is
rejected. Missing catalysts are not relabeled CLEAR. The legacy Swing policy still
requires them. Original complete daily/hourly history, source binding, indicators,
option eligibility, current quotes, risk gates and native exits remain required.

Scope uses four source groups: provider readiness, technical structure, cross-market
agreement and exact SPXW contracts. Its four patterns are opening-range break/hold,
compression expansion, failed-break reversal and trap reversal, in both directions.
The price variant freezes its reference at the completed confirmation close, its
invalidation at the structural stop, and its targets from the configured risk
multiples. Current admission independently checks remaining reward and known
intervening levels. It does not enter at a crossed historical breakout price.

Scope retains SPY/QQQ confirmation, completed plateau/pivot path checks, original
geometry locks, score thresholds, exact option terms, spread/tick/size checks,
objective consumption and native portfolio limits. It does not use VWAP or award
points for missing dealer, news, macro, flow or expected-move evidence. Those
legacy context attestations are rejected by the new variant.

Arming is explicitly **sampled confirmation**, with advancing index/option source
clocks and a maximum 30-second sample gap. It is not proof of uninterrupted prices
between samples. Completed bars keep their original clocks and may remain unchanged
until the next five-minute boundary; the next completed bar must then be present.
Current quote/index age, receive-lag and skew gates remain separate and unchanged.
The larger sample gap does not extend entry validity for stale quotes.

## Preserve the existing account

After deploying and building this release, with all connected sessions stopped:

```bash
python3 scripts/connected-session-host.py review-strategy-upgrade
```

Inspect the concrete review, then apply its exact returned hash:

```text
python3 scripts/connected-session-host.py apply-strategy-upgrade \
  --expected-review RETURNED_REVIEW_SHA256
```

This narrow upgrade accepts only the existing never-traded PAPER owner. It preserves
account/population identity, cash, journals, every old event, execution limits,
budgets, simulator state, feed counters and halt. It appends one strategy amendment
under the existing restore fence and updates the frozen strategy/settings bindings.
Historical rollover receipts retain their old owner hashes through that verified
amendment. It does not resume workers, clear a halt or submit an order.

Both owner and collector leases are required. A durable pending intent blocks normal
runtime startup if publication is interrupted. Retry the same apply command with
the original review hash to complete publication; do not remove the intent, rewrite
runtime files manually, re-enroll the owner or reset the bankroll.

## Session inputs

`prepare-session` accepts `--observed-swing-history` and an optional separate
`--swing-capture-directory` containing `contracts.json` plus `quotes-1.json` through
`quotes-3.json`. Swing requires exactly one CALL and PUT per enrolled SPY/QQQ symbol,
with advertised expiration 7–45 calendar days after the target session. The existing
contract capture helper can capture that selected expiration. A same-day DEGEN
catalog is supplied separately.

The observed-history choice selects `utc-day-halfhour-v1` mapping and preserves
UNKNOWN entitlement, original bars/clocks and capture hashes. Incomplete,
interpolated, delayed or post-open originals remain blocked. ETF standard terms are
explicit simulation assumptions, not broker-verified terms; future expiration does
not authorize overnight holding.

Optional `--scope-binding` points to a reviewed `ScopeFeedBinding` JSON: exact native
SPXW OptionInstrument, exact ScopeSession/calendar, previous session, one explicit
pattern/right choice and original contract capture SHA256. It is an operator-supplied
reviewed binding, not an automatic SPXW term discovery/verifier. The caller must
inspect the original contract evidence corresponding to its hash. ETF assumptions
cannot substitute for SPXW cash/European/PM terms. This release handles one bound
Scope watch, not autonomous whole-chain watch selection.

```text
python3 scripts/connected-session-host.py prepare-session \
  --capture-directory /root/ACTUAL-SAME-DAY-CAPTURE \
  --target-session YYYY-MM-DD \
  --observed-swing-history \
  --swing-capture-directory /root/ACTUAL-SWING-CAPTURE \
  --scope-binding /etc/trade-bot-connected/ACTUAL-REVIEWED-SCOPE.json \
  --next-policy /etc/trade-bot-connected/sessions/UNIQUE-ID/policy.json
```

The existing review-session/enroll-session hashes, fresh native acceptance, reviewed
entry recovery and bounded run remain required. Do not reuse expired session dates.
Preparation does not activate the dashboard or workers.

Capacity is eight candidate option contracts without Scope, or seven plus the bound
Scope contract. Up to two held contracts remain independently quoted. Eight IDs per
option request and eight total calls per capture remain enforced. A four-DEGEN plus
four-Swing catalog plus Scope exceeds this bound and is rejected, never silently
truncated. Select a smaller reviewed candidate set when running all three families.

## Connected collection and protection

The collector schedules three schema-pinned SPX reads alongside ordinary market
reads within one bounded worker connection. It charges all reads to the existing
quota and retains original private receipts. Scope read failure leaves successful
ordinary reads available. Missing Swing history likewise does not erase peer quotes.

SPX venue_timestamp remains the source clock; provider updated_at or receipt time
cannot make an old index value fresh. `IndexReference` serializes a value and original
identity/clocks/hash with `executable_book: false`, never a stock bid/ask or size.
Only option contracts can be filled. The reference passes through native entry,
fill attribution and barrier protection. A current invalidation can terminate an
unfilled watch even when new history is unavailable. Consumed watches are not
re-created after restart.

Index histories require exact completed session coverage and explicit
`interpolated: false`. Missing interpolation flags remain unknown. Absent index
volume stays absent. No index VWAP is calculated from invented volume.

## Actual data boundary

- Swing: the saved daily history contains interpolated/zero-volume placeholders.
  Complete original daily/hourly input and the intended 7–45 DTE catalog are still
  needed. Stock entries additionally require an executable stock book.
- Scope: the saved October 29 SPX capture has a stale venue timestamp and no bars
  explicitly marked noninterpolated. Fresh valid bars and exact reviewed SPXW
  contract/session evidence are still needed. Fresh quotes alone do not fix this.
- Both: host upgrade, current session enrollment, market-hours native acceptance,
  bounded lifecycle evidence and connected dashboard activation remain unproven.

Tests use clearly synthetic qualifying inputs for CALL/PUT native entry, fill and
close. They also retain and reject the actual unusable provider captures. No test
result establishes provider completeness, strategy profitability or live readiness.

## Validation for this release

Final installed-package focused regression: **173 passed**. Coverage includes
Swing and Scope CALL/PUT lifecycles, native index invalidation, collector quota and
optional-input failures, combined worker reads, all three interrupted upgrade file
boundaries, prior rollover preservation, host/session preparation and installed
read-child import isolation. All **311** installed application files match source;
installed release inspection returns `VERIFIED_FILES`.

The earlier broader 467-case run passed 464 checks. Its failures were one outdated
catalyst-report expectation (corrected) and two five-second simulator subprocess
timeouts. All three pass in the final installed-package run. That local rerun does
not establish server timing: retain the bounded host check, especially on its
single-CPU deployment. No timeout, freshness, spending or admission safeguards were
removed to make tests pass.


Host apply correction (2026-10-30): the initial release's launcher incorrectly
mounted the configuration directory read-only for the amendment operation. The
fixed launcher permits only this offline apply path to publish configuration while
keeping policy.json and schemas.json read-only. If the initial apply failed, build
the corrected release and retry the **original** apply review hash. The pending
intent is recovery evidence and must be retained. Review/ordinary runtime config
mount protections are unchanged.

October 30 market-hours evidence: the operator's read-only verification confirmed
`UPGRADE_VERIFIED` at owner revision 355 with the stop/halt preserved. Do not apply
the completed amendment again. The current session still needs reviewed inputs.

The saved `trade-bot-options-proof-VQXJP1` capture contained two source timestamps
0.545227 and 0.539 seconds after capture completion, with no regression and host
NTP synchronization reported. That does not establish the provider clock's cause
or justify correcting timestamps. Observed-simulation catalog preparation now
retains future samples as `SOURCE_AFTER_CAPTURE`, preserves their original clocks
and negative ages, and reports them as not fresh. Only contract identities/terms
are prepared; no captured quote is enrolled as an executable quote. Strict catalog
binding, regression rejection, native future-quote rejection, and all runtime
freshness/fill guards remain unchanged. Existing saved captures can be reused for
offline observed-simulation preparation.

The independent `trade-bot-input-probe-Nrk6E9` received a current SPX quote but no
explicitly noninterpolated history bars (204 interpolated, 84 unknown). Its stock
book response was 484,845 bytes, exceeding the diagnostic's old 128 KiB limit.
Only that diagnostic tool now permits 512 KiB, with a 704 KiB observations budget
inside the unchanged 768 KiB capture and 1 MiB worker envelope. Other tool payloads
retain 128 KiB limits. Full original responses are retained without trimming or
rewriting. The oversized prior response was not retained and requires a new probe.
This change does not enroll stock sizes, certify history, or start trading.

Validation: 218 focused tests pass, including preserved negative quote ages,
unchanged strict/native rejection, capture-to-catalog reporting, original large
book retention within the worker envelope, size-limit failures, isolated captures,
observed PAPER fills, session preparation and guarded flat recovery. Host data
acceptance remains pending; these tests do not certify the provider clocks.
