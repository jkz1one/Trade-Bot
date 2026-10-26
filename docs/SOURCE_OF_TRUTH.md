# Autonomous Compounding Trader: source of truth

Version 1.139. Guarded first collector enrollment, 2026-10-26 EDT.

[Guarded collector enrollment](CONNECTED_ENROLLMENT.md) now reviews and creates the
first collector against the existing unused native owner. Exact configuration and
owner-revision hashes are rechecked under its lease. It preserves the one bankroll,
halt, fills and runtime state; used runtimes cannot reset missing feed history.
The old create CLI delegates to the same guard and cannot start workers during
creation. Read-only runtime checks now verify the complete frozen strategy identity
through the native serializer without opening model keys. See
CONNECTED_ENROLLMENT_PROOF.json for 205 installed passing cases and all
289 matching application files. Initial collector and
supplied carry-schedule enrollment are implemented; schedule/catalog rollover,
full host setup and missing eligible feeds remain unfinished. No host action or
activation occurred. Stopping reason: slice end; more offline coding remains.

[Connected carry intent](CONNECTED_CARRY_INTENT.md) now accepts an optional frozen
per-session schedule with separate stock and option exit dates. Preparation,
restart verification and runtime assembly use the same original intent. Native
calendar/expiry guards apply; no date or catalyst clearance is inferred. Absent
schedules preserve legacy hashes, while changed enrolled schedules are rejected.
See CONNECTED_CARRY_INTENT_PROOF.json for installed validation. Bounded carry-input
wiring and guarded first enrollment are implemented; schedule rollover is still work.
The host is unchanged. Publication is a slice end and more offline coding remains.

[Continuous delivery fixes](CONTINUOUS_STRATEGY_DELIVERY.md) preserve quotes between
prepared Swing cycles and after optional intraday-history failures. MARKET
conversion strips all cycle-only sources/catalysts while retaining original
bindings for the next complete cycle. Failed raw receipts remain retained. Missing
Scope input now explicitly blocks an entry cycle without discarding available
SPY/QQQ protection quotes. See CONTINUOUS_STRATEGY_DELIVERY_PROOF.json for installed
validation. No runtime schema was weakened or data eligibility promoted.

The catalyst provider adapter is blocked by a missing reviewed source/schema:
none of the six fixed read tools supplies catalyst/news clearance. No fictional
provider or CLEAR override was added. This publication is a slice end; other
offline implementation remains possible. Host setup, schedule rollover, Scope inputs,
eligibility and candidate replacement remain unfinished. Server unchanged;
connected simulation inactive.

[Runtime assembly](SWING_RUNTIME_DELIVERY.md) now joins verified original Swing
sources with exact current metadata/quotes and explicit typed catalysts. Degen
inventories receive same-day expiries while Swing and held quotes remain covered.
Missing inputs produce MARKET packets with explicit reasons and usable protection
quotes; no partial strategy universe is silently enabled. Native catalyst gates
remain authoritative. The collector loads retained source bindings on each tick;
the installed run path still has no catalyst provider and supplies none. Diagnostic
and packet-capacity handling preserve readable quote delivery. See
SWING_RUNTIME_DELIVERY_PROOF.json for installed offline validation. This is a slice
end, not a collection-forced stop. More offline coding remains possible. The host
is unchanged and connected simulation is inactive.

[Native source binding](SWING_SOURCE_BINDING.md) now prepares exact stock sources,
single option seeds and complete batch roots through existing validators/builders.
The collector retains one original result per session, including unknown-evidence
blockers, and revalidates it on restart without restamping or rewriting. Current
normalized history remains UNKNOWN and therefore blocked. Current metadata and
frame assembly now have the delivery path above. Catalyst provider/provenance and
operational carry schedule rollover remain unfinished, alongside Scope, eligibility,
candidates and host setup.
See SWING_SOURCE_BINDING_PROOF.json for installed offline evidence. Publication
is a slice end; additional coding can continue without another collection run.

The [Swing history collector](SWING_HISTORY_FEED.md) now has explicit opt-in daily/
hourly capture, exact exchange-calendar normalization and durable raw-bound native
history snapshots. It preserves clocks and UNKNOWN entitlement, reserves quote
read capacity, retains usable required quotes when optional history fails, and
reuses history across restart. Legacy collector hashes remain unchanged. Installed
offline evidence is in SWING_HISTORY_FEED_PROOF.json. This is history transport,
not completed Swing signal delivery: catalyst ingestion/provenance, Scope inputs,
contract/data eligibility, candidate replacement and host setup still need work.
Actual daily/hourly responses are unverified. More offline coding remains possible;
publication is a slice end, not a stop forced by missing collection. No server or
provider/model/credential access occurred.

The [coordinated runner](CONNECTED_RUNTIME.md) now reopens the enrolled native
owner and continuous collector under their existing leases. The first runtime
tick precedes held-instrument collection, including recovery of durable fills
not yet journaled. Shared failure/shutdown fencing drains both components before
lease release. A read-only check rejects missing enrollment, configuration drift
and frozen review populations. Restart preserves cash, exact plays and delivery
sequence; it never resumes entry or resets a bankroll. Installed offline evidence
is in CONNECTED_RUNTIME_PROOF.json. Host enrollment/configuration, missing feed
inputs, data eligibility and dashboard activation remain unfinished. No server,
provider, model, credentials, dependencies or CI changes occurred.

[Connected simulation work](CONNECTED_SIMULATION.md) now checks collector/owner
configuration together before opening state or credentials. Expired unheld
candidates are retired from reads; held identities remain covered. This is not
activation. Runtime delivery now has typed Swing source/catalyst assembly, but still lacks
the catalyst provider and Scope SPX/context inputs; the optional history cache
does not close those gaps. The earlier statement that feed integration was complete
applied only to the implemented SPY/QQQ quote/intraday transport. Complete strategy
feed coverage and guarded operational launch remain work, alongside explicit
contract/entitlement/stock-size evidence. The operator is unavailable on the host
during today's market hours; proceed offline without claiming tomorrow is ready.

The operator confirmed a653cc7 deployed successfully: 283 application files match,
health/authentication pass, and frozen V3 retains two native fills. The rounding
fix is installed. before-price-format is now a consumed rollback name. Do not
rerun the prior refresh. The original failed dceb64e startup cause remains unknown.

At 09:33 EDT the bounded host check reported three fresh, advancing samples for
SPY/QQQ equities and both known October 26 call contracts. The uploaded sample-3
matches its reported SHA256 and independently passes exact plan, pinned schemas,
subject identity, source-clock, book and session checks. Latest ages at capture
were 0.473–1.124 seconds. Option sizes and Greeks are present. See
[raw acceptance evidence](REGULAR_SESSION_QUOTE_PROOF.json). Only sample-3 was
independently revalidated; three-sample advancement is operator-reported evidence.
Do not repeat this bounded freshness check as an unresolved prerequisite.

The response omits equity sizes, explicit data entitlement and full option
contract terms. UNKNOWN is the mapper's conservative default, not an observed
provider error. These fields cannot be invented from fast quote timestamps. No
connected simulator has been activated and no simulated execution on this market
capture is claimed. Continuous operation, runtime configuration and activation
still need completion on the same bot/dashboard with virtual funds.

The operator's first current-data check completed all three samples: SPY/QQQ
equity quotes were fresh and their clocks advanced. Options still carried Friday
timestamps during premarket. The dceb64e price refresh subsequently passed file
and fixture checks, then failed its six startup probes and rolled back to acabf4a.
The helper now waits up to approximately 90 seconds, checks container liveness,
and preserves startup logs before rollback. The previous failure's cause is not
established. Connected simulation remains inactive. See MARKET_DATA_PROOF.md.

The user wants simulated trades driven by real incoming data in this bot and on
the existing dashboard. No separate brokerage account is required. A local
virtual-cash ledger is implementation storage, not a new external account.
The connected simulator is not yet running; offline lifecycle completion and a
frozen UI deployment do not satisfy that goal.

[Today's bounded data check](MARKET_DATA_PROOF.md) reuses the confirmed installed
image, captures three sets of SPY/QQQ quotes and known October 26 option samples,
and reports source-clock advancement, freshness, sizes and remaining restrictions.
Premarket and regular-session host results are supplied; see the current acceptance above.
The deployed price display removes trailing decimal padding without changing
stored stops or targets.

The [native two-play implementation](TWO_PLAY_IMPLEMENTATION.md) connects up to two
simultaneous PAPER plays through one owner and bankroll: atomic capacity/funds
reservation, full-cost accounting, independent orders/protection/exits, original
strategy/model receipts, restart recovery and sequential shared selection. V2 is
explicit enrollment; old single-play databases and frozen fixtures retain their
original protocol and IDs. [Installed proof](TWO_PLAY_NATIVE_PROOF.json) records
the completed offline checks. This supersedes the isolated capacity/accounting
checkpoints; no connected trading population has been migrated or activated.

The UI now supports two complete play cards with a compact selector and preserves
the selected play/tab/disclosures/scroll during polling. All lower tabs retain the
same 420px default height. Signed/revision-bound 0/1/2 controls appear only for an
explicit operator-inbox enrollment. Pages only read stored evidence.

Continuous normalized feed transport is wired and tested offline with retained
source clocks, held-instrument coverage, partial-batch evidence, rate budgets and
restart/reconnect behavior. Reviewed metadata, entitlement, executable stock sizes
and Scope/SPX connected mapping remain unresolved. Browser visuals and fresh,
ongoing market-open host acceptance remain pending. Do not call the connected
engine ready or deploy/activate PAPER on the strength of offline checks.

Earlier October 26 output confirmed acabf4a deployed with 283 matching files,
two native simulated fills, health OK and authenticated frozen ui-review-v3. The
startup resets cleared during retries. The previous d2092f1 reader is retained as
before-two-play. Do not rerun V3 prepare/activate. The supplied browser screenshot
confirms the two selectors/card display and identifies the stop-formatting defect;
it does not establish full browser acceptance. LIVE stays disabled. No provider,
model or trading worker was started. No workspace credentials access, dependency
changes, hosted CI or remote service changes occurred during implementation.

The [Data Stream/dashboard release](MIXED_DATA_STREAM.md) adds retained quote/event
records inside the existing detail tabs, clearer average-entry/bid/ask/P&L display,
darker charcoal surfaces and a greener accent. Original grid proportions remain.
Active mixed accounts now poll authenticated stored snapshots every five seconds
without reloading the page; UI selections, disclosures, focus and scrolling persist.
Frozen reviews/history stay paused, failures remain visible and quote source times
stay separate from page synchronization. No page-triggered provider/trading work.
63 installed Python cases, 23 JavaScript cases and all 259 file byte identities pass.
The operator deployed a51a313 successfully after correcting root-only source-file
permissions: all 259 file matches, frozen native verification and authentication
passed, with three fills retained. The a3216b6 rollback is before-stream.

The [detail-panel balance correction](MIXED_PANEL_BALANCE.md) gives Trades a compact
scrolling view and expand/collapse control, and removes Data Stream's independent
maximum-height cap so it follows the shared grid row. The active-trade tabs stay;
its Summary has one Exact levels and original targets disclosure. Extra scroll-jump
links are removed. Plain-language explanations and amber negative amounts keep
the same simulation, freshness and cost distinctions. No portfolio, engine, strategy or dependency changes. The deployed native implementation still supports one open
position across families in its original v1 enrollment. The v2 continuation above
adds native two-play ownership. That earlier checkpoint recorded 33 installed Python and 19 JavaScript
checks pass with 259 matching files. Supplied operator output confirms d2092f1
is deployed: matching image, 259 installed files, native frozen verification,
authentication and three fills. Browser visual acceptance remains pending.
The a51a313 rollback already exists as before-panel-balance. Do not rerun the old
refresh blindly; its prior-image guard and rollback name have been consumed.

The operator restored interactive authorization, then supplied successful headless
schema discovery with the unchanged pin and a completed four-read capture at
October 25 00:49 EDT. The [actual quote/history/chain evidence](ROBINHOOD_SAMPLE_ACCEPTANCE.md)
validates against the installed package. Two quotes keep their Friday source times,
missing sizes and UNKNOWN entitlement. Twelve completed bars omit interpolation
flags but have positive volume; the mapper now derives non-interpolation only from
that schema-backed evidence. Unknown zero-volume and contradictory bars still fail;
raw receipts remain untouched. No engine/dependency/strategy/authority change.
119 installed Python cases and all 256 source/wheel/installed file matches pass.
The earlier failed attempts remain preserved. No authenticated workspace calls.

The exact-strike and four-decimal-format instrument calls both returned empty
results. A broader listing initially failed before container startup because the
user had deleted the credential directory. Fresh login/headless discovery succeeded
with the dedicated **`/var/lib/trade-bot-read-auth`** directory; old auth-path commands
are historical. The [successful broader listing and next option sample](ROBINHOOD_OPTION_SAMPLES.md)
returned 100 calls per symbol with pagination, including observed active/tradable
SPY760 and QQQ705 October 26 call UUIDs. No more pagination is needed for this sample;
complete chain coverage is not established. Earlier empty-filter cause is unproven.

The two-read option plan completed at October 25 01:16:47 EDT. Both exact observed
UUIDs returned bid/ask prices and sizes, Greeks, volume and open interest; each
history returned six regular five-minute bars. [Accepted response evidence](ROBINHOOD_OPTION_RESPONSE_PROOF.json)
verifies the plan, schemas, identities and clocks. Quotes retain Friday 16:14:59 EDT
source times and are about 33 hours stale. Option history has no volume and omits
interpolation flags; neither is fabricated. All six tools now have successful real
response samples; no further sample capture is required at this stage.

This is wire-response acceptance, not native option normalization or PAPER
activation. Complete reviewed contract metadata and entitlement are still absent;
stock sizes remain missing. Continuous normalized capture/delivery and fresh
market-session host acceptance remain incomplete. Broker sellout is not exchange
expiry/settlement proof. No application/engine/strategy/dependency changes; prior
119 installed cases and 256-file identity verification remain unchanged. No new
suite run, dashboard refresh, model/PAPER/LIVE activation, paid call, account read
or broker order. No authenticated workspace calls.

The operator successfully refreshed the separate dashboard to
`a3216b6d3953d1291643830b20ac4ef69fd8b37b`: all 255 application files matched,
health/private authentication passed, and three frozen historical fills remained.
Startup resets cleared within retries. The e6fd353 reader is retained separately
as `trade-bot-dashboard-before-chart`; v1/v2 and earlier rollback readers are
preserved. The running original de5dd1c SHADOW services remain unchanged.
The chart uses dashed missing-value connectors, and trade labels flow beneath
numbered markers. Browser review/screenshots of those changes remain pending.
No additional dashboard refresh is needed for these read-evidence changes.

The operator supplied the actual six-tool Robinhood schema export. Its recomputed
digest matches `d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15`.
All input/output schemas are present. The [offline mapper and reviewed sample plan](ROBINHOOD_READ_MAPPING.md)
now bind the known wire shapes to existing equity/stock/option/Greek/liquidity and
completed five-minute history models, with exact identities and original clocks.
No provider calls, engine changes, strategy changes or dependencies are introduced.
The earlier 97-case proof used synthetic responses; the newer authentic-sample
proof above separately records the first supplied market response acceptance.

Important actual schema limits remain explicit: equity quotes omit executable
sizes; option metadata omits several mandatory contract terms/times; there is no
per-observation entitlement field. The mapper keeps sizes missing, entitlement
UNKNOWN and requires independently reviewed instrument metadata. It cannot make
native admission pass by inventing those values or treating broker sellout time
as exchange expiration. The existing opt-in native quote-fill integration is
unchanged. **This is not yet a connected Robinhood PAPER service.** The normalized
collector and authentic acceptance remain incomplete.

A concrete first plan contains four market reads: SPY/QQQ equity quotes, six
five-minute bars each from October 23 09:30–10:00 EDT, and SPY/QQQ chain metadata.
One schema rediscovery precedes those reads. No account/model/order/PAPER work is
included. The user explicitly authorized that bounded capture. Its first attempt failed
before reads; the later post-login attempt completed all four reads. No prospective
activation or model call was authorized.
The operator executes host commands; credentials remain private. Main is unchanged,
PR #1 remains open/draft, the original experiment is frozen, and LIVE is disabled.

[Independent Scope A/B/C/D comparison](OPTIONS_SCOPE_COMPARISON.md) now connects
choice-only B, matched independent native accounts and portable full-cost export.
[Continuous Scope runtime inputs](OPTIONS_SCOPE_RUNTIME.md) now connect explicit
watch instructions, durable delivery/restart receipts, fresh paid admission and
independent protection. [Combined Scope/Swing carry](OPTIONS_SCOPE_CARRY.md) now
binds explicit native owner, entry/management, runtime and stored export contracts.
[Continuous Scope session comparison](OPTIONS_SCOPE_SERIES.md) now preserves four
independent owners, explicit settlement, saved closing evidence, full costs and
known-only SPY session endpoints. [Native repeated-entry attribution](OPTIONS_NATIVE_ENTRY_ATTRIBUTION.md)
now binds a separately frozen loss policy and post-close flat-account proof.
[Combined Scope/carry series](OPTIONS_SCOPE_CARRY_SERIES.md) now binds separate
frozen replay/export, choice-only B and explicit overnight costs.
[Original Swing target derivation](OPTIONS_SWING_TARGETS.md) now binds the existing
daily-breakout seed to fixed 1R/2R/3R objectives, native retirement and portable replay.
[Native daily base breakout/breakdown](OPTIONS_SWING_BASE.md) now binds complete
daily/hourly source rules, original targets and family identity through shared native
execution, runtime, carry and independent full-cost export.
[Native daily MA pullbacks](OPTIONS_SWING_MA.md) now bind 8 EMA, 21 EMA and 50 SMA
variants to original evidence/targets, native execution, runtime and independent
carry/export. [Higher-timeframe level setups](OPTIONS_SWING_LEVELS.md) now derive
complete previous-week/month extrema and aligned weekly opens, retaining original
geometry through native execution, runtime and independent carry/export.
[Concurrent Swing-family batches](OPTIONS_SWING_BATCH.md) now bind complete original
sources, atomic roots, exact selection, runtime and independent native carry/export.
[Shared mixed cash history and admission](MIXED_CASH_HISTORY.md) now reconstruct
one stock/options balance, costs, reservations and loss envelope with order-free
stock admission and an existing option-account projection. The separately enrolled
[native mixed owner](MIXED_NATIVE_OWNER.md) now connects common journal/restore,
stock preparation/attempts, complete reconciliation, independent protection and
full-cost global/family outcomes. [Original stock carry](MIXED_STOCK_CARRY.md) now binds explicit calendar
horizons, original catalyst coverage, DAY entry orders, retained protection and
full daily allocations. [Original stock sources and shared selection](MIXED_STOCK_SELECTION.md)
now bind completed Degen/Swing evidence, original source locks/retirement, native
stock/options/Scope competition and full-cost attribution. [Paid mixed entry and
management](MIXED_AI.md) now bind full worker receipts, original native terms, fresh
post-cost admission and all entry/management charges. [Continuous mixed runtime](MIXED_RUNTIME.md)
now binds complete delivered inputs, native protection, source retirement, restart
and explicit cash settlement. [Common mixed tapes and independent native A/B/C/D
replay/export](MIXED_REPLAY.md) now retain full response contracts, actual later
fills, original carry/session terms, independent loss controls and every known or
unknown cost. This connects the settled strategy/engine plumbing; final UI/visual
and authentic provider/normalization/model/host/economic/PAPER acceptance remain.
[Shared durable mixed fixture](MIXED_VENUE.md) now connects actual share and option
orders to one venue balance, atomic order lock, event sequence and bounded fixed
child. Original terms, partial fills and explicit settlement persist across restart.
Legacy owners still reject this enrollment. The new native mixed owner binds both
asset paths explicitly. Mixed tapes and independent replay/export require their
separate complete enrollment; legacy consumers keep their original input guards.
[Shared Scope entry AI](OPTIONS_SCOPE_AI.md) now binds one paid Degen/Swing/Scope
decision to native approval, fixed Scope terms, fresh post-cost admission and stored
trade-level cost attribution. The original expiry still caps dispatch; scale/final
exits and loss outcomes retain the paid entry. This requires a new frozen owner;
legacy deterministic cohorts remain model-off. [Shared Scope position reasoning](OPTIONS_SCOPE_POSITION.md)
now retains original native protection and freshly recomputed Scope context through
paid management and stored cost attribution. [Common Scope observations](OPTIONS_SCOPE_MARKET_TAPE.md)
now retain frozen session/source policy, point-in-time diagnostics and tape-linked
native watch replay. Each independent owner computes its own arming/admission and
retains original terms, native revisions and portable accounting. This watch-only
mode does not implement model roles or trading comparison. The separate
[deterministic A tape baseline](OPTIONS_SCOPE_TRADING_REPLAY.md) now connects shared
selection, native later fills, independent protection and full-cost accounting. The
separate Scope A/B/C/D wrapper now supplies matched fixture accounting; continuous
watch/runtime inputs now have explicit native enrollment. Legacy comparison consumers still reject Scope tapes. A separate
[C/D scripted response contract](OPTIONS_SCOPE_REPLAY_MODEL.md) now binds full shared
Scope entry/management receipts and matched declared entry scripts. A separate frozen
[native C/D tape enrollment](OPTIONS_SCOPE_MODEL_REPLAY.md) now connects that contract
to delivered fresh observations, native paid admission, later fills and full-cost export.
The settled family/mixed stock-options plumbing is connected through its explicit
native fixture contracts. Final UI and authentic PAPER acceptance are still open.
M1/M2 and the first M3 Degen execution path are fixture verified. M3 provider acceptance is open.
The broader AI role is an extension of M3/M4. Its contract, bounded model worker and
durable full-plan PAPER execution are fixture verified; authentic model/feed
acceptance remains open. P3 position reasoning now has durable opt-in management
integration with atomic consumption, tighter stops and full PAPER exits. M8 adds the
user-requested dedicated dashboard design and visual acceptance.
The [dashboard presentation](OPTIONS_DASHBOARD.md) now adds a research-desk briefing,
visible stored blockers/ages, selected-page decision context, current protection
before historical decisions, and expandable exact cost/order/fill evidence.
Eight offline display states and native read-only regressions are available; actual
desktop/mobile rendering, keyboard and user visual acceptance remain open. The
browser rejected the workspace fixture URL. The option observer's mixed-owner guard
remains intact; the separately bound mixed presentation is documented above, with visual acceptance open.
The [isolated options test procedure](OPTIONS_TESTING.md) now joins installed-file
identity, native runtime/recovery, shared entry, observer and full-cost replay
checks with those display files. Its retained receipt requires completed test
summaries and never grants provider, host, visual or LIVE acceptance. Successful
runs now export a portable dashboard review pack containing only the fixed display
pages and limited build/test evidence, so visual reviewers need no Python setup.
Native [fill-bound underlying observations](OPTIONS_FILL_UNDERLYING.md) now preserve
optional exact quotes through partial fills, reconciliation, stored attribution and
sealed replay/export. Historical missing data stays absent. New opt-in
[fill-bound target protection](OPTIONS_ENTRY_REFERENCE.md) now resolves the native
reference from complete entry fills and retains it through scales, restart and
export. Scope management v2 retains both original milestones and binds T1 protection
to that reference. New [Scope entry evidence binding](OPTIONS_SCOPE_ENTRY_BINDING.md)
retains the original watch and exact owner/admission/management receipt through
stored selection and portable research replay. Later journal actions require fresh
admission; evidence selection grants no order authority. Native Scope order/fill
and family-loss enrollment are connected by the separate frozen native version.
New [deterministic entry deadlines](OPTIONS_ENTRY_TIME_PROTECTION.md) freeze an
earlier strategy exit in native decisions, orders and holdings. The stricter owner
session/expiry cutoff still wins; partial fills, runners, attribution and export
retain the terms. Scope handoff includes its original protection time without
granted entry authority. Attempted-order and account-freshness controls remain.
New [native Scope execution/loss integration](OPTIONS_SCOPE_EXECUTION.md) connects
responsive/balanced one-to-three-contract plans to native PAPER decisions, orders,
fills, target/time exits, full-cost outcomes, family cooldown/lock and signed resets.
Create-only native fixture replay and portable accounting reconstruction are available.
Research cohorts remain order-free. The pinned approved playbook reserves the full
unobstructed-path requirement for convexity, which remains blocked. Four-contract
plans remain blocked by missing T3; neither case is silently resized or relaxed.
This supersedes earlier broad statements that all Scope execution requires complete
obstruction proof. Authentic data/provider, prospective economics, host and final
UI/visual acceptance remain open. See the latest status entry for installed proof.
P3 paired accounting, sealed market tapes, setup/shortlist replay and automatic
native first-session A/B/C journal export and independent virtual-clock replay
with scripted model delays are fixture verified. Multi-session replay/export now
preserves native accounts, explicit funds settlement and saved closing evidence.
[Arm D replay/export and stored attribution](OPTIONS_MANAGED_REPLAY.md) now extend
that path to four independent accounts with all entry and management costs.
The [eligible long-underlying comparator](OPTIONS_UNDERLYING_BASELINE.md) now adds
an independently funded, explicitly enrolled share baseline on A's approved
CALL opportunities, with later sized quotes, all costs and explicit settlement.
[Whole-session analysis](OPTIONS_SESSION_ANALYSIS.md) now adds optional manifest-frozen
primary-arm block diagnostics, retaining incomplete sessions and all costs.
The [continuous local PAPER runner](OPTIONS_LOCAL_RUNTIME.md) now adds independent
protection, scheduled decisions, interruption-safe shutdown and stored runtime
evidence for a new normalized-fixture options population.
[Reviewed operator recovery](OPTIONS_OPERATOR_RECOVERY.md) now adds separately
keyed local halt/resume/revocation requests with exact revision and evidence gates.
[Shared Degen/Swing arbitration](OPTIONS_SHARED_STRATEGIES.md) now adds a locked
next-session daily-breakout family to the same PAPER owner and full-entry AI packet.
The original adaptation retains session-close protection. New populations can separately
enroll [native bounded Swing carry](OPTIONS_SWING_EXECUTION.md), with original-seed
terms, DAY orders, retained protection, rollover/restart, carry-aware model contracts
and independent full-cost multi-session replay.
New [overnight carry preflight](OPTIONS_SWING_CARRY.md) now verifies explicit actual-
session horizons, expiry buffers, catalyst coverage and fee-inclusive current admission.
Its portable report always retains an execution blocker; native carry requires the
separate frozen enrollment above. Daily open boundaries remain inconclusive; a
flat-ended full-period cash diagnostic includes all costs without a gapless SPY comparison.
An optional frozen completed-bar lifecycle now retains original-stop invalidation
across recovery, revised history and restart, with native preparation/dispatch
guards and stored observer evidence. Revisited expired seeds use actual XNYS closes.
A separate frozen observed-quote policy now retains between-bar original-stop
breaches during supervision and native entry review, including independent replay.
A separate frozen lifecycle now requires an original first target in the pre-open
seed and retains unfilled target consumption through native review and replay.
[Original Swing target derivation](OPTIONS_SWING_TARGETS.md) now prepares the existing
daily-breakout seed and binds its fixed objectives through native execution and replay.
Broader families and authentic overnight acceptance remain open.
[Shared-family replay/export](OPTIONS_SHARED_REPLAY.md) now runs frozen Degen/Swing
tapes through independent A/B/C/D accounts across sessions, preserving every
entry/management charge and the existing proposal/review/fill attribution.
[Historical comparison views](OPTIONS_COMPARISON_VIEW.md) now bind explicit
full-cost research reports to a population's audit prefix, with stored-only
net-equity/SPY/cash display and visible incomplete paths. Browser visual acceptance
remains open; historical reports do not complete current marks or prove profitability.
[Installed-file identity](OPTIONS_LOCAL_RUNTIME.md#installed-release-identity) is
now recorded per runtime generation and displayed from stored evidence. File
consistency and installer metadata do not grant release approval or prove liveness.
[Scope evidence preflight](OPTIONS_SCOPE_PREFLIGHT.md) now checks all nine required
evidence groups, SPX/SPY/QQQ completed coverage and exact 0DTE SPXW identity.
Preflight alone grants no setup, account or order authority; native enrollment is separate.
[Scope completed structure](OPTIONS_SCOPE_STRUCTURE.md) now adds nine price-derived
patterns, explicit SPY/QQQ directional confirmation and exact-strike reachability.
[Scope context review](OPTIONS_SCOPE_CONTEXT.md) now adds the six level-anchored
variants and bound flow/news/event/expected-move risk checks. These remain
diagnostics. [Durable unfilled watches](OPTIONS_SCOPE_WATCHES.md) now retain called-play
counts, locked evidence and deterministic invalidation/expiry in the existing
journal. New frozen watch cohorts can now record a distinct neutral reset and
require cooldown plus fresh post-reset reversal bars. [Scope quality review](OPTIONS_SCOPE_QUALITY.md)
now adds auditable source scoring and conservative known-level path checks, with
optional frozen watch integration. Opt-in completed SPX structural path checks
add opening-range levels, confirmed pivots and exact VWAP without claiming
complete path proof. A separate frozen `completed-spx-plateaus-v2` extension now
adds confirmed exact equal-high/low runs to quality, arming and current-price
admission, retaining formation and confirmation times through stored observation
and restart. Existing v1 cohorts remain unchanged.
[Scope sampled arming](OPTIONS_SCOPE_ARMING.md) now adds durable fresh-observation holds and resets against locked evidence.
[Scope contract profiles](OPTIONS_SCOPE_CONTRACTS.md) now add exact-contract price,
spread, observed-delta and liquidity gates with optional frozen watch integration.
[Scope owned admission review](OPTIONS_SCOPE_OWNED_ADMISSION.md) now stores
common-governor sizing from fresh armed evidence and the authoritative owned account.
Fresh reviews now enforce the approved executable-ask quantity tiers (4/3/2/1)
through that governor, preserving stricter owner limits and every entry/exit fee.
Fresh admission also rechecks remaining first-target R and the known-level path
from the current CALL ask or PUT bid against the locked geometry. Failed checks
reset arming and retain rejected evidence; full path proof remains open.
The [stored observer](OPTIONS_OBSERVER.md#scope-research-visibility) now shows
Scope research watches, arming and fee-inclusive sizing with separate stale-time
labels; reads never refresh evidence or grant execution authority.
It now exposes selected original/latest quality, profile and obstruction evidence,
with input/policy hashes and latest-action/receipt binding. Missing or altered
bindings make the report unavailable; saved passes never replace missing latest reviews.
[Scope research lifecycle replay](OPTIONS_SCOPE_REPLAY.md) now runs frozen ordered
watch/arming/admission/advance/reset fixtures through a create-only native owner,
retaining action receipts, explicit rejects and independent state. It supplies no
orders, model calls or Scope economic result. Native execution replay uses its separate contract.
Portable JSON verification now reproduces the frozen request in temporary independent
state and compares all action receipts and final evidence. It requires the original
request hash retained separately, never opens source journals and grants no authority.
Reproduction proves consistency with the installed rules, not provider authenticity.
The common engine now blocks generic OPEN_LONG preparation and dispatch for these
research cohorts while preserving HOLD and owned/protective exits.
[Stored native position outcomes](OPTIONS_POSITION_OUTCOME.md) now reconstruct
verified fills, fees and linked entry/management charges; incomplete links or costs
withhold the net outcome. New native buys from selected opportunities now freeze
Degen/Swing family and candidate identity in intent and approval; dispatch rechecks that evidence and
closes/management attribution inherit it through the exact entry. Historical
unlabeled orders remain unlabeled. New native closes bind the exact owned entry in
intent and approval; dispatch rechecks that identity before any attempt. Legacy
unlinked closes are not backfilled. Cash-settlement and worthless-expiry outcomes
now derive entry attribution from complete native accounting replay, retaining
fees and all entry/management charges. An opt-in
[native account loss guard](OPTIONS_NATIVE_LOSS_CONTROL.md) now consumes verified
outcomes once, enforces a recognition-time cooldown and preserves threshold lockout
across restart/global resume. A separately signed reviewed reset now requires the
exact revision, expired cooldown, verified outcomes and fresh flat account evidence;
it preserves economic history, global limits and any global halt.
Paid entry-model admission now enforces this loss guard before recording a call;
expected pauses complete the coordinator slot as HOLD without a new global halt.
Validated owned-position management retains its separate admission and all costs.
New frozen cohorts can additionally enroll independent Degen/Swing loss streaks,
cooldowns and locks derived from verified native entry lineage. Signed targeted
family resets preserve account-wide and other-family guards, history and all costs.
Paid entry advice pauses when every stored candidate family is paused; mixed
packets still face independent preparation/dispatch checks. This does not enable
Scope or its family-scoped reset. Data/host costs remain in the session economic report.
Enrolled replay owners now refresh risk before saving each closing snapshot.
Native export retains audit-bound loss state, consumed-entry economics/lineage,
entry pauses and reset receipts across independent A/B/C/D session boundaries.
Portable reports bind policy and history while labeling this as stored evidence.
[Native whole-contract partial closes](OPTIONS_PARTIAL_CLOSE.md) now let a new
frozen PAPER cohort retain an owned runner through the same governor and journal.
Exact requested/approved/fill quantities, all fees and linked model costs persist;
mandatory protection preempts unattempted scales and preserves attempted orders.
[Frozen native target schedules](OPTIONS_TARGET_EXITS.md) now add entry-bound
allocations, durable target progress and automatic whole-contract sales through
the same protection, governor and fill accounting. Restarts retain pending orders;
attempted failures require review. Partial entries are not silently reallocated.
Optional frozen target stops now tighten effective invalidation on fresh target
evidence, preserving stricter existing stops, exact rebound triggers, order
reservations and restart state. No underlying target touch claims an option profit.
New frozen v2 target schedules also represent stop-only milestones with zero sale
quantity, preserving protection at objectives with no scale allocation. Version
binding, native fills, full costs and Scope entry restrictions remain enforced.
Native export and portable replay now retain open target-managed positions without
mistaking saved target progress for changed ownership. Frozen schedules, original
entry basis, actual holdings and all costs remain checked; open boundaries remain
inconclusive with no net return or invented closing valuation.
[Executable premium trails](OPTIONS_PREMIUM_TRAIL.md) now preserve the completed
entry's actual premium basis and fresh bid peak across partial exits and restart,
with native mandatory exits and stored-only attribution/observer evidence. All
entry/management costs remain charged; premium floors are not net-profit claims.
[Native whole-trade floor previews](OPTIONS_TRADE_FLOOR.md) now derive remaining
sale requirements from complete original entry fills, actual partial-sale proceeds,
all recorded execution and attributable model charges, and conservative future exit
fees. The read API retains false authority. New frozen owners can explicitly enroll
`native-target-floor-v1` to enforce 0/10/25% reference floors after native target
touches, using fresh bids adjusted for conservative slippage and tick rounding.
Accepted fill-price floors never decrease after sales, restart or later uncertainty.
Unknown costs withhold new arithmetic and block scale-outs while retaining prior
floors and independent mandatory exits. Attempted orders retain their reservations.
Original enrollment, stored state, native export and independent A/B/C/D cost
attribution remain bound; data/host costs stay in session reports. This enables
no new target geometry, Scope entry or full-entry AI target schedule.
[Observed Greek pressure](OPTIONS_GREEK_HEALTH.md) now supplies explicit units,
provenance and source/receipt times for quote-bound delta, theta and IV evidence.
The stored observer compares valid observations against the original entry quote;
missing, stale, estimated or conflicting data never becomes a healthy/zero input.
Sealed tapes prevent future Greek observations, and native A/B/C/D replay retains
all entry/management charges. These are diagnostic source components, not the full
health score, stop policy or exit authority.
[Durable observed progress](OPTIONS_PROGRESS_HEALTH.md) now binds original approved
underlying risk geometry and completed actual entry premium to per-entry peaks,
target progress and last-progress times. Partial sales and restart preserve them;
missing, conflicting or gapped observations cannot invent stall coverage. Exact
stall/divergence/giveback diagnostics are audited with supervision and exposed by
stored-only observer reads. Every execution and entry/management cost remains in
native accounting; premium diagnostics do not claim net returns.
[Observed daytrade health](OPTIONS_HEALTH_MANAGEMENT.md) now composes those inputs
with native spread/session evidence in an explicit frozen PAPER policy. Complete
inputs can tighten pre-target stops or latch governed health exits; incomplete data
withholds new actions while preserving independent protection. Rechecks, restart,
attempted-order reservations, native attribution/export and independent A/B/C/D
cost accounting remain bound. Swing and longer-dated contracts are excluded;
unverified free-form regime labels and stale-price action rules are not adopted.
Authentic health evidence and prospective policy performance remain unverified.
[Scope management plans](OPTIONS_SCOPE_MANAGEMENT.md) now preserve the source
balanced allocations for one through three owned contracts and explicit profile
premium limits beneath the owner ceiling. A new-cohort native entry premium
protector retains those tighter terms through fills, scales, restart and attribution.
Four-contract Scope allocation remains blocked because locked geometry lacks T3;
the generic source fixed-R fallback is not adopted. Native responsive/balanced
one-to-three-contract execution, management and full-cost loss/cooldown linkage are
connected under explicit new-cohort enrollment. Convexity remains blocked without
its complete-path evidence.
Authentic collection/coverage and prospective economic evidence remain open.
Optional Scope observed-quote cohorts now retain original-stop/second-objective
terminals before admission readiness checks, preventing recovery from reviving the
same unfilled watch. Exact quotes, geometry, receipt time and owner-limit hashes
persist through restart, observer reads and reproducible research replay. Invalid
quotes reset holds without inventing terminals. Research books cannot bypass the native entry guard.
Report capabilities and gates, not completion percentages.

## Goal and definition of completion

Build one autonomous reasoning trader that can select **US stocks/ETFs or purchased
options**, manage one position and remain in cash when evidence is weak. Adapt
SignalFlow's Degen/0DTE, Swing and Scope Wizard strategies and interface into this
smaller auditable engine. Deliver PAPER validation, then a concrete governed path
to limited LIVE operation. Trading capability and profitability are separate:
completion means verified bounded operation, not guaranteed gains or a promised
daily income. SPY remains the economic benchmark.

The user approved the expanded stocks/options and eventual LIVE goal. The initial
single-leg options scope, milestone contracts and UI layout below are working
engineering decisions for delivering it. Actual LIVE capital/loss limits, account
capability and activation remain unresolved. This document does not authorize real
broker writes or silently replace the deployed experiment's configuration.

The [reasoning-trader research and completion plan](AI_TRADER_RESEARCH_PLAN.md)
defines the requested stronger AI role, source comparisons, decision contract and
P0–P8 delivery packages within these milestones. This is the working design for
new cohorts; the delivered SELECT/HOLD model remains unchanged. The
[full entry-plan path](OPTIONS_ENTRY_REASONING.md) now has local fixture proof
through durable PAPER execution and independent protection, alongside that arm.

This document owns current scope and implementation order. Latest explicit user
instructions take precedence. The October 18 direction is to finish remaining
strategy/engine implementation efficiently, then perform UI and authentic data/model
integration as the final validation pass. Only concrete blocking dependencies
should interrupt implementation; this does not waive any acceptance gate. README is
the entry point, research explains the decisions, and status/evidence documents
record observations. Older stock-only
continuations remain historical. Code describes delivered behavior; a future goal
in this file must never be reported as implemented code. Record any discrepancy as
a blocker instead of quietly changing the plan or relabeling results.

## Rules that stay settled

1. HOLD is an ordinary, auditable decision. No minimum trade count, forced entry or
   threshold relaxation to make the bot look active.
2. The model proposes from supplied evidence. Deterministic software owns approval,
   rejection, quantity, exposure and exits. The Trader Agent has no broker tools,
   credentials, recovery authority or permission to alter risk settings.
3. One trader, one bankroll, one brokerage and one position across all setup families
   and instrument types. Several contracts of one approved option identity can be
   one position; different strikes, expiries or stock/options holdings cannot become
   hidden extra positions. Unresolved orders retain reservations and block new entry.
4. Initial options support is fully paid **long calls or long puts**, with sells
   limited to closing owned contracts. Bearish underlying direction is not short
   stock or permission to sell an opening option. No naked selling, multi-leg spreads,
   borrowing, averaging down, futures, crypto, OTC or penny stocks. Purchased options
   still have embedded exposure and can lose their entire premium.
5. Default PAPER; existing LIVE remains disabled. Real-account SHADOW retains its
   governed equity-review-only boundary. Options previews need their own validated
   schemas, account capability and deterministic admission. No generic tool allowlist
   expansion or automatic promotion to real orders.
6. Original invalidation cannot widen. Model HOLD, timeout, service restart or a
   rebound cannot erase an exit requirement. Supervision, halt controls and alerts
   operate independently of model judgment. Unknown fills/costs never become zero
   or assumed success; ambiguous attempts never automatically replay.
7. Freeze population identity, prompt/model, setup, selection, money/risk policy,
   execution assumptions and measurement versions. Changes create reviewed new
   populations or explicitly versioned future cohorts. Do not optimize from one day.

## Current delivered state and populations

| Population/surface | Actual state | What it cannot establish |
| --- | --- | --- |
| Deployed `virtual-v1` | Frozen $10 synthetic stock experiment on release `de5dd1c7bd3a2d3b85a2d6bb7f624e0d3a3f9245`; operator provides regular-session decisions, usage and simulated fills | Real broker fills, options behavior, useful signal, newer engine acceptance or profitability |
| Isolated execution engine | Durable fake-venue orders/model attempts, reconciliation, budgets, supervision, reviewed control/recovery, alerts, checkpoints and archive contracts implemented and tested locally | Actual target-host installation, authenticated full-universe/model evidence, independent archive retention or host-loss acceptance |
| Options foundation | M1 admission and M2 durable local fixture lifecycle with whole fills, reconciliation, independent exits and explicit settlement implemented and fixture verified | Authenticated options integration, mixed runtime PAPER readiness, provider/host acceptance or live safety |
| SignalFlow reuse | 60 pinned reference files audited; reusable strategy/UI concepts; draft management fixes distinguished from main | A ready live adapter, healthy deployed options feed or a replicated profitable strategy |

The legacy $10 population remains untouched. New options PAPER execution uses a
separate named identity and databases, with explicit virtual capital and limits.
Research comparisons may use separate simulated ledgers; they never grant several
owners access to a funded brokerage account. Do not reset, retune, pull or rebuild
the deployed SHADOW checkout. Its helper selects images by HEAD.

Operator target-host evidence now establishes the separate installed validation
release's 1,815-test pass and all eight disposable credential-namespace probe cases.
This closes those specific host compatibility/probe gates. It does not establish
the fixed production service topology, actual application boot/lifecycle,
independent alerts/archive or host-loss acceptance. No options trader was started;
M5 remains incomplete. See [the exact evidence record](SLICE2_STATUS.md) and
[read evidence procedure](OPTIONS_READ_CAPTURE.md). Authenticated six-tool schema
discovery is now operator observed and its supplied schema digest locally verified.
Zero market reads were completed; actual samples, normalization and latency remain open.

The [second operator report](SHADOW2_EVIDENCE.md) shows cumulative net equity
$9.95992452597485, net return -0.4007547402515%, SPY -0.453936060819% and net excess
+0.0531813205675 percentage points. It contains one new XLE round trip with
$0.0004482945831 price profit, while cumulative model costs increase $0.0139332.
Latest state is flat. This is another operational sample, not a reason to promote
or modify the frozen experiment.

## Instrument, evidence and risk contracts

Keep existing equity types compatible. Introduce explicit option identity containing
broker-independent contract ID, underlying, call/put, strike, expiry, multiplier,
deliverable, exercise style, settlement type/time and last trading instant. Provider
and broker identifiers map to that identity; a ticker or OCC string alone cannot
override conflicting metadata. Initially reject unsupported adjusted deliverables.

Quotes bind that exact contract and source feed, bid/ask/size, source and receipt
times, entitlement, coverage and delay status. Store underlying evidence separately.
Reject stale, future, crossed, missing or unsynchronized inputs using frozen limits.
Observed and estimated IV/Greeks remain labeled. No timestamp invented from the
current clock, indicative quote presented as executable truth, or current chain
substituted into historical evidence.

Money uses Decimal and option quantities are whole contracts. Software selects the
largest integer quantity that fits **all** frozen quantity, entry debit, available
settled funds, full-premium loss and account exposure caps, including conservative
fees/slippage. A planned stop-loss estimate is a separate diagnostic, never a
guaranteed worst-case loss. Quantity zero means HOLD/rejection; never round up to
afford one contract. Do not copy the legacy MICRO tier's 8% modeled risk and 50%
drawdown shutdown into LIVE options as presumed approved limits.

Underlying bullish/call and bearish/put geometry differ. Freeze original underlying
invalidation separately from premium catastrophe/time rules. One contract cannot
partially scale out. Stops and MFE defense may tighten under deterministic rules;
neither a target touch nor an estimated Greek creates a fill. PAPER buys at eligible
ask plus configured adverse slippage, sells at eligible bid minus slippage and
accounts for observable size. Missing bids retain unpriced exposure and alert/halt
state. Protective handling must follow the reviewed venue policy, not fabricate
a close or wait for the model to become available.

Expiry requires actual exchange calendars and broker cutoffs, including half days
and AM/PM settlement. Separate expiration, cash settlement, broker liquidation and
exercise-created holdings from ordinary fills. A put cannot silently become short
stock; a call cannot create an unaffordable stock holding. Any unexpected exposure
halts admission and needs authoritative reconciliation. No real exercise/cancel/
placement action is added under this documentation task.

## Strategy and model contract

Degen, Swing and Scope feed one candidate selection boundary. They do not control
bankrolls, quantity or independent execution workers. First adapt a small liquid
SPY/QQQ Degen set: opening-range continuation, VWAP/trend pullback and explicitly
confirmed failed-break reversal. Use completed 5-minute/15-minute structure for
initial signal evidence; faster position supervision is a separate safety cadence.
Freeze both cadences in the new cohort. Do not change the old 15-minute scheduler.

The October 12 clarification reinforces one shared engine and AI selection boundary
for Degen and Swing. The new opt-in shared PAPER slice now implements that boundary
with one ledger/order reservation/model budget, preserving separate research accounts.
Family-specific evidence and holding rules remain explicit. Scope now has separately
enrolled native PAPER execution/loss integration for responsive/balanced one-to-three-
contract plans. Its research watches remain order-free unless enrolled under the
native contract. Convexity and missing-T3 four-contract plans remain blocked. Mixed
stock/options ownership now has a separately enrolled [native fixture owner](MIXED_NATIVE_OWNER.md);
paid mixed contracts, continuous runtime and independent mixed
replay/export now have separate complete native fixture enrollment. New
[deterministic Scope/Degen/Swing arbitration](OPTIONS_SCOPE_ARBITRATION.md) now selects
from bound native candidates in one owner,
with immutable alternatives/selection, fresh dispatch gates and full-cost portable
accounting. Shared Scope entry AI now binds full paid decisions, fresh owned
approval and trade-level cost attribution. Shared Scope position reasoning now
binds original native terms and current Scope context. Common Scope observations
and independent native watch replay are fixture implemented. Independent single-session
A/B/C/D trading replay/export and continuous watch/runtime inputs now have fixture
proof. Combined Scope/Swing carry now has explicit native entry/management/runtime
and stored export contracts. Session-close Scope series now preserve independent
accounts, frozen scripts, closing evidence and full costs. Combined carry replay/export now has a separate frozen series contract;
mixed model/runtime/replay now has complete separate enrollment and native fixture
integration. Existing cohorts stay frozen.

Swing retains completed higher-timeframe bars, exact contract locking, next actual
exchange session, catalyst/earnings clearance, chase and invalidation geometry.
Scope retains the approved V2 SPX/SPXW identity: exact 0DTE, SPX setup authority,
SPY/QQQ confirmation and its documented continuation/reversal modules. Missing SPXW
capability or data blocks Scope; no disguised SPY or 1DTE fallback. Source score,
time, debit and loss settings are research baselines, not automatically suitable
live bankroll limits.

Initial option order intents are single-leg DAY limits with valid contract tick
increments and a fixed approved price/quantity ceiling. A timeout cannot trigger
automatic market conversion, cancellation/replacement or a second submission.
Any later repricing workflow needs separate deterministic authority and evidence.

Store setup observations, eligibility, input availability and exact blockers.
The current legacy collector deliberately omits relative volume; the new cohort
needs real point-in-time volume evidence if an ORB rule requires it. Optional flow/
dealer features remain optional until coverage and incremental value are measured.
Do not import the entire SignalFlow OPRA/Redis service graph to add a few features.

The delivered deterministic selector and bounded SELECT/HOLD model become comparison
arms A/B. The entry reasoning implementation adds evidence-linked thesis, contract
choice and geometry within frozen family limits (arm C). P3 now has [MAINTAIN/EXIT_ALL/TIGHTEN proposals and a bounded model worker](OPTIONS_POSITION_REASONING.md)
for the exact held position, connected to durable costs and atomic stop/full-exit
application in a separate opt-in cohort. Arm D replay/export and stored
proposal/approval/fill attribution now extend the fixture comparison. This is a
larger strategic role while deterministic software retains sizing, admission,
execution and mandatory exit authority. Full contracts, source rationale, event
bounds and acceptance are in [the research plan](AI_TRADER_RESEARCH_PLAN.md).

The AI receives verified bounded evidence and no tools. It cannot invent contracts,
change strategies/risk policy, widen original/effective invalidation, postpone an
exit, add to a position or renew a deadline. Mandatory protection wins races with
model advice. Unknown usage still halts new risk. Compare equivalent capital, data,
timing, governor and fill assumptions, retaining all costs and incomplete outcomes.
No model name or subjective confidence is adopted as proven alpha or probability.
New roles, prompts and management create separate frozen populations. The old
experiment and existing SELECT/HOLD cohorts remain unchanged.

## Milestones, dependencies and acceptance

M1 is fixture verified; [its implementation contract](OPTIONS_ADMISSION.md) records
the offline API and limits. [M2 local lifecycle core](OPTIONS_EXECUTION.md) is fixture
verified, with conservative regular-hours calendar and explicit receipt boundaries.
The [first M3 Degen execution path](DEGEN_PAPER.md) has local fixture proof.
The [headless options schema/sample acquisition](OPTIONS_READ_CAPTURE.md) is fixture verified.
The [optional candidate model selector](OPTIONS_MODEL_SELECTION.md) also has fixture/native
proof. The [first M4 stored options observer](OPTIONS_OBSERVER.md) has fixture/native
proof; browser visual acceptance and matched cost/benchmark/cohort evaluation remain open.
**The settled P7 strategy/engine plumbing is connected with native fixture proof.
P1 actual bounded market samples and exact normalized collection remain required
for the final integration validation pass; P2 full-plan entry has local durable
integration proof. P3 has a supplied-evidence
accounting evaluator, sealed shared tape, native first-session journal export and
scripted A/B/C replay scheduling with multi-session state/export and explicit
settlement. Position reasoning now has opt-in durable attempts/costs and atomic
once-per-revision action consumption with independent protective-exit precedence.
Arm D replay/export and stored attribution are implemented for independent accounts.
The eligible long-underlying baseline is implemented as a separate offline account.
Optional whole-session primary-arm diagnostics are implemented. Remaining P3 gates
include justified inferential coverage and frozen prospective evaluation evidence;
P4 now has a continuous local normalized-fixture runner with independent protection,
recorded slots/runtime state and stored observer integration. A separately keyed
local operator recovery inbox now preserves exact review revisions, receipt replay
and unknown-cost/order/runtime gates. Runtime starts now retain bounded installed
application identity, with a stored-only observer projection. P1 actual provider
capture and P4 authenticated/host/visual runtime acceptance are still open.** Schema discovery has passed its narrow
gate. Actual read/model usage,
latency, P3 comparative evaluation and P4 runtime acceptance remain open. Each milestone
ends with reviewed code, meaningful tests, status proof, commit and branch push.
Milestones are acceptance contracts, not fixed session or calendar promises.

| ID | Deliverable | Required proof before marking delivered |
| --- | --- | --- |
| M0 | Source audit and authoritative scope | Pinned SignalFlow sources, primary broker/data/strategy research, evidence limits and this document. The October 10 requested AI-role research/design pass P0 is recorded separately and complete as a plan, not a runtime gate. |
| M1 | Broker-neutral option identity and deterministic admission | Positive call/put approval plus rejection of identity/expiry mismatch, bad timestamps/quotes, unsupported deliverables, fractional/unaffordable quantity, wrong-side closes, duplicate position and exceeded full-premium/account caps. Equities regressions pass. No broker writes. |
| M2 | Option PAPER lifecycle in the durable engine | Cash/contract conservation, whole partial fills, unknown acknowledgments, no replay, restart/reconciliation, original-stop and model-independent exits, single-contract allocation, half-day/expiry/settlement and unexpected underlying exposure. No assumed flat state from missing history. |
| M3 | Degen candidates, reasoning proposals and real option-read boundary | Versioned setup/contract selection, bounded evidence-linked entry/management proposals with independent deterministic authority, and HOLD reasons; candidate-first bounded collection and held-contract supervision. Fixture proof first, then authenticated exact-universe/source/latency/entitlement evidence. Optional governed preview is separate from writes. |
| M4 | Integrated observer and experiment evaluation | Read-only stored opportunities/position/health/history, truthful stale/unknown/error states, visible mode/cohort/costs, desktop/mobile checks. Browser reads cause zero model/provider/order work. Model-off/on and SPY/cash/eligible-underlying comparisons preserve point-in-time inputs and all costs. |
| M5 | Actual isolated-host PAPER acceptance | Installed verified package on a separate namespace/population, boot/lifetime ownership/shutdown/orphan tests, independently delivered alerts, actual off-host archive retrieval and source-host-loss evidence. Matching metadata or local TLS/process fixtures cannot close it. |
| M6 | Concrete single-broker LIVE release review and bounded canary | Account identity/product/settled funds/fee/cutoff/approval settings; reviewed order identity and authoritative partial/terminal/unknown evidence; explicit capital/per-trade/full-premium/daily/drawdown limits; independent supervision and halt/alerts; approved release and explicit real-write authorization. LIVE stays disabled until these are satisfied. |
| M7 | Swing and Scope completion on the shared foundation | Each family's frozen setup/contract/management and UI behavior, authentic required data, calendar/overnight or SPXW cutoff/exposure proof, separately measured cohort and explicit mode eligibility. Family-specific failure never redirects into a different strategy. |
| M8 | Visually polished trading dashboard | Cohesive visual system; clear equity/benchmark, opportunities, AI thesis, exact position/protection and decision/fill timeline; truthful stale/unknown states; desktop/mobile visual, keyboard and contrast acceptance. Functional UI arrives in M4; this dedicated finish is required for product completion, not a new live-authority surface. |

Dependencies: M1 before M2; M1/M2 support M3; M4 consumes their stored evidence.
Prepare the existing M5 host acceptance procedure while offline implementation
continues, rather than making more host abstractions. M6 requires the selected
family's M1–M5 operational gates. M7 can develop after M2 in parallel with later
acceptance work; completing every strategy family does not gate a first reviewed
Degen canary. The complete requested product includes all three families and the UI,
with each live-enabled family separately accepted. M8 completes the requested
visual product quality after functional M4 integration; it can proceed alongside
strategy acceptance and never changes trading authority. This turn does not enable them.

Robinhood remains the first capability investigation because it is the existing
brokerage. Current documentation is recorded in the [research](OPTIONS_LIVE_PIVOT_RESEARCH.md).
If it cannot provide the needed account/product/data/order semantics, record the
specific failed requirement and select one alternative before funded integration.
Do not build several live adapters or switch brokers on outdated public assumptions.

## UI acceptance contract

Reuse SignalFlow's information hierarchy, not its whole frontend/runtime:

- Overview: mode, actual release/population, bankroll/net equity, one owned position,
  pending/unknown orders, session, worker/supervisor heartbeat and alert health.
- Opportunities: Degen/Swing/Scope families, exact candidate contract and setup,
  eligibility, evidence time and reason for HOLD. No fake default opportunities.
- Position: strike/call/put/expiry/multiplier/settlement, underlying invalidation,
  premium bid/ask/size/age, whole quantity, debit, full-premium exposure and stop estimate.
- Management: distinct thesis, contract and execution/data health, original/tightened
  stop, time/expiry requirements and deterministic action reason. Main SignalFlow's
  midpoint/last fallback must not be copied as executable sale truth; draft #102's
  principles require deliberate adaptation and testing.
- History/evidence: proposals versus approvals versus fills, scheduler coverage,
  HOLD/reject/error counts, all model/venue/data/host expenses, net results versus
  SPY and immutable versions. Stale last-known values keep a visible timestamp.

Viewing the observer reads bounded persisted records only. Research runs and signed
operator actions are separate explicit controls with receipts. A dashboard demo,
saved automation setting or healthy web process does not certify trader health.

### Dedicated dashboard finish (M8 / user step 8)

Build a distinctive, cohesive dark dashboard with restrained accents, readable
charts, deliberate spacing/typography and clear desktop/mobile hierarchy. Lead
with mode, bankroll/net equity versus SPY and health; follow with opportunities,
the AI thesis and its uncertainty, exact held position/protection, and a decision
timeline distinguishing proposal, approval, order and fill. Explain HOLD visibly.
Costs and data age must stay legible rather than hidden behind decoration.

Before visual acceptance, verify realistic populated, empty, stale, halted, unknown
cost/order and long-text states at desktop and mobile widths, keyboard operation,
contrast, chart labels and no clipping. Retain screenshots and review actual
rendering. Design polish cannot imply live data or profitable results; dashboard
reads stay side-effect free. Existing server-rendered fixture tests alone do not
close this milestone.

## Economic evaluation and live progression

Keep an experiment ledger of every planned/completed/missed slot and candidate,
including HOLD, missing data, rejected entries and unknown receipts. Cost estimates
and invoices are different evidence. Exclude incomplete option paths from measured
returns without hiding the excluded denominator. Store every attempted research
configuration and use chronological development/validation/untouched evaluation,
avoiding leakage across overlapping holding periods.

Report net cash-conserving returns versus matching SPY and cash, model-off results
and eligible underlying-only signals; include spread, slippage, venue fees, all model
calls and allocated data/host costs. Separate setup selection, option selection and
management contributions. Report session drawdown/tail losses, regime/time
concentration, uncertainty and coverage. Never infer option alpha from stock OHLC,
score saturation or a profitable-looking mark.

Funding and withdrawals are external capital flows, never strategy profit or a
reason to erase losses. Freeze the cohort's funding policy; if flows are allowed,
use a contribution-adjusted benchmark or suppress the raw return comparison until
it is valid. Do not quietly increase funding to make a one-contract trade eligible.

Operational acceptance can support review of a small supervised live **research
canary**, with explicit loss limits and acknowledgement that profitability is
unproven. It does not justify autonomous scaling or a claim of demonstrated alpha.
Broader production/scale needs credible held-out net economic evidence and a
separate reviewed decision. No automatic transition, magic trade-count threshold
or model-led capital increase. Concrete broker actions, real-write code and release
activation require explicit instructions beyond this plan-only turn.

## Open inputs and stop conditions

Missing inputs for later LIVE review: the intended funded bankroll and acceptable
full-premium/per-trade/session/drawdown losses; actual account options permissions
and account restrictions; required real-time data entitlement; secure target-host
and independent archive/alert access. The remembered personal trading balance and
the frozen $10 simulator are not approved new funding amounts. Credentials never
belong in chat or Git. Offline M1/M2 work can proceed without these inputs.

Stop new entries on incompatible identity, stale/incomplete data, exhausted or
unknown budgets, unresolved orders, mismatched account truth, failed supervision,
alert backlog, ownership/recovery fence or unsupported exposure. Retain the reason
and unresolved evidence, alert independently, and apply only already approved
protective handling. Reopening a page or restarting a process cannot resume trading.

## Continuation discipline and completion reporting

Before editing, recover fresh GitHub branch/main/PR references and relevant current
code/documents. Use `slice2/robinhood-read-shadow`; main stays untouched and PR #1
draft until its verification gates are satisfied. Keep the frozen deployment separate.
Read this file first after README, then current status and the next milestone's code.
Do not restart strategy/broker research unless a specific implementation question,
changed primary evidence or explicit user direction requires it. The requested
October 10 AI-role pass is complete as [P0](AI_TRADER_RESEARCH_PLAN.md); continue
through its bounded delivery packages, not another open-ended research cycle.

Every slice must deliver a milestone capability or reproduce and close a concrete
blocker to it. Record the failing case, fix and acceptance evidence. Generic
hardening without such a requirement leaves the queue. Avoid micro-check turns,
repeated approvals, whole-suite reruns for document-only edits and setup churn.
For application changes, run appropriate behavioral/regression and installed-package
checks, broaden only for unresolved concerns, and push verified branch changes.
If credentials/host access block acceptance, bundle the necessary operator evidence
into one useful procedure and continue independent code work.

Update milestone status as **not implemented**, **fixture verified**, **provider
verified**, **host verified**, or **live canary accepted**, with commit/test/evidence
references. These states are not interchangeable. A passing local test never grants
provider, deployment or profitability proof. Preserve source/operator evidence
separately from our own observations and record failures openly.

Current milestone state: M0 research complete; **M1 fixture verified** with
`app.options.models`, `app.options.governor` and `tests/test_option_admission.py`.
**M2 local lifecycle core is fixture verified** with `app.options.engine`, its separate
durable local venue and `tests/test_option_execution.py`. See [OPTIONS_EXECUTION.md](OPTIONS_EXECUTION.md)
for proof and precise boundaries. **M3's completed-bar Degen/contract selection and
durable PAPER coordination are fixture verified** with `app.options.degen`,
`selection`, `coordinator` and `tests/test_degen_options.py`; see [DEGEN_PAPER.md](DEGEN_PAPER.md).
Its separate headless schema/sample capture also has fixture/native process proof;
see [OPTIONS_READ_CAPTURE.md](OPTIONS_READ_CAPTURE.md). It produces evidence only,
not an execution feed. [Optional bounded model selection](OPTIONS_MODEL_SELECTION.md)
also has fixture/native proof, including durable usage, HOLD and original admission
ceilings. The [first M4 stored observer](OPTIONS_OBSERVER.md) has fixture/native proof
for opportunities, exact positions, management, order/fill distinctions and unknown
costs. M4 browser visual acceptance and full economic/cohort evaluation remain open.
M3 authenticated normalized collection/model acceptance and M5–M8 are not complete
for options. M7 now has shared Degen/Swing PAPER candidate arbitration and a first
locked next-session daily-breakout adaptation with session-close protection.
Native bounded Swing carry and deterministic shared Scope selection now have
fixture integration. Shared Scope paid entry/management, single-session A/B/C/D
tape comparison, continuous runtime inputs and combined native Scope/Swing carry
now have fixture integration. Session-close Scope series now retain independent
accounts, closing evidence and full costs. Combined carry replay/export,
original Swing families and the mixed stock/options native owner, paid contracts,
continuous runtime and independent common-tape replay/export are fixture integrated. Scope
native execution/loss integration is fixture implemented within its explicit profile/quantity
boundaries; authentic provider and prospective performance acceptance remain open. Existing
runtime services still execute equities only; local M2 is not an options deployment.
Some underlying stock-engine/host procedures already exist and are reused, but do
not mark an options milestone complete from that prior work. Report concrete
delivered capabilities, their evidence level, and the next acceptance gate.
Do not use engineering completion percentages. LIVE readiness and profitability
remain unestablished.

## References and evidence checkpoint

- [Reasoning trader research, decision contract and completion plan](AI_TRADER_RESEARCH_PLAN.md).
- [Options/SignalFlow/broker/model research](OPTIONS_LIVE_PIVOT_RESEARCH.md) and
  [pinned source manifest](research/signalflow_options_sources.json).
- [Latest engineering and historical operator status](SLICE2_STATUS.md).
- [Second printed operator report](SHADOW2_EVIDENCE.md); first report remains in status.
- [M1 delivered options admission](OPTIONS_ADMISSION.md).
- [M2 delivered local options lifecycle](OPTIONS_EXECUTION.md).
- [First M3 Degen execution path and remaining collector gate](DEGEN_PAPER.md).
- [M3 private schema/sample acquisition and operator procedure](OPTIONS_READ_CAPTURE.md).
- [P2 entry-plan contract, native worker and durable PAPER integration](OPTIONS_ENTRY_REASONING.md).
- [Arm D replay/export, all-call accounting and stored decision/fill attribution](OPTIONS_MANAGED_REPLAY.md).
- [Paired session accounting evaluator](OPTIONS_EVALUATION.md), [sealed common tape](OPTIONS_MARKET_TAPE.md) and [native first-session A/B/C export](OPTIONS_EVALUATION_EXPORT.md), and [independent replay](OPTIONS_REPLAY.md) with [multi-session state/export](OPTIONS_REPLAY_SERIES.md).
- [M3 optional candidate model selection and cost authority](OPTIONS_MODEL_SELECTION.md).
- [First M4 private stored observer and remaining acceptance](OPTIONS_OBSERVER.md).
- [Isolated runtime](PAPER_RUNTIME.md), [host acceptance](PAPER_HOST.md),
  [bounded model acceptance](PAPER_MODEL_ACCEPTANCE.md),
  [evidence checkpoints](EXECUTION_CHECKPOINTS.md) and
  [independent archive host](CHECKPOINT_ARCHIVE_HOST.md).

Initial planning checkpoint: pre-edit branch/PR head
`a55b6bcf512669a8ebb0afa84fd271ff4deca1ad`, tree
`9399594922eea2ba59a5759281fb0d1ff72e3af2`; main
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft. Source-of-truth/evidence
work changed documentation only. It did not install services, alter application
code, call a model/broker/provider or validate profitability. The current M1
implementation and verification checkpoint is recorded at the top of status.
