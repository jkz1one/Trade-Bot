# Slice 2 — Robinhood READ / SHADOW Status

## Quote-driven simulated fills and dashboard correction: 2026-10-25 UTC

Fresh GitHub and local state matched e6fd3536f1c615542c0fdefd972b21c8651c73f4,
tree `3dd647b87e6059ddb876aed4f3e7b8a78eac5684`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 remains open/draft.
The operator successfully refreshed the separate reader to e6fd353, with 254
installed matches, three historical fills and authenticated frozen-content checks.
The latest populated screenshot identifies disconnected chart endpoints and
colliding active-trade labels. Current presentation changes use explicit dashed
missing-value connectors and a flowing numbered price legend. Missing valuations,
original price terms and source clocks remain unchanged. Updated desktop/mobile
browser review and current-revision Docker acceptance remain pending.

The user requested plumbing for Monday testing. Audit found that continuous native
runtime tests still injected fills manually. An explicit frozen
`mixed-quote-fills-v1` policy now connects validated later delivered quotes to the
existing native simulated venue, reconciliation and independent protection. Tests
cover stock/option entry and exit, size-limited partial fills, receipt aliases,
stale/delayed/unknown-size data, conflicts, expiration, unresolved attempts and
unchanged default policy behavior. No strategy, dependency, deadline, approval,
source retirement or settlement rule changes. The read-only dashboard never calls
this fill path. Reader refresh preserves v1/v2 and both prior rollback containers.

**This is not a connected Robinhood PAPER service.** Exact schema content and market
samples remain unavailable in this workspace; provider normalization, an ongoing
read feed and authentic acceptance remain incomplete. The retained six-tool digest
is `d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15`.
An offline `export-schemas` command safely extracts only that object from the
existing private discovery artifact; no OAuth or provider call is needed to export.
The operator must identify the actual discovery file in the retained private
directory. No authenticated provider/model/broker call, prospective PAPER activation,
new host trader, dependency change or SHADOW deployment change occurred. LIVE is
disabled. [Behavior and remaining connection work](MIXED_QUOTE_FILLS.md).

379 distinct installed Python cases and 14 JavaScript cases passed. All 255
application/template files match source, wheel and installed bytes. Wheel SHA-256:
`2cb437f56ae9dfe230c35496654a02cc118f8865d57d572e14bdadb4376ed14f`.
Source/wheel/installed byte identities,
exact test identities and screenshot hashes are retained in
[MIXED_QUOTE_FILLS_PROOF.json](MIXED_QUOTE_FILLS_PROOF.json). Native tests run serially
from copied tests outside checkout with Python `-I`, warnings as errors, plugin
autoload disabled and explicit anyio. The first focused run exposed a test's wrong
expectation: native reconciliation legitimately resolved UNKNOWN to OPEN while
retaining its halt. Only that assertion was corrected; no engine safeguard changed.
One initial broad-run collection referenced a nonexistent test filename and ran no
cases; it is not counted as a pass.



## Dashboard visual balance and successful v2 host receipt: 2026-10-24 America/New_York

Fresh local/GitHub HEAD matched `c2ad7ca22a1902dde9365eed475d004737bdbda7`,
tree `3da19862e364d1fa5d75b34c0f08e0f543a557f6`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 remains open/draft.

The operator completed v2 preparation and dashboard activation: 254 matching
installed application files, three native simulated fills, $803.64 cash and
$1,001.87 historical equity. Startup curl resets resolved within retries;
health, private authentication, frozen mode and unchanged SHADOW service checks
passed. Two populated desktop screenshots are now baseline visual evidence.
V1 is preserved; cc990cf remains as the first rollback container.

At the user's request, the top cards now share a row height; lower navigation
sits above the decisions/activity cards, which share top/default bottom edges.
Activity shows three rows and expands independently. Developer-oriented prose is
trimmed, identifiers/JSON moved under System and simulation/protection/cost/stale
meaning preserved. Only presentation code changes. The guarded refresh reuses v2
read-only, preserving both existing journals and a separate c2ad7ca rollback reader.
No fixture replay, new trader, provider/model/broker call, dependency or engine change.

163 distinct installed Python cases and 14 JavaScript cases passed. All 254
application/template files match source, wheel and installed bytes. Four original
wording assertions were updated and rechecked; no data assertions were removed.
[Contract and installed proof](MIXED_DASHBOARD_BALANCE.md). Updated browser review
of this revision, including mobile and expansion behavior, remains pending.

## Native fixture child import correction: 2026-10-24 UTC

Fresh GitHub/local HEAD matched `b9b5134d9e525e619893dd37afb4a51d7868c2a8`,
tree `89e2b5fe6224628f4eeb4d963b649fa45c9ccd6f`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 was open/draft.

The operator's snapshot-only diagnostic against the old 77e69c6 image preserved
both source databases and confirmed exactly one OPEN venue order, zero fills and
submit_count 1. Full worker/engine imports took 4.831 seconds, with Agents SDK
imports accounting for 3.132 cumulative seconds. The snapshot child returned first
stdout at 3.839 seconds, EOF at 4.440 seconds and completed at 4.540 seconds.
This identifies avoidable import overhead close to the five-second native budget;
the exact timing of the original failed attempt was not instrumented.

Only one application file changes: the existing `runtime_lease` import moves from
module initialization to `OptionExecution.open`. The owner still acquires the
same lease before any enrollment/open. Fixed venue children now avoid loading
`app.execution.runtime`/judgment/Agents while using existing engine helpers.
No deadlines, approval/source clocks, intent terms, native admissions, fills,
independent exits, uncertainty halts or full-cost evidence change. No dependency
or strategy change. A fresh-interpreter regression fails on the old installed
wheel and exercises actual snapshot, stock and option acceptance with model/runtime
imports denied on the corrected wheel.

The host helper accepts an explicit `ui-review-v2` destination. It requires the
retained v1 directory and mounts it read-only during recovery preparation; it
refuses any existing output directory. Activation still requires completed native
fixture evidence, installed-source identity, private authentication and the same
old dashboard image/rollback checks. No old attempt is resumed or replayed.
[Recovery runbook](MIXED_DASHBOARD_REVIEW.md).

**373 distinct installed Python cases passed in 188.54 seconds**, serially from
copied tests outside checkout with noneditable wheel, Python `-I`, warnings as
errors, plugin autoload disabled and explicit anyio. All **254 application/template
files** match source, wheel and installed bytes. Wheel SHA-256:
`bea1355ad9c06ee5541883491593c18d9bba6687182c95614bb4e4d48e59c414`.
The local new historical fixture completed with three native simulated fill
receipts; the corrected local snapshot probe completed in 0.624 seconds and
preserved source bytes. This is not a host timing comparison or Docker acceptance.
Exact test identities and hashes are retained in
[correction proof](MIXED_CHILD_IMPORT_PROOF.json). Corrected Docker preparation,
activation and populated browser/screenshots remain pending operator results.
The original de5dd1c SHADOW worker/observer and running cc990cf dashboard remain
unchanged by this workspace work. LIVE, authenticated provider/model/broker calls
and prospective PAPER runtime remain disabled.

## Hybrid stored desk and retained host timeout: 2026-10-24 America/New_York

Fresh GitHub/local HEAD and tree matched `77e69c60d87336e608d17bf6427eddb00a575a33`
and `0e81ffded0d18fc25b468c2374447edb0df0dece`; local checkout was clean.
Main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 open/draft.
The supplied hybrid plan is now the presentation direction; its repeated attachment
is byte-identical. [Contract and mapping](MIXED_HYBRID_DASHBOARD.md).

The mixed UI now keeps equity and trade above five workspace tabs, with local
trade tabs, visible native protection/deadline, record-based chart ranges and
exact-value inspection, family order filters, exact-identity stage links and a
bounded stored activity list. No strategy/engine/dependency change. Missing watch,
continuous equity, mixed benchmark and performance cohort contracts remain explicit.
Only nine application files differ from the parent, all under `app/web`.

Final wheel SHA-256:
`fa2ac508b0abcb24f5c2dc2cfb633862555458d7591f5391f3a55defb9fb500c`.
**163 distinct installed Python cases passed in 90.31 seconds; 14 JavaScript
unit cases passed.** Native tests ran serially from copied tests outside checkout,
noneditable wheel, Python `-I`, warnings as errors, disabled plugin autoload and
explicit anyio. All **254 application/template files** match source, wheel and
installed bytes. Initial collection failed because copied test roots were missing
from pythonpath; no cases ran and it is not included in the pass count. New tests
verify selected-cycle isolation, chart gaps, incomplete-fill withholding, escaped
text, empty-state layout, exact links and diagnostic population isolation.
[Durable proof](MIXED_HYBRID_PROOF.json) retains exact test IDs and hashes.

The operator's previous host preparation failed after native approval and one
accepted simulated venue order. The parent recorded `FixtureProcessTimeout`,
UNKNOWN and `UNCERTAIN_STOCK_ATTEMPT`; venue evidence retained OPEN, zero fills,
submit_count 1 and $1,000 cash. Activation never ran. Worker-only import probes
of 0.818/1.318 seconds do not isolate the original overrun. The partial
`/var/lib/trade-bot-dashboard/ui-review-v1` remains preserved; no preparation retry,
resume, timeout extension or approval change was made.

A new snapshot-only diagnostic copies retained SQLite evidence into private
temporary storage, measures full imports/first stdout/EOF/exit, and verifies source
hashes unchanged. Its installed local probe passed with zero dispatches/fills;
this is not host evidence. The old 77e69c6 image can run the diagnostic from the
updated separate checkout without rebuilding, activating or changing services.

Nine native/synthetic display states generated successfully; these are not browser
screenshots. Actual browser review, populated host activation and the timeout's
underlying cause remain pending. Original SHADOW deployment and password/Caddy
configuration are untouched. LIVE, authenticated provider/model/broker calls and
prospective PAPER activation remain disabled. Main stays unchanged and PR #1 draft.


## Paused native UI fixture and operator deployment receipt: 2026-10-24 UTC

Fresh GitHub/local HEAD matched `cc990cf5dd1b29f14449b3e4b59b98a13b5ead4c`,
tree `efe4afeaadd56e031c2952d4a9b7fe45a762991b`; PR #1 was open/draft and main
remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The operator deployed the separate `cc990cf` reader on loopback 8790, verified
health and authentication, and switched Caddy's existing HTTPS route from 8787 to
8790 after validation. The frozen original worker/observer stayed at `de5dd1c`.
An authenticated 2048×1152 desktop screenshot shows the truthful empty mixed desk
(`DATABASE_NOT_CREATED`). This is actual empty-state browser evidence, not
populated/mobile/keyboard visual acceptance. The [runbook](MIXED_DASHBOARD_REVIEW.md)
retains the exact operator deployment and route-backup details.

The authorized next step now provides a create-only offline native UI fixture:
$1,000 virtual capital, three actual simulated fill receipts, a closed trade,
an open share position and tightened native stop. All source clocks and original
terms remain historical. The explicit observer review clock displays a prominent
paused-fixture banner; ordinary current-clock reads remain stale and withhold
equity. No real feed, paid model, broker, continuous PAPER runtime or collector
runs. Fixture risk settings are not operating recommendations.

Final wheel SHA-256:
`b1549e4cc284d347465f8371aad10d9787d99f5408ffb7d3bb11aaa504d1f682`.
**156 distinct installed Python checks passed in 82.30 seconds**, including six
new cases; **7 JavaScript unit cases passed**. Serial native tests used copied
tests outside the checkout, noneditable wheel, Python `-I`, warnings as errors,
disabled plugin autoload and explicit anyio. All **247 application/template files**
match source, wheel and installed bytes; **245 are unchanged** from `cc990cf`.
Only the web factory and mixed template changed. Lint/format, fatal lint, locked
dependencies, pip consistency, documentation links, shell syntax and whitespace
checks pass. [New proof](MIXED_DASHBOARD_REVIEW_PROOF.json) retains exact case IDs
and identities; prior wheel counts are not added again.

The guarded host helper builds the exact release, creates the fixture with network
disabled, checks native accounting and installed bytes, and retains the old reader
for rollback. It verifies private authentication without printing the password and
checks original SHADOW container identity/start times. Actual populated activation
and host rollback are pending operator execution; no direct host access exists in
this workspace. No dependency, engine or strategy change. Main and PR status remain
unchanged. Authentic acceptance and mixed benchmark presentation remain open.


## Mixed dashboard verification and deployment handoff: 2026-10-23 America/New_York

Fresh GitHub/local HEAD matched `21fb5917bea055826e27b0b686d7c75bc3ee8e18`,
tree `fd51593ad8bf7a5c660b7d0f5ccec7d0646d775d`, with a clean working tree.
The checkpoint's explicit mixed observer now has installed verification. The
[desk contract](MIXED_DASHBOARD.md) documents persistent balance/trade panels,
local tabs, exact original protection and the pinned SignalFlow price-rail adaptation.
This follow-up fixes option order-origin labels, makes an absent original option
revision explicit and requires historical attempted-order coverage even without
fills. Settled engine modules remain unchanged.

Final wheel: `eddd8789e4d5d4cae5389dcb49c187816f7a37cef75ed48d9c926161e832572d`.
**150 distinct passing installed Python cases**, including **21 mixed desk cases**,
and **7 JavaScript unit cases**. The full run passed 149 and failed one new test
because its harness used `e.read()` instead of `e.journal.read()`. The corrected
one-case rerun passed; no application change or reinstall intervened. Durations:
73.86 seconds and 2.52 seconds. An earlier intermediate wheel passed 149 cases;
all overlap the final count and are not added again. The initial checkpoint's
14 passes/two failures are also excluded from final-wheel proof.

All **247 application/template files** match source, final wheel and installed
bytes. **241 are unchanged** from the pre-mixed-UI parent `abdc220`; only the six
mixed observer/CLI/route/template/style/rail files differ. Native tests ran serially
from copied tests outside the checkout, Python `-I`, warnings as errors, plugin
autoload disabled and explicit anyio. Changed-scope lint/format, fatal repository
lint, locked dependency consistency, pip check, documentation links and whitespace
checks pass. No dependencies changed. [Proof manifest](MIXED_DASHBOARD_PROOF.json)
retains exact IDs, wheel-specific runs, file/test/page hashes and limitations.

Nine native/synthetic display states generated desktop/mobile wrappers, with
balanced markup and the installed script. Generation is not browser review.
**No screenshots or visual acceptance**: prior local previews were unreachable and
workspace/file URLs were security-blocked. No bypass was attempted. Mixed SPY/A/B/C/D
comparison presentation and authentic provider/normalization/model/host/economic/
PAPER acceptance remain open; the legacy comparison guard remains intact.

The user's latest instruction now authorizes dashboard deployment. It does not
authorize LIVE or authenticated provider/model/broker calls. Deployment was **not
performed**: no SSH configuration, known-host record, SSH agent or connected host
execution tool is available. The documented existing `signalflow.duckdns.org`
service reads the older SHADOW/virtual-v1 schema, not a native mixed journal.
The [separate observer handoff](MIXED_DASHBOARD.md#authorized-deployment-handoff)
identifies required host access, compatible journal/population/owner and private
route, with verification and rollback steps. Do not run the SHADOW start/build
helper as a mixed dashboard upgrade. Existing worker and deployment remain unchanged.
Main remains `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays open/draft.

Retained proof: `/workspace/scratch/c75087a760c3/mixed-ui-proof/release/`;
wheel: `/workspace/scratch/c75087a760c3/mixed-ui-wheels/release/`.

## Mixed desk recovery checkpoint: 2026-10-23 America/New_York

User requested immediate Git preservation after the workspace disconnected.
Parent: `abdc220cb8755ba6674d7098a5ed17b38c495fb4`, tree
`101683dd1e52a1a5aa2b2af03b19f5b0bb04fcde`. This commit is an **unfinished
checkpoint**, not UI acceptance or deployment approval.

Draft adds explicit `--mixed` observer selection, authenticated `/api/mixed`,
unified stock/options trade cards, native original terms, stored costs, flat-only
balance boundaries with gaps, and a SignalFlow-inspired underlying-price rail.
The existing options-only guard remains intact. Page reads attach no executable
owner and perform no trading, provider or model work. No dependencies changed.

Initial isolated wheel `6a64c7a7687285e068099241718b219d31dcb06b03130717386f379541c4608b`
ran 16 new cases: 14 passed, two failed in 52.97 seconds. The failed expectations
were revised to preserve whole-report Unavailable for an invalid ledger and
unknown fill coverage before a post-attempt snapshot. Subsequent changes retain
costs during incomplete reconciliation, include stored frames, strengthen historical
prefix checks and add the target rail plus four tests. These latest changes have
**not yet passed an installed-wheel run**. A failed text replacement in the
historical prefix function was repaired before this checkpoint. Lint/format and
whitespace checks are not a substitute for the pending runtime tests.

Next: verify the latest noneditable wheel against copied tests, resolve failures,
review actual desktop/mobile browser screenshots, update durable proof and final
continuation docs, then publish the verified follow-up. Main stays
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 open/draft, LIVE disabled and
deployment frozen. Authentic acceptance remains unauthorized.


## Persistent desk, trade card and local tabs: 2026-10-23 UTC

Parent `b22eb1d183627cec64a15e5cb9cb295b915fff3f`, tree
`f24641eb543f228c5ff55a1a899e69bff7729aae`, verified locally and on GitHub.
Main remains `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 remains open/draft.

The [options desk](OPTIONS_DASHBOARD.md) now keeps balance history and an active
native trade card outside locally switched Summary/Trade details/Decisions/Scope/
Fills & costs tabs. The restrained HUD palette uses original thesis, native stops,
exit deadline and stored gross bid value without inventing current marks or net
returns. Chart ranges and benchmark toggles operate only on already rendered
stored values. Tab and chart preferences survive refresh; no-JavaScript and print
fallbacks expose evidence. The same-origin authenticated script has no network or
execution operations. No candle chart, engine change or dependency change.

Installed-wheel proof: 129 distinct passing Python cases (124 initial passes plus
five resolved presentation-label assertions), seven passing JavaScript unit cases,
244 source/wheel/installed identities, 239 unchanged parent files. Changed-scope
lint, fatal lint, dependency lock, pip consistency and whitespace checks pass.
Wheel SHA-256: `bbbcba357fffd726fdc5fe70eea3562d6902ebeaeed7df5a3d819f48a3fe6a3b`.
[Proof manifest](DASHBOARD_HUD_PROOF.json) retains IDs and run boundaries. Prior
proof is preserved separately; these counts do not add overlapping prior cases.

Remaining: actual browser review/screenshots (local preview connection refused),
explicit mixed-account observer and bound original target rail. SignalFlow code
was inspected as a reference, not ported wholesale. Authentic acceptance remains
open and unauthorized. LIVE remains disabled; deployed experiment frozen.



## Dashboard research desk and stored-evidence hierarchy: 2026-10-23 America/New_York

Fresh GitHub and local state matched HEAD
`5d5700db52bde439d364a953aff15d963030e059`, tree
`b194119274fc28579c21a61c5b3626f63c921379`; working tree was clean.
Main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 open/draft.
The settled engine plumbing was not reopened. This is a presentation-only slice.

The [research desk](OPTIONS_DASHBOARD.md) now leads with observed time, fixture mode,
account metrics and saved health. A responsive briefing exposes recorded entry
blockers, source ages, exact owned contract/protection and the newest decision on
this selected family/page. The last item is explicitly historical when applicable,
never current advice. Missing ages stay Unknown, zero age stays zero and unknown
current equity gets warning emphasis. No historical result replaces a missing mark.

Current position and independent deterministic protection now appear before the
long historical decision timeline. Proposal, native review, order attempt and
actual fill stages retain their separate evidence. Model charges retain exact
precision; uncertainty and original thesis remain escaped and available. Exact
historical session costs are in a native disclosure; separate order and fill tables
are open by default. Scope selections do not link hidden option decisions. The
layout adds responsive briefing columns, deliberate metric hierarchy, a timeline,
focusable long-text regions and larger navigation targets without JavaScript.

Validation: **124 distinct final-wheel installed tests**, including **8 new cases**,
passed in 30.82 seconds across dashboard, observer, historical comparison and Scope
observer suites. Native fixture tests ran serially from copied sources outside the
checkout, with Python `-I`, warnings as errors, disabled plugin autoload and explicit
anyio. Existing tests verify authenticated GET-only reads, no trading/provider work,
source byte preservation, unknown/stale accounting, comparison gaps and escaping.
The new mixed-owner guard case reads a real native fixture without changing its
journal or venue and confirms Unavailable without invented account/position values.
An initial runner collection failure omitted the copied test root from pythonpath;
it ran no tests and is excluded. The final runner includes only copied root/tests.

Wheel SHA-256:
`5b0c0f64f3867b09292d0862dc2d20f286b140a882c7e3dc2a42e513fb5ecf79`.
All **242 application/template files** match source, wheel and installed bytes.
Only four templates differ from the parent (three modified, one added); all **238
other application files are byte-identical**, including the settled engines,
observers, exports, authentication and routes. Dependency consistency (60 runtime,
3 build and 6 dev packages), pip check, changed-test lint, fatal repository lint,
document links and whitespace checks passed. No dependency was changed.

The [durable proof manifest](DASHBOARD_REVIEW_PROOF.json) records every final-wheel
case ID, source/wheel/installed identity, copied test hashes, generated-page hashes,
excluded diagnostic and browser failure. Retained raw proof and review pages:
`/workspace/scratch/c75087a760c3/ui-proof/`; wheel:
`/workspace/scratch/c75087a760c3/ui-wheels/final/`. Eight fixture states generated
successfully, with desktop 1360px and mobile 390px wrappers. The portable review
pack includes only those fixed pages, a review index and limited proof, not fixture
databases or credentials.

**Browser/visual acceptance is blocked, not passed.** Actual browser navigation to
local loopback returned `ERR_CONNECTION_REFUSED`; the workspace-host URL then
returned `ERR_BLOCKED_BY_CLIENT`. No policy bypass was attempted. No screenshots,
actual rendering/clipping review, keyboard traversal or browser contrast acceptance
are claimed. The static review pack is for review, not evidence of visual success.

**Remaining UI work:** actual desktop/mobile and user visual acceptance, plus a
separately bound unified mixed-owner observer/comparison presentation. Inspection
confirmed that `OptionObserver` deliberately rejects mixed-owner enrollment; that
guard is preserved rather than relabeling an options report as a mixed account.
This is a UI boundary, not unfinished native mixed engine plumbing.

Authentic provider/normalization/model/host/economic/PAPER acceptance remains open
and was not run or authorized here. LIVE remains disabled, deployment frozen,
main unchanged and PR #1 draft. No provider/model/broker calls, deployment, merge
or strategy/authority changes occurred. Continue the UI gates without reopening
settled strategy decisions.

## Common mixed tapes and independent native replay/export: 2026-10-23 UTC

Fresh GitHub/local state began at HEAD
`1cc4430cdfbca47ac294063c5857a1d51a589981`, tree
`de0c034ef16c35d882186743c4bf4f52ffb778a1`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The [complete mixed replay contract](MIXED_REPLAY.md) now binds common original
stock/options/Scope tapes to four independent native A/B/C/D owners. Frozen source
identity, declaration, family/asset policies and every available source clock are
validated before use. MARKET and Scope-only records cannot hide replacement stock
sources. Old tapes, replay adapters and exports retain their original guards and
serialization.

B has an explicit choice-only full-request contract. C/D share original declared
entry scripts; D adds native position management. Exact mixed enrollment binds the
adapter type, complete request, ordered tapes and script. Original request duration,
account/revision and approval deadlines still govern admission. Every known charge
survives a rejected/late plan; missing usage remains unknown. Native cost recording
recognizes the new B receipt without changing old plan contracts. Option dispatch
recognizes the same choice-only contract while retaining original native exits.

Delivered post-cost reads, original Scope watch actions and actual later source
quotes drive native approvals, attempts and fills. Independent stop/target/time
protection retains original terms. Stock source size cannot be replenished by a new
receive clock. Partial fills and missing exits retain actual exposure. Four native
accounts keep separate capital, cash, reservations, fills and loss history across
sessions; only explicit native receipts settle funds. Carry retains its original
enumerated sessions and deadlines, with overnight coverage left unknown.

Portable fixed-schema export reconstructs original approvals, cash/fills, every
entry/management charge, execution fee, explicit calendar allocation and consumed
full-cost loss outcome. Comparison additionally binds original cycle clocks,
scripted receipts, delivered refreshes, watch revisions, settlement and immutable
session prefixes. Unknown costs and open exposure suppress net results. The
private installed run/verify commands are bounded and create-only; interrupted
runs retain partial evidence without resume or execution authority.

Validation: **676 distinct installed checks**, including **102 new mixed
tape/replay/export cases**. The broad wheel passed 441 cases; the final wheel passed
660, including 86 new cases. Their 425 overlapping cases are counted once.
Only the read-only mixed exporter changed between these wheels; all other 240
application/template files are identical. The final exporter additionally verified
29 retained native comparison bundles, without counting those verifications as
additional test cases. Native execution results from the broad wheel are not
claimed as final-wheel native runs.

| Wheel | Completed phase | Passing cases | Seconds |
| --- | --- | ---: | ---: |
| broad | `native-stock-initial` | 3 | 543.49 |
| broad | `native-operating-final` | 1 | 2.91 |
| broad | `native-option-initial` | 1 | 378.02 |
| broad | `native-option-partial-final` | 1 | 228.01 |
| broad | `pure-final` | 81 | 7.30 |
| broad | `contracts-final` | 342 | 27.52 |
| broad | `native-assets-final` | 3 | 586.25 |
| broad | `native-carry-fixed` | 2 | 765.47 |
| broad | `native-scope-final` | 1 | 449.17 |
| broad | `native-stock-final` | 6 | 1232.55 |
| final | `pure-hardened` | 81 | 7.67 |
| final | `contracts-hardened` | 342 | 29.98 |
| final | `export-hardened` | 2 | 376.64 |
| final | `native-series-final` | 3 | 1034.88 |
| final | `paid-final` | 131 | 634.58 |
| final | `runtime-final` | 92 | 259.03 |
| final | `legacy-replay-final` | 9 | 423.10 |

Earlier diagnostic runs and failed cases are excluded. The initial option run
contributed one passing case; its insufficient-liquidity partial-fill fixture was
corrected and passed in a focused rerun. The initial stock run contributed three
passing cases; a focused passing case verifies the original healthy-owner rejection
for unknown initial operating allocations and retained unknown-cost evidence.
All retained failures have a passing resolution. Tests use copied sources outside
the checkout, noneditable installed wheels, Python `-I`, warnings as errors and
disabled plugin autoload. Native runs are serial.

Final wheel SHA-256:
`398bf595409ecb6feeccbf95a12a91cd472e01297699f9df30a793f49839d0a7`.
Broad wheel SHA-256:
`7cefa44bd040cc27328a209324ab259e1f76870b3835d0e9d2a79564a030a969`.
All 241 application/template files match source, final wheel and installed bytes;
223 parent files remain unchanged. Twenty-nine representative legacy contracts,
including old tape headers, Scope frames and choice-only receipts, serialize
byte-for-byte identically to the parent wheel. Changed-scope lint, repository
fatal lint, document links, dependency consistency and whitespace checks pass.
Full repository style lint retains 306 findings in 52 byte-identical parent files.

The [committed proof manifest](MIXED_REPLAY_PROOF.json) retains exact case IDs,
wheel digests, application-file identities and overlap accounting.
Retained raw proof: `../mixed-replay-proof/` (`final-proof.json` with exact phase/case
lists and durations, completed XML/log pairs and wheel receipts, export-only delta,
retained bundle verification, identity/legacy serialization and lint evidence).
Final wheel: `../mixed-replay-wheels/`; test interpreter:
`../scope-replay-env/bin/python`.
Focused diagnostics fixed B receipt usage/dispatch binding and the serialized
Scope candidate digest. JSON-roundtrip attribution, complete cycle/paid-overlap
coverage, and complete snapshot/order/fill coverage are checked at the new portable
boundary. Tamper tests recompute every enclosing hash and summary export reference;
unowned fills still fail. No original native admission guard was removed.

The settled strategy/engine plumbing is connected: original family sources and
retirement, one mixed native owner, paid entry/management, continuous delivered
runtime and independent common-tape replay/export. No additional settled plumbing
track remains on the continuation list. Final UI/visual and authentic provider
samples, exact normalization, model/host/economic/PAPER acceptance remain open;
fixture proof does not establish those gates or prospective profitability.

Dependencies and main are unchanged. PR #1 remains open/draft, LIVE remains disabled
and deployment frozen. No authenticated provider/model/broker calls were made.
Continue from the acceptance gates when authorized; do not reopen settled strategy
decisions or weaken legacy enrollment to accept new inputs.

## Continuous mixed runtime and native recovery: 2026-10-23 America/New_York

Fresh GitHub/local state began at HEAD
`9064af89063212e33fa3c0ec66943c13a90ac46d`, tree
`717de1061b32d609842836b3ee886842480b5a96`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The [explicit mixed runtime](MIXED_RUNTIME.md) now binds the existing continuous
PAPER runner to one native stock/options/Scope owner. Frozen settings retain the
original stock source policy, paid entry/management and any Scope/option carry
terms. A separate versioned envelope requires complete CYCLE stock coverage,
original available clocks and exact identity. MARKET/WATCH packets cannot replace
original stock source bundles. Old envelopes and unenrolled owners still reject
shares. No old frozen runtime serialization is changed.

Every delivery retains its exact packet/hash, acceptance clock and completion.
Paid refresh waits for completed native protection and uses only delivered evidence;
unread files, rejected actions, interrupted prefixes and halted owners cannot
approve an entry. Scope still requires new post-cost source observations. Full
read-only prefix reconstruction rejects changed receipts without granting authority.

One native snapshot routes protection to the actual held asset. Stock stop/target/
time exits run between decision slots and during slow paid management. Fresh
executable quote observations retire original stock Swing families permanently;
delayed quotes cannot manufacture retirement. The installed initializer binds one
venue balance and exact stock limits; restart does not refund capital or resume
admission. Explicit native receipts settle proceeds across the weekend.

Validation: **673 distinct final-wheel installed checks**, including **23 new
mixed runtime cases**. Completed runs: 23 runtime (152.41s), 179 control/recovery
(150.08s), 205 native execution/loss/source selection (305.26s), 131 paid/shared
entry/management (644.95s), and 135 original source/carry (654.80s). Earlier
and focused diagnostics are excluded; overlapping cases are not double-counted.
All runs use copied tests outside the checkout, a noneditable installed wheel,
Python `-I`, warnings as errors and disabled plugin autoload. Native runs are serial.

Final wheel SHA-256:
`574863de60a30e402d340b4366c2f301c80deba182892edec136c95141e6d16b`.
All 233 application/template files match source, wheel and installed bytes; 224
parent files remain unchanged. Twenty-three representative legacy contracts,
including old runtime settings and envelopes, serialize byte-for-byte identically
to the parent wheel. Changed-scope lint, repository fatal lint, document links,
dependency consistency and whitespace checks pass. Full repository style lint
retains 306 findings in 52 byte-identical parent files.

Retained proof: `../mixed-runtime-proof/` (`final-proof.json`, five completed
XML/log pairs and wheel receipts, identity/legacy serialization and lint evidence).
Final wheel: `../mixed-runtime-wheels/`; test interpreter:
`../scope-replay-env/bin/python`. Nested Scope index protection also accepts its
original quote beside two ordinary underlying quotes without changing the frozen
frame capacity or old serialization.

Dependencies are unchanged. LIVE remains disabled and deployment frozen; no
authenticated provider/model/broker calls were made. Final UI/visual and authentic
data/model/host/economic/PAPER acceptance remain after plumbing.

Remaining plumbing in total: common mixed market tapes, complete matched B/C/D
response contracts, four independent native A/B/C/D accounts and portable full-cost
replay/export. Preserve all original leases/source terms, every entry/management
charge, execution fee, explicit operating/overnight allocation and unknown cost.
Old adapters/exports must continue rejecting mixed inputs until the complete new
contracts exist. Do not reopen settled strategy rules.

## Paid mixed entry and native management: 2026-10-23 America/New_York

Fresh GitHub/local state began at HEAD
`1b7069afe14f536d2a3191e3361885b03d06acf1`, tree
`aa064acc300ea639481975df4485db15d18a7c5c`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The [paid mixed contract](MIXED_AI.md) now connects one full stock/option/Scope
entry request to durable attempt/usage, native post-cost approval and actual fills.
Stock choices retain complete original source, account/revision, admission,
quantity/price ceilings, fixed objectives, source clocks and carry/deadline terms.
Scope still requires its full fresh owned post-cost admission and original approval
ceiling. Model thesis, native approval, attempt and actual fill remain separate.
Old paid/replay adapters cannot bypass the new frozen enrollment.

Held shares now use the bounded position worker for MAINTAIN, TIGHTEN and EXIT_ALL.
The packet retains original source and paid thesis, current completed context,
remaining native shares, protection, full cash history and account revision.
Fresh review rejects late advice, widening, changed quantities or unavailable
quotes. Stop/target/time protection runs independently before and after reasoning.
Tightening and decision consumption are atomic; full closes retain native execution
and the original management lease. Partial-close races invalidate obsolete advice.
Restart retains completed and interrupted attempts without another model call.
Ordinary option and Scope management retain original targets, premium/time
protection and native partial-close behavior under the same paid owner.

Every admitted entry/management charge is reconstructed from complete stored
receipts. Unknown remains unknown. One allocator covers both asset types, paid
HOLD/rejections and all management calls without double subtraction. A flat-account
entry charge at the exact prior close clock belongs to the following actual entry;
management still binds its exact original holding. Pending management cannot freeze
a premature closed-trade loss result. Native option outcome reads and common loss
controls use the same execution/model/operating allocation as stock outcomes.

Validation: **1,239 distinct final-wheel installed checks**, including **37 new
mixed cases**. Completed runs: 37 mixed entry/management/carry (367.96s), 245 entry/position contracts (12.39s), 107 paid native coordination (323.33s), 313 mixed owner/accounting/source (374.82s), 304 execution/loss/outcomes (410.84s), 233 runtime/shared/replay boundaries (215.97s).
Earlier diagnostic runs are excluded; overlapping cases are never double-counted.
All runs use copied tests outside the checkout, a noneditable installed wheel,
Python `-I`, warnings as errors and disabled plugin autoload. Native runs are serial.

Final wheel SHA-256:
`03452fe60ab3c517e8f55a9c4ff21c8e6f5c536aeef4a9fb259eab8f73c67bca`.
All 232 application/template files match source, wheel and installed bytes; 208
parent application/template files remain unchanged. Nineteen representative legacy
contracts, including entry/position packets and absent mixed fields, serialize
byte-for-byte identically to the parent wheel. Changed-scope lint, repository fatal
lint, document links and whitespace checks pass. Full repository style lint reports
306 findings in 52 byte-identical parent files; that retained baseline is unchanged.

Retained proof: `../mixed-entry-proof/` (`final-proof.json`, six completed XML/log
pairs and wheel receipts, `identity.json`, `legacy-identity.json`, parent/current
serialization and lint evidence). Final wheel: `../mixed-entry-wheels/`.
Tests ran from `../scope-replay-env/bin/python`; no editable install was used.

Dependencies are unchanged; deployment remains frozen and LIVE stays disabled.
No authenticated provider/model/broker calls were made. Final UI/visual and
authentic data/model/host/economic/PAPER acceptance
remain open. Legacy tape/runtime/export consumers continue rejecting mixed inputs.

Remaining plumbing in total:

1. Explicit continuous mixed inputs and source collection, independent stock/option
   protection, settlement and session/restart recovery.
2. Common mixed tapes and four independent native A/B/C/D replay/export accounts,
   including every entry/management charge, execution fee, operating/overnight
   allocation and unknown cost.

Continue with the runtime boundary in `app/options/runtime_models.py`, `runtime.py`,
`scope_runtime.py` and the coordinator, then explicit mixed replay/export. Preserve
all old frozen contracts and bind complete new enrollment before accepting inputs.
The current paid worker rejects old replay adapters. Do not reopen settled strategy
rules or treat fixture proof as authentic PAPER acceptance.

## Original stock sources and shared native selection: 2026-10-22 America/New_York

Fresh GitHub/local state began at HEAD
`8bf4c567e1a0855328f57eaf26ad1f0d68e91666`, tree
`45fcb67a58189a5d36ac725010e08bcaead6a7ea`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The [stock source/selection contract](MIXED_STOCK_SELECTION.md) now derives native
long-share Degen and Swing candidates, then selects once across stocks, native
options and Scope using one create-only family/asset order. It uses the existing
owner, cash, journal, account revision, admission, order lock and independent exits.
Degen stock targets use the original completed signal close and scanner stop.
Swing daily/base/MA/level families share complete original exchange-session sources
without fabricating option identity. Original fixed targets and source-bound carry
survive approval, actual fill, restart and full-cost outcome attribution.

Original Swing roots lock by session/symbol. Completed invalidation/T1 consumption
and fresh executable bid observations retire a family permanently for that root;
rebound, restart or stale current entry evidence cannot erase observed retirement.
Ask-only targets do not retire it. Selection retains the full original admission,
source frame, cash history, account and revision. Native preparation and stored
verification rebuild the selected candidate; dispatch rechecks fresh entitlement,
break/chase and native admission. Selected price/quantity and approval expiry are
ceilings, so delayed preparation cannot extend the original decision window.

Held stock cycles use independent native protection without new candidate inputs.
Missing quotes and pending orders keep explicit blockers. New source/terminal tables
participate in the existing journal restore fence. Old coordinators, tapes and
runtime envelopes reject stock inputs they cannot consume. Mixed paid/runtime/replay
guards stay intact. Old absent-field serialization and option source arithmetic are
preserved.

Validation: **730 distinct final-wheel installed checks**, including **44 new
selection cases**. Completed runs: 44 selection (96.36s), 102 coordinator (86.19s), 81 owner/carry (156.53s), 335 native execution (140.58s), 140 control/runtime (77.38s), 28 source arithmetic (3.42s).
Earlier diagnostic runs are excluded; no overlapping cases are double-counted.
All tests use copied sources outside the checkout, a noneditable installed wheel,
Python `-I`, warnings as errors and disabled plugin autoload; native runs are serial.

Final wheel SHA-256:
`0f8bfac6a435a61494d21540202bea6b9ad83200c064160ef27083f57b5633b6`.
All 229 application/template files match source, wheel and installed bytes;
216 parent application/template files remain unchanged. Thirteen representative
contracts, including the old frame without stock inputs, serialize byte-for-byte
identically against the separately installed parent wheel. Ruff/format, dependency
consistency, local documentation links and whitespace checks pass. Proof is retained
in `../stock-selection-proof/`; the wheel is in `../stock-selection-wheels/`.


Continuation: finish complete mixed paid entry/management requests/results,
usage charges, fresh post-cost native admission and attribution; then explicit
continuous mixed source/session/recovery inputs; then common tapes with four
independent native A/B/C/D replay/export owners. These are the three remaining
plumbing tracks. Final UI/visual and authentic provider/model/host/PAPER acceptance
follow plumbing. Dependencies, main and deployment are unchanged; LIVE stays disabled.

## Original native stock carry: 2026-10-22 America/New_York

Fresh GitHub/local state began at HEAD
`ee327cce075e55d4f16f6a33eb99f44e2a07c407`, tree
`845aad4f344b2aee7ce13c09bf088c248c0c422a`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The [original stock carry contract](MIXED_STOCK_CARRY.md) now binds separately
frozen long-share carry policy to the existing native mixed owner. Original
calendar sessions, exact final exit, source/policy hashes and full catalyst
coverage are retained in the proposal, approved intent, held position and closes.
Preparation, dispatch and stored approval verification reconstruct the actual XNYS
path. Catalyst freshness is checked again at attempt without replacing the
original evidence or extending source/approval deadlines. Entry orders remain DAY.

Intermediate session cutoffs no longer shorten explicitly enrolled stock carry.
Original stop, target and time protection persist through partial closes, weekends
and restart. Missing quotes retain mandatory final exits. Closed markets block
execution and keep an explicit supervision issue; no unobserved fill is invented.
Native approval, fixture close acceptance and common fill reconstruction preserve
the complete original carry terms. Owners without enrollment, and later exits
without original carry terms, still reject carry.

Daily declared data/host/operating allocations include nontrading days. A native
Friday-to-Monday roundtrip demonstrates an execution profit becoming a full-cost
loss after four calendar allocations. Unknown costs retain existing blocking and
incomplete-outcome semantics. No extra account or synthetic option contract is used.

Validation: **744 distinct final-wheel installed checks**, including **34 new
stock-carry cases**. Completed runs: 34 carry checks (38.24s), 47 owner checks (124.41s), 335 native checks (141.02s), 140 control checks (80.21s), 188 mixed checks (117.01s).
The 29-case diagnostic run is excluded; no overlapping cases are double-counted.
All tests use copied sources outside the checkout, noneditable wheel installation,
Python `-I`, warnings as errors and disabled plugin autoload; native runs are serial.

Final wheel SHA-256:
`83fc9fb58eb3656fe55aeeed662ce09933be747e7b7b1d464ff3369f9805d0af`.
All 227 application/template files match source, wheel and installed bytes; 218
parent application/template files are unchanged. Twelve representative contracts,
including mixed policy and stock proposal, serialize byte-for-byte identically
against the separately installed parent wheel. Ruff/format, dependency consistency,
local documentation links and whitespace checks pass. Proof is retained in
`../stock-carry-proof/`; the wheel is in `../stock-carry-wheels/`.


Continuation: derive original Degen/Swing stock candidates and connect the shared
stock/options/Scope selector, binding these carry terms to original source rules.
Then finish mixed paid entry/management contracts and attribution, explicit
continuous runtime/source/session recovery, and common mixed tapes with four
independent native A/B/C/D replay/export owners. Those guards remain intact; no
claim of completed mixed strategy, runtime or replay acceptance is made here.
Final UI/visual and authentic provider/model/host/PAPER acceptance follow plumbing.
Dependencies, main and the deployed experiment are unchanged; LIVE remains disabled.



## One native stock/options owner and independent protection: 2026-10-22 America/New_York

Fresh GitHub/local state began at HEAD
`bf7a4b97d2e356b343a173bcda79c7c82635dc14`, tree
`1ad1a2354d537d7f64a16da990ce7bbacb758751`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The [native mixed owner](MIXED_NATIVE_OWNER.md) now binds actual shares and native
options to one exact `OptionExecution`, journal, original capital, revision, restore
fence and bounded fixture child. Create-only mixed policy freezes share limits and
explicit nullable daily data/host/operating allocations. SQLite cross-table locks,
read epochs and submission guards cover both asset paths. Stock approvals store
and recompute their original proposal, quote, complete common cash history,
session, account snapshot, revision and admission. Fresh dispatch cannot extend the
original approval, increase its price or resize its approved quantity.

One chronological stock/option fill and settlement sequence reconstructs common
cash, settled balances, lots, fees and realized outcomes from original capital.
Native reconciliation checks exact approved intent, original attempt, immutable
fill prefixes and terminal history; missing/unowned/rewritten evidence fails closed.
Stock holdings use the existing `EquityHolding` account discriminator. Native Scope
fixed targets and Swing carry horizons remain attached to their original entries.
Stock → option → stock continuity uses one owner and one balance.

Independent stock stop/target/time protection latches across rebound, partial fills
and restart. Missing quotes do not erase time exits; entry halts or unknown model
costs do not suppress owned close admission. Partial-close preparation and dispatch
freshly assess mandatory protection. Unattempted partial closes can be superseded;
attempted/uncertain closes cannot be replayed. Native uncertainty/restart, lifetime
ownership, paired restore fencing, signed resume and global/family resets retain
original evidence and exact revisions. Original stock carry requests are rejected
rather than silently shortened into a session-close plan.

Explicit daily calendar allocations reduce common loss headroom, including idle
charges, and attach once to the held/next actually filled entry. Closed stock and
option results feed one global/family loss history with fees and full operating
allocations; a gross stock win can become a net loss. Unknown costs remain unknown.
Mixed paid contracts remain unenrolled: unexpected retained usage blocks entry and
loss consumption, while independent held exits remain available. Option-only paid
coordinator/model, runtime and comparison/export paths explicitly reject mixed
inputs. The basic owner report labels mixed fixture state; it does not claim final
observer/UI or portable mixed replay acceptance.

Validation: **907 distinct final-wheel installed checks**, including **47 new
native mixed-owner cases**. The completed phases were 47 owner cases (118.36s),
335 native admission/execution/fill/settlement/Scope/Swing regressions (136.60s),
75 focused loss/family/reset/model-admission checks (58.88s), 62 paid Scope and
stored-outcome checks (270.63s), 140 operator/observer/runtime checks (86.93s),
188 common accounting/admission/fixture checks (131.53s), and 60 evaluation/Scope
native export checks (64.69s). Exact completed IDs are retained and counted once.
The targeted risk run excludes the full two-session/four-arm fixture; stored-outcome
checks select direct owned-position cases rather than the full managed replay
fixture. Interrupted wide runs and all overlapping diagnostics are excluded.
No unfinished long replay is counted as a pass.

Final wheel SHA-256:
`82ac2d2793213f3dae5f2aae348a9076eff00d020b604137dbf9b8a75a8b832c`.
All 226 application/template files match source, wheel and installed bytes; 212
pre-existing application/template files are unchanged. Ten representative frozen
contracts serialize byte-for-byte identically across separately installed parent
and current wheels. Changed-source Ruff/format, dependency consistency, local
Markdown links and whitespace checks pass. Tests are copied outside the checkout
and run serially against a noneditable wheel with Python `-I`, warnings as errors
and plugin autoload disabled. Proof: `../mixed-owner-proof/`; wheel:
`../mixed-owner-wheels/`; environment: `../scope-replay-env/`. The parent is
`bf7a4b97d2e356b343a173bcda79c7c82635dc14`. Source of truth is v1.102.

Continuation: original stock candidates/shared family selection and required stock
carry contracts; full paid mixed
entry/management contracts and fresh post-cost native attribution; continuous
mixed runtime/source inputs; independent native A/B/C/D mixed tape/replay/export.
The [remaining list](MIXED_CASH_HISTORY.md#remaining-plumbing-in-total) now removes
the completed native owner/protection/recovery portion. See the new owner document
for the next implementation boundary. Final UI/visual and authentic PAPER acceptance
remain after plumbing. No dependency, deployment, authenticated provider/model/broker,
LIVE or main changes. PR #1 stays open/draft and the deployed experiment stays frozen.


## Shared stock/options fixture and fixed child: 2026-10-22 America/New_York

Fresh GitHub/local state began at HEAD
`8191de7e2bf5dba71f70f99140985cc1abd3e13f`, tree
`90dab2ba1431f8337001e7802a98f2fb769d4dff`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The [shared durable mixed fixture](MIXED_VENUE.md) now binds actual long shares and
options to one private venue, original capital, cash/settled balance, unresolved
order lock, holding, submit count and chronological event sequence. Mixed creation
requires explicit frozen share limits and a separate schema. Both asset paths
check the same working orders and position; concurrent fixed children cannot
acquire competing stock and option order locks.

Stock observations retain the complete accepted intent, including original thesis,
source clocks, geometry, family, approval hash, account revision and deadlines.
Fills reject any rewritten accepted term, stale/nonexecutable/undersized source,
reused source size, nonconforming fractional quantity, wrong price/fees, overfill
or changed history. Partial cancellations retain actual holdings. Closes preserve
original entry terms and cannot open shorts or average another entry. Sale proceeds
remain unsettled until an explicit receipt. Stock → option → stock fills reconstruct
one continuous balance through the existing mixed accounting boundary.

The existing bounded isolated fixed child now supports a separately typed stock
operation, retaining exact policy/venue identity and original deadlines. Lost,
invalid and oversized acknowledgments, crashes and stalls retain accepted history;
client identities cannot be resubmitted. Scripted fixture terminal outcomes remain
distinct from native cancellation/retry authority. Reads/writes check one global
sequence, order/fill identities, submit count and nonregressing clocks.

Existing option-only fixture state and serialized contracts omit the new optional
fields. Ten representative prior contracts are byte-identical across separately
installed parent/current wheels. Legacy native owners reject mixed enrollment,
including flat mixed snapshots; stock evidence cannot be accepted and ignored.
Stock primitives were moved below the option lifecycle import boundary with public
compatibility re-exports. The prior pure accounting implementation is unchanged
except for extracting its frozen stock-rule helpers for reuse by the fixture.

Validation: **523 distinct final-wheel installed checks**, including **69 new
fixture cases**, **119 common accounting/admission checks** and **335 native
option/admission/fill/settlement/Scope/Swing regressions**. The final phases
completed in 109.16, 7.57 and 137.48 seconds respectively. Exact completed case
IDs and per-phase receipts are retained without double-counting. Final wheel SHA-256:
`90e91660f85f2f5bb110ad58e32b97b3d45d73f08bad4b8b43aba7b9b524707e`.
All 221 application/template files match source, wheel and installed bytes;
212 pre-existing application/template files are unchanged. Changed-file Ruff/format,
dependency consistency, local documentation links and whitespace checks pass.
Proof: `../mixed-venue-proof/`; wheel: `../mixed-venue-wheels/`; environment:
`../scope-replay-env/`. Tests are copied outside the checkout and run serially
against the noneditable installed wheel with Python `-I`, warnings as errors and
plugin autoload disabled. Earlier overlapping/diagnostic runs are excluded. A
fractional-exit test helper's duplicate keyword was corrected; stock fault tests
use the existing five-second process bound rather than a shorter startup allowance.

This completes the venue/fixed-worker portion of mixed plumbing, not the native
mixed owner. Remaining: native journal, preparation, complete reconciliation,
independent stock protection, loss outcomes, restart/recovery; original stock
candidate/shared selection and full paid entry/management contracts; continuous
mixed runtime and independent native A/B/C/D tapes/replay/export with all costs.
The [remaining list](MIXED_CASH_HISTORY.md#remaining-plumbing-in-total) is retained.
No dependencies, deployment, provider/model/broker calls, LIVE controls or main
changes. UI/visual and authentic PAPER acceptance remain later work.


## Mixed cash history and order-free admission: 2026-10-22 America/New_York

Fresh GitHub/local state began at clean HEAD
`35ac9d415ce2c5b13619d5074697d85e1a33e4d7`, tree
`da51f021c2c0f9344cbdaea2e6e34c1720ce3096`. PR #1 was open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

[Shared mixed cash history/admission](MIXED_CASH_HISTORY.md) now supplies the common
accounting boundary needed by the remaining native owner. One frozen original
capital, account, population and venue reconstruct stock and option fills and
settlement in the same cash/settled-cash/fee/P&L sequence. Stock holdings are genuine
long US-listed equities/ETFs, with exact frozen share increments, original terms,
source clocks/validity deadlines and FIFO lots. Option holdings retain original
Scope/Swing target, premium, time, fill-reference and carry terms through existing
native accounting on the current common balance. No second capital is introduced.

Complete fill identity, attempt/original deadline, sequence, quantity, debit,
source quote, observed liquidity, tick/slippage and fee checks reject changed or
unsupported evidence. A held stock blocks options and a held option blocks stocks.
Partial fills retain original terms; an entry cannot resume after an exit starts.
Stock proceeds remain unsettled pending explicit receipts. Physical exercise is
not a stock-entry path. An unresolved order retains a shared reservation even after
approval expiry, with actual paid debit subtracted once and exit fees reserved.
A pending sale cannot exceed the owned remainder. Equivalent decimal formatting
and changed receipt timestamps cannot recycle stock source liquidity.

All supplied model charges, including rejected entry calls, and explicit DATA/HOST/
OPERATING allocations reduce the common economic envelope. Absent calendar-date
allocations and unresolved usage remain unknown, suppress net/loss-budget results
and block entry. Later usage resolution retains the original unknown receipt.
Immutable prefix validation rejects changed capital/account/venue/policy, rewritten
fills/costs and silently dropped unresolved reservations. Terminal evidence remains
a native-owner obligation, not a model-controlled cancellation facility.

Stock admission is deterministic and order-free. It sizes from common settled
cash, full-loss headroom, fees and exposure, preserving original geometry and
source/session/freshness deadlines. The existing option governor receives the same
account and its existing equity-holding discriminator. Both paths default to
unreconciled. Native reconciliation remains an explicit trusted-owner assertion;
these pure helpers grant no dispatch rights. Close admission stays independent of
entry halts, entry cutoff and unknown/exhausted economic budgets while requiring
fresh exact ownership, quotes, executable size and fee-paying liquidity.

Validation: **454 distinct final-wheel installed checks**, including **119 new
cases** and **335 native regressions**. Final wheel SHA-256:
`ccc0cd1df231836333989e3a4fe8183498c94157eef523ff6ca60574bc6d2a61`.
The new checks include actual native option, Scope and Swing carry projection;
stock/options/stock cash continuity; partial fills, settlement, reservations,
source/receipt/deadline tampering, fractional shares, costs and common admission.
Four independently bound history projections retain separate cash/costs; this is
not native four-arm mixed replay acceptance. Regressions cover option admission,
native execution, fill-underlying evidence, settlement outcomes, Scope execution
and Swing carry, including frozen model-contract identity.

All 219 application/template files match source, wheel and installed bytes; the
original 215 tracked application/template files are byte-identical to the parent.
Copied tests ran outside the checkout against a noneditable wheel with Python
`-I`, warnings as errors, plugin autoload disabled and serial native execution.
Proof: `../mixed-ledger-proof/`; wheel: `../mixed-ledger-wheels/`; environment:
`../scope-replay-env/`. Exact final case IDs, timings and file identities are
retained. Earlier diagnostic/overlapping runs are excluded; an imported fixture
registration mistake was corrected in the copied-test workflow. Final review
also explicitly bound the stock source clocks before final-wheel reruns.
Changed-file Ruff/format, dependency consistency, local links and whitespace pass.

This does **not** finish mixed native ownership. The linked document lists all
remaining plumbing: one native owner/venue and cross-instrument order lifecycle;
original stock candidates in shared family selection; complete paid entry/management
and family-loss binding; mixed runtime/protection/recovery; common tapes and
independent native A/B/C/D full-cost replay/export. These precede final UI and
authentic PAPER acceptance. Existing cohorts and deployed experiment stay frozen;
LIVE disabled, PR #1 open/draft, main untouched. No dependency changes,
authenticated provider/model/broker calls, deployment or merge occurred.


## Complete concurrent Swing-family plumbing: 2026-10-22 UTC

Fresh GitHub/local state began at clean HEAD
`ee08888b862ab752d50d156d381bac285b1f9421`, tree
`c4a6d0944199adfb9e5500176c530f93f3db5e2e`. PR #1 was open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

[Complete Swing-family batches](OPTIONS_SWING_BATCH.md) now let daily base,
8/21 EMA, 50 SMA and higher-timeframe level setups compete inside the same native
owner. One compact original source per symbol supplies the completed daily/hourly
history and exact CALL/PUT contract pair. Software enumerates every enrolled
variant, retaining blocked diagnostics. Complete source/calendar/clock defects
reject the batch; nonpositive original risk is never repaired with a current price.
Original stops, fixed 1R/2R/3R objectives, source clocks, target/carry sessions,
full frozen policy and original batch hashes remain bound.

All roots and children lock atomically. A conflict in a second symbol rolls back
a new first-symbol root. Current metadata/catalyst refresh does not replace original
terms. Quote reads deduplicate only identical instruments; conflicting aliases
reject. Every family retains separate evidence/admission/candidate identity.
Selection, paid entry, native review and carry reconstruction now join the exact
family, symbol, right and instrument. Tests select different families sharing the
same contract. One native owner retains cash, reservations, one position, cost/loss
controls, mandatory exits and original per-child stop/T1 retirement across runtime
and restart. Paid rejected entries remain charged; unknown usage remains unknown.

New enrollment leaves legacy seeds/frames/population serialization unchanged.
Common tapes reject missing/duplicate batches, unsupported legacy fields and
unenrolled child hashes. Native independent A/B/C/D carry replay and portable export
retain separate accounts, actual fills, entry/management charges, execution fees
and explicit session/overnight allocations. Reconstruction rederives complete roots
and children and rejects rehashed source, child-set, policy and selected-lineage
substitution. No older Scope replay-model restriction was removed.

Eight unique quotes, 24 candidates, 256 KiB wire/model requests and existing token,
cost and response limits remain bounded. Oversized requests fail closed. Only the
new tagged expanded journal contract permits 30 scans/read plans and 4 MiB; legacy
records retain their prior bound. Observer reads use frozen enrollment and create
no execution/model/provider activity. Pure original-source derivation has a bounded
cache keyed by exact serialized inputs; current time, database state, approval,
account and terminal evidence are never cached.

Validation: **611 distinct final-wheel installed checks**, including
**58 new cases**. Wheel SHA-256:
`f90c8895afa7ed32c925f7aaf70e06e34ecc50f6cbb2e686f4bcdcc197a94f29`.
Final native/boundary/runtime/observer checks: 41; common tape and independent
carry/export checks: 17; regressions: 553. The regressions cover existing
level/MA/base/target/shared/quote/lineage/Scope/Degen, legacy model contracts,
common tapes and both ordinary/Scope continuous runtimes. Six retained pre-batch
exports reconstruct exactly; artifact checks are separate from pytest counts.
All 215 application/template files match source, wheel and installed bytes.
Copied tests ran outside the checkout against a noneditable wheel, with Python
`-I`, warnings as errors, plugin autoload disabled and serial native execution.
Exact distinct case IDs/times, test/source identity and publication receipts are in
`../swing-batch-proof/`; wheel: `../swing-batch-wheels/`; environment:
`../scope-replay-env/`. Earlier overlapping/diagnostic runs are excluded. They
exposed the expanded journal boundary and an observer test field-name mistake;
these were corrected without relaxing quote, model, source or risk controls.
The final enrollment review also closed an old-tape unbound-child-hash acceptance
edge. Runtime settings now reserve both original Swing contract slots before
creating a population. Changed-file Ruff/format, dependency consistency, local Markdown links and
whitespace checks passed.

Remaining major plumbing is **mixed stock/options ownership**: one common bankroll,
reservation/exposure/loss/cost ledger and selector across both instrument types;
instrument-specific native execution, fills, settlement and protection; durable
reconciliation/restart/recovery; unified runtime inputs and independent A/B/C/D
full-cost replay/export. Running separate stock and option bankrolls is not this
completion. Final UI and authentic provider/model/host/economic/PAPER acceptance
follow that implementation. LIVE stays disabled, deployment frozen, PR #1 draft,
main untouched. No dependencies, authenticated provider/model/broker calls,
deployment or merge were changed.


## Native higher-timeframe level plumbing: 2026-10-21 America/New_York

Fresh GitHub/local state began at clean HEAD
`f0b985022ca58626d6f0ba47e01fa98e3b383ab8`, tree
`147ce1cdc95047bb0b8fe47193fca5422f60bc06`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

[Higher-timeframe level setups](OPTIONS_SWING_LEVELS.md) now bind previous-week
high/low, previous-month high/low and aligned weekly-open CALL/PUT variants to the
shared native owner. Levels derive from complete actual exchange-session histories;
no caller-supplied level price is accepted. Original source-period endpoints,
latest completed cross, retest/hold, directional confirmation, reference/stop and
fixed 1R/2R/3R objectives retain their native family identity through execution,
runtime, restart, carry and portable independent A/B/C/D export.

The source remains SignalFlow commit
`f9eaf2c1b5d13dca287ee7138126883065b00395`, setup engine blob
`af7912bc06dbf0bee94c148cfe7fb1540842d85b`. Fixed rules preserve the twelve-bar
cross lookback, 0.7% touch tolerance, 0.4% close tolerance, directional candle
confirmation and 1.5-tolerance original stop. Repeat clusters remain a source
warning rather than a new gate. Weekly open requires an available aligned completed
daily 10/50 SMA regime; high/low variants retain their pinned direction. Exact native
Decimal prices and conservative stop rounding replace source presentation rounding.
No model score or new quote moves original levels or targets.

The new explicit history/enrollment requires 56–260 completed consecutive daily
sessions and complete prior calendar periods. Actual holiday, half-day, DST and
year boundaries are verified. Missing/partial periods, foreign or future source
clocks, unsupported hourly/MA fields and unenrolled keys fail closed. Native
next-session break/hold, exact contracts, catalyst/chase, account revisions,
post-cost admission, original deadlines and mandatory exits remain independent.
Stored export reconstruction rederives family evidence and rejects rehashed source,
level, family and enrollment substitution. Original stop/T1 retirement remains
terminal through runtime delivery and restart; unknown usage is never zero.

Validation: **426 distinct final-wheel installed checks**, including **112 new
cases**. Wheel SHA-256:
`a7175e28d29f7e0747278936e339c8a4b07a44b9e57ebfd7d7033966b9a7d978`.
Final native/source/runtime cases: 78; independent replay/export cases: 34;
existing MA/base/target/shared/quote/lineage/Scope/Degen/frozen-contract regressions:
314. Every level/direction variant has its own four-account carry run with
actual fills, paid reopening management, execution fees and explicit session/gap
allocations. Five retained pre-level exports reconstruct exactly; artifact checks
are separate from pytest counts. Copied tests ran outside the checkout against the
noneditable installed wheel with Python `-I`, warnings as errors, plugin autoload
disabled and serial native execution. Exact distinct case IDs and times are retained
in `../swing-level-proof/final-proof.json`; earlier overlapping native checks are
excluded. All 214 application/template files match source, wheel and installed bytes.
Changed-file Ruff/format, dependency consistency, copied-test identity, local
Markdown links and whitespace checks passed. Proof/source/test/publication receipts:
`../swing-level-proof/`; wheel: `../swing-level-wheels/`; environment: `../scope-replay-env/`.

Next plumbing: concurrent Swing-family candidate enumeration/selection, then mixed
stock/options ownership, with full runtime/replay/export integration. The current
base, MA and level enrollments each retain one locked original seed per symbol/
session; the new detectors do not imply joint candidate enumeration. That boundary
needs an explicit complete input batch, atomic original locks, bounded unique quote
requests and exact selected-scan lineage while preserving frozen cohorts and current
quote/model limits. Final UI and authentic provider/model/host/economic/PAPER
acceptance follow plumbing. LIVE remains disabled, deployment frozen, PR #1 draft,
main untouched. No dependency changes, authenticated provider/model/broker calls,
deployment or merge were introduced.


## Native daily MA-pullback plumbing: 2026-10-21 America/New_York

Fresh GitHub and local state matched clean branch HEAD
`3b19be3bbeca5cb2f81909134d373996b116ca32`, tree
`7dd8d87e9f6655e1f94719214895b14ecacee994`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

[Native daily MA pullbacks](OPTIONS_SWING_MA.md) now enroll all three approved
variants: 8 EMA, 21 EMA and 50 SMA. Each seed locks its original variant, complete
daily/hourly source evidence, reference/stop and fixed 1R/2R/3R objectives. Native
selection retains its exact setup identity within SWING and uses the existing
account, paid model slot, reservations, approval, fills, management and loss guards.
Research A/B/C/D accounts remain independent; no balances or budgets are shared.

Rules follow pinned SignalFlow commit
`f9eaf2c1b5d13dca287ee7138126883065b00395`, setup engine blob
`af7912bc06dbf0bee94c148cfe7fb1540842d85b` (local source blob reverified).
Daily regime, prior MA trend/slope, current test/hold and directional confirmation
are reproduced with exact Decimal arithmetic. Source volume, repeat-test and hourly
opposition diagnostics remain diagnostics, not new mandatory strategy filters.
Neutral candle tags alone do not confirm. Original stop geometry uses the signal
extreme and MA/ATR buffer, with native conservative 12-decimal rounding. No source
score, fabricated confluence, guessed unavailable regime or current-price target
replacement grants authority.

New `swing-ma-daily-v1` history requires 56–260 completed consecutive exchange
sessions. Existing hourly wire evidence is reused with the frozen source and actual
open-anchored intervals. Explicit MA enrollment, allowed variant, original source
clocks, original target hash and native post-cost checks remain required. Common
tapes reject unsupported/foreign/future/missing inputs; native stored reconstruction
rederives setup/diagnostics and rejects rehashed family or enrollment substitution.
Original stop/T1 retirement survives runtime delivery/restart. Mandatory native exits,
paid rejected attempts, unknown usage and independent account accounting remain intact.

Validation: **333 distinct installed checks passed, including 103 new cases**,
on wheel SHA-256
`d4ebaff5f39d5d129cf747c626e66a6bf486ef744bb640f1ba2905c5fcad283f`.
The final wheel passed 84 MA unit/native/runtime cases and 19 common-tape/independent
carry-export cases, plus 230 existing base, original-target, shared-family,
quote lifecycle, lineage, Scope arbitration, Degen and frozen-model-contract cases.
Each MA variant ran through all four independent carry accounts with actual fills,
paid reopening management, model/management charges, execution fees and explicit
session/gap allocations. Four retained pre-MA exports reconstruct exactly; artifact
checks are separate from pytest counts. Native checks ran serially from copied tests
outside the checkout using a noneditable wheel, Python `-I`, warnings as errors and
plugin autoload disabled. Exact unique case IDs/times are in
`../swing-ma-proof/final-proof.json`; overlapping diagnostic runs are excluded.

Diagnostic failures were fixture-only: converting a carry policy temporarily left
a long lookback without its family enrollment, and an assertion guessed a new hourly
wire version instead of the deliberately reused original contract. Both fixtures
were corrected without relaxing production rules. All 212 application/template
files match source, wheel and installed bytes. Changed-file Ruff/format, dependency
consistency, copied-test identity, local Markdown links and whitespace checks passed.
A whole-repository lint probe also reported pre-existing unrelated issues; they were
not modified or represented as passing. Proof/source/test/publication receipts:
`../swing-ma-proof/`; wheel: `../swing-ma-wheels/`; environment: `../scope-replay-env/`.

Next plumbing: higher-timeframe level break/retest families, concurrent Swing-family
enumeration/selection, then mixed stock/options ownership with full runtime/replay/
export integration. This MA enrollment still locks one original seed per symbol/
session and is separate from the base enrollment; it does not claim that joint
family integration is finished. Final UI/visual and authentic provider/model/host/
economic/PAPER acceptance follow plumbing. LIVE disabled, deployment frozen, PR #1
draft and main untouched. No dependencies, authenticated provider/model/broker calls,
deployment or merge were introduced.


## Native daily-base family plumbing: 2026-10-21 America/New_York

Fresh GitHub and local state matched clean branch HEAD
`b1888576abfcb9526b852da6b2bf41bea80d5704`, tree
`e5e76d9d8352e96a53e958023b55bda5d238af6e`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

[Native daily base breakout/breakdown](OPTIONS_SWING_BASE.md) now connects an
explicit new `swing-daily-base-v1` enrollment to the existing shared PAPER owner.
`SWING_DAILY_BASE` retains its own setup identity inside the SWING family through
selection, native approval/dispatch, actual fills, held management, loss attribution,
runtime delivery, restart and independent carry replay/export. It does not create
another ledger, reservation, worker or model budget inside an account. Research
A/B/C/D accounts remain independent. The old small daily-breakout adaptation remains
frozen and its optional fields stay absent.

The implementation follows SignalFlow commit
`f9eaf2c1b5d13dca287ee7138126883065b00395`, setup engine blob
`af7912bc06dbf0bee94c148cfe7fb1540842d85b`: fifteen-session compression, boundary
close, close location, 1.20x prior-twenty-session volume, 1.25 ATR extension and
non-opposed daily/hourly 10/50 SMA regimes. Original reference/stop and fixed
1R/2R/3R objectives bind the original source evidence and frozen policy. Exact
Decimal arithmetic and native conservative stop rounding remain in force.

This native adaptation explicitly requires 55–260 daily bars and 54–260 hourly bars
so required prior daily and hourly trend contexts are available. The source's
35-bar/unavailable-context path does not turn missing evidence into neutral support.
New daily history has its own version; hourly history has frozen source, identity,
actual exchange-open-anchored intervals and original source/receipt clocks. Full
regular and early-close intervals, DST and consecutive sessions are validated.
Future, unfinished, missing, gapped, interpolated, zero-volume or foreign hourly
inputs are blocked, including at the common tape boundary. Old cohorts keep their
twenty-bar bound and do not silently accept new family data.

The original next-session break/hold, current chase, exact contract, catalyst,
account risk and approval deadlines remain independent native gates. Unfilled
original stop/T1 observations remain terminal across runtime and restart. Native
stored reconstruction rederives the family rules and rejects altered source,
rule diagnostics, family identity or enrollment, even with a rehashed export.
Held carry retains original terms and deadlines; paid fresh rejections retain
their charge, unknown usage remains unknown and actual fills remain distinct from
proposals and attempts. A/B/C/D carry exports retain all model/management charges,
execution fees and explicit session/gap operating allocations.

Validation: **242 distinct installed checks passed**, including **47 new
cases**, on wheel SHA-256
`4970a618bea4c132ae268336c86e63ce533ef4f440b78c0d0ec046449f8d7f5a`.
Exact case IDs and phase times are in `../swing-base-proof/final-proof.json`.
The 37-case base phase, nine-case independent carry/export phase and final runtime/
regression phase plus the focused frozen-model-contract check are counted once by
distinct case ID. Earlier overlapping focused
runs are retained but not added. Native tests ran serially using a noneditable
installed wheel, copied tests outside the checkout, Python `-I`, warnings as errors
and plugin autoload disabled. The new runtime test was appended after the 37-case
phase; its unchanged earlier test source snapshot is retained separately.

Coverage includes CALL/PUT geometry under changed ambient Decimal contexts, all
source rule blockers, unavailable/foreign/future/gapped hourly inputs, actual
DST/half-day boundaries, deterministic/paid entry and actual protective fills,
fresh paid rejection, unknown cost, original stop/T1 retirement, restart and runtime
delivery. Four independent carry owners retain native fills, paid reopening
management and full accounting. Existing Degen, shared Swing, target derivation,
quote retirement, native lineage and Scope arbitration/history regressions passed.
Three retained exports (legacy Scope series, original combined carry and prior
derived-target carry) reconstruct exactly; those artifact checks are separate
from the pytest count.

The initial native fixture had already crossed the correctly derived base stop
before entry, so its expectation of requesting that contract's quote was invalid.
The valid-entry fixture was corrected; the existing stop rule was preserved and a
separate test verifies that the original adverse history permanently blocks the
seed. Diagnostic logs/XML remain retained. No production rule was relaxed to make
that fixture enter.

All 210 application/template files match source, wheel and installed bytes. Proof,
source/test snapshots and publication receipt: `../swing-base-proof/`; wheel:
`../swing-base-wheels/`; environment: `../scope-replay-env/`. Ruff, dependency
consistency, copied-test identity, local Markdown links and whitespace checks passed.

Next plumbing: remaining Swing daily MA-pullback and higher-timeframe level
break/retest families, then mixed stock/options ownership and remaining family
integration. Preserve pinned source contracts and settled strategy decisions.
Final UI/visual and authentic provider/model/host/economic/PAPER acceptance remain
open after plumbing. LIVE remains disabled, deployment frozen, PR #1 draft and
main untouched. No dependencies, authenticated provider/model/broker calls,
deployment or merge were introduced.


## Original Swing target derivation plumbing: 2026-10-22 UTC

Fresh GitHub and local state matched a clean working branch at
`76b0d88e8d3e06ef4ec616c1f397a76195bad1da`, tree
`bb40cce49453478f5ad047009853ca471534cbfd`. PR #1 remained open/draft;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

[Original Swing target derivation](OPTIONS_SWING_TARGETS.md) now prepares the
existing daily-breakout seed from completed pre-open evidence. New explicit
`original-risk-ladder-v1` enrollment requires the existing original-T1 retirement
lifecycle and freezes reference, invalidation, risk and all 1R/2R/3R objectives.
Policy and original seed-input hashes bind the source bars/clocks, target session,
contract and carry horizon. A bounded offline builder/API and create-only CLI retain
a portable non-authoritative request/seed envelope. The current native source,
calendar, contract, catalyst, quote, account, approval and deadline gates remain
independently required. No target moves with a new quote, paid decision or restart.

The fixed risk ladder follows SignalFlow commit
`f9eaf2c1b5d13dca287ee7138126883065b00395`, setup engine blob
`af7912bc06dbf0bee94c148cfe7fb1540842d85b`. This adaptation uses existing native
daily-breakout geometry and conservative 12-decimal stop rounding with exact Decimal
target arithmetic. It does not import floating-point rounding or silently expand
the current three-to-twenty-bar setup into the source's full base detector.
Nonpositive risk or any nonpositive objective rejects the seed. T2/T3 are retained
objectives, not a new automatic scale-out policy or replacement full AI entry plan.

Native seed locking/scanning, selected-entry review and common tapes reject missing,
changed or unenrolled target proof. Native stored reconstruction also compares the
full seed JSON to the selected scan, verifies its hash and rederives the objectives;
keeping an old hash cannot conceal changed stored target fields. Original T1
consumption remains terminal across recovery/restart. Actual entry/protective fills,
carry deadlines, paid fresh rejection, unknown usage and all costs retain native
ownership. Independent A/B/C/D carry replay/export preserves four accounts and the
original seed geometry, full entry/management charges, execution fees and explicit
session/gap allocations. Old optional fields remain absent and old cohorts stay frozen.

Validation: **296 distinct installed checks passed on the final wheel**,
including **46 new cases**. Exact case IDs, phase timings and unique totals are in
`../swing-target-proof/final-proof.json`. Native tests ran serially from copied tests
outside the checkout using a noneditable wheel, Python `-I`, warnings as errors and
plugin autoload disabled. Coverage includes CALL/PUT arithmetic under changed
ambient contexts, source/session/contract failures, original proof tampering,
runtime T1 retirement, actual fills/protection, paid rejection/unknown costs,
restart, four-account overnight management/accounting and rehashed detached export
tampering, including modified seed JSON with an unchanged stored hash. Existing Swing lifecycle/quote/target/owner/execution and common Scope
and legacy market-tape regressions passed. Retained legacy Scope and combined
carry-series exports reconstruct exactly; those artifact checks are separate from
the pytest count.

Candidate-wheel diagnostics remain retained and excluded from the final count.
They exposed a fixture target below the existing minimum reward-to-risk requirement,
then an assertion hashing raw JSON instead of the canonical typed seed. Fixtures
were corrected without relaxing either native contract. The export review also
added full stored-seed target reconstruction before the final rebuild. Candidate
and overlapping case counts are not added to final-wheel totals.

Final wheel SHA-256: `371535eea65fe9924c6f1762307b3fa6cc000cb83c0badaa2eda44611aa111bc`.
All 208 application/template files match source, wheel and installed bytes. Proof,
source/test snapshots and diagnostic receipts: `../swing-target-proof/`; wheels:
`../swing-target-wheels/`; environment: `../scope-replay-env/`. Ruff, dependency
consistency, copied-test identity, diff whitespace and local Markdown links passed.

Next plumbing: remaining supported Swing families (daily MA pullback, full daily
base breakout/breakdown and higher-timeframe level break/retest), then mixed
stock/options ownership and remaining family integration. Use the pinned source
contracts and preserve independent research accounting; do not reopen settled
strategy decisions. Final UI/visual and authentic provider/model/host/economic/PAPER
acceptance remain open after plumbing. LIVE is disabled, deployment frozen, PR #1
draft and main untouched. No dependency changes, authenticated provider/model/broker
calls, deployment or merge were introduced.


## Combined Scope/Swing carry replay plumbing: 2026-10-21 UTC

The working branch and local HEAD started clean at
`42cdc630aa9df0957300ceed7d68b05ce3782bc3`, tree
`9229d377c6de0b644cafa0850096bae2534716c8`. GitHub branch and PR head matched;
PR #1 remained open/draft and main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`.

The separate [combined carry series](OPTIONS_SCOPE_CARRY_SERIES.md) now connects
four independent native A/B/C/D owners, common Scope/Swing observations, original
carry sessions and deadlines, full entry/management receipts and portable export.
Each owner retains its own cash, reservation, fees, fills, model budget and loss
controls. C/D declared entry scripts match; D management is separately charged.
Scope retains its original intraday authority. Entry proposals, approvals, attempts and
actual fills remain separate. Fresh owned post-cost Scope admission and original
model/approval/protection deadlines remain mandatory.

`scope-carry-series-model-v1` freezes the ordered tapes, full request and complete
script. Only the exact new carry response adapters can bind it. B additionally
requires `scope_carry_shortlist="scope-carry-shortlist-v1"` and its own prompt/schema;
no replacement geometry or horizon is accepted. Existing native runtime and old
Scope replay/cohort serialization and rejection boundaries stay frozen. Complete
result parsing and native usage settlement now retain the new B receipt type.

Every exact between-session gap has an explicit data/host allocation for each
independent account. Missing gap/session costs and unknown model usage remain
unknown. Native closing exports retain cumulative costs and immutable prior
history; settlement remains explicit. Daily open holdings stay unvalued. Separate
whole-period cash arithmetic is available only after final flat complete accounting;
paired differences require all four accounts complete. An unfilled Scope close
remains explicit unresolved intraday exposure with its original cutoff across
sessions, without dropping its export or granting a carry horizon. A bounded Swing
exit missed before another gap stays explicitly unresolved with its original
deadline and native expired-order review halt. Later quotes cannot clear that halt
or trigger an automatic retry; held accounting stays incomplete. Overnight
return/drawdown and an unsupported matched SPY whole-period benchmark are never inferred.

The new carry scheduler defers its initial empty opening observation when a real
same-clock receipt is recorded. Diagnostics exposed the legacy flat-session scheduler's
synthetic empty opening tick latching a stale-price halt before that receipt.
Only the new carry scheduler defers that tick; missing/later opening quotes retain
the persistent native halt, and mandatory exits still operate independently.
No halt is automatically cleared and no deadline is extended.

Validation: **172 distinct installed checks passed on the final wheel**,
including **30 new cases**. Exact case IDs and phase timings are retained in
`../scope-carry-series-proof/final-proof.json`. This is separate from prior wheels'
counts; prior-wheel results and repeated case IDs are not added. Native runs were
serial against a noneditable wheel with copied tests outside the checkout, Python
`-I`, warnings as errors and plugin autoload disabled. Coverage includes actual
weekend Swing holdings, paid reopening management, Scope same-session closes,
independent accounting, complete gap costs, unknown usage, unknown gap allocation,
unfilled final close, expired protective-order review with the original cutoff,
missing opening quotes, frozen contract changes and detached export tampering. A subsequent paid Scope entry in the same carry-series owner
retains the first closed loss, cumulative charges and the second-loss lock. Existing
entry/model, native combined carry and Scope comparison compatibility
also passed on the final wheel. The preceding candidate wheel passed 263 distinct
installed checks, including legacy Scope shortlist/model and session-series checks.
Only `app/options/scope_carry_series.py` changed afterward to preserve unresolved
intraday exposure and overdue bounded-carry exits in the gap report. That broader
proof, exact source delta and its earlier wheel are retained separately and are not added to the final count.

Diagnostic failures and their logs/XML remain retained. They exposed an initially
incomplete new B result/usage union, unshifted fixture session boundaries, and a
Scope fixture incorrectly attempting a second-day entry cycle without new Scope
input. The complete B receipt binding and fixture evidence were corrected; old
adapters, missing-input gates and native unknown-cost protection remain intact.
A focused diagnostic also corrected an expectation of automatic retry after an
expired protective order; the existing native review halt was preserved and
explicitly verified. A reused proof directory was retained as a separate failed
diagnostic; final native runs use fresh directories. The earlier final four-account
Scope session bundle also reconstructs exactly on this wheel; that artifact check is separate from the pytest count.

Wheel SHA-256: `6a4daefee36c3f5537c914be20409b075c755bed3c82054ad333ec6d587337b6`. All 206 application/template files match
source, wheel and installed bytes. Proof/source/test copies: `../scope-carry-series-proof/`;
wheels: `../scope-carry-series-wheels/`; installed environment: `../scope-replay-env/`.
Ruff, dependency consistency, local Markdown links and copied-test identity passed.

Next plumbing: automatic Swing target derivation, remaining supported family
integration and one mixed stock/options owner. Continue from the pinned source
contracts without reopening strategy decisions. Final UI and authentic
provider/model/host/economic/PAPER acceptance remain open and follow plumbing. LIVE stays disabled, the deployed experiment frozen,
PR #1 draft and main untouched. No dependencies, authenticated provider/model/broker
calls, deployment or merge were introduced. Settled strategy decisions and blocked
unsupported Scope plans remain unchanged.

## Native repeated-entry attribution plumbing: 2026-10-21 UTC

The working branch and local HEAD started at
`f9438f351f15941c3ca9af79ddfb4599601d4a9c`, tree
`1d86de8eb95d17a4006ab71fdecc2d0e97046275`, with a clean working tree.
Main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 remained open/draft.

[Native repeated-entry attribution](OPTIONS_NATIVE_ENTRY_ATTRIBUTION.md) now adds
explicit `later-flat-entry-v1` enrollment to the frozen native loss policy. New
full-entry owners can keep an already closed trade's exact full-cost loss record
while a later paid entry is pending. Complete typed request/call binding must
prove a reconciled flat account captured after that close, with original packet
and call clocks in order. Native stored loss policy and owner policy must match.
This does not assign the later charge to the prior holding or omit it from account
costs. HOLD/rejected advice remains charged; unknown usage remains unknown and
keeps account-level net results incomplete. Management, overlapping/unproven calls
and legacy cohorts retain their conservative behavior.

Model-off/selection-only owners and replay adapters cannot acquire this native
contract. The policy cannot be added or removed on reopen. Historical serialization
is unchanged when it is omitted. Runtime settings carry the same frozen policy.
Repeated Scope admission still requires delivered fresh observations, native
account revision, original source clocks and approval deadlines. Two realized
losses still produce the original account/family lock; no loss, reservation,
fee, model charge, data/host allocation or protective deadline is reset.

Validation: **189 distinct installed checks passed on the final wheel**,
including **22 new cases**. This proof is separate from the preceding series
wheel's 267 checks and is not added to that overlapping count. Exact case IDs and
phase timings are in `../native-entry-proof/final-proof.json`. Native runs were
serial, against a noneditable installed wheel and copied tests outside the checkout,
with Python `-I`, warnings as errors and plugin autoload disabled. Coverage includes
successive CALL/PUT Scope entries with/without combined carry, saved pending-call
evidence, HOLD, unknown usage, corrupted linkage, frozen reopen, old behavior,
continuous delivered-input runtime and portable native export. Native outcome/loss,
shared Scope AI, Scope runtime and carry compatibility also passed.

Diagnostics exposed stale nested fixture metadata and a reused fixture provider
request ID. Fixtures were corrected; freshness and duplicate-charge gates remain
unchanged. Other diagnostic runs retained explicit rejection/immutable-reopen
assertions, a nonrepeating SQLite write/fence failure, and a stale runtime feed.
No authority file was reset or repaired. These runs are excluded from final proof.

The concurrent runtime test exposed repeated validation work that could starve
protection processing or exhaust the original fresh-evidence deadline. Profiling
identified eleven validations of the same two entry lineages in one outcome read.
Successful lineage validation is now reused only for exact arguments inside that
synchronous call and its existing unchanged transaction. Writes disable reuse;
changed arguments, separate calls and separate owners are always revalidated.
New explicitly enrolled Scope runtime owners also wait for protection-tick
completion before paid refresh. Failed/canceled ticks cannot supply admission,
and canceled model refresh cannot cancel protection. Legacy runtime cohorts keep
their prior behavior. The two-entry runtime case passes with concurrent completion,
original deadlines and complete delivered receipts. Focused cache/cancellation
boundary checks also passed. All final checks ran again on the final wheel; no
earlier-wheel diagnostic passes or overlapping cases are added to its count.
No process, model, approval or protective deadline was extended.
The prior complete four-account/two-session Scope bundle also reconstructed exactly
on the new wheel; this artifact check is recorded separately, not counted as pytest.

Environment: `../scope-replay-env`; proof: `../native-entry-proof/`; wheel directory:
`../native-entry-wheels`; wheel SHA-256: `7bf7767e6361ac852a3c57f256b4550869d30e970cf849b633455780e1ac88fd`.
All 204 application/template files matched source, wheel and installed
bytes. Ruff, dependency consistency, local Markdown links and copied-test identity
passed. Proof retains logs/XML, source, test copies, pending/native journals, export
receipts and publication metadata.

Next: combined Scope/carry replay, remaining family integration and one mixed
stock/options owner. Final UI and authentic PAPER testing remain after plumbing.
No authenticated provider/model/broker call, dependency change, deployment, merge
or main modification occurred. LIVE remains disabled and the deployed experiment
frozen. Settled strategy rules and blocked unsupported Scope plans remain unchanged.

## Continuous Scope session replay/accounting plumbing: 2026-10-21 UTC

Fresh local/GitHub state matched `b7cbd51d27063144cbc5a5f4f7b6b91ead902e49`,
tree `9e2cf164441eb2adad4e13d64037b67dd2cdcef8`, with a clean working tree.
Main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

[Continuous Scope series](OPTIONS_SCOPE_SERIES.md) now retains four independent
native A/B/C/D owners across ordered session-close tapes. Cash, reservations,
positions, explicit funds settlement, all entry/management charges, fees and
account/family loss controls remain continuous. Each owner enrolls once. The new
`scope-native-series-model-v1` contract binds every ordered tape, the whole request
and the complete original per-arm script. Existing single-session contracts, old
adapters and combined-carry replay restrictions remain intact.

Each session starts with empty delivered-market/position caches and its own Scope
reader. Fresh paid admission retains original source clocks, native revisions,
fixed Scope terms and approval deadlines. Independent protection and later-quote
fills remain authoritative. Consistent evidence-only SQLite snapshots and portable
native exports preserve every closing boundary. Reconstruction checks exact frozen
owner/model/source policies, event prefixes, old economic rows, original order
and watch identities, explicit settlements and cumulative operating allocations.
Backdated new economic evidence cannot be silently moved into the next session.
Unknown earlier costs remain unknown; unresolved holdings remain owned and unvalued.

Session rows open from the prior closing ledger and charge only the new model/fee
increments plus explicit period allocations. Whole-series paired nets require all
four accounts and all boundaries to be complete and flat. Known account totals
remain separate. Supplied valid SPY endpoints support session midpoint returns and
known-only compounding; missing evidence is not interpolated. Overnight gaps,
dividends and benchmark costs remain excluded. Economics stays INCONCLUSIVE.

A diagnostic found a real second-entry attribution blocker: a later paid entry
request temporarily made a previously closed trade's outcome pending. The new
series contract now proves the later request was made on a flat account after that
close, keeps its charge in account totals/diagnostics, and preserves the old trade's
loss record. It does not waive unknown costs, management linkage or fresh approval.
Legacy cohorts keep their existing conservative behavior. Explicit native/runtime
adoption and repeated-entry proof remain a named follow-up before native plumbing
can be called complete.

A later diagnostic hit the original five-second dispatch window while repeatedly
reconstructing the same paid evidence. Read-only outcome reconstruction now reuses
validation only within that one call/transaction. Canonical fingerprint processing
avoids repeated model/date introspection for exact built-in JSON primitives, while
retaining the old normalization path for subclasses and identical canonical bytes.
A subsequent return-format assertion found internal tuples versus portable JSON lists;
the series report now normalizes its returned JSON representation. Native execution
and the reconstructed amounts were already correct.
No approval, model, process or protective deadline was extended; uncertain attempts
still halt and never retry. Focused timing evidence is retained separately and is
not counted as final pytest proof. The focused second-entry validation times were
2.57 seconds for C and 2.98 seconds for D, with the original five-second process
limit and earlier approval deadline intact.

Validation: **267 distinct installed checks passed on the final wheel**,
including **42 new cases** and **225 compatibility cases**. Exact case
IDs and phase timings are retained in `../scope-series-proof/final-proof.json`.
Every phase used a noneditable installed wheel, copied tests outside the checkout,
Python `-I`, warnings as errors, disabled plugin autoload and serial native workers.
Diagnostic runs and overlapping checks are excluded. Source/wheel/installation
identity, Ruff, dependency consistency and local Markdown links passed.

Environment: `../scope-replay-env`; proof: `../scope-series-proof/`;
wheel directory: `../scope-series-wheels`; SHA-256:
`285861e5ed85a71a787d16448ee71618fa9469236a674e99795ec7d8f36e348f`. All 204 application/template files matched exactly.
Proof retains logs/XML, copied tests, native journals, closing snapshots, portable
exports, source and identity. No authenticated provider/model/broker call, dependency
change, deployment, merge or main modification occurred. LIVE remains disabled and
the deployed experiment frozen.

Next: explicit native repeated-entry attribution, combined Scope/carry replay,
remaining family integration and one mixed stock/options owner. Final UI and
authentic PAPER testing remain after plumbing. Convexity/full-path and missing-T3
four-contract Scope plans remain blocked; no settled strategy rule was relaxed.

## Combined native Scope/Swing carry plumbing: 2026-10-21 UTC

Fresh local/GitHub state matched `f4da7937e721e7dd1f3765a2715f7102cf79d613`,
tree `0c9a6c487d22dd5136d3cfc88ec01016e24fb64c`, with a clean working tree.
Main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

[Combined native Scope/Swing carry](OPTIONS_SCOPE_CARRY.md) now requires explicit
`shared-scope-carry-v1` markers on the native owner and shared strategy, plus the
full entry/management policies when enabled. The owner retains all three family
loss controls and the existing bounded Swing policy. Runtime creation, coordinator
creation, management packets and stored shared/export reconstruction check matching
contracts. Existing populations cannot acquire the enrollment; absent optional
fields and old prompt/schema/configuration hashes preserve frozen cohorts.

The separately hashed entry prompt and strict plan permit a multi-session horizon
only for a selected Swing candidate with original native carry terms. Degen remains
intraday. Scope still selects its exact fixed plan without replacement geometry,
quantity, target, premium profile or deadline. Its paid selection still requires
fresh owned post-cost admission, advancing source clocks, account revision and the
original approval/model deadline. Native usage settlement now recognizes the full
combined plan; paid rejected advice remains charged.

The separately hashed management prompt binds either Scope's original fixed plan
and paid entry thesis or Swing's original daily scan and enumerated carry sessions.
MAINTAIN/TIGHTEN/EXIT_ALL retain original protection and actual native fills. Scope
never acquires an overnight horizon. Swing retains its original first target and
exit, short-lived approval, DAY attempt and explicit unknown overnight path. Held
and unresolved exposure continues to reserve the common account.

Continuous runtime/restart retains the exact holding and original deadline. Feed
loss cannot erase independent latched exits; fresh exact quotes remain necessary
for a close. An unfilled Scope watch expires at its original cutoff while a Swing
holding carries. Native portable export verifies the combined frozen contract and
compares original carry terms against ledger/venue holdings. Entry/management
charges, execution fees and explicit whole-period data/host allocations remain in
full-cost accounting. Unknown costs and unresolved exposure remain unknown.

Validation: **489 distinct installed checks passed on the final wheel**, including
**40 new combined-carry cases** and **449 compatibility cases**. The disjoint
new-case phases `boundaries` and `native` took 37.52 and
230.06 seconds. Compatibility phases `profile`, `core`, `runtime` and
`comparison` took 700.08 seconds in total. New cases cover all three
entry families, CALL/PUT, both holding contexts, all three management actions,
restart/feed loss/watch expiry, malformed enrollment, fixed Scope geometry,
original horizon/target limits, paid refresh rejection, mocked SDK schema/transport,
portable accounting and rehashed stored-enrollment tampering. Compatibility covers
legacy entry/position reasoning and workers, native standalone carry, Scope paid
entry/management, Scope/legacy runtime, tape rejection/release identity, four-account
comparison and unknown-cost account isolation.

All runs used a noneditable wheel, copied tests outside the checkout, Python `-I`,
warnings as errors, disabled plugin autoload and serial native workers. Diagnostic
runs and overlapping reruns are excluded. Initial diagnostics found the missing
combined-plan usage parser; it was fixed. Subsequent fixture-only corrections
created runtime enrollment before trading and used explicit order chronology.
No native protection was relaxed to make a fixture pass. An interrupted broad
compatibility run is excluded after an apparent partial-close management stall.
The focused final-wheel run passed in 55.23 seconds versus 45.96 in the prior
proof, without further application changes. Remaining compatibility phases ran in separate serial interpreters.

Environment: `../scope-replay-env`; proof: `../scope-carry-proof/final-proof.json`;
wheel directory: `../scope-carry-wheels`. Wheel SHA-256:
`794a483bcad8309d28131b0d14b33e754becfcc7d65a5a2b76f4ef5a22295238`.
All 203 application/template files matched source, wheel and installed bytes.
Ruff, dependency consistency and local Markdown link checks passed. Proof retains
exact case IDs, logs/XML, copied tests, native journals/exports, source and identity.

Current Scope replay/model/comparison adapters remain single-session contracts and
reject combined carry. The old replay adapter and choice-only B cannot enter this
new runtime owner. Remaining work: Scope multi-session/benchmark comparison, broader
family completion and one mixed stock/options owner. UI and authentic PAPER testing
follow that plumbing. Convexity and missing-T3 four-contract Scope plans stay blocked.
No dependencies, authenticated provider/model/broker calls or deployments changed.
LIVE remains disabled; the deployed experiment stays frozen. Do not merge or modify main.

## Continuous Scope watch/runtime input plumbing: 2026-10-21 UTC

Fresh local/GitHub state matched `24025825bca7794bd09739f4e7d994843cdf4587`,
tree `3ce4515ea77a138529d1b8ebe37d0a00938aa56d`, with a clean working tree.
Main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

[Explicit Scope runtime enrollment](OPTIONS_SCOPE_RUNTIME.md) now connects the
installed create/run path to the existing native watch/coordinator owner. Frozen
settings bind family priorities, source/universe/quote capacity, loss policies and
model-off or full entry/management contracts. Old packet serialization and missing-
version defaults remain intact. Legacy packets reject nested Scope; Scope packets
require their own explicit version/enrollment. Old and B replay adapters remain
excluded from the continuous native runtime. Combined carry/Scope remains blocked.

WATCH, MARKET and CYCLE receipts are distinct. Watch/market updates do not consume
a five-minute entry/management slot. New packets require consecutive sequences;
repeated identical packets do not repeat work. Missing sequence, foreign/future/
conflicting evidence, changed original session/deadlines and reused action identities
fence entry before the next awaited native snapshot. Exact common/nested quotes
feed independent protection. Original unfilled-watch cutoffs expire during missing
feeds and halts without inventing observations or changing submitted positions.

The runtime persists delivery before suspension, then applies an explicit watch
instruction at the actual current clock/revision after supervision. No external
account revision, approval or fill is accepted. Durable rejection/interruption
receipts prevent retries, including the process window after native watch commit
but before transport receipt completion. Restart retains halt/recovery semantics.
Full paid Scope review consumes only delivered, completed observations for the exact
play. It preserves original terms, advancing source clocks, native post-cost
admission and original deadlines. Known charges remain for rejected/late advice;
unknown usage remains unknown. Protection continues during pending model work.

Stored runtime summaries expose bounded receipt metadata without reading the feed.
Optional native export retains complete Scope runtime packets/actions and verifies
packet hashes plus exact native request/revision/receipt links. Existing exports
without this enrollment keep their shape. Every entry/management charge, execution
fee and explicit operating allocation still belongs to its independent native
account. Unfinished exposure and unknown costs remain unresolved.

Validation: **284 distinct installed checks passed on the final wheel**, including
**31 new Scope runtime cases** and **253 compatibility cases**. Runs `final`,
`compatibility` and `crash` took 88.61, 998.44 and 3.27 seconds respectively. The
compatibility suite covers legacy runtime/operator recovery/release identity,
shared Scope paid entry/position reasoning, deterministic arbitration, old tape
boundaries and the full independent A/B/C/D comparison, including unknown-cost
isolation. New cases cover both rights, complete watch/arming/entry/fill/deadline
paths, explicit enrollment and transport rejection, source/session/sequence faults,
delivered versus stale/late/missing post-cost input, paid charges, independent
management-time protection, cutoff expiry and before/after-native-commit interruption.
Portable runtime packet/request/receipt links are reconstructed and tamper checked.

All runs use a noneditable installed wheel, copied external tests, Python `-I`,
warnings as errors, disabled plugin autoload and serial native workers. Exact case
IDs and phase receipts are in `../scope-runtime-proof/final-proof.json`; diagnostic
runs and focused passes are excluded from the distinct count. The proof retains
logs/XML, copied tests, native journals/exports, source snapshots and identity.
Environment: `../scope-replay-env`; wheel directory: `../scope-runtime-wheels`.
Wheel SHA-256: `fe8b0f3a64557b9e63430ff136d96555680fd0e4dd09f14e72c7d32bb187dcb0`.
All 202 application/template files match source, wheel and installation. Ruff and
dependency consistency pass; local Markdown link references were checked.

Diagnostics initially
caught the new table missing from the native journal reopen allowlist; that was
fixed. A test fixture skipped its last required arming sample and correctly failed
Scope admission; the sample was restored without relaxing native continuity.
Another fixture used text instead of Decimal in a copied quote and was corrected
under warnings-as-errors. Earlier diagnostic passes are not added to final totals.

Next: combined Scope/Swing carry, remaining families and mixed stock/options
ownership, plus Scope multi-session/benchmark comparison. Final UI and authentic
PAPER testing remain after plumbing. No dependency version, deployment, authenticated
provider/model/broker call, main merge or LIVE change occurred.

## Independent Scope A/B/C/D comparison and choice-only B: 2026-10-21 UTC

Fresh GitHub/local state matched `cccf68072c8636039d0be32da9d781983ae0d491`,
tree `148ba7cc0d9736ff61678661a7e63e755d5d9280`, with a clean working tree.
Main remained `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

The [separate Scope comparison](OPTIONS_SCOPE_COMPARISON.md) now runs independent
A/B/C/D owners against the same sealed tape and ordered watch actions. It rejects
reused population/account identities, tape/watch drift, unequal capital/risk/fees,
operating allocations and mismatched model costs/limits before creating output.
C/D retain exactly matched declared entry scripts; D management remains separately
paid. Actual reached opportunities, cash, reservations, order/fill identities and
loss controls stay native to each account. No account state or fill is copied.

B now has a versioned SELECT/HOLD/UNKNOWN script, choice-only prompt and full native
receipt. It cannot change any family's original geometry. Ordinary Degen/Swing
selection preserves the original proposal, caps and deadline, with native family/
session exits and no invented model target/horizon. Scope selection still requires
fresh owned post-cost review and the original terms/source clocks/revision/deadline.
The normal authenticated runtime, old adapter and unenrolled new adapters remain
blocked. Existing cohort serialization and ordinary C/D behavior are preserved.

An ordinary B test exposed a dispatch assumption that every full entry receipt has
a model target protection record. Dispatch now recognizes only the explicit B
shortlist policy, still rechecks the complete paid receipt, and rejects missing or
changed stored receipts before an attempt. Known model charges survive rejection.
No protection threshold, source clock or model deadline was relaxed.

The portable comparison binds each owner/strategy/model configuration to the
retained request and each B/C/D enrollment to its tape/script. It reconstructs
native accounting and exact decimal differences versus A. All entry/management
charges, execution fees and explicit allocations remain; unknown costs or unresolved
exposure suppress paired net results while retaining known independent account
results. Root-hash and native reconstruction detect altered reports/transplanted
exports. Create-only failures preserve partial evidence. This is single-session
fixture accounting, economically INCONCLUSIVE, with no benchmark/provider/host claim.

Validation: **239 distinct installed checks passed on the final wheel**: 43 new
shortlist/comparison cases and 196 compatibility cases. The new cases cover both
Scope rights, ordinary Degen/Swing selection, lost/changed paid receipts, fixed
geometry and ceilings, late/HOLD/missing/unknown/stale responses, matching and
independence boundaries, portable tamper checks, interruption and unknown-cost
isolation. Compatibility covers historical entry geometry/dispatch/restart/optional
serialization, C/D response contracts, old tape/adapter rejection and native shared
family/Scope management behavior. Final run times were 7.82, 484.01, 4.53 and
68.03 seconds respectively; no overlapping cases or earlier checkpoints are added. Final proof and exact case IDs are in `../scope-comparison-proof/final-proof.json`;
initial diagnostics and focused reruns are retained without double-counting. The
first script test exposed a slot-pattern validation gap, fixed with explicit entry
slot validation. The ordinary dispatch blocker above was reproduced and fixed;
subsequent fixture assertions were corrected to respect omitted optional fields
and the existing family-priority order of the Swing shortlist.

All tests run serially against a noneditable wheel with copied tests outside the
checkout, Python `-I`, warnings as errors and plugin autoload disabled. Final-wheel
runs are `ordinary2`, `release`, `swing2` and `compatibility`; earlier wheel/diagnostic
passes are excluded. Native evidence also verifies four distinct entry IDs and eight
distinct fills. No authenticated provider/model/broker calls occurred.

Wheel SHA-256:
`ab2640fad8de16d955ed03bf6240b250cda244709247ede5ec50506ec4209b3f`.
All 201 application/template files match source, wheel and installation. Ruff,
dependency consistency and 367 local documentation targets pass. Proof includes logs,
JUnit summaries, copied tests, final native journals/exports, `account-isolation.json`
and source/wheel identity. Environment: `../scope-replay-env`; wheel:
`../scope-comparison-wheels/`. Abandoned copies of this project's prior installed
wheel were removed from the scratch environment; no dependency version changed.

Next: continuous Scope watch/runtime inputs, then combined Scope/Swing carry and
remaining family/mixed stock-options plumbing. Scope multi-session/benchmark
comparison and final authentic data/model, host and visual acceptance remain open.
Finish plumbing before final UI and authentic PAPER testing. Main, PR draft status,
LIVE-disabled state and the deployed experiment remain unchanged.


## Native shared Scope C/D tape scheduling and accounting: 2026-10-20 UTC

Resumed the retained uncommitted draft after the workspace connection failed.
Fresh local/GitHub state matched `e777def5a1f866c9dd0efc40797c56f3a9b04c84`,
tree `c970a33e01a5657afca07d860169a3107cc7e53a`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 open/draft.

The separate [native C/D tape path](OPTIONS_SCOPE_MODEL_REPLAY.md) now binds the
full scripted entry/management contract to a frozen tape/request/script enrollment.
Each invocation creates independent native journal/venue files, capital, reservations,
orders, fills and loss state. All equal-time receipts are delivered before releasing
a model result. Fresh Scope selection uses only the exact latest complete observation
already delivered for that play, with receipt sequence and event/input/tape hashes
retained. No source clock is rewritten and no cached quote is merged into old context.

Native usage settlement precedes fresh owned admission. Original Scope terms,
quantity/fee ceilings, source clocks, account revisions and original deadlines remain
binding. Proposals, native approval, attempts and later actual fills stay distinct.
D uses the existing MAINTAIN/TIGHTEN/EXIT_ALL path; deterministic protection continues
while a response is pending. Unknown usage and explicit operating allocations stay
unknown. Portable export retains every entry/management charge and execution fee.

The pending-stop case exposed a loss-finalization race: a charged management result
could be consumed into a closed loss record before its native application was stored.
For this new frozen replay enrollment only, position outcomes now remain incomplete
while that exact management cycle is STARTED. The scheduler refreshes loss controls
once the decision becomes terminal, at the original completion clock. Known charges
and mandatory fills are never deferred. Unknown management usage leaves the loss
outcome unresolved. Existing cohort loss-record serialization/behavior is unchanged.

The old replay adapter and unbound new adapter remain rejected. Legacy comparison
consumers still reject Scope. This slice delivers individual C/D native runs, not
B or the matched independent A/B/C/D comparison/export wrapper. No strategy decision
was reopened. All remaining plumbing precedes final UI and authentic PAPER testing.

Validation: **148 distinct installed checks passed on the final wheel**: 23 new
native replay cases and 125 compatibility cases. The new cases cover both rights,
C entry, all three D actions, same-time fresh reads, original approval deadlines,
later fills, late/HOLD/missing/unknown/stale responses, seven enrollment boundaries,
known/unknown management during protective closure, frozen reopen without retry,
tampered configuration, unknown operating allocation and create-only output.
Compatibility covers full response contracts, historical tape/watch serialization,
unsupported consumers/old adapter rejection, native shared-family behavior, legacy
loss controls and the deterministic A native replay/export.

Runs are serial noneditable installed-wheel checks using copied tests outside the
checkout, Python `-I`, warnings as errors and disabled plugin autoload. The final
receipt unions exact passed case IDs: `additional6` (2), `reopen` (1), `boundaries`
(12), `release` (5), `release3` (3) and `compatibility` (125). Their elapsed seconds
are respectively 349.198, 108.096, 44.807, 914.854, 440.373 and 200.727. Partial-run
failures are retained, and each failed final-wheel case has a later focused pass.
No overlapping cases, diagnostic passes or earlier checkpoint counts were added.

Initial fixture assumptions were corrected: a flat rejected entry must not request
a held-only cycle, stale evidence returns explicit native admission rejection,
required policy fields and sealed-tape mutation must be valid, and reopening a
venue must omit creation capital. A near-close management attempt correctly hit
its existing preflight gate, so pending protection uses an earlier stop breach.
That exposed the actual loss-finalization race fixed above. Two native five-second
worker timeout failures are retained: an initial uncertain entry acknowledgement
and the final matrix's PUT TIGHTEN snapshot read. Focused reruns passed without
changing worker limits or deadlines. An overly broad retry selector was interrupted
and replaced by exact case IDs; it contributes no passes. Host acceptance remains open.

Wheel SHA-256:
`73fd0e6f9ad27e8e13442187e1e6383e8249bfa3b8271aa5a401167de5c7d374`.
All 199 application/template files match source, wheel and installed files. Ruff,
dependency consistency and 360 local documentation targets passed. Proof:
`../scope-native-model-proof/final-proof.json`, `build.log`, `install.log` and
`release/` (copied tests, completed summaries/XML, native journals and diagnostics).
Environment: `/tmp/scope-replay-env`; wheel: `../scope-native-model-wheels/`.

Next: B shortlist integration and matched independent A/B/C/D comparison/export,
then continuous Scope watch/runtime inputs. Combined Scope/Swing carry and remaining
family/mixed stock-options plumbing remain later. Final UI/visual and authentic
feed/model acceptance remain open. No dependency, authenticated provider/model/broker
call, deployment, LIVE, main or merge change is authorized by this fixture proof.

## Full shared Scope C/D scripted response contract: 2026-10-20 UTC

Fresh GitHub/local state matched `800844045a1a65f0d4675c42fba825b6ca591617`,
tree `f6e7c7e6b1d00a537ea34d29cf14d963bd935d93`; the working tree was clean,
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 open/draft.

The separate [C/D response contract](OPTIONS_SCOPE_REPLAY_MODEL.md) now supplies
strictly typed, tool-less scripted full entry and position receipts. Fixed Scope
ENTER binds the original candidate digest/evidence without replacement terms.
Ordinary family entry retains explicit indexed selection and complete geometry;
HOLD and D MAINTAIN/TIGHTEN/EXIT_ALL retain their full native protocol. Original
packet/configuration hashes, source context, owned entry/revision and deadlines
survive unchanged. Matching C/D declarations must agree on every entry slot,
choice, geometry, delay and token count; D management remains separate.

The response adapter owns no account, clock, tape, venue, credential or cost ledger.
Its future exposes the original virtual completion time without advancing clocks
or renewing leases. Missing/UNKNOWN scripts retain unknown usage. Invalid proposals
return safe full error receipts with known synthetic usage retained. Late release
retains its known usage and original deadline for the future native owner to enforce.
Cancellation consumes the in-memory slot and clears pending state; overlapping calls
cannot consume a second opportunity. Durable restart prevention, paid cost settlement
and execution approval remain native integration work.

**This is not native replay enrollment.** Tests prove both old and new adapters are
still rejected by the shared Scope coordinator. No existing application module was
modified, and all 196 prior application/template files match the previous wheel
byte-for-byte. The deterministic A baseline remains the only delivered Scope trading
replay. B integration, C/D tape scheduling, exact fresh post-cost Scope observations,
original deadline consumption, mandatory protection during pending calls and
independent all-cost comparison/export remain open. No strategy decision was changed.

Validation: **115 distinct installed checks passed**, comprising 62 new contract
cases in 99.26 seconds and 53 compatibility cases in 12.57 seconds. New cases use
captured native CALL/PUT entry and owned-position requests, verify full result
protocols and original request preservation, and cover ordinary/HOLD alternatives,
late/unknown/missing usage, rejected selections/stops, cancellation, overlap, matched
scripts and continued enrollment rejection. Compatibility retains golden tape bytes,
source/clock/capacity checks, legacy consumers, old adapter guards and watch serialization.
No overlapping cases or previous checkpoint passes were added to the total.

Tests ran serially from copied tests outside the checkout, against a noneditable
installed wheel with Python `-I`, warnings as errors and plugin autoload disabled.
The first invocation failed collection because the isolated harness omitted the
copied test package root; adding that copied root fixed collection without exposing
the checkout. The two complete application runs passed without timeout/retry.
Ruff, dependency consistency and 181 local documentation targets passed.

Wheel SHA-256:
`deb62d4e1a6d18ebd6d2ae47b8156904bf82879173d1ae108fa6565d67ccbe75`.
All 197 current application/template files match source, wheel and installed files.
Proof: `../scope-model-proof/final-proof.json`, `build.log`, `install.log` and
`release/{contract,compatibility}.{log,xml}`. Environment: `/tmp/scope-replay-env`.
The release proof also retains the copied tests, native capture journals and initial
collection diagnostic. No dependency versions, provider/model/broker calls,
deployment, LIVE activation, main or merge state changed.

Next: connect the C/D response contract to explicitly enrolled native tape scheduling
and fresh post-cost Scope admission, then complete B and independent A/B/C/D export.
Continuous Scope watch/runtime inputs follow. Carry/mixed-family plumbing and final
UI/visual/authentic-data/model acceptance remain later work.

## Deterministic Scope tape trading baseline: 2026-10-20 UTC

Fresh GitHub state matched `8cb6b5142cdc712c3cedbbd0f6dff6fdb86156a0`,
tree `d1fc90aba4972016b99a41bb993c2517fcd412c1`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 open/draft.
The previous scratch checkout/environment/proof were not retained. A fresh clean
branch checkout and isolated environment were restored from the unchanged exact
runtime, development and build locks. No dependency versions changed.

[Deterministic Scope tape trading](OPTIONS_SCOPE_TRADING_REPLAY.md) now connects
sealed watch references to one independently funded native A baseline. Shared
selection, owned approval, attempts, later executable fills, partial fills, original
Scope time protection and final family/global loss controls use the existing native
coordinator and scheduler. Exact nested Scope prices enter the fill/protection loop
once; future equal-time observations cannot affect earlier cycles. Complete enrolled
family evidence remains mandatory. Native cycle failure leaves an incomplete marker.

The create-only API rejects policy drift, model/AI enrollment, carry, bad seals,
unordered/duplicate references and out-of-session instructions before output creation.
Each owner retains its own cash, reservations, order/fill identities and loss state.
Portable accounting preserves every actual fee, explicit allocation and unknown cost;
missing exit liquidity leaves exposure and net accounting incomplete. Returned report
and saved JSON agree. The result explicitly remains arm A, comparison incomplete and
NOT_EVALUATED. Existing app modules, legacy serializers/consumers and the Scope AI
replay-adapter restriction are unchanged.

Validation: **77 distinct installed checks passed** on the final noneditable wheel:
24 new trading cases and 53 focused compatibility checks. The complete new suite
passed in 585.30 seconds; compatibility passed in 48.86 seconds. Tests were copied
outside the checkout, run with Python `-I`, warnings as errors and plugin autoload
disabled. An attempted deselection used absolute IDs and did not take effect; the
six repeated passes are counted only once, using the complete final 24-case run.

Release wheel SHA-256:
`9e299480824f677cbd67653bd128381034710f2564add99895012d02e99b3a0c`.
All 196 application/template files matched source, wheel and both installed copies.
Proof: `../scope-trading-proof/final-proof.json`, `identity.json` and
`local-release/{remaining,regression}.{log,xml}`. The copied local environment was
`/tmp/scope-replay-env`; the restored workspace environment is `../scope-replay-env`.
Complete logs and failed/interrupted diagnostic artifacts remain under that proof
root. Frozen tape bytes, nested source clocks/capacity, all old consumer guards,
Scope AI adapter rejection and legacy watch-request serialization passed.

Initial failures identified an incomplete mixed-family fixture and tuple/list report
normalization; both were corrected. Subsequent concurrent and workspace-serial runs
hit the unchanged native five-second child deadline. These interrupted/failed runs
are retained as diagnostics, not passed proof. The isolated failure journal showed
an uncertain attempt followed by authoritative reconciliation refusal. Tests were
moved to a temporary local copy of the same noneditable installed environment and
copied tests; all 196 installed app/template files still matched the release wheel.
One partial-fill case also hit that deadline in the temporary environment, then
passed in the subsequent complete run. No native deadline, approval lifetime or execution
gate was relaxed. Failed/interrupted attempts are not added to distinct pass counts.

Full B/C/D role contracts, paid fresh post-cost Scope admission and managed common-tape
comparison/export remain next, followed by continuous Scope watch/runtime inputs.
Combined Scope/Swing carry, remaining family/mixed stock-options plumbing, final
UI/visual and authentic-data/model acceptance remain open. No provider/model/broker
calls, deployment, LIVE activation, merge or main changes were made.

## Tape-linked independent native Scope watches: 2026-10-20 UTC

Fresh GitHub/local state matched `c8beed32702ead238e3d100db4bde25d533ad7dc`,
tree `97f38d66fd9c20daf86a64e83cfc9ac302bfc58c`. The retained checkout was clean;
main remained `b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 open/draft.

[Common Scope tape replay](OPTIONS_SCOPE_MARKET_TAPE.md#tape-linked-native-watches)
now drives CALL, arming, owned admission, completed-bar/quote invalidation, neutral
reset and cutoff expiry through independent native watch owners. The existing
create-only native replay request explicitly enrolls `scope_tape` and strict
`ScopeTapeWatchAction` references. Exact watch/source limits and the session open
are frozen; only account/population identities may differ from the common market
limits. Raw watch payloads, native trading steps and shared coordinator enrollment
cannot be mixed into this watch-only mode. Old requests retain their original JSON,
canonical hash and native execution/export behavior.

Each referenced observation must already be visible for the exact play. Input/source
clocks, contract, context and session deadlines remain unchanged; delayed observations
do not become fresh. Missing samples are explicit and timer expiry needs no fabricated
market input. Each owner reconciles/supervises and obtains its own actual revision
before applying the native action. No admission or cash/position/fill state is copied
between owners. Saved receipts bind original instructions, tape/policy/event/input
hashes, resolved steps and native revisions. Expected rejected actions cannot mutate
the watch revision; unexpected mutation marks the run incomplete.

Four independent owner fixtures retain distinct account admissions and portable
exports from the same tape. A constrained owner rejects an opportunity admitted by
another owner. Restart preserves original watch terms. Portable native accounting
retains explicit data/host allocations and unknown costs. The report explicitly says
`COMPLETE_TAPE_WATCH_REPLAY`, `comparison_complete=false` and `NOT_EVALUATED`.
No model attempt, order, fill, settlement or loss reset is generated by this mode.
It is not A/B/C/D trading comparison or authentic source acceptance.

Validation: **201 distinct installed checks passed**, including **45 new cases**.
The broad run passed all 201 in 212.16s. The final clean wheel passed **109**
checks in 100.995s, covering all new cases, native replay/export and the retained
unsupported-consumer/model-adapter boundaries. Overlapping runs are not added.
The initial focused run passed 33/34; its restart fixture incorrectly supplied
create-only capital arguments while reopening a venue. Correcting the fixture to
use the existing reopen API resolved it without changing a native boundary.
The focused correction/addition run passed 13; all cases subsequently passed in
the broad and applicable final-wheel runs. No failures/errors/skips remain in the
normalized case ledger.

The initial wheel inventory found an unused `scope_tape.py` left in the retained
build directory by the superseded prototype. A clean build removed it. Every other
application byte is identical between the broad-tested and release wheels. All
**195 application/template files** now match source, release wheel and installed
inventory exactly. Copied tests match source; lint/format, dependency consistency,
whitespace and 204 local documentation targets pass. Tests use noneditable isolated
wheels, copied tests outside the checkout, Python `-I`, disabled ambient plugins,
warnings as errors and separate retained pytest directories. Release wheel SHA-256:
`ab3c382dc6a9ecefb16b578adcbd549c396868d418bc22a1ed12b8c241c0ddab`.

Proof: `/workspace/scratch/c2a4a0346b96/scope-tape-watch-proof`, including all logs,
JUnit, fixture state, `identity.json` and per-case `validation-summary.json`.
Release wheel: adjacent `scope-tape-watch-release-wheels`; installed environment:
`scope-tape-watch-env`. Earlier wheel/build output is retained separately for audit.
README, source of truth v1.85, continuation and replay/testing guides are updated.

Next: connect these watch lifecycles to full A/B/C/D model contracts, original
approval leases, fresh post-cost Scope admission, later actual fills and managed
full-cost comparison export, then continuous watch/runtime input. Existing comparison
consumers and the old shared Scope AI adapter remain explicitly blocked. Combined
carry, remaining family/mixed ownership and UI/authentic-data acceptance remain later.
No dependency, authenticated provider/model/broker call, deployment or host setting
changed. Main remains untouched, PR draft, LIVE disabled and deployed experiment frozen.

## Scope tape publication reconciliation and acceptance: 2026-10-20 UTC

The working branch advanced from `33106efa6a064d1c8b0415a5f888752759e70155` to
`8f407f2e6fdb409fcee228699690bfe38326a42c` during publication. The protected ref
update did not overwrite that concurrent work. This follow-up adopts its full
`ScopeTapePolicy`, frozen index session/deadlines, between-cycle SCOPE observations,
context reproduction and explicit unsupported-consumer behavior. Application code
is unchanged from `8f407f2`; this commit adds acceptance tests and documentation.

`test_option_scope_tape_boundaries.py` adds **52 cases** covering every nested
source/receipt-clock boundary, rejected-write atomicity, nested Greek availability,
combined quote capacity, the original shared-Swing header and complete legacy tape
digests, every account consumer with both populated and empty enrolled Scope tapes,
and continued rejection of the old C/D model adapter. Golden hashes were captured
independently from the original installed `33106efa` wheel. Account consumers cannot
create/open owner state or report complete Scope economics through the legacy path.

Final consolidated verification: **145 distinct installed cases passed** (30.92s),
including all 43 published Scope tape cases, the 52 added boundary cases, the legacy
market-tape suite and the installed replay CLI permission/create-only case. There
were no failures, errors or skips. Tests used an isolated noneditable wheel, copied
tests outside the checkout, Python `-I`, disabled ambient plugins, warnings as errors
and a new retained pytest base directory. All **194 application/template files**
match the published `8f407f2` source, local source, wheel and installed package.
Lint/format, dependency consistency, whitespace and local documentation targets pass.
Final wheel SHA-256:
`673bc7d8881dd3fc442db3c66493bd4c0f73cf734e70e30fc94e144214676c9b`.

The superseded local prototype separately passed 280 distinct installed cases,
including a focused rerun of one CLI permission-invocation timeout. Those results
and the prior entry's 198 cases are **not added** to this final 145-case count.
The prototype's incompatible tape schema was not published. Its source/tree and
proof remain retained separately for audit; this follow-up preserves the remote
contract rather than adding a competing implementation.

Final proof: `/workspace/scratch/c2a4a0346b96/scope-tape-merged-proof`, with copied
tests, installed JUnit/log, fixture state, build/install logs and per-case/file
`validation-summary.json`; wheel in the adjacent `scope-tape-merged-wheels`.
Original prototype proof remains beside `/workspace/scratch/a622c2254d81/Trade-Bot`
under the `scope-tape-*proof` directories. No dependency, authenticated provider/
model/broker call, host change or deployment occurred. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 open/draft, LIVE disabled and the
deployed experiment frozen. Next remains independent Scope watch lifecycle and
A/B/C/D model/replay/export binding, then continuous watch/runtime inputs.

## Common Scope observation tapes and explicit replay boundary: 2026-10-20 UTC

Fresh GitHub and the retained checkout matched
`33106efa6a064d1c8b0415a5f888752759e70155`, tree
`8a8cf63f28050bf0d21e6cfe0845ec76b575f4e5`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.
The retained checkout was initially clean. A concurrent writer subsequently changed
those same files, so this slice moved to an isolated checkout at
`/workspace/scratch/375f7ed7f8ff/Trade-Bot`, preserving the other working tree.

The old installed wheel reproduced the concrete boundary failure: both CYCLE and
MARKET accepted nested Scope evidence without any Scope header enrollment.
[Common Scope observations](OPTIONS_SCOPE_MARKET_TAPE.md) now explicitly freeze the
watch/source policy and reviewed session, including original cutoff/protection
clocks. Recording and loading reject unenrolled Scope, future/foreign/duplicate
evidence, unfinished histories, wrong SPXW identity, changed session/deadlines and
conflicting common/nested prices. Existing header/frame serialization and the old
header hash remain unchanged when enrollment is absent.

A distinct Scope-only observation event retains between-cycle inputs without
creating extra decision slots. Quote-only MARKET remains separate. Original-time
context reproduction exposes only recorded prefixes and returns native scanner
diagnostics with exact input/policy/event/tape bindings and no authority. Missing,
stale or blocked source evidence remains explicit. Source capture never consumes
an account revision, copies an admission or asserts a fill. A multi-session input
series must retain the same Scope watch policy and enrollment.

Independent Scope A/B/C/D native replay/export remains open. Legacy shortlist,
replay and export now explicitly reject Scope enrollment; replay refuses before
creating accounts/output, and recorded evaluation suppresses totals with
SCOPE_TAPE_COMPARISON_NOT_SUPPORTED. The old Scope AI replay-model restriction was
not removed. No model/native approval/position logic or cost policy changed.
Next: bind separate native watch lifecycles and model-role contracts to these
common observations, preserve original deadlines and fresh post-cost admission,
then extend later-fill/management/full-cost export and continuous runtime inputs.
Combined carry, remaining families/mixed ownership and final UI/authentic-data
acceptance remain later gates.

Validation: **198 distinct installed cases passed**, including all **43 new
Scope tape cases**, with no skipped cases or unresolved failures. The final run completed in 1180.88 seconds and
used an isolated noneditable wheel, copied tests outside the checkout, Python `-I`,
disabled ambient plugins and warnings as errors. It includes common tape integrity,
independent/shared A/B/C/D replay, multi-session settlement and cost continuity,
native export, management attribution and unknown-cost regressions.

The initial focused run passed 42 of 43 cases. Its one failure was a test-only
comparison between native canonical hashing and JSON-string values. The corrected
assertion pins the exact header digest independently reproduced on the previous
installed wheel. All 43 cases passed in the final run; overlapping runs are not
summed. No application gate was relaxed to fix that expectation.

All 194 application/template files match source/wheel/install. Copied tests match
source. Lint, format, dependency consistency, whitespace and 233 local documentation
links pass. Wheel SHA-256:
`5deb96e7322752dce5269a95ad8ba373f34d90178f2713d510ced7990e322568`.
Proof beside the isolated checkout: `scope-tape-proof` (initial run and old-wheel
reproducer), `scope-tape-final-proof` (final installed run, JUnit/log, fixture state,
identity and distinct-case summary), `scope-tape-dist` and build/install logs.

README, source of truth v1.84, research continuation and tape/replay/testing guides
record the delivered boundary. Main remains untouched, PR draft, LIVE disabled and
the deployed experiment frozen. No dependency, deployment, host configuration or
authenticated provider/model/broker call changed.

## Shared Scope position reasoning: 2026-10-19 UTC

Fresh GitHub/local state matched `42e1711d1d300a0d50d076920278883c506f758e`,
tree `6c02ac4256f3c9ce1ea190122e28243b5fa59cb9`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

[Shared Scope position reasoning](OPTIONS_SCOPE_POSITION.md) now explicitly enrolls
`scope-fixed-position-v1` with the existing shared entry AI owner. It uses one
bounded management worker and native account across Scope, Degen and session-close
Swing. Original policies serialize unchanged when the new setting is absent;
existing cohorts cannot acquire management on reopen. Scope/carry remains rejected.

A held Scope packet verifies the original native entry and paid selection, retains
the AI thesis/uncertainty and fixed native targets/profile/deadline, and recomputes
current SPX/SPY/QQQ context through the frozen Scope policy. It requires the exact
consumed play and held contract; unavailable/stale/foreign context starts no call.
New observations are management evidence, not permission to replace the setup.

MAINTAIN, tighter invalidation and full exits use the existing atomic revision
consumption, native dispatch and restart path. Target scales and mandatory stops,
premium/time exits remain independently authoritative. Known entry and management
charges remain in trade outcomes and native portable accounting; unknown usage
still fences the account. Management after a partial close uses the remaining
owned quantity without resetting original terms or losing prior fees/costs.
Stored attribution rechecks the exact native entry and complete original paid
selection, including after closure. Independent research accounts remain separate.

Validation: **330 distinct installed cases passed**, with no unresolved failures
in the normalized case ledger. The broad run passed 326 of 328 cases (805.71s),
including native management, entry/Scope arbitration, lineage/outcomes, observer
and independent A/B/C/D accounting replay. Its two failures were new fixture errors:
a coverage-only payload was mutated instead of the recomputed technical payload,
and the restart test attempted a second owner on an already attached engine.
Both fixtures were corrected without changing those engine boundaries.

The final wheel passed **175 distinct installed cases**, including all **18 new
Scope/shared-family management cases**. Its main run passed 172 of 173 (363.55s);
the corrected actual-restart/worker/tamper case then passed (20.86s), and both
Degen/Swing management cases under the shared Scope owner passed (13.98s).
The final-wheel case ledger has no unresolved failures. Earlier partial-close
fixtures were corrected to reconcile and supervise at their new clock before
requesting a scale; both focused scale cases passed. The mocked child fixture now
includes both copied-test import roots, matching the existing worker harness.
No freshness, one-owner, process, usage or risk gate was relaxed.

Coverage includes CALL/PUT MAINTAIN/TIGHTEN/EXIT_ALL, paid entry plus management
costs through full closure and portable export, management after a partial close,
missing/stale/foreign context, bound technical payloads, late/lost usage,
mandatory stop precedence, frozen enrollment, exact original terms and paid thesis,
real installed worker execution with mocked SDK transport, reopening and tampering.
All runs used isolated noneditable wheels, copied tests outside the checkout,
Python `-I`, disabled ambient plugins, warnings as errors and retained distinct
pytest base directories. No actual provider traffic was used.

All **193 application/template files** match final source/wheel/install. The final
wheel differs from the broad wheel only in the three directly retested position
contract/prompt/context modules. Lint, formatting, dependency consistency, whitespace
and local documentation targets pass. Final wheel SHA-256:
`89f5102c09b319606b6df99f6ba2dd8b383d20a397ba1936e8a58cd90ad2ad13`.
Retained proof beside checkout: `scope-position-proof`, `scope-position-release-proof`,
`scope-position-worker-final-proof`, `scope-position-family-proof`, the intermediate
`scope-position-final-proof`, scale/worker proofs, XML/logs and fixture directories.
Final `identity.json`, `final-wheel-validation.json` and `validation-summary.json`
retain file identity and per-case resolution. Build/install logs and wheels are
retained alongside these proofs.

README, source of truth v1.83, research continuation and Scope/position/testing
guides now record the contract. No actual provider/model/broker request, deployment,
host or dependency change occurred. Main remains untouched, PR #1 draft, LIVE
disabled and the deployed experiment frozen.

Next: common A/B/C/D Scope tapes/replay and continuous watch runtime input,
combined Scope/carry enrollment and remaining family/mixed ownership plumbing.
Final UI/visual and authentic-data/model acceptance remain open.

## Shared Scope entry AI and native cost attribution: 2026-10-19 UTC

Fresh GitHub/local state matched `fe0fe44c333138c813bf3a1a1276533af749873d`,
tree `013358b77d88b3f8f8d765cc0af2338d191444e7`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

New [shared Scope entry AI](OPTIONS_SCOPE_AI.md) connects one paid Degen/Swing/Scope
entry decision to the native owner. Explicit `shared-scope-entry-v1` enrollment
freezes the model prompt/schema, rates/bounds, entry policy, family set and complete
Scope watch policy in a new healthy, untraded account. Existing deterministic and
Degen/Swing AI configurations remain unchanged. Scope can be the only admitted
family; it counts toward pre-call family loss admission only after its original
stored admission is verified. Family/account locks and unknown costs still gate calls.

Degen/Swing retain full underlying entry reasoning. Scope selects its exact fixed
plan by supplied digest; the model cannot replace its contract, quantity, stop,
targets, profile or protection deadline. HOLD remains a paid final outcome. Full
requests, results, alternatives and known/unknown usage are retained. A Scope choice
requires genuinely newer observations and a new owned admission after settlement.
The fresh-input reader is bounded by the original remaining lease. Rejection never
falls through to another candidate or retries the paid opportunity.

The original/fresh Scope actions and the complete paid decision are independently
rechecked at native preparation. Decision, order, shared selection and watch
consumption commit atomically. Scope approval expires at the earliest original
Scope, fresh Scope or shared model packet deadline. Clock movement between family
scans and Scope admission is supported without admitting future evidence. Restart,
dispatch and stored attribution verify the original bindings and settled charge.

Paid cycles now link explicitly to native Scope buys and their scales/final exits.
Full-cost closed outcomes count the entry charge once, preserve all other recorded
entry/management costs and actual fees, and feed native account/family loss controls.
Partial exits are not closed losses. Portable shared native export reconstructs
these links; unknown costs, incomplete exposure and missing operating allocations
still suppress net results. Stored observer reads follow the paid cycle and fresh
Scope quote without making a model/provider call. Independent owners share no cash,
reservations, model receipts or loss counters.

Validation: **399 distinct installed cases passed**, deduplicating the broad and
focused runs. The broad run passed 385 of 386 cases (498.60s), exposing the missing
Scope-only candidate in the pre-call family loss guard. After correcting that
boundary, all 83 installed family/model/shared-entry cases passed (266.85s).
The final wheel passed all **139 installed cases** (156.64s), including all **35 new
shared Scope AI cases**, the strict entry contract/worker, model loss admission and
native Scope execution boundaries. No failed gate was waived; the normalized case
ledger has no unresolved failures.

The final timing checks also cover a stalled fresh-input reader, a shorter shared
model-packet deadline and clock progress between family scans and Scope admission.
Fixture-only setup errors during those checks were corrected without relaxing source
history, arming or freshness gates. Two code fixes from review bound the reader and
native expiry, while the packet now permits valid later Scope admission timestamps.
The observer's paid-entry lookup was corrected before the broad installed run.

All runs used isolated noneditable wheels, copied tests outside the checkout,
Python `-I`, disabled ambient plugins, warnings as errors and distinct retained
pytest base directories. All **192 application/template files** match final
source/wheel/install. The final wheel differs from the intermediate wheel only in
five directly covered entry/Scope modules; the intermediate wheel additionally fixes
`loss_control.py`. Scoped lint/format, dependency consistency, whitespace and local
documentation targets pass. Final wheel SHA-256:
`40e607116642e180b53441b3e9ff67a8434fb210119cff4d12fcc68d004cb62b`.
Retained proof beside checkout: `scope-ai-proof`, `scope-ai-release-proof`,
`scope-ai-final-proof`, their XML/logs/fixture directories, final `identity.json`,
`validation-summary.json`, and the corresponding wheel/build/install logs.

README, source of truth v1.82, research continuation and Scope/entry/testing guides
now record this boundary and its explicit enrollment. No actual provider/model/broker
request, host/deployment or dependency change occurred. Main remains untouched,
PR #1 draft, LIVE disabled and the deployed experiment frozen.

Next: shared Scope position reasoning and common A/B/C/D replay, continuous watch
input/runtime integration, combined Scope/carry enrollment and the remaining
family/mixed ownership plumbing. Final UI/visual and authentic-data/model acceptance
remain open. Shared entry AI does not enable a position model or migrate any cohort.


## Post-cost Scope reapproval prerequisite: 2026-10-19 UTC

Fresh GitHub/local state matched `4dbf19a589dccf36c82b1b71e10eccadb6cb6134`,
tree `5375596eb5c2653ed61244990f5dce1bdc0e399a`. PR #1 was open/draft and main
remained `b5359aaf396e692d2142d7e02908f1544e045ee6`.

The new [post-cost Scope review](OPTIONS_SCOPE_POST_COST.md) closes the read-only
comparison boundary needed before a shared paid decision can receive fresh native
approval. It verifies the original immutable watch action, an intervening settled
model attempt/usage receipt, and the latest exact-revision owned admission. It
requires newer observations rather than replayed source clocks. Trading terms,
quantity, fee-inclusive ceilings and original expiry cannot expand after the call.
Current account evidence must reflect all recorded costs, including management;
unknown costs and foreign-owner receipts remain blocking.

The diagnostic retains both packet hashes/bindings, original and fresh native
source identities, the paid source/usage/cost and bounded deadline. It writes
nothing and grants no order authority. The deterministic shared coordinator still
rejects model settings. This is a prerequisite, not completed shared Scope AI:
full request/result binding, atomic consumption and explicit model-cycle-to-native-
trade attribution remain next. Do not enable model enrollment merely because this
review passes, use a refreshed admission's longer lease, or silently replace the
selected plan when costs reduce its admissible quantity.

Validation: **86 installed cases passed** in 158.85s, including all 33 new
post-cost review cases and shared selection/history, owned admission and native
execution-boundary regressions. The run used an isolated noneditable wheel,
copied tests outside the checkout, Python `-I`, disabled ambient plugins and
warnings as errors. All **190 application/template files** match source, wheel
and installation. Scoped lint/format, dependency consistency, whitespace and
local documentation targets pass. No test failure was waived.

Wheel SHA-256:
`b517791f5c592cec657d3ada65873ffc2250ad40965ce1ce286376460adc1a90`.
Retained proof beside checkout: `scope-postcost-proof/installed.xml`,
`installed.log`, `identity.json`, `retained-tmp`, and the separate wheel/build/install
logs. The initial source checks exposed fixture mistakes (repeated source clocks
and equivalent timestamp string encodings); both were corrected before the clean
installed run. No native revision/freshness gate was relaxed.

README, source of truth v1.81, shared Scope/entry reasoning and the research
continuation now distinguish this completed prerequisite from remaining integration.
Main stays untouched, PR #1 stays draft, LIVE stays disabled and the deployed
experiment stays frozen. No authentic model/provider/broker request, deployment,
host or dependency change occurred.

Next: connect this boundary to the full shared AI request/result, native preparation
and stored entry/scale/final-exit cost attribution. Continuous Scope watch ingestion,
common A/B/C/D tapes, combined carry/Scope enrollment and broader/mixed ownership
remain subsequent plumbing; final visual and authentic-data acceptance remain open.


## Deterministic shared Scope selection: 2026-10-19 UTC

Fresh GitHub/local state began at `fa7843924d2dc1f8bc4cc09cdfecfff46857bded`, tree
`714b4104304d8dbc02ab90bfaa5119482584d1ca`. Scope native execution/loss and separate
bounded Swing carry were already fixture integrated. This slice closes the next
deterministic shared-selection boundary. [Enrollment, APIs and remaining work](OPTIONS_SCOPE_ARBITRATION.md).

New `shared-scope-selection-v1` owners select among Scope, Degen and optional
session-close Swing in one coordinator, five-minute claim, cash ledger, reservation
and native loss-control boundary. The full Scope watch policy and explicit family
priority are frozen with the coordinator. Every enabled family needs its loss policy.
The shared v1 rejects paid entry/management model settings and scripted model replay;
old Degen/Swing AI populations and standalone Scope owners remain unchanged.

Fresh Scope admission follows reconciliation and other cycle events. Exact active
watch coverage is mandatory. Original candidates and selection are retained with
policy/packet hashes and native source identities. Native preparation rejects bypass
requests; order, decision, selection event and Scope consumption commit together.
Dispatch and attribution recheck the original selection. Rejection stops that cycle
without trying a second candidate. Scope targets, quantity/price ceilings, fees,
profile protection and deadlines remain exact; held/native partial-exit protection
stays independent. No SPY fallback, invented T3, changed convexity rule or fill is added.

Stored attribution carries the selection into entry, scale and final-sale records.
The observer exposes shared Scope candidates and held quote evidence. Portable
`shared-scope-native-export-v1` reconstructs the entire account and every enrolled
family from fixed typed native tables. Unselected Scope alternatives remain bound
to their original action after later watch mutations. Every entry/management charge
and fee remains counted; unknown cost, incomplete outcomes, open exposure or absent
operating allocations suppress net results. Independent owners do not share costs,
reservations or loss counters.

Validation: **384 distinct installed cases passed**, deduplicating overlapping
reruns. The broad 381-case run exposed three earlier integration gaps: a Scope
family label could parse with a Degen/Swing source, and two legacy family-risk
cases incorrectly needed carry scan evidence without strategy enrollment. The
Scope source namespace is now validated. Carry checks preserve unenrolled legacy
behavior while rejecting missing strategy records for carry-enrolled owners.
No failed gate was waived: 134 Scope/lineage/observer cases passed after the first
correction (291.55s), and 64 family-loss/carry/shared/history cases passed on the
release wheel after the second (159.79s). The earlier broad run's other 378 cases
and the separate two-case historical-alternative proof also passed. There are no
unresolved failures in the normalized case ledger.

All runs used isolated Python, noneditable wheels, copied tests outside the checkout,
disabled ambient plugins and warnings as errors. Fixture directories are explicitly
retained. All **189 application/template files** match final source/wheel/install.
Only `lifecycle.py` and `swing_execution.py` differ from the broad-test wheel; both
corrections were covered by the passing focused reruns. Scoped lint/format,
dependency consistency, whitespace and local documentation targets pass.
Release wheel SHA-256:
`6a544bc6125512dbd616d472a6b0b36364ee7c9f151bc930c1f7766ea5ed3850`.
Retained proof beside checkout: `shared-scope-proof/{installed,history,final,release}.xml`,
corresponding logs, `validation-summary.json`, `release-identity.json`, and the
release wheel/build/install logs.

README, source of truth v1.80, research/continuation and testing guides now record
this boundary. Main remains `b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays
open/draft, LIVE stays disabled and the deployed experiment stays frozen. No actual
provider/model/broker calls, host/deployment changes or dependency changes occurred.

Next: shared Scope paid AI, continuous watch ingestion and common A/B/C/D tapes;
combined carry/Scope enrollment, broader families and mixed stock/options remain
open. The final UI/visual and authentic data/model acceptance passes still follow
this plumbing. Do not reopen the settled Scope management/loss decisions.

## Native bounded Swing carry: 2026-10-19 UTC

Fresh GitHub/local state began at `fb6da02fb27d344c2f63e52dcb7145b87dad932f`, tree
`f4377fabd74a049269bc64240f39713373f2a0d1`. Scope's supported native execution/loss
integration was already closed. This slice connects the next open Swing holding
path through native execution, held reasoning and full-period cash accounting.
[Enrollment, behavior, reproduction and remaining gates](OPTIONS_SWING_EXECUTION.md).

A new explicitly frozen `BOUNDED_CARRY_V1` strategy requires original-target v3
lifecycle, an original seed exit session, explicit session/calendar/expiry bounds,
full-horizon catalyst clearance, matching native carry enrollment and Swing family
loss control. Original seed/policy hashes, actual sessions, T1 and the final deadline
are retained in decisions, approvals, intents and fills. Native preparation,
dispatch, reconciliation, restart and stored attribution verify those bindings.
The preflight report remains order-free and cannot enable or migrate an owner.

Entry approval remains short lived and the entry order remains DAY. Partial fills
keep the original position deadline; the remainder needs observed terminal evidence.
Original stop, premium protection, T1 and fixed deadline stay independent of model
availability. This explicit local adaptation exits the whole holding at original
T1, with no invented partial ladder. Missing overnight/reopening quotes stay unknown;
a fixed deadline can latch without quotes, while submission/fills require executable
evidence. There is no assumed stop fill, automatic calendar roll or exercise funding.

Carry entry reasoning has a separately hashed schema/prompt and explicit maximum
horizon. Only supplied carry terms authorize the longer envelope; Degen remains
intraday. Models cannot extend T1/deadline or end their horizon in a closed session.
Held packets retain the original daily Swing setup alongside fresh intraday context
and explicit non-continuous overnight coverage. MAINTAIN/TIGHTEN/EXIT_ALL retain
original position identity, costs, proposal/review/application and fill attribution.
Legacy model configuration hashes remain byte-for-byte unchanged.

Native full-cost loss accounting refreshes across rollover and counts a closed entry
once with all attributable entry/management charges and execution fees. Independent
A/B/C/D replay keeps the same account ledgers across sessions. Detached accounting
resolves later exits and management to prior-session entries. Daily open boundaries
remain unvalued/inconclusive. Separate `carry_accounting` gives flat-ended whole-period
cash arithmetic only with verified complete evidence and every model/data/host cost;
unknown cost or open final exposure suppresses net results. There is no comparison
against the existing gap-excluding SPY session compound or profitability claim.

Validation: **507 distinct installed cases passed**, without adding overlapping reruns.
The core run passed 254 cases in 230.78s; model protocol/held reasoning passed 196 in
11.83s; the complete two-session carry/native run passed 21 in 704.40s. After the
final stored-observer label/terms correction, all 71 native-carry/observer cases
passed in 27.62s on the final wheel. Trading/model/accounting files are byte-identical
between those wheels; only `app/options/observer.py` changed for that final run.
Isolated Python used noneditable wheels, copied tests outside the checkout,
disabled ambient pytest plugins and warnings as errors. No failed gate was waived.

Coverage includes CALL/PUT, DAY partial remainders, restart without quotes, fixed
deadline/original-T1 exits, carry schema through the SDK stub, closed-session and
extended-target rejection, MAINTAIN/TIGHTEN/EXIT_ALL, both paid charges, exactly-once
loss consumption, tamper rejection and unchanged legacy hashes. Full Friday/Monday
A/B/C/D replay exports eight boundaries and independently reconstructs every cost;
unknown model/allocation costs and open final exposure suppress period net results.
The initial development tape omitted mandatory seed coverage and correctly halted;
its coverage was fixed before the passing installed replay, without relaxing a guard.

All **188 application/template files** match final source/wheel/install. Scoped
lint/format, dependency consistency, whitespace and local documentation targets pass.
Final wheel SHA-256:
`865a8d8c94b348912afdd2f8ac1f875ef72997ce21e4c91809b9f1221a9dbb50`.
Retained proof beside checkout: `native-carry-proof/{core,protocol,carry,observer-final}.xml`,
`native-carry-proof-*.log`, `native-carry-final-dist` and build/install logs.

README, source of truth v1.79 and continuation/testing documents describe the new
boundary. Main remains `b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 remains open
and draft, LIVE remains disabled and the deployed experiment remains frozen.
No authentic provider/model/broker calls, deployment, host or dependency changes.

Next P7 work remains broader families, shared arbitration including Scope and mixed
stock/options ownership, followed by the requested final UI/visual and authentic
data/model testing passes. Native carry fixture integration does not grant those
acceptances or reopen settled Scope decisions.

## Overnight Swing evidence contract: 2026-10-19 UTC

Scope native execution/loss integration was already closed at the fresh GitHub
checkpoint `59c842c1da8289f6266ba8bfe5e860807564b338`, tree
`061aa0e25f68f9e0d59852dcb7f71b24daad944d`. This slice advances the next open plumbing
area: overnight Swing. The concrete missing dependency was a reproducible contract
for actual carry sessions, expiry buffers and catalyst coverage beyond today's close.
[API, complete fixture, installed CLI and remaining integration](OPTIONS_SWING_CARRY.md).

`SwingCarryRequest` now freezes explicit research limits and supplied original/current
evidence. Review recomputes completed Swing structure, original first-target/terminal
lifecycle, exact contract selection, current directional break/chase and the existing
account governor. It enumerates actual XNYS sessions across weekends, holidays, DST
and early closes. The requested final session must satisfy both calendar-day and
exchange-session bounds, the configured before-close deadline, a whole-session expiry
buffer and the exact earlier contract cutoff. It never rolls an invalid exit date,
substitutes a contract or silently shortens the requested horizon.

Catalyst clearance must be fresh, complete, REALTIME, exact-source/symbol CLEAR and
cover the entire proposed deadline. Missing or today's-only coverage blocks. Current
admission retains the short entry-session approval; no future date widens it. Sizing
uses the native per-contract exit-order fee reserve, every execution fee and adverse
slippage, with supplied independent-account available loss budgets. Unknown cost
budgets remain blocked. Preflight does not generate model bills, future costs or P&L;
all actual entry/management charges must already be included in supplied account truth.
It proves neither native ownership nor unseen prices/provider authenticity.

Portable export retains all typed inputs and the complete review. Verification
requires an independently retained request hash and independently reproduces calendar,
setup, contract, admission and every output field. The create-only installed CLI
bounds input size, rejects duplicate JSON fields and never overwrites a report.
A complete synthetic request is committed; it needs no credentials or broker setup.

Every report, including READY evidence, has `authority=false` and the explicit
`SWING_OVERNIGHT_EXECUTION_NOT_ENROLLED` blocker. Existing native Swing remains
`SESSION_CLOSE`. The regression proves that a positive carry report neither mutates
an owner nor changes its same-day order/position deadlines. No frozen cohort migrates.
The pinned SignalFlow promotion and contract-selection sources were reread at
`f9eaf2c1b5d13dca287ee7138126883065b00395`; this new research contract does not claim
an overnight execution policy from those sources.

Validation: **382 installed cases passed in 493.97s**, including **58 new carry
preflight cases**. The run used isolated Python, a noneditable wheel, copied tests
outside the checkout, disabled ambient pytest plugins and warnings as errors.
Coverage includes CALL/PUT, weekends/holidays/DST/early closes, exact horizon and
expiry boundaries, insufficient/stale catalyst evidence, missing quotes, exact
contract/seed identity, terminal observations, low/unknown budgets, per-contract
exit fees, changed portable data and installed CLI create-only/verification errors.
Existing shared-owner, completed/quote/target lifecycle and admission suites pass,
including all three native A/B/C/D lifecycle variants with independent accounts and
every entry/management charge. No failed gate was waived. The earlier source run
passed 57 cases with only the installed CLI case deliberately deferred to the
installed run; overlapping results are not added.

All **186 application/template files** match source/wheel/install, and all six
selected copied test files match source. Scoped lint/format, dependency consistency,
whitespace and local documentation targets pass. The committed synthetic example
was reviewed and verified separately through the installed CLI. Final wheel SHA-256:
`a3426229fe8823d85fda2218a10085c65abdfcfa9c807d1b5f334a7aadc8f2a0`.
Proof beside checkout: `swing-carry-proof/installed.xml`, `swing-carry-installed.log`,
`swing-carry-dist`, `swing-carry-verification.json` and source/build/install logs.

README, source of truth v1.78, testing and continuation documents now describe this
boundary. Stale P7/source-of-truth claims that Scope execution/family loss linkage
were still unimplemented were corrected to match the prior delivered commit.

Next: bind an explicit native Swing carry policy to entry decisions/fills and retained
protection, then session rollover/restart, carry-aware held model context and independent
multi-session full-cost replay/export. Broader families, shared arbitration including
Scope, mixed stock/options ownership, final UI and authentic data/model/calendar,
host and prospective economic acceptance remain open. Scope convexity and missing-T3
four-contract plans retain their explicit rejection boundaries. Main untouched, PR #1
draft, LIVE disabled and deployment frozen; no authentic broker/provider/model call,
service change or dependency update.

---

## Scope native execution and loss-control integration closed: 2026-10-19 UTC

The requested integration is closed for explicitly enrolled `scope-native-v1`
PAPER owners: original called watch → current armed admission → native decision/
order → actual fills and target/time management → full-cost outcome → SCOPE
cooldown/lock → signed reviewed reset. This is bounded offline implementation
acceptance, not authentic provider, prospective economic, host or visual acceptance.
[Enrollment, API, source boundary and testing](OPTIONS_SCOPE_EXECUTION.md).

Fresh GitHub baseline was `402ec6c8743551c2aee7ef7015467593dccb2ede`, tree
`25b9eb6bca72473f89cb6caf80b58295f7525935`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft. The baseline was
checked again before publication preparation.

New native owner/watch enrollments require existing v2 target milestones, actual
fill references, tighter profile premium/deadline protection, exact entry binding,
quote/arming/admission gates, direction resets and SCOPE family loss rules. Existing
research cohorts remain order-free and cannot migrate. Generic native entry cannot
bypass the Scope consumer. Inside one transaction, preparation rechecks original
and latest receipts, owner, revision, account/risk, exact proposal and management
terms, then saves native decision/order, consumption receipt and watch transition.
A rejected stale preparation does not burn the watch: a fresh admission has a new
source identity. A consumed play can never create another native entry.

Dispatch rechecks current quote/profile/price tier, coverage age, known path,
remaining R, original admission lifetime and the current common governor/loss guard.
Lineage derives from the consumed original receipt and survives closes, stored
attribution, reconciliation and exports. Native lifecycle distinguishes working
orders, actual held positions, closed trades and terminal never-filled attempts.
Partial buys/canceled remainders keep their position; scales keep their runner,
original fill basis, profile limit and earlier deadline. Uncertain/attempted orders
retain reservations and existing reviewed-recovery requirements. Calls still count
when never filled. Neutral reset, fresh reversal bars and cooldown remain necessary
for an opposing call; resets never refund calls or reopen plays.

The pinned approved SignalFlow V2 playbook at
`f9eaf2c1b5d13dca287ee7138126883065b00395` was reread. Its unobstructed-path condition
is specific to cheap convexity consideration. Earlier continuation notes overstated
that as a prerequisite for every profile; the new native version follows the pinned
rule. Responsive/balanced one-to-three-contract plans execute with existing known-
level, reachability and remaining-R gates. Convexity remains blocked, and four-
contract plans retain `SCOPE_THIRD_TARGET_UNSPECIFIED`; no objective, resize, extra
runner or complete-path claim is invented.

Reconciliation feeds actual native outcomes into both account and SCOPE loss state.
All entry/management charges and execution fees remain included; unknown/unallocated
costs or open runners cannot become completed losses. Completed outcomes count once,
cooldown starts at recognition, and locks persist across sessions/restart. Signed
Scope resets require an actual lock, expired cooldown, exact revision and fresh flat
complete evidence. Actor/reason/time/session/prior state remain audited. Only Scope's
operational boundary clears; global locks, daily P&L, costs and independent accounts
remain intact.

Create-only native replay now drives watch actions, entries, actual fills, owned/
protective exits, observed terminal/settlement receipts and signed fixture resets.
Protective orders can be filled by their replay action key. Portable export verifies
original native links, cash/fill/settlement accounting, risk/reset evidence and all
costs in an in-memory reconstruction. It also checks open holdings' original deadline,
protection and fill reference. Data/host costs default to unknown. The stored observer
labels native PAPER plays and exact entry links; reads remain non-mutating. This is
semantic integration, not final visual acceptance.

Validation covers **1,117 distinct installed cases with no unresolved failures**,
including **40 new native Scope/replay cases**. All runs use isolated Python,
noneditable wheels, copied tests outside the checkout and warnings as errors:

- Broad run: 1,114 cases in 655.76s, with 1,111 passing and three fixture/harness
  failures. It includes all existing Scope suites, native execution, family/account
  loss/reset/operator controls, partial closes, deadlines/targets and full independent
  A/B/C/D entry/management-cost attribution.
- Final Scope/native-observer run: 59 passed in 183.67s, including original holding
  protection checks, orphaned native receipt rejection and corrected observer fixture.
- Final replay/export run: 12 passed in 87.51s after adding action-key linkage for
  protective fills; this was the only application change after the 59-case run.
- Corrected compatibility run: 5 passed in 4.14s. SCOPE is now a supported loss family,
  so the old invalid-family fixture now uses UNKNOWN. The isolated harness now includes
  its copied test-package root for an existing qualified helper import.

The other broad-run failure was a too-short password in the new observer fixture;
its corrected case passed independently and in the final 59-case run. The underlying
minimum-password rule was retained. Earlier development runs also caught the new
export's duplicated-capital consistency omission, a Decimal/string comparison and
incorrect fixture assumptions/field names; all were corrected before relevant final
installed gates. No failed application gate was waived, no dependency was changed,
and overlapping runs are not added together. JUnit identity union records 1,117 cases.

All **185 application/template files** match final source/wheel/install; final selected
copied tests match source. Scoped lint/format, dependency consistency, whitespace and
local documentation targets pass. Final wheel SHA-256:
`e8042258cedf1c11f1090963620a0c495b42f76d5a62cedd8b768db2bd60520d`.
Proof beside checkout: `scope-native-proof`, `scope-ready-proof`,
`scope-delivery-proof`, `scope-compat-fixed-proof`, their installed logs/JUnit files,
`scope-delivery-dist` and `scope-verification.json`. Historical development proofs
are retained separately.

Remaining broader work: overnight Swing, remaining families/mixed stock-options
ownership, final UI/visual review and authentic normalized data/model/calendar,
prospective economic and host acceptance. Unsupported convexity/four-contract cases
remain explicit Scope rejection boundaries. Main untouched, PR draft, LIVE disabled
and the deployed experiment frozen; no authentic broker/provider/model call,
service/deployment change or dependency update.

---

## Deterministic entry deadlines and Scope handoff: 2026-10-18 UTC

A concrete native Scope prerequisite is now implemented: deterministic entries can
freeze an earlier exit deadline without borrowing an AI plan/target. The pinned
SignalFlow approved V2 playbook at `f9eaf2c1b5d13dca287ee7138126883065b00395`
was reread: remaining Scope modeled positions must exit by 15:45 ET. The previous
native deterministic API could apply only owner session/expiry time, which cannot
represent an earlier strategy deadline when the owner's cutoff is later.

New frozen PAPER owners can enroll `entry_time_protection="tighten-only-v1"` and
bind `EntryTimeProtection` to trusted deterministic buys. The effective deadline
is the earliest of the entry's request, owner session cutoff and exact expiry guard.
Approval and buy-order lifetime cannot outlive it. Original decision, approval,
intent and filled position retain the terms through partial buys, scales, runners,
restart, stored attribution and portable economic reconstruction. Native dispatch
and reconciliation recheck the original decision and stricter owner ceilings.

With fresh reconciled account evidence, the existing `TIME_EXIT` latches at the
deadline even without usable market quotes; later usable evidence can execute the
owned close. Entry expiry does not prevent protective sales. Unattempted scales
can be preempted, while attempted orders retain reservations and failed/canceled
attempted exits retain their reviewed-recovery requirement. No cancellation, fill,
fee or entry/management charge is invented or omitted. Unknown costs stay unknown.

Scope's bound selection now derives the deadline from original locked session
`protect_at`. An enrolled time policy and exact handoff cannot bypass the existing
Scope native entry guard. This closes the native time-protection dependency, not
Scope order/fill or family-loss enrollment. Complete path requirements, missing
four-contract T3 and Scope runtime acceptance remain open.
[API and boundaries](OPTIONS_ENTRY_TIME_PROTECTION.md).

Fresh GitHub baseline: `cc69c84643a1bfd9e1f9cf0a9ca3088fc012cf95`, tree
`b5920d8ce15013795348bc2ab4140a808b2168b0`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation: **237 installed cases passed in 260.57s**, covering native deadline
behavior, Scope binding, premium protection, execution/reconciliation, target export,
partial closes with known/unknown entry-management costs, fill-bound stops, Scope
entry guards and full-session independent A/B/C/D accounting. One additional,
disjoint installed Scope handoff/owner-enrollment guard case passed in 3.54s.
Together these include 26 new deadline cases. Both runs used isolated Python,
a noneditable wheel and copied tests outside the checkout, with warnings as errors.

The first installed focused run had 52 passing cases and four fixture assertion
failures: three omitted required fresh account reconciliation at the deadline,
and one incorrectly expected an automatic retry after a canceled attempted exit.
The fixtures were corrected to retain those existing controls; no production fix
or waived gate was needed. The final tests also cover earlier owner/expiry ceilings,
atomic rollback, independent deadlines and rejection of changed portable ownership.

All 182 application/template files match source/wheel/install, and final copied
tests match source. Scoped lint/format, dependency consistency, whitespace and
67 distinct local documentation targets pass. Wheel SHA-256:
`621b534083105d10806b077004f29d2b7e6a12848380a28c1fc9dd362c5985fb`.
Proof beside checkout: `entry-time-focused.log`, `entry-time-installed.log`,
`entry-time-scope-boundary.log`, `entry-time-proof`, `entry-time-dist` and build/install logs.

Scope execution/loss integration, complete path requirements, four-contract T3,
overnight Swing and mixed ownership remain open. UI and authentic provider/model/
data/host/economic acceptance remain final passes. Main untouched, PR draft, LIVE
disabled and deployment frozen; no authentic broker/provider/model call, dependency
update or host/deployment change.

---

## Scope watch-to-entry evidence binding: 2026-10-18 UTC

The next native Scope dependency is now fixture implemented: new frozen
`scope-entry-binding-v1` research cohorts bind the original called watch to the
exact latest owned admission and management v2 receipt. The binding includes
population/account, frozen policies, original call receipt, latest action/request,
journal revision, whole-record hash and original validity. It is committed with
watch state and audit evidence, and rolls back with them.

Read-only `ScopeWatchBook.entry_selection()` verifies those bindings and returns
exact proposal, quote, fee-inclusive sizing, account/session and management terms.
Later journal events require fresh admission; a new revision argument cannot revive
an old selection. Later watch mutations remove it. Historical retries remain
historical, and restart cannot extend validity. Stored observer and portable research
reproduction retain and verify this evidence. Independent accounts cannot exchange
bindings, and four-contract plans retain the missing-T3 blocker without resizing.
[Contract and boundaries](OPTIONS_SCOPE_ENTRY_BINDING.md).

This is evidence linkage, not native Scope execution enrollment. Generic native
preparation/dispatch still reject Scope even with the exact selected admission.
There are no new native orders, fills, model calls or costs. Existing entry and
management charges, unknown-cost treatment and split-exit fee reserves remain intact.
Native order/fill lineage, full-cost Scope family loss/reset and complete obstruction
coverage still gate execution; Scope runtime and four-contract T3 remain open.

Fresh GitHub baseline: `f502339a3a44111c48e95511a67d736f5311d46e`, tree
`43027efc8b2f66fd7eeb668ae65180994bbf42f2`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation: **190 installed cases passed in 226.80s**, including all 32 new
binding/selection cases, Scope management/admission/native boundaries, observer,
research replay and portable verifier, known/unknown entry-management costs through
partial closes, and full-session independent A/B/C/D attribution. Tests used isolated
Python, a noneditable wheel and copied tests outside the checkout, with warnings
as errors. No failed gate was waived.

The earlier source run had 31 passing cases and one incorrect restart assertion:
reopening alone does not append an event. The corrected test proves unchanged
binding/deadline after reopen and rejection after reconciliation. No production
change or gate waiver was needed. These cases overlap the final installed run.

All 182 application/template files match source/wheel/install, and copied tests
match final source. Scoped lint/format, dependency consistency, whitespace and
66 distinct local documentation targets pass. Wheel SHA-256:
`bb7b61e2cf9acdbd467db011f4c9c33ff08503d1fd9e4e6d82b54636d69f5d8c`.
Proof beside checkout: `scope-entry-source.log`, `scope-entry-installed.log`,
`scope-entry-proof`, `scope-entry-dist`, and build/install logs.

Remaining Scope execution and loss linkage, complete path requirements, four-contract
T3, overnight Swing and mixed ownership stay open. UI and authentic provider/model/
data/host/economic acceptance remain final passes. Main untouched, PR draft, LIVE
disabled and deployment frozen; no authentic broker/provider/model call, dependency
update or host/deployment change.

---

## Fill-bound target protection and Scope management v2: 2026-10-18 UTC

Continuing the settled engine-first order, the native target owner now resolves an
explicit first-milestone stop from actual original entry-fill observations. The
pinned SignalFlow `play_management.target_stop_price()` was reread at
`f9eaf2c1b5d13dca287ee7138126883065b00395`: T1 uses its entry reference, T2 uses T1,
and target protection is independent of scale allocations. Our documented partial-
fill adaptation uses exact quantity weighting of observed CALL asks / PUT bids,
with protective rounding to twelve decimals. It does not copy the source's setup-
price fallback or claim an option/net-profit breakeven.

New native cohorts explicitly enroll `fill-weighted-underlying-v1` with v2 target
milestones and target stops. Preparation, dispatch, reconciliation and portable
accounting enforce enrollment. The original buy retains each fill's quantity,
receipt hash and observed reference or missing data. Complete original quantity
and coverage are required; each sample must be strictly inside original stop/T1
geometry. Scales and restart retain the full original basis, never remaining-lot
or later-quote prices. Frozen plans cannot name both a fixed and entry-bound stop.

Fresh target touches latch independently; usable supervision applies the tighter
reference and checks rebounds immediately. Missing/invalid reference evidence
blocks scales without turning ordinary partial-entry completion into a global halt.
Original stop, premium/time/expiry protection, later fixed stops and full owned
closes remain available under their existing rules. No fill, fee, sale proceeds,
entry/management charge or unknown cost is omitted. Independent owners retain
separate reference and account state.

Scope management v2 now emits both locked milestones for one through three
contracts: T1 protection uses the native entry-bound marker and T2 protection uses
locked T1, including zero-sale milestones. V1 behavior and existing cohort hashes
remain unchanged. Four contracts still report the missing T3; no source allocation
is resized or relabeled. Stored observer and portable research verification retain
the exact v2 plan. The Scope native entry guard remains enforced.
[Contract, source boundary and examples](OPTIONS_ENTRY_REFERENCE.md).

Fresh GitHub baseline: `801ef93c4cfc21381d6b38e8995f1f1f85540abd`, tree
`d067544e403fcb9755ebf2448fcdaf6310dfff14`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation: **315 installed cases passed in 312.09s**, covering the new native
reference behavior, Scope management v1/v2, target exits/stops/milestones and open-
runner export, fill observations, partial closes, cost-floor review, Scope entry
boundaries, research replay/verifier and full-session independent A/B/C/D accounting.
A separate disjoint **33-case installed run passed in 37.67s**, including two new
reference/cost-floor combinations and the complete native cost-floor execution
suite. Both runs use isolated Python, a noneditable wheel and copied tests outside
the checkout, with warnings treated as errors. No failed gate was waived.

An earlier focused 22-case native run passed in 21.31s before the Scope v2 factory
extension; it overlaps the final suite and is not added to its counts. The final
suites verify quantity weighting, protective decimal rounding, partial-entry
completion, missing/invalid observations, stop-only milestones, restart/rebounds,
immutable enrollment, dispatch rejection, rollback, read-only receipt verification,
independent owners and tampered portable basis rejection. Missing entry reference
evidence cannot suppress the independent whole-trade cost-floor exit.

All 181 application/template files match source/wheel/install; copied tests match
final source. Scoped lint/format, dependency consistency, whitespace and 65 distinct
local documentation targets pass. Final wheel SHA-256:
`c5df3dd482d8bf545c1f6b55e9cf2b2da322fda02322917dd7797db16d5fa529`.
Proof beside checkout: `entry-reference-focused.log`, `entry-reference-installed.log`,
`entry-reference-floors.log`, `entry-reference-proof`, `entry-reference-final-dist`
and build/install logs.

Remaining native Scope watch/order/family-loss linkage, complete path requirements,
four-contract T3 resolution, overnight Swing and mixed ownership stay open. UI and
authentic provider/model/data/host/economic acceptance remain final gates. Main
untouched, PR draft, LIVE disabled and deployed experiment frozen; no authentic
provider/model/broker call, dependency update or host/deployment change.

---

## Fill-bound underlying observations: 2026-10-18 UTC

Continuing the settled strategy/engine-first order, native option fill receipts
previously retained the option quote but no underlying observation at the fill
instant. The older setup/approval reference cannot establish that missing evidence.
This slice adds the receipt-level dependency for subsequent actual-entry management
binding. It does not enable Scope entries or invent an aggregate entry/stop rule.

Optional exact underlying quotes now survive individual partial fills, native
reconciliation, restart, stored order/decision attribution and portable export.
Explicitly supplied observations use the existing owner source, freshness,
receipt-lag, synchronization and price limits. Invalid evidence rejects atomically;
reconciliation independently rejects it and refuses any rewrite of accepted fills.
Legacy receipts omit the new field and retain their original encoding. Mixed
coverage stays mixed, without borrowing from approval or later prices.

Replay attaches only usable observations already delivered to each independent
account. Unusable or missing context does not erase an executable option fill or
its charges. Sealed comparison requires attached evidence to have been recorded
by fill time. The evaluator checks projected attribution against the exact fills;
the stored observer retains nullable evidence without refreshing it. Existing
cash, slippage, fees, entry/management charges and unknown-cost treatment remain
unchanged. [Contract and boundaries](OPTIONS_FILL_UNDERLYING.md).

Fresh GitHub baseline: `cafce4866c767109f7541073e3ebf3a00aa221b6`, tree
`f78f6bfd816617b3aab51950b4947827b704a4ca`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation: **22 final installed fill-evidence cases passed in 10.14s**.
The broader installed run passed **288 cases in 297.50s**, with one test-fixture
assertion failure: its altered receipt reused an already recorded snapshot ID,
so the snapshot conflict correctly rejected it before the intended fill conflict.
The final fixture uses a later snapshot and now verifies the exact fill-history
rejection. The initial focused run also had an incorrect result-key assertion.
Only test code changed after these runs; no production fix or waived gate was
needed. The final 22-case rerun covers the corrected fixture and all new cases;
counts overlap and are not added.

The broader checks cover native execution/reconciliation, independent accounting,
sealed tapes, export/CLI, stored observer, stop-only target protection, known/unknown
entry-management costs and the full-session independent A/B/C/D replay. Its managed
attribution checks also verify exact fill-time quotes and reject changed/removed
projections. Runs use isolated Python, a noneditable wheel and copied tests outside
the checkout, with warnings as errors.

All 180 application/template files match source/wheel/install; copied tests match
final source. Scoped lint/format, dependency consistency, whitespace and local
link checks pass. Wheel SHA-256:
`5d9218addd0a0047fc02460986395d1736f1b5d40eb5ca6ed80edb49e32c7e14`.
Proof beside checkout: `fill-underlying-focused.log`, `fill-underlying-conflict.log`,
`fill-underlying-installed.log`, `fill-underlying-final-focused.log`,
`fill-underlying-proof`, `fill-underlying-dist` and build/install logs.

Remaining Scope fill-bound stop rule, native watch/order/family-loss linkage,
complete path requirements, four-contract T3 resolution, overnight Swing and mixed
ownership stay open. Final UI and authentic provider/model/data/host/economic
acceptance remain separate gates. Main untouched, PR draft, LIVE disabled and the
deployed experiment frozen; no authentic provider/model/broker call, dependency
update or host/deployment change.

---

## Durable Scope quote invalidation: 2026-10-18 UTC

Continuing the user's strategy/engine-first delivery order, the prior installed
build reproduced a real watch revival defect: a fresh quote exactly at the original
stop left the same watch `WATCHING` with rejected admission, and later fresh recovery
samples made it eligible again. Completed-bar invalidation already existed; this
slice closes the separately observed quote lifecycle before Scope execution linkage.
A follow-up test also reproduced new-key reuse of a completed bar predating the
terminal quote. New calls now require a strictly later completed bar, while a
genuinely later valid setup retains eligibility under the original call limit.

New frozen watch cohorts may enroll `quote_lifecycle="scope-observed-quotes-v1"`.
The new quote-observation action and enrolled admission reviews share the owner's
frozen SPX source, freshness/receipt-lag bounds, source-clock/content checks and
original geometry. Valid quotes permanently retire the watch at original invalidation
or the locked second objective. Admission observes price before account/context/
arming readiness, so unrelated missing inputs cannot erase an actual observed breach.
Old cohorts retain their prior behavior and cannot adopt the policy on reopen.

Quote evidence, active lock, arming reset and action/audit receipt commit together.
No completed bar, fill, proceeds or loss is invented. Missing/stale/foreign/conflicting
quotes reset an enrolled hold without manufacturing a terminal. Quote-only observations
remove prior admission evidence and never extend the hold. Exact retries, original
terminal evidence, independent watches and original neutral/cooldown rules survive
restart. Native activity still blocks unfilled mutations and Scope entry remains
blocked. [Contract and limits](OPTIONS_SCOPE_WATCHES.md#optional-observed-quote-lifecycle).

Stored observer output retains the exact historical quote, geometry, observation time
and owner-limit hash. The research replay now accepts `OBSERVE_QUOTE`, and the portable
verifier reproduces terminal/rejected recovery steps from the retained request hash
without changing originals. No native order/model call or account mutation is added;
unknown data/host costs remain unknown. Existing independent trading-arm accounting
retains every entry and management charge.

Fresh GitHub baseline: `6e106924a7190eff76e36e90141dcab6c187788c`, tree
`4656a64ba4144385bbcf7b9813c5d5ba8e1d5220`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation: **768 final installed Scope cases passed in 141.53s**, covering all
20 Scope test files and 32 new quote-lifecycle cases, with warnings treated as
errors, isolated Python, noneditable installation and copied tests outside source.

The preceding installed build passed **770 cases in 257.52s**, including all Scope
suites, known/unknown entry-management cost attribution and the independent A/B/C/D
full-session replay. The final change after that run is confined to the six-line
new-call post-terminal bar guard in `scope_watch.py`; all other application bytes
are identical. The complete final Scope suite is rerun rather than repeating the
unchanged trading/accounting implementation. Counts overlap and are not summed.

Focused source runs passed 26 cases in 21.12s and 29 in 23.53s before the additional
neutral/new-key checks. The new-key regression initially selected a setup that was
not detected and failed for that unrelated fixture reason. After selecting an
actually detected setup, it reproduced the missing gate (no exception). The fix
then passed its negative and positive cases in 2.33s. No failed gate was waived.

All 180 application/template files match final source/wheel/install, and copied
tests match source. Scoped lint/format, dependency consistency, whitespace and 63
distinct local documentation targets pass. Final wheel SHA-256:
`11b2f6db31191a5c61b72c28758da5b2b6ebf86c2b06490d2b44275c8fa5ae3d`.

Proof beside checkout: `scope-quotes-source.log`, `scope-quotes-source-final.log`,
`scope-quotes-installed.log`, `scope-quotes-installed-final.log`,
`scope-quotes-post-terminal-*.log`, `scope-quotes-proof`, build/install logs and
`scope-quotes-final-dist`. Remaining native Scope watch/order/family-loss linkage,
complete path requirements, four-contract T3 resolution, overnight Swing and mixed
ownership stay open. UI and authentic data/model/host/economic acceptance remain
final gates. Main untouched, PR draft, LIVE disabled and deployed experiment frozen;
no authentic provider/model/broker call, dependency update or host/deployment change.

---


## Native stop-only target milestones: 2026-10-18 UTC

The user clarified the delivery order: finish remaining strategy/engine plumbing
before the final UI and authentic data/model validation pass. Existing strategy
research remains authoritative; only concrete missing rules/dependencies need a
focused follow-up. The UI review pack remains available but is not the current
engineering milestone.

A concrete management gap was reproduced against the prior installed build:
`TargetExitStep(quantity=0, tighten_underlying_to=...)` was rejected. Thus a
one-contract plan allocated entirely to T2 could not tighten independently at T1.
The pinned SignalFlow `play_management.target_stop_price()` was re-read at
`f9eaf2c1b5d13dca287ee7138126883065b00395`; it advances target protection independently
of scale fills. No new strategy target or allocation is inferred from that source.

New frozen PAPER owners can explicitly enroll `frozen-target-milestones-v2` with
whole-contract closes and frozen target stops. A zero-sale milestone requires an
explicit tighter stop. Schedule and owner versions must match at preparation and
dispatch; old v1 schedules/cohorts remain unchanged. Native target latching,
protection, cumulative fill accounting, order reservations, restart and portable
export now cover stop-only objectives. Zero due creates no target sale or proceeds.
Separately enrolled cost floors use the explicit milestone stages and retain all
fees/model charges. Unknown costs and unvalued open positions remain incomplete.

This closes a shared-engine requirement for small allocations and protected runners.
It does not enable Scope entry or change its frozen v1 management factory. Scope
still needs actual-entry stop/geometry binding, native watch/order/family-loss linkage,
complete path requirements and runtime/replay enrollment; its missing four-contract
T3 remains explicit. Overnight Swing and mixed ownership remain separate work.
See [native milestone contract](OPTIONS_TARGET_EXITS.md#stop-only-target-milestones).

Fresh GitHub baseline: `0211510d6c597c6277df4cf4df15d37c578e0f2f`, tree
`ebcffd3add2540073cc215d55ab97369d107d023`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation: **205 installed tests passed in 294.99s**, warnings as errors, outside
the checkout using the noneditable wheel, isolated Python and copied tests. This
covers 19 new milestone cases, native targets/stops/export, partial closes,
cost-aware floors, Scope management and execution boundaries, plus the independent
A/B/C/D full-session replay with every entry/management charge. A strengthened
exact dispatch-version rejection assertion passed separately in 2.89s with no
production change. The initial focused 14-case run passed in 18.19s; these counts
overlap and are not added. No failed test was waived.

All 179 application/template files match source/wheel/install, and final copied
tests match source. Scoped lint/format, dependency consistency, whitespace and 63
distinct local documentation targets pass. Wheel SHA-256:
`2f69815a89693f5cafaf080e57daa358a4079c091fe88ab82fb7fb09c42059e9`.

Proof beside checkout: `target-milestones-focused.log`,
`target-milestones-installed.log`, `target-milestones-proof`, build/install logs
and `target-milestones-dist`. Main untouched, PR draft, LIVE disabled and deployed
experiment frozen. No authentic provider/model/broker call, dependency update or
host/deployment change. Visual, authentic input/model, host and economic acceptance
remain separate gates.

---



## Portable dashboard review handoff: 2026-10-18 UTC

The next real-market gate still requires actual private provider responses; no
wire mapping or entitlement is inferred from schemas. To advance hands-on testing
without repeating completed build work, the existing installed fixture results
now have a portable UI handoff. [Review procedure](OPTIONS_TESTING.md#your-first-hands-on-review).

Successful `options-test-kit.py` runs create `Trade-Bot-UI-Review.zip`: the exact
24 dashboard HTML files (eight states and both width wrappers), a review index,
README and limited build/test summary with page hashes. Fixed filenames exclude
fixture databases, credentials, source copies, logs and arbitrary report extras.
Incomplete/failed/skipped phase evidence, missing/symlinked pages and an existing
archive are rejected. No browser/server/provider/model/broker call is introduced.

The current pack was exported directly from the completed installed test run at
`21e6a55f37bb6fd39d00dd3204233db9a78be571`, which retained 289 passing cases.
All 24 pages match that output byte for byte. Reviewers can extract and open
`index.html` without installing Python or rerunning tests. This is a review
handoff, not completed visual, provider, host, profitability or LIVE acceptance.
The cloud browser file-URL restriction remains unresolved; no workaround was used.

Fresh GitHub baseline: `21e6a55f37bb6fd39d00dd3204233db9a78be571`, tree
`5db5913369577666166139aaabafe5a78e9467d3`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation: **14 runner/export checks passed in 7.83s**, warnings as errors,
including the existing native import/plugin regression. The real prior completed
run exported 27 ZIP members, passed archive CRC and exact page-byte checks, and
retained 289 passing cases in its limited summary. Scoped lint/format and whitespace
checks pass. Application/runtime code and dependencies did not change, so the
already verified installed trading suites were not repeated. Archive SHA-256:
`6c4dbc520f3cb8caf04f496520916095b6a322967a907bb0141afd2446edb482`.

Proof beside checkout: `ui-review-export-tests.log` and the archive inside
`options-testing-proof-v3`. Main untouched, PR draft, LIVE disabled and the deployed
experiment frozen. Remaining provider samples, normalization, authentic model/host
acceptance, browser/user review and broader strategy implementation stay open.

---


## Installed PAPER testing entry point: 2026-10-18 UTC

The user asked to get ready for testing efficiently without skipping required work.
The current Degen/shared-Swing fixture path is testable before all later families
are complete. The concrete usability gap was scattered commands and proof files,
with no single installed-package run joining runtime/recovery, strategy, observer,
full-cost accounting and dashboard review. [Start testing](OPTIONS_TESTING.md).

`scripts/options-test-kit.py` now requires a new private output directory, a retained
wheel SHA-256 and an installed application matching the checkout. It copies test
inputs outside the checkout, records their hashes and the harness hash, invokes
fixed isolated phases with local fixture workers, and retains logs/JUnit results,
independent test state, before/after release identity and a JSON receipt. Every
phase requires a nonempty completed summary with no failure, error or skip; a zero
exit without a summary cannot become a pass. Application/test drift, interruption,
timeout or failure retain non-passing evidence. Existing output is never adopted.

After all phases pass, the existing eight dashboard display states are generated
at both widths and linked from a local results index. It opens no browser, server,
provider/model/broker connection or deployed population. Static route limitations
and required desktop/mobile/keyboard/contrast review stay explicit. Actual visual
acceptance remains PENDING, including the prior cloud file-URL limitation.

This closes a repeatable offline operator testing path, not authentic PAPER data
or host readiness. The next external dependency is the already documented bounded
Robinhood sample capture with separate authorization, followed by reviewed exact
normalization and authentic model/host acceptance. Scope/overnight/mixed-asset work
remains separate; there is no strategy replan or new live authority.

Fresh GitHub baseline: `4406d7548d3ba813c4d66fa4fc98731e892daeeb`, tree
`de43cb890f029bc73b986987bea700f406acb8f1`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Final runner checks: **eight passed in 7.74s**, warnings as errors.
  Covers existing output, wrong installed identity, empty/failed/skipped summaries,
  and zero process exit with missing completion evidence. The added integration
  case runs the two affected native observer tests through the actual isolated
  runner, proving copied-package imports and explicit async-plugin registration.
- Initial real runner attempt: **85 passed, two failed in 73.69s** in the first
  phase because the isolated copied-tests import path omitted the package parent.
  It correctly retained FAILED, stopped before later phases and did not claim a
  dashboard result. A second attempt retained **85 passed, two failed in 76.22s**
  because disabled plugin auto-loading also needed explicit registration of the
  existing async plugin. The runner now supplies both copied paths and that plugin;
  warnings remain errors. No trading code changed.
- Final complete installed procedure: **289 passed** across runtime/recovery
  (**87**), shared entry (**137**), observer (**64**) and full-session accounting
  (**one**). Each phase retained completed JUnit with zero failures/errors/skips,
  warnings as errors. The accounting phase preserves independent A/B/C/D owners,
  entry and management charges, fees and data/host costs; economics stay INCONCLUSIVE.
  The final receipt is `PASSED_OFFLINE_FIXTURES`. All eight dashboard states were
  generated at both widths; no visual acceptance is claimed. Before/after identity
  and copied test hashes match. Scoped lint/format/whitespace checks pass; all
  63 local documentation targets resolve.
- The existing installed wheel is reused because application sources/templates did
  not change: SHA-256
  `a566fd3cec9fcebe9afb8773d4962442f399bdf4b59fea5baf37c14d70356403`,
  application digest `5d125ccc695d8d0d962befc62f363bec82794539e1a456ddc9c39477e5035e28`.
  Native identity verifies all 179 application files before/after the run. Dependency
  locks remain unchanged. The harness is a checkout script, not a new runtime service.
- Proof beside checkout: `options-testing-proof` (retained failed run),
  `options-testing-proof-v2` (retained plugin-registration failure),
  `options-testing-proof-v3` (final full procedure), `options-test-kit-tests.log`
  and `options-test-kit-tests-final.log`.

Main untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker calls, dependency/host change or deployment.

---


## P7 original Swing first-target consumption: 2026-10-18 UTC

New populations may enroll `observed-lifecycle-v3` with an explicit original
`SwingSeed.first_target`. This closes the pinned promotion contract's unfilled T1
retirement rule for the existing session-close daily-breakout adaptation.
[Policy and limits](OPTIONS_SHARED_STRATEGIES.md#original-first-target-consumption).

The target must be beyond the directional daily breakout reference, recorded in
the seed before the target session opens, and retained in its immutable hash.
Missing/wrong-side targets block v3 eligibility; changing a locked target conflicts.
No target is generated from a generic R multiple, AI output or a later quote.
Earlier cohort policies and omitted-field serialization remain unchanged.

Validated completed bars or fresh authoritative underlying quotes now retain
`TARGET_CONSUMED`, with the exact first target, seed hash, trigger/observation times
and history hash or full quote. Exact touches count. A bar touching stop and target
records invalidation because OHLC cannot establish within-bar order. Quotes use
CALL bid / PUT ask and all prior source/clock/session/price/ownership gates.
Retirement survives recovery, revised histories and restart. Attempted/held orders
retain their existing ownership/protection path, and every paid rejected entry
remains charged. Native replay preserves each independent account's state.

The saved observer displays the original consumed target on subsequent opportunity
records; reads are side-effect free and historical rows retain their own observations.
This does not create held-position target exits, overnight authority or a provider
attestation. Broader target derivation/families, overnight Swing, Scope execution,
mixed stock/options and authentic provider/host/economic/visual acceptance remain open.

Fresh GitHub baseline: `1641c8c7bfbeea26030be03f73513a0b20f9aa06`, tree
`a96968a5f161c6f6625ab2fea6479ca9c9d6d2f0`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Pre-change reproducer failed because the seed had no original first-target
  field. The pinned SignalFlow promotion contract was re-read at
  `f9eaf2c1b5d13dca287ee7138126883065b00395`; no broader strategy replan.
- Source lifecycle/quote/target regression: **94 passed, two full-session cases
  deselected in 30.72s**. Final expanded target suite: **45 passed in 16.77s**.
  Both treat warnings as errors. Covers CALL/PUT, original target geometry and
  immutability, exact touches, invalid evidence, bar ambiguity, recovery/restart,
  paid preparation/dispatch races, ownership, runtime/observer and prefix/native replay.
- The initial combined installed run ended without a final pytest summary and is
  not counted as completed proof. The same cases were split into separate full
  replay and regression invocations; no application change was made.
- Final installed regression outside checkout: **288 passed, three full replay
  cases deselected in 116.53s**. Separate v3 full-session replay: **one passed in
  165.62s**. Both treat warnings as errors, totaling **289 verified installed
  cases**. All eight selected test files and the shared replay helper match the
  copied inputs. The replay preserves independent A/B/C/D orders, all entry and
  management charges, fees and data/host allocations; complete arithmetic remains
  economically INCONCLUSIVE. Previously verified v1/v2 full-session cases were not
  repeated. All 62 local documentation link targets resolve.
- All 172 Python modules and seven HTML templates match source/wheel/installation.
  Wheel SHA-256: `a566fd3cec9fcebe9afb8773d4962442f399bdf4b59fea5baf37c14d70356403`.
  Initial installed collection was discarded after an environment setup error
  selected an older shared package; the corrected environment explicitly installs
  this wheel and asserts its import path before tests. No application change was
  made for that setup issue. Scoped lint/format, dependencies and whitespace pass.
- Scratch proof: `swing-targets-env`, `swing-targets-dist`, `swing-targets-proof`,
  `swing-targets-build.log`, `swing-targets-reproducer.log`, `swing-targets-source.log`,
  `swing-targets-final-source.log`, `swing-targets-install-collection-failure.log`
  `swing-targets-installed.log`, `swing-targets-installed-replay.log` and
  `swing-targets-installed-regression.log` beside checkout.

Status: **fixture verified**.
Main untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker calls, dependency/host change or deployment.

---


## P7 observed Swing quote invalidation: 2026-10-17 UTC

New populations may now enroll
`SwingPolicy.unfilled_lifecycle="observed-invalidation-v2"`. It retains valid
underlying-quote breaches between completed-bar decisions, including a recovery
before the next entry cycle. The existing v1 completed-bar behavior remains frozen.
[Policy, native paths and limits](OPTIONS_SHARED_STRATEGIES.md#observed-quote-invalidation).

The quote must match the configured source, exact seed symbol and target exchange
session, with REALTIME complete evidence, ordered fresh source/receipt clocks,
uncrossed prices and the existing price floor. Exact CALL bid / PUT ask touches
of the original buffered daily stop count. The terminal retains the full observed
quote and source/observation times; no completed history is invented.

The existing supervisor and native entry cycle persist this evidence. Preparation
and dispatch also retain a fresh breach atomically with rejection. Paid rejected
proposals stay charged. Unattempted prepared intents can lose eligibility; attempted
or uncertain orders and known positions retain their existing protection path.
After a verified close, a later breach can retire the same seed for future entry.
No cancellation, resubmission, synthetic fill or implicit flat-state recovery was
added. The native replay applies this boundary separately to each account, while
shortlist replay remains an account-free visible-prefix diagnostic.

Stored terminal/event records retain between-cycle evidence immediately; subsequent
opportunity scans and observer history carry that terminal. Historical opportunity
rows retain their original cycle observations. Dashboard reads do not sample data
or advance lifecycle. Independent A/B/C/D accounts and every entry/management cost,
fee and data/host allocation remain bound to native accounting.

Fresh GitHub baseline: `6e84eb28e29e42a69693c38c764ab4054ae7c6c2`, tree
`897e68f5986413730355265d5ca055e5494736e2`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused source lifecycle/quote suites: **50 passed, two full replay cases
  deselected in 16.15s**, warnings treated as errors. Separate native quote-race
  replay: **one passed in 7.04s**. Covers CALL/PUT, exact touches, frozen v1,
  recovery/restart, invalid/ambiguous quotes, paid entry races, attempted/filled
  protection, continuous runtime/observer and no future tape leakage.
- Initial installed regression outside checkout: **243 passed, one failed, one
  deselected in 252.70s**, warnings treated as errors. The sole failure was the
  reused full-session test expecting no terminal after a completed trade. V2
  correctly retires that seed on a later quote while the account is flat. The
  revised assertion checks retirement at/after the verified fill history and
  retained observed quote. No application guard changed for this correction.
- Corrected installed full-session replay: **one passed in 145.49s**, warnings
  treated as errors. Together with the initial regression, **244 distinct installed
  cases are verified**; the previously verified v1 full-session case was excluded.
  All seven selected test files match the copied installed-proof inputs. The v2
  replay retains independent A/B/C/D accounts, entry and management charges, fees
  and data/host allocations; complete arithmetic remains economically INCONCLUSIVE.
- All 172 Python modules and seven HTML templates match source/wheel/installation.
  Scoped lint/format, dependency and whitespace checks pass; documentation links
  resolve. Wheel SHA-256:
  `f439630c20ceab9e3d3d4234568e1f096a6c5720d5ae18da702cd6d3040d405a`.
- Artifacts/logs beside checkout: `swing-quotes-env`, `swing-quotes-dist`,
  `swing-quotes-proof`, `swing-quotes-build.log`, `swing-quotes-source.log`,
  `swing-quotes-race-source.log`, `swing-quotes-installed.log` and
  `swing-quotes-installed-replay-final.log`.

Observed-quote retirement is fixture verified. Unfilled T1 consumption, broader
Swing families/overnight ownership, Scope execution gates, mixed stock/options,
authentic provider/host acceptance, prospective economics and actual dashboard
visual acceptance remain open. Main untouched, PR draft, LIVE disabled and deployed
experiment frozen. No authentic provider/model/broker call, dependency/host change
or deployment.

---


## P7 terminal Swing completed-bar invalidation: 2026-10-17 UTC

Reproduced a concrete lifecycle gap: a completed CALL bar crossed the original
buffered daily stop, but the prior scanner later returned CONFIRMED after price
recovered into a breakout. New frozen populations may now enroll
`SwingPolicy.unfilled_lifecycle="completed-invalidation-v1"` to retire that exact
seed permanently. CALL/PUT exact touches count; only validated completed
target-session history establishes a breach. [Contract and limits](OPTIONS_SHARED_STRATEGIES.md#terminal-completed-bar-invalidation).

The native cycle retains the first stop/history/seed/time evidence before quote
coverage review and paid entry work. The same journal/restore fence carries the
terminal state across restart and revised history. Both entry preparation and
dispatch enforce it; paid proposals rejected by the guard retain their charges.
An eligible Degen candidate, a fresh session seed and an independent account retain
their own eligibility. Revisited seeds expire at the actual target XNYS close,
including early closes, without replacing earlier invalidation.

The authenticated observer exposes saved reason, original stop and observation/
trigger times without side effects. Shortlist replay reconstructs only the visible
input prefix; native A/B/C/D replay retains separate actual journals and every
entry/management cost. Legacy policy/scan serialization omits absent opt-in fields.
No existing population is migrated or silently enrolled.

Fresh GitHub baseline: `7f20a0e32bd139fa5ecb9c7131466806612ddcd1`, tree
`0ccfd2061d280e4e5b3b88d3a86c3643b35f47b8`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Final focused source: **24 passed, one full native replay case deselected in
  8.07s**, warnings treated as errors. That full replay case runs in the final
  installed proof below.
- Final new installed lifecycle suite outside checkout: **25 passed in 165.15s**,
  warnings treated as errors. Includes native A/B/C/D full-session replay with
  independent order identities, both entry/management charges, fees and data/host
  allocations; complete arithmetic remains economically INCONCLUSIVE.
- Final existing installed regression outside checkout: **214 passed in 420.54s**,
  warnings treated as errors. Includes shared strategy and multi-session replay,
  Degen, market tapes, authenticated observer and dashboard rendering. Together
  the two installed suites passed **239 tests**. All seven selected test files
  match the copied installed-proof inputs.
- All 172 Python modules and seven HTML templates match source/wheel/installation;
  scoped lint/format, dependency and whitespace checks pass. Local documentation
  targets resolve.
- Wheel SHA-256: `09eebf6442120149f2951cca38bf31c3103a39f97cc62372560bdb83d1ad63fa`.
  Artifacts/logs beside checkout: `swing-lifecycle-env`, `swing-lifecycle-dist`,
  `swing-lifecycle-proof`, `swing-lifecycle-build.log`,
  `swing-lifecycle-focused-final.log`, `swing-lifecycle-installed-focused.log`
  and `swing-lifecycle-installed-regression.log`.
- Initial new tests needed existing helper/route corrections and assertions using
  equivalent UTC timestamps and the exported usage schema. The full source replay
  produced COMPLETE_ARITHMETIC before its incorrect raw-cost-field assertion.
  Earlier failing outputs remain `swing-lifecycle-source.log`,
  `swing-lifecycle-source-second.log`, `swing-lifecycle-source-third.log` and
  `swing-lifecycle-source-final.log`; the prior focused 20-case pass is retained
  in `swing-lifecycle-source-fourth.log`. No production guard was relaxed.

This is completed-bar pre-entry retirement, not quote-tick latching, unfilled T1
consumption (the current seed has no frozen T1), overnight Swing or full M7
acceptance. Scope source/path/native-entry/family-loss/T3/runtime gates,
mixed-instrument ownership, authentic provider/host acceptance, prospective
performance and actual dashboard visual acceptance remain open. Main untouched,
PR draft, LIVE disabled and deployed experiment frozen. No authentic provider,
model or broker call, dependency/host change or deployment.

---


## M8 dashboard decision/protection presentation: 2026-10-17 UTC

The first dedicated dashboard pass now leads with compact cash/current-estimate,
known-cost and operating evidence; population/release details expand separately.
Decision history replaces the wide opportunity table with readable proposal,
review/application, order-attempt and fill stages. It retains exact model charges,
unknown/not-called states, AI uncertainty, management changes and candidate/identity
details. A stop application without an order never becomes a fictional fill.
[Surface, rendering drill and remaining acceptance](OPTIONS_DASHBOARD.md).

Owned management now displays saved health condition/action with observation time
and freshness, retained premium/trade floors and expandable progress/Greek evidence.
Missing components remain unknown; stale saved conditions remain labeled as history.
Historical comparison and current incomplete estimates retain their distinct cost
boundaries. HOLD, unavailable evidence, unknown orders/costs and research-only Scope
remain explicit. All controls are native links/disclosures; no JavaScript or trading
control was added. Authentication, CSP, API schemas, native accounting, independent
accounts and every entry/management charge are unchanged.

The new offline drill creates eight synthetic display states and wrappers for
1360px/390px viewports. Entry/management/fill, stale and HOLD baselines use native
fixture owners with scripted responses; comparison and modified edge states are
presentation examples only. It attaches to no deployed or authentic population.

Fresh GitHub baseline: `28f24332c377963802a09509d9748a8bebf678d7`, tree
`5a7465b8bd7ce9c4461e0ddb26eedde108b00be6`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Existing observer/comparison/Scope evidence source regression: **105 passed,
  one installed-only case deselected in 26.68s**. Focused new presentation cases:
  **11 passed in 5.06s**, warnings treated as errors.
- Final installed regression outside checkout: **188 passed in 373.48s**, warnings
  treated as errors. Includes observer authentication/immutability, comparison,
  Scope observer/evidence, native health and full managed replay/export suites;
  all entry/management costs and independent A/B/C/D accounts remain covered.
- Installed offline drill generated all eight states and both 1360px/390px wrappers.
  This proves rendering output generation, not browser rendering or screenshots.
- All 171 Python modules and seven HTML templates match source/wheel/installation;
  all eight selected test/helper inputs match. All 30 checked text-palette/background
  combinations exceed 4.5:1, with minimum calculated contrast **6.18:1**. Scoped
  lint/format, dependencies, whitespace and 58 unique local documentation targets pass.
- Wheel SHA-256: `b99a814df98141541b49073ba9d9fea23335f4b8f3f561b848e8fe15b1222681`.
  Artifacts/logs beside checkout: `dashboard-env`, `dashboard-dist`, `dashboard-proof`,
  `dashboard-installed-preview`, `dashboard-build.log`, `dashboard-initial-tests.log`,
  `dashboard-focused-final.log`, `dashboard-installed-final.log` and
  `dashboard-render-final.log`.
- Initial installed test collection and drill failed because the isolated test
  harness omitted the copied root needed by existing `tests.*` imports. The harness
  and documented drill now include both the copied root and test directory. No
  application code or guard changed for this correction. Original error outputs
  remain `dashboard-installed-tests.log` and `dashboard-render.log`.

The cloud browser rejected the local fixture preview URL under its HTTP/HTTPS-only
URL policy. No workaround or alternate browser surface was attempted. No screenshot,
actual desktop/mobile rendering, clipping, keyboard traversal or user visual
acceptance is claimed. The deterministic palette check does not replace rendered
contrast review. M8 remains open pending those checks and user review.

Scope source/path/native-entry/family-loss/T3/runtime gates, authentic provider/host
acceptance, prospective economics, remaining Swing and mixed-instrument support
remain separate. Main untouched, PR draft, LIVE disabled and deployed experiment
frozen. No provider/model/broker call, dependency or host/deployment change.

---

## P7 portable Scope replay reproduction verification: 2026-10-17 UTC

`app.options.scope_replay_verify` now verifies exported research JSON against an
independently retained original request hash. It captures the normalized inputs,
exact numbered actions and final report, then reproduces the request through the
native research runner in new private temporary PAPER state. All receipts, rejected
reasons, revisions, hashes, artifact indexes and final observer/account evidence
must match canonical JSON, including exact authority types. Editing a receipt and
its own hash no longer suffices. [Command and limits](OPTIONS_SCOPE_REPLAY.md#portable-reproduction-verification).

The verifier never opens source journals or restore authority and does not modify
original file contents. Portable copies need only the private JSON layout; results
explicitly say `source_journals_verified=false`. It rejects interrupted/missing/extra
artifacts, duplicate keys, nonfinite literals, unsafe final symlinks, public modes,
nonregular files and per-file/aggregate size overflow. Temporary state is removed on
success and handled failure. Verification describes the captured snapshot under the
installed implementation, not provider authenticity, release approval or later edits.

Rejected actions, arming resets and missing four-contract T3 remain research results,
not trade approval. Scope remains blocked from native entry. Research data/host costs
and net return remain null; economic conclusion remains NOT_EVALUATED. Independent
A/B/C/D trading accounts and all entry/management charges are unchanged.

Fresh GitHub baseline: `142a75574770b667971f92931c0193bb02be09bb`, tree
`33fc76ad04aa50ecde1e9037afe2bd6925618909`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Initial focused source run: **36 passed, one installed-only case deselected in
  18.03s**, warnings treated as errors. The later missing-T3 acceptance case is
  included in the final installed run.
- Final installed regression outside checkout: **737 passed in 140.01s**, warnings
  treated as errors. Includes all 19 Scope files, all 38 new verifier cases, installed
  isolated replay/verifier CLIs and enrolled A/B/C/D full entry/management-cost replay.
- New cases cover CALL/PUT reproduction, fee/receipt/revision/reason/report edits,
  coordinated receipt-hash edits, substituted requests, exact authority types,
  missing/extra/interrupted artifacts, private modes, symlinks, nonregular files,
  JSON ambiguity, bounds, original-file preservation, JSON-only portability,
  rejected actions/resets, retained missing-T3 blocker and temporary failure cleanup.
- All 171 Python modules and four HTML templates match source/wheel/installation;
  all 19 copied Scope test files match. Scoped lint/format, dependency and whitespace
  checks pass; local documentation targets resolve.
- Wheel SHA-256: `84654e32b5002a8285e30e69dd8d02864fb04c0b72d3e94ff7b472697385a7d3`.
  Artifacts/logs beside checkout: `scope-verify-env`, `scope-verify-dist`,
  `scope-verify-proof`, `scope-verify-build.log`, `scope-verify-source.log` and
  `scope-verify-installed-tests.log`.

Portable research reproduction is delivered. Scope complete path coverage,
watch/order linkage, filled family-loss/reset controls, four-contract T3 resolution
and trading runtime/replay acceptance remain open. Dedicated UI visual acceptance,
authentic provider/calendar/host evidence, remaining Swing and mixed-instrument
support and prospective economics remain separate gates. Main untouched, PR draft,
LIVE disabled and deployed experiment frozen. No authentic provider/model/broker
call, dependency or host/deployment change.

---

## P7 native Scope research lifecycle replay: 2026-10-17 UTC

`app.options.scope_replay` now runs a frozen ordered CALL / OBSERVE_ARMING /
REVIEW_ADMISSION / ADVANCE / NEUTRALIZE fixture sequence through a create-only
native PAPER owner and the existing watch book. It reconciles and supervises its
independent empty account at each virtual clock, obtains the actual journal
revision and invokes the native research method. No caller account, quantity,
revision, receipt, outcome or execution authority is accepted.
[Request, artifacts, command and precise limits](OPTIONS_SCOPE_REPLAY.md).

The private run retains frozen inputs/hash, per-step full native receipts or
explicit action rejections, receipt hashes, native journals and final stored
observer/account/model evidence. Interrupted runs retain available artifacts and
cannot be resumed or overwritten. A completed research run means all supplied
steps were processed, not that each action passed. Arming resets, rejected admission
and the missing four-contract T3 retain their original meanings and blockers.

No orders, fills, paid model calls or native trade decisions may exist at export.
Native fee-inclusive admission and recorded account/model evidence are retained;
data/host cost and net return stay null, with `economic_conclusion=NOT_EVALUATED`.
Independent run directories remain independent accounts. This does not enroll Scope
in trading A/B/C/D replay, remove its entry guard or establish economic performance.
The existing trading replay still retains every entry and management charge.

Fresh GitHub baseline: `6c7fce05b10528ceaf9aa1286f280c85629188a3`, tree
`fbf9b5a63fdcd36e70cd063e6538a39a14ac382d`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused source: **20 passed, one installed-only case deselected in 11.13s**,
  warnings treated as errors. Covers CALL/PUT, arming, fee-inclusive admission,
  invalidation/neutral reset, cutoff expiry, rejected calls, missing-data resets,
  identical-run reproduction, independent owners, future/ambiguous/extra inputs,
  private/create-only paths, interrupted runs and retained T3 management blocker.
- Installed command outside checkout: **one passed in 6.49s**, using isolated mode.
- Full installed Scope regression plus enrolled A/B/C/D full-cost replay:
  **699 passed in 121.46s**, warnings treated as errors, outside checkout. Includes
  all 18 Scope files and the new native CLI case.
- All 170 Python modules and four HTML templates match source/wheel/installation;
  all 18 copied Scope test files match. Scoped lint/format, dependency and whitespace
  checks pass; 61 unique local documentation targets exist.
- Wheel SHA-256: `c4a63ac3a95e611d07187d6caa7e4fb2db5feb188c51dc099ef6d5f31553a714`.
  Artifacts/logs beside checkout: `scope-replay-env`, `scope-replay-dist`,
  `scope-replay-proof`, `scope-replay-build.log`, `scope-replay-source-complete.log`,
  `scope-replay-cli-tests.log` and `scope-replay-installed-tests.log`.
- Initial focused run caught a fixture using the wrong underlying quote-source
  name, correctly blocking both CALL/PUT admissions. The fixture now uses the
  owner's configured source. No native guard was weakened. Earlier outputs remain
  `scope-replay-source.log` and `scope-replay-source-final.log`.

Research lifecycle replay/export is delivered. Scope still requires complete path
coverage, native watch/order linkage, filled family-loss/reset controls,
four-contract T3 resolution and trading runtime/replay acceptance. Dedicated UI
visual acceptance, authentic provider/calendar/host evidence, remaining Swing and
mixed-instrument support and prospective economics remain separate gates.
Main untouched, PR draft, LIVE disabled and deployment frozen. No authentic
provider/model/broker call, dependency or host/deployment change.

---

## P7 Scope stored decision evidence and action binding: 2026-10-17 UTC

The stored observer now exposes selected original and latest sampled Scope quality,
contract profile and path evidence. Scores/components, classifications, exact
obstructions and plateau formation/confirmation provenance remain attached to their
saved input/policy hashes and evaluation time. The existing authenticated page adds
collapsed **Decision evidence** details; the API retains the full bounded level set.
[Read contract and limits](OPTIONS_OBSERVER.md#scope-research-visibility).

Every displayed watch must match its latest action event and original receipt,
including exact record, revision and false authority values. Frozen enrollment and
last-action time must match their recorded events. Typed scans must retain their
input/policy/time bindings and unique selected pattern/parent/direction; contract
reviews must contain the same quality review. Missing or independently altered
bindings make the report unavailable. This is stored consistency checking, not
request replay, provider authentication or protection against coordinated rewriting
of the complete journal.

Missing latest scans remain missing, even when the original call passed. Future,
expired and within-recorded-window labels remain distinct from eligibility. The
page shows at most five path levels with an explicit total; raw market frames and
unselected alternatives are not added to the report. Reads do not call scanners,
attach an owner, submit orders or change journal revisions. Account costs and
independent A/B/C/D execution remain unchanged.

Fresh GitHub baseline: `7812763d9a8871de48aee53980a0922f36710edf`, tree
`df45e847fc528794f89c3afd6a1fd8269225268c`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused source evidence/observer/plateau suites: **81 passed in 22.22s**, warnings
  treated as errors. New cases cover original/current selections, CALL/PUT,
  stale/future/missing inputs, altered watch/event/receipt/enrollment records,
  input/policy/clock/selection mismatches, no scanner/owner calls, authenticated
  HTML/API rendering, and unchanged journal revisions.
- Installed wheel outside checkout: **763 passed in 121.61s**, warnings treated as
  errors. Includes all 17 Scope files, the general observer and historical comparison
  suites, plus enrolled A/B/C/D replay with every entry/management charge.
- All 169 Python modules and four HTML templates match source/wheel/installation;
  all 17 copied Scope test files match. Scoped lint/format, dependency and whitespace
  checks pass; 60 unique local documentation targets exist.
- Wheel SHA-256: `474b3b1b2a035fa6c387447acdcf078fac137ccadb30e2ac3080823e3d45968d`.
  Artifacts/logs beside checkout: `scope-evidence-env`, `scope-evidence-dist`,
  `scope-evidence-proof`, `scope-evidence-build.log`, `scope-evidence-source.log`
  and `scope-evidence-installed-tests.log`.
- Initial focused run: 59 passed / one failed because an old retained-history
  fixture inserted watches without their action/receipt evidence. The fixture now
  seeds consistent historical records; the production binding check remains intact.
  Original output is retained in `scope-evidence-initial.log`.

Functional read-only UI evidence is delivered; the dedicated desktop/mobile design
and visual acceptance pass remains open. Scope full path coverage, native watch/order
linkage, filled family-loss/reset controls, missing four-contract T3 and runtime/replay
enrollment remain open. Authentic provider/model/host and prospective economics,
remaining Swing and mixed-instrument support remain separate gates. Main untouched,
PR draft, LIVE disabled and deployment frozen. No authentic provider/model/broker
call, dependency or host/deployment change.

---

## P7 Scope confirmed plateau path evidence: 2026-10-17 UTC

New research cohorts can freeze `completed-spx-plateaus-v2`, extending the existing
completed SPX level review with maximal exact equal-high/equal-low runs. Strict
outside neighbors and a completed right confirmation bar are required. Formation
start/end, confirmation time and touch count persist alongside the exact level.
No tolerance, future bar, session-edge neighbor or complete-path claim is inferred.
[Contract and remaining coverage limits](OPTIONS_SCOPE_QUALITY.md#optional-confirmed-equal-highequal-low-plateaus).

The same levels now participate in quality, sampled arming and current CALL-ask /
PUT-bid admission against locked geometry. Obstructions through T1 reject; those
between T1 and T2 remain visible. Newly confirmed obstructions reset arming, and
blocked calls consume no watch or model charge. Stored observer output and restart
preserve provenance. Existing omitted/v1 policies retain behavior and serialization;
frozen watch cohorts cannot change enrollment on reopen. No score, objective,
quantity tier, account limit or cost policy changed.

Fresh GitHub baseline: `b0c5b66b967bea4537eba3a2bd205011ae68cad9`, tree
`5b5946b2513f3216a36e45fc564149180521b94b`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused source suite: **40 passed in 4.44s**, warnings treated as errors.
  Covers both directions, exact path endpoints, 2/3/94-touch formations, missing
  neighbors, unequal prices, no look-ahead, legacy behavior, invalid histories,
  atomic watch rejection, arming resets, fee-inclusive admission, stored reads,
  restart and frozen-policy mismatch.
- Installed wheel, outside the checkout: **657 passed in 93.39s**, warnings treated
  as errors. Includes all 16 Scope test files and enrolled A/B/C/D replay retaining
  every entry/management charge in independent accounts.
- All 169 application source/wheel/installed modules match; all 16 copied Scope
  test files match. Scoped lint/format, dependency and whitespace checks pass;
  60 unique local documentation targets exist.
- Wheel SHA-256: `d2eca442a6420dd8dde488d59255e5fc6867de0a5f02d17156fc53c4848bd666`.
  Artifacts/logs beside checkout: `scope-plateaus-env`, `scope-plateaus-dist`,
  `scope-plateaus-proof`, `scope-plateaus-build.log`,
  `scope-plateaus-source-tests.log` and `scope-plateaus-installed-tests.log`.
- Earlier focused runs caught fixture omissions: contract metadata lacked observed
  delta/liquidity, and a flat-close extension no longer detected the selected trend
  pattern. Corrected fixtures exercise the intended gates; no production guard
  was weakened. Those logs remain `scope-plateaus-focused.log` and
  `scope-plateaus-focused-final.log`.

This closes the equal-extreme plateau component of known-level coverage, not the
full obstruction gate. Overnight/other-horizon/broader-zone coverage, native Scope
watch/order linkage, filled family-loss/reset controls, missing four-contract T3
and runtime/replay enrollment remain open. Convexity and native Scope entry remain
blocked. Authentic provider/model/host and prospective economics, remaining Swing
and mixed-instrument support, and the dedicated UI pass are separate gates.
Main untouched, PR draft, LIVE disabled and deployment frozen. No authentic
provider/model/broker call, dependency or host/deployment change.

---
## P7 frozen observed daytrade health actions: 2026-10-17 UTC

New PAPER cohorts can explicitly enroll `observed-daytrade-health-v1`. Original
buy inputs, approval and intent bind the frozen owner policy; dispatch and portable
accounting reject mismatched enrollment. Existing owners cannot silently adopt it.
The policy composes observed Greek/progress diagnostics with native spread and
session evidence. Complete inputs can tighten pre-target stops to source caution
or defensive risk levels, or latch mandatory exits for crossed caps and covered
stalled-trade decay. Existing stricter stops and mandatory reasons keep priority.
[Policy, thresholds and precise source adaptation](OPTIONS_HEALTH_MANAGEMENT.md).

Incomplete/estimated/stale/conflicting/gapped evidence withholds new health actions
and blocks discretionary scales while independent full protection remains active.
Swing and longer-dated contracts are explicitly outside this policy. No unverified
free-form regime label or stale-price fallback gains authority. Source premium
diagnostics remain before costs; native fees, every entry/management charge and
session data/host allocations remain intact in four independent replay accounts.

Health state and protection commit atomically with audit evidence. Restart/rebound
cannot clear an exit or loosen a stop. Attempted scales keep reservations; only
never-attempted scales may be superseded. A paid stale model response cannot undo
new health tightening and retains its charge. Stored observer reads verify audit
binding and label freshness without reassessment. Closing attribution inherits the
original entry enrollment; open exports remain economically inconclusive.

Fresh GitHub baseline: `045234fb7ee72eed50cfcd24139ac08dd123f96d`, tree
`e7a267fb6b0e00bf39847b021c85575d32df83b6`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused development caught test-fixture errors: a scale fill attempted to regress
  snapshot time, replay enrollment used the wrong settings field, same-source-time
  conflicting Greek evidence correctly withheld an action, and portable definitions
  needed consistent arm policies and matching definition hashes to reach the policy
  mismatch check. The model race correctly returns REJECTED for its stale paid plan.
  Fixtures/assertions were corrected without weakening evidence gates.
- Final installed health suite: **24 passed in 51.71s**, warnings treated as errors,
  outside the checkout against the non-editable wheel. Includes CALL/PUT stops,
  decay exits, restart/fills, incomplete inputs, late-session/spread rules, longer
  dated exclusion, scale reservations, target gating, atomic rollback, stored
  observer, paid-model race, native open export and enrolled A/B/C/D costs.
- Broader installed health/progress, execution, Greek, observer, partial/target
  exits/stops, floors/trails, position-management and economic/export regression:
  **603 passed, 2 failed in 431.12s**. That process had already loaded the earlier
  model-race and portable-definition test assertions described above. Both corrected
  cases pass in the final 24-case installed suite. Production/wheel bytes are
  unchanged between these runs; all 605 distinct selected cases are covered by
  passing final evidence, without another unrelated full regression run.
- Seven source/wheel/installed modules and all 15 final copied test files match.
  Scoped lint/format, dependency, whitespace and 265 local documentation links pass.
- Wheel SHA-256: `2d475a4ad84b39b961f5ba1d2903cab4e575559b0fa6d254469cf11e9ec7ce2c`.
  Artifacts/logs beside checkout: `health-management-env`, `health-management-dist`,
  `health-management-proof`, `health-management-build.log`,
  `health-management-initial-tests.log`, `health-management-focused.log`,
  `health-management-final-cases.log`, `health-management-installed-tests.log` and
  `health-management-final-focused.log`. An obsolete focused process overlapped the
  final log destination; its combined original is retained as
  `health-management-overlapped-focus.log`. The final focused process exited 0;
  its distinct 24-pass result is retained separately from the obsolete failures.

Authentic health/provider/model evidence and prospective policy economics remain
unverified. Scope entry/path/family-loss/runtime integration, remaining Swing and
mixed-instrument support, host acceptance and the dedicated UI pass remain open.
Main untouched, PR draft, LIVE disabled and deployment frozen. No authentic
provider/model/broker call, dependency or host/deployment change.

---

## P7 durable observed progress and stall coverage: 2026-10-17 UTC

Native supervision now records `observed-progress-v1` for each owned entry in an
audited transaction. Original preparation/approval underlying quotes supply fixed
CALL-ask/PUT-bid references and original risk distance; completed actual entry fills
supply premium basis and original quantity. Partial entries remain incomplete.
Partial sales, stop changes, reconciliation and restart cannot rebase these terms.

Fresh synchronized exact-contract bids and directional underlying prices retain
peaks, last-progress time and highest native target stage. Exact source-backed
stall, premium divergence and premium/underlying giveback diagnostics are available
without enabling health-driven actions. Missing, stale, regressing or conflicting
observations preserve state and suppress current signals. Stalls require a valid
20-minute sampled coverage window; gaps cannot become evidence of no progress.
Tracking never backfills an unobserved pre-installation or partial-entry interval.
[Evidence contract and thresholds](OPTIONS_PROGRESS_HEALTH.md).

Stored observer reads bind the saved row to its latest audit event and label current
freshness separately from historical evaluation. Legacy detached journals without
the table remain readable. Native A/B/C/D journals retain separate progress and all
entry/management charges. Premium diagnostics exclude costs and are not net returns;
verified economic exports, unknown-cost semantics and whole-trade floors remain
independent. Portable progress-history export is not added in this slice.

Fresh GitHub baseline: `d33d4f75349ccace1062c39edc097126f0b0b215`, tree
`ea2a098bd33b2f839aeac99a60e1c2d82a9bdca9`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Initial focused tests found the missing restart table registration and a repeated
  observation event caused by equivalent Decimal values with different text scales;
  both were corrected. A test helper's low-precision price construction was moved
  outside the low-precision application check. Focused source suite then passed
  **21 tests in 13.18s**, before adding target, audit-binding and A/B/C/D cases.
- The first installed regression invocation used a nonexistent test filename and
  collected no tests. The path was corrected without application changes; the
  retained log is `progress-health-collection.log`.
- Final installed progress, execution, Greek, observer, partial-close, target,
  floor/trail, position-management and native-export regression: **533 passed in
  377.46s**, including all **25 new cases**, with warnings treated as errors outside
  the checkout against the non-editable installed wheel. Includes native A/B/C/D
  progress with every entry/management charge, target touches without sales,
  restart, partial fills/scales, exact thresholds, quote conflicts, duplicate
  observations, audit rollback and detached/legacy observer reads.
- Three source/wheel/installed modules and all 13 copied regression files match.
  Scoped lint/format, dependency consistency, whitespace and 254 local documentation
  links pass.
- Wheel SHA-256: `16fdf478da5f5d5a4e45df670ad9343c24bf6da7eeafecad8e4f5b6559ea09ea`.
  Artifacts/logs beside checkout: `progress-health-env`, `progress-health-dist`,
  `progress-health-proof`, `progress-health-build.log`, `progress-health-focused.log`,
  `progress-health-collection.log` and `progress-health-installed-tests.log`.

Full health management still needs remaining liquidity/session context, composition
with Greek/progress evidence, frozen actions and native stop/exit/restart/replay
acceptance. Scope entry/path/family-loss/runtime integration, authentic provider/host
evidence, prospective economics and the dedicated UI pass remain open. Main untouched,
PR draft, LIVE disabled and deployment frozen. No authentic provider/model/broker
call, dependency or host/deployment change.

---

## P7 observed Greek evidence and pressure review: 2026-10-17 UTC

The next missing health-management input was explicit theta/IV evidence: native
option quotes carried only bid/ask/size, while selection metadata retained delta
alone. Optional `OptionGreekObservation` now preserves exact instrument, source and
receipt times, completeness, entitlement, OBSERVED/ESTIMATED/UNAVAILABLE provenance,
and explicit per-share/day theta and decimal-fraction IV units. Omitted observations
retain legacy serialization. No provider adapter or Greek estimator is introduced.

The fixed `observed-greek-pressure-v1` review implements the Greek components of
pinned SignalFlow v1 `assess_management`: theta reference pressure at 6% per reference
hour using the fixed 6.5 divisor, IV warnings/severity at 15/25% contraction, and absolute
delta warnings/severity at 20/35% deterioration. Exact comparisons precede display
rounding. Original entry observations are checked at their preparation time; current
observations must be fresh, observed, synchronized, correctly signed and bound to
the same instrument. Missing components remain null while independent valid
components remain visible. READY never means healthy; no full source score is claimed.

The stored observer exposes the review when Greek evidence exists, binding the
original approval/preparation quote and withholding conflicting current observations.
Reads remain bounded and immutable. Sealed tapes reject future/foreign Greek evidence;
native fills and four independent replay accounts retain it and all model charges.
[Evidence contract, exact thresholds and limitations](OPTIONS_GREEK_HEALTH.md).

Fresh GitHub baseline: `30c4d71665aa623a3dcab1009ab26b080b84cb69`, tree
`5d2516a9adb543578ce7a8b3ea666a985b64286e`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- The initial boundary-test input exceeded the existing 12-decimal evidence bound;
  the validator correctly rejected it. Test values were corrected within the bound,
  preserving distinctions below display precision; application bounds were not widened.
- Focused source suite: **49 passed in 18.03s** before adding three observer/freshness
  cases.
- Final installed Greek, admission, sealed-tape, observer, native execution,
  entry/position reasoning and position-coordination regression: **595 passed in
  128.05s**, including all **52 new cases**, with warnings treated as errors outside
  the checkout against the non-editable wheel. The new four-arm replay case retains
  observed Greeks through fills and all native entry/management charges.
- Four source/wheel/installed modules and all eight copied regression files match.
  Scoped lint/format, dependency consistency, whitespace and 244 local documentation
  links pass.
- Wheel SHA-256: `26f6a71e854576642ff43f213053a9240455340f027c9a59b6dce9e9607712ca`.
  Artifacts/logs beside checkout: `greek-health-env`, `greek-health-dist`,
  `greek-health-proof`, `greek-health-build.log`, `greek-health-focused.log`,
  `greek-health-initial-input-failure.log` and `greek-health-installed-tests.log`.

Full health management still needs durable original underlying risk geometry,
progress/stall/peak state, remaining non-Greek conditions and frozen action/restart
acceptance. Scope entry/path/family-loss/runtime integration, authentic provider/host
evidence, prospective economics and the dedicated UI pass remain open. Main untouched,
PR draft, LIVE disabled and deployment frozen. No authentic provider/model/broker
call, dependency or host/deployment change.

---

## P7 automatic native whole-trade floors: 2026-10-17 UTC

New frozen PAPER owners can enroll `trade_floor="native-target-floor-v1"` alongside
whole-contract partial closes and frozen target exits. Original buy inputs, intent,
approval and dispatch bind enrollment; accounting and reconciliation preserve it.
The engine activates the pinned 0/10/25% reference scenarios after native target
progress, using complete original entry premium, actual linked sales, every execution
fee and attributable entry/management charge, plus conservative remaining exit fees.
It never invents a target schedule for a full-entry AI position or Scope watch.

Accepted minimum fill-price protection is monotone across scales and restart.
Fresh executable bids pass through native conservative slippage and downward tick
rounding; crossing the saved positive floor latches `WHOLE_TRADE_FLOOR`. The first
exit time survives rebound. Existing mandatory reasons keep priority. Missing costs
or incomplete entries withhold new arithmetic and block scales after a target,
retaining earlier protection and independent full exits. Working orders keep their
reservations; only never-attempted scales may be superseded. Native partial-close
and settled management execution reviews refresh protection in audited transactions.

The observer displays saved state without refresh. Native export retains complete
floor annotations, while fill/cash comparison checks original enrollment and ignores
dynamic state. Open positions remain inconclusive; data/host costs stay in session
economics. The existing explicit preview API retains false authority and can show a
lower candidate than the owner's accepted monotone floor. [Policy and limitations](OPTIONS_TRADE_FLOOR.md).

Fresh GitHub baseline: `f58583ba6784b4115978d52a9b0cc7474fdc0d61`, tree
`12f07e69900437b2b336ffb124c5687d6307df1d`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Initial focused source cases: **24 passed in 14.34s**.
- Installed floor, preview, premium trail, target exits/stops/export, partial-close,
  position-coordination, native outcome and observer regression: **296 passed in
  307.47s**, warnings treated as errors, outside the checkout against the
  non-editable wheel. Includes independent A/B/C/D entry/management costs.
- Final focused installed suite: **31 passed in 34.36s** outside the checkout,
  including three additional native paid-selection/unknown/unallocated cost cases.
  Those three also passed separately in 4.26s. The complete suite covers both
  option directions, exact thresholds, monotone sales/restart, audit rollback,
  stale bids, pending and partially filled orders, enrollment/dispatch binding,
  stored observation, native open export and four independent replay accounts.
- Ten changed source/wheel/installed modules and all ten copied regression files
  match. Scoped lint/format, dependency consistency, whitespace and 236 local
  documentation links pass.
- Wheel SHA-256: `914f55a148f2c7d948e5fa5ae9cc9ed51a2eec00a56d1075c86e97e0d3057ba5`.
  Artifacts/logs beside checkout: `auto-floor-env`, `auto-floor-dist`,
  `auto-floor-proof`, `auto-floor-build.log`, `auto-floor-focused.log`,
  `auto-floor-installed-tests.log`, `auto-floor-cost-tests.log` and
  `auto-floor-final-focused.log`.

Remaining work includes source health/Greek management, Scope watch/entry and full
management/runtime/replay integration, its missing four-contract third objective,
authentic provider/host evidence, prospective economics and the dedicated UI pass.
The full-entry AI path still has no frozen native target schedule; enrollment is
inactive there and does not change its existing protection. Main untouched, PR draft,
LIVE disabled and deployed experiment frozen. No authentic provider/model/broker
call, dependency, host unit or deployment changed.

---

## P7 native whole-trade floor previews: 2026-10-16 UTC

The next whole-trade management prerequisite is verified remaining-proceeds
arithmetic after scale-outs. Pinned SignalFlow `play_management.py` at
`f9eaf2c1b5d13dca287ee7138126883065b00395` supplies reference 0/10/25% floors but
omits execution fees and model charges from its whole-trade formula. The new
`native-target-floor-preview-v1` calculation uses complete original entry fills,
actual linked sale proceeds, every paid execution fee and attributable entry or
management charge. It reserves remaining exit fees conservatively as one charged
filled order per remaining contract. Upward contract-tick rounding produces a
minimum actual fill-price threshold, including the $3 tick-tier boundary.

`OptionObserver.trade_floor(entry_client_id)` exposes this explicit read-only
preview from one bounded native snapshot. It retains full position evidence and
hashes, revision, separate account-snapshot/event times, current remaining quantity
and stored target progress. Unknown/unallocated costs, partial entries and unresolved
orders suppress floors. Closed entries have no runner floor. A target touch never
creates sale proceeds; scales never replace original premium with remaining basis.
Stored target progress can select a reference scenario only when the frozen schedule
matches the original intent. All results retain false execution/LIVE authority.

This supplies accounting plumbing, not automatic enforcement or policy enrollment.
No quote is fetched or sampled, exit latched, order submitted or existing observer
page changed. Data/host charges remain in session economics, explicitly excluded
from this position preview; future paid advice can raise required proceeds.
READY means available stored arithmetic, never a completed outcome or guaranteed
breakeven. [API and exact boundaries](OPTIONS_TRADE_FLOOR.md).

Fresh GitHub baseline: `37ca15f7d003a04ee9ca5eefd683fc91ab313169`, tree
`b5ed294495df3bc5fb8d115c6bdd50ec98c7c899`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Source preview cases: **22 passed in 19.29s** before extending the model-cost
  cases to include an actual partial sale.
- Final focused installed preview suite: **22 passed in 20.21s**, including native
  entry plus non-order management charges after a scale, unknown/unallocated costs,
  CALL/PUT stages, exact fees, original weighted basis, tick tiers, incomplete orders,
  altered schedules, independent owners and detached read-only copies.
- Initial broader installed invocation stopped at collection because a shared test
  helper imports the `tests` package. The corrected isolated runner adds only the
  copied proof directory to its import path, not the checkout. No application or
  wheel change was needed; the collection log is retained.
- Installed floor preview, native position outcome, partial-close, target-exit,
  position-coordination and observer regression: **199 passed in 236.41s**, warnings
  treated as errors, outside the checkout against the non-editable installed wheel.
  Includes all 22 new cases and independent A/B/C/D native outcome/cost attribution.
- Two source/wheel/installed modules and copied regression bytes match. Scoped
  lint/format, dependency consistency, whitespace and 237 local documentation links
  pass.
- Wheel SHA-256: `982c74e7ec26f4927593b7a585455e326c6597f89d34260e5101b2452895fab1`.
  Artifacts/logs beside checkout: `trade-floor-env`, `trade-floor-dist`,
  `trade-floor-proof`, `trade-floor-source-tests.log`, `trade-floor-focused.log`,
  `trade-floor-installed-tests.log`, `trade-floor-collection.log` and
  `trade-floor-build.log`.

Automatic whole-trade floors still require frozen enrollment, fresh bid review,
persistent monotone protection and native dispatch/restart acceptance. Remaining
Scope entry/path/management integration, authentic provider/host evidence and the
dedicated UI pass remain open. Main untouched, PR draft, LIVE disabled and deployed
experiment frozen. No authentic provider/model/broker call, dependency, host unit
or deployment changed.

---

## P3/P7 target-managed open-boundary export: 2026-10-16 UTC

Reproduced a concrete native export blocker against the prior installed wheel:
a valid target touch saved `target_exit_stage=1` in the owner's ledger while the
fill-derived venue position retained stage zero. Export raised
`Native closing ownership mismatch` even though cash and holdings matched.
The same annotation also prevented portable fill replay from matching its close.

Native export and portable replay now exclude only target progress from their
existing management-annotation comparisons. The full saved position still exports,
including stage, tightened stop and premium peak. Frozen schedule terms, original
protection, completed entry premium basis and remaining FIFO lots remain exact.
Touched positions, partially filled scales and retained runners now retain their
cash, execution fees and allocated costs as inconclusive evidence. Open holdings
receive `OPEN_BOUNDARY_POSITION_UNVALUED`; working orders, missing cycles and unknown
costs remain explicit. No mark, net return, close or settlement is invented.
No execution, admission, account ownership or deployed policy changed.

Fresh GitHub baseline: `d8da42606e6796fd06ad05cc52caa7d83bf00e9d`, tree
`06dbc087114879e6d6a6ca18a3dec19cc0a0ff16`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Prior installed wheel: target-touch export regression **failed as expected**
  with `Native closing ownership mismatch` (**2.74s**).
- Fixed installed wheel: **11 passed in 9.30s**, covering CALL/PUT touches,
  partial scale fills, retained runners, stop/peak retention, exact fees, read-only
  export, unknown allocations and rejection of changed original terms.
- Installed native/portable evaluation/export, Arm D managed replay, multi-session
  continuity/settlement, target exits/stops and premium-trail regression: **220 passed
  in 629.33s**, warnings treated as errors, outside the checkout against the
  non-editable installed wheel. Includes all 11 new cases and independent A/B/C/D
  entry/management cost attribution.
- Both changed source/wheel/installed modules and the copied regression match.
  Scoped lint/format, dependency consistency, whitespace and 245 local documentation
  links pass.
- Wheel SHA-256: `06ac113b06997d1f7861c34583104c91a29bbed9660d3bf968afcddd9d36c109`.
  Artifacts/logs beside checkout: `target-export-env`, `target-export-dist`,
  `target-export-proof`, `target-export-before.log`, `target-export-focused.log`,
  `target-export-installed-tests.log` and `target-export-build.log`.

This is fixture verification of incomplete-boundary handling. The targeted fixtures
use native deterministic orders and intentionally sparse scheduler evidence; they
cannot establish a complete paired session or prospective economics. Authentic
provider/host evidence, remaining Scope integration and dedicated UI acceptance
remain open. Main untouched, PR draft, LIVE disabled and deployed experiment frozen.
No authentic provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 executable premium trailing protection: 2026-10-16 UTC

New PAPER owners can explicitly enroll `premium_trail="executable-premium-v1"`.
Entry approval, intent and stored decision inputs bind this frozen protection for
both deterministic and model-proposed buys. Dispatch rechecks enrollment and terms.
Only complete actual entry fills establish the original premium basis; incomplete
entries cannot seed peaks. The original quantity/basis remains fixed after partial
sales, independently of remaining FIFO lots and realized proceeds.

Fresh executable bid peaks drive the pinned source premium floors: 20% gain activates
97% of original premium; 35% activates 110%; 50% activates the greater of 125% and
entry premium plus 55% of peak gain. Exact original-quantity premium equivalents
avoid average-price division and threshold rounding. Missing, stale, crossed or
unbound bids cannot raise peaks or trigger floors. Existing mandatory protection
takes precedence; a fresh floor touch latches `PREMIUM_TRAIL`. Rebound cannot erase
it. Peaks/latches survive scales, reconciliation and restart; attempted orders keep
reservations. Native admission, full-premium risk, every fee and all entry/management
costs remain unchanged. No premium floor claims net profit or a guaranteed fill.

Stored attribution carries enrollment through exact close links. The observer shows
original basis/quantity, saved peak and a clearly labeled before-costs floor without
fresh evaluation. Native export and portable accounting ignore the changing peak
for economic comparisons while retaining policy, quantity and original basis.
Independent owners retain independent state and costs. Scope entry remains blocked.

Reference: SignalFlow `play_management.py` at
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Its midpoint/last fallback is not adopted.
Source whole-trade floors, health/Greek rules and Scope-specific management enrollment
remain separate; this shared primitive does not supply missing Scope entry/path proof.

Fresh GitHub baseline: `2a6b5dbab87fe2aa84a24162e2e7a88cd151a5f4`, tree
`f1708a7d732c9de6cd260d4c70b8dd80caf2f232`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused installed lifecycle suite: **28 passed in 11.26s**. An initial weighted
  entry fixture expected a 1.00 fill from a 1.00 ask despite native slippage/tick
  rounding; corrected the supplied ask to .99. Production fill rules were unchanged.
- Additional explicitly enrolled independent A/B/C/D native replay/export:
  **1 passed in 18.77s**, including Arm D entry and management cost attribution.
- Installed trail/target/partial-close/execution, entry/position coordination,
  observer and evaluation/export regression: **399 passed in 251.06s**, warnings
  treated as errors, outside the checkout against the non-editable installed wheel.
  Final review then added explicit portable entry/arm trail-policy binding.
- Final installed trail/evaluator run: **76 passed**, with one test incorrectly
  expecting the evaluator to throw instead of returning an inconclusive arm
  (**37.87s**). Corrected that report-contract assertion; its enrolled A/B/C/D
  replay and missing-policy case then **passed in 16.51s** without production changes.
  The final wheel differs from the broad regression only by the evaluator's
  two-line entry/arm enrollment guard; the other eight changed modules are identical.
- Nine source/wheel/installed modules and the final copied test file match.
  Scoped lint/format, dependency consistency, whitespace and 279 local doc links pass.
- Final wheel SHA-256: `6a8ed6d57461b75e7a905e6fdb0040c809ec0a788f6266bc9baa0708c8ddd5de`.
  Prior regression wheel: `511ffebd85c4896ecbe22f204ef157df38e58b989b56649cc1da35b44c3b83d2`.
  Artifacts/logs beside checkout: `premium-trail-env`, `premium-trail-dist`,
  `premium-trail-final-dist`, `premium-trail-proof`, `premium-trail-focused.log`,
  `premium-trail-replay.log`, `premium-trail-installed-tests.log`,
  `premium-trail-final-tests.log`, `premium-trail-binding-retry.log`.

[API, exact thresholds and boundaries](OPTIONS_PREMIUM_TRAIL.md). Scope still needs
its missing four-contract objective, native watch/entry binding, complete path proof,
family loss/reset and full management/runtime/replay acceptance. Authentic provider/host,
prospective economics and dedicated UI acceptance remain open. Main untouched, PR draft,
LIVE disabled and deployment frozen. No authentic provider/model/broker call,
dependency, host unit or deployment changed.

---

## P7 native target-triggered stop tightening: 2026-10-16 UTC

The next management gap was an effective stop that stayed unchanged after a target
touch unless another caller explicitly tightened it. New PAPER cohorts can now
enroll `target_stops="frozen-target-stops-v1"` alongside native target exits.
Each optional `TargetExitStep.tighten_underlying_to` freezes a particular stop
adjustment before entry. Prices must strictly tighten from original invalidation
and preceding specified stops, remaining behind their own directional target.
Preparation and dispatch enforce enrollment and immutable schedule binding.

Fresh supervision applies reached stop levels without weakening a stricter existing
stop. Gaps use every reached step. If underlying target progress latched during an
unavailable option quote, fresh recovery applies the stop and checks the current
rebound in the same assessment. A boundary touch latches ordinary underlying
invalidation. Mandatory exits keep precedence; attempted orders stay reserved.
Partial entries retain protection without resized allocations. Stage, effective
stop and exit latch persist atomically across partial fills, reconciliation and
restart. Stored schedules and supervision expose their terms without evaluating
on read. All premiums, fees, entry/management charges and independent balances remain
unchanged; an underlying entry-price stop is not option breakeven.

Source precedent: pinned SignalFlow `play_management.target_stop_price()` at
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Prices remain explicit; no native stage
is silently relabeled Scope T1/T2 and no research reference substitutes for actual
entry. Scope management previews continue to omit these fields. The missing
four-contract objective, native watch/entry binding, full path proof, family loss/reset,
premium trails and full Scope management/runtime/replay acceptance remain open.

Fresh GitHub baseline: `591a15efb47548d354a71e78b559e2618b6d1279`, tree
`21c923e03c249314830ad6dcc96aacc6410b1b7a`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Initial installed target-stop suite: **24 passed in 12.17s**. Five further cases
  cover exact boundaries, optional steps, dispatch enrollment and mandatory-exit
  priority in the broader run.
- Installed target-stop, target-exit, premium-protection, partial-close, execution,
  position-coordination/outcome, observer and Scope-management/entry-boundary suites:
  **341 passed in 265.76s**, warnings treated as errors, outside the checkout against
  the non-editable installed wheel. Includes all 29 new cases and independent A/B/C/D
  native replay with full entry/management cost attribution.
- Three source/wheel/installed modules and the copied target-stop test file match.
  Scoped lint/format, dependency consistency, whitespace and 269 local documentation
  links pass.
- Wheel SHA-256: `f58cb9c179ada4248f2fc506198a86e3443db2e92172796b027aeb7ea8dc93eb`.
  Artifacts/logs beside checkout: `target-stops-env`, `target-stops-dist`,
  `target-stops-proof`, `target-stops-focused.log`, `target-stops-installed-tests.log`.

[API and boundaries](OPTIONS_TARGET_EXITS.md#optional-frozen-target-stops).
Authentic provider/host, prospective economics and dedicated UI acceptance remain
separate. Main untouched, PR draft, LIVE disabled and deployed experiment frozen.
No authentic provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 Scope allocation previews and entry premium protection: 2026-10-16 UTC

Fresh source review recovered Scope's actual shared sizing rule: the pinned
orchestrator explicitly selects balanced scaling, independently of contract profile.
A new frozen optional `ScopeManagementPolicy` now derives plans from successful
owned admission, current eligible contract observations and original locked geometry.
One contract exits at T2; two allocate one to T1 and one runner; three allocate one
to each objective and one runner. The source four-contract allocation additionally
requires T3, which current approved Scope geometry does not define. Its preview
retains the distinct T3 and runner quantities, returns
`SCOPE_THIRD_TARGET_UNSPECIFIED`, and emits no native schedule.

The source emits `scope_t1`/`scope_t2` candidates, but its generic target selector
accepts neither method and can replace them with fixed-R targets. That fallback is
not adopted. No invented objective, silent reallocation or reduction from four to
three is introduced. Account admission eligibility remains distinct from management
plan readiness, and every plan retains `native_execution_ready=false`.

Source premium-stop estimates (.35 Responsive/.45 Balanced/.60 Convexity) are
recorded separately from explicitly enrolled premium limits. Proposed protection
uses the tighter profile/owner fraction. Convexity remains blocked by its existing
full-path gate. A new native `entry_premium_protection="tighten-only-v1"` enrollment
allows trusted deterministic buys to freeze a tighter premium catastrophe fraction.
Preparation and dispatch reject widened or mismatched terms. Fills, scales, remaining
FIFO basis, restart and close attribution retain the exact original entry protection.
Fresh executable bid triggers the existing mandatory latch; stale/missing bids,
working/unknown orders, underlying stops and time/expiry precedence remain unchanged.
Full-premium admission/reserves and all execution/model charges are not discounted.

Management previews are stored in the existing atomic admission receipt. The observer
checks policy, geometry, quantity, admission identity/times and owner risk limit,
retaining stale labels without fresh evaluation. Missing/inconsistent enrolled plans
become unavailable. Old cohorts omit the optional fields and cannot migrate on reopen.
Scope's generic native entry guard still rejects the generated schedule/protection.

Fresh GitHub baseline: `f0ad9f08fd9ec8865b3b042c1578b2ddd04d46d2`, tree
`59e6f561a4004b84702ac7181f06eac4e5f06652`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.
Reference: SignalFlow `f9eaf2c1b5d13dca287ee7138126883065b00395`,
`play_orchestration.py`, `play_sizing.py`, `scope_wizard.py` and the pinned V2 playbook.

Validation:

- Source entry-premium, Scope management, owned-admission and observer suites:
  **104 passed in 35.94s**. Initial fixture failures reflected JSON-versus-typed
  timestamp hashing, supplied ask-size limits and price-driven profile classification;
  corrected fixtures now exercise the intended cases through the actual gates.
  An additional missing-plan observer case was added for the installed run.
- Installed entry-premium, all Scope, target/partial-close, native execution,
  closing/entry lineage, entry/position coordination, outcome and observer suites:
  **940 passed in 320.59s**, with warnings treated as errors, outside the checkout
  against the non-editable installed wheel.
- New cases cover both directions/profiles, one-through-four-contract allocations,
  exact executable premium boundaries, actual FIFO basis, stricter owner/profile
  caps, full-premium reserves, target/protection races, runner restart, all fees,
  independent owners, frozen enrollment, stale inputs, changed stored terms,
  retry/rollback and explicit Scope entry rejection. Partial-close regressions retain
  known/unknown entry and management charges in complete/incomplete outcomes.
- Nine modules match source/wheel/installed files; three changed tests match copied
  proof files. Scoped lint/format, dependency consistency, whitespace and local
  documentation links pass.
- Wheel SHA-256: `66194355bdfa4e0aef9cacd6c55d7f6efef5dca491873af5549d0316dd99fda4`.
  Artifacts/logs beside checkout: `scope-management-env`, `scope-management-dist`,
  `scope-management-proof`, `scope-management-source.log`,
  `scope-management-installed-tests.log`.

[API, source discrepancy and boundaries](OPTIONS_SCOPE_MANAGEMENT.md). Scope still
requires reviewed four-contract allocation, watch/entry linkage, complete obstruction
coverage, Scope family loss/reset, full management/runtime/replay acceptance. Authentic
provider/calendar/host, prospective economics and UI acceptance remain separate.
Main untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 frozen native target exits: 2026-10-16 UTC

New PAPER cohorts can enroll `target_exits="frozen-targets-v1"` alongside the
whole-contract close policy. Trusted deterministic software freezes one-to-three
ordered target prices and exact whole-contract allocations before entry. The
schedule must match the common governor's approved quantity; it cannot enlarge
admission or be attached to the existing AI single-target entry-plan path.
Dispatch rejects changed schedules or already-consumed first objectives.

Independent supervision latches fresh directional target observations. The normal
protective tick then requests cumulative scheduled quantities minus verified sales
linked to the exact entry. A gap across targets aggregates due quantities; bid size
caps each actual order, and only verified fills retire an allocation. Unallocated
contracts remain protected runners. Restart preserves both target progress and
prepared order identity. Mandatory stops, catastrophe and deadlines retain priority;
attempted/unknown orders retain reservations and attempted failures require review.
A terminal partial entry is not silently resized into a different allocation.

Native accounting preserves every order fee, FIFO basis, unsettled proceeds and
entry/management charge. Stored attribution exposes entry schedules and exit stages
separately from requested, approved and filled quantities. Target touches make no
claim about premium profitability. Independent owners retain separate progress and
cash. Scope entry remains blocked, including for cohorts with this shared primitive.

Reference check: SignalFlow at `f9eaf2c1b5d13dca287ee7138126883065b00395`, pinned
Scope V2 playbook, `play_sizing.py`, `play_management.py`, `premium_scaling.py` and
Scope modules. Scope contract profiles and shared sizing profiles are distinct;
this slice does not invent a mapping or adopt Degen's separate premium ladder.
Scope profile/allocation selection and profile-specific premium protection remain
open alongside watch linkage, complete path proof, family loss/reset and runtime/replay.

Fresh GitHub baseline: `9f5534eedbd5e129c1b8f51ddd586ed650d90fba`, tree
`1679a7a160c494fbd7f8d6eb651a889eb46b66b8`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Source target-exit/partial-close suites: **70 passed in 45.53s**. A three-target
  gap case was subsequently added for the installed run. The initial run exposed
  a fixture incorrectly reusing consumed quote size; supplying distinct fresh sized
  quotes fixed that fixture without weakening fill validation.
- Installed target/partial exits, native execution, close/entry lineage, entry and
  position coordination, family/account loss, Scope boundary/admission, position
  outcomes and managed A/B/C/D replay suites: **339 passed in 554.92s (0:09:14)**,
  with warnings treated as errors.
- Cases cover both directions, one-to-four-contract full exits, scales/runners,
  two/three-target gaps, executable-size limits, all execution fees, attribution,
  independent accounts, restart/rebound, rollback, stop races, unknown/failed orders,
  partial-entry review, frozen enrollment, changed terms and consumed objectives.
  Existing partial-close regression covers every entry/management charge, unknown
  management usage and completed-loss recognition.
- Six modules match source/wheel/installed files; copied target tests match source.
  Scoped lint/format, dependency consistency, whitespace and local documentation
  link validation pass.
- Wheel SHA-256: `c79b298aee8f910d84808e198acfb069750dbe8a7a0eeed9e40871cf2af55202`.
  Artifacts/logs beside checkout: `target-exits-env`, `target-exits-dist`,
  `target-exits-proof`, `target-exits-source.log`, `target-exits-installed-tests.log`.

[API, exact semantics and remaining gates](OPTIONS_TARGET_EXITS.md). Authentic
provider/calendar/host and prospective economics, overnight Swing/mixed instruments,
and the dedicated desktop/mobile UI pass remain open. Main untouched, PR draft,
LIVE disabled and deployed experiment frozen. No authentic provider/model/broker
call, dependency, host unit or deployment changed.

---

## P7 native scale/runner execution primitive: 2026-10-16 UTC

The common engine now supports explicitly bounded whole-contract closes for a
new frozen PAPER cohort enrolled with `partial_closes="whole-contract-v1"`.
`OptionProposal.close_quantity` is CLOSE-only and a strict positive integer.
The common governor caps it by exact ownership and executable bid size, rejecting
requests above ownership. The original requested ceiling and actual approved order
quantity persist separately; dispatch cannot enlarge the fixed order or accept
changed proposal/approval terms. Existing cohorts and omitted-field serialization
remain unchanged. Only deterministic local orchestration may use this API.

Fresh protection checks at preparation and dispatch prevent a planned scale from
retaining contracts after a required full exit. Stops, premium catastrophe,
entry targets and deadlines retain the common latched protection. The independent
protective tick can supersede only a never-attempted prepared scale for that same
entry, recording its local rejection before a full protective close. Attempted,
working and unknown orders keep their reservation and reconciliation requirements;
no venue cancellation, replay or inferred fill is introduced.

Scale and runner fills use the same FIFO accounting, exact entry attribution and
per-order/per-contract fees. Remaining ownership retains original/tightened stops
and target/horizon protection. Partial sales do not complete a position outcome or
consume a completed loss. Entry and management charges survive all exits, including
advice without an order; missing management usage withholds the final net outcome.
This supplies a necessary shared execution primitive for Scope, not automatic
Scope target allocation or watch-to-order enrollment.

Fresh GitHub baseline: `da1b726ae3b9836b6ee81c1fdf3b69cf85de7462`, tree
`85ac72d6b62bc2659ee091719fb222c1e2a170ee`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Source partial-close/admission/closing-link suites: **231 passed in 21.70s**.
  A final stored-proposal corruption case was added afterward and passes in the
  installed run below. Initial fixture expectations were corrected for the actual
  MAINTAIN status and immutable-configuration exception. An initial mixed-source
  smoke run used the previous installed worker and rejected the new intent schema;
  the subsequent matching wheel/native worker passes the real lifecycle tests.
- Installed partial-close, admission, execution, close/entry lineage, entry and
  position coordination, family/account loss and Scope boundary/admission suites:
  **443 passed in 158.28s (0:02:38)**, with warnings treated as errors.
- New cases cover both directions and 1/2/3-contract scales, final runners, actual
  fees, remaining exit reserves, settled cash, exact caps, strict counts, frozen
  reopen, source retries, restart, protection at prepare/dispatch, local supersession,
  attempted-order precedence, changed attribution and atomic rollback. The actual
  fixture AI coordinator retains entry plus management charges through both exits;
  missing usage stays unknown and prevents loss consumption.
- Five changed modules match source/wheel/installed files; copied changed tests
  match source. Scoped lint/format, dependency consistency, whitespace and 262 local
  documentation links pass.
- Wheel SHA-256: `707497126364702eb711b678f9292ec02b7af1c613cc68041d8280ac0d481ed3`.
  Artifacts/logs beside checkout: `partial-close-env`, `partial-close-dist`,
  `partial-close-proof`, `partial-close-source-final.log`,
  `partial-close-installed-tests.log`.

[API and boundaries](OPTIONS_PARTIAL_CLOSE.md). Scope full-path coverage, frozen
watch/order/family-loss linkage, profile/quantity-specific target allocation,
management/runtime/replay, authentic provider/calendar/host acceptance and the
UI desktop/mobile pass remain open. Native Scope entry remains blocked. Main
untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 Scope current-price admission geometry: 2026-10-16 UTC

Reproduced a concrete Scope admission defect in both directions: the original
1.5R setup could still receive `eligible=true` at a quote only one cent before
its first objective. The current-price check only rejected a consumed objective;
quality R and known levels still used the original reference/completed close.

Fresh owned admission now requires remaining first-target reward to meet the
frozen minimum R against the locked stop, using CALL ask or PUT bid after the
common governor validates current evidence/account constraints. Exact Decimal
products decide the gate; rounded display ratios do not. The same known-level
classifier reruns from that current reference through the original second target,
including opt-in structural levels. A retreat can expose levels previously behind
the completed close. Failure records a zero-quantity rejection and resets arming.

Stored `entry_path` retains original geometry, current reference, threshold,
displayed R, levels and reasons; the observer reads it without recomputation.
Historical receipts remain historical, retry/restart behavior is preserved, and
fresh reviews tighten the existing rule without changing frozen policy values.
The common governor still owns sizing, all fees/slippage and account limits.
Underlying structural R is not estimated option return or all-in economics.
No watch call, order, reservation or paid model request is added by this review.

Fresh GitHub baseline: `177b5ee0b097033a5a7560f337926d3630455fd9`, tree
`b855d5168a80c54c7bea0415071ace66dc3a7653`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Baseline reproduction accepted CALL 101.49 against stop 100/first target 101.50
  and PUT 98.51 against stop 100/first target 98.50. Both now reject.
- Source current-path/owned-admission/structural-path suites: **65 passed in 21.33s**.
- Installed complete Scope and native execution suites: **645 passed in 77.13s**,
  warnings treated as errors. New cases cover both directions, exact R boundaries,
  adverse spread side, current-price prior/structural obstructions, fixed geometry,
  common-governor fee totals, stale/wrong-source handling, observer visibility,
  retry/restart, independent owners and ambient arithmetic precision.
- Four changed modules match source/wheel/installed files; copied changed tests
  match source. Scoped lint/format, dependency consistency, whitespace and local
  documentation links pass.
- Wheel SHA-256: `99e662d41685b7718a67e5c3b9c9a93574845763392cc51cfd513e8cb086d42a`.
  Artifacts/logs beside checkout: `scope-entry-env`, `scope-entry-dist`,
  `scope-entry-proof`, `scope-entry-source.log`, `scope-entry-installed-tests.log`.

Complete obstruction coverage and native Scope watch/order/family-loss linkage,
management/runtime/replay, authentic provider/calendar/host acceptance and the
UI desktop/mobile visual pass remain open. `complete_path_proven` stays false;
convexity and native Scope execution remain blocked. Main untouched, PR draft,
LIVE disabled and deployed experiment frozen. No authentic provider/model/broker
call, dependency, host unit or deployment changed.

---

## P7 native loss evidence in session replay/export: 2026-10-16 UTC

Enrolled A/B/C/D owners now refresh loss controls after final session reconciliation
and before saving each independent boundary. A final completed trade is recognized
even without another entry cycle. Streaks, recognition-time cooldowns and sticky
account/family locks persist into the next session; no automatic reset is issued.
Pending outcomes and unknown costs remain pending. Cash, settlements and every
entry/management charge retain their existing independent accounting.

`ArmSession.loss_control` now records the frozen policy hash, last stored risk
state, cumulative consumed-entry economic hashes and exact family lineage,
recognition times, entry-model pauses and applied reset summaries. Native export
recomputes consumed economics from current verified fills/settlements/costs and
checks state, consumption and reset audit/receipt consistency. Completed model
pauses must match their HOLD receipt without a charged call. Read-only export does
not refresh risk or attach owner authority. Historical unenrolled rows omit the field.

The portable evaluator checks enrollment, policy/family shape, time bounds and
cumulative history continuity, and shows `stored_loss_control` beside full session
economics. A valid lock remains a valid accounting outcome; missing enrolled risk
evidence makes the arm inconclusive. These are stored-evidence checks, not independent
signature verification, replay of every historical risk decision or an external
witness against coordinated database/audit rewriting. Data/host costs stay separate;
this operational loss basis is not all-in return or profitability acceptance.

Fresh GitHub baseline: `ab1dc3c5c24f4561575b151bc95e66061079a117`, tree
`44568f6449e45443e1a48cf3fcf7b349fbfcbbc4`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Source loss/family/evaluator regressions: **87 passed in 33.64s**.
- New source evidence and two-session shared A/B/C/D replay cases:
  **14 passed in 265.32s**. The replay checks overnight lock persistence,
  independent entries/cash, retained D entry/management charges, unpaid later
  pauses, exact saved state and portable history rejection. Direct native cases
  cover stale/missing/changed risk evidence, family counts, reset receipts and
  read-only behavior. Two additional saved-boundary cases check pause-completion
  linkage and rejection when a consumed management charge becomes unknown.
  All three saved-boundary checks (including exact final recognition time) pass
  against the completed installed replay without rerunning the simulation.
- Installed loss/evidence/evaluator/export/multi-session/managed/comparison suites:
  **204 passed in 834.17s**, with warnings treated as errors. The two added
  corruption cases and final-recognition assertion also pass against that run
  through the saved-boundary checks above; the final copied test file matches source.
- Source/wheel/installed changed modules match. Scoped lint/format, dependency
  consistency, whitespace and 429 local documentation links pass.
- Wheel SHA-256: `88c2f32662f6ef43c06d3168669edea26e30baf61d73e54431549378e312f1d9`.
  Artifacts/logs beside checkout: `loss-export-env`, `loss-export-dist`,
  `loss-export-proof`, `loss-export-source.log`, `loss-export-new-source.log`,
  `loss-export-installed-tests.log`, `loss-export-saved-boundary-tests.log`.

Scope full-path proof and native watch/order/family-loss linkage, Scope management/
runtime/replay, authentic provider/calendar/host acceptance and the dedicated
UI desktop/mobile visual pass remain open. Main untouched, PR draft, LIVE disabled
and deployed experiment frozen. No authentic provider/model/broker call, dependency,
host unit or deployment changed.

---

## P7 independent Degen/Swing loss controls: 2026-10-16 UTC

New native PAPER cohorts can optionally freeze separate Degen/Swing loss thresholds
and recognition-time cooldowns in addition to the account-wide guard. Complete
outcomes retain exact selected-entry lineage and every attributable entry/management
charge and execution fee. A win in one family cannot clear another family's streak;
locks persist across cooldown expiry and restart. Accounts retain independent state.
Unknown usage still blocks outcome consumption; data/host costs remain session-level.

Preparation and dispatch enforce both account-wide and selected-family pauses.
Family-enrolled cohorts reject unlabeled entries. Paid entry admission pauses before
creating a call when all stored candidate families are paused, or valid candidates
are absent. Mixed packets may proceed unchanged, but a paused selected family still
fails preparation and its call cost remains recorded. Validated owned management,
ordinary closes and independent protection retain their existing gates and charges.

The signed local `RESET_LOSS_LOCK` envelope/CLI now accepts an optional DEGEN/SWING
target. Exact revision, fresh flat account, known costs, remaining budgets, idle
runtime, verified history and expired target cooldown are required. Only the target
streak/lock clears; account-wide/other-family locks and all economic history survive.
Omitting the target preserves the existing account-wide reset and leaves family
locks intact. Signature binding, audit/receipt atomicity and read-only replay remain.
Existing frozen cohorts retain omitted-field serialization and cannot be migrated.
Scope family enrollment/reset and executable watch/order linkage remain open.

Fresh GitHub baseline: `82c6df2e6b3973174ad0712dae0f667628b0f6bd`, tree
`f7452420055f72c66c8045f777e54988fb9a988d`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- 23 new source cases pass: independent streaks, cross-family wins, global/family
  reset isolation, separate accounts, signed CLI/inbox delivery, tampering,
  stale/cooldown rejection, replay, atomic rollback, dispatch recheck, model pauses,
  mixed packets, malformed candidates, frozen reopen and full-cost management.
  Seeded candidate fixtures test native risk/lineage, not new Swing setup acceptance;
  the management cases also exercise the real coordinator with a fixture model.
- One initial fixture exhausted settled cash after repeated large entries; reducing
  its proposed debit preserved settlement rules and isolated the intended check.
- Installed family/loss/operator/lineage/management/observer/Scope-boundary suites:
  **229 passed in 127.69s**, with warnings treated as errors. An initial isolated
  collection used the tests directory instead of its parent on the import path;
  the corrected run loads the copied fixtures and matching installed package.
- Source/wheel/installed changed modules and copied new tests match. Scoped
  lint/format, dependency consistency, whitespace and 426 local documentation links pass.
- Wheel SHA-256: `951f9d4fef7f97a42ddc69f9033ff752e810758c5ab69ca9aef0bf5d6b999227`.
  Artifacts/logs beside checkout: `family-loss-env`, `family-loss-dist`,
  `family-loss-proof`, `family-loss-new-source2.log`, `family-loss-installed-tests2.log`.

Full Scope path proof, native watch/order linkage, Scope family loss/reset,
management and runtime/replay remain open, alongside authentic provider/calendar/
host acceptance and the dedicated dashboard/desktop/mobile visual pass. Main
untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 native strategy entry lineage: 2026-10-16 UTC

New native buys from stored selected opportunities now freeze the strategy family,
setup, opportunity key, selected candidate ID and full candidate hash in both intent
and approval. The owner derives this identity inside preparation. Dispatch verifies
both copies and the original selected candidate before any attempt; changed,
missing, duplicate or conflicting evidence rejects the order and releases its lock.
Labels cannot be supplied through the proposal or inferred from a contract/thesis.

Exact ordinary/protective/model close attribution inherits the buy's identity.
Position outcomes and paid management advice, including MAINTAIN/TIGHTEN without
an order, carry the same verified link and retain all entry/management charges and
execution fees. Unknown/unallocated costs continue to suppress net outcomes;
data/host costs remain session-level evidence. Independent accounts remain separate.

Historical unlabeled intents and attribution omit the optional field and are not
backfilled. Direct native orders with no stored selected opportunity remain
unlabeled. Scope cannot be claimed through the Degen/Swing lineage contract, and its
existing research-only preparation/dispatch guard remains enforced. This completes
a prerequisite for exact family loss attribution; it does not enable family loss
reset, Scope orders, new strategy enrollment or a deployment.

Fresh GitHub baseline: `aa3d6564ec1572cc7e7020ed401310b90fff40fa`, tree
`48ada20f9936dbb7453814604860efba5bbc7c80`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- 24 new cases cover Degen/Swing, CALL/PUT, deterministic/model selection, exact
  closes, management charges, dispatch tampering, stored-history tampering and
  historical omission. A source run initially used the prior installed isolated
  worker, which could not decode the new intent; owner/worker now use the same
  built release. A new hash test also compared different Python/JSON representations;
  its corrected assertion checks identical prior fields and unchanged JSON encoding.
- Installed replay/execution/attribution/management/loss/observer suites:
  **352 passed in 792.94s**, with warnings treated as errors.
- Installed Scope execution-boundary suite: **8 passed in 3.58s**.
- Source/wheel/installed changed modules and copied new tests match. Scoped
  lint/format, dependency consistency, whitespace and 426 local documentation links pass.
- Wheel SHA-256: `ec4a5a244b792acfc8973a0068c4c4fc350670834239d3b0729b341416705be2`.
  Artifacts/logs beside checkout: `entry-lineage-env`, `entry-lineage-dist`,
  `entry-lineage-proof`, `entry-lineage-source*.log`, `entry-lineage-installed-tests.log`,
  `entry-lineage-scope-boundary.log`.

Full Scope path proof, native watch/order linkage, family loss/reset, management and
runtime/replay remain open, alongside authentic provider/calendar/host acceptance
and the dedicated dashboard/desktop/mobile visual pass. Main untouched, PR draft,
LIVE disabled and deployed experiment frozen. No authentic provider/model/broker
call, dependency, host unit or deployment changed.

---

## P7 stored Scope research observer: 2026-10-16 UTC

The options observer now exposes enrolled Scope research watches instead of labeling
Scope unimplemented. The authenticated API and HTML show stored call state, exact
contract/geometry, arming samples and fee-inclusive admission results. Research
records remain separate from native opportunities, positions, orders and fills.
Independent account ownership and existing entry/management cost reporting remain
unchanged; no review becomes an executable approval.

The latest 25 watches have explicit total/truncation metadata. The active record is
retrieved separately, independent of opportunity filters and pagination. Recorded
status/eligibility stay historical while separate time labels identify future
records, passage of the entry cutoff and expired arming/admission validity. Reads
never expire/reset watches, refresh evidence, run scanners or open an execution
owner. Malformed/boundedness failures and conflicting selected identities fail
closed. This projection is not a full action-history audit or fresh path review.

Fresh GitHub baseline: `e86eafe342c4d9cb8cbaefd3a1cd1ab5f9d18674`, tree
`4bfb4c1077616cfb3327e55d930cff7cbbb5a04a`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Source Scope-observer and existing observer suites: **73 passed in 10.17s**,
  including 20 new cases for enrollment, CALL/PUT sizing, expired/future records,
  history bounds, immutable reads, malformed evidence and authenticated HTML/API.
  Initial run exposed string timestamps being passed to the datetime-only engine
  clock. The projection now explicitly decodes and validates stored timestamps;
  numeric, missing and timezone-naive timestamps return unavailable.
- Non-editable installed wheel, all Scope suites plus common admission and existing
  observer suites, warnings treated as errors: **801 passed in 40.12s**.
- Source/wheel/installed modules and HTML template match; changed copied tests match.
  Scoped lint/format, dependency consistency, whitespace and 425 local documentation
  links pass. Desktop/mobile browser visual acceptance remains open.
- Wheel SHA-256: `0d090d51cfbf303c55617752e0901c47b2b5c87639930e880b6b68fbf7c7537b`.
  Artifacts/logs beside checkout: `scope-observer-env`, `scope-observer-dist`,
  `scope-observer-proof`, `scope-observer-source*.log`, `scope-observer-installed-tests.log`.

Full path proof, native Scope watch/order and family-loss linkage, family reset,
management/runtime/replay and authentic provider/calendar/host acceptance remain
open. Main untouched, PR draft, LIVE disabled and deployed experiment frozen.
No authentic provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 completed SPX structural path checks: 2026-10-15 UTC

New frozen Scope quality policies can opt into `completed-spx-levels-v1`.
The review derives opening-range high/low, strictly confirmed three-bar pivots
and exact volume-weighted typical price from validated completed SPX history.
Each level records when it became knowable. Both directions retain inclusive
path endpoints, repeated evidence and levels through the second objective;
a level through the first objective blocks quality and cannot consume a watch call.
Exact rational VWAP comparisons precede display rounding. Scores are unchanged.

Omitted policy fields preserve historical serialization and hashes. Existing watch
cohorts cannot adopt the new policy on reopen. Complete path proof remains false:
other horizons, overnight levels, plateau/zone interpretation and authentic coverage
remain open. Convexity and native Scope execution remain blocked. Independent
account ownership and all entry/management cost accounting are unchanged.

Fresh GitHub baseline: `4ec5b6d8246b6c25d625fe10ccb0acd845616768`, tree
`8950b91ad1e6542232c00ef221247994d8780347`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused new source suite: **26 passed in 2.03s**. Covers CALL/PUT boundaries,
  pivot confirmation, missing/forming/changed/zero-volume history, exact VWAP,
  ambient precision, frozen policies, stored evidence and atomic watch rejection.
  Initial failures exposed test fixtures using the wrong stored field and default
  watch pattern; corrected fixtures without relaxing application gates.
- Non-editable installed wheel, all Scope suites plus common option admission,
  warnings treated as errors: **728 passed in 31.62s**.
- Source/wheel/installed module and copied new tests match. Scoped lint/format,
  dependency consistency and whitespace checks pass.
- Wheel SHA-256: `5e8c85e1fb14d8b29e7bf390b1de5b4e29ee9ef475fb1400191785b606b19f59`.
  Artifacts/logs beside checkout: `scope-path-env`, `scope-path-dist`,
  `scope-path-proof`, `scope-path-source*.log`, `scope-path-installed-tests.log`.

Main untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 approved Scope price-based quantity ceilings: 2026-10-14 UTC

Fresh Scope owned-admission reviews now enforce the approved V2 executable-ask
quantity tiers: at most four contracts through $1.25, three through $1.65, two
through $2.50 and one through $5.00, with the $0.20 floor. Exact Decimal comparison
preserves inclusive boundaries without display rounding. This closes a missing
playbook constraint before native order linkage; it does not authorize Scope orders.

The pinned SignalFlow playbook at `f9eaf2c1b5d13dca287ee7138126883065b00395` was
freshly read and its settled tiers retained. The smaller of the tier cap and the
owner's `max_contracts` is passed into the existing governor. No separate quantity
formula bypasses slippage, tick rounding, all entry/exit fees, ask size, settled
cash or daily/total/full-premium limits. Fees may reduce a tier's maximum quantity,
including to zero; they are never dropped to fit the $500 debit cap.

Stored evidence adds current ask, tier version and maximum quantity beside original
and effective limits. Each fresh review recalculates the tier. Historical action
receipts remain historical and do not overwrite current sizing. Earlier receipts
are not rewritten or promoted to authority. Frozen enrollment is unchanged;
independent owners retain their own stricter risk limits. Full path proof, Scope
watch/order linkage, family loss attribution/reset, management/runtime/replay and
authentic provider/calendar/host acceptance remain open.

Fresh GitHub baseline: `b800d9d73e5a86ee538f889e8d74607d7979ff05`, tree
`2542c480a550b05013eb2cf64acc36809f854517`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Focused source suites: **59 passed in 20.96s**, including 37 new tests for exact
  boundaries, invalid values, CALL/PUT sizing, costs, stricter owner limits and
  fresh repricing versus historical retries. Initial run: 56 passed and two
  test-string mismatches (`.20` versus canonical Decimal `0.20`); the expected
  evidence now uses Decimal serialization. No application gate was relaxed.
- Non-editable installed wheel, all Scope suites plus common option admission
  with warnings treated as errors: **702 passed in 28.42s**.
- Source/wheel/installed changed modules and copied new tests match. Scoped
  lint/format, dependency consistency, whitespace and 423 local documentation links pass.
- Wheel SHA-256: `84abf9259d4829de04eb5aae7b9ecf110531e86145375f795cc7f7ad4710a264`.
  Artifacts/logs beside checkout: `scope-tier-env`, `scope-tier-dist`,
  `scope-tier-proof`, `scope-tier-source*.log`, `scope-tier-installed-tests.log`.

Main untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 native loss guard before paid entry reasoning: 2026-10-14 UTC

Closed a common cost-control integration gap: an explicitly enrolled loss-guard
population could previously pay for entry reasoning before preparation rejected
the resulting trade. Entry `begin_model_attempt` now refreshes native loss state
before recording an attempt or starting a model worker. Recognition-time cooldown,
consumed outcomes and source/input-bound pause audit commit atomically. Expected
loss/cooldown/incomplete-outcome pauses create no unknown-cost row or model charge.

The coordinator completes these expected pauses as HOLD with the specific blocker,
without adding a global halt that would prevent cooldown expiry from allowing a
future cycle. Historical cycle retry returns its stored result without another
model attempt or risk event. Corrupt/changed evidence still follows the existing
failure path. Both candidate selection and full-entry reasoning use the common gate.

Owned-position requests retain their existing strict binding, revision, account and
cost admission, so pending entry outcomes do not disable MAINTAIN or EXIT_ALL.
All admitted entry/management charges remain recorded. Existing model-admission
checks were moved unchanged into a helper; unenrolled cohorts retain their behavior.
This does not cancel or refund in-flight calls, skip data/host work, change independent
accounts, or replace the final preparation/dispatch gates. Scope watch/order linkage,
family-specific loss handling and complete path proof remain open; Scope remains
research-only.

Fresh GitHub baseline: `4f9f5547fbfaa178fb0296e7604c7e2ebbba66ce`, tree
`04b863c43e99811cb28946702ad6d58f3866741b`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Final focused source suite: **8 passed in 7.80s**. The coordinator fixture first
  attempted a manual entry rejected by its full-plan policy, then incorrectly
  required byte-identical historical replay despite the existing fenced write
  transaction. It now exercises an actual paid fixture entry/close and verifies
  unchanged event revision, model count, economic state and risk state on replay.
  No application gate was relaxed.
- Non-editable installed wheel, nine related suites with warnings treated as
  errors: **253 passed in 162.68s**. Coverage includes the new cost gate, native
  loss/reset, execution, full-entry and position coordination, signed recovery,
  runtime and the independent Scope execution boundary.
- Source/wheel/installed application bytes and copied new tests match; the extracted
  admission helper's AST exactly matches the former transaction body. Scoped
  lint/format, dependency consistency, whitespace and 423 local documentation links pass.
- Wheel SHA-256: `d2f50be62a370e203426168a242f9d38b8b60bf0e0aaddadb892184e189b6854`.
  Artifacts/logs beside checkout: `loss-model-env`, `loss-model-dist`,
  `loss-model-proof`, `loss-model-source*.log`, `loss-model-installed-tests.log`.

Main untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 reviewed native loss-lock reset: 2026-10-14 UTC

The existing signed local operator protocol now accepts `RESET_LOSS_LOCK` for
explicitly enrolled native PAPER loss-control populations. The saved review and
stored observer include loss state without refreshing risk. Only the current
owner applies a signed command, with exact reviewed revision, binding, lifetime
and authenticated replay checks. An active model/runtime task blocks recovery.

Reset requires a persisted lock, elapsed cooldown, fresh matching flat account and
supervision, no working order, known costs and positive remaining daily/total loss
budgets. Native outcomes are revalidated; incomplete/changed evidence cannot clear
the lock. Newly consumed outcomes require another explicit review. Reset clears
only the account-wide lock/streak and retains consumed history, cooldown timestamp,
all entry/management costs, ledger/P&L, frozen limits and any separate global halt.
State, prior/new-state audit and command receipt are atomic. Same-command replay
does not reset again or erase later risk. A later loss starts a new streak.

This is common account recovery, not Scope family-scoped reset. Scope watch/order
linkage, family loss attribution/reset, complete path proof and Scope runtime/replay
remain open. The model has no operator capability. No order is authorized by the
reset, and no existing cohort is migrated.

Fresh GitHub baseline: `38dacee2952be0d4ce986ae8aacb7676035f49c0`, tree
`06007098e47b34de076669435521575956b3c0bd`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Initial new source suite: 10 passed, three test-fixture failures (nonexistent
  public halt helper and a backward fixture snapshot). Fixtures now use signed HALT
  and monotonic snapshots; no application gate was relaxed. Corrected suite:
  **13 passed in 8.20s**, then expanded with three additional evidence/isolation cases.
- Non-editable installed wheel, six related suites with warnings treated as
  errors: **180 passed in 81.84s**, including all 16 new reset cases, native loss
  control, signed operator recovery, observer, runtime and Scope execution boundary.
- The initial installed attempt stopped at collection because pip reused the
  shared dependency directory's older same-version application. Installing the
  wheel explicitly into the isolated environment fixed the test harness; the
  five changed application modules now match source, wheel and installed bytes,
  and the copied reset tests match source. No dependency version changed.
- Scoped lint/format, dependency consistency, whitespace and 423 local
  documentation links pass.
- Wheel SHA-256: `c03e9ee352144197d6be773d2ec45cfa6bd3d8eb48f166e4a77c26b2d3ba131d`.
  Artifacts/logs beside checkout: `loss-reset-env`, `loss-reset-dist`,
  `loss-reset-proof`, `loss-reset-source.log`, `loss-reset-installed-tests.log`.

Main untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 common native loss cooldown and persistent lock: 2026-10-14 UTC

New explicitly frozen PAPER populations can enroll a common account-wide loss
control. It consumes verified native outcomes exactly once with execution fees
and all attributable entry/management charges, starts cooldown from actual loss
recognition, and persists threshold lock across restart and global resume. Entry
preparation and dispatch enforce the state before any order attempt. HOLD and
owned/protective exits remain available through their normal rules.

The policy retains the pinned Scope bounds as conservative research settings:
at most two consecutive losses, at least 30 minutes of cooldown. This is shared
owner infrastructure, not a Scope family enrollment or completed Scope integration.
Existing cohorts are not migrated. The operational net basis includes recorded
execution/model charges; data/host allocations remain in session economics.
Incomplete/unknown costs or outcome history block, not reset. Terminal unfilled
attempts do not erase losses; their costs remain in global account budgets.

Outcome/state/audit records are atomic and restore-fenced. Previous outcomes are
revalidated, clocks cannot rewind, and bounded history cannot be truncated to
clear losses. A WIN/FLAT breaks an unlocked streak without shortening cooldown;
a locked cohort has no reset endpoint in this slice. No cash, P&L, global limit,
fee, model charge or Scope research gate is cleared by this control.

Fresh GitHub baseline: `57dbb9ac1d0075e2e154d9dd313bd1253b78c439`, tree
`b13e2bb9632ef683c14f663b1def4385f63ef85b`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Final expanded source suite: **16 passed in 10.51s**. Initial suite had eight
  passes and one timestamp-string assertion failure (`Z` versus `+00:00`); the
  assertion now compares aware datetime values. No application gate was relaxed.
- Non-editable installed wheel, eight related suites with warnings treated as
  errors: **222 passed in 217.39s**. This covers loss control, settlement and
  position outcomes, closing links, execution, coordination, observer reads and
  the independent Scope entry boundary.
- New cases cover recognition-time/exact-boundary cooldown, automatic gate
  consumption, restart/global-resume persistence, win and unfilled semantics,
  dispatch-before-worker enforcement, unknown usage, paid management/fees turning
  a premium gain into a net loss, expiry loss, frozen policies and atomic rollback.
- Source/wheel/installed module bytes and copied changed tests match. Scoped
  lint/format, dependency consistency, whitespace and 421 local documentation links
  pass. Wheel SHA-256: `488129067d101a23ccd68d171ad7b4eac14279226a3d29d666e5b864db2bb516`.
  Logs/artifacts beside checkout: `native-loss-source*.log`,
  `native-loss-installed-tests.log`, `native-loss-env`, `native-loss-dist`
  and `native-loss-proof`.

[Native guard contract](OPTIONS_NATIVE_LOSS_CONTROL.md) records the account-wide
scope, immutable enrollment, capacity and missing reset/scheduler integration.
Scope watch/order and family loss linkage, reviewed reset, complete path coverage,
Scope runtime/replay and dashboard integration remain open. Authentic provider/
model/calendar/host, visual and prospective economics remain separate. Main
untouched, PR draft, LIVE disabled and deployed experiment frozen. No authentic
provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 native settlement outcome attribution: 2026-10-14 UTC

Cash settlement and worthless expiry now close a stored position outcome through
complete native accounting replay. Receipts are assigned to the exact entry held
at their ordered event, not to every trade sharing the contract. Snapshot identity,
receipt/fill coverage, contiguous sequence, time order, native settlement terms,
ledger cash/settled cash/realized P&L/fees/daily P&L and remaining owned lots must
all agree. Conflicts fail closed. FUNDS_SETTLED is not an exit, physical exercise
remains unsupported, and no settlement is fabricated as a trade fill.

Partial sales plus settlement count remaining contracts once. A later settlement
of a second same-contract entry cannot contaminate the first outcome. Every
recorded entry and management charge remains attributable, including MAINTAIN;
unknown usage still withholds the net result. Data/host allocation and authentic
broker settlement-fee coverage remain open. The fixture's exact cash-settlement
terms encode no extra settlement fee. No new receipt authority or input is added.

This closes an expiry-loss attribution gap needed for subsequent Scope loss state.
It does not start cooldowns, clear loss limits or enroll Scope trading. The native
Scope entry guard and independent research accounts remain unchanged.

Fresh GitHub baseline: `19c94e09c37120fcc91dcfe0cbc28fd154826848`, tree
`6cebc9db1c6eb3a4d5a82e39b2d5ac178089642c`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Initial new source suite: **13 passed in 5.35s**. Expanded source suite:
  **15 passed in 6.71s**, including same-contract reentry and paid management at
  expiry. Four further cases cover snapshot identity/completeness/fill coverage
  and unknown entry cost after settlement.
- Final noneditable installed package: **206 passed in 202.41s**, seven suites,
  outside source with isolated Python, copied tests and warnings as errors. Includes
  all 19 new settlement cases, independent A/B/C/D outcome replay, close linkage,
  native execution/management, observer and Scope entry-boundary regressions.
  No failed test or timeout was waived in this installed run.
- The prior transient environment's Python executable was absent at first test
  invocation. A fresh isolated environment was built using existing dependencies;
  no dependency or application gate was changed to recover it.
- Source/wheel/installed module bytes and copied changed tests match. Scoped
  lint/format, dependencies, whitespace and 416 local documentation links pass.
- Wheel SHA-256: `00372bb382a5e25871a01e40232ee6cf495c3b5f866324db64f6ae3242b81a2d`.
  Logs/artifacts beside checkout: `settlement-outcome-source*.log`,
  `settlement-outcome-installed-tests.log`, `settlement-outcome-env`,
  `settlement-outcome-dist` and `settlement-outcome-proof`.

[Stored outcomes](OPTIONS_POSITION_OUTCOME.md) records replay and output semantics.
Scope watch/order linkage, loss/cooldown/reset controls, complete path coverage and
Scope execution/runtime remain open. Authentic provider/model/calendar/host,
visual and prospective economics remain separate. Main untouched, PR draft,
LIVE disabled and deployed experiment frozen. No provider/model/broker call,
host unit or deployment changed.

---

## P7 native closing-entry linkage: 2026-10-14 UTC

Ordinary CLOSE orders previously had no exact entry identity, leaving their
position outcome incomplete and fresh dispatch dependent on contract-level
ownership. New native close intents and approvals now retain the held entry ID
from the owning journal transaction. Protective and model-managed closes carry
the same explicit link. Dispatch rejects a mismatched/missing half-link or a
changed held entry before recording an attempt, starting a worker or submitting.
Stored attribution verifies the buy identity, instrument, chronology and agreement
with existing protective/model links. Close-model cost attribution retains that
entry identity too; independent accounts and all entry/management costs remain.

The field is optional and absent fields remain omitted from historical intent
encoding. Existing protective/model links still work. Historical unlinked ordinary
closes are not backfilled and remain incomplete for exact-position outcomes.
No Scope execution is enabled. Watch/order association, full-cost loss/cooldown/
reset controls, complete path coverage and runtime integration remain open.

Fresh GitHub baseline: `562380e752c65b5d35a22fafa495fd0fd67dce18`, tree
`cec0905dcb00712275be3c5a225b6efe96e1a871`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Final noneditable installed package: **187 passed in 304.43s**, six suites,
  outside source with isolated Python, copied tests and warnings as errors. This
  includes nine new closing-link cases, the expanded 21-case outcome suite with
  independent A/B/C/D replay, and native execution, management, observer and Scope
  entry-boundary regressions. No failed installed test was waived.
- Initial source-only invocation used the previous installed worker/schema and
  produced four close-worker failures (14 passed). Rebuilt the noneditable package
  so owner and isolated child use the same schema; no execution gate was relaxed.
- New cases cover owner-derived identity, historical retry, approval/intent/held
  entry conflicts, absent half-links, no worker attempt, BUY rejection and stored
  attribution conflicts. Outcome coverage distinguishes new linked closes from
  legacy unlinked history and retains both-side fees.
- Source/wheel/installed module bytes and copied changed tests match; dependencies,
  scoped lint/format, whitespace and 415 local documentation links pass.
- Wheel SHA-256: `93ce590aa9e2926a6be0a1db35d0f83c43e9703b6f7c67b832846a1fdefcaf1c`.
  Logs/artifacts beside checkout: `closing-link-source.log`,
  `closing-link-installed-tests.log`, `closing-link-env`, `closing-link-proof`
  and `closing-link-dist`.

See [stored outcome contract](OPTIONS_POSITION_OUTCOME.md). Main untouched,
PR draft, LIVE disabled and deployed experiment frozen. No provider/model/broker
call, dependency, host unit or deployment changed. Authentic provider/model/calendar/
host, browser and prospective economics acceptance remain separate.

---

## P7 stored native position outcomes: 2026-10-14 UTC

The stored observer now exposes `position_outcome(entry_client_id)` for one exact
native buy. It reconstructs linked protective/managed exit fills, premiums, actual
fees and every attributable entry/management model charge from the same snapshot.
Account identity and token prices come from frozen journal configuration. Missing
costs, unallocated account calls, unlinked manual exits or contract-only settlement
receipts prevent a complete net outcome; conflicting lineage and orphan fills fail
closed. Open/partial/unfilled positions do not acquire realized outcomes.

This provides native evidence for subsequent Scope loss-state integration. It does
not allocate data/host costs, label its result all-in profit, link Scope watches to
orders, start cooldowns or reset limits. Full-cost session comparisons and existing
account-level budgets remain authoritative. The Scope preparation/dispatch guard
is unchanged. No provider/model/broker call, dependency, host unit or deployment
changed; all replay inputs are normalized fixtures and scripted model receipts.

Fresh GitHub baseline: `b08da50a211dc8cad7bb4cd95cbc594c1cfd49fd`, tree
`a4509fdbd70f78d022373a6b72a802756d095f1d`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 open/draft.

Validation:

- Initial source suite: **13 passed in 185.07s**, including independent A/B/C/D
  native replay costs, read-only bytes, exact account identity, damaged fill/cost/
  approval/consumption evidence, open/partial entries and manual/protective exits.
- Focused lifecycle check: **4 passed in 9.97s**. Three additional cases cover
  known/unknown unallocated account calls and unknown entry usage.
- Additional installed lifecycle proof: **4 passed in 9.71s**, covering charged
  MAINTAIN/TIGHTEN without exits, missing admitted receipts, unfilled entries and
  contract-only settlement linkage.
- Noneditable installed package: **172 passed, 1 fixture-process timeout in
  332.75s** across five suites, outside source with isolated Python, copied tests
  and warnings as errors. The existing management `missing` case timed out before
  its mocked model call; the unchanged exact-case retry **passed in 8.84s**.
  No deadline or application gate was relaxed. The separate four-case installed
  group above also passes; no single all-green 177-case invocation is claimed.
- Source/wheel/installed module bytes and copied outcome tests match. Scoped
  lint/format, dependency consistency, whitespace and 414 local documentation
  links pass.
- Initial installed collection used the copied tests directory as its import root;
  a cross-test package import failed. The corrected invocation uses the copied
  proof root and runs outside the source checkout; no application change was needed.
- Wheel SHA-256: `52b05eebd6b8f42c0336f05d023e8adba1e4fd4caa30ff93a7947913bf1cb829`.
  Logs/artifacts beside checkout: `position-outcome-source.log`,
  `position-outcome-native.log`, `position-outcome-installed-tests.log`,
  `position-outcome-env`, `position-outcome-dist`, `position-outcome-proof`.

[Outcome contract](OPTIONS_POSITION_OUTCOME.md) records exact closure and incomplete
semantics. Native Scope watch/order linkage, full-cost loss/cooldown/reset state,
complete obstruction coverage, Scope dispatch/management/runtime/replay and
observer integration remain open. Authentic provider/model/calendar/host, visual
and prospective acceptance remain separate. Main untouched, PR draft, LIVE disabled
and deployed experiment frozen.

---

## P7 Scope native entry boundary repair: 2026-10-13 UTC

Reviewing the next native integration exposed an execution-boundary gap: Scope
watch APIs correctly withheld authority, but the generic engine entry API did not
check research enrollment. The common engine now rejects `OPEN_LONG` at both
preparation and dispatch whenever the Scope watch-policy table exists. Stored
eligible sizing, a caller-supplied admission ceiling, another source key or no
active watch cannot bypass `SCOPE_NATIVE_EXECUTION_NOT_ENROLLED`.

The check fails closed for an incomplete enrollment table. Preparation keeps its
normal rejected native decision/audit receipt and creates no order/reservation.
Dispatch rejects a prepared buy before an attempt or worker, clears the active
order lock and records the reason. Historical preparation retries do not authorize
current dispatch. HOLD and owned/protective exits retain their normal rules,
including recovery from legacy/inconsistent state. Existing attempted-order
reconciliation is unchanged. Accounts without Scope enrollment retain their
existing Degen/Swing behavior, independent ledgers and full cost accounting.

This repairs the promised research-only boundary; it does not implement Scope
orders, native filled-position/loss/cooldown linkage or complete path coverage.
A rejected generic entry is still a native decision and therefore blocks subsequent
research-watch mutations under the existing native-history restriction. Callers
must use watch APIs for research rather than retry generic entry as a bypass.

Pre-edit fresh GitHub head was `e11cbe1adfc3cae1497f13cf9d9038492d1a92c7`, tree
`5384288ec9c6603a85082ea0d23cb8fa189ed479`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 is open/draft.

Validation:

- Focused source group: **81 passed in 19.43s**, including eight new boundary
  cases plus owned admission and watch lifecycle. Tests cover direct/prepared
  entries, eligible-sizing reuse with/without a ceiling, incomplete enrollment,
  restart, worker non-invocation and retained HOLD/owned-close behavior.
- Initial new suite: six passed, two failed because the new assertions expected
  `ABANDONED`; the engine's established dispatch rejection status is `REJECTED`.
  Tests now verify that status, no attempt, released lock and the stored reason.
  No application gate or existing lifecycle status was changed to satisfy tests.
- Final noneditable installed package: **811 passed in 102.83s**, fourteen suites,
  outside source, isolated Python, copied tests and warnings as errors. Scope,
  native execution/admission, Degen and shared-strategy regressions all pass.
- Source/wheel/installed module bytes and copied Scope tests match; scoped
  lint/format, dependencies, whitespace and 245 local documentation-link checks pass.
- Wheel SHA-256: `4eabaa260c366c01046af75a9c66ebc834543ca30a2538b45e3cef5ee383f928`.
  Local logs/artifacts: `scope-boundary-source*.log`,
  `scope-boundary-installed-tests.log`, `scope-boundary-env`,
  `scope-boundary-proof` and `scope-boundary-dist` beside the checkout.

[Native boundary semantics](OPTIONS_SCOPE_OWNED_ADMISSION.md#native-execution-boundary)
record the recovery behavior. Native Scope order/position linkage and full-cost
loss/cooldown/reset, complete obstruction coverage, dispatch/management/runtime/
replay and observer integration remain open. Authentic provider/model/calendar,
host, visual and prospective acceptance remain separate. Main untouched, PR draft,
LIVE disabled and experiment frozen. No provider/model/broker call, dependency,
host unit or deployment changed.

---

## P7 Scope owned account admission review: 2026-10-13 UTC

New frozen watch cohorts may now explicitly enroll an account-aware sizing review.
The action refreshes arming evidence, requires the complete hold and current
contract gates, then uses the existing common governor with the original exact
contract/invalidation. The current underlying quote must remain before target one.
Callers cannot supply account balances, quantity, a replacement stop or a calendar.

Account state comes from the same owned journal inside the transaction. Original
and effective limits, authoritative account, proposal, both calendar inputs,
restricted session and full governor result are retained. Slippage and entry fees
are included; effective limits reserve one exit-order fee per contract, matching
native partial-exit protection. All existing loss/cash/exposure/size gates remain
binding. The Scope debit cap only tightens the owner envelope. No parallel cash or
cost calculator, model call, order, reservation or native decision is created.

The owner session and explicit Scope index window are intersected conservatively,
never substituted. The offline result expires no later than its arming sample.
Incomplete holds cannot size. Failed current evidence or rejected admission resets
the hold; action/hold/price termination/review commit atomically. Historical retries
and stored-only reads do not refresh a result. Native activity remains blocked in
this research watch version, preserving independent accounts and all existing
entry/management cost accounting. An eligible review grants no dispatch authority.

Pre-edit fresh GitHub head was `c1c73d55b4ab56a7e60ce0892a7f76dbbd41c0ef`, tree
`8e84c2aee047a541e7a4fd2489b2bfba35b83f7c`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 is open/draft.

Validation:

- Source owned-admission/contract/arming/quality/watch/direction group: **249 passed
  in 29.78s**, including 22 new cases. Initial owned-admission suite passed 16
  before six extra fee-boundary, restart/account-isolation and atomicity cases.
- Final noneditable installed package: **803 passed in 116.15s**, thirteen suites,
  outside source, isolated Python, copied tests and warnings as errors. Includes
  all Scope suites plus native execution/admission, Degen and shared strategies.
  The previous slice's runtime-init timeout case passes in this group. No failed
  test or deadline relaxation in this slice; prior timing failures remain recorded.
- Tests verify exact fee-inclusive debit/full-loss boundaries, CALL/PUT, current
  target/stop crossing, fresh underlying source/time, quote size, unfinished holds,
  historical retries, native-activity guard, global owner blocks, frozen opt-in,
  owner restart, independent accounts and atomic rollback.
- Source/wheel/installed modules and copied Scope tests match; scoped lint/format,
  dependency consistency, whitespace and 253 local documentation-link checks pass.
- Wheel SHA-256: `5b7e870f859766b6c624d9ba280bc8530879c4ee0e59c2d8fc638fd95f16e2d1`.
  Local proof: `scope-owned-source*.log`, `scope-owned-installed-tests.log`,
  `scope-owned-env`, `scope-owned-proof` and `scope-owned-dist` beside the checkout.

[Owned admission contract](OPTIONS_SCOPE_OWNED_ADMISSION.md) records the offline
boundary. Native position/order linkage, full-cost filled-outcome loss/cooldown/reset,
complete obstruction coverage, Scope common-owner dispatch/management/runtime/replay
and observer integration remain open. Authentic provider/model/calendar, host,
visual and prospective acceptance remain separate. Main untouched, PR draft,
LIVE disabled, deployed experiment frozen. No market/model/broker call, dependency,
host unit or deployment changed.

---

## P7 Scope exact-contract profile gates: 2026-10-13 UTC

The supplied-contract review now recomputes quality and classifies responsive,
balanced and convexity alternatives from current exact SPXW evidence. Explicit
frozen price/spread/liquidity bounds, observed nonzero signed delta, upstream
identity/tick/freshness and target reachability gates remain binding. Missing
volume/open interest stays unknown. Higher observed delta is not capped by Degen's
unrelated band. Profiles retain pattern/parent/right and explicit rejection reasons.

Convexity can be classified but cannot pass while complete path evidence remains
unproven. No failed convexity branch falls back to a different profile. Scores,
reference deltas and premium prices do not become quantities, debit approvals or
execution authority. Native sizing must still include all fees/slippage and entry/
management costs through the shared owner, not a new Scope account calculator.

New frozen watch cohorts may enroll the exact matching contract/quality policy.
Calls lock the full review; rejected calls consume no play/event. Arming samples
recheck current eligibility and persist failed reviews as resets. Original
instrument/geometry, source progression, global owner limits, action receipts and
restore fencing remain intact. Old cohorts omit the field and cannot add it on
reopen. Independent accounts and existing shared Degen/Swing execution are unchanged.

Pre-edit fresh GitHub head was `ae3f81e341475b32855dfa817e40878d1df5bb2b`, tree
`e049cb1527de7c93722f5e5eb47293fffa593cc5`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 is open/draft.

Validation:

- Final source contract/arming/quality/watch/direction group: **227 passed in
  10.90s**, including 36 contract cases.
- Initial source group: 198 passed, 25 failed. New fixtures used off-tick quotes,
  so existing preflight rejected them before profile checks. Corrected fixtures
  use valid ticks and compare exact spread-policy boundaries. Follow-up: 31
  passed, one failed because the zero-delta test expected a profile-level reason;
  zero delta correctly fails earlier preflight. That assertion now verifies the
  upstream failure. No application gate was weakened or failing case removed.
- Final noneditable installed group: **780 passed, one failed in 142.62s**,
  outside source, isolated Python, copied tests and warnings as errors. Twelve
  suites cover 36 new contract cases, all earlier Scope capabilities and native
  execution/admission, Degen and shared-strategy regressions. The failure was the
  existing `test_installed_runtime_init_roundtrip_joint_settings` subprocess's
  20-second initialization deadline. No deadline or application gate was relaxed.
  The unchanged isolated retry completed: **1 passed in 11.23s**. The initial failure
  remains recorded; authentic host startup/latency acceptance stays open. This
  does not claim an all-green 781-test invocation.
- Installed/wheel/source module bytes and copied Scope tests match; scoped
  lint/format, dependency consistency, whitespace and 248 local documentation-link
  checks pass.
- Wheel SHA-256: `87352fc33ef789cffd53b2cd0e49a87716a7e92580a11162a77cbeb23f20f636`.
  Local logs/artifacts: `scope-contract-source*.log`,
  `scope-contract-installed-tests.log`, `scope-contract-env`,
  `scope-contract-proof` and `scope-contract-dist` beside the checkout.

[Contract-profile semantics](OPTIONS_SCOPE_CONTRACTS.md) distinguish the pinned
source classification from stricter observed-data requirements. Native account-aware
admission, filled-position/full-cost loss/cooldown/reset, complete obstruction
coverage, Scope common-owner execution/runtime/replay and observer integration
remain open. Authentic provider/model/calendar, host, visual and prospective
acceptance remain separate. Main untouched, PR draft, LIVE disabled and experiment
frozen. No provider/model/broker call, dependency, host or deployment changed.

---

## P7 Scope sampled arming hold: 2026-10-13 UTC

New frozen watch cohorts can explicitly require a 60–600 second research hold
with fresh samples no more than 1–10 seconds apart. Enrollment requires the exact
quality policy. Every current evidence/history/metadata/quote/context source clock
must advance; receipt-only refreshes cannot accumulate a hold. The first passing
sample starts the timer. Source ages, context validity and entry cutoff bound each
sample's validity; gaps restart the interval. Exact configured duration is allowed.

Every observation rechecks owner readiness and complete quality against the
original instrument/session, selected pattern/parent/right, geometry, anchor and
prior evidence. Newly completed bars pass the same chronological price guards as
explicit advancement. Crossings terminate the unfilled watch atomically. Missing,
stale, blocked or changed evidence records a durable reset; recovery starts over.
Source watermarks, full inputs, quality results, timing, reasons and original
historical action receipts remain under the existing lease/revision/restore fence.

`ARMED` is a dated sampled research result, never trade authority. The top-level
watch remains `WATCHING` until termination/expiry; reads do not refresh its state.
Sampling does not prove an uninterrupted intrabar path or complete obstruction
coverage. No order, model charge, P&L or account balance is invented. Independent
accounts and all native entry/management costs remain unchanged. Old cohorts omit
the new optional field and cannot add it on reopen.

Pre-edit fresh GitHub head was `b6fc49a29b2aaa94265581b397db1095e4255e17`, tree
`5e3da8f1e144780185207ef658b0f3906d3c337d`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 is open/draft.

Validation:

- Final noneditable installed wheel: **745 passed in 97.83s**, outside source,
  isolated Python, copied tests and warnings as errors. Eleven suites include
  30 new arming cases, all earlier Scope diagnostics/watch/direction/quality,
  options execution/admission, Degen and shared Degen/Swing regressions.
- Earlier source group passed 182 tests in 11.18s before the nine added arming
  restart/source-stream/price-crossing/atomicity cases. Initial arming run passed
  21 in 9.71s. Counts overlap; the installed total is the final proof.
- New tests cover CALL/PUT hold boundaries, sampling gaps, stale/missing/blocked
  evidence, exact retries/conflicting keys/revisions, source-clock progression,
  restart, locked history, new-bar invalidation, expiry, frozen enrollment and
  transaction rollback. No test failure or deadline relaxation in this slice.
- Installed/wheel/source module and copied Scope-test bytes match. Scoped
  lint/format, dependency consistency and whitespace checks pass.
- Wheel SHA-256: `25bb62e5f640826a4a9a92a8cacbce66fa774c53312c78365dca15f55afebd80`.
  Local proof: `scope-arming-installed-tests.log`, `scope-arming-env`,
  `scope-arming-proof` and `scope-arming-dist` beside the checkout.

[Arming contract](OPTIONS_SCOPE_ARMING.md) records the source's default sixty-second
hold and the conservative sampling adaptation. Complete obstruction coverage,
contract-profile admission, native filled-position/full-cost loss/cooldown/reset,
Scope common-owner execution/runtime/replay and observer integration remain open.
Authentic provider/model/calendar, host, visual and prospective acceptance gates
remain separate. Main untouched, PR draft, LIVE disabled, deployed experiment
frozen. No provider/model/broker call, dependency, host unit or deployment changed.

---

## P7 Scope quality and known-level path review: 2026-10-13 UTC

`app.options.scope_quality` now recomputes complete context and reports the pinned
research score for all detected alternatives. Nine original base scores and six
parent-derived variant adjustments remain explicit. Seven named components retain
confirmation, flow, news, event risk, actual first-target reward, expected-move
consumption and required dealer context. Score thresholds are explicit and frozen;
classifications are not win probabilities or evidence of profitability.

Blocked/watching context stays unscored. Exact Decimal geometry determines the
minimum first-target reward check before display rounding. A consumed first
objective blocks. Supplied dealer nodes, prior-session high/low and ATM boundaries
are retained along the direction from the current completed close to the second
objective. A known level before/at the first objective fails this conservative
review. No intervening supplied level does not prove a clear path:
`complete_path_proven` remains false, including at the convexity score threshold.

The point schedule follows pinned SignalFlow
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Known-level/consumed-first-objective
rejection is an explicitly documented conservative adaptation. The pinned source
mentions an unobstructed path but does not implement complete directional
obstruction coverage; this slice does not claim to supply that missing evidence.

New frozen watch cohorts may explicitly include the exact matching quality policy.
Calls recompute the selected pattern/parent/right review, reject atomically without
consuming a call, and lock the full original quality scan on success. Omitted
quality fields preserve old policy serialization and behavior. No old cohort is
migrated, and the shared Degen/Swing execution path remains unchanged.

Pre-edit fresh GitHub head was `b4d983e0e286f1507b222e7e2bc147547de444de`, tree
`e85b5325a244ba4ade83970b0bed07c12e8f79bd`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 is open/draft.

Verification:

- **715 passed in 89.53s** on the final repeated noneditable installed-wheel run,
  outside source, isolated Python, copied tests and warnings as errors. Ten suites
  cover quality, direction/watch, context/structure/preflight, native options
  execution/admission, Degen and shared Degen/Swing strategy paths.
- The first installed group had **714 passed, 1 failed in 98.30s**: the existing
  shared native model-worker roundtrip exceeded its five-second request deadline.
  The unchanged isolated test passed in 7.10s total, then the unchanged full group
  passed as above. Neither application/test code nor the deadline was relaxed.
  This retains the timing failure as evidence; authentic host latency acceptance
  remains open. Overlapping runs are not added together.
- The final source quality/watch/direction group passed **161 tests in 7.50s**,
  including 86 new quality cases. An initial quality-only run had 75 passes and one
  fixture failure: it assumed the first objective was already consumed. The final
  fixtures explicitly place completed price before, at and beyond that objective
  in both directions. No application gate was weakened or failed test waived.
- Coverage includes all nine patterns and six parent-preserving variants in both
  directions, component arithmetic and saturation, exact threshold/half-move/2R
  boundaries, upstream blockers/missing evidence, directional known-level endpoints,
  prior/ATM levels, consumed objectives, exact versus displayed reward, stable
  Decimal context, hashes, immutable inputs and absence of file/socket/SQLite work.
  Optional watch-policy matching, locked scan storage and atomic rejection pass.
- Installed/wheel/source modules and copied Scope tests match. Scoped lint/format,
  dependency, whitespace and local documentation-link checks pass.
- Wheel SHA-256:
  `53c0dda130bdf696981a5eb12c752db15ad8c664776a0ab020a8833ddd82b97f`.

See [source of truth v1.32](SOURCE_OF_TRUTH.md) and the
[quality/path contract](OPTIONS_SCOPE_QUALITY.md). Complete obstruction coverage,
arming hold, contract profile/admission, native filled-position linkage with every
entry/management cost, loss/cooldown and reviewed family reset, Scope shared
execution/runtime/replay, observer integration and authentic provider/calendar
acceptance remain open. All research accounts and full-cost accounting stay
independent and unchanged. No market/model/broker call, dependency, host or
deployment changed. Main untouched, PR #1 draft, LIVE disabled, experiment frozen.

## P7 Scope watch neutral reset and direction control: 2026-10-13 UTC

New explicitly frozen watch cohorts can now enroll `ScopeDirectionResetPolicy`.
The optional field is omitted for older policies, preserving their serialization
and fail-closed direction behavior. Existing populations cannot enable it on
reopen. This adapts the already pinned Scope requirement to invalidate, return to
neutral and receive fresh reversal confirmation before an opposing called play.

A separate `neutralize` transaction requires the latest invalidated unfilled play,
no active watch, unchanged identity/history and fresh structure evidence completed
after invalidation was processed. It stores a neutral software state and evidence;
it does not infer a neutral price zone or overwrite the original classification,
geometry, call count or account loss controls. Exact retries, stale revisions,
transaction rollback and restart follow the same journal/restore protections.

An opposing call then requires the current full context scan to detect a REVERSAL,
at least the frozen ten-minute cooldown measured from the actual neutral record,
and at least two complete SPX bars that began after that record. Bars already in
progress do not count. The frozen policy may require a longer cooldown or more
bars. Waiting, a new continuation or old bars cannot substitute for a reversal.
Daily limits and current global owner readiness remain binding. Neutral cleanup
can run while halted; a new call cannot bypass the halt.

Pre-edit fresh GitHub head was `7b7a975c351995c5d7095e19a1de0956478579b4`, tree
`39e26d5409cde2c2ec51ca97157bf26775d68fb7`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`, and PR #1 is open/draft.

Verification:

- **629 passed in 93.90s** from the final noneditable installed wheel, outside
  source, isolated Python and copied tests, warnings as errors. Nine suites cover
  direction/watch, all earlier Scope diagnostics, options execution/admission,
  Degen and shared Degen/Swing strategies. No failed test was waived.
- The final source direction/watch group passed **75 tests in 6.41s** (24 new
  direction cases plus the existing 51 watch cases). An earlier expanded run had
  67 passes and one boundary-fixture failure: its evaluation time preceded its
  own evidence receipt. The corrected fixture tests one second before cooldown
  and the exact boundary using already-known evidence; no application gate was
  weakened and the final installed group covers this correction.
- Tests cover both directions, neutral persistence, no immediate/pre-reset flip,
  reversal-class enforcement, exact cooldown boundaries, larger confirmation
  requirements, locked history/identity, stale data/revision rejection, transaction
  rollback, halted cleanup versus call rejection and unchanged old-cohort policy.
- Installed module, wheel and source bytes match, as do the copied Scope tests.
  Scoped lint/format, dependency, whitespace and local documentation links pass.
- Wheel SHA-256:
  `f0a1850d6242bd1dd3a600c06d733e917e2d6900d94bbf41631205caba6dec5f`.

See [source of truth v1.31](SOURCE_OF_TRUTH.md) and the
[watch and direction-reset contract](OPTIONS_SCOPE_WATCHES.md). This is unfilled
research state, not order authority or filled-position management. Native full-cost
loss/cooldown attribution and reviewed family reset, quality/arming hold/obstruction
policy, common-owner Scope admission/management/runtime/replay, stored observer
projection and authentic provider/calendar acceptance remain open. No entry or
management cost is dropped or replaced with inferred watch P&L. Independent accounts
remain separate. No market/model/broker call, dependency, host or deployment changed.
Main untouched, PR #1 draft, LIVE disabled, deployed experiment frozen.

## P7 durable unfilled Scope watches: 2026-10-13 UTC

`app.options.scope_watch.ScopeWatchBook` now records called research plays in the
existing owned options journal. The frozen policy explicitly caps calls at one or
two per reviewed session, including unfilled invalidations and expirations. A
single active watch locks the full original frame, context scan, selected pattern
and parent, exact instrument, session and geometry. Later calls cannot reuse old
completed endpoints or rewrite prior SPX/SPY/QQQ history.

Fresh completed-bar review processes every new bar against the original geometry,
retaining the first invalidation/objective crossing and separate observation time.
Same-bar ambiguity chooses invalidation. The original entry cutoff expires an
unfilled watch without fresh data, including during an account halt. None of these
states supplies a fill, win, loss, P&L or execution authority.

Exact request receipts, revision checks, transactional call counting and the unique
active row survive restart and concurrent attempts. All three tables participate
in the existing paired restore fence. Stored snapshots perform no market work or
mutation. Separate accounts retain separate counts and unchanged cash/cost ledgers.

This version requires a new untraded, healthy owner with matching SPX/provider/quote
identity. Native model/order/decision/opportunity/runtime history blocks enrollment
and subsequent mutations: execution linkage must be implemented before a watch can
safely represent a traded position. Opposite-direction calls are explicitly blocked
until the settled durable neutral/flip path exists. There is no reset that refunds
called plays, nor a caller-supplied outcome or loss bypass.

Pre-edit GitHub head was `a5cfc8d037e9a6a0fc30c752f20ca703c2dc8c19`, tree
`08a19845a59cbb8695653fbe6d5c857ae5108fd0`. The original requested head
`077dfe56bbda89019642332e714903306eb682c4` remains an ancestor. Fresh GitHub reads
confirmed main `b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 open/draft.

Verification:

- **605 passed in 93.33s** on the final noneditable installed wheel, using isolated
  Python and copied tests, warnings as errors. Eight suites cover the 51 new watch
  cases, existing Scope context/structure/preflight, options execution/admission,
  Degen and shared Degen/Swing strategy paths. No failed test was waived.
- Source checks progressed through 41 and 48 passing cases. An expanded run had
  49 passes and two test-fixture failures (a changed date expectation and unchanged
  positive delta on a PUT fixture). Both were corrected; the final source run
  passed all 51 cases in 5.17s, and the installed group covers those corrections.
- Watch cases cover both directions, original evidence/geometry locks, first versus
  later crossing, same-bar ambiguity, unfilled daily counting, exact retries,
  restart, concurrent actions, independent accounts, explicit next-session counting,
  stale/context/identity/history/revision rejection, halt-time cutoff expiry,
  atomic rollback, journal-only restore rejection and closed-owner protection.
- Installed module, wheel and source bytes match for the new book and journal
  change; copied Scope tests match source. Scoped lint/format, dependency and
  whitespace checks pass. Documentation links were checked locally.
- Wheel SHA-256:
  `18e050fb3cded31e6f7b37c5baceaf2c63e4b8cf6ce9e8261b65d28eeaab17b2`.

See [source of truth v1.30](SOURCE_OF_TRUTH.md) and the
[durable watch contract](OPTIONS_SCOPE_WATCHES.md). Durable neutral/flip state,
verified native full-cost loss/cooldown attribution and reviewed family reset,
quality/obstruction policy, common-owner admission/management, Scope runtime/replay
and observer projection remain open. Authentic provider/calendar, host and
prospective economic gates remain open. Existing independent A/B/C/D accounts and
all entry/management costs are preserved. No provider/model/broker call, dependency,
host or deployment changed. Main untouched, PR #1 draft, LIVE disabled, experiment
frozen.

## P7 Scope context variants and risk review: 2026-10-13 UTC

The pure `app.options.scope_context` review now adds the six pinned level-anchored
variants to completed Scope structure: prior-level continuation/rejection,
dealer-level acceptance/rejection, implied-move boundary rejection and exhaustion
confluence reversal. Each retains its exact parent geometry and matched level.
Context cannot create an absent pattern, rescue a blocked contract/confirmation,
or remove the failed-break neutral/reset requirement.

Typed dealer, expected-move, SPX/SPXW flow, broad-market news and US macro-event
payloads bind to their current coverage attestations with exact hash/source/clock/
quality agreement. Explicit prior-session range and reviewed date must agree and
be known before the current open. Unknown/expired/missing/mismatched inputs block.
Opposing flow/news, high-impact event windows and excessive expected-move
consumption block both original detections and every derived variant. Elevated
risk stays an explicit quality-review note. No score, probability, quantity,
account, model, order or execution authority is added.

Pre-edit branch head was `3cec6b9042e39e19a7b00f30a46198d103b41a83`, tree
`eddeb9508a9e86cff43eecfd33b47b220356fa12`. This continues the same pinned
SignalFlow context/risk implementation at
`f9eaf2c1b5d13dca287ee7138126883065b00395`, without another strategy research pass.

Verification:

- **490 passed in 37.08s** from the final noneditable installed wheel, outside
  source, isolated Python, warnings as errors. Six suites cover 61 new context
  cases, 56 structure cases, 107 preflight cases and existing option admission,
  Degen and shared-engine regressions. No failed test was waived.
- Source checks passed 56 initial and 61 final cases. Both directions of all six
  context variants preserve parent geometry/level. Tests cover every missing
  payload, wrong source/clock/entitlement/completeness, unbound modified content,
  unknown/expired state, exact expiry/kind, prior-session chronology, directional
  risk, exact expected-move and proximity boundaries, deterministic node ties,
  no-pattern/pending-reset/contract rejection preservation and far/unmatched levels.
- Full input/policy hashes, unchanged input bytes, fixed Decimal context and no
  file/socket/SQLite work are verified. Prior-session dates and provider values
  remain supplied fixture evidence, not authentic calendar/feed acceptance.
- Installed module, wheel and source bytes match, as does the copied test input.
  Scoped lint/format, dependency and whitespace checks pass; all 132 checked local
  documentation links resolve.
- Wheel SHA-256:
  `bb0de2a5bad78b92991fda3326246c605d10538afb4000ae9cc2ff2c5879af20`.

See [source of truth v1.29](SOURCE_OF_TRUTH.md) and the
[Scope context contract](OPTIONS_SCOPE_CONTEXT.md). Durable play counting,
neutral/loss/cooldown state, quality/obstruction policy, common-owner admission and
management, Scope runtime/replay and authentic provider/calendar evidence remain
open. Anchored variants are correlated views of a parent pattern, not independent
trades or another bankroll. Independent research accounts and all entry/management
cost paths remain preserved. No provider/model/broker call, dependency, host or
deployment changed. Main untouched, PR #1 draft, LIVE disabled, experiment frozen.

## P7 Scope completed structure and confirmation: 2026-10-13 UTC

The pure `app.options.scope_structure` scanner now evaluates all nine pinned
price-derived Scope modules in both CALL and PUT directions. It reruns exact
preflight, binds technical/confirmation attestations to supplied histories,
requires at least five completed SPX bars and complete volume-backed VWAP,
computes SPY/QQQ directional confirmation, and checks the supplied SPXW strike
against the second structural objective. Missing or mismatched evidence blocks;
confirmation cannot create a missing SPX pattern or substitute another contract.

Failed-break reversal remains blocked on its initial neutral close and requires
a separate completed follow-through bar. Trap reversal retains that same local
sequence. This is not a durable account play-state transition. Consumed objectives,
invalid geometry, unavailable SPX volume and unrepresentable derived values block.
No source score/probability, quantity, account, order or trading authority is added.
Existing independent accounts and every entry/management cost path are unchanged.

Pre-edit branch head was `1cf3affc72fd1033e5a5c6d1f7e6635399d10f8b`, tree
`f67929eb134eb059a85aee223b6167fa5a7eef76`. Fresh GitHub reads confirmed main
`b5359aaf396e692d2142d7e02908f1544e045ee6`, with PR #1 open/draft.
The nine structural modules and confirmation/reachability formulas were re-read
from the already approved SignalFlow commit
`f9eaf2c1b5d13dca287ee7138126883065b00395`.

Verification:

- **429 passed in 37.80s** from the final noneditable installed wheel, outside
  source, isolated Python, warnings as errors. Five suites cover 56 new structure
  cases, 107 preflight cases and existing option admission, Degen and shared-engine
  regressions. No failed test was waived. Initial source checks passed 50 cases;
  final source checks passed 56 after additional negative geometry/path cases.
- Both directions of all nine patterns, exact SPY/QQQ confirmation/conflict
  boundaries, exact/on-or-beyond strike reachability, neutral/fresh sequencing,
  consumed objectives, flat/no-pattern structure, changed contract right,
  nonpositive risk and numeric bounds are covered.
- Payload mismatch, changed history, not-yet-known attestations, absent/partial
  volume, too few completed bars and preflight failures produce explicit blockers.
  Tests verify immutable input bytes, full policy identity, fixed Decimal context
  and no file/socket/SQLite work during scanning.
- Installed module, wheel and source bytes match, as does the copied test input.
  Scoped lint/format, dependency and whitespace checks pass; 124 checked local
  documentation links resolve.
- Final wheel SHA-256:
  `f226702bf6f86393ea873658493b876241308671e49127dc27b95ae946764006`.

See [source of truth v1.28](SOURCE_OF_TRUTH.md) and the
[Scope structure contract](OPTIONS_SCOPE_STRUCTURE.md). Six context-derived
modules, context-risk semantics, durable play/loss/cooldown state, common-owner
admission/management, Scope runtime/replay and authentic required data remain open.
These diagnostics do not close Scope M7, provider, host, prospective economic or
LIVE gates. No dependency, provider/model/broker call, host or deployment changed.
Main is untouched, PR #1 draft, LIVE disabled and the deployed experiment frozen.

## P7 Scope exact-contract evidence preflight: 2026-10-13 UTC

The pure `app.options.scope` preflight now validates the nine required Scope
coverage attestations, completed SPX/SPY/QQQ histories and one exact same-day
SPXW metadata/quote pair. Every missing, duplicate, unbound, incomplete, delayed,
stale, future or inconsistent input retains a subject-specific blocker. Explicit
index-session boundaries and the contract's last-trading time must permit the
supplied protection cutoff. No SPY, AM-settled SPX or different-expiry fallback
exists. Frozen source/age/lag/skew/spread settings have no provider-derived defaults.

A complete result only means supplied coverage is complete for setup review.
It does not evaluate evidence-payload semantics, confirmation agreement, setup
geometry or risk. Payload hashes bind references; they do not authenticate the
provider or load/validate external content. Results bind the whole input/policy
and always carry false authority/LIVE flags. There is no account, model, order,
I/O, new execution owner or change to Degen/Swing enrollment and costs.

Pre-edit branch head was `581a83c0df75905dcc9910769ee24441ba5cbfbe`, tree
`597aa3ff379fb8e543a325c66a7c748155921be4`. Fresh GitHub reads confirmed main
`b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 open/draft.
The approved SignalFlow V2 playbook, policy and implementation were re-read at
`f9eaf2c1b5d13dca287ee7138126883065b00395`; this is an implementation step,
not a new strategy/source comparison.

Verification:

- **373 passed in 37.28s** on the final noneditable installed package, outside
  source, warnings as errors. The four suites cover 107 new Scope cases, existing
  options admission, Degen and shared Degen/Swing execution.
- Initial installed invocation stopped at collection because isolated Python
  excluded the copied test package's parent. The final command explicitly adds
  only that external proof directory to pytest's path. No application/test logic
  was changed to resolve the harness error. Earlier source-only proof passed
  97 cases before ten additional metadata/history/session cases were added.
- Rejections cover every missing/duplicate evidence group, missing/duplicate or
  gapped/future/interpolated histories, metadata/quote capability and freshness,
  wrong root/underlying/settlement/deliverable/expiry, changed provider mapping,
  expired/premature last-trading cutoff, crossed/unsized/off-tick/wide markets,
  synchronization, naive/future clocks and unsafe copied models. CALL/PUT and
  supplied shortened-session fixtures pass without importing a Degen delta band.
- Coverage results preserve input bytes, bind changed payload/policy hashes,
  remain stable under a changed global Decimal precision and perform no file,
  socket or SQLite connection work. Supplied session fixtures do not claim actual
  calendar/provider acceptance.
- Installed module, wheel and local source bytes match; the copied test input
  matches. Scoped lint/format, dependency and whitespace checks pass; all 125
  checked local links resolve.
- Wheel SHA-256:
  `5f225e81edafbfdcaab0b637d98ec59758445df6aad944a4a687e4ef4ea65fd8`.

See [source of truth v1.27](SOURCE_OF_TRUTH.md) and the
[Scope preflight contract](OPTIONS_SCOPE_PREFLIGHT.md). Authentic SPX/SPXW and
other required data, semantic setup/confirmation evaluators, shared-owner
integration, management, replay/export and all-cost prospective evidence remain
open. No provider/model/broker call, dependency, host or deployment changed.
Main stays untouched, PR #1 draft, LIVE disabled and the deployed experiment frozen.

## P4 historical full-cost dashboard comparison: 2026-10-13 UTC

The stored options observer now accepts an explicitly materialized historical
comparison for its existing population. A separate create-only installed CLI
checks the native export bundle, manifest/evidence hashes, arm accounting, SPY
endpoints and final source proof, then emits a bounded private view. Observer
reads bind its population/account/configuration/strategy and exact historical
event prefix; later appends are compatible, replaced history is not. A comparison
failure stays separate from independently readable current account evidence.

The panel shows dated net equity, independent model-off A, SPY's session-price
benchmark and cash. Entry/management model charges, unknown calls, venue fees,
data and host allocations remain visible in the session table. Cumulative curves
stop at the first incomplete paired session and never rebase across a gap. Current
marks remain separate and still exclude exit/data/host costs. Page reads perform
no evaluation, data/model work, execution ownership or source writes. The SVG
chart has text alternatives, patterned lines and exact tabular values; a skip
link and visible scroll-region focus support the responsive surface.

Pre-edit branch head was `89b0e4159a6c626695bbbc1fc84fb12583461634`, tree
`4f3e09bccefaa1032f8a452f3599afc2c31be200`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 remained open/draft.

Verification:

- **202 passed in 96.57s (0:01:36)** on the final noneditable installed package,
  outside source, warnings as errors. Five suites cover comparison view (32 new
  cases), observer, release identity, operator recovery and shared strategies.
  Materialization CLI runs isolated `-I` and verifies create-only output/rejection.
- Initial installed run: **200 passed, 2 failed in 100.58s**. A test constructed a
  Decimal field with an unvalidated string before serialization; another retained
  the removed placeholder's exact label. Both test-only corrections are included
  in the final 202 pass. Earlier source-only checks passed 30 cases with the
  installed CLI deselected, before the additional chart-gap case.
- Separate final-wheel integration materialized the completed two-session native
  arm D replay, then read it through authenticated HTML/API. The view reports
  historical net equity `953.53940`, preserving both entry and management charges.
  Journal and comparison bytes remain identical after reads; POST is rejected.
  This reuses actual completed replay evidence, not synthetic publication-unit
  proof alone. The replay's economic conclusion stays INCONCLUSIVE.
- Tests reject modified net/fee/model/SPY arithmetic, proof/hash/strategy mismatch,
  future boundaries, foreign populations/accounts/configurations, changed audit
  prefixes, unsafe paths/files and invalid seals. Unknown costs never become zero;
  incomplete paths do not reconnect. Long text is escaped. Reads cannot call the
  evaluator. Missing/invalid comparisons do not replace current metrics.
- Six application/template files and both edited test inputs match the final
  installed proof. Scoped lint/format, dependency and whitespace checks pass;
  100 checked local documentation links resolve.
- Final wheel SHA-256:
  `2fdf2382f0cde5fc1de3b432ac12391b466904a6c0d8502604403e747e83f01a`.

See [source of truth v1.26](SOURCE_OF_TRUTH.md) and the
[historical comparison contract](OPTIONS_COMPARISON_VIEW.md). The official
Chromium download again produced an unusable archive; no browser screenshots,
desktop/mobile visual acceptance or complete M8 claim is made. Authentic inputs,
prospective economics, host acceptance, overnight Swing, Scope and mixed ownership
remain open. No dependency, host, deployment, provider/model call or broker write
changed. LIVE stays disabled, main untouched and the deployed experiment frozen.

## P7 shared-family native replay/export: 2026-10-13 UTC

New optional `TapeHeader.swing` enrollment now drives the existing independent
A/B/C or A/B/C/D owners through the common Degen/Swing candidate universe. The
tape freezes the Swing policy alongside Degen setup/selection, enforces exact
daily/seed/catalyst/metadata identities and recording clocks, and includes both
families in the quote bound. The read-only shortlist uses only its available
prefix, retains first-valid supplied seed locks and reports missing/conflicting
coverage. Native accounts retain their own actual locks and account gates.

B's new scripted comparison uses an explicit shared SELECT/HOLD packet/prompt;
C/D retain full-entry reasoning, with D's identical entry script plus management.
Normal shared runtime eligibility still requires full-entry AI or model-off.
Old Degen packets, headers and configuration hashes are unchanged. Each owner
retains cash, settled funds, fees, entry/management costs, halts and audit history
across sessions. Export binds the native Swing policy to the tape and labels the
joint session-close universe without inventing standalone family returns.

Pre-edit GitHub head was `018471bf1acb69c28de4614b0e7471424ac0e11b`, tree
`edd736fc8ce0c01ef5d4cad61b4ce75d93a2e812`. Main was
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- Final noneditable installed build, outside source and warnings as errors:
  **229 passed, 1 failed in 589.90s (0:09:49)** across shared replay, market tape,
  narrow judgment/native worker, shared strategies and entry reasoning.
  The failure was a test expecting four distinct provider account labels. Legacy
  fixtures deliberately reuse a label across independent populations. The corrected
  test checks unique population ledgers and native order IDs. Its full two-session
  cost/continuity/isolation assertions then passed on the retained completed
  final-wheel native run; the six-minute replay was not repeated for this assertion
  correction. This is not reported as an all-passing 230-case pytest run.
- The final native run completed two full XNYS sessions for all four accounts,
  156 cycle slots per account, Swing entries/exits in both sessions, and D entry
  plus management receipts/filled-exit attribution. Every model role, venue fee,
  data and host allocation is retained. Both sessions report COMPLETE_ARITHMETIC;
  the economic conclusion remains INCONCLUSIVE. No virtual funds reset or inferred
  settlement was introduced. Separate unknown-cost replay leaves B halted while
  A/C/D continue independently.
- Installed isolated export CLI exited 0 from detached boundary copies. Its bundle,
  report and shared-universe metadata exactly match the final native replay output.
- Before the final packet validator/metadata addition, compatibility ran
  **210 passed, 1 failed in 106.72s**. The existing process-kill case missed its
  ten-second startup deadline during concurrent replay. Its final-wheel recheck
  passed **1 case in 17.98s**, unchanged deadline, and the final group above also
  passed it. Results overlap and are not summed.
- Initial new replay run: **15 passed, 2 failed in 372.18s**. Early full-session
  fixture slots omitted required Swing evidence, correctly halting all accounts
  before entry. The corrected fixture supplies point-in-time seed/metadata/catalyst
  inputs at each cycle; the final run above contains actual trades.
- Pure tape/shortlist checks passed 14 cases, including future/foreign/duplicate
  evidence, incomplete daily bars, quote capacity and immutable prefix locks.
  Scoped Ruff lint/format, dependency and whitespace checks pass. All six changed
  application files match the final installed wheel. Legacy header/frame/selector
  configuration serialization matches the preceding installed code exactly.
- Final wheel SHA-256: `fdfc1cf9c2b7375d7c15b532a06ce4e271affe03e6d9ef474f27fb56f6284bab`.
  Initial build: `a6b02f78eb1bd8bea92ef80e6909cb0558fd3532d65654fd8d429462fa62dd39`.

See [source of truth v1.25](SOURCE_OF_TRUTH.md) and the
[shared replay contract](OPTIONS_SHARED_REPLAY.md). Overnight Swing, additional
families, Scope/SPXW, mixed ownership, authentic provider/model evidence,
prospective economics, host acceptance and dashboard visual acceptance remain open.
No provider/model call, broker write, dependency, host or deployment change.
LIVE remains disabled, main untouched and the deployed experiment frozen.

## P4 installed-file release identity: 2026-10-12 UTC

Each new local options runtime generation now stores its own bounded installed-file
identity in `OPTION_RUNTIME_STARTED`. The observer displays that saved evidence;
page reads never inspect the web process's package. Earlier generations remain
explicitly unknown. The standalone `release` CLI inspects a noneditable wheel
installation without opening a population or loading trading credentials.

Inspection checks bounded metadata, the complete application inventory and each
file's SHA-256/size against RECORD, then derives a reproducible application digest.
The optional wheel hash is installer-declared provenance. Modified/missing/extra
files, symlinks, special files, oversized inputs, editable installs and unrelated
source imports cannot produce verified identity. This is local file consistency,
not dependency or loaded-memory attestation, process liveness or release approval.
Ordinary unavailable evidence has no execution authority; an unexpected inspection
exception follows the runtime's existing halt and shutdown cleanup.

Fresh pre-publish GitHub head was `393f57df5d5afc457b4ff7118971acb8fc0be01e`, tree
`e4965cb00a72ba16a47675e2549d33b49558d745`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- **65 passed in 42.49s** on the final noneditable wheel outside source, warnings
  as errors: release identity (27 cases) and continuous runtime (38). This includes
  the final unexpected-inspection-failure cleanup change.
- Before that final cleanup change, **207 passed in 108.87s** on the preceding
  installed build: release identity, runtime, observer, shared strategies and
  operator recovery. These overlapping results are not summed.
- Installed CLI reports `VERIFIED_FILES`, 151 application files and digest
  `590b4a5cabc7dfc00de18396c05291125f26e64a7711f57dbfa5a1f56b4c6e76`.
- Final wheel SHA-256:
  `728da7b89cde9c05287405d4e62e02f1959019528005a764d11301f4f18ff0b0`.
  Pre-cleanup wheel: `dcf81764c1b017670c80ad499c645cfc965cc0ea3158faf4f8cd2d1aa7567a30`.
- Scoped lint/format, compilation, dependency and whitespace checks pass. Changed
  application files and copied tests match their installed verification inputs.

See [source of truth v1.24](SOURCE_OF_TRUTH.md) and the
[installed identity contract](OPTIONS_LOCAL_RUNTIME.md#installed-release-identity).
Approved release provenance, target-host lifecycle/alerts/off-host recovery,
authentic provider/model evidence and full dashboard visual acceptance remain
open. No host unit, dependency, deployment, provider/model call or broker write
changed. LIVE stays disabled and the deployed experiment stays frozen.

## P7 shared Degen/Swing PAPER selection: 2026-10-12 UTC

The user's October 12 direction reinforces one AI selection boundary and one
execution owner across strategy families. A new opt-in `swing_policy` now adds
`SWING_DAILY_BREAKOUT` to the existing options PAPER coordinator, journal, lease,
cash ledger, order reservation and model budget. The full-entry AI receives both
families in one bounded packet and selects at most one candidate or HOLD. A
frozen family priority supplies the model-off comparison. Research A/B/C/D
accounts remain independent and their existing enrollment/serialized inputs are
preserved; joint-family replay enrollment is explicitly unsupported.

Swing seeds retain complete consecutive daily exchange bars, the next actual
XNYS session and a contract locked before that open. The first recorded valid
seed is immutable per symbol/session, including across restarts. Current completed
break-and-hold evidence, fresh explicit catalyst clearance, contract metadata and
chase bounds precede execution. Preparation and dispatch both recheck shared
candidate membership; Swing also rechecks its seed, session, current break/chase
and catalyst expiry. One unresolved order or unknown model charge fences the
common account. Existing deterministic sizing, full-premium funding, fees, all
entry/management costs and independent protection remain authoritative.

The stored observer now filters shared Degen/Swing candidates and shows their
setup blockers without performing trading work. The installed runtime accepts
joint-family settings and retains held-contract priority, one decision claim and
the existing operator recovery path. See [source of truth v1.23](SOURCE_OF_TRUTH.md),
[the delivered contract](OPTIONS_SHARED_STRATEGIES.md) and the
[fixture settings example](../examples/options-local-runtime-shared.json).

Fresh pre-edit GitHub head was `55d7beab938452ef07eb8b9bebff62f78d283322`, tree
`401fd9b4aeb39e3b79a0c345f7144053693ffa43`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- **242 passed in 101.65s (0:01:41)** on the noneditable final wheel outside source,
  warnings as errors. Six suites cover shared strategies (41 new cases), observer,
  entry reasoning/coordination/native worker and continuous runtime. Installed CLI
  and worker cases use isolated `-I` processes.
- **1 passed in 26.25s** on that final wheel: the specific existing managed-replay
  `EXIT_ALL-5-False` case that previously exceeded its native snapshot deadline.
  Its five-second limit was unchanged. This overlaps the broader run below.
- The earlier installed build ran 13 suites: **483 passed, 3 failed in 1204.50s
  (0:20:04)**. It covered shared strategy, execution, Degen, entry reasoning/
  coordination/judgment, position coordination, runtime, observer, operator,
  managed replay, first-session replay and multi-session replay. Two failures
  were test-harness expectations (isolated helper import and Swing status); the
  third was the existing `FixtureProcessTimeout` just rechecked. These are not
  reported as an all-passing run or added to the final count.
- Final-wheel initial run: **240 passed, 2 failed in 101.94s**. The contract-binding
  test hashed JSON strings instead of normalized typed values, hitting the earlier
  evidence-hash guard; it now constructs the intended exact-binding mismatch.
  An additional observer assertion still expected Swing `NOT_IMPLEMENTED` instead
  of `NOT_ENROLLED`. Both test-only corrections are covered by the final 242 pass.
- During development, partial-entry fixtures correctly blocked a protective close
  while the BUY remained unresolved; the full-fill test now exercises actual
  independent closing. A mistaken expected exit-reason name was corrected.
  The new native worker harness initially lacked the fixture package root;
  isolated reproduction confirmed `ModuleNotFoundError: tests`. Its corrected
  individual run passed, then passed again in the final group. No deadline relaxed.
- Scoped Ruff lint/format, compilation, pip check and whitespace checks pass.
  The shared runtime example validates. All checked local documentation links
  resolve. Ten changed Python modules and the template match installed bytes;
  copied tests match source. The final application was installed separately while
  the earlier replay tests ran; their package files were never replaced in use.
- Legacy Degen frame, full-entry packet and setup/selection hashes matched the
  preceding installed release exactly. No equity-suite or full-provider/host rerun;
  retained earlier proof remains below.
- Final wheel SHA-256: `b97dfec73265fa9a96f077568fafe8587778a5ac79df8a8c797987cd6c3d05c5`.
  Earlier broader-run wheel: `3b1007c881e9bd99c5e422ffd991c45c293b7477c67b41536bc937701106205f`.

This is **session-close PAPER fixture capability**, not complete M7. Overnight
Swing, additional Swing families, joint-family replay/economics, Scope/SPXW and
mixed stock/options ownership remain open. The first adaptation shares the current
intraday management context; no overnight horizon is enabled. Actual normalized
provider/model evidence, target-host lifecycle/alerts/off-host recovery, installed
release reporting and full dashboard/visual acceptance remain open. No authentic
provider/model call, broker write, host unit, dependency or deployment change.
LIVE stays disabled; the deployed experiment remains frozen and main/PR draft retained.

## P4 reviewed local operator recovery: 2026-10-12 UTC

A new opt-in, separately keyed options capability now lets an operator review one
committed snapshot and submit signed HALT/RESUME/REVOKE_KEY requests to the active
local PAPER owner. Submission only queues a private file; the runner applies one
bounded request before each protection tick. The observer remains read-only and
shows capability status plus bounded original command receipts without key access.

Commands bind the options protocol, journal/population, credential generation,
nonce, action, actor/reason, exact reviewed revision and a maximum five-minute
lifetime. RESUME preserves the existing revision/account/runtime/supervision/order
and cost gates inside the same fenced transaction, and rejects a pending decision
or stop. An unsettled call row always blocks recovery, including a costs-off
configuration. HALT/revocation reduce authority and can use a stale revision while
still requiring valid authentication and time. No trading, risk-policy or LIVE
command is accepted. Model packets never receive the operator capability or secret.

Same-ID/same-body repeats return the original receipt; different bodies conflict.
Journal application precedes fsynced receipt publication. Delivery errors retain
the request for replay and halt entry; replay does not clear a later delivery halt.
Key/directory/backlog failures fence entry while independent protection continues.
Old populations omit the optional field and gain no transport or changed policy
identity. [Source of truth v1.22](SOURCE_OF_TRUTH.md) and the
[recovery contract](OPTIONS_OPERATOR_RECOVERY.md) define exact operator procedures.

Fresh pre-edit GitHub head was `cadea741fd2192fb3052eb2ca0662be82ce8a695`,
tree `098b545857ec48fcb12f7f28128647b6f35534e3`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- **140 passed in 90.50s (0:01:30)**, warnings as errors, on the noneditable final
  release wheel outside source. Operator (49 new cases), runtime and observer
  suites include installed isolated-mode CLI review/submission and read-only HTML.
- **297 passed in 220.01s (0:03:40)** on the earlier installed application build,
  covering seven files: operator, runtime, execution, observer, Degen strategy and
  full-entry/position coordination. These overlap the final 140 cases and are not
  summed. All Python modules matched the subsequent UI build; the final release
  additionally guards malformed receipt shapes, covered by the final focused run.
- Coverage includes signing/tampering/domain/binding/nonce/time limits, replay and
  conflicts, exact revisions, unsafe account/cost/order/runtime/stop/pending-task
  recovery, key revocation/loss, model-secret separation and packet exclusion,
  bounded inbox/file handling, crash-before-receipt replay and independent
  protection after malformed receipt evidence.
- Scoped Ruff lint/format, compilation, pip check and whitespace checks passed.
  All 179 local documentation links checked resolve. Nine changed app modules and
  the template match installed bytes; copied tests match source. Both settings
  examples validate. No broader options/equity suite rerun; prior proof is below.
- Release wheel SHA-256: `baa0d93dd475b6a78b19979bad47d10edf2824fbcca4cbd6a8e0408af9bfe854`.

Earlier final-UI build: **139 passed in 93.77s**, before the receipt-shape guard.
These tests overlap the release proof. Malformed receipt metadata now produces an
entry fence while independent supervision continues.

Development:
Development first exercised 40 operator cases. The recovery test exposed an
unsettled-call row ignored by costs-off accounting; the shared resume gate now
checks unsettled rows explicitly. Invalid symlink requests now produce a safe
rejection receipt. Two test fixtures were corrected (OPEN_LONG and a closed file
read). The focused 195-case run had **194 passes and one FixtureProcessTimeout**
in an existing native management test; that isolated case then passed in 5.70s.
Final installed regression is required below; these are not extra distinct passes.

This closes the bounded local recovery surface, not complete P4 acceptance.
Actual normalized provider/model use, installed release identity, target-host
lifecycle/independent alerts/off-host recovery and desktop/mobile/full-dashboard
acceptance remain open. Key rotation/reprovisioning and remote control transport
are not implemented. P3 prospective/economic acceptance remains separate. No
authentic provider/model call, broker write, deployment, host unit or dependency change.
LIVE stays disabled; the deployed experiment is frozen and main/PR draft retained.

## P4 continuous local options PAPER runner: 2026-10-12 UTC

A new opt-in normalized-fixture runtime now drives the existing native Degen owner
continuously, with five-minute decisions and faster independent reconciliation and
protection. Optional selection/full-entry/management workers retain their existing
deterministic reviews and all known/unknown model charges. The latest private
packet is bound to the population, source time, sequence and original packet hash.
No provider normalization, automatic fill or settlement credit is invented.

Runtime enrollment freezes engine/strategy/venue identity, feed path and cadence.
Slots retain COMPLETE/SKIPPED/INTERRUPTED evidence. A fresh RUNNING heartbeat is an
additional new-entry gate; feed failure fences pending entry before the next native
snapshot wait. A requested stop immediately blocks new entry. Shutdown then retains
halts and unknown costs, cancels/drains decision work and releases the owner only
after cleanup. Restart retains interruptions and cannot resume entry automatically.

The stored observer now reads runtime freshness, observed exchange session and the
latest accepted frame in one committed snapshot. Pages still perform zero feed,
model, supervision or order work. Heartbeats do not prove process liveness; actual
release identity remains unknown. [Source of truth v1.21](SOURCE_OF_TRUTH.md) and the
[local runner contract](OPTIONS_LOCAL_RUNTIME.md) retain the exact scope and CLI.

Fresh pre-edit head was `357fe5ace0209e841559024b97e66741c7f078a8`, tree
`abdf1e0d62fea06517833f0ea786eeabe58842c2`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- **334 passed in 200.35s (0:03:20)**, warnings as errors, on the noneditable final
  wheel outside source. Eight files cover runtime (38 new cases), Degen strategy,
  option execution, full-entry coordination, position coordination, stored observer,
  entry judgment and position judgment. Installed CLI tests use isolated `-I` mode.
- Coverage includes native entry/fill/stop handling without an extra decision,
  protection during a paid management wait, charge/unknown-attempt retention,
  immediate feed-failure/stop-request entry fences, once-per-slot/missed-slot handling,
  source identity/time/sequence bounds, private file bounds, exclusive create/restart,
  interrupted shutdown, native supervision timeout, stale heartbeat entry gates,
  immutable observer/HTML reads and absence of LIVE authority.
- Scoped Ruff lint/format, compilation, pip check and whitespace checks passed.
  All 176 local documentation links checked resolve. Six changed app modules and
  the HTML template match installed bytes; all copied tests match source. The
  deterministic fixture settings example validates.
- Wheel SHA-256: `a8f250cd08afe9692e2c0302b8f19213e9cb910ba5f63bcae4934dabd2456bb3`.

Development source runtime group: **35 passed in 41.60s**; earlier runtime/observer
proof was **87 passed in 44.54s**. These overlap final proof. The first installed
run ended after progress output without a final summary and is INCOMPLETE, not a
passing result. The final wheel was installed after that process ended and all
eight files were rerun. Initial work fixed the restart schema-allowlist omission;
two test fixtures were corrected (Decimal serialization and fenced mutation).
Review found and fenced the pending-entry feed-failure and requested-stop windows.
The broader options/equity suites were not rerun for this slice; prior proof is
retained below.

This P4 runner slice has local fixture proof; full P4 provider/host/visual
acceptance remains open. Authentic
continuous exact data/model usage, installed release identity, reviewed recovery
surface, target-host lifecycle/independent alerts/off-host recovery and desktop/mobile
visual/full-dashboard acceptance remain open. P3 prospective enrollment/economics
and the remaining strategy families are separate gates. No dependency, host unit,
deployment, broker write or authentic provider/model call is part of this slice.
LIVE stays disabled; the deployed experiment is frozen and main/PR draft are retained.

## P3 whole-session analysis diagnostics: 2026-10-12 UTC

Optional manifest-frozen analysis now consumes the evaluator's verified paired
session net-equity differences. It fixes one primary B/C/D arm against A, block
length, minimum blocks, replicate count, seed, interval level and declared trial
IDs. Circular blocks preserve whole sessions; time blocks, calendar months and
optional predeclared regime labels expose concentration. All entry/management,
venue and allocated costs remain in the native accounting inputs. Independent
accounts, stored attribution and underlying benchmark gates remain intact.

Any incomplete declared session withholds the overall mean and interval without
shrinking the denominator. Incomplete group sums stay null. Secondary arms remain
descriptive; even a diagnostic interval above the hurdle cannot change the
INCONCLUSIVE economic conclusion or grant execution authority. Optional policy
omission preserves existing manifest hashes. [Source of truth v1.20](SOURCE_OF_TRUTH.md)
and the [analysis contract](OPTIONS_SESSION_ANALYSIS.md) specify the exact method,
reproducibility algorithm and limits.

Fresh pre-edit GitHub head was `72676fe0b021664f65b1da3596fead0eaf393708`,
tree `7e3b8563b24925f2b937689e92ba000277a960c6`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- **239 passed in 1256.53s (0:20:56)**, warnings as errors, on the noneditable installed
  wheel outside source using Python 3.12.14/OpenSSL 3.5.8. Eight files cover session
  analysis (31 new cases), evaluation, market tapes, journal export, first-session
  replay, multi-session replay, managed replay and the underlying benchmark.
- Source analysis tests: **31 passed in 14.90s**. Coverage includes frozen policy
  admission, legacy manifest identity, exact paired costs, known/unknown management
  charges, missing sessions, circular wrapping/final block truncation, quantile
  interpolation, deterministic seed/context, concentration and read-only CLI output.
- Scoped Ruff lint/format, compilation, pip check and whitespace checks passed.
  All 176 local documentation links checked resolve; three changed app modules
  match installed bytes and all copied proof test files match source.
- Wheel SHA-256: `be7327d0cda24bc22205df8b7d3c44eb841f093df4b76ee32b6cc0a38a2e454a`.

The broader options/Degen and equity suites were not rerun for this bounded pure
analysis change. The prior full options/Degen result remains recorded below.
No dependency, database schema, deployment script or service unit changed.

This is bounded offline diagnostic machinery, not completed statistical or
prospective acceptance. P3 still needs authenticated collection/coverage, frozen
trial/enrollment history and a justified untouched duration/precision design.
P1 actual provider/model usage and latency and P4 continuous runtime/UI remain
open. No deployment, broker writes, authenticated model calls or LIVE activation.
The deployed experiment remains frozen; main and PR #1 draft status are unchanged.

## P3 eligible long-underlying benchmark: 2026-10-12 UTC

The evaluator, native replay and exporter now support an explicitly enrolled
long-share comparator on A's approved deterministic CALL opportunities. It owns
separate cash, settled funds and shares; PUT/index opportunities stay cash. It
uses whole shares under the matched capital/risk envelope, later sized tape quotes,
spread/slippage/tick rounding, all share fees and explicit data/host allocations.
A/B/C/D retain their independent native accounts and all entry/management costs.
[Source of truth v1.19](SOURCE_OF_TRUTH.md) and the
[underlying benchmark contract](OPTIONS_UNDERLYING_BASELINE.md) define its exact
opportunity-schedule scope; this is not a separately rerun stock signal strategy.

Independent underlying stop/time exits require later executable bids. Partial
closes retain ownership; repeated source timestamps cannot create new size and
exit order fees are charged once. Optional underlying bid/ask share sizes preserve
legacy serialization/hashes when absent. Missing liquidity/cost/source evidence,
invalid settlement or open boundary exposure stays inconclusive and blocks a later
reset. Separate explicit between-session receipts alone release sale proceeds.
The enrolled comparison withholds totals when the baseline is incomplete.
SPY midpoint/session price and cash benchmarks remain separate.

Fresh pre-edit GitHub head was `26514e94fa18da767b54236a978fda430746a865`,
tree `cdf4505a06bb0b7d3e3d87773d683e03460c1df0`. Main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- **971 passed in 1601.84s**, warnings as errors, on the noneditable installed
  wheel outside source using Python 3.12.14/OpenSSL 3.5.8. Nineteen options/Degen
  files: the prior 945 cases plus 26 new underlying-comparison cases. Native
  fixture workers and installed CLIs used the installed package.
- The 26 new cases cover share fills and all fees/allocations; strict subsequent
  quotes; missing/stale/zero size and limit rejection; partial exits; repeated
  source/changed-receipt size; stop/time exits and low-priced liquidation;
  independent settled/risk/fee/share ceilings; PUT cash; source/cost uncertainty;
  old hash compatibility; separate identity/settlement admission; multi-session
  cash/cost continuity and invalid credit; installed read-only evaluation CLI;
  Decimal context independence; and native replay/export opt-in behavior.
- Development: 26 new cases passed in 113.55s; the 112-case accounting/tape group
  passed in 42.02s. These overlap the final suite and are not additional distinct
  acceptance counts. The initial missing-size case exposed uncertainty being
  erased by a later entry cancellation; the retained reason and regression now
  prevent that.
- Scoped Ruff lint/format, compilation, pip check, documentation links, seven
  installed/source app-file comparisons and copied-test comparisons passed.
  Whitespace checks passed. No dependencies, database schemas, deployment scripts
  or service units changed. No full equity-suite rerun or hosted CI was invoked.
- Installed wheel SHA-256:
  `bd5c6798becde865765b268385729b70fbb281ae63a71a5b9b45548e8cd9b4d4`.

This is local fixture/native-process proof. No provider/model call, broker write,
deployment or profitability claim is made. Actual normalized market/model evidence,
whole-session statistical/prospective evaluation, continuous options PAPER runtime/UI,
actual host lifecycle/alerts/off-host recovery, Swing/Scope/mixed ownership and the
finished dashboard remain open. LIVE is disabled, main remains untouched, PR #1
remains draft, and the frozen deployed experiment is unchanged.

## P3 arm D replay/export and stored attribution: 2026-10-12 UTC

Arm D now runs full entry reasoning plus bounded MAINTAIN/TIGHTEN/EXIT_ALL through
its own native PAPER owner, virtual clock and durable account. The same single-
and multi-session replay/export interfaces support explicit A/B/C/D enrollment;
legacy A/B/C requests remain supported. C/D entry scripts and model configuration
must match, while each account retains its own position, settlement, calls and
fills. [Source of truth v1.18](SOURCE_OF_TRUTH.md) and the
[managed replay/attribution contract](OPTIONS_MANAGED_REPLAY.md) define scope.

Stored observer opportunities and exported cycles now distinguish the proposal,
review, applied action, admitted model cost, prepared order, actual attempt and
native fill receipts. Managed decisions retain exact entry/revision linkage and
requested/applied geometry. Protective and discretionary exits have distinct
origins. Full paid receipts, consumption/review/tightening events and fill-table
coverage must agree; contradictory lineage is unavailable evidence. A prepared
or accepted close never becomes a fill without a later eligible quote/receipt.

Every admitted entry/selector and management call is counted once, including
known HOLD, MAINTAIN, rejected and late advice. Role-separated charges reconcile
to total model cost. A known charge completed after session close stays charged
to its starting session while the comparison remains inconclusive. Missing usage
and allocations remain unknown. D-versus-A and descriptive D-minus-C results use
independent portfolios after venue/model/data/host costs; neither proves alpha.
Independent mandatory exits continue during pending reasoning and override advice.

Fresh pre-edit GitHub/PR head matched `077dfe56bbda89019642332e714903306eb682c4`,
tree `fffc10d017fd9320c6befc66e816bc3b370b1a84`. Main matched
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 was open/draft.

Verification:

- **945 passed in 770.53s**, warnings as errors, on the noneditable installed wheel
  outside source using Python 3.12.14/OpenSSL 3.5.8. All eighteen options/Degen
  files: the prior 918 cases plus 27 new arm D/attribution cases. Native fixture
  workers and installed CLIs ran against the installed package.
- New cases cover a complete four-arm session, independent account/call/fill
  lineage, MAINTAIN/TIGHTEN/full exits, late and unknown advice, mandatory races,
  unfilled approvals, six stored-lineage corruptions, exact enrollment/matched
  entry scripts, installed four-arm export, two-session cash/settlement/cost and
  unknown-history continuity, four projection conflicts, and paid post-close usage.
- The 91-case source replay/export/observer regression group passed in 196.08s;
  it is development evidence, not an additional distinct acceptance count.
  Development initially caught a missing-history test fixture and an incorrect
  observer test invocation; both were corrected. An intermediate child run failed
  during environment replacement, and initial copied-test collection lacked its
  helper package. The clean installed run above supersedes those incomplete runs.
- Scoped Ruff lint/format, compilation, pip check, local documentation links,
  eleven installed/source app-file comparisons and all copied-test comparisons
  passed. Whitespace checks passed. No dependencies, database schemas, deployment
  scripts or service units changed; no full equity-suite rerun or hosted CI invoked.
- Verified wheel SHA-256: `c4c3e76dac4881497c702aa29124fd09b5866d1fcd3310df3c7d17e34ab837c1`.

This is local fixture/native-process proof. No authentic model/provider call,
broker write, deployment, browser visual acceptance or profitability conclusion
is claimed. Actual market normalization/model latency and usage, the eligible-
underlying baseline/prospective evaluation, continuous options runtime/UI, actual
host lifecycle/alerts/off-host recovery, Swing/Scope/mixed ownership and the
finished dashboard remain open. LIVE stays disabled, main remains untouched,
PR #1 remains draft, and the frozen deployed experiment is unchanged.

## P3 durable opt-in position management: 2026-10-12 UTC

The existing position reasoning worker is now connected to a separate opt-in
full-entry PAPER cohort. MAINTAIN records a reviewed decision; TIGHTEN atomically
improves the effective stop; EXIT_ALL prepares a full-owned-quantity native close
with immutable packet/plan/entry/revision protection. Native dispatch requires
the full paid receipt and fresh deterministic admission. The model receives no
broker tools or execution authority. [Source of truth v1.17](SOURCE_OF_TRUTH.md)
and the [management contract](OPTIONS_POSITION_REASONING.md) define the boundary.

The owner persists each bounded request before model-cost admission, requiring
exact frozen configuration, current ownership, original decision revision/lease
and available reserved call budget. Known usage survives unusable or late advice;
missing, foreign or interrupted usage remains uncertain and blocks further calls.
A captured revision can be consumed once, with its stop mutation or prepared
intent in the same transaction. Duplicate callbacks return the retained result;
a different source or changed plan cannot consume it again. A later slot may
reassess a newly captured revision; ordinary cost/heartbeat events do not make
unchanged ownership a different position.

Independent protection runs before and after reasoning. Fresh dispatch review
also persists any newly triggered mandatory latch, so rejecting a discretionary
exit cannot erase a target/stop after a rebound. Atomic write-failure tests retain
paid costs while rolling back both action and consumption. Cancellation keeps an
unknown attempt without retry; reopen retains the applied stop and completed
receipt. Interrupted or rejected exits retain existing uncertainty/recovery rules,
not automatic resubmission. Native receipts alone establish a PAPER fill.

Existing populations cannot adopt this policy on reopen. A/B/C replay is unchanged
and its exporter rejects managed cohorts rather than silently calling them arm C.
Arm D replay/export and dedicated proposal/approval/fill attribution are next.
No provider/model call, broker write, dependency, deployment script/unit or database
schema change occurred. The frozen deployed experiment is untouched.

Verification:

- **918 passed in 597.03s**, warnings as errors, using the noneditable installed
  wheel outside source on Ubuntu Python 3.12.3/OpenSSL 3.0.13. All seventeen
  options/Degen files: 32 new integration cases, one new exporter guard and the
  existing 885 contract/worker, execution, entry, replay/series, accounting/tape,
  admission, model, observer and capture cases. All copied test modules matched
  source; native installed worker/CLI paths were exercised.
- The 32 new owner-integration cases cover CALL/PUT actions, known/unknown/late
  costs, reserved-budget rejection before a child starts, partial-entry blocking,
  once-only consumption, changed ownership/halts/pending orders/quotes, mandatory
  races, atomic rollback, cancellation, reopen and native dispatch receipt tampering.
  A separate exporter case rejects a managed cohort labeled as arm C.
- Source development run: 32 passed in 49.36s, warnings as errors. It is not
  counted again as distinct proof. Native PAPER submit/fill paths run against the
  local durable fixture venue; model responses are scripted.
- Scoped Ruff lint/format, compilation, pip check, five installed/source module
  byte comparisons, 157 local documentation links and whitespace passed.
- Verified wheel SHA-256:
  `effa7a3040ed70e2eee18eed54764f86443f8e8d9a068b23c245944e750a62b1`.

This is local fixture/native-process proof. No full equity-suite rerun, hosted CI,
authentic model/feed acceptance, target-host installation or profitability claimed.
Actual normalized data/model usage and latency, continuous options runtime/UI,
prospective frozen evaluation, lifecycle/alert/off-host recovery, Swing/Scope/mixed
ownership and the polished dashboard remain open. LIVE is disabled. Main remains
untouched and PR #1 remains draft.

## P3 position proposal/review and bounded native worker: 2026-10-12 UTC

`app.options.position_reasoning` now defines strict MAINTAIN/EXIT_ALL/TIGHTEN
proposals and fresh deterministic review for one exact owned option position.
The packet retains original entry thesis/protection, effective invalidation,
current completed context, quotes/account, position revision, frozen policy/model
binding and original decision lease. Neither proposals nor reviews have execution
authority. [Source of truth v1.16](SOURCE_OF_TRUTH.md) and the
[position-reasoning contract](OPTIONS_POSITION_REASONING.md) record the boundary.

Wrong/revised ownership, unknown references, widened/crossed stops, stale/foreign
market evidence, halted/unknown account and unresolved orders cannot yield an
eligible discretionary change. EXIT_ALL requires fresh close admission for the
entire authoritative owned quantity. A smaller displayed size rejects instead of
silently scaling out. The existing stop/premium/time/expiry/target calculations
now live in a shared pure protection function used by both the native supervisor
and management review. Original latches/timestamps and stale-data behavior remain.
Mandatory protection overrides MAINTAIN, EXIT_ALL and TIGHTEN alike.

`position_judgment` and its installed native worker freeze prompt/schema, model,
prices, token/process limits and management policy. Request binding requires the
native packet's cost policy to match. The child counts the exact strict request
before one generation, with no tools, retries, broker credentials or journal
handles. Pipes/deadlines/parent watchdog and process-group cleanup remain bounded.
Known observed usage survives rejected/late output; missing or foreign usage is
uncertainty, not free cost. Error MAINTAIN cannot override independent exits.

No coordinator or deployed service invokes this worker. This slice does not admit
durable management attempts, settle charges, consume revisions or apply model
stops/exits. Repeated pure review is not deduplication. New-cohort opt-in durable
integration is next, followed by D replay/export and stored observer attribution.
Existing A/B/C configurations, schemas, replay and the frozen deployment remain
unchanged. No provider/model call, broker write or LIVE activation occurred.

Verification:

- **885 passed in 527.39s**, warnings as errors, using the noneditable installed
  wheel outside source on Ubuntu Python 3.12.3/OpenSSL 3.0.13. All sixteen
  options/Degen files: 157 new management contract/worker cases and the existing
  728 execution, entry, replay, series, accounting, tape, admission, model,
  observer and capture cases. The 157-case source development run is not counted
  again as distinct proof.
- Tests cover CALL/PUT MAINTAIN/EXIT_ALL/TIGHTEN; exact owned quantity and effective
  stop boundaries; changed/closed ownership and revisions; all six mandatory/latch
  triggers against each action; unknown/halted account and unresolved orders;
  source identity, freshness, deadlines, strict schema and packet revalidation.
- Real SDK serialization uses fake responses, with exact count/generation payloads,
  no tools and retained rejected/late usage. Native child tests cover fixed SDK
  origin and credential environment, timeout/overflow/bad output, lineage/cost
  mismatch and repeated cancellation with process reaping. No authentic API call.
- Existing native execution and A/B/C single/multi-session replay regressions pass
  with the shared protection function. No management actions are dispatched.
- Scoped Ruff lint/format, compilation, pip check, 95 local documentation links,
  five installed/source module byte comparisons and whitespace passed. No
  dependency, deployment script, unit or database schema changes. No full equity
  suite, hosted CI, provider acceptance or deployment claimed.
- Verified wheel SHA-256:
  `765589b934c41c479f57a24c490e0ba8080f074243b6f3ffcf0348c93af8e8a7`.

Authentic normalized market/model evidence, continuous options PAPER runtime,
polished UI, prospective frozen collection and actual host/recovery acceptance
remain open. This is local fixture/native-process proof, not deployment or
profitability. Main remains untouched and PR #1 remains draft.

## P3 continuous multi-session PAPER replay and boundary export: 2026-10-12 UTC

The native A/B/C replay now accepts an ordered predeclared series of sealed tapes
on the same three independent PAPER accounts. Bankroll, settled cash, positions,
high watermark, fees, model attempts/costs, halts and sequence continue across
sessions. No new day resets an account or clears uncertainty. Explicit frozen
`FUNDS_SETTLED` receipts may release actual unsettled sale proceeds between
sessions; there is no inferred settlement credit or invented exercise/expiry close.
[Source of truth v1.15](SOURCE_OF_TRUTH.md) and the
[multi-session contract](OPTIONS_REPLAY_SERIES.md) record scope and continuation.

Each completed arm/session retains a private consistent closing journal snapshot
and scheduler receipt. Snapshots contain no execution authority companion or venue
and are not usable execution backups or proof of off-host protection. The series
exporter reads cumulative snapshots without attaching authority, verifies native
owner/configuration and prior audit/economic history, then extracts each day's
new evidence. Later opening balances equal the preceding close exactly. Removing
or changing old calls/orders, replacing an owner, resetting cash or omitting a
boundary cannot silently create a complete comparison. Late historical corrections
currently make export unavailable; no correction/revaluation protocol is claimed.

Legacy single-session CLI requests remain supported. Both installed CLIs also
accept ordered series requests. Tape loading is incremental and bounded; native
journal/audit/venue capacities remain in force. No pruning/reset, automatic resume,
provider/model call, broker write, service installation or LIVE activation occurs.
Missing costs, skipped slots and carried exposure keep comparisons inconclusive.
Even complete arithmetic and minimum sample count do not establish profitability.

Verification:

- **728 passed in 538.49s**, warnings as errors, on the noneditable installed
  wheel outside source using Ubuntu Python 3.12.3/OpenSSL 3.0.13. All fourteen
  options/Degen test files: 20 new series cases plus 708 existing replay,
  accounting/tape/export/admission/execution/model/entry/observer/capture cases.
- Two full 78-cycle sessions run through each native A/B/C owner. Original cash
  1,000 carries to 976.80 and then 953.60; explicit 384.40 funds receipts change
  spendable funds, not total cash. Fees and known model/data/host costs are charged
  once, and each second-day opening equals the first-day close.
- Tests cover no implicit settlement, retained unknown cost/halt and open exposure,
  seven historical-source conflicts, invalid settlement amount/sequence/time/ID,
  interruption retaining a completed boundary, authority-free read-only export,
  both installed series CLIs and incremental combined tape capacity.
- Scoped Ruff lint/format, compilation, pip check, 115 local documentation paths,
  five final installed/source module byte comparisons and whitespace passed.
  No dependency, deployment-script or service-unit changes. No full equity-suite
  rerun, hosted CI, authenticated provider/model acceptance or deployment claimed.
- Verified wheel SHA-256:
  `283bf067c22d07d0d68980936fbfefcfa62121e109fc0ea693c6e68228e4938f`.

Next P3: position reasoning with deterministic review, mandatory-exit precedence
and monotone protection, then stored proposal/approval/fill attribution. Authentic
normalized market/model evidence, continuous options PAPER runtime, polished UI,
prospective frozen collection and actual host/recovery acceptance remain open.
This wheel is local fixture proof and has not been deployed. The separate operator
release and frozen legacy experiment below remain unchanged. LIVE stays disabled.

## P3 native first-session A/B/C replay scheduler: 2026-10-11 UTC

The dedicated scheduler is now implemented in `app/options/replay.py`, with a
private installed CLI and explicit scripted model protocol. It consumes the
sealed common tape through independent native A/B/C PAPER owners, then invokes
the existing automatic journal exporter and paired accounting evaluator.
[Source of truth v1.14](SOURCE_OF_TRUTH.md) and the
[replay contract](OPTIONS_REPLAY.md) record scope and continuation.

Each arm has its own virtual clock, bankroll, journal, venue and position. Model
completion suspends only that arm; delivered market updates continue. Fresh entry
approval uses the latest available quotes, with all equal-time receipts processed
before a scripted completion. Original leases/process limits still reject late
responses. Known usage remains charged; missing/unknown responses retain unknown
cost. Occupied intervening slots are reported as skipped, never backdated.

Only subsequent delivered quotes with source time strictly after decision creation
can fill. Exact identity, entitlement, freshness, fixed limits, adverse slippage
and unused whole-contract size remain enforced by the native fixture venue.
Independent protection runs on market changes and exit timers. DAY expiration is a
local fixture outcome, not a broker cancel. Missing exit quotes retain exposure;
no fill, close, settlement or missing model receipt is invented.

The create-only private run directory retains original settings/tape admission,
exact strategy/script hashes before any cycle, three native sources and the
exported result. Interruptions leave evidence and no result receipt; existing
targets cannot resume or be overwritten. Scripted response/usage attribution is
explicit. No API key, model/provider call, live placement or broker write occurs.
Default native model paths and previously enrolled cohorts retain their existing
configuration and validation. This wheel has not been deployed.

Verification:

- **707 passed in 298.26s**, warnings as errors, on the noneditable installed wheel
  outside source using Ubuntu Python 3.12.3/OpenSSL 3.0.13. All thirteen
  options/Degen files: the first 13 scheduler cases and the existing 694
  accounting/tape/export/admission/execution/model/entry/observer/capture cases.
- Final timing review added an explicit all-equal-time-receipts-before-completion
  rule and its regression case. The targeted source test passed in 5.76s.
  Rebuilt final wheel: **14 replay tests passed in 126.85s**, warnings as errors,
  outside source. The broader 707-case run preceded that scheduler-only correction;
  it was not repeated or counted as 721 distinct tests.
- The full-session fixture runs all 78 cycles separately for A/B/C. Scripted delays
  produce first fills at +1s (A), +3s (B) and +2s (C), with later independent exits
  and automatic complete arithmetic. This is mechanical fixture proof, not AI
  performance or profitability evidence.
- Late/paid HOLD/unknown/missing responses, busy-slot omission, changed-market
  rejection during reasoning, whole partial fills, missing exit quotes, unfilled
  DAY expiration, task interruption retaining unknown cost, create-only refusal,
  mismatched tape rejection and installed CLI/private-input checks pass.
- Scoped Ruff lint/format, compilation, pip check, 99 local documentation paths,
  five final installed/source module byte comparisons and whitespace passed.
  No dependency, deployment script or service-unit changes. No full equity-suite
  rerun, hosted CI, authentic provider/model acceptance or target-host claim.

Final wheel SHA-256:
`6957f942474ad8615a0494dd1148782716ea06720efc24a960a3c4d168bd2fd4`.

Next bounded P3 step: explicit multi-session opening state and settlement in the
runner/exporter without resetting capital or losing unknown history, then position
reasoning and stored proposal/approval/fill attribution. P1 authenticated normalized
market/model evidence, continuous options runtime, required finished UI,
prospective sessions and host/recovery acceptance remain open. The older deployed
experiment stays frozen; LIVE remains disabled, main untouched and PR #1 draft.

## P3 automatic native A/B/C first-session export: 2026-10-11 UTC

`app/options/evaluation_export.py` and its installed CLI now build the paired
comparison from actual retained native PAPER journals, rather than requiring
caller-assembled orders, costs and closing balances. [Source of truth v1.13](SOURCE_OF_TRUTH.md)
and [the export contract](OPTIONS_EVALUATION_EXPORT.md) define this bounded step.
The independent virtual-clock strategy replay runner is still open; this slice
completes its native result-extraction dependency. Existing engine, coordinator,
provider collection and deployed populations are unchanged.

The reader uses the existing private bounded observer transaction, without opening
an execution owner, venue, model key or authority pair. Each arm must match its
frozen native limits/policy, population and A/B/C strategy configuration. The
strategy digest retains setup/selection and model/entry configuration while
excluding only the private key-file path. The exact common tape binds session and
market limits. Sources may be detached journal copies with no execution authority.

Extraction checks contiguous audit events, cycle starts/completions and frame
hashes, exact order attempts/observations, full matching fill rows, receipt IDs,
model admission/usage events and frozen-rate costs. Retained model results cannot
lose their attempt/cost rows and appear free. Native closing cash/settled funds/
ownership and snapshot order/receipt coverage are checked. Known HOLD costs stay
charged; legitimate unknown calls, interrupted cycles, absent slots/allocations and
incomplete closing evidence remain inconclusive. Structural contradictions fail
export. No fills, settlement, balances or missing scheduler rows are invented.

The first version supports exactly one first session per native journal. Earlier
activity is rejected rather than resetting capital or inferring a historical
opening balance. Multi-session opening state and settlement boundaries remain
unimplemented. Every arm read is internally consistent; the three independent
journals are not one global atomic snapshot or a funded multi-owner system.

The export returns an evaluator-ready bundle, path-free source revisions/hashes
and the sealed-tape comparison report. The installed private request CLI prints
that envelope without writing source/output files; exit 0 is complete arithmetic,
1 inconclusive and 2 sanitized unavailable evidence. The economic conclusion always
remains INCONCLUSIVE. This does not authenticate provider data, actual paid model
behavior, source completeness against owner tampering or prospective enrollment.

Verification:

- Noneditable installed wheel outside source, Ubuntu Python 3.12.3/OpenSSL 3.0.13:
  **694 passed in 181.51s**, warnings as errors. All twelve options/Degen files,
  including 23 new exporter cases and all prior tape/accounting/admission/native
  execution/model/entry/observer/capture regressions.
- Native test fixture runs all 78 session cycles separately for A, B and C. A opens
  and closes a real local-venue whole-contract position using subsequent recorded
  quotes and independent protection. Mocked B/C responses HOLD and retain known
  model usage. Native accounting exports A net change -$23.23 and B/C -$0.03015 each
  after explicit fixture costs. These are test expectations, not observed strategy
  performance or model-selection evidence.
- Detached source copies have no authority pair/venue/key; export succeeds without
  creating them or changing database bytes. Damaged definitions/strategy/events/
  attempts/fills/cycles/costs/snapshots fail. Missing scheduler slots and unknown
  costs/closing state remain visible. Decimal-context independence and installed
  CLI complete/unavailable behavior pass; output omits source paths and credentials.
- Initial 22 focused cases passed in 68.06s. Final review added an omitted-attempt/
  cost case where the native model result is still retained, plus receipt identity,
  venue and common-limit checks. No existing protection was relaxed.
- Scoped Ruff lint/format, compilation, pip check, two installed/source module byte
  comparisons, 88 local documentation paths and whitespace checks passed. No dependency
  lock, deployment script, service unit or existing engine behavior changed.
- Verified installed wheel SHA-256:
  `2b9ceb59bad1c43a6d1bc1c08b721d5f2f2002ad2c2acf4aaeb0b5d43f2ba1bd`.

Pre-edit canonical branch/local/PR head:
`a586a4be34a678131f2525340002c93defef4563`, tree
`a29f12d1cc0cb40e706e79a15a3a8eed919d84a0`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays draft.
No full equity-suite rerun, hosted CI, actual provider/model call, production
capture, new deployed enrollment or deployment occurred. The frozen deployed
experiment remains unchanged and LIVE disabled.

**Next P3:** connect the dedicated A/B/C replay scheduler with independent virtual
clocks/portfolios, actual completion delays and subsequent tape-driven fills to
this exporter; add explicit multi-session opening/settlement state. Then position
reasoning and observer attribution. Authentic data/model acceptance, continuous
options runtime/UI, independent host/alert/archive recovery, prospective evidence,
M7 families and M8 visual finish remain open.

## P3 sealed shared market tape and recorded comparison: 2026-10-11 UTC

`app/options/market_tape.py` adds a separate create-only fixture recorder and
source-independent sealed reader. `recorded_evaluation.py` connects its retained
content to the paired evaluator. [Source of truth v1.12](SOURCE_OF_TRUTH.md) and
[the tape API/boundaries](OPTIONS_MARKET_TAPE.md) distinguish delivered market-stage
replay from the still-open full A/B/C portfolio runner and automatic ledger exporter.
No existing cohort, provider collector, execution service or dashboard uses the new
recorder yet. Authenticated normalized acquisition remains unverified.

The header binds one exact complete XNYS session, declared experiment/time, setup,
contract-selection policy and limits. Each frame retains source/receipt/recording
times, a contiguous sequence and previous-content hash. Cycle slots are unique;
only completed bars are accepted, and future receipts/nested metadata or foreign
sources/universes are rejected. Quote-only updates support subsequent fill evidence
and SPY boundaries. Missing inputs can be retained as empty cycle frames. Recording
a slot is not proof of usable data or actual strategy execution.

The API creates a new owned private file, syncs each successful append and writes
an explicit final seal. Close never seals; no overwrite/reopen/resume/prune/retry
operation exists. Partial write/sync failure poisons the writer. The reader rejects
unsealed/truncated/changed/oversized/non-private/symlink/special files and verifies
the entire chain. Boundaries: 4,096 events, 256 KiB per line, 32 MiB per tape and
64 MiB combined normalized tape evidence for evaluation. Same-host owner replacement
remains possible; no authentication, prospective enrollment witness, hardware
immutability or off-host protection is claimed.

The replay view exposes only recorded events available by the requested instant.
`replay_shortlist` reruns the existing completed-bar scanner and exact contract
planner at the original cycle time. It never substitutes later history or a current
chain. It does not perform account admission, model calls, portfolio management or
order simulation. Independent A/B/C portfolio state still requires the next runner.

`evaluate(bundle, tapes=...)` and optional repeated CLI `--tape` arguments verify
exact experiment/session/limits/digest bindings, all planned cycle slots, frame
hashes, model/entry timing, actual fill-quote availability and both recorded SPY
endpoints. Existing accounting checks remain authoritative. Missing content retains
the denominator and suppresses paired/aggregate totals; malformed tapes are
unavailable. Reports distinguish supplied hashes from sealed local fixture content.
Economic conclusion remains INCONCLUSIVE, even with complete recorded arithmetic.

Verification:

- Noneditable installed wheel outside source, Ubuntu Python 3.12.3/OpenSSL 3.0.13:
  **671 passed in 113.00s**, warnings as errors. All eleven options/Degen files,
  including 49 new tape cases and all prior accounting, admission, native execution,
  model/entry, observer and capture regressions.
- Includes native PAPER round-trip quote binding; matched after-cost accounting;
  missing/hash/frame/source/limits/SPY mismatches; delayed fill/cycle observations;
  original-time shortlist replay with no future fallback; metadata/bar/clock guards;
  changed seals/order/truncation; private create-only files; typed-copy revalidation;
  installed CLI complete/inconclusive/unavailable outcomes and unchanged sources.
- Actual SIGKILL after a synced append preserved the header/event prefix; it could
  not load as a sealed tape or resume. Injected partial write also prevented sealing.
- Initial focused run exposed the new adapter's mistaken `quote_source` field name
  (corrected to existing `option_source`) and a tuple-versus-mapping fixture mistake.
  A subsequent run passed 44 cases with one decimal-display assertion mismatch;
  corrected to exact Decimal comparison. No production protection was relaxed.
- Scoped Ruff lint/format, compilation, pip check, four installed/source module
  byte comparisons, 78 local documentation paths and whitespace checks passed.
  No dependency locks, deployment scripts, service units or existing engine behavior
  were changed. No full equity-suite rerun or hosted CI was performed.
- Verified installed wheel SHA-256:
  `3bd55dfd43685c4f8c1e78aa5191569d3cdfc35540a19161d4461e381026f5e3`.

Pre-edit canonical branch/local/PR head:
`2b2b3c987dc7515b2e5ed19f9642a46b3b828733`, tree
`0e5e5a3107bf7354b42e3f51fbb0dbfdd2f78a8e`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays draft.
This release is not installed on the target host. No authentic provider/model call,
broker write, production capture, new experiment enrollment or deployment occurred.
The frozen deployed experiment remains unchanged and LIVE disabled.

**Next P3:** run A/B/C strategies with their independent ledgers against this common
tape and export their complete ledger/model receipts automatically, then add exact-
position reasoning and observer attribution. Actual normalized market/model evidence,
continuous options runtime/UI, independent host/alert/archive recovery, prospective
frozen evaluation, M7 families and M8 visual finish remain open.

## P3 first paired session accounting evaluator: 2026-10-11 UTC

`app/options/evaluation_models.py`, `evaluation.py` and `evaluation_cli.py` add
bounded, read-only A/B/C **accounting replay of supplied fixture evidence**.
[Source of truth v1.11](SOURCE_OF_TRUTH.md) and
[the delivered API/boundaries](OPTIONS_EVALUATION.md) distinguish this kernel from
the still-open shared recorder/export and strategy-rerun harness. No active
strategy, cohort, provider, execution service or dashboard uses the evaluator yet.

The manifest declares distinct virtual populations, matching capital/risk/fill
assumptions, strategy/tape bindings, complete ordered XNYS sessions, enrollment
time, explicit model/data/host cost assumptions and a descriptive hurdle/sample
minimum. Hashes bind supplied content; they do not authenticate enrollment, market
data, source completeness or the strategy that produced an outcome. Only the
`LOCAL_FIXTURE` evidence kind is accepted. No additional funded owner is created.

Replay uses existing exact cash/lot/fill/settlement accounting and the engine's
extracted pure fill-evidence validator. The authoritative engine delegates to the
same unchanged validation logic. All observed fills must use quotes strictly after
decision completion, fit exact order/attempt/lifetime/price/size/debit constraints,
and preserve complete event sequence and cash/ownership conservation. Known
model costs include HOLD calls; unknown usage or missing data/host allocation is
never zero. Between-session funds settlement preserves cash and sequence. Missing
prior ledger evidence cannot reset capital and resume a later comparison.

All declared sessions remain visible. Unresolved orders/cycles, open boundary
positions, missing slots, mismatched frame coverage or invalid SPY endpoints make
the pair inconclusive. Any incomplete pair suppresses overall comparison totals,
preventing complete-case cherry-picking. Complete arithmetic reports price P&L,
fees, turnover, costs, net changes/returns, B/C differences versus A, worst session
and session-boundary drawdown. SPY is explicitly midpoint price-only, with session
compounding that excludes overnight gaps, dividends and benchmark execution costs;
it is not buy-and-hold total return. Cash price return is zero. The economic
conclusion always stays INCONCLUSIVE; fixture arithmetic/sample counts cannot
establish alpha. Underlying-only and management-D baselines remain unimplemented.

The installed CLI accepts an existing bounded regular JSON bundle, rejects links/
special/oversized/changing files, emits sanitized unavailable results for invalid
input, and writes no trading state or output file. No production bundle exists yet.
It cannot create/adopt/recover a journal, collect data, call a model or place orders.

Verification:

- Noneditable installed wheel outside source, Ubuntu Python 3.12.3/OpenSSL 3.0.13:
  **622 passed in 111.73s**, warnings as errors. All ten options/Degen files,
  including 48 new evaluator cases and existing execution, native workers, entry
  coordination, observer and capture regressions.
- New proof includes replay of real native local-venue round trips; cash/fees/
  turnover, model-funded entries, HOLD costs, multi-session continuity/settlement,
  incomplete denominator retention, no invented open-position marks, old-quote
  exclusion, duplicate order/source identity, receipt/sequence/debit/fee/price
  damage, definition/calendar/money
  validation, source matching, SPY endpoint rejection, Decimal-context independence,
  content hashes and the installed read-only CLI/symlink rejection.
- Initial focused tests exposed a session-date versus scheduler-slot identifier
  mismatch in the new calendar adapter. It was corrected to `session_date`; the
  complete-session and enrollment requirements were retained. Final full run passed.
- Scoped Ruff lint/format, compilation, pip check, 71 local linked paths, five
  changed module wheel/source byte comparisons and whitespace checks passed.
  Dependency locks, deployment scripts and service units are unchanged.
- Verified wheel SHA-256:
  `ed1c0303b7ea1834e4df5615aa92a84434bf3012a9b087f89278233ee34da966`.

Pre-edit canonical branch/local/PR head:
`6ffaa64dce9f8390e5c21df84fcf5f98b819650f`, tree
`5efbd20721d4e3d58b069d59ab89d5cbb712e772`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays draft.
No full equity-suite rerun, hosted CI, authentic market/model call, broker write
or deployment is claimed. The frozen deployed experiment remains unchanged and
LIVE disabled. No economic outcome is claimed from fixture tests.

**Next P3:** connect an immutable common market recorder/evidence exporter and
A/B/C strategy replay to these independent ledgers, then exact-position reasoning
and observer attribution. P1 actual samples/normalization and authentic model
acceptance, P4 options runtime/UI, independent host/alert/archive recovery,
prospective frozen evidence, M7 families and M8 visual finish remain open.

## P2 full-plan durable PAPER integration: 2026-10-11 UTC

The broader entry model now connects to the existing single-owner options PAPER
coordinator, accounting and independent protection. This is **local fixture and
installed-package proof**, not authentic provider acceptance or deployment.
[Source of truth v1.10](SOURCE_OF_TRUTH.md) and
[the delivered entry API](OPTIONS_ENTRY_REASONING.md) record the current boundary.

New healthy, untraded populations can explicitly enroll `entry_policy` alongside
their model limits/key path. The frozen strategy stores the exact entry-model
configuration. Existing selector populations cannot adopt it or change policy.
The new `entry_coordination` module records the complete request before durable
model admission, retains result/completion evidence before usage settlement, and
never replays an interrupted slot. Known charges survive HOLD, late or rejected
output. Missing/foreign usage halts with unknown cost; mismatched count/usage
retains known cost and halts. The existing native worker still has no broker tools.

Preparation and dispatch require the full stored matching request/result and
paid plan receipt. They freshly review geometry, entry condition, account/budget,
session binding and original authority. Passing only the old nested proposal is
rejected for this new cohort. The order retains complete evidence plus immutable
packet/plan hashes, underlying target and absolute horizon. Both entry order
lifetime and position exit time are capped by the earlier plan/deterministic limit.
Partial fills and replayed authoritative accounting preserve these exact terms.
Changed or missing protection in a venue snapshot is rejected.

Independent supervision latches CALL targets on bid and PUT targets on ask, with
existing invalidation/catastrophe/time/expiry precedence. Targets and exit horizons
survive restart without another model call. Time exits latch even when quotes are
missing, retaining blocked/unpriced exposure. A working partial entry can block a
protective close; its actual fills, protection and sticky exit are retained without
an invented cancellation, replacement or flat state. These are fixture order
semantics, not accepted broker behavior. Legacy absent fields serialize exactly
as before; no new tables or migration of frozen cohorts are introduced.

Verification:

- Noneditable installed wheel outside source, Ubuntu Python 3.12.3/OpenSSL 3.0.13:
  **574 passed in 89.71s**, warnings as errors. All nine options/Degen test files,
  including 22 new integration cases and existing admission, execution/native
  children, entry/selector workers, observer and capture regressions.
- New cases cover CALL/PUT entry, complete paid receipts, fill/restart/target exit,
  conservative spread sides, sticky exit, partial fills, time exit without quotes,
  no fill beyond horizon, old cohort rejection, proposal-only bypass rejection,
  HOLD/unknown/foreign/late/malformed/count/error outputs, cancellation without
  replay, removed receipt/cost/protection and fresh dispatch rejection when target,
  condition or horizon changes. Real venue children are used; model responses are
  mocked. Prior worker main/SDK mock tests are included in the regression run.
- The first broad run had 573 passes and one test-fixture failure: a modified
  snapshot reused its old ID and hit the earlier identity-conflict guard. Giving
  the fixture a distinct snapshot ID exercised the intended protection mismatch;
  the full rerun passed. No production guard was relaxed.
- Scoped Ruff lint/format, compilation, pip check, 78 local linked paths,
  six changed wheel/source module byte comparisons and whitespace checks passed.
  A truncated local cryptography binary initially prevented test collection; the
  same locked version was reinstalled locally. Repository locks were unchanged.
- Verified wheel SHA-256:
  `72a78ebf58c17170a7953ca3126a92f0c3faa694210c48a9662bb5ddbab0715b`.

Pre-edit canonical branch/local/PR head:
`1e01aab135147eeedefdc09067572e213f0a6108`, tree
`ea429c018bfe41782598a6c71e4bc9a36421ccb1`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays draft.
No full equity-suite rerun, hosted CI, authentic market/model call, broker write
or deployment is claimed. The frozen deployed experiment and separate previously
validated host release remain unchanged. LIVE stays disabled.

**Next:** P1 actual bounded market samples/normalization and authentic model
latency/usage acceptance remain pending. P3 comparative economic ledgers and then
exact-position reasoning can proceed locally from this complete entry path.
P4 continuous options runtime/functional UI, host lifecycle/independent alerts/
off-host recovery, prospective frozen evidence, M7 families and M8 visual finish
remain open. No profitability or LIVE-readiness conclusion follows from this slice.

## P2 bounded entry model worker: 2026-10-10 UTC

`app/options/entry_judgment.py` and `entry_judgment_worker.py` add the separate
native request protocol for the broader entry contract. See
[its API and durable integration boundary](OPTIONS_ENTRY_REASONING.md).
This is **local fixture and installed-package proof**, with fake provider
responses, not authentic model acceptance, deployment or a changed trading cohort.

The request freezes prompt/schema/configuration hashes, model/cost/token limits,
policy, parent identity and remaining original opportunity deadline. One tool-less
strict-schema payload is counted before a single generation attempt; maximum
configured charge must fit the per-call reservation. The child uses a fixed SDK
origin, no retries, stripped environment and bounded pipes. The parent reaps
children on protocol failure, timeout and repeated cancellation; the existing
parent/deadline watchdog is reused. The model receives explicit evidence IDs and
binding hashes. Returned plans must match identity, usage and original geometry.
Rejected responses become bound HOLDs with valid captured usage retained; missing
or mismatched usage remains evidence for the future durable caller, never assumed
zero cost. Provider error text is not echoed. No broker handles or tools are passed.
This process boundary is not an OS sandbox.

**Next P2 slice:** durably admit/freeze the new request, retain the complete plan
and receipt, settle known usage or halt on uncertainty, then fresh-review at
dispatch and enforce target/absolute horizon independently. The existing engine
stores an exit time but not this model target; forwarding only its old proposal
would lose required terms. The current SELECT/HOLD coordinator remains unchanged.
No new service or population invokes this worker. P1 actual market samples and
normalization, P3 management/evaluation, P4 runtime and M8 dashboard remain open.

Verification:

- **160 passed in 33.79s**, warnings as errors, in the noneditable installed wheel
  outside source on Ubuntu Python 3.12.3/OpenSSL 3.0.13. Includes 39 new worker
  cases, 49 entry-contract cases and 72 existing selector cases.
- Real SDK serialization with mock responses covers CALL/PUT/HOLD, exact count
  and generation payloads, refusal/incomplete/tool/fragmented/malformed output,
  invalid evidence/geometry, wrong model, count/usage ceilings, missing usage,
  deadline expiration and configuration tampering. Native subprocess tests cover
  actual worker `main` with fake SDK transport, environment filtering, overflow,
  invalid lineage/usage, nonzero exit, timeout and repeated cancellation cleanup.
- Initial native fixture failure was traced to an omitted test-package import
  root under `-I`; corrected the fixture, then reran the combined suite successfully.
  Production deadlines and import isolation were not relaxed.
- Scoped Ruff lint/format, compilation, pip check and whitespace checks passed.
  Wheel module bytes match source. No dependency lock or previously tracked
  application module was changed. No full equity/options-suite rerun is claimed.
- Verified wheel SHA-256:
  `bc0c899e1aaaf6495523c895ae9f61dce502afc08be48e52284b0e4643300298`.

Pre-edit canonical branch/local/PR head:
`22b1161db036e5475e77c053ff12d521a3e35027`, tree
`11342c9dd00de2cd7054639005dbd4e40b5e4ee3`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays draft.
Source of truth v1.9 records capability progress without changing the roadmap.
No authentic provider call, broker write, hosted CI or deployment was performed.
The old frozen experiment and previously evidenced host release remain unchanged.
LIVE stays disabled. No profitability claim follows from these tests.

## P2 offline entry reasoning and dashboard completion gate: 2026-10-10 UTC

The first code slice of the broader AI role is implemented in
`app/options/entry_reasoning.py`; see [the exact API and integration boundary](OPTIONS_ENTRY_REASONING.md).
This is **fixture/installed-package verified offline review**, not a model call,
durable trader integration, new runtime, deployed strategy or proof of alpha.

Software constructs a bounded packet from exact confirmed Degen candidates and
reproduces their original admission before exposing evidence. Serialized evidence
IDs, candidate/decision/configuration binding and original opportunity expiry are
explicit. The strict model-output contract permits HOLD or an entry plan with
underlying condition, target, invalidation, horizon, thesis and uncertainty. It
forbids model quantity, contract creation, premium/underlying ambiguity and extra
authority fields. Decimal validation and full revalidation reject malformed or
unchecked copied inputs.

Review rejects foreign/stale output, unknown references, widened invalidation,
wrong CALL/PUT geometry and targets/triggers/horizons outside the supplied frozen
envelope. Fresh deterministic admission checks exact source/entitlement, executable
quotes, reconciled account and budgets. Reduced funds can reduce size; cheaper
premiums cannot increase original quantity; required price, debit, full-premium
loss and validity cannot exceed original admission. Unmet entry conditions yield
HOLD with no standing instruction. ELIGIBLE always retains
`execution_authority=false`; target and absolute exit time remain in the complete
review. The caller must supply already settled cost/account truth.

**Integration still required:** a versioned native model worker and durable
coordinator must retain the complete plan, bind frozen enrollment, record and
settle usage, enforce target/time protection independently and revalidate at
dispatch. Passing only its nested old `OptionProposal` to execution would discard
required terms and is explicitly unsupported. Existing SELECT/HOLD coordinator,
protective supervisor, schema, populations and deployed experiment are unchanged.
Position-management proposals remain future P3 work.

The user-requested **step 8 / M8 visual dashboard finish** is now recorded in
[source of truth v1.8](SOURCE_OF_TRUTH.md) and the delivery plan. Functional UI is
still part of P4; dedicated dark styling, charts/hierarchy, real state handling,
desktop/mobile screenshots, keyboard and contrast acceptance are required for
the finished product. No visual redesign is claimed in this code slice.

Verification:

- New entry reasoning: 49 tests; together with existing admission, **233 passed
  in 2.15s**, warnings as errors.
- Noneditable installed wheel, outside source, Ubuntu Python 3.12.3/OpenSSL 3.0.13:
  **513 options-suite tests passed in 106.74s**, warnings as errors. Includes
  admission, Degen, old model selection, durable execution, observer and capture.
- Scoped Ruff lint/format, compilation, pip check and whitespace passed. The four
  current delivery documents passed 68 local links/anchors. Wheel module bytes
  match source. Existing dependency locks and all previously tracked app code are
  unchanged; only the new module extends application code.
- Verified wheel SHA-256:
  `3a511b859bcf1194c3d2c19946706672f771e367c45884d8d0c01e08388dabc1`.

Pre-edit canonical branch/local/PR head:
`21286b77a243649db2452020e2bababc00424870`, tree
`07e5dafd10371bbbb51958912921e0e94c4ff050`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays draft.
No hosted CI, provider/model call, broker write or deployment was performed.
The actual host remains on its prior separately validated release; these 513 cases
are local installed-package proof, not a new operator-host run. No full equity
suite rerun is claimed for this isolated additive module.

**Next:** continue P2 native/durable plan integration without changing old cohorts;
P1 bounded actual market samples and normalization remain pending operator capture.
Authenticated discovery is already complete. Full options runtime, independent
host lifecycle/alerts/archive recovery, prospective economic evidence, M7 families
and M8 visual acceptance remain open. LIVE stays disabled.

## Reasoning-trader research and actual schema evidence: 2026-10-10 UTC

The user requested a strong research/design pass before further coding and a
larger useful AI role. [Source of truth v1.7](SOURCE_OF_TRUTH.md) now references
the [bounded research and completion plan](AI_TRADER_RESEARCH_PLAN.md). The working
design expands the future model from SELECT/HOLD to entry thesis/geometry and
then exact-position MAINTAIN/EXIT_ALL/TIGHTEN proposals. Deterministic authority,
one owner/position, frozen populations and independent mandatory exits remain.
These broader proposals are **not implemented**. Existing selector cohorts and
the deployed experiment are unchanged. P0 research/design is complete as a plan;
P1 actual samples/normalization and P2 offline proposal contracts are next.

Targeted TradingAgents and AI Hedge Fund source files were inspected at pinned
commits; all five recovered source bytes matched canonical Git blob hashes, with
[the manifest](research/ai_trader_sources.json) retaining identities. Relevant
FinMem, LiveOption, financial-LLM bias and backtest-overfitting research plus official
broker/0DTE documentation were reviewed within the limits recorded in the plan.
No external framework was executed, fully audited or shown to be profitable.
SignalFlow main and draft #102 pins remain unchanged; all 60 retained main reference
files again matched their existing manifest. Prior test limitations remain historical.

**New operator evidence:** authenticated read discovery returned exit 0, COMPLETE,
capture `bc8356d41540421d903e5fe8295c1542`, no missing tools/input/output schemas,
zero completed market reads, `execution_authority=false` and
`normalized_data_verified=false`. Private evidence remains at
`/root/trade-bot-options-auth-BqLFmz` on the operator host; no direct SSH inspection
or independent off-host archive is claimed.

The operator subsequently supplied only the read-schema export as a text attachment.
Its local bytes have SHA-256
`7642124d02d45a9a9c1cac50e1f6e79b7db93eef03cebaa836e4cb167b59bd1a`.
Parsing that supplied artifact with the installed `ReadSchemas` model verified:

- Captured time: `2026-10-10T20:00:43.613542Z`.
- Schema SHA-256: `d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15`.
- All six allowed read tools, both schema kinds, read-only annotations and empty
  missing lists. No OAuth content was read or committed.

This closes the **supplied authenticated schema discovery** gate only. Read shapes
are now known; actual samples, normalized identity, exercise/deliverable metadata,
entitlement, coverage, market-hours freshness/latency and model usage remain open.
The next sample must use exact reviewed arguments and actual returned instrument
IDs. Saturday discovery is not real-time market acceptance. Earlier entries below
requesting discovery describe historical next steps, now superseded by this result.

Canonical pre-edit branch/local/PR head:
`dc43e7482c64db5a4cf75ed57b4e1ef1ee877c7b`, tree
`ed2a208b6024abd16d52db26960fc5de546081ad`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6`; PR #1 stays open/draft.
This checkpoint changes documentation and a source manifest only. Application,
tests, scripts, units and lockfiles remain identical to installed validation
release `618d464f1cbde622d7c05170a99d50cca97c8ca2`. Retain its operator 1,815-test
pass and eight sandbox cases; no suite/probe rerun is warranted for this plan.
Local documentation checks passed: 116 relative links/anchors, 15 shell blocks,
research JSON parsing and whitespace. Schema validation and all 65 pinned external
reference file hashes passed (60 SignalFlow, five new comparison files). These
checks validate documentation/provenance, not model efficacy or trading behavior.
No new provider/model call, deployment, service start or broker write was made.
Full application host acceptance, economic evidence and LIVE readiness remain open.

## Operator target-host credential probes passed: 2026-10-10 UTC

**Operator-provided evidence:** the existing disposable systemd harness returned
exit 0, `status=OBSERVED`, and eight OBSERVED cases. Runtime, control, alerts and
checkpoint each passed with initially present and missing credential peers; every
case reported a separate mount namespace. The reviewed harness checks the access
matrix before and after creating missing peers. Its exit-0 contract also requires
confirmed transient-unit termination and exclusive fixture cleanup.

The supplied command reused validated commit
`618d464f1cbde622d7c05170a99d50cca97c8ca2`, tree
`d744b2478862d6c1620728b1d024e49090717744`, checked unchanged probe/unit files,
required systemd PID 1 and validated the dedicated non-root service identity.
The account-provisioning branch creates that identity only if absent; the summary
does not establish whether it was newly created. No production unit or trader was
installed, enabled or started by this harness.

Retained operator evidence directory:
`/opt/trade-bot-validation/618d464f1cbde622d7c05170a99d50cca97c8ca2/sandbox-verification-OgTIGn`.
The command saves `report.json`, `stderr.log`, `host-metadata.txt` and `exit-code`
there. The supplied compact summary establishes the reported result; the raw files,
their digests and kernel/systemd metadata have not been independently inspected or
retained off host. This is operator evidence, not direct authenticated host access.

**Closed gate:** actual target-host kernel/service-identity behavior of all eight
dummy credential-namespace cases, including late-created peers. No repeat run or
application reinstall is needed to record this result.

**Remaining boundary:** the report deliberately retains
`host_acceptance=UNVERIFIED` and `live_enabled=false`. Substituted paths and dummy
code do not establish the fixed installed credential topology, actual SHADOW path
denial, application boot/lifetime ownership/shutdown/orphan behavior, independent
alerts, archive retrieval or source-host-loss recovery. M5 remains incomplete.

**Next integration action:** obtain authentic read schemas with the
[complete pinned discovery command](OPTIONS_READ_CAPTURE.md#pinned-discovery-after-the-passing-host-probes).
It reuses the already tested installation, prompts for a separately managed OAuth
file path on the server and makes one tool-list discovery, with no market read,
model invocation or broker write. Separate authorization is a real prerequisite;
the frozen deployed experiment's active/default OAuth file must not be reused.
Review the retained schema artifact before preparing any sample arguments; no
provider schemas or normalization defaults can be guessed. Matched economic
evaluation remains independent unfinished M4 work, not a substitute for this M3
data gate. The engine is not yet running an options SHADOW session.

Fresh canonical branch/local/PR head before this evidence update was
`67777ac101de06e9fcd495fe95eb3f71a9fc2c85`, tree
`685997506a96c4ee3dff3bcf781672ad7f48f9ac`; main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 remains open/draft.
This checkpoint changes documentation only. Existing 1,815-test installed host
proof and the new eight-case operator probe proof are retained without rerunning
the suite. Local checks passed for 99 documentation links/anchors, 18 bash blocks,
the embedded Python preflight and five offline private-file cases (valid private,
symlink, public, absent and relative). Application/scripts/units/tests and dependency
locks remain identical to validated `618d464f...`; whitespace checks passed.
These checks do not exercise provider authorization. No application code, provider call, service or frozen experiment was
changed from this workspace. LIVE remains disabled.

## Operator target-host installed release passed: 2026-10-10 UTC

**Operator-provided host evidence:** the pinned detached validation installation
of `618d464f1cbde622d7c05170a99d50cca97c8ca2`, source tree
`d744b2478862d6c1620728b1d024e49090717744`, completed with **1,815 passed in
783.51 seconds (13:03)**, warnings as errors, and an **exit receipt of 0**.
The operator supplied the saved log tail and receipt directly in chat. The preceding
installation output showed successful locked dependency installation, wheel build,
noneditable package installation and `pip check` with no broken requirements.
The final log showed the options observer CLI help and the launcher's explicit
`Validation passed. No trading service started.` completion line.

The supplied launcher used `umask 077`, low-priority tests, empty `PYTHONPATH` and
`-o pythonpath=` outside the source checkout, with no copied application source.
It checked the exact detached commit/source tree before building. The supplied
installed import path was:
`/opt/trade-bot-validation/618d464f1cbde622d7c05170a99d50cca97c8ca2/venv/lib/python3.12/site-packages/app/__init__.py`.
The log and receipt remain at that release directory's `output.log` and `exit-code`.

Host-built wheel SHA-256, from the earlier supplied installation output:
`0ebc2e7efb1df30bbd3532fc4a418a71d41ecf1eb637deafbd426d99c75bc725`.
This separately built host artifact differs from the local wheel digest recorded
below; byte-identical reproducible builds and independent host byte inspection are
not established. This record is supplied operator evidence, not direct SSH access,
a downloaded full host log, independently retained artifacts or off-host protection.
The previously reported host platform was Ubuntu 24.04/Python 3.12.3/OpenSSL 3.0.13.

**Closed blocker:** installed target-host compatibility of this tested release,
including the repaired Ubuntu native TLS startup and permission/cleanup/timing
regressions. No additional suite run or application reinstall is required merely
to record this evidence. The old failed release/log is retained as history.

**Still open:** fixed installed systemd topology/boot/lifecycle and independent alert/archive/
source-host-loss acceptance; authenticated option-read schemas/samples and exact
normalized collection; actual model/read usage/latency; mixed stock/options runtime;
matched economic evaluation and browser visual acceptance. M5 is not complete,
no options trading service has started, and provider/profitability/LIVE acceptance
is not granted by a fixture-provider test suite.

**Next host action:** use the existing [disposable sandbox integration](PAPER_SANDBOX_ACCEPTANCE.md)
from the already validated `618d464f...` source. Provision only its dedicated
non-login service identity if absent; eight unique transient probes use harmless
dummy credential files and substituted disposable paths. They install/enable no
production unit, initialize no population, read no real credentials and make no
provider call. Their narrow namespace/access results must be separately supplied;
all eight were subsequently supplied as OBSERVED in the record above. No new host
abstraction or repeat probe run is needed.

**Options integration gate:** obtain exclusively managed authorization and actual
[read discovery/sample artifacts](OPTIONS_READ_CAPTURE.md), then implement the
normalization and options runner from that evidence. The existing stock runtime
units cannot be relabeled as an options trader. The source-of-truth v1.6 milestone
order is unchanged, main stays `b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1
stays draft, the frozen deployed SHADOW experiment stays untouched and LIVE stays
disabled. Independent economic evaluation work remains available while authentic
provider artifacts are pending.

## Target-host validation repair: 2026-10-10 UTC

Fresh GitHub branch/local/PR state matched `e4d09575d6f4bc331ebc405f63cb3495a8a78342`,
tree `b3079f86e020fab4c84e1a7832f79c119be01ca9`. PR #1 remains open/draft;
main remains `b5359aaf396e692d2142d7e02908f1544e045ee6`.

**Operator evidence:** the separate installed-release validation on Ubuntu 24.04
finished with **1,800 passed, 10 failed in 601.27 seconds**, warnings as errors,
exit code 1. Installation/import and `pip check` succeeded. This was a validation
installation, not an options trading-service launch. The supplied complete failure
log SHA-256 is `5db2e26d49edfb826126053298a72078d9c472de81a9f6d61697c4fee197ba89`.
The operator reported Python 3.12.3/OpenSSL 3.0.13 and dependency versions matching
the locks. No authenticated provider, trading session or deployment acceptance
is established by this run.

The failures break down as follows:

- Two permission fixtures relied on creation modes despite validation's `umask 077`.
  The existing-directory fixture became 0700 rather than 0750; the intentionally
  unsafe market-read lock became safe 0600 rather than 0644. Explicit fixture chmod
  now establishes the intended existing modes. Production permission guards stay intact.
- Four native companion/lifecycle failures shared one actual startup defect.
  Ubuntu's server SSL context reports `MINIMUM_SUPPORTED`, while the prior local
  build defaults to TLS 1.2. The served context now explicitly sets a TLS 1.2 floor
  and preserves a stronger existing minimum. Plaintext, credential, certificate,
  key and proxy restrictions remain unchanged.
- Two neighboring HTTP/model-count tests failed on unclosed subprocess-pipe warnings
  from earlier failed native startups, not their own authority/count assertions.
  Both affected native harnesses now drain/reap exited children as well as kill
  running children on failure; warnings remain errors.
- The warming test held a mocked read across native account processing but gave that
  read only 0.5 seconds. A deliberate 0.75-second account delay reproduces its exact
  failure. Its disposable source fixture now uses the existing bounded five-second
  policy used by other synchronized native-read tests, with delayed/normal cases.
- The options SIGKILL harness allowed four seconds for both parent startup and child
  acceptance, racing the unchanged five-second dispatch allowance. A deliberate
  five-second pre-dispatch parent delay reproduces the exact submit-count failure.
  The harness now bounds startup plus acceptance separately from that production
  dispatch allowance, diagnoses early exits, and reaps a captured child on failure.

**Local reproduction:** installed-wheel tests using system Ubuntu Python 3.12.3,
OpenSSL 3.0.13 and `umask 077` reproduced the TLS startup failures and later garbage
collection of leaked pipes. Separate delayed fixtures reproduced both timing
signatures. Exact target-host scheduling remains unobserved; these are local
reproductions and regression proof, not a new successful operator run.

**Local focused verification:** **294 tests passed in 200.90 seconds** on Ubuntu
Python 3.12.3/OpenSSL 3.0.13 with `umask 077`, warnings as errors and the installed
wheel outside the source checkout. All affected suites passed, including actual
TLS 1.2/1.3 HTTP/signing/restart paths, weak/strong initial context floors and both
deliberately delayed timing regressions. An additional **15 tests passed in 2.43
seconds** on Python 3.12.14/OpenSSL 3.5.8 with the same private umask, covering the
context floor, startup rejection and permission fixtures.

**Final local installed verification:** **1,815 tests passed in 463.34 seconds**
on Ubuntu Python 3.12.3/OpenSSL 3.0.13 under `umask 077`, warnings as errors, outside
the source checkout. This includes native runtime/control/alert/checkpoint/options
and model-child paths with fixture/faked providers. All 114 application Python files
and three web templates match source, wheel and installed package. All 69 entries
across runtime/dev/build locks match installed dependency versions. Wheel SHA-256:
`8b19080883c5db09fa38f977ad5f86f1edcdcf414e7b0508527974915fc44ace`.
Production-file Ruff and scoped test lint/format, installed compilation under both
interpreters, `pip check`, documentation links, retest shell syntax and whitespace
checks passed. No warning filters, skips, automatic retries or production timeout
extensions were added. The subsequent operator retest passed as recorded above.

**Retest procedure:** the [single logged retest](TARGET_HOST_RETEST.md) was subsequently
completed successfully, as recorded above.
No newer PAPER service, Caddy route, LIVE mode,
broker write or frozen deployed SHADOW checkout has been started or changed.
A successful retest would establish installed target-host test compatibility, not
actual namespace/boot/provider/alert/off-host recovery or options-trader acceptance.
The milestone order and remaining product scope in [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md)
are unchanged.

## First M4 stored options observer: fixture/native proof, 2026-10-09 UTC

[SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md), version 1.6, retains the settled goal,
rules and milestone order. [OPTIONS_OBSERVER.md](OPTIONS_OBSERVER.md) documents the
new separate authenticated read-only app and installed loopback CLI. It consumes
existing options journal evidence without opening an execution owner, attaching
venue/model authority or initializing/recovering a population.

The dashboard displays stored opportunities and HOLDs, admitted exact contracts and
ceilings, locked owned positions, original/tightened invalidation, retained exit
requirements, order attempts versus authoritative local fixture fills, known model
costs and unresolved usage. Current-position evidence is independent of history
pagination. Degen enrollment and model/setup versions are visible; Swing/Scope stay
explicitly unimplemented. Worker/session/release remain unknown and restore authority
is explicitly not checked. Local alerts do not imply independent options delivery.

Each bounded report reads a single committed read-only SQLite snapshot. Private
schema/population binding, file identity, cooperative deadline and capacities reject
unusable sources without adopting or repairing them. Missing files yield EMPTY and
no fabricated zero/flat/healthy state. Latest exact stored bids need qualifying
metadata, source/timestamps/entitlement and enough observed size; a newer invalid
or conflicting quote cannot reuse an older mark. Unknown orders/account evidence
and reconciliation issues suppress equity; unknown model costs suppress the
after-cost estimate. Exit/data/host costs and matched SPY/cash/model-off/on cohort
evaluation remain explicitly unimplemented.

Fresh GitHub/local/PR state matched `8ab66cca80d02cb3183ab4d8025359a645939442`,
tree `677abc455069f4d784c5c539d5cb311fb6296114`; main was
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR open/draft and checkout clean.

Verification: **85 focused options/legacy web tests passed in 9.16 seconds**, warnings
as errors, including 53 new observer cases. The initial new-test run had two fixture
failures: Decimal presentation precision and unvalidated string fields introduced
by a fixture model-copy update. Both fixtures were corrected. Repeated authenticated
API/HTML reads preserve journal, authority, venue and model-key bytes; forbidden
execution/model/venue entry points are never called. Concurrent writes do not mix
report revisions, and interrupted opportunities remain interrupted without recovery.

The final installed full suite outside the source checkout passed **1,810 tests in
438.47 seconds**, warnings as errors, including native execution/control/alert/
checkpoint/options/capture/model regressions with faked provider behavior.
All **114 application Python files plus the observer template** match source, wheel
and installation. Wheel SHA-256:
`13dd4aaf4d097d5e7f65e0cb8b8db01aa0f7d5cf5426c2d828d0622a067638fa`.
Actual installed `-I` observer CLI HTTP checks passed health, unauthenticated 401,
authenticated EMPTY, no database creation, clean shutdown and no access-log/secret
output. Scoped Ruff lint/format, installed compilation, `pip check`, 87 local
documentation links and whitespace checks passed.

**Browser visual acceptance remains open.** The official browser-binary download
returned an unusable empty archive; the remote browser could not reach the local
fixture-only loopback preview. No rendered desktop/mobile proof is claimed. The
preview server was stopped. Responsive CSS and server-rendered page branch tests
do not substitute for visual acceptance.

No authenticated broker/model provider call, order review, broker write, host
operation, service/Caddy install, LIVE enablement or deployed experiment change
occurred. This is the first M4 stored-observer capability, not completion of M4 or
options deployment. **Next independent work:** point-in-time matched economic
evaluation with explicit SPY/cash/model-off/on comparisons and complete cost
uncertainty. Authenticated schema/samples and exact normalized collection remain
M3 provider gates. Mixed stock/options ownership, M4 visual acceptance, M5 isolated
host/independent alert/off-host restore/source-loss proof, M6 explicit LIVE review
and authorization, and M7 Swing/Scope-specific acceptance remain open.

## M3 optional candidate model selector: fixture proof, 2026-10-09 UTC

[SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md), version 1.5, preserves the settled scope
and milestones. [OPTIONS_MODEL_SELECTION.md](OPTIONS_MODEL_SELECTION.md) describes
the delivered opt-in library API. Authenticated normalized collection still requires
actual schema/sample artifacts; this independent model slice did not invent mappings.

Added a frozen, tool-less candidate chooser to the separate Degen options PAPER
owner. Only already admitted candidate IDs or HOLD are allowed; the model cannot
supply contract, price, quantity, risk, invalidation, budget or deadline fields.
Default deterministic selection and existing model-off cohort identities remain
unchanged. Opt-in needs a new untraded population, explicit frozen cost/token/time
policies and an absolute private model-key path. Supervision never reads the key.

The installed fixed native child counts the exact prompt/schema/packet before one
Responses generation, with no tools, retries, storage, streaming or background work.
Minimal environment excludes broker credentials and mutable API origin; the official
model origin is fixed. Bounded protocol, deadline/cancellation cleanup and independent
parent-death watching prevent lingering workers. Request/packet/configuration binding
and strict final-message parsing reject wrong lineage, fragments, tool output,
refusal, incomplete output and invented IDs. All provider responses in tests are faked.

Durable model admission precedes launch. Returned usage evidence is saved before
settlement, charged on matching-model HOLD/rejection/late replies, and checked against
exact input count and token ceilings. Unknown/wrong-model/unbound usage, interruption
or failed receipt storage remains unresolved and blocks entry without automatic
retry/fallback. Receipt identities are unique. Fresh sizing after cost settlement can
reduce quantity. Original admission quantity, price, entry debit, full-premium funding
and approval expiry remain upper bounds through model waiting and native dispatch.
The wait also cannot cross the original five-minute slot or frozen process deadline.

Protective management remains a separate fast deterministic path. A missing model
key cannot prevent a held-position stop. Accepted orders remain unfilled until
authoritative fill evidence arrives. No options service or actual broker feed was
installed, and the old deployed synthetic experiment stays frozen.

Fresh canonical/local/PR state matched `0b4521dbe7317159f8ec7d7eb4952459eed282c6`,
tree `91e20556693bfd48c89538cfd017aa02b4ed67df`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR open/draft and checkout clean.

Verification: **104 existing Degen/options lifecycle tests passed in 33.30 seconds**,
warnings as errors. The initial new-test run had 11 failures from fixture assumptions
about unfilled orders, supervision fields, enrollment and intercepting unrelated
venue children; those fixtures were corrected. Review also found that selected-model
evidence could mask a later execution-rejection reason. The merge order was fixed,
current-clock admission restored and a concurrent-halt test added. The final **72
new selector tests passed in 25.96 seconds**, warnings as errors. Actual owner SIGKILL
left the model attempt unknown, retained interrupted opportunity evidence, released
ownership and stopped its native child with watcher exit 99; restart did not replay.
The native worker main used the real installed SDK with mocked HTTP transport.

An earlier installed full run was deliberately interrupted for that final
admission/report correction; it is not counted as completed verification.
The final installed full suite outside the source checkout passed **all 1,757
tests in 439.24 seconds**, warnings as errors. Installed native runtime/control/
alert/checkpoint/option/capture/model entry points were exercised, with explicitly
faked market/model provider behavior in their relevant tests.

All **111 application Python files** match source, final wheel and installation.
Final wheel SHA-256: `8d0976de0b8bf1131aef815e59b16e7a0523f5d498dfaeb58aae978225b5b942`.
Scoped Ruff lint/format, installed compilation and `pip check` pass.
**55 current continuation-document links** resolve; whitespace checks pass.

No authenticated model/broker call, order review, broker write, target-host operation,
LIVE enablement or deployed credential/experiment change occurred. Configured model
rates remain estimates. Local fixture process proof is not provider latency, real
billing, host namespace/boot behavior or independently retained recovery protection.

**Next gate:** obtain actual discovery and bounded samples with
[OPTIONS_READ_CAPTURE.md](OPTIONS_READ_CAPTURE.md), then implement the exact normalized
candidate/held-contract collector. Actual read/model latency, usage and supervised
sessions remain provider gates. M4 stored observer/cohort evaluation, mixed stock/options
ownership, M5 isolated host/alert/off-host archive/source-loss acceptance, M6 explicit
LIVE review/authorization and M7 Swing/Scope-specific acceptance remain open.

## M3 headless options schema/sample acquisition: fixture proof, 2026-10-09 UTC

[SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md), version 1.4, retains the existing scope
and milestone order. [OPTIONS_READ_CAPTURE.md](OPTIONS_READ_CAPTURE.md) supplies
the operator procedure and exact limits. The normalized Degen data mapper is still
pending actual authenticated schemas/responses; acquisition is evidence only.

Added a separate fixed six-tool options/equity market-read gateway, SHA-256 metadata
pinning and whole-plan input-schema validation before the first request. Schema
drift, missing inputs, contradictory annotations, external references, invalid
arguments, tool errors and oversized/invalid advertised outputs fail closed.
Missing output schemas can yield explicitly unvalidated raw samples for review;
they never imply normalized/real-time/complete market evidence. Existing broker
firewalls are unchanged; review, placement, cancellation, exercise, account/order/
position management and model tools are absent from the new capability.

Discovery and up-to-eight-call acquisition use the installed fixed native worker,
isolated imports, stripped environment, bounded stdin/stdout and at-most-30-second
deadline. Current-owner private existing OAuth authorization is reused headlessly;
refresh persistence is not a broker write. A capture-only OAuth-path lease remains
held through cancellation/termination cleanup; other clients/hosts still require
exclusive credential management. Native parent-death/deadline watching prevents an
orphaned provider child from continuing after owner loss.

The CLI exclusively creates a private artifact before collection, flushes an
INCOMPLETE admission and records completed or sanitized failed evidence. Existing
files/symlinks are rejected; console output never echoes credentials/arguments/raw
results. Ordinary worker errors retain a successful prefix; hard death can lose an
unreturned prefix or leave incomplete/partial JSON. Every artifact explicitly has
no execution authority and no verified normalized data. Declared symbols/instrument
IDs are intended scope, not proof that raw requests/responses match that universe.
No automatic feed publication, model invocation, order action, polling or deployment
is wired to this evidence command.

Fresh canonical/local/PR state matched `e65585b8efbc660820905d812be7eea31d155716`,
tree `f175500369ce1db71f9f9537d7022a1c5d925da3`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR open/draft and checkout clean.

Verification: **166 focused capture/legacy market/gateway/client/Degen tests passed
in 16.76 seconds**, warnings as errors, including **50 new capture cases**. Native
discovery and pinned capture, uncancelable read deadline, cancellation/reaping and
actual parent SIGKILL/orphan exit were exercised with explicit fake clients. The
SIGKILL child exited with the parent-death watcher code 92, not an assumed timeout.
Private admission-before-read, no overwrite, reviewed pin failure, partial evidence,
safe console output and unchanged legacy denies have proof. The final installed
full run outside the source checkout passed **all 1,685 tests in 415.23 seconds**,
warnings as errors. Installed native runtime/control/alert/checkpoint/option/capture
entry points were used; provider behavior in capture cases was explicitly faked.

All **109 application Python files** match source, final wheel and installation.
Wheel SHA-256: `9d2e72022d5079e284f764befe72748c11840dce323be1ef1db1928daf744cbb`.
Scoped Ruff lint/format, installed compilation, `pip check`, **46 current document
links**, installed isolated CLI help and whitespace checks pass. `jsonschema` is
now an explicit dependency; the installed MCP SDK already requires it.

No authenticated Robinhood/model call, preview, broker write, target-host operation
or deployed OAuth/experiment change occurred. Public read-tool documentation does
not replace authentic schemas, exact expiry/deliverable/Greek/entitlement/coverage
evidence or observed provider latency. Local captures are not off-host protection.

**Next gate:** operator discovery and bounded actual samples using the documented
installed command, then an exact normalized mapper and candidate/held-contract
collector that can publish usable Degen/fast-supervision evidence. Optional governed
model selection, M4 observer/cohort evaluation, mixed stock/options runtime and M5
actual namespace/boot/alerts/archive/source-host-loss acceptance remain open. M6 LIVE
review/authorization and M7 Swing/Scope-specific acceptance remain future gates.

## First M3 Degen execution path: local fixture proof, 2026-10-09 UTC

[SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md), version 1.3, keeps scope and milestone
order. [DEGEN_PAPER.md](DEGEN_PAPER.md) describes delivered APIs and the remaining
authenticated collector gate. This is a concrete Degen-to-order implementation,
not a completed provider integration or options deployment.

Added versioned completed-bar opening-range continuation, VWAP/trend pullback and
observed failed-break reversal for frozen SPY/QQQ symbols. CALL and PUT setups need
real supplied volume, directional VWAP and completed fifteen-minute confirmation;
forming bars cannot vote. Missing, delayed, stale, gapped, duplicated, foreign or
interpolated history blocks. Three adapted SignalFlow source blobs were rechecked
against the pinned manifest. Rules are an explicit smaller adaptation, not the full
SignalFlow strategy graph. Preceding-bar volume ratio is not historical same-slot RVOL.

Bounded exact 0DTE metadata selection requires observed delta, option volume/open
interest and complete supported contract identities. Stable shortlist ranking and
quote capacity precede M1 deterministic admission. Selected evidence flows into M2
fixed-intent prepare and fresh dispatch approval, followed by one native local-venue
attempt. No model chooses size or receives broker tools.

The owned coordinator freezes explicit strategy/selection policy before trading,
claims one durable five-minute entry opportunity, retains inputs/HOLD/candidate/order
evidence and prevents duplicate/concurrent attempts. Interrupted slots retain selected
evidence, halt entry and never replay. Exact held/pending identity comes from the
journal rather than the current chain. A separate fast supervision method can exit
inside an already claimed entry slot. Stored reports perform no provider/model/order
work. New tables remain part of paired restore fencing; stock defaults are unchanged.

Fresh branch/local/PR state matched `cf2d9c84ab08e33eca5b81296f614599c820aa96`,
tree `523e0faf38d7b804ec048e7db7d56bb603a75b66`. Main remains
`b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 stays draft.

Verification: **288 focused options tests passed in 33.32 seconds**, warnings as
errors, including **41 new Degen cases**. A first focused run exposed inconsistent
immediate/stored rejection serialization; production reporting now returns the same
durable JSON outcome. Positive CALL/PUT fixtures prove all three setups, native PAPER
entry, owned stops, fast in-slot exits, concurrent deduplication and interruption
retention. The final installed-package full run outside the source checkout passed
**all 1,635 tests in 418.03 seconds**, warnings as errors. It used installed native
runtime/control/alert/checkpoint/option entry points and includes the repaired
archive fixture. This is new full-run proof, separate from the accurately retained
M2 failure and targeted retest below.

All **105 application Python files** match source, wheel and installation. Final
wheel SHA-256: `401ce412f6dc675ed93f85e208a674a132347613fed25bcabdde5c56e285cc3f`.
Scoped Ruff lint/format, installed compilation, `pip check`, **41 current document
links** and whitespace checks passed. No authenticated provider/model call, preview,
broker write, deployment update or LIVE enablement occurred.

**Next:** actual-schema authenticated options collector with bounded native
process/output/latency and exact source/universe/entitlement/held-contract evidence;
then optional tool-less model selection with actual cost receipts. M4 observer/cohort
evaluation, mixed stock/options service integration, actual options host/namespace/
boot/alert/archive/host-loss acceptance and future LIVE account/capital/release review
remain open. No fabricated wire mapper, scheduler deployment or off-host protection
is claimed. The old deployed SHADOW experiment remains frozen and separate.

## M2 durable local options PAPER lifecycle — 2026-10-09 UTC

M1 admission and **M2 local lifecycle core are fixture verified**.
[SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md), version 1.2, retains the adopted scope
and milestone order. **Next: M3 Degen candidates and the real option-read boundary.**
[OPTIONS_EXECUTION.md](OPTIONS_EXECUTION.md) describes the delivered API and limits.
Engineering completion percentages are retired at the user's direction. Historical
estimates below remain historical; current reporting uses capabilities and gates.

Added `app.options.lifecycle`, `accounting`, `venue`, `process`, `worker` and
`engine`. The options owner reuses journal transactions, paired restore fencing,
lifetime ownership, native child cleanup, calendar and usage contracts, with a
separate option schema/ledger. Stock defaults remain unchanged and stock readers
reject the option schema. Frozen explicit fixture capital/limits/venue/population
stay outside model authority; no existing deployed bankroll was reset or adopted.

HOLD/rejections and fixed DAY-limit approvals retain their source, complete inputs
and outcome. Fresh dispatch re-admission cannot increase original quantity/price/
funding authority or renew the approval lease. SUBMITTING commits before the one
native attempt. Invalid/lost acknowledgments, crashes, timeout, cancellation and
interrupted ownership retain uncertainty/reservations and never replay. Actual
SIGKILL proved restart recovery, lock release and orphan exit, with one accepted
order retained and no duplicate submission.

Whole partial fills retain exact contract/quote/size/price/fee/sequence evidence.
FIFO cash/settled funds, premium basis, realized P&L and all fees reconstruct from
complete immutable history. Sale proceeds require an explicit settlement receipt.
Entry reserves worst-case one closing order fee per contract. Low-value one-contract
catastrophe closes conserve cash without borrowing. Missing history, changed terms/
IDs, bad quote/fill/receipt evidence, cash/basis mismatch and unsupported underlying
exposure halt without replacing prior authority or assuming flatness.

Original/tightened call/put invalidation, executable-bid premium catastrophe and
fixed time/expiry exits operate without model judgment and survive restart/rebound.
Unpriced/stale exposure remains owned and halted. Actual size-limited close progress
can authorize a distinct remaining close; rejected/canceled/expired closes require
review rather than automatic replacement. Native XNYS holiday/half-day behavior is
clamped by exact supplied contract instants and frozen cutoffs. Explicit AM/PM cash
settlement and worthless-expiry receipts are distinct from fills; clocks alone do
not flatten. Scripted exercise-created stock/short exposure is preserved as rejected
evidence, never permitted or exercised by the engine.

Durable optional model attempts retain unknown costs across restart. Matching
immutable usage/proposal receipts charge configured rates even on HOLD, reduce
loss allowances and enforce frozen call/session/total budgets. These are fixture
receipts, not actual model calls or provider billing proof.

Fresh pre-edit branch/local/PR state matched
`b67e4f1a89418608a58205cbfc02fa99b7f39bc0`, tree
`57e52f5c1b014e2563236f91573a16cbb07eeef3`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR open/draft and checkout clean.

Verification: **331 focused options/shared stock journal/restore/process tests passed
in 51.70 seconds** before four final additional cases. The final installed-package
run outside the source checkout executed **1,594 tests: 1,593 passed and one existing
archive TLS fixture failed in 432.77 seconds**, warnings as errors. All **63 new
options lifecycle tests passed** in that run. The archive fixture sent a large body
after an incomplete-admission retry was already rejected, racing the intentional
connection close. The repaired fixture sends the same authenticated identity/length
headers and reads the early 409 without streaming the rejected body; it still proves
SIGKILL retention, no overwrite and distinct recovery upload. All **44 installed
archive receiver tests passed in 20.32 seconds**, warnings as errors. No archive
production change was needed. The initial full run is not described as a clean
full-suite pass; unaffected tests were not repeated after this test-only repair.

All **102 application Python files** match source, final wheel and installation.
Wheel SHA-256:
`764e0ca2a2425cb3e1fefaa1c2a36f1a667bdfde960a7e509805767b4a6d3da3`.
Scoped Ruff lint/format, compilation, installed `pip check`, **37 current document
links** and staged whitespace passed. Native tests use installed entry points and
the option child uses fixed `python -I -m app.options.worker` with a stripped
environment. No provider/account/model call, preview, broker write or deployment
operation occurred.

Remaining gates: authenticated exact option universe/source/entitlement/latency and
model usage evidence; mixed stock/options selector and service/observer integration;
actual options host namespace/boot/lifecycle and independent alert/archive/host-loss
acceptance; Swing overnight and authentic Scope/SPXW session/cutoff/feed acceptance;
reviewed broker/account/capital/loss configuration and explicit future LIVE-write
authorization. The local options calendar is a conservative XNYS regular-hours
intersection, not broker/CBOE acceptance. Existing equity service/control/alert/
checkpoint tools are not options runtime adapters. Old deployed SHADOW stays frozen;
its worker/slot audit and more sessions remain separate. LIVE disabled, main untouched,
PR #1 draft and profitability unestablished.

## M1 offline options admission — 2026-10-09 UTC

M1 is **fixture verified**. [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md), version 1.1,
retains the adopted scope and milestone order; next is **M2 durable options PAPER
lifecycle**. [OPTIONS_ADMISSION.md](OPTIONS_ADMISSION.md) describes the implemented
API and its execution boundary.

Added `app.options.models` and pure `app.options.governor.admit_option`. Exact
broker-neutral identities bind underlying/root/right/strike/expiry, multiplier,
deliverable, US market, exercise/settlement and trading-time/tick metadata. Provider
IDs cannot override conflicting metadata. Frozen explicit PAPER policy and
reconciled account/population evidence stay outside the model proposal. The model
cannot grant quantity, bankroll, mode, tools or risk settings.

Admission checks exact identities, complete REALTIME two-sided entry quotes,
source/receipt freshness and lag, synchronization, opposite call/put underlying
stop geometry, session and last-trading boundaries, existing stock/options holdings,
unresolved orders and entry health/cost blockers. Whole-contract quantity floors
independent cash, entry/exposure, full-premium, remaining daily/total-loss, observed
size and contract caps, with adverse tick-rounded slippage and explicit entry/
reserved-exit fees. No minimum-one rounding or stop-risk discount. Adjusted/OTC/
non-US/incompatible metadata and below-floor underlyings remain ineligible.

Exact owned closes use bid/whole size and signed cash change. Entry/model/unknown
budget blockers do not veto a valid funded close; missing bid, stale/unowned/
unresolved evidence cannot invent flatness. Low-value closes can spend settled cash
on fees without borrowing. A bounded approval expires with its earliest evidence,
session, cutoff or last-trading deadline. Money/quantity schemas reject binary
float, nonfinite, fractional and malformed inputs. UTC normalization preserves
actual DST instants; Decimal arithmetic does not inherit ambient precision/range.

Fresh pre-edit GitHub/local branch and PR #1 matched
`f3e244e333f00de310f50cc272ca7b35f1c1162e`, tree
`eef983c73da982df02347b2725b19f402f88b2b0`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR open/draft and checkout clean.

Source checks: **184 options tests passed in 0.25 seconds**, warnings as errors.
**139 existing equity/risk/rehearsal/broker/trader tests passed in 3.79 seconds**,
warnings as errors. **1,531 full-suite tests passed in 384.34 seconds**, warnings
as errors, from copied tests/deploy/scripts outside the checkout against the final
installed wheel. Native runtime/control/alert/checkpoint/archive children used that
installation. All **96 application Python files** match source, wheel and installed
bytes. Wheel SHA-256:
`c02b38f9dd729973cc24428cedd1aa0c7394fc9479f2f996fa265b786c89c977`.
Scoped Ruff lint/format, compilation, installed-environment `pip check`, **53 local
document links** and staged whitespace passed. Preliminary installed runs were
stopped during code review and are not counted as completed verification.

This is local fixture/package proof only. No option provider read, authenticated
account check, model call, SHADOW preview, actual host installation or broker write
occurred. The module does not reserve, submit, reconcile fills, exercise or settle
options, and is not wired into the current runtime. M2 must persist policy/evidence/
reservations, re-admit fresh authoritative inputs and implement the durable option
lifecycle and independent exits. No SignalFlow or frozen deployment change.
LIVE remains disabled; PR stays draft and main untouched. Original stock PAPER
engine estimate remains approximately 89%; options M1 fixture verified, M2–M7 open,
expanded LIVE readiness and profitability unassessed.

## Source of truth and second operator report — 2026-10-09 UTC

[SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md), version 1.0, now owns current product
scope, working engineering decisions, milestone dependencies and acceptance gates.
The expanded goal is stocks and fully funded long calls/puts using one trader,
bankroll, brokerage and position, adapting Degen/0DTE, Swing and exact SPXW Scope.
Next work is **M1 option identity and deterministic admission**, then M2 durable
options PAPER lifecycle. Model-independent exits, UI/data truth, actual host/provider
acceptance and a reviewed live path have distinct gates. Swing/Scope follow on the
same foundation without delaying a separately accepted first-family research canary.
LIVE stays disabled and no real broker writes are authorized by this document change.

Fresh GitHub matched branch/PR `a55b6bcf512669a8ebb0afa84fd271ff4deca1ad`, tree
`9399594922eea2ba59a5759281fb0d1ff72e3af2`; main stayed
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft, checkout clean before edits.

The operator supplied a 12-page second PDF, printed October 9 at 01:16 ET, describing
the October 8 session. [SHADOW2_EVIDENCE.md](SHADOW2_EVIDENCE.md) retains aggregate
findings, extraction limits and source identity. PDF SHA-256:
`e5cd5ec7278cdced234f54080fb15593c0c3d4e6d8b7f5631c3935c23a468987`.
This is supplied printed API evidence, not our authenticated fetch. Revision 52
shows cycles 28–52, 23 HOLDs/one OPEN_LONG/one CLOSE, 24 attempted calls and no
visible agent errors. Cycle 27 is outside the default window. Latest state is flat,
no pending intent, zero unknown/unaccounted calls. Exact scheduler completeness
still needs the separate worker/slot audit.

A new synthetic XLE pair bought/sold 0.03051699 shares in cycles 44/51 after source
proposals 43/50. Price profit is $0.0004482945831. The earlier XLV pair is unchanged.
Cumulative price P&L is -$0.01191747402515, configured model cost $0.0281580, net
equity $9.95992452597485, net return -0.4007547402515%; matching SPY return
-0.453936060819%, net excess +0.0531813205675 percentage points. Incremental model
cost is $0.0139332, versus visible-window receipts totaling $0.0134582; the $0.0004750
difference cannot be attributed to a specific omitted receipt from this PDF.

Decimal checks reconcile all fill notionals, pair/cumulative P&L, gross/net equity,
return/excess and each visible usage charge. Rendered first/last pages were checked.
Visible old-worker latency is 10.087–26.349 seconds, median 12.0435; it does not
prove newer bounded model-process acceptance. Current collector source deliberately
sets relative volume to None, explaining an observed missing confirmation input.
Keep the old experiment frozen; new setup evidence belongs in the new population.
Two trades and a small benchmark lead do not establish profitability.

This is documentation/evidence work only, with no application/dependency/wheel,
deployment, SignalFlow or provider change. No authenticated broker/model/market
call or host access occurred. Prior application-suite and source-audit test results
remain historical proof, not newly rerun or options acceptance. The old PAPER engine
estimate remains approximately 89%; expanded options and LIVE readiness unassessed.

## Active goal correction and research — 2026-10-09 UTC

The user's latest direction is stocks **and options**, adapting SignalFlow's Degen/
0DTE, Swing, Scope Wizard and UI toward eventual governed LIVE trading. Historical
stock-only continuation rules describe the frozen original experiment. Current
code is still equities PAPER/SHADOW with LIVE disabled and no broker write adapter.
See [OPTIONS_LIVE_PIVOT_RESEARCH.md](OPTIONS_LIVE_PIVOT_RESEARCH.md) for the new
implementation queue and evidence boundaries. Continue next with broker-neutral
exact option contracts, Decimal full-premium limits and whole-contract deterministic
admission, then options PAPER lifecycle and candidate/UI adaptation. Avoid another
generic infrastructure slice without a demonstrated missing requirement.

Fresh GitHub verified branch/PR head `607ab623191e70716a3086d5a967571f60d460ce`,
tree `678c4251ea55e26ec28bb3db8d6d9f0ef1850db5`, unchanged main
`b5359aaf396e692d2142d7e02908f1544e045ee6` and draft PR #1 before edits.
SignalFlow main remains `f9eaf2c1b5d13dca287ee7138126883065b00395`.
Sixty selected reference documents/modules/components/tests match canonical Git
blob hashes; the [manifest](research/signalflow_options_sources.json) separately
records unmerged draft management PR #102 at `3cd8015da171e272ac25617f2b7ae459e41da00f`.

Sixteen unchanged reference Scope/Swing tests ran after recovery of storage
dependencies: 15 passed, one failed because the fixed August 3 evidence is pruned
by Scope's actual-time 45-day retention on October 9. A diagnostic confirmed the
row is absent after the first save and neither save is recognized as a duplicate.
The 15 remaining decision/evidence tests passed in 0.08s with warnings as errors;
the retention test was explicitly deselected, not fixed or represented as passing.
No full SignalFlow suite, UI rendering or deployment was verified.

Primary broker/market/rule and strategy/LLM research now distinguishes public
capability from account entitlement, published backtests from reproduced net option
returns, and source UI from observed operation. Current Robinhood documentation
lists external-agent options tools; verify the existing brokerage before migrating.
This is documentation-only work, with no application/dependency/wheel changes,
broker/model/market calls, SignalFlow edits or host access. The prior 1,340-case
installed suite remains historical verification of unchanged application code.
The deployed synthetic cohort remains frozen. Intended options capital/loss limits,
authenticated account/feed evidence and actual isolated host/archive/host-loss
acceptance remain open. Do not activate LIVE or implement real writes from this
research. Keep the old PAPER engine estimate approximately 89%; expanded options
and LIVE readiness remain unassessed.

## Current checkpoint — 2026-10-09 UTC

Branch: `slice2/robinhood-read-shadow`. PR #1 remains draft. `main` remains untouched.
The authenticated core path is verified: strict OpenAI output, real Robinhood reads,
model judgment, deterministic governor and persisted SHADOW audit. Scheduling is
installed and its closed-session behavior is verified on the Mac. Provided synthetic
regular-session decisions/usage now support scheduled operation on the server; exact
claim completion still needs the worker audit. Forward quote outcome
tracking and a persistent Linux SHADOW service are implemented and verified offline.
The service and private read-only observer are now running on the permanent
DigitalOcean server, with both containers healthy. The opt-in synthetic bankroll
profile now has operator-provided regular-session API evidence: a 25-row window,
one simulated XLV round trip and known model usage/costs. That first session ended
flat with negative net return; it does not establish signal. Worker/slot completeness
still needs the separate audit response. Automatic container
restart and experiment configuration persistence passed the operator's host reboot
check. The operator confirmed the HTTPS dashboard login/page works. An integrity-checked
local backup succeeded and a nightly cron job is installed. Off-host protection,
mobile inspection, failure recovery and authenticated scheduled model-process
evidence remain deployment gates. The existing deployed synthetic path has now
provided scheduled-session decisions/usage/fills, while its worker/claim audit and
the newer bounded isolated model/market components still need verification. LIVE is disabled.

Parallel engineering now includes a separate offline execution lifecycle rehearsal,
informed by SignalFlow's reservation and authoritative reconciliation contracts.
It has no broker write adapter or connection to the deployed experiment. The latest
full installed-package suite passed **1,340 tests in 348.79 seconds with warnings treated as errors**,
including the previous 1,308 cases and 32 measured model-process evidence cases. Installed native
runtime/control/alert, checkpoint and archive receiver entry points were used in that full run. Interrupted
PAPER claims now support reviewed no-replay resolution through the existing control
transport, preserving the original cycle and its halt until a separate RESUME.
The source-bound market-only PAPER feed now connects through a bounded headless
read child; explicit new-population continuous refresh now joins the PAPER runtime.
Installed-package scheduled HOLD, repeated native reads, blocked-child cleanup and
native CLI SIGTERM proofs passed with local MCP fixtures.
The operator API now has a native TLS companion CLI which attaches without trader
startup recovery; installed-package tests preserved active SUBMITTING state, applied
a signed HALT once and drained actual SIGTERM with exit 0.
The independent alert CLI now uses the same safe attachment, retains lifetime
ownership and delivers halt alerts after the trader stops. All 91 installed
alert cases passed; actual native SIGTERM drained bounded work and restart did not
replay confirmed delivery. This is local TLS evidence, not external notifications.
Three independent systemd unit specifications now define isolated host lifecycles,
with no automatic trader-failure restart or coupling to the control/alert services.
All six host cases passed with installed native role processes; actual target-host
installation and sandbox enforcement remain unverified.
Earlier native HTTPS/runtime recovery proof remains recorded below. Authenticated
collector latency, full-universe availability and deployed composition remain unverified.
The deployed application release remains the one recorded below.

## Independent archive service lifecycle — 2026-10-09 UTC

Fresh GitHub matched branch/PR head `d8e3eaca5b12a334b4816bdc8aa3d8578cc33470`
and source tree `387274cea769e1add362af567c0b7960f2fee5c6`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

The implemented archive receiver lacked a reviewed independent host lifecycle.
`deploy/archive/trade-bot-archive.service` now supplies a separate `tradebot-archive`
UID/group and installed isolated interpreter, only the preinitialized object store
writable, and an unconditional read-only archive credential-root mask with just the
receiver directory bound back read-only. Additional optional PAPER/SHADOW path blocks
do not replace actual namespace testing. No unit is coupled to the trader services.
No hooks initialize/adopt/reset state, upload, prune, report, repair or restore authority.

The original native 30-second shared socket budget stays unchanged. SIGTERM drains
current work before releasing the lease, with a 45-second host cgroup stop bound;
hardware/filesystem stalls can still reach final kill. Ten-second failure restart
and three starts per five minutes bound process retries. Restart only reopens the
same store/listener and cannot replay a client upload or replace incomplete evidence.
Missing provisioning conditions can skip startup and are not readiness evidence.
The source unit's explicit `archive.invalid` hostname is a placeholder requiring
reviewed substitution to the actual independent TLS origin before installation.
No secret value is in unit arguments/environment; user/storage/TLS/quota/encryption/
network provisioning remains explicit and separate from this repository change.

All **162 installed-package archive/receiver/checkpoint/catalog/durability cases
passed in 87.10s**, warnings treated as errors, outside the checkout against the
unchanged verified wheel. Seven new service cases exercise the real unit-derived
command with only interpreter, disposable paths and loopback origin/listener/port
substitutions; the production 30-second budget remains intact. Native SIGTERM drains
an admitted stalled upload within the 45-second bound; actual SIGKILL/restart retains
its original incomplete bytes, releases ownership and permits a later distinct
upload. Complete object bytes/inode and authenticated retrieval survive both paths;
duplicate native owners fail without replacing evidence. Missing store/token/key
cannot initialize/adopt state. Native systemd parser validation passes with only
local executable/user/group substitutions. None of this imposes systemd cgroups
or namespaces on the workspace processes.

The final seven installed service cases also passed in **32.07s**, warnings treated
as errors, after a test-only missing-key path adjustment preserved the shared TLS
fixture. Final staged test/unit bytes match source. The initial seven source cases
passed in 32.05s; the adjusted three missing-provisioning source cases passed in 0.45s.

The existing 95 application source/wheel/installed files remain identical. No new
application release or dependency change is needed; the prior full installed suite
remains **1,340 passing cases in 348.79s**, not a newly claimed 1,347-case full run.
Wheel SHA-256 remains
`ae3f8b7fe34d13b54718c7aabe66f5bc81dc3fac9ff0d1c7d07126f4ab214bd2`.
Scoped new-test Ruff lint/format, compilation, dependency pins, pip check, local
document links and whitespace passed.

The [archive host procedure](CHECKPOINT_ARCHIVE_HOST.md) describes the exact reviewed
paths, origin substitution, boot/failure/stop and authenticated recovery evidence.
No archive/trader host was accessed, unit installed/enabled, credential requested,
remote object uploaded or deployment changed. Reports retain off_host_protection
UNVERIFIED and execution_authority false. Actual independent archive namespace/
cgroup/boot/storage/retention/retrieval and real source-host-loss still need operator
evidence, alongside target PAPER host acceptance, authenticated market/model usage/
billing, independent alerts and the frozen worker/slot audit. LIVE stays disabled;
engine completeness remains approximately **89%**, excluding LIVE readiness and
demonstrated profitability.

## Measured bounded model-process evidence — 2026-10-09 UTC

Fresh GitHub matched branch/PR head `63d6f059e128d8c58782f2849a4a2291fa6c2767`
and source tree `6cfc0155dae61a32d0bead37ff604488d51c4740`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

The existing bounded model path retained usage and decisions but lacked measured
count/generation and invocation/reaping observations for authenticated acceptance.
Its fixed child now measures only the existing input-count and generation SDK
methods: strict 0/1 attempted/completed counts, cumulative elapsed intervals and
whole perform time. Completion means the SDK returned, before usage/decision
acceptance; refusals/invalid usage still fail to HOLD with their existing accounting.
No new request, tool, model input, raw response, credential path or key is retained.

Existing MODEL_JUDGMENT_RECORDED and MODEL_JUDGMENT_INTERRUPTED events now retain
`paper-model-process-evidence-v1`: model, saved attempt packet hash, exact frozen
configuration, original process/request limits, monotonic admission, invocation
and child-reaping intervals, total and optional child observations. Cancellation
records timing only after owned work cleanup, preserves unknown cost and cannot
replay its durable attempt. Native timing includes spawning/imports, client
creation/closure, protocol validation and reaping; child perform timing includes
local validation/decision parsing. Total ends before settlement/recording.
Missing/incoherent observations remain UNVERIFIED; coherent observations are
OBSERVED only as measurements. Provider and billing acceptance always remain
UNVERIFIED and execution_authority false. Invalid diagnostic types/bounds fail
the existing child protocol. There is no new journal schema/event kind, approval
gate, policy hash, prompt, request ceiling, SDK retry, model price or runtime command.

All **120 focused judgment/output/runtime cases passed in 19.18s**, warnings treated
as errors, including **32 new evidence cases**. They bind measurements to unchanged
provider payloads, exact durable packet/configuration/usage/cost identity, successful
deterministic approval and paired restore verification; partial failures/refusals,
missing/incoherent/invalid diagnostics and cancelled work preserve existing HOLD,
usage/uncertainty and no-replay behavior. An actual isolated private worker with a
local pinned-SDK transport recorded both calls and was reaped before parent evidence.
An initial new test incorrectly assumed its fixture was fenced; explicit enrollment
corrected that test, without changing production fencing or accepting UNFENCED proof.

The first installed full run recorded **2 failures and 1,338 passes in 326.65s**:
native control shutdown emitted an empty-task grace timeout, and an existing
closed-to-open market fixture timed out waiting for a complete cycle. Both passed
in isolation in 75.01s. Pinned Uvicorn awaits native TLS server closure; CPython's
TLS close budget and the configured control grace both used 30 seconds, allowing
a deadline race. Control grace is now 35 seconds, still inside the unchanged
45-second host cgroup bound. The companion test explicitly checks that ordering.
The disposable market fixture now holds the first exact sample for native
reconciliation, freezes a five-second test read/eight-second source age budget,
observes early task failure and always drains in finally. Production freshness/
collection/approval guards are unchanged. All **60 source market/companion/host
integration cases passed in 150.33s**, warnings treated as errors, including actual
read-failure/hard-kill restart, independent companion operation and SIGTERM.
These supporting fixes resolve verification races; they do not complete host acceptance.

Final verification: **1,340 installed-package tests passed in 348.79s**, warnings treated as errors, outside the checkout
against the final installed wheel. Native runtime/control/alert/market/model/checkpoint/
archive processes ran with installed interpreters. Final staged test bytes and all
95 application source/wheel/installed files matched. Scoped Ruff lint/format,
compilation, pinned dependencies, pip check, document links and whitespace passed.
The touched market/companion fixture files retain 20/5 baseline lint findings;
comparison to the parent confirmed no new findings, and both formats passed.
Wheel SHA-256:
`ae3f8b7fe34d13b54718c7aabe66f5bc81dc3fac9ff0d1c7d07126f4ab214bd2`.

The [authenticated model acceptance procedure](PAPER_MODEL_ACCEPTANCE.md) uses a new
full-universe continuous-market population with the existing prompt/limits and total/
daily budgets equal to the frozen single-call reservation. Positive known cost or
unknown usage prevents a second full reservation. The existing run command receives
an explicit outer timeout; its report retains the latest bounded event/cycle window.
Neither wrapper exit status, skipped HOLD, SDK method counts nor configured-rate
generation cost proves provider acceptance, invoice correctness, preflight billing
or full scheduler completeness. No authenticated call occurred in this workspace,
no credentials were requested and no deployed population/provider/host was changed.
Target-host namespace/boot/application lifecycle, authenticated market/model usage/
billing, independent alert/archive retention/retrieval, real host-loss and the old
worker/slot audit remain open. LIVE disabled; engine completeness remains approximately
**89%**, excluding LIVE readiness and demonstrated profitability.

## Independent native TLS checkpoint archive — 2026-10-09 UTC

Fresh GitHub matched branch/PR head `f94ad6ac434dd38cb59c73f5ba2bc8240bcb07a6`
and source tree `4ecae1ba8a6639e0a1e8b51c10528053019ff6af`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

The archive transfer client had only a local fixture receiver. The standalone
`app.execution.archive_cli init/serve/report` now implements its existing exact
native HTTPS PUT/GET contract on explicitly provisioned independent storage.
It uses only the standard library, retains opaque bytes and opens no checkpoint
database, engine, broker/model client or deployed state. It neither installs a
service nor schedules uploads or changes the frozen SHADOW experiment.

Explicit initialization exclusively creates a private capacity-bound store.
A retained directory descriptor and nonblocking lifetime lease admit one receiver
or report owner. Authenticated exact content-addressed PUT durably reserves a new
private directory before reading a bounded body, hashes complete bytes, fsyncs the
file and exclusively publishes/fsyncs its identity before confirming retention.
Wrong framing/identity/authentication/origin, ambiguous/forwarded metadata, traversal,
encodings and oversized inputs cannot claim acceptance. Stored identity retries
recheck private size/hash/durability and hash their complete body without replacement.
Interrupted/corrupt admissions remain retained, consume capacity and cannot be
overwritten or repaired by retry. No delete/prune/restore/promotion endpoint exists.

Native TLS 1.2+ is mandatory, with private separate token/key material, explicit
origin/listener and no proxy/plaintext fallback. One connection at a time shares a
maximum 30-second socket watchdog across handshake, headers, body and reply.
Filesystem hashing/fsync still cannot guarantee hard deadlines under hardware stalls.
SIGTERM drains the current request loop; SIGKILL preserves admitted evidence and
releases process ownership. GET checks original private bytes before transmission;
the existing isolated download client independently verifies its separately retained
pin. Local exclusive reports distinguish VERIFIED/INCOMPLETE/UNAVAILABLE and always
retain `off_host_protection=UNVERIFIED`, `execution_authority=false`.

The initial receiver run failed because a test helper treated the stdlib HTTP client
as a context manager. The helper was corrected; all 42 initial receiver cases passed
in 17.64s. The strengthened combined source receiver/checkpoint/catalog/durability
run passed **153 tests in 51.46s**, warnings treated as errors. The final full suite
also includes two added storage-permission cases, for **44 new receiver cases**.
Actual native SIGKILL during a partial body retained incomplete admission/bytes,
released the lease and allowed a distinct upload after restart without replacing the
partial evidence. TLS/header stalls expired independently; an admitted stalled body
drained actual SIGTERM. Fsync failures never claimed retention; a lost publication
confirmation retried an unchanged complete inode. A separate native receiver process
accepted the existing client upload, restarted after source journal/authority/bundle
deletion, returned the original object and staged unresolved model evidence.
Engine attachment still failed `RESTORE_AUTHORITY_MISSING`.

Final verification: **1,308 installed-package tests passed in 347.43s**, warnings treated as errors, outside the checkout
against the final installed wheel. Native receiver and existing runtime/control/alert/
market/model/checkpoint entry points ran with installed interpreters. Final staged
tests and all 95 application source/wheel/installed files matched. Scoped Ruff
lint/format, compilation, dependency pins, pip check, document links and whitespace
passed. Wheel SHA-256:
`43f16245bca5c8b03e72cc685f7d39ff134979b3875311fb778584f0c7965e59`.

The [receiver provisioning and acceptance procedure](CHECKPOINT_ARCHIVE.md) requires
a dedicated independently hosted UID/storage/quota/retention/encryption/native TLS
endpoint, secret and lifecycle. No such host was accessed or deployed. The local
source-loss test is simulated process/source loss within one workspace, not actual
off-host durability or host-loss recovery. Independent alerts/archive acceptance and
a real host-loss drill remain open, with target-host namespace/boot/application
lifecycle, authenticated full-universe market latency, bounded model usage/billing
and the old worker/slot audit. Main, deployment and provider accounts remain unchanged;
LIVE disabled. Engine completeness remains approximately **89%**, excluding LIVE
readiness and demonstrated profitability.

## Measured full-universe market evidence — 2026-10-08 UTC

Fresh GitHub matched branch/PR head `2ef2938d1ab236367619660f7055b072666b679c`
and source tree `131c817fc9b5e24c14500dc9b1c40cd6fd89dd5f`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

The existing one-shot collector previously returned publication/candidate counts
without measured latency or observed tool counts for the authenticated 20-symbol
gate. It now returns `paper-market-read-evidence-v1`: feed/request/source identity,
exact universe, collection/check/oldest quote clocks, saved packet hash, the original
timeout, parent read/reaping, validation/publication and total monotonic intervals.
The child observes only its four existing safe gateway methods, counts attempted
and validated completed calls and measures cumulative method duration. Collection
time includes connection closure. Arguments, account IDs, credential paths/contents
and raw responses are not retained in those observations.

Twenty symbols require 24 observed gateway calls: one account selection, one quote
batch, two tradability batches and 20 single-symbol histories. Coherent counts and
child/parent timing receive `OBSERVED`; absent/incoherent diagnostics remain
`UNVERIFIED`. These observations do not gate publication, grant provider acceptance
or change entry policy. Invalid diagnostic types/bounds fail the existing bounded
child protocol. There is no new command, reader, automatic retry, quote schema,
execution-journal field, policy migration or model-visible packet data. Continuous
health/admission, private credentials, original deadline and atomic publication
rules remain intact. The [collection procedure](PAPER_MARKET_ACCEPTANCE.md) provides
an explicit new disposable full-universe one-shot population and retained report.

All **175 focused source market cases passed in 12.11s**, warnings treated as errors.
Twenty-two new tests bind report hashes/identities to the actual saved sample,
measure parent interval boundaries, reject invalid counters/times, retain incomplete
counts after cancellation/failure, preserve the capability firewall and keep
missing/incoherent observations from claiming acceptance. Five existing actual
20-symbol child cases now assert complete safe-call counts, measured intervals and
no private data while preserving failure atomicity and reaping. An earlier focused
run stalled at a test wait and was stopped; the complete rerun with per-test logging
and traceback deadlines passed. No diagnosis or successful result is inferred from
the interrupted run.

Final verification: **1,264 installed-package tests passed in 328.42s**, warnings
treated as errors, outside the checkout against the final wheel. Installed native
runtime/control/alert/market/model and checkpoint/catalog/archive entry points ran;
the market fixture child explicitly used the final installed interpreter. Final
staged test bytes and all 93 application source/wheel/installed files matched.
Scoped Ruff lint/format, compilation, pinned dependencies, pip check, document
links and whitespace passed. Wheel SHA-256:
`5ed2575bcf70242040dbc43b6a4282497eaf772f506d7cbfeddec3e54c9085e6`.

Every report retains `provider_acceptance=UNVERIFIED`, `execution_authority=false`
and LIVE disabled. Local MCP fixtures can produce the same report shape; gateway
invocations are not every HTTP/OAuth exchange or provider-internal retry. Actual
authenticated regular-session latency/coverage and continuous cadence remain open,
alongside target-host namespace/application lifecycle, bounded authenticated model
usage/billing, independent alerts/archive recovery, host-loss and the old worker/slot
audit. No host, deployed frozen experiment or provider account was changed. Engine
completeness remains approximately **89%**, excluding LIVE readiness and profitability.

## Disposable systemd sandbox integration — 2026-10-08 UTC

Fresh GitHub matched branch/PR head `c02f645413b1d16204df352a4a858692f9962eda`
and source tree `4e73d3059c06d9eb396ca4b08f733d2a28262299`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

The next host namespace gate now has an explicit executable integration harness,
`scripts/paper-sandbox-acceptance.py --run`, with trusted-source transfer and result
instructions in [PAPER_SANDBOX_ACCEPTANCE.md](PAPER_SANDBOX_ACCEPTANCE.md). It requires
root, systemd PID 1 and a pre-provisioned non-root service user/group; prerequisites
and all four reviewed source-unit digests are checked before transient admission.
It neither creates an account nor installs, enables or changes a production unit.
It never touches a real credential, database, authority or deployed SHADOW checkout.

Eight unique transient probe cases preserve all reviewed `[Service]` restrictions
with only disposable PAPER path, command/type and test lifecycle substitutions.
Service-UID reads/writes check allowed read-only versus market-refresh access,
denied peers, read-only system paths, an unlisted directory created after startup,
and initially absent known peers created while the same probe remains alive.
Absent optional binds cannot acquire access without restart. Reports retain both
matrices, identity, source-unit digest and transient name. Probe/manager waits and
runtime are bounded; lost start responses still require stop. Unconfirmed cleanup
retains fixtures and the exact transient name, blocks further cases and grants no
success. No daemon-reload, application startup or provider/network request occurs.

All **37 source harness tests passed in 0.33s**, warnings treated as errors, including
four native parser cases and an actual stdlib probe handshake/SIGTERM. Mocked manager
and access matrices prove orchestration, not kernel enforcement. Tests also reject
unrestricted dummy access as proof, final-template drift before any admission,
missing prerequisites and failed/expired probes; uncertain starts are stopped and
failed cleanup preserves fixtures. The native CLI on this workspace returned exit 1
with `SYSTEMD_MANAGER_UNAVAILABLE`, no fixture setup or transient service submission.

Final verification: **1,242 installed-package tests passed in 327.00s**, warnings
treated as errors, outside the checkout against the retained verified wheel. Native
runtime/control/alert/market/model and checkpoint/catalog/archive entry points ran.
The final harness/test bytes matched the full-suite stage. All 93 application files
remain byte-identical to source, installed package and the earlier verified wheel;
no application or reviewed production unit bytes changed. Scoped Ruff lint/format,
compilation, pinned dependencies, pip check, document links and whitespace passed.
Retained wheel SHA-256:
`474cab3e04c40c56cf3d1af3702878ffe737b9c8986be435f1a04390f20e9d64`.

Even matching actual-host probe reports retain `host_acceptance=UNVERIFIED`, no
execution authority and LIVE disabled. The substituted paths/dummy command do not
prove fixed installed mounts, SHADOW path access denial, real credentials, all network
or cgroup restrictions, application/boot/lifecycle or checkpoint timer behavior.
Actual target-host execution, authenticated market/model evidence, independent
alerts/archive recovery and the old worker/slot audit remain open. The frozen deployed
experiment is unchanged. Engine completeness remains approximately **89%**, excluding
LIVE readiness and demonstrated profitability.

## Checkpoint extraction pin binding — 2026-10-08 UTC

Fresh GitHub matched branch/PR head `f7f1482995bbe3f8dc375f8ac7c4ed2ca9402698`
and source tree `8b7150e3f2e9647c97d4912d85498f17c89b9d30`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6` and PR #1 draft.

Two pre-fix regressions reproduced inspection and staging accepting a complete
older pair after an in-place bundle rewrite between the initial hash scan and
extraction. The input kept the same inode and byte count; its older member hashes,
schema and paired authority were valid. Verification nevertheless reported the
newer independent pin, so the initial scan did not bind the evidence actually read.

Extraction now hashes the exact consumed magic, length, manifest and both member
payloads, checks final EOF and compares that digest to the independent pin before
opening any SQLite member. Changed consumed bytes and newly appended trailing
bytes reject inspection/staging; staging removes its incomplete quarantine and
publishes no verified marker. A later rewrite of header bytes already consumed
can still preserve the original pinned extracted snapshot. This checks snapshot
identity, not ongoing path retention or protection against the filesystem owner.
No source state, replay, promotion or usable execution authority is added.

All **137 source checkpoint/catalog/durability/restore tests passed in 34.42s**,
warnings treated as errors. Ten added cases cover old-pair substitution,
same-size header changes, appended bytes, mutation of already-consumed headers,
no SQLite opening on changed pins, incomplete staging cleanup, unchanged source
pairs, preserved unknown model evidence, execution denial and sanitized CLI failure.
The first two regressions failed before the production fix. A subsequent fixture
mistake changed JSON header lengths; it was corrected with same-size byte rewrites
before complete affected-suite verification.

Final verification: **1,205 installed-package tests passed in 318.07s**, warnings
treated as errors, outside the checkout against the verified final wheel. The run
used installed native runtime/control/alert/market/model and checkpoint/catalog/archive
entry points. Scoped Ruff lint/format, compilation, pinned dependencies, pip check
and whitespace passed. All 93 application files matched source, wheel and installed
bytes. Wheel SHA-256:
`474cab3e04c40c56cf3d1af3702878ffe737b9c8986be435f1a04390f20e9d64`.

The frozen deployed synthetic experiment, host and provider accounts remain
untouched. Local race fixtures do not prove independent archive retention or a
real host-loss drill. Actual isolated-host namespace/boot/lifecycle checks,
authenticated market/model evidence, external alert/archive acceptance and recovery,
and the old worker/slot audit remain open. Engine completeness remains approximately
**89%**, excluding LIVE readiness and demonstrated profitability.

## Read-only isolated host snapshot audit — 2026-10-08 UTC

Fresh GitHub matched branch/PR head `a2fd63d7043b798bc01bc2745cf813e1641078c5`
and source tree `40edad38ed7d8984c38aa56af815f192c71176f0`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

Host acceptance previously required manual unit/process/mount inspection. The
installed `python -I -B -m app.execution.host_audit` now collects a bounded,
read-only `paper-host-audit-v1` report for the three separately installed PAPER
services. It pins exact reviewed root-owned unit bytes, rejects drop-ins/reload
drift, checks fixed manager properties and running process UID/GID/command/start
identity, then observes the credential root tmpfs and role bind identities/options
through that process's root view. Unexpected credential names, nested mounts,
visible peers and changing process/mount/unit/boot observations block the snapshot.
Absent optional runtime credentials and empty mode-000 inaccessible placeholders
are handled without opening any credential contents. Each fixed read-only manager
query explicitly retains empty requested properties with `--all` and has a
five-second deadline, 64KiB response limit, sanitized failures and
retained child ownership across cancellation. There are no path/unit overrides.

The audit opens no execution/authority database, journal or credential file and
performs no installation, service lifecycle action, provider call or execution.
Even matching snapshots retain `host_acceptance=UNVERIFIED` and no execution
authority. Observations are sequential, not atomic host acceptance. Full namespace,
service-UID access, cgroup/children, peer creation after startup, boot/lifecycle,
provider/alert/archive operation, optional checkpoint timer and host-loss recovery
remain independent gates. See [the command and limits](PAPER_HOST.md).

Local fixture/native query proof: **55 final audit tests passed in 0.45s**; all **61
focused audit/host tests passed in 145.91s**, warnings treated as errors. Tests cover
unit symlink/special-file/writable/content drift, manager protocol/settings,
credential bind ownership/inode/options, visible peers, nested/stacked mounts,
read-only per-mount versus superblock options, metadata-only process collection,
changed PID/mount/unit/boot identity, sanitized errors and actual query
timeout/overflow/cancellation cleanup. No namespace fixture is target-host proof.
The installed CLI on this workspace's non-systemd host returned exit 1 with
`SYSTEMD_MANAGER_UNAVAILABLE`, no role queries or setup/fallback and no authority.

Final verification: **1,195 installed-package tests passed in 342.90s**, warnings
treated as errors, outside the checkout against the final wheel. Native isolated
runtime/control/alert/market/model and checkpoint/catalog/archive entry points were
used. A query regression rejected the missing `--all` flag before its correction;
the earlier full run and subsequent final run were retained separately. Scoped Ruff
lint/format, compilation, pinned dependencies, pip check and whitespace passed.
All 93 application files matched source, wheel and installed bytes. Wheel SHA-256:
`c8ec849d015c32675542e8328ce7f07dd6a978a66d9a7418147fd5f0649a330d`.

No DigitalOcean installation, host access, credential provisioning, experiment
retuning or broker/model account action occurred. The frozen deployed synthetic
experiment and its worker/slot audit remain separate. Engine completeness remains
approximately **89%**, excluding LIVE readiness and demonstrated profitability.

## Fixed execution-child import isolation follow-up — 2026-10-08 UTC

Fresh GitHub matched branch/PR head `f07a2b4b80e3c19ff1ed7113cf645f3631cc8c5e`
and source tree `682525ce2662d435499c469190216e9871189646`; main stayed
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

Systemd's parent `-I` did not carry into its newly launched execution interpreters.
All five fixed child commands omitted isolation; four also inherited PYTHONPATH.
A native pre-fix regression executed a planted working-directory `app` package
before fixture request validation. Fixture venue, judgment, market, alert and archive
children now launch `sys.executable -I -m` with PATH/LANG/LC_ALL only, plus the explicit
model key for judgment. No Python path/settings variables are forwarded. The selected
interpreter must already have the application/dependencies installed. Root-owned
installed packages/hooks remain trusted; this is not OS or same-UID/host-owner isolation.

Fifteen native regressions cross all five fixed workers with planted current-directory
packages, PYTHONPATH packages and startup hooks. Bad private requests exercise native
error protocols without clients/credentials/network; the venue child instead completes
a valid local snapshot with unchanged database bytes. All children are reaped, no
poison marker executes, and ambient model/broker/Python settings are excluded. Existing
model/MCP test transports now preserve/assert the child isolation flag. All 124 focused
source cases passed in 29.89s with warnings treated as errors.

The first full run exposed an existing fixture race: a deliberately paused market
read expired under its half-second test deadline while native entry/reconciliation
ran, leaving an unbounded callback wait after runtime failure. That disposable test
now enrolls a five-second read/eight-second source-health policy before attempts,
uses bounded failure-aware waits and always drains its owner. Production deadlines,
freshness and frozen policies are unchanged. All 26 source composition cases passed
in 8.93s; the interrupted full-run log was retained before complete re-verification.

Verification: **1,140 installed-package tests passed in 347.68s**, warnings treated
as errors, including native runtime/control/alert/market/model, checkpoint/catalog/archive
and host entry points. Scoped Ruff lint/format, compilation,
pinned-dependency check, pip check and whitespace passed; the modified legacy market
tests retain their pre-existing lint baselines (4 read findings, 20 service findings), with
none introduced.
All 92 application files matched source, wheel and installed bytes. Wheel SHA-256:
`981a6316a1343706e298031fafb39453e8a0360fb5225a7a569173107debb320`.

No deployed code/experiment, host or broker/model account was changed. Local import
proof does not satisfy actual target-host namespace/boot/lifecycle gates. Authenticated
full-universe market/model evidence, independent alert/archive acceptance and retention,
host-loss recovery and the old worker/slot audit remain open. Engine completeness is
approximately **89%**, excluding LIVE readiness and demonstrated profitability.

## Isolated model response acceptance follow-up — 2026-10-08 UTC

Fresh GitHub branch/PR state matched `56a994a65f1821a341427d1e312ef5d71a27e8eb`,
source tree `977a231b9e2a1a6d7391fbfeb72fdd97e6e73964`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

A pinned-SDK regression reproduced an OPEN_LONG being accepted from completed
output containing both valid decision text and a refusal. The SDK convenience
property also joins text across messages/blocks, omitting non-text content and
message completion/role/phase checks. The isolated child now parses exactly one
text block from one completed assistant final decision message. Mixed refusals,
multiple/fragmented messages or blocks, foreign roles, intermediate/unknown phases,
unfinished/unknown reasoning status and non-message/reasoning output fail to HOLD.
Optional reasoning status may be absent or completed. Provider usage is retained
before decision checks; prompt, schema, model, rates, ceilings and tools are unchanged.

Twenty-five new cases cover 18 ambiguous pinned-SDK envelopes, five valid decision/
reasoning shapes including HOLD, and two actual private worker/main runs with local
HTTP transports. Native parent bounds/watchdog and durable accounting run normally:
the failure settles reported usage, emits one sanitized judgment alert, creates no
order, rejects substituting the hidden OPEN_LONG and rejects replay of the same source.
The pre-fix refusal case failed as expected. All 61 focused source judgment cases
passed in 12.05s with warnings treated as errors.

Verification: **1,125 installed-package tests passed in 323.84s**, warnings treated
as errors, including native runtime/control/alert/market/model and checkpoint/catalog/archive
entry points. Scoped Ruff lint/format, compilation,
pinned-dependency check, `pip check` and whitespace checks passed. All 92 application
files matched source, wheel and installed bytes. Wheel SHA-256:
`559f071e2a0c4baf2016e7bbb445e0f124f4f6edd66bebbe2b19520190ee4817`.

These are local response/accounting fixtures, not authenticated model output, real
billing, target-host operation or profitability. No deployed experiment or host was
changed. Remaining gates are target-host namespace/boot/lifecycle validation,
authenticated full-universe market/model evidence, external alert/archive acceptance
and independent retention, host-loss recovery, and the old worker/slot audit.
Engine completeness remains approximately **89%**, excluding LIVE readiness and
demonstrated profitability.

## Execution evidence parent durability follow-up — 2026-10-08 UTC

Fresh GitHub branch/PR state matched `6baed0baa6caff68853d6048f15ec3ff9f6fc2e4`,
source tree `fe596b9cfc99e488d0b5f2201dcb25e7eb3ec970`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

Recovery staging flushed its final marker and directory but omitted the parent entry
that names the new quarantine. Output ancestors created by evidence commands also
used ordinary recursive mkdir without directory flushes. Export, receipt admission,
download and quarantine now flush their existing anchor/parent, then each new private
ancestor and its parent entry before evidence work or child admission. An existing
anchor left by a failed preparation is re-flushed on a separate explicit attempt.
Staging also flushes its parent after the verified marker/directory before success.
Existing modes, unrelated files, frozen enrollment and no-overwrite rules remain.

Ten focused regressions passed: real filesystem flush order, nested export/staging,
ancestor storage failures and explicit retry, final quarantine-parent failure with
sanitized CLI error/cleanup, archive admission denial before a durable parent, existing
mode/evidence preservation, and a native-TLS upload/download round trip after original
source/bundle deletion. Unknown model evidence survives in quarantine; engine opening
still fails with RESTORE_AUTHORITY_MISSING before mutation. This is local fixture
proof, not actual power-loss, cross-host durability or independently retained storage.

Verification: **1,100 installed-package tests passed in 303.37s**, warnings treated
as errors, including native runtime/control/alert/market, checkpoint/capture/archive
and host entry points. All 10 focused source regressions passed in 2.11s. Scoped Ruff
lint/format, compilation, pinned-dependency check, `pip check` and whitespace passed.
All 92 application files matched source, wheel and installed bytes. Wheel SHA-256:
`72cfea67beb9d3d19096197f0b8f86c0fbfd103a894dc4ee7f2dd26fc27e297a`.

No host or deployed experiment was changed. Remaining gates are target-host namespace,
boot/lifecycle verification, authenticated market/model evidence, external alert/archive
acceptance and independent retention, host-loss recovery, and the old worker/slot audit.
Engine completeness remains approximately **89%**, excluding LIVE readiness and
demonstrated profitability.

## Isolated PAPER credential namespace follow-up — 2026-10-08 UTC

Fresh GitHub branch/PR state matched `9b9a4a89df47846fe3b1bd398f84a3ae9bd8a764`,
tree `d27731a548b66c28de6e470cbd68e2277869ede6`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.

The existing optional peer-directory blocks were skipped when those host paths did
not exist at service startup. That leaves an incomplete direct credential view if
a peer or previously unlisted credential directory is provisioned later. Each of the
four isolated role units now mounts an unconditional empty read-only 1MiB tmpfs over
the credential root, then binds only permitted directories. Runtime gets read-only
model files and writable market OAuth; control gets read-only operator files;
alerts get read-only alert files; checkpoint gets no credential bind. Bound private
file/directory modes remain unchanged. Existing peer/SHADOW blocks, population access,
process lifecycles, restart limits and frozen enrollment remain unchanged.

The pattern follows the
[Ubuntu 24.04 systemd execution manual](https://manpages.ubuntu.com/manpages/noble/man5/systemd.exec.5.html).
It does not establish isolation from arbitrary same-UID processes or a host owner
changing mounts. This workspace has no systemd service manager; its nested user
namespace probe failed with `Operation not permitted`. No target-host service was
installed or accessed. The role contract/parser tests cannot prove kernel namespace
enforcement; target-host verification must inspect permitted read/write behavior and
absent-then-created peer directory visibility, along with boot/lifecycle behavior.

Application files are unchanged from the previous verified wheel and 1,090-test full
installed-package baseline. This follow-up changes unit specifications, their focused
contract assertions and host/status documentation only. **All 40 affected installed
host/checkpoint-catalog cases passed in 146.90s**, warnings treated as errors. The
native systemd 255 parser accepted all four role services and the checkpoint timer.
Existing installed native process tests cover failure halt, explicit restart,
surviving companions, signed ACK, graceful shutdown, capture interruption and source
loss; they launch role commands without applying systemd namespaces. Scoped E/F
lint, formatting and whitespace checks passed. All 92 application files still match
the previously verified wheel and installed bytes. The full suite was not repeated
for this unit-only follow-up; the 1,090-test application baseline is unchanged.

Engine completeness remains
approximately **89%**, excluding LIVE readiness and demonstrated profitability. The
remaining target-host, authenticated market/model, independent alert/archive retention
and host-loss gates, plus the old deployed worker/slot audit, remain open.

## Isolated PAPER publication deadline follow-up — 2026-10-08 UTC

Fresh branch and PR references matched `605297ea905d8614278a51b55eb02cc666802a01`,
source tree `c97ffd034cd90708150c5ade2b72ac1ca11a7422`; main remained
`b5359aaf396e692d2142d7e02908f1544e045ee6`, PR #1 draft and checkout clean.
This bounded follow-up supports the existing market-deadline gate. It adds no source
configuration, retry policy, market cache or deployment step.

The child timeout previously ended before cleanup and parent publication. A valid
child result could therefore admit a sample after the original request deadline.
The parent now passes that same monotonic deadline into publication. Observed expiry
before packet validation, after transaction acquisition or immediately before commit
rejects the refresh and rolls back uncommitted evidence. Acquisition and commit lock
waits use the remaining budget, capped at the existing 100ms. An expired idempotent
receipt cannot report success. Existing manual fixture publication remains unchanged.

Six injected expiry boundaries, actual native child cleanup under retained reader
ownership, before-deadline success, expired idempotency, real SQLite writer/reader
contention, and finite deadline validation are covered. The continuous-service case
first publishes successfully, then proves that late collection preserves its sample
and successful-health timestamps, halts, releases ownership and does not retry or
submit an order. These are local fixture proofs. Cleanup still completes after
expiry; filesystem/fsync stalls are not hard real-time bounded by these admission
checks. No authenticated provider timing or actual host integration was established.

Verification: **1,090 installed-package tests passed in 299.94s**, warnings treated
as errors, with the installed native runtime/control/alert, checkpoint and host
entry points. All 16 new deadline cases passed in the focused source run. Scoped
Ruff lint/format, compilation, pinned-dependency verification, `pip check` and
whitespace checks passed. All 92 application files matched source, wheel and installed
bytes; verified wheel SHA-256:
`db2fee1fe9e007f61795ab0826ef2143a1f3eb69b28ecdd2a8de7b612a4b645d`.

Engine completeness remains approximately **89%**, excluding LIVE readiness and
demonstrated profitability. The frozen deployed experiment remains unchanged. The
remaining gates are target-host namespace/boot/lifecycle validation, authenticated
full-universe market latency and model-process/billing evidence, independent alert
and archive acceptance/retention, a host-loss drill and the old worker/slot audit.

## Isolated PAPER market integrity and installed-package follow-up — 2026-10-08 UTC

Fresh GitHub references matched the supplied baseline before editing:
`952f992f04b24e1c5cc5f9d2dce5e83c8bd9eda0`, source tree
`e888f5aef03c7b577a78f1bfd227eaae29155d35` and main
`b5359aaf396e692d2142d7e02908f1544e045ee6`. PR #1 remained draft and the
recovered checkout was clean. No continuation or AGENTS.md was found in the repository.

Inspection found that dictionary construction in the shared market adapter could
silently collapse duplicate response rows or accept a historical response for a
different requested symbol. Historical timestamps and OHLC ranges were not checked
before indicator calculation. The isolated PAPER child now uses a strict subclass
of its existing four-tool market firewall; the shared legacy adapter and frozen
deployed experiment keep their existing behavior.

Quote, tradability and single-symbol history responses must each contain exactly
their requested unique symbols. Missing, extra, foreign, duplicate and null rows,
and MCP error flags, reject the whole refresh. Historical interval/bounds must match
the request. Each nonempty history has at most 2,048 bars, strictly increasing aware
timestamps inside its requested window, finite positive consistent OHLC values,
nonnegative integer volume and explicit boolean interpolation flags. Interpolated
bars keep their existing exclusion from indicators. No sorting, repair, substitution,
cache, extra capability, source-policy migration or automatic retry was added.

The parent retains existing complete-universe, quote freshness, child deadline,
lease/cleanup and atomic publication checks. A failed child leaves the prior sample
unchanged; the continuous service retains its existing halt/no-retry behavior.
Successful validation is not proof of contiguous/current-session bars, split-adjustment
correctness, authenticated availability, provider latency or deployed operation.

Full installed-package verification exposed a separate existing PAPER dashboard
asset-path defect: 1,073 tests passed, but its template lookup depended on the source
checkout working directory. The PAPER routes now resolve bundled templates relative
to their installed module, as the separate SHADOW observer already did. The dashboard
regression changes to an unrelated temporary directory before rendering and running
the existing stub HOLD cycle. This changes no observer routes or execution authority.

Final full installed-package suite: **1,074 tests passed in 309.35s with warnings
treated as errors**. The combined market/dashboard source run passed **143 tests
in 6.55s**, and the final installed-wheel focused run passed **143 tests in 6.64s**,
with warnings treated as errors. Scoped lint/format, compilation, pip check, exact
dependency-lock verification and whitespace checks passed.
The 48 new cases include the configured 20-symbol universe, reversed valid response
ordering, 10-symbol tradability batches, individual historical request bindings and
malformed history/identity rejection. Actual isolated native children made two
successful complete refreshes, or rejected cross-bound history, duplicate quotes,
future bars and invalid OHLC after a prior success. Failure preserved the prior
database bytes/sample, reaped children and released the reader lease. The native
fixture returned fake account selection solely for tradability and emitted no account
authority or private values. No remote broker/model call occurred.

All 92 application files were byte-verified against the source, wheel and installed
package. Dependency loading reuses the already verified pinned runtime environment;
application module/template origins resolve inside the wheel's installed package,
and the copied test workspace contains no application checkout. Final wheel SHA-256:
`aca65b5b7a1cd3c7a7f0d06f6d812e95a1825a63c70d3f47c0fbaff3866339b7`.

Next gates remain isolated target-host namespace/lifecycle validation, authenticated
full-universe timing/data and bounded model-process evidence, independently retained
archive recovery and a host-loss drill. The deployed virtual-v1 experiment stays
frozen and needs further sessions plus its separate worker/slot audit. LIVE remains
disabled. Rough engine completeness remains about 89%, excluding LIVE readiness and
demonstrated profitability.

## Bounded local checkpoint capture follow-up — 2026-10-08 UTC

The isolated PAPER engine now has explicit `checkpoint_cli capture-init`, `capture`
and `capture-report` commands. A new private catalog freezes the canonical source,
verified authority UUID, cooperative timeout and admission capacity. One independent
lease spans source validation, paired export and fsynced exclusive receipt publication.
Source transactions acquire paired RESERVED locks and roll back without advancing
generation or performing trader startup recovery. Source failure/rebinding is rejected.

Each admitted UUID directory is retained after interruption. Missing receipts remain
INCOMPLETE, consume capacity and are never automatically promoted/replayed/deleted.
A later capture uses a different ID and current evidence. Default capacity is 30
(maximum 90); free-space admission requires 128 MiB plus 8 KiB. Space is checked,
not reserved against concurrent writers. Reporting needs no surviving source and
checks private/bounded receipts, UUID bindings, whole-artifact digest/size and
manifest equality. It provides local integrity evidence, not an independent off-host
pin, latest-source witness, invoice record or usable execution authority.

An optional independent systemd oneshot/timer schedules local capture at 01:15 UTC,
with persistent missed-activation handling, no network or credential access, no
process restart loop and explicit startup/stop bounds. Both reviewed units pass the
native systemd parser with only executable/UID/GID mapped locally. They are not
installed on DigitalOcean, do not alter deployed cron, and do not upload archives.

Verification: **1,026 full-suite tests passed in 298.92s with warnings treated as errors**.
Scoped lint/format, compilation, pip check and whitespace checks passed. The installed wheel passed **91 checkpoint,
catalog and archive cases in 30.58s with warnings treated as errors**, including
34 new catalog cases. Installed `-I` native entry points captured evidence, reported
and quarantined after deleting the source pair, and survived actual SIGKILL during
paired copy: incomplete admission remained, locks released, and a later capture used
a distinct ID. Unknown orders/HALT and unknown model-cost evidence remained auditable;
quarantine could not construct execution authority. Tampered receipt manifests,
digests, private-file boundaries, duplicate capture, capacity and space failures were
covered. Wheel SHA-256:
`ea971c91f0f6ff07bf3cec2fe3c3a8ac7f027b3f92d77591c1cf03e1e59e9108`.
No broker/model calls, native target-host installation or archive provisioning occurred.

Next gates remain target-host isolated population/namespace/lifecycle validation,
authenticated full-universe latency and bounded model-process evidence, independent
archive retention/retrieval and a host-loss recovery drill. The running virtual-v1
experiment keeps its frozen deployed release/configuration and continues collecting.
LIVE remains disabled. Rough engineering estimate stays about 89%, excluding LIVE
readiness and demonstrated profitability.

## Operator API evidence — 2026-10-07 regular session

The operator supplied a 13-page PDF of the authenticated
`/api/synthetic/virtual-v1` response, printed October 7 at 21:26 America/New_York.
Source PDF SHA-256: `f6a38f2376e2d346e78f80882414dd2c4779d2ddbc95fd39c2bc5641445e3779`.
This is user-provided printed API evidence, not a direct credentialed fetch or a
complete journal/packet archive. Numeric fields/fill records were extracted and the
final page visually checked; wrapped prose is not preserved as canonical JSON.

The response is OK, revision 26, with 25 displayed cycle records (IDs 2–26) from
13:45:31.848366 to 19:45:11.125865 UTC, October 7. Cycle 1 is outside this default
25-row window. It records 24 attempted model calls in that window, no agent errors,
and a last rules-only HOLD with no model attempt. The visible decisions comprise
23 HOLDs, one OPEN_LONG and one CLOSE. Release identity remains
`de5dd1c7bd3a2d3b85a2d6bb7f624e0d3a3f9245`; frozen virtual-v1 policy, $10 capital,
5 bps slippage, zero per-fill fee, prompt hash and configured token rates remain
as recorded at initialization. The quarter-hour timestamps support regular-session
operation, but service heartbeat and exact scheduler-claim completion need the
separate authenticated `/api/shadow?limit=100` evidence.

One synthetic XLV round trip completed. Cycle 6 requested entry; cycle 7 bought
0.01473545 shares for $2.499202460742 at 15:00:15.856226 UTC. Cycle 24 requested
close; cycle 25 sold the same quantity for $2.48683669213375 at 19:30:22.468451 UTC.
Both fills reference their earlier source cycle, consistent with the frozen
next-quote policy. These are simulated executions, never real broker fills.
Latest state at 19:45 UTC has no position or pending intent, and reports fresh
position/benchmark valuations, zero unknown model calls and zero unaccounted attempts.

Price P&L is -$0.01236576860825. Cumulative estimated model cost is $0.0142248;
net-after-model equity is $9.97340943139175, a -0.2659056860825% return. Matching
SPY liquidation equity is $10.0046793323244, +0.046793323244%; reported net excess
is -0.3126990093265 percentage points. This measures the frozen synthetic execution
and configured model-cost assumptions, without hosting/setup costs, taxes, dividends
or splits. It is the first provided operational session sample, not profitability
or useful-signal proof. Model rates remain configured estimates, not verified invoices.

This closes the prior absence of provided regular-session synthetic decisions,
usage and fill evidence for the deployed release. It does not validate the newer
isolated execution engine, broker writes, full packet/input provenance, every
scheduler slot, fresh post-close worker health, off-host backups or host recovery.
A raw `/api/synthetic/virtual-v1?limit=100` response plus `/api/shadow?limit=100`
would retain the earlier row and worker/claim evidence without PDF wrapping.

## Target-host evidence — 2026-10-06 UTC

Evidence below comes from the operator's pasted deployment output, not remote
execution by this workspace. Deployed application release:
`de5dd1c7bd3a2d3b85a2d6bb7f624e0d3a3f9245`.

- Fresh Ubuntu 24.04.5 amd64 server; application cloned from the Slice 2 branch.
  Docker build completed on `python:3.12.15-slim-bookworm`, including package
  installation and `pip check`.
- Resolved Python base digest:
  `sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`.
  Built application image index digest:
  `sha256:734ec19a3fba9238ed5faeb3b4e988dc2624abd066da95b10b26ffac292ade45`.
- OpenAI authentication accepted for `gpt-6-luna`; exact structured-output smoke
  returned `structured_output: true`, action HOLD, without touching Robinhood.
  This smoke is not the worker's isolated scheduled model process.
- Fresh Robinhood OAuth authorization and safe probe passed: reconciliation true,
  no positions, no working orders, all 20 candidates and mixed regime. No broker
  identifier or private account values are copied into this public document.
- Operator chose a fresh server database, preserving the Mac database separately.
  No bootstrap migration occurred. Only one worker may run across machines.
- `virtual-v1` initialized with $10 virtual capital, 5 bps per-side slippage,
  zero fixed fee, SPY benchmark and frozen `gpt-6-luna` prices/prompt/risk inputs.
  Prompt version: `v3-session-shadow:virtual-account-v1`.
- Preflight passed. Scheduled one-off and detached service returned MARKET_CLOSED
  with exit 0 and population SYNTHETIC_PAPER. At 20:22:06 UTC, heartbeat status was
  RUNNING; worker and observer were healthy. Observer port remained localhost-only.
- Schedule had no active claim or slots. Experiment revision was 0, with no cycles,
  fills or unaccounted model attempts. An empty cohort has no signal/performance
  evidence. No order placement, cancellation or LIVE path was enabled.
- Mac editable installation and full suite passed: **276 tests in 23.55 seconds**
  on Python 3.14.5, independently of the earlier locked Linux suite.
- Operator's post-reboot output at 20:56:46 UTC showed both containers healthy
  after automatic restart, RUNNING heartbeat and MARKET_CLOSED. The same release,
  experiment ID, frozen configuration and revision-0 empty cohort persisted.
- Host Caddy service reported active after restart. Operator selected DuckDNS plus
  Caddy HTTPS access instead of an SSH tunnel, retaining the observer's localhost
  bind and application authentication. See SHADOW_SERVER.md for the proxy boundary.
  At 20:58 UTC the operator confirmed dashboard login and the website page work.
  This is operator browser evidence; exact HTTP headers, mobile inspection, firewall
  configuration have not been supplied.
- At 21:00:16 UTC, the operator ran the server backup helper successfully:
  `/data/backups/robinhood-20261006T210016Z.db`, status OK, no network calls.
  The helper creates an integrity-checked SQLite snapshot. The same successful
  shell block installed `/etc/cron.d/trade-bot-backup` for 01:15 UTC daily and
  enabled cron, with output in `/var/log/trade-bot-backup.log` (mode 600).
  Installation is verified; a cron-triggered run and off-host copy are not yet observed.

Next: verify off-host backup protection and mobile
dashboard rendering; then observe a regular-session scheduled
model cycle, stored usage/decision/risk evidence and subsequent virtual transitions.
Target-host failure recovery remains unverified. Keep PR #1 draft and main untouched.

## Offline execution foundation — 2026-10-06 UTC

The operator requested execution engineering while SHADOW collects evidence, using
SignalFlow for inspiration and integration. Fresh GitHub refs were recovered before
editing: Trade-Bot `e1e846e3a5c0b28e2e3ccbf7666c472db3654128`, SignalFlow `main`
`f9eaf2c1b5d13dca287ee7138126883065b00395`. Relevant broker capability, reservation,
reconciliation, ledger and partial-fill sources were read at that pinned snapshot.

Implemented `app.execution` with existing decision/packet/governor integration,
current journal account authority, pre-dispatch reapproval, durable intent/attempt
identity, one active reservation, cumulative partial fills, Decimal cash/fees,
original invalidation, daily entries/cooldown, atomic ledger/fill/order updates and
persistent halt/manual recovery. Missing orders never expire an attempted reservation
or authorize replay. Startup latches interrupted attempts as UNKNOWN. Only a built-in
local fixture venue can be attached; PAPER/LIVE-disabled configuration is required.
The journal is separate from all existing PAPER/SHADOW/synthetic tables and refuses
their databases. No Robinhood calls, model calls, broker writes or SignalFlow runtime
imports were added. The server runner, `virtual-v1`, prompt and risk policy are unchanged.

Verification: **40 execution tests passed**; the full suite passed **316 in 10.18s**
on Linux CPython 3.12.14. Coverage includes a real child-process exit after the
committed attempt, concurrent/repeated dispatch, lost acknowledgment, partial and
terminal outcomes, immutable/missing/stale evidence, budget/limit violations,
fees/cash, persistent limits/halt, transactional failure rollback and read-only,
network-free reporting. Changed-code Ruff checks/format checks and dependency
`pip check` passed. A built wheel was installed outside the repository and its
standalone fixture command also passed under optimized Python, saving two simulated
fills, terminal orders and a flat final account. These scripted results are execution
verification, not trading performance or real broker capability evidence.

See [EXECUTION_REHEARSAL.md](EXECUTION_REHEARSAL.md) for the reproducible command,
SignalFlow adaptation and remaining adapter/deadline/operator-control engineering.
Do not rebuild the deployed server for this offline foundation. Its first regular
market-session model cycle and the previously listed host verification gates remain
pending; LIVE remains disabled.

## Offline position-supervision follow-up — 2026-10-06 UTC

Fresh GitHub branch state matched `e8dfa23c8e54f0f5e26012c873e0fc53f965f64b`
before editing. SignalFlow's pinned stop-authority source was read alongside the
current engine and settled synthetic stop/session policy. The fixture engine now
persists original entry management, latches stop/session exits across HOLD/rebound/
restart, marks the owned position and prepares governor-approved protective exits
without a model. Explicit overnight permission preserves the existing policy; it
never disables stop invalidation. Missing/stale/regressing evidence halts execution.
Partial entry remainder must be definitively resolved before an exit; active sells
are reused and known canceled residual shares get a new intent. Entry preparation
and dispatch both enforce the final-15-minute session gate and current invalidation.

Verification: **26 supervision tests passed as part of 342 full-suite tests in
10.57s** on CPython 3.12.14. Tests include early closes, overnight permissions,
legacy lineage recovery, stale/missing/crossed/regressing quotes, stale account
evidence, failed calendar, concurrent preparation, partial fills, expired unattempted
exits, persistence rollback and unchanged original stop. Changed-code Ruff checks,
format checks, dependency integrity and whitespace checks passed. The new wheel
installed outside the repository and passed the optimized-Python fixture command,
with two simulated fills and a flat final account. This is offline fixture
evidence only. No broker adapter, deployment change or authenticated call was added.
Bounded executor deadlines, actual broker contract proof, deployed supervision,
bankroll/account gates and operator recovery/alerts remain future engineering.

## Offline account/dollar-envelope follow-up — 2026-10-06 UTC

Fresh canonical branch state matched `fdd6d5ad80eb9fbc04fd7eb79a5aed1a459367d7`
before editing. Each new offline journal now freezes its fixture account identity,
entry/position dollar ceilings and total/daily loss limits. Current journal/account
truth owns authority. Profits, model account proposals, runtime configuration changes
or manual resume cannot raise these limits. Daily realized net P&L includes all fill
fees, persists across restart and updates once with the atomic fill ledger. Loss
gates block new entries while protective closes remain available. Existing journals
without this envelope remain read-only reportable; execution requires a fresh journal
rather than silently adopting new authority.

PREPARED dispatch now requires a supplied fresh market packet and rechecks the saved
proposal against it. Current stop invalidation, tradability, volatility and account
limits can reject the old approval. Duplicate/crossed/nonfinite/stale/regressing
evidence never authorizes an attempt. Buy risk covers the original maximum executable
limit even if the current ask falls. Observed and governed packets and snapshot/risk
identity are saved; blocked admission/dispatch retains an audit reason. Attempted
orders still cannot replay and do not need a new packet simply to return their status.

Verification: **377 tests passed in 10.80s**, including 35 new limit/dispatch tests.
Changed-code Ruff checks/format checks, `pip check` and whitespace checks passed.
The wheel installed outside the repository and passed optimized-Python rehearsal
and independent account-pin/$2-ceiling/fresh-invalidation checks without network calls.
No server, existing experiment, model prompt, broker API or LIVE path was changed.

Estimated v1 execution-engine completeness: **about 60%**, a rough engineering
estimate of implemented components, not a LIVE-readiness or profitability score.
Remaining work includes bounded executor deadlines, actual broker identity/order/fill
contract proof, real account/capital enablement gates, operator recovery/alerts,
deployed supervision and integrated failure verification. The pending market-session
and host evidence above remains separate.

## Offline bounded executor follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `24069cd6d523a2dd7cbe3f743aa80cce8c888d63`
before editing. Isolated submission/read calls now use only the built-in durable
fake venue, separate from engine and server experiment databases. Acceptance and
complete order/fill/account truth persist independently across process deaths.
The journal binds a venue UUID/account and rejects replacement/transport bypass.
Write-ahead receipts precede launch; the frozen monotonic process deadline is also
capped by the intent's remaining admission lifetime and checked before acceptance.

Timeout, crash, lost/malformed/oversized acknowledgment and cancellation preserve
UNKNOWN/reservation/halt rather than retrying. Cleanup terminates, escalates if needed,
drains and reaps the child even under repeated cancellation or cancellation during
launch. The child receives no broker/model credentials or LIVE settings. Parent-death
checks stop diagnostic fake stalls while already accepted orders remain durable.
Failed complete-history reads halt without fabricating account or terminal evidence.

Verification: **399 tests passed in 31.77s** on Linux CPython 3.12.14, including
**22 new process/venue tests in 20.95s**. Tests use real children, native timeout/
SIGTERM-ignore/crash faults, cancellation races, an abrupt parent `os._exit(95)` and
reaped orphan child, bounded short admission lease, immutable venue binding, safe
database isolation and a saved end-to-end partial-entry/protective-exit scenario.
The Linux parent-death test owns/reaps its orphan using a temporary test-process
subreaper flag; this does not change a host service or the deployed server.
Ruff checks/format checks, dependency and whitespace checks passed. The wheel
installed outside the repo and its optimized-Python `deadline-run` saved a timeout,
two simulated fills, terminal orders and a flat final account; read-only reporting
passed. No broker/model calls, credential loading or server changes occurred.

Estimated v1 execution-engine completeness: **about 70%**, a rough component estimate.
Remaining: actual broker identity/order/fill/deadline contract verification, real-account
enablement/capital gates, authenticated operator recovery and alerts, deployed
supervision and integrated failure testing. This is not LIVE-readiness or profitability
evidence; the previously listed host and market-session gates still apply.

## Offline authenticated recovery follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `9b95db444bfa8bd01b481118be4c57469281ef03`
before editing. The isolated execution journal now supports explicit operator
capability enrollment, signed command envelopes and durable replay receipts.
HMAC commands bind an immutable journal UUID, actor label, reason, action/target,
reviewed audit revision and a maximum-five-minute lifetime. The key and signature
are not persisted in audit records or supplied to the trader/model processes.
Shared-key capability authentication is not per-person login; trusted local
Python/filesystem owners retain authority. No HTTP mutation route was added.

HALT reduces authority even if review/config changed. RESUME, local PREPARED
abandonment and alert acknowledgment require the exact current reviewed revision.
Mutation, event and receipt commit together. Repeats return the original receipt
without reapplying, including after expiry; content reuse under the same ID fails.
Expired/future and risk-rejected requests have durable rejected receipts.
Recovery additionally requires fresh owned-position supervision/quotes, retains
complete account/order reconciliation and cannot release an uncertain attempt or
waive original stops, frozen limits or terminal-evidence requirements.

Critical events and changed blocked/exit-required supervision create persistent
alert rows atomically with their source events. Pagination retains older pending
alerts beyond the report's 100-row page; acknowledgment records operator/time/ID
but never clears a halt, delivers an external message or releases reservations.
Repeated identical supervision is deduplicated. Compatible current journals gain
only additive tables on writable open; read-only prior reports do not migrate or
enroll. Historical events are not backfilled as new alerts.

Verification: **434 tests passed in 32.58s**, including **35 new operator/alert
tests in 0.85s**, on Linux CPython 3.12.14. Coverage includes invalid/tampered/cross-
journal signatures, immutable enrollment, secret/MAC audit exclusion, expiry,
replay/conflicting IDs, concurrent duplicate/stale requests, late fills invalidating
review, receipt/alert storage rollback, uncertain-order recovery restrictions,
fresh position supervision, stop persistence, alert pagination/deduplication,
read-only legacy reports and an exclusive-file offline CLI proof.
Ruff check/format, dependency and whitespace checks passed. The wheel installed
outside the repo and its optimized-Python operator scenario persisted one canceled
fake order, three command receipts, one acknowledged alert and no retry. Read-only
reporting left the private database unchanged. No broker/model calls, credential
loading, server changes or external notification occurred.

Estimated v1 execution-engine completeness: **about 72%**, a rough component estimate.
Remaining: actual broker identity/order/fill/deadline contract proof, real-account
enablement/capital gates, deployed independent supervision, integrated model costs,
secure operator transport/key lifecycle/restore handling, external alert delivery
and host failure testing. LIVE readiness and profitability remain unverified.
The deployed release and earlier host/market-session gates remain unchanged.

## Offline credential lifecycle and restore follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `e029afa3a8b9b77dafccfd1b8be0350c3f04addf`
before editing. Signed ROTATE_KEY/REVOKE_KEY and credential generations now retire
old capabilities and latch dispatch halts. Retired keys cannot be reused, including
through trusted local recovery. Revoked-capability recovery requires a new key and
reason, advances generation and preserves the halt, active reservation and ledger.
Recovery still needs definitive venue evidence and ordinary signed RESUME.
Retired controls cannot read a review or replay old command receipts. Shared key
capability authentication remains local; no per-person login or HTTP control exists.

Explicit restore-fence enrollment creates a private separate authority file. Fenced
writes verify journal UUID, commit generation and complete logical-state digest
under attached-database locks before mutation, then advance both checkpoints in
one transaction. Files use DELETE journal mode and writer connections synchronous
FULL; unsupported modes fail without persistent-mode changes. Missing/replaced
authority, journal-only rollback, a restore before fence enrollment, or same-audit-
revision state changes block writes and cannot silently rebind authority. Reports
remain read-only and show VERIFIED, BLOCKED or UNFENCED. The fence is opt-in for
offline rehearsals; nothing is enrolled on the server.

Verification: **460 tests passed in 32.76s**, with **26 new credential/restore tests
in 1.48s**, on Linux CPython 3.12.14. Tests cover retirement/re-enrollment, stale
review, competing rotations, preservation of uncertainty, retired-generation
re-signing, receipt/authority rollback, private/idempotent provisioning, restores
before/after enrollment, accepted-order retry prevention, missing/foreign files,
unsupported WAL, unchanged read-only reports, concurrent writers, failed fence
initialization and an actual child `os._exit(97)` while both files are uncommitted.
Both files recovered consistently after reopening. This is not a host power-loss
or mid-COMMIT crash test. A saved exclusive-file `recovery-run` proves rotation,
revocation, unknown-order blocking, definitive fake cancellation and rollback
rejection, then restores the exact known-current fixture bytes without changing
authority. No arbitrary database restore/reset utility was introduced.

Ruff check/format, pip check and whitespace checks passed. The built wheel installed
outside the repo; its optimized-Python recovery scenario verified credential
generation 4, two retired keys, four receipts, one canceled fake order, blocked old
journal retry and a VERIFIED current pair. Read-only reports left both private
files unchanged. Wheel SHA-256:
`b343bd90c56ae2aad357051cc5ff2aaca5c761c78affa182882e370f7671bad9`.
No broker/model calls, external notifications, deployment changes or LIVE path.

Estimated v1 execution-engine completeness: **about 74%**, a rough component estimate.
Remaining: actual broker identity/order/fill/deadline contract proof, real-account
enablement/capital gates, deployed independent supervision, model-cost integration,
secure operator transport, external alert delivery, off-host/multi-host checkpoint
protection, verified restoration and host failure testing. Rolling back both local
files together or duplicating the valid pair across machines is not detected by
this local safeguard; full-history digest growth is also unmeasured. LIVE readiness
and profitability remain unverified. Deployed release/experiment remain unchanged.

## Offline model-cost and economics follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `f3ec2445a94d2bfa47abb784604c13b001dd6871`
before editing. Opt-in engine cost enrollment freezes model, configured standard
rates, total/daily budgets and a per-call reservation. A durable receipt commits
before a future model invocation; exact source/packet replay never calls again.
Unknown usage blocks additional calls/entries and suppresses net economics.
Current account/session/quote evidence and no active order are required before
granting a new invocation receipt. This module never invokes an API.

Trusted local usage evidence must carry pinned model, positive input tokens,
nonnegative output tokens and unique request identity. Decimal charges, immutable
decision fingerprint and audit commit atomically. Duplicate settlement is a no-op;
conflicts cannot double-charge or erase uncertainty. All charges above the assumed
per-call bound remain counted, produce an alert and block further calls/entries.
Every new attempt reserves room in total and New York daily budgets. Daily charges
belong to the attempt date, including late settlement; total costs persist.

BUY admission requires matching settled decision and original packet evidence.
Fresh dispatch retains decision/cost authority and reruns cost-aware entry gates.
Total/daily loss floors include known reasoning charges alongside trading equity
or fee-adjusted realized P&L. Brokerage/simulated cash and buying power are not
debited by external model costs. HOLD costs count; deterministic protective CLOSE
still works with uncosted reasoning, subject to normal reconciliation/ownership/
quote/halt rules. Reports expose known/unknown costs and net equity/return only
with complete usage and fresh account/position marks.

Verification: **490 tests passed in 33.46s with warnings treated as errors**,
including **30 new model-cost/economics tests**, on Linux CPython 3.12.14. Coverage
includes receipt/settlement replay, concurrent requests, source/decision/packet
binding, missing/invalid/foreign usage, provider ID conflicts, frozen/runtime-policy
changes, reserved/exhausted budgets, full over-bound charges, daily attribution,
economic loss gates, preserved broker cash, protective exit under unknown costs,
stale/mismatched net marks, rollback/restore fencing and actual child `os._exit(98)`
after receipt commit. Restart retains the potentially charged call and cannot replay.

Ruff check/format, pip check and whitespace checks passed. The installed wheel ran
outside the repo under optimized Python with warnings as errors: two fake fills,
protective exit while a HOLD cost was unknown, $0.00030 final scripted model cost,
exact cash-minus-cost net equity, VERIFIED restore pair and unchanged read-only
files. Wheel SHA-256:
`0c2063a16a01e70a59aab1de8117f2fbf393dd443e9277dd804754cbba2f0d09`.
No broker/model calls, actual billing proof, server changes or LIVE capability.
The saved `economics-run` exclusively creates a new fixture file.

Estimated v1 execution-engine completeness: **about 76%**, a rough component estimate.
Remaining: actual broker/order/fill/deadline verification, real-account/capital
enablement, deployed independent supervision and operator transport, external
alerts, off-host/multi-host restore protection and host failure testing. Actual API
request/token ceilings, invoice/discount treatment and verified noncharge recovery
must still support this cost ledger before integration; its rates are configured
assumptions, not current-price verification. Isolated economics exclude SPY pairing,
corporate actions, taxes, hosting/setup charges and real invoice adjustments. The
server's paired synthetic SPY experiment remains separate and unchanged. LIVE
readiness and profitability remain unverified.

## Bounded model judgment follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `3f377a146c1e009dfecc72cab8e329473002f09f`
before editing. The optional fixture-engine `JudgmentCoordinator` now connects
frozen cost authority to a private OpenAI Responses child. Existing Trader
instructions, strict `AgentOutputSchema(TradeDecision)` and runtime validation
remain the judgment contract; the deployed Agents SDK/SHADOW path is unchanged.

Enrollment before model receipts freezes prompt/schema/cost hashes and request
bounds. Defaults: 16,000 input tokens, 1,024 output tokens, 30-second process and
20-second request deadlines. Their maximum configured token cost must fit the
existing per-call reservation. Reconciled journal cash/position replaces proposed
account values in the model packet. A revision check atomically binds that review
to the durable pre-model receipt. Receipt commit/storage failure and replay cannot
launch another child or silently charge zero.

The fixed child gets only an explicit model key plus basic locale/path environment,
with a pinned OpenAI API origin, no SDK retries, suppressed logs and no tracing.
It counts the exact instruction/input/tools/schema payload, rejects bad/excessive
counts and generates at most once with bounded output, empty tools, no tool choice,
disabled truncation, no streaming/background and `store=false`. A watchdog exits on
parent death/deadline; parent cleanup kills/drains/reaps even after repeated cancel.

Provider response identity/usage is captured before structured decision parsing.
Incomplete/refused/invalid output becomes HOLD with full valid reported usage cost;
failed requests or absent usage stay unknown. Exact model, usage bounds and counted
versus returned input are checked. Violations preserve reported evidence, count all
valid pinned-rate charges and persist a new-call/entry block. Foreign model usage
cannot inherit pinned pricing. Settlement, decision audit and violation state commit
together; enrolled BUY authority requires the matching bounded judgment record.
No model judgment prepares or dispatches an order. Protective closes retain their
existing deterministic path under cost/evidence entry gates.

Verification: **526 tests passed in 37.82s with warnings treated as errors**, with
**36 new bounded-judgment tests**. Native pinned SDK calls use local HTTP mock
transport to prove count/generation payload equality, empty tools/strict schema,
output cap, missing usage, invalid/incomplete/refused/unexpected output and no
retry after quota failure. Tests cover source restart, frozen/runtime policy,
review races, cash reconstruction, receipt/audit rollback, direct-settlement entry
rejection, full usage under violations, private child environment, real deadlines,
crash/oversized protocol, repeated cancellation and a real parent `os._exit(94)`.
The actual worker watchdog exits its orphan with code 99; the cost receipt remains
unknown and cannot replay after restart, with the authority pair still VERIFIED.

Ruff check/format, pip check and whitespace checks passed. The installed wheel ran
outside the repo with optimized Python and warnings as errors. Both real subprocesses
loaded installed package code and the pinned SDK used mock transport, producing a
valid entry and a billed incomplete HOLD, two fake fills, flat final state, exact
$0.00030 cost/net conservation, private files, a VERIFIED authority pair and
unchanged read-only report bytes. The first proof's alert-count assertion was adjusted
to account for the existing protective-exit alert alongside the model HOLD alert;
the corrected proof completed. Wheel SHA-256:
`013026d933f9f3dc5886e83fdbb5cd547d09837a5842592e40813a5c3d4f76c8`.
No authenticated API or broker call, server update or LIVE capability was added.

Estimated v1 execution-engine completeness: **about 78%**, a rough component estimate.
Remaining: authenticated token-count/generation/model-identity verification before
adopting this optional interface; invoice/discount treatment and verified noncharge
recovery; actual broker/order/fill/deadline contracts and account/capital enablement;
deployed independent supervision, secure operator transport, external alerts and
off-host/multi-host restore protection with host-failure proof. First scheduled
authenticated market-session evidence from the deployed cohort remains unobserved.
The existing server and paired synthetic SPY experiment remain unchanged. This
mocked execution proof establishes neither live readiness nor profitable signal.

## Independent fixture supervisor follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `dcf1b5fd2771bb5b81c56aa6eae06c9fe1d1a9ef`
before this slice; PR #1 remains draft and main is unchanged. A new opt-in
`ExecutionSupervisor` runs account reconciliation and stop/session supervision
without awaiting model reasoning. It accepts only the built-in execution engine,
durable fake venue and private manually published `DurableQuoteFeed`.

Enrollment before orders freezes venue/feed/account identity, paths, universe and
poll/tick/freshness limits. Defaults are 5/10/20 seconds respectively; poll plus
whole-tick deadline must fit the lease, which cannot exceed quote freshness. A
single-host lifetime file lock prevents duplicate owner claims. Completed OK ticks
alone renew entry health. After enrollment, BUY preparation/dispatch and new model
receipts require that fresh RUNNING result. STOPPING revokes health before child
cleanup completes; failed/interrupted/stopped-with-risk runners retain a dispatch halt.
Interrupted recovery needs explicit reasoned review; reads never auto-resume.

The loop reads complete fixture history in the existing bounded private child,
validates quote feed identity/sequence/freshness, supervises owned risk, and may
prepare/reuse only a governed protective SELL. It never creates a BUY or cancellation.
Original invalidation, session policy, one active reservation and partial-fill
ownership stay in the existing engine. Read fencing captures account/order/fill
state before awaiting and atomically discards superseded results before applying
them, without renewing health. Unchanged-epoch mismatches still halt. Quote/account
freshness is checked again at completion. Blocked result alerts deduplicate.

Verification: **557 tests passed in 51.80s with warnings treated as errors**, including
**31 new supervisor tests**. They cover protective fake SELL while a real model child
is blocked with an unknown receipt; idempotent polls; stop/session exits; unresolved
partial BUY and definitively canceled partial SELL; stale/future/missing/oversized/
foreign/regressed quote evidence; freshness gates before preparation, dispatch and
model receipt; shutdown admission while cleanup is pending; immutable/runtime
policy; duplicate owner; read/tick deadlines; health-commit rollback; repeated
cancellation; and older read completion after new intent/fill evidence. A real
parent `os._exit(93)` leaves an interrupted owner and its actual read child exits
through the parent-death watchdog. Restart cannot claim healthy entry authority
until fresh reconciliation and explicit review; the authority pair stays VERIFIED.

Changed-code Ruff checks/format, pip check and whitespace checks passed. The wheel
installed outside the checkout passed an optimized-Python, warnings-as-errors proof.
The installed supervisor completed a governed fake SELL and reconciled flat with
two fake fills while the installed model child was blocked in mocked SDK generation.
The cancelled model attempt stayed unknown, prior known cost remained $0.00015 and
net economics stayed unavailable. Children were reaped; all journal/authority/venue/
feed files remained private, the authority pair was VERIFIED, and read-only reporting
did not change bytes. Wheel SHA-256:
`c7bb42c651abdd0d57c3da689a4595d279fdb0ff0d06b5508c755b80d57d94c3`.

Estimated v1 execution-engine completeness: **about 80%**, a rough component estimate.
This loop is local fixture library infrastructure, not a deployed daemon, broker
stop order or hard real-time guarantee. Synchronous local storage/calendar work can
still stall its parent event loop. Actual broker contracts, authenticated model
validation/adoption, deployed supervision/operator transport/alerts, off-host
protection and host-failure proof remain. The server release, SHADOW experiment and
first scheduled regular-session evidence gate are unchanged. No authenticated
model/broker call, server update or LIVE capability was introduced.

## Isolated operator transport follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `97aa22b7718b1c65f028777d90d6e38019cedd9d`
before editing. PR #1 remains draft and main is unchanged. The opt-in fixture
engine now has a separate native-TLS control application exposing only authenticated
bounded review and the six existing signed operator commands. Startup requires
explicit prior key enrollment and a VERIFIED journal/authority pair; it never
creates an engine, enrolls credentials, migrates state or resumes execution.

The read token and signing key are separate 32-byte hex secrets in private,
owner-only regular files. Files/capability retirement are rechecked per request.
The API pins an exact HTTPS origin, rejects forwarding/ambiguous headers and
cross-origin requests, provides no cookie/CORS or order/LIVE/enrollment/recovery
routes, and disables documentation. Native ASGI TLS with proxy-header handling
disabled is required; this is not wired into the current observer's Caddy route.

Review binding/revision/evidence share one read-only snapshot and omit prompts,
full event/order/fill history and signing material. Responses are capped at 64 KiB.
Commands require the read token and exact HMAC envelope. Existing expiry, reviewed
revision, generation, reservation ownership, fresh recovery evidence and atomic
action/audit/receipt rules are preserved. Replays never reapply an action or turn
a rejection into approval. Signed rotation/revocation retain the halt, retired
keys cannot obtain replay receipts, and trusted local key provisioning/recovery
remains required.

Known-length/chunked request bodies are capped at 16 KiB, with a default five-second
body deadline and four admitted requests (maximum eight). Malformed/duplicate/
nonfinite/extra JSON is rejected without echoing validation details. All responses
carry privacy/no-store headers. A cancellation test caught early admission release
in the generic HTTP middleware wrapper; the final pure ASGI boundary retains the
slot until cancelled local thread work drains, even after repeated cancellation.
A lost response does not prove nonapplication: inspect/replay the same signed
command while its capability remains active. A body timeout cannot abort a
committing SQLite transaction or establish a hard real-time storage guarantee.

Verification: **614 tests passed in 54.07s with warnings treated as errors**, including
**57 new control-transport tests**. Tests cover read-only bytes; startup provisioning,
restore and private-file requirements; auth/TLS/origin/header rejection; parser,
body and admission bounds; cancellation/committed receipt retention; durable replay;
stale reviews; unknown/attempted-order recovery rejection; unattempted abandonment;
alert acknowledgment without resume; fresh owned-position supervision; rotation,
revocation and read-token changes; runtime engine changes; journal-only rollback;
and oversized review rejection. Changed-code Ruff check/format, pip check and
whitespace checks passed.

The wheel installed outside the checkout passed a native Uvicorn HTTPS proof under
optimized Python and warnings as errors. The client validated the generated
loopback certificate, anonymous and forwarded-header requests were denied, signed
halt/resume and exact replay succeeded, and a client closed its connection after a
third command committed but before receiving the reply. Replaying that same command
returned its original receipt without reapplying it. Three durable command receipts,
private credentials/state, VERIFIED restore authority, unchanged read-only bytes,
zero broker/model calls and a reaped server were verified. The proof harness was
corrected to treat HTTP header names case-insensitively before its completed run.
Wheel SHA-256:
`06993ae79c130b449c4d9d99dec138035ce3e2c8f29b0f47062d02104fe50fbf`.

Estimated v1 execution-engine completeness: **about 82%**, a rough component estimate.
This proves the isolated fixture transport, not actual-host TLS/certificate lifecycle,
key provisioning, deployed recovery, user identity or broker authority. Actual broker
contracts, authenticated model validation/adoption, deployed supervision and alerts,
off-host restoration and host-failure proof remain. The deployed release and SHADOW
cohort are unchanged; first scheduled regular-session evidence remains unobserved
in this workspace. No LIVE capability, actual server update or outbound broker/model
call was introduced.

## Durable alert delivery follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `7d2e41c2b246e94dbf09ed06083eac8fc6a063a7`
before editing. PR #1 remains draft; main and the deployed worker are unchanged.
The opt-in fixture engine now freezes an HTTPS sink/limits/private token path and
requires VERIFIED restore authority before delivery enrollment. It sends minimal
alert identities rather than account, order, money, prompt or full event payloads.

Attempts are committed before the fixed isolated child runs. An exact strict sink
receipt is required; redirects, malformed/foreign/oversized/compressed receipts,
TLS/credential failures and timeouts cannot mark delivery complete. Native TLS
verifies hostname/trust; optional CA file/hash and private token are checked per
request. Broker/model secrets, proxies and engine database handles are excluded.
A nonblocking single-host lifetime lock spans awaits and child cleanup; a watchdog
bounds orphan work after parent death. Idle polls are read-only.

Lost responses/restart/cancellation retain the identical alert ID, payload and hash.
Default retry delays are 60 then 120 seconds, with at most three attempts per batch.
Exhausted alerts stop automatic retries. Trusted-local reasoned rearm audits a new
bounded batch while keeping cumulative attempts and identity; it neither resumes
trading nor acknowledges an alert. There is no HTTP rearm route. Other due alerts
are not starved by a waiting or exhausted earlier alert.

Once enrolled, overdue (default 120 seconds), future/invalid-clock or exhausted
undelivered alerts block new entries and model-call receipts. HOLD remains first-class;
governed protective SELLs retain their existing checks. Delivery confirmation and
operator acknowledgment remain independent, and neither clears a dispatch halt.
Journal and authenticated operator review expose delivery backlog health. The sink
must durably deduplicate IDs before returning a receipt; remote receipt acceptance
is not evidence of human notification or resolution.

Verification: **673 tests passed in 91.39s with warnings treated as errors**, including
**59 new delivery tests**. Changed-code Ruff check/format, pip check and whitespace
checks passed. Related tests also corrected fixture ordering so model evidence did
not mask the independent BUY gate, and verified specific restore rollback diagnostics.
Tests cover actual loopback verified-TLS child requests, strict receipts, lost replies,
retry caps/backoff, private credentials, trust changes, leases, duplicate owners,
repeated cancellation, actual parent crash/watchdog exit/reaping, storage failures,
restart, idle read-only bytes, audited outage rearm, no starvation, entry/model gates
and governed protective exits.

The installed wheel outside the checkout passed the native HTTPS sink/journal restart
proof under optimized Python and warnings as errors. The first request was durably
accepted by the local sink but lost its response. After sink and engine restart, the
same ID/payload/hash replay returned one durable unique receipt for two requests.
Both children were reaped; restore status remained VERIFIED, private files and
read-only byte checks passed, halt and acknowledgment state remained unchanged,
and there were zero broker/model calls. Wheel SHA-256:
`2c848ea63c78f11daaa419bf21102e26c71c3cdcd2370a04b2af7625df5bd84f`.

Estimated v1 execution-engine completeness: **about 84%**, a rough component estimate.
This verifies transport against a local contract sink, not deployed external alerts
or human delivery. Actual sink/notification provisioning, server integration and
credential lifecycle, off-host restoration/host-failure proof, actual broker
contracts and authenticated bounded-model adoption remain. Synchronous storage and
whole-history restore hashing are not hard real-time guarantees; paired rollback
and multi-host coordination remain outside local fencing. The deployed release,
SHADOW cohort and unobserved first scheduled regular-session evidence gate are
unchanged. No LIVE, broker write path or external recipient notification was added.

## Paired evidence checkpoint and archive follow-up — 2026-10-07 UTC

Fresh canonical branch state matched `a4a154ca77d8f50c0a7c60a4f8781755646add8d`
before editing. PR #1 remains draft, main is unchanged and the deployed SHADOW
worker/backup cron remain on their existing release. This adds explicit fixture
execution evidence export, inspection, archive transfer and quarantine staging;
it does not update the deployed Robinhood database, secrets or services.

Export requires a compatible private journal and VERIFIED authority pair. It holds
both SQLite RESERVED locks and uses separate read connections for the two backup
copies, blocking source writers until both captures finish. It then rolls back the
lock transaction without changing source bytes or authority generation. Copies
pass integrity/logical authority verification. A fixed uncompressed envelope has
no arbitrary paths, caps the artifact at 64 MiB and the manifest at 4 KiB, binds
member hashes/sizes and records original authority identity/generation/state hash.
The private file is fsynced and published exclusively without overwriting targets.
Signing/API/OAuth credential files are not included; journal audit data remains
private and the envelope itself is not encrypted at rest.

An independent retained full-file SHA-256 pin is mandatory before inspection,
retrieval or staging. Wrong/truncated/trailing/duplicate/misbound/corrupt evidence
and complete older-pair substitution against a newer pin fail before publication.
A user-selected old pin still represents historical evidence; this does not create
an online latest-generation witness or cure paired rollback.

Explicit one-request PUT/GET archive operations use a separate exact HTTPS origin,
a dedicated private token, verified native TLS, optional bound CA and a fixed
isolated child. No redirects, proxy discovery, SDK retries, engine handles or
broker/model credentials are provided. Bounded pipes, a maximum-30-second process
deadline, cancellation TERM/KILL/drain/reap and parent-death watchdog retain the
existing capability boundary. A private receipt lock and fsynced IN_FLIGHT record
precede upload. Only an exact strict retention receipt becomes REMOTE_ACCEPTED;
lost replies/errors leave UNKNOWN and cancellation/crash leaves IN_FLIGHT. Same-ID
retry is explicit and destination-bound; attempts accumulate and no upload is
automatically repeated. A saved receipt records historical acceptance; retrieval
separately validates the stored bytes and publishes no failed/older download.

Recovery creates only a new private evidence directory with differently named
journal/authority files and a final verification marker. Original unresolved
orders, reservations, fills, costs, model receipts, halt and credential generations
are retained. No broker truth, terminal outcome, cost resolution or fresh risk
approval is invented. There is no normal journal authority sidecar; engine opening
fails before mutation. The tool cannot initialize, migrate, re-enroll, release,
resume or replay execution. A privileged filesystem owner remains outside this
local boundary.

Verification: **730 tests passed in 117.54s with warnings treated as errors**, including
**57 new checkpoint/archive tests**. Changed-code Ruff check/format, pip check and
whitespace checks passed. Tests cover private/bounded inputs, source-byte preservation,
concurrent source writes blocked across both copies, authority/pin/format/integrity
rejection, source-loss evidence recovery, original unknown model/order state, strict
TLS receipts, explicit retry, no retargeting, corrupt/older retrieval, copy/deadline/
receipt storage failures, repeated cancellation, actual parent death/watchdog exit
and reaping, and execution denial. Fixture registration was corrected before the
completed focused/full runs; the final source and transport checks passed.

The installed wheel outside the checkout passed under optimized Python and warnings
as errors with a separate durable native-TLS archive process. The first upload was
stored but its reply was lost. After archive restart, explicit same-ID/bytes retry
returned one durable object for two upload attempts. All original source journal,
authority and local bundle files were then deleted in the fixture. Download matched
the retained SHA-256; quarantine retained the dispatch halt and one active UNKNOWN
order, and ordinary engine opening was denied without changing evidence bytes.
Private-file checks passed and all three transfer children plus both archive server
instances were reaped. There were zero broker/model calls. Wheel SHA-256:
`0657480b6c7d50420e6708d54e8ad944c0852520bd71ce1c50d9785ee766758b`.

Estimated v1 execution-engine completeness: **about 86%**, a rough component estimate.
This proves simulated source loss and the archive client contract, not actual
cross-host retention, deployed backups, power-loss behavior or active-state recovery.
A real independent archive endpoint/pin custody, retention/encryption/credential
lifecycle, latest-generation witness and authenticated recovery still need proof.
Export can delay source writes and local storage/hash work is not hard real-time.
Actual broker contracts, authenticated bounded-model validation/adoption and deployed
supervision/control/notifications remain. The existing SHADOW cohort and unobserved
first scheduled regular-session evidence gate are unchanged. No LIVE capability,
broker mutation, external recipient notification or server update was introduced.

## Fixture PAPER runtime follow-up — 2026-10-07 UTC

The new opt-in PaperRuntime connects the exact durable fixture engine, venue, quote
feed, independent supervisor and optional bounded judgment coordinator. Default is
an explicit stub HOLD. This is isolated from the deployed SHADOW worker, Robinhood
account and frozen `virtual-v1` population. Operations: [PAPER_RUNTIME.md](PAPER_RUNTIME.md).

Enrollment requires VERIFIED paired authority, precedes orders/model attempts and
freezes source identities/paths, engine/supervisor/model policies, runtime limits and
current-slot XNYS cadence. A private single-host lease spans the whole service and
all child cleanup; the CLI takes it before writable startup recovery. Initialization
is exclusive, with private separate fixture files, and supplies PAPER/LIVE-disabled
settings explicitly. There is no automatic enrollment/rebind/reset on restart.

The independent supervisor, runtime heartbeat and scheduled cycle task run together.
Cycle admission requires the supervisor's exact freshly observed quote sequence/hash
and reconciled account truth. A durable current-slot claim plus governed packet
precedes any model call. One attempt per 15-minute regular-session slot; no missed-slot
backfill or interrupted replay. Known model cost remains counted when late judgment
crosses a slot and cannot prepare/dispatch. HOLD, risk rejection and fake execution
retain their decisions/results and existing detailed risk/usage/dispatch evidence.

Entry health is revoked during shutdown and after stopped/stale/failed ownership;
new model receipts and BUY admission/dispatch require it. Protective SELL retains
its existing checks and runs while model reasoning waits. Interrupted cycles persist,
halt and block later slots without an automatic resolution command. Failure stops
all components. Repeated cancellation drains fixed children before lease release,
then finishes bounded supervision; STOPPING ticks cannot renew supervisor authority.

Integration testing found a read/submission race: a supervisor read during SUBMITTING
could falsely interpret pre-acceptance absence as a missing attempted order. Fenced
supervisor reads now defer until the bounded attempt settles, renewing neither account
evidence nor heartbeat. UNKNOWN/missing orders still run the normal fail-closed checks.
No attempted order is replayed or reservation released by this deferral.

Verification: **757 tests passed in 126.65s with warnings treated as errors**, including
**27 new runtime cases**. Coverage includes scheduled HOLD/restart ownership,
duplicate-run admission before writes, known/unknown model usage, risk rejection,
slot crossing, service failure, stale/stopped entry/model gates, interruption/no replay,
protected cleanup during repeated cancellation, private key/lease files, immutable
policy, explicit paired authority, bounded publication and read-only CLI reports.
Related supervisor/process cases passed; changed-code Ruff/format, pip check and
whitespace checks passed.

The wheel installed outside the checkout passed optimized-Python/Werror proof using
real fixture/model subprocesses and a mocked native SDK transport, with no external
calls. The runtime scheduled a governed entry, reconciled a scripted fill and began
its second scheduled judgment. While the model child remained blocked, independent
supervision dispatched a governed fake SELL and reconciled flat after the second
scripted fill. Shutdown reaped all children, preserved one interrupted cycle and an
unknown model receipt, kept the halt and withheld net economics. Known cost was
`0.00015`; the authority pair remained VERIFIED and reporting changed no store bytes.
A separate installed native CLI process, with an explicitly closed fixture calendar,
rejected a duplicate start, handled real SIGTERM with exit 0 and persisted STOPPED
without any cycles or network calls. Wheel SHA-256:
`423bfbeb7e5155af03acf1fde92e645c2507154c47d13ee7c5ec20e47e5b8f91`.

Estimated v1 execution-engine completeness: **about 87%**, a rough component estimate.
This connects fixture scheduling/supervision/judgment/execution; it is not production
market-data collection, automatic fake fills, an authenticated provider run or trading
signal evidence. Operator/alert/archive service provisioning, real data integration,
authenticated bounded-model validation/adoption, host failure/recovery and actual
broker capability contracts remain. The deployed worker stays at its recorded release;
no server update, real broker write, LIVE capability or experiment policy change occurred.

## Signed PAPER interruption recovery follow-up — 2026-10-07 UTC

RESOLVE_CYCLE extends the existing operator capability/control transport with a signed
exact cycle_slot target. Fresh revision, journal/generation/actor/reason/expiry/MAC
checks and atomic durable command receipts remain. The six original action envelopes
retain their canonical signatures and existing receipt fingerprints. No endpoint,
model tool, broker write adapter or automatic recovery path was added.

Resolution requires VERIFIED authority, a halted STOPPED/FAILED runtime and its free
lifetime lease through commit. Active-owner cleanup cannot race resolution. Only a
completed INTERRUPTED claim can be resolved; remaining CLAIMED rows first need normal
startup review. Fresh complete account reconciliation, no issues/active reservations
and fresh owned-position supervision are mandatory. Unknown model costs/violations
block it. Linked model evidence must match frozen policy, original packet, provider
identity/count/usage/decision/audit/token limits and pinned-rate cost. Any linked order
must already be terminal, with fresh matching terminal history after an actual fake
attempt. Unattempted PREPARED orders require the existing explicit abandonment first.

An immutable overlay saves the original-cycle hash, reviewed snapshot/ledger/model/
order evidence and signed command identity. The original cycle remains INTERRUPTED;
model usage, orders/fills, positions, alert acknowledgments, limits and dispatch halt
remain. Only a hash-matched resolved interruption ceases blocking future slots. The
original slot stays attempted forever, and other unresolved claims still block.
A separate reviewed RESUME retains its risk checks and fresh service/supervisor gates.
There is no declaration that an unknown model call was free and no automatic replay.

Verification: **809 tests passed in 123.91s with warnings treated as errors**, including
**52 new recovery cases**. These cover receipt replay across restart/expiry,
concurrent commands, exact target/signature/revision and six-action compatibility,
runtime lease/status/clock guards, fresh account/owned-position evidence, unknown
cost blocking, original packet/usage/decision/count/policy bindings, terminal order
reconciliation, immutable claim/halt/fill/cost preservation, storage/event/receipt/
authority rollback, changed resolution lineage, read-only bounded review, signed
HTTP transport and later-slot continuation only after separate resume. Changed-code
Ruff/format, pip check and whitespace checks passed.

The wheel installed outside the checkout passed optimized-Python/Werror proof via
real native verified loopback HTTPS. A signed resolution applied and its repeated
command returned the original receipt. Review confirmed the retained halt before a
separate signed RESUME. After the API process stopped and was reaped, the installed
runtime rejected the original slot, attempted one later scheduled stub HOLD and
stopped cleanly. Original interrupted evidence was unchanged, the resolution stayed
singular, read-only store bytes were unchanged and the authority pair remained
VERIFIED. Server and all bounded read children were reaped; zero broker/model calls
occurred. Wheel SHA-256:
`e1d929df12ae9b175104585a7638c865a73a52f43d564c5ee77d0c3820b83d30`.

Estimated v1 execution-engine completeness: **about 88%**, a rough component estimate.
This proves reviewed recovery of known fixture evidence, not active-order release,
unknown/no-charge cost recovery, authenticated provider semantics or deployed controls.
Actual read-data integration, bounded-provider validation/adoption, external control/
alert/archive provisioning, host failure/recovery and broker capability proof remain.
The deployed SHADOW release/cohort, main and LIVE state are unchanged. No broker
placement, cancellation, real-account mutation or server update was performed.

## Robinhood quote-component freshness follow-up — 2026-10-07 UTC

The read adapter previously assigned the newest bid/ask/trade timestamp to the
whole quote. A current trade could therefore hide an old executable bid or ask.
It now uses the oldest timestamp of the bid, ask and the exact selected last-trade
price. Unused older trade prices cannot age a newer selected trade, and an unpriced
update cannot refresh it. All market timestamps must be timezone-aware. Missing or
malformed required timestamps fail the collection closed; any required component
in the future is rejected individually before the oldest timestamp is selected.

An injectable collection clock checks future components at completion, allowing
honest updates received after request start. A naive or regressing collection clock
fails closed. Existing governor age limits still own staleness: the adapter retains
old evidence rather than replacing its clock, allowing audited STALE_QUOTE rejection
for both entries and closes. This conservative single-clock contract can reject a
current spread when its selected trade is old; it does not infer unseen freshness.

Offline tests cover each component independently, entry/close governor rejection,
missing/malformed/naive/future clocks, selected price/time pairing, timezone offsets,
request/completion timing and collection clock regression. Authenticated adapter
verification and connection into the independent PAPER runtime remain pending.
The full suite passed **837 tests in 125.01 seconds**. The wheel installed outside
the checkout passed **30 adapter cases** with warnings treated as errors, importing
the installed package rather than repository code. Wheel SHA-256:
`4640e69dd21432e892300694c5976553317b4709c0ad3c48c4b5cfd52823eb04`.
Scoped fatal-error/import lint, formatting, pip check and whitespace checks passed.
No broker/model calls, deployment, experiment migration or LIVE capability was added.
The deployed worker stays on its recorded release; this is not a rebuild instruction.
Engine completeness remains about 88%, excluding LIVE readiness and profitability.

## Source-bound PAPER market-read bridge follow-up — 2026-10-07 UTC

New isolated PAPER populations may explicitly opt into a Robinhood market source
through init's private `--market-oauth-file`. Enrollment precedes supervisor/runtime
policy freeze; existing manual feeds are neither adopted nor migrated. Source policy
pins endpoint, existing redirect registration, credential path, universe, five-minute
bars/seven-day history and bounded collection/freshness limits. Its hash joins the
supervisor policy; source metadata changes fail closed during publication/reload.
Default manual publication cannot mix packets into a sourced feed. Provenance is
trusted local configuration, not protection against a host owner controlling code/files.

The one-shot collect CLI uses a fixed headless child with only explicit broker OAuth
storage and market request identity. Its gateway allows exactly get_accounts,
get_equity_quotes, get_equity_tradability and get_equity_historicals. It rejects broker
review, portfolio/position/order reads, placement, cancellation and other tools before
the client. It selects exactly one active eligible account solely for tradability;
no account identifier/value is returned to the parent. The child receives no model
key, execution journal/authority or venue handle. Existing OAuth refresh persistence
is bounded private authentication state; authorization walls never launch a browser.

Collection has a default/max 30-second monotonic process deadline, bounded pipes,
parent watchdog and kill/drain/reap cleanup. A private nonblocking per-feed lease
spans awaits and publication, including repeated cancellation cleanup. Failed,
malformed/oversized or timed-out reads publish nothing and leave old samples to expire
under their original clock. The parent checks exact source/feed/request identity,
complete unique universe, aware collection clocks and sane fresh quotes before atomic
publication. Quotes cannot be newer than their collection or borrow freshness.

Packets contain only candidates/regime with zero account values, no positions,
orders, lessons or session metadata. Independent supervision and scheduled judgment
continue to rebuild account authority from the virtual ledger; real prices cannot
authorize real orders or invent simulated fills. This bridge does not add an automatic
fill policy or an autonomous continuous refresh service.

Verification: **900 tests passed in 128.38s with warnings treated as errors**, including
63 new cases. These cover source separation, account privacy, frozen policies,
invalid lineage/universe/time evidence, gateway denials, private OAuth/lock files,
duplicate readers, real child success/failure/timeout/cancellation, repeated-cancellation
lease retention and source reload rejection. Scoped fatal-error/import lint, format,
pip check and whitespace checks passed. The installed wheel outside the checkout
also passed all **63 bridge cases** with warnings treated as errors. Wheel SHA-256:
`910b8b024d8e10fe9510af347ff0b837ea85d4c9c0327d6205c72cf855467f10`.

Separate installed proof exercised the native collector entry point/protocol with
local MCP response fixtures, published one source-bound sample, completed independent
supervision and a current-slot stub HOLD, and stopped both runtime components. Source
account value was zero; the saved governed packet used virtual $10 cash. Collection
changed no execution/authority bytes, reporting changed no store bytes, the pair stayed
VERIFIED and both actual children were reaped. There were zero remote broker/model
calls. This is installed orchestration evidence, not authenticated MCP/provider proof.

Remaining at that checkpoint: authenticated full-universe collection timing/availability, continuous
source refresh and failure composition, bounded model validation/adoption, deployed
operator/alert/archive services, host recovery and actual broker capabilities.
Do not rebuild the deployed image for this separate population. Deployed SHADOW,
virtual-v1, main and LIVE state are unchanged; no real placement/cancellation occurred.
Operations: [PAPER_RUNTIME.md](PAPER_RUNTIME.md).

Estimated v1 execution-engine completeness: **about 89%**, a rough component estimate,
excluding LIVE readiness and profitability.

## Continuous PAPER market composition follow-up — 2026-10-07 UTC

New isolated populations may explicitly add `--continuous-market` alongside the
private market OAuth opt-in before runtime enrollment. Existing fixture and one-shot
populations keep their frozen policy and behavior; no migration or implicit adoption
occurs. The added service requires the exact built-in engine/feed and VERIFIED paired
authority, and freezes identities, universe, source hash, cadence and freshness bounds.

The runtime now owns market collection alongside independent supervision, heartbeat
and scheduled decisions. The market service holds its reader lease for its whole
lifetime, including closed-session polling and bounded child cleanup; one-shot readers
cannot compete. Each read keeps the child isolated from model credentials and venue
handles, with a market-only gateway, 30-second deadline and atomic publication checks.
Default cadence waits five seconds after completion. Full seven-day histories are
currently fetched each time; authenticated 20-symbol timing is not established.

Closed, flat accounts without active reservations idle without OAuth reads or any
market/model/venue child. At cold start or session opening, missing/stale feed warmup
is bounded to the pending source read or recent idle polling grace and only while
flat without reservations. WAITING cannot grant entry health. Owned risk keeps the
existing immediate quote requirements; malformed/future evidence cannot use grace.
Reads continue outside sessions when a position or active reservation remains.

Success commits sample sequence/hash and original oldest-quote/success times under
the execution fence. New BUY preparation/dispatch, model receipts and scheduled
claims require source health as well as independent supervision. Pending refresh
preserves protective SELL checks; HOLD remains auditable. Failure preserves the old
sample, persists only a sanitized exception class, halts and ends all tasks without
automatic retries. Shutdown revokes source health before child cancellation and
retains both reader/runtime leases through reaping. Interrupted owners retain a halt
and discard inherited health on restart; fresh collection never resumes authority.
Journal and existing operator reviews expose read-only bounded service health.

Verification: **926 tests passed in 131.12s with warnings treated as errors**, including
26 new cases for cold/open-session warmup, closed idle, duplicate readers, refresh
failure, freshness/configuration/authority gates, no-retry behavior, protective exits,
owned-risk missing quotes, interruption and repeated-cancellation cleanup. Scoped
fatal-error/import lint, format, pip check and whitespace checks passed. The installed
wheel outside the checkout passed all **89 market cases** with warnings treated as
errors. Wheel SHA-256:
`c4088480ce1e316538b89546353295993e0b57c046209bf9e22f5c8d63ae30a8`.

Installed native proof ran the real collector entry point/protocol against local MCP
fixtures for two published samples and completed one scheduled stub HOLD using the
virtual ledger's $10 cash. Source account value remained zero. A third actual child
blocked until stop; all five source/venue children were reaped before both leases
released. All tasks ended STOPPED, reporting changed no store bytes and paired
authority remained VERIFIED. A separate installed native CLI ran closed/flat with its
OAuth file removed, idled without samples/cycles, handled actual SIGTERM with exit 0
and retained VERIFIED authority. Both proofs made zero remote broker/model calls.

Remaining: authenticated full-universe source latency/availability, bounded model
validation/adoption, actual host composition and operator/alert/archive services,
restore/host-failure evidence and real broker capabilities. No automatic fixture
fills, broker write adapter or deployed worker integration was added. Main, deployed
SHADOW/virtual-v1 and LIVE state remain unchanged. Do not rebuild the deployed SHADOW
image for this independent population. Operations: [PAPER_RUNTIME.md](PAPER_RUNTIME.md).

Estimated v1 execution-engine completeness: **about 89%**, a rough engineering
component estimate excluding LIVE readiness and profitability.

## Safe companion attachment and native operator CLI follow-up — 2026-10-07 UTC

Starting a second engine with the trading owner's constructor can convert an active
local SUBMITTING attempt to UNKNOWN and halt it as interrupted. That recovery remains
correct for actual owner startup. A new exact built-in `attach_existing` path instead
validates the retained private journal/authority pair and frozen current engine policy
read-only. It creates no files/tables, runs no migration/recovery, changes no permissions
and preserves reservations, order states, halts and runtime/source ownership. Every
later companion mutation still enters the existing paired write fence. Missing,
unfenced, foreign, rolled-back, publicly accessible or incompatible evidence fails
without repair/adoption. It is a trusted local handle, not broker or owner authority;
the existing complete-pair rollback/host-owner limitations remain.

The existing operator transport now has a native TLS `app.execution.control_cli`
entry point using this attachment path, without enrolling or automatically resuming.
Only the existing read review and signed command routes are exposed. Exact origin,
independent current read/signing credentials, action/revision/generation/evidence
guards, bounded request handling and signed receipt replay remain in force. A new
population may explicitly enroll its existing private signing key during runtime init
with `--operator-key-file`, validated before population creation. Old populations and
default init behavior remain unchanged; the key is not copied into runtime policy,
arguments, audit or model packets.

The companion defaults to literal loopback/8788, with explicit other IP/port binds.
It requires bounded owned certificate/key files, a mode-600 TLS key, a matching
noninteractive key pair and native TLS 1.2 or newer. Final symlinks/FIFOs, plaintext
origins and interactive TLS passwords fail closed. One process, no proxy-header
authority, no WebSockets/access logs and bounded concurrency/graceful shutdown apply.
A private single-host control lease is distinct from the trader lease, so a control
service can coexist without reclaiming the owner. Duplicate companions fail before
serving or changing execution state. Native SIGINT/SIGTERM handling retains the lease
through server/loop drainage, restores handlers and returns cleanly; startup errors
emit only a sanitized exception class.

Verification: **954 tests passed in 134.92s with warnings treated as errors**, including
28 new cases for retained order/halt/pair preservation, actual pending submission,
owner recovery compatibility, environment/config/authority/file boundaries, new-only
enrollment, TLS/credentials, duplicate ownership and native signed replay/shutdown.
Scoped fatal-error/import lint, formatting, pip check and whitespace checks passed.
The installed wheel outside the checkout passed all **85 companion/control cases**
with warnings treated as errors. Wheel SHA-256:
`252e8f59c864c7b64403b4d0b9329534af262da27dd41a1777078b7be4155373`.

The actual installed native CLI served verified loopback HTTPS against local fixture
state. Startup and GET review left both retained files unchanged and preserved
SUBMITTING without a halt; anonymous review and a duplicate CLI were rejected. An
exact signed HALT committed once and replay returned the original result with its
replayed flag. Actual SIGTERM returned exit 0, released the control lease and left
the unresolved reservation/SUBMITTING state intact under VERIFIED authority. An
independent test attached during a real stalled fake-venue acceptance child without
mutating its active attempt; its owner's later cancellation retained UNKNOWN and
reaped the child through the existing lifecycle. Zero remote broker/model calls
occurred. This is installed local fixture/TLS evidence, not real broker semantics.

Remaining: deployed service/certificate/key lifecycle and signed recovery, independent
alert-service composition and external notification/archive provisioning, authenticated
market/model validation, host-failure/restore proof and real broker capabilities.
This adds no broker write adapter, LIVE switch or current server deployment. The
deployed SHADOW release/virtual-v1, main and LIVE state remain unchanged. Do not rebuild
the deployed SHADOW image for this isolated engine component. Operations:
[PAPER_RUNTIME.md](PAPER_RUNTIME.md).

Estimated v1 execution-engine completeness: **about 89%**, a rough component estimate
excluding LIVE readiness and profitability.

## Independent alert-service follow-up — 2026-10-07 UTC

The HTTPS delivery component now has an independent native `app.execution.alert_cli`
with run/once/report commands. A halted, failed or stopped trader cannot terminate
this separate sender. It reconstructs only the exact existing enrollment from a
bounded frozen policy, validates the retained authority pair and current engine
configuration, and never invokes trading-owner recovery or the enrollment constructor.
Starting/reporting creates no execution tables, changes no permissions and preserves
PREPARED/SUBMITTING/UNKNOWN orders, reservations and retained halts. Missing enrollment,
changed/foreign policy, CA hash mismatch and invalid authority fail without repair.
Report is read-only, bounded and does not read the sink token or contact the network.

New runtime populations may explicitly enroll an exact HTTPS sink with
`--alert-origin --alert-token-file` and optional `--alert-ca-file`, validated before
population creation. Private tokens and optional CA trust retain existing transport
requirements. Paths/origin/limits are frozen; the sender has no CLI/environment
reconfiguration, auto-enrollment, rearm or resume option. Existing/default populations
and the deployed SHADOW experiment are unchanged. Initialization performs no network
calls. The sink must implement the existing exact ID/hash acceptance contract.

The private single-host alert lease now spans the entire service, including idle
polls, admission, transport and child cleanup. Runtime/control ownership remains
independent. Duplicate services fail before attachment; one-shot delivery retains
BUSY compatibility. Native SIGINT/SIGTERM drains the current bounded attempt and
starts no further sends. Cancellation of an embedding caller retains the lease
through native child cleanup even under repeated cancellation, leaving uncertain
IN_FLIGHT evidence for the existing conservative retry lease. Stable identities,
exact receipts, retry/backoff limits, exhaustion and explicit reviewed rearm are
unchanged. Exhausted older alerts do not starve newly due alerts. Delivery never
acknowledges an alert, resolves orders, releases reservations or resumes trading;
existing overdue/exhausted backlog gates and protective-exit rules remain intact.

Verification: **986 tests passed in 157.21s with warnings treated as errors**. This adds 32 focused cases covering attachment,
retained trading state/pair bytes, missing/changed policy, authority/CA boundaries,
new-only initialization, credentials, independent lifetime ownership, exhaustion,
continued halted delivery, repeated cancellation, privacy and native shutdown.
Scoped fatal-error/import lint, formatting, pip check and whitespace checks passed.
The wheel installed outside the checkout passed all **91 alert transport/service
cases in 58.05s with warnings treated as errors**. Wheel SHA-256:
`2df1b57a15770c9b41e3690e6ce064dc27a1df5427d6e7d88853d2edc127995f`.

The installed native sender delivered a retained halt alert to a verified loopback
TLS contract sink while an order remained SUBMITTING. Duplicate run/once admission
was rejected without changing either retained file or sending another request.
Actual SIGTERM returned exit 0 and released the lifetime lease. Restart did not
replay the confirmed alert; read-only report left both files unchanged without a
sink token. The unresolved order/halt remained intact under VERIFIED authority.
A second actual native proof signalled during a stalled request, drained its bounded
failure to RETRY, returned exit 0 and freed ownership. Zero remote broker/model calls
occurred. Sink acceptance is not proof of a human notification.

Remaining: independent host/service provisioning, external notification/archive
contracts and credential lifecycle, authenticated market/model timing and billing,
host-failure/restore validation and broker capabilities. This adds no daemon wrapper,
real broker write adapter, LIVE enablement or server change. The deployed release
remains `de5dd1c7bd3a2d3b85a2d6bb7f624e0d3a3f9245`. Do not rebuild the deployed
SHADOW image for this isolated PAPER component. Operations:
[PAPER_RUNTIME.md](PAPER_RUNTIME.md).

Estimated v1 execution-engine completeness: **about 89%**, a rough component estimate
excluding LIVE readiness and profitability.

## Isolated PAPER host layout follow-up — 2026-10-08 UTC

Three reviewable systemd units now define independent runtime, native TLS operator
control and alert service lifecycles under a dedicated service UID and Python 3.12
installation. They use a separate private population and role credential directories,
Python isolated mode, read-only code/system paths, private temporary directories,
no new privileges and explicit shared SQLite write paths. Peer credential and
deployed SHADOW directories are hidden from each role. Operator TLS stays loopback.
No unit installs dependencies, pulls code, initializes/migrates a population or
promotes LIVE. Startup conditions require retained journal/authority, with venue/feed
also required for runtime. A skipped condition is not healthy service evidence.

No cross-service Requires/BindsTo/PartOf links exist. Runtime has Restart=no;
failure does not auto-retry model/order work. Explicit owner restart/boot retains
existing halt, interrupted-claim and no-replay guards. Control/alerts have bounded
on-failure restart delay/start limits and immutable attachment; restart never resets
alert attempts or resumes/acknowledges trading. SIGTERM reaches the main process
first; cgroup kill deadlines allow 240 seconds for runtime and 45 for companions.
A hard owner death cannot invent an alert; its retained state is detected on later
owner startup, and external dead-process/host-loss monitoring remains required.

Verification: **992 tests passed in 297.76s with warnings treated as errors**. Scoped lint/format, pip check and whitespace
checks passed. The actual systemd 255 parser accepted all three units with only the
local executable/UID/GID mapping. All six host-contract/native composition cases
passed with installed native role processes outside the checkout: **6 passed in 144.91s with warnings treated as errors**.
Wheel SHA-256: `84ef0c4908453ae4d66136d39ed63f571f97e84d100f4eb68aff94f415a19921`.

The held-session disposable fixture completed one scheduled stub HOLD under native
owner/control/alert processes. A malformed fake-account read produced a FAILED
runtime and retained halt; a separate actual SIGKILL proof retained unclean RUNNING
state and detected it on explicit owner restart. Both preserved the completed slot,
with no model generation, fake order submission or replay. Operator HTTPS review
and alert receipt delivery survived the owner. Exact signed ACK committed without
resuming; companion restart preserved receipt replay and did not resend confirmed
alerts. Actual SIGTERM exited cleanly and freed all three leases under VERIFIED
paired authority. The test-only held clock is not a production override/replay
feature. Native control drainage includes open verified TLS clients within the
unit's stop allowance. Zero remote broker/model calls occurred.

This validates unit syntax and native role composition, not target-host systemd
installation, namespace enforcement, memory/cgroup behavior, reboot, external
notification acceptance or off-host protection. Actual host provisioning and recovery,
credential/certificate lifecycle, full-universe authenticated market timing and model
billing still require verification. No units were installed on DigitalOcean, no
existing worker/data/OAuth files were changed, main remains untouched and LIVE is
disabled. Operations: [PAPER_HOST.md](PAPER_HOST.md).

Estimated v1 execution-engine completeness: **about 89%**, a rough component estimate
excluding LIVE readiness and profitability.

## Sequential synthetic portfolio and build hardening

The opt-in synthetic profile runs the sole trader against its own virtual cash and
position. It uses safe Robinhood reads, real broker/local reconciliation, the same
persistent scheduler/lifetime lock and the existing isolated model process. It
rejects broker review as well as writes. Real-account SHADOW journals, cost reports
and ownership remain separate; default PAPER/SHADOW behavior is preserved.

Approved proposals queue for a later fresh quote and deterministic revalidation.
The ledger persists virtual fills/cash, original stops, session exits, daily entries,
cooldown, fees, all reported model costs, paired SPY liquidation equity and observed
net drawdown. Configurations are immutable named cohorts, including model/prices,
market inputs, prompt and risk policy. A pre-model receipt exposes potentially
billed calls after crashes/rollback; missing usage blocks new entries and makes net
economics unavailable. Future/naive quote timestamps now fail closed in the governor.
See [SYNTHETIC_EXPERIMENT.md](SYNTHETIC_EXPERIMENT.md) for execution assumptions,
profile selection and reporting limitations.

The complete updated suite passed **276 tests in 8.45 seconds** in a fresh Linux
CPython 3.12.14 environment installed exclusively from the new exact dependency
locks. `pip check` and lock/environment comparison passed. Tests include sequential
fills/accounting, restart/isolation, bad quotes, gap/session exits, cost uncertainty,
atomic rollback, cancellation, durable halt, backup restoration, CLI selection,
read-only gateway and authenticated read-only observer integration. These are
synthetic fixtures; no new authenticated broker/model or profitability evidence is
claimed. An actual installed-package Uvicorn run also passed authenticated synthetic
HTML/JSON, denied anonymous reads, unchanged DB and completed lifespan shutdown
with three simulated cycles/two fills. The earlier 229-test observer checkpoint
remains recorded below.

Server runtime and build dependency closures are pinned and the Docker build disables
both dependency resolution and build isolation. The official Python base tag is
explicit; target-host build and basic mounted credential/database access now pass
as recorded above. Normal host restart now passes. Authenticated regular-session
operation, failure recovery and desktop/mobile visual review remain host gates.
PR #1 stays draft; no merge has occurred.

## Private SHADOW observer

A separate `app.web.shadow:create_shadow_app` now reads stored worker/slot/cycle,
account, risk/reconciliation, review completion, linked model usage and forward
quote outcomes. The PAPER/demo app and its controls remain separate. Observer
startup requires SHADOW mode, LIVE disabled and an independent private password.
No broker/model clients are initialized or called; there are no mutation routes.

The database is opened read-only without bootstrap/repair. Reports use a single
committed snapshot, bounded pagination and source-linked outcome cohorts. Latest
account values carry their saved timestamp/age; heartbeat readiness is a separate
signal. Model HOLD, deterministic HOLD, unattributed legacy HOLD and failure remain
distinct. Missing usage is unknown; quote marks are not portfolio profit/alpha.
Raw broker reviews/identifiers, working orders and claim-owner tokens are omitted.

Compose mounts only read-only data and the independent observer password, without
broker OAuth or API credentials, and publishes only `127.0.0.1:8787`. Access uses an
SSH tunnel and password authentication. `prepare` generates the password privately
without overwriting existing files; `observer` can start inspection without starting
the worker. See [SHADOW_SERVER.md](SHADOW_SERVER.md) for consolidated operations.

The full updated suite passed **229 tests** in 7.60 seconds. Observer validation
includes authentication and password failure/rotation, denied
SQLite writes, absent mutation routes, empty/corrupt history, escaping and secret
projection, heartbeat freshness, paged cohort linkage, one committed WAL snapshot,
and progress with default-journal writes plus concurrent readers. Wheel packaging,
Compose schema/private-boundary checks and shell syntax are also verified. Actual
Uvicorn startup/private HTTP reads/graceful shutdown passed with synthetic history
and no remote calls. HTML responses render in tests; desktop/mobile visual review remains a host gate because
the browser download failed in this workspace. No deployment or live calls occurred.

## Model subprocess hardening

The SignalFlow review exposed the earlier `asyncio.to_thread` cancellation limitation.
OpenAI SHADOW decisions now execute in an isolated, tool-less child process. The child
receives only the MarketPacket, model name and request timeout through stdin. It owns
no broker connection or database handle. Success returns validated TradeDecision and
exact usage; errors return a sanitized class and fail-closed HOLD. Child stdout/stderr
diagnostics cannot enter the protocol or application logs.

Defaults: 60-second SDK request timeout, zero SDK retries, 120-second entire process
deadline (startup/import included). Model timeout or outer cycle cancellation terminates
the process group, escalates to SIGKILL after two seconds if needed and reaps the child.
Cancellation during startup or cleanup cannot leave an orphan or turn cancellation
into a successful proposal. The original strict schema, runtime limits, tools=[] and
one-turn policy remain unchanged. SDK tracing is disabled only in the subprocess;
application audit/usage persistence remains authoritative.

A model deadline persists HOLD/ModelProcessTimeout, no review and exit 8, then latches
HALTED. An outer cycle deadline leaves its active claim interrupted and blocks replay.
Missing usage remains unknown; local termination cannot guarantee cancellation of
remote computation or billing. No model calls are retried or reconstructed by recovery.

Updated local suite: **198 tests passed**, including 17 new process tests. They use real
blocking synchronous children that ignore SIGTERM, prove forced kill/reaping, cover
startup/repeated/success-cleanup cancellation, malformed/oversized/crashed output, exact
packet/decision/usage transport, no retries/tools, durable service halt and claim state,
no review/replay after timeout, and shutdown draining a blocked model call.
Compilation, fatal-error lint and whitespace checks passed. No live API/broker calls
were made. Container build, authenticated subprocess output, host memory/latency and
first scheduled regular-session cycle remain target-host gates.

## SignalFlow architectural review

[SIGNALFLOW_REUSE_ASSESSMENT.md](SIGNALFLOW_REUSE_ASSESSMENT.md) records a targeted,
source-linked comparison against SignalFlow `f9eaf2c1b5d13dca287ee7138126883065b00395`
and Trade-Bot `87319600d44524840010ccb3d4b3c084c0b00e74`. SignalFlow was read only;
no runtime features or integration were added by this review. Twelve isolated pure
SignalFlow rejection/replay/outcome tests passed; Trade-Bot's 181 tests passed again.

Reusable patterns are stored-evidence dashboard/reporting, complete decision cohorts,
point-in-time replay and separately measured synthetic execution. Options/flow feeds,
multi-bot coordination and SignalFlow's narration-only AI schema are not a direct fit.
The existing web app remains PAPER/demo only; the separate SHADOW observer is now
implemented above.

An important limitation in the reviewed snapshot was reproduced locally: the cycle timeout cancels an
awaiting task but cannot terminate the synchronous model thread used by `to_thread`.
Durable halt/claim blocking prevented another cycle; subprocess hardening above now
fixes local cleanup/shutdown for OpenAI SHADOW. The observer is implemented; the next
experiment slice is the sequential experiment ledger. No live model/broker
calls or server changes occurred during the review.

## Persistent server follow-up

The foreground Mac runner is a local verification tool. Continuous operation now
has a separate `compose.shadow.yml` worker and `scripts/shadow-server.sh` helper,
with a consolidated migration/operations guide in [SHADOW_SERVER.md](SHADOW_SERVER.md).
SignalFlow's separate Docker worker, persistent state, restart and container-hardening
patterns informed the deployment. SignalFlow itself is not changed or reused.

The worker uses a lifetime process lock, local heartbeat, graceful signal handling,
a bounded cycle timeout and durable HALTED state. Model, review, authentication,
calendar and interrupted-claim failures stop further attempts until explicit local
operator recovery. Resuming never replays an attempted slot. Docker restart does not
clear a halt. Scheduled idempotency and crash blocking remain in the existing SQLite
claim ledger. The service always disables interactive OAuth; an explicit stopped-worker
authorization command remains available for operators.

Credentials are private files; the OpenAI key is mounted as a secret and OAuth state
is writable for refresh. SQLite, claims, audit history and service state persist outside
the code checkout. Export/backup commands use consistent SQLite snapshots, check
integrity and print no secrets. Initial server import refuses to overwrite existing
history. Only SHADOW is configured. The observer follow-up now publishes a
localhost-only port through an SSH tunnel; no public web listener is configured.

Verification: **181 tests passed** locally. The 14 new service/backup tests cover
locks, in-flight heartbeats/shutdown, timeouts, sanitized persistent failures, local
credential checks, explicit claim abandonment/resume and private migration bundles.
The actual CLI booted healthy with MARKET_CLOSED and synthetic credentials, then
handled SIGTERM with exit 0 and STOPPED state. Compose configuration validation,
shell syntax, compilation, fatal-error lint and whitespace checks passed.

This workspace has no Docker daemon, real broker OAuth state, API key or confirmed
droplet connection. The image has not been built here and no server has been deployed.
Target-host image build, authenticated read probe, restart verification and the first
regular-session model cycle remain deployment gates. No new live-account/model evidence
is claimed by these offline checks.

## Installation follow-up

The user's next Mac batch pulled `0a6167681ea1b5e1694b8b6f5d334325ec505a6d`
but stopped at `pip install -e '.[dev]'`: setuptools discovered both `app` and
the runtime `var` directory as top-level packages. Tests and both scheduler commands
in that chained batch did not run.

Package discovery now explicitly includes only `app` and `app.*`, with implicit
namespaces disabled. The web HTML template is explicitly included as package data;
generated build directories are ignored. The original failure was reproduced locally
with an empty `var` directory. With that directory still present, the full editable
installation and wheel build succeeded. Wheel contents were checked for application
code and the template, with no runtime `var` files included. The installed CLI's
Saturday tick returned MARKET_CLOSED, exit 0.

The subsequent Mac batch pulled `32f0d23c6b7eeb9bedbd958e081c583353344d51`:
installation succeeded, **136 tests passed** in 33.95 seconds, the scheduled tick
returned MARKET_CLOSED with exit 0, and status showed CLOSED, no active slot, no
attempted slots and `network_calls: false`. The whole chained batch completed.
Installation and the closed-session gate are now verified on Python 3.14/macOS.

## Authenticated evidence from the user's Mac

The earlier authenticated model batch pulled `7abcf284ee84a787020ba5913c5cc8d504ee930c` and passed
**105 tests** in 3.66 seconds. Every subsequent command completed:

- `openai-structured-check`: OK, `gpt-6-luna`, HOLD, structured output accepted;
  Robinhood untouched.
- `shadow-cycle --agent openai`: reconciled account, no position or working orders,
  20 candidates and mixed regime. Model returned HOLD; governor rejected entry with
  `NO_ENTRY_REQUEST`; execution SKIPPED. No broker review or order submission.
- `shadow-audit`: cycle 6, packet timestamp `2026-10-03T17:52:06.028989`, prompt
  `v2-live-shadow`, model `gpt-6-luna`, latency 12,730 ms and explicitly linked evidence.
  Usage: 2,999 input / 322 output tokens; estimated cost **$0.00046090**.
  SPY observations: 769.86 to 769.86.
- `shadow-history --limit 100`: six HOLDs, including four historical agent failures,
  one earlier stub HOLD and this real model HOLD. Five legacy cycles were unlinked;
  only cycle 6 had explicitly linked evidence and usage. Zero broker reviews.

The model cited stale quotes and the Saturday session as reasons to stay in cash.
This verifies plumbing and a valid HOLD, not useful trading signal or profitability.
The governor-approved `review_equity_order` path has full simulated-cycle tests;
an authenticated approved review has not yet been observed.

Earlier batches passed 58, 95 and 105 tests but stopped respectively at an unsupported
Decimal schema regex and exhausted API credits. Those failures did not reach the
subsequent Robinhood cycle. The successful batch above supersedes the credit blocker.
Price wire schemas now accept number/string without the unsupported regex; Decimal
precision, positivity, finiteness and application limits still validate after parsing.

## Market-session runner

- `shadow-run --agent openai` polls locally every 30 seconds and starts at most one
  cycle per 15-minute slot, anchored to the XNYS regular-session open.
- The exchange calendar handles weekends, holidays, daylight saving and early closes.
  Closed sessions skip before initializing broker or model clients. Calendar errors
  and dates outside calendar coverage fail closed, with exit 12.
- Restart runs only the current slot; it never catches up missed slots.
- An additive SQLite table claims each slot before external calls. A unique active
  lock allows only one scheduled cycle in flight across workers sharing the database.
- Cycle evidence and slot completion commit together. Previously attempted slots
  never automatically retry, including model or review failures.
- A crash or interruption while a claim is active leaves it CLAIMED and blocks future
  scheduled cycles (exit 10). Inspect `shadow-schedule-status` and the audit before
  resolving an interrupted claim. No expiration or automatic replay is implemented.
- Session boundaries and scheduled time enter the packet. The session is checked
  again after reads and before review. If it has closed, model judgment or review is
  skipped as appropriate and the reason persists in execution evidence.
- Existing daily entry limits now count completed hypothetical entry reviews from
  persisted history, using the New York calendar day. Unreviewed proposals do not
  count. The existing exit cooldown uses the latest completed hypothetical close
  review and survives restarts. These are review controls, not simulated fills.
- Prompt version is now `v3-session-shadow`. The last authenticated model run used
  `v2-live-shadow`; the updated prompt has not yet been exercised against OpenAI.

The process runs in the foreground and must remain running on an awake machine.
It is not automatically installed as a service. Separate database files do not share
claims; use the same `robinhood.db` for this one-trader experiment.

## Persistent audit and history

New cycles save decision, exact usage, account/benchmark snapshots and reconciliation
in one transaction. Explicit evidence links prevent borrowing usage from an earlier
cycle. Legacy rows remain `LEGACY_UNLINKED`; missing usage is unknown.

`shadow-history` separates explicitly linked model HOLDs, deterministic stub/session
HOLDs, unattributed HOLDs and agent failures. For compatibility, `genuine_hold_count`
still means all non-failure HOLDs; it is not a model-only count. Session context and
blocked execution counts are included. SPY output is a raw quote-price return with
sample endpoints. Strategy/economic P&L remains null: there is no counterfactual fill
ledger yet, and SHADOW submits no trades.

## Forward quote outcomes

New cycles also atomically register two outcome rows per source cycle, for fixed
15- and 60-minute horizons anchored to its scheduled session slot. Policy:
`v1-forward-quote-marks`. This uses already-read packet quotes and adds no broker
or model calls. These rows are separate from orders, fills and owned positions.

- Eligible sources have clean reconciliation, explicit linked model usage and an
  available decision inside a scheduled regular session. Source quotes must be
  fresh, uncrossed and not future-dated. Stub/guard/failure/unscheduled sources and
  legacy cycles cannot silently become model performance evidence.
- Reviewed entries require deterministic approval and a completed broker review.
  The reference is the decision-packet ask and approved notional. It is a quote
  reference, not a claim that an execution-time fill was available at that price.
- Cash HOLD is first-class: the fixed reference notional is the source account's
  equity, price change is zero and the linked source model cost is deducted.
  HOLD with an existing position and CLOSE/REDUCE are explicitly excluded in this
  first measurement policy.
- SPY uses its packet ask and subsequent bid on the same fixed reference notional.
  A qualifying later cycle provides fresh quotes at/after the target, after source
  decision completion, in the same regular session. The first accepted observation
  is immutable and links to the exact later cycle and quote timestamps.
- The observation window ends five minutes after the target or at regular close,
  whichever comes first. Missing/stale/future/pre-target pairs remain PENDING;
  a later cycle marks overdue rows EXPIRED. Targets outside the regular session or
  before decision completion are EXCLUDED. No next-session backfill occurs.
- Source model cost is frozen with the baseline and deducted per horizon sample.
  The database's reported total cost is counted once from usage rows. Reports keep
  15/60-minute cohorts and reviewed entries/cash HOLDs separate. Overlapping marks
  are not independent samples and are never summed into a bankroll or compounding
  return. Fees, slippage and dividends are not modeled.
- Existing databases receive an additive `shadow_forward_outcomes` table. Legacy
  cycles are not reconstructed/backfilled. Reports make no network calls and do
  not expire rows on read; pending status is as of the last collected packet.

Inspect local evidence:

```bash
python -m app.robinhood.cli shadow-outcomes --limit 100
```

The result includes baseline/measurement cycle IDs, status/reasons, quote references,
fixed notional, linked model cost, forward quote changes and SPY excess after source
model cost. It reports arithmetic cohort means only when observations exist.
An existing database with only legacy/manual cycles initially reports EMPTY. Portfolio
strategy/economic P&L remains null because this is proposal evidence, not a fill ledger.

Audit, history and schedule status make no OpenAI or Robinhood calls:

```bash
python -m app.robinhood.cli shadow-audit
python -m app.robinhood.cli shadow-history --limit 100
python -m app.robinhood.cli shadow-schedule-status
python -m app.robinhood.cli shadow-outcomes --limit 100
```

## Authority and configuration

- Default remains PAPER, with a separate `trader.db`. Robinhood defaults to `robinhood.db`.
- Trader Agent has `tools=[]`, strict `TradeDecision` and `max_turns=1`.
- Deterministic software approves/rejects/sizes, capped by unleveraged buying power.
- SHADOW may use only `review_equity_order` after governor approval for hypothetical
  trading. It never submits or cancels an order. LIVE remains disabled.
- Broker/local mismatches fail closed, including unsupported assets, multiple positions,
  unowned/missing positions, quantity/symbol mismatch, non-long positions and working orders.
- Robinhood discovery proved 76 tools and schemas without required-tool/schema gaps.
  Accounts, portfolio, positions, working orders, quotes, historical OHLCV, indicators,
  tradability and regime construction work. Historical requests deliberately fetch
  one symbol per call to avoid the MCP SDK's 1 MiB SSE-event ceiling.
- Universe: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLI, XLV, XLY, AAPL, MSFT, NVDA,
  AMZN, META, GOOGL, TSLA, AVGO, JPM, COST.
- Model: `gpt-6-luna`; configured standard prices: $0.10 / 1M input tokens and
  $0.50 / 1M output tokens. Costs are estimates using these configured rates.
- Agent errors persist fail-closed HOLD and exit 8; review errors persist decision,
  risk and usage with sanitized error class and exit 9. No failure submits an order.

## Verification and next use

The Mac calendar installation is already verified. Validate this follow-up without
repeating dependency installation or the structured-output check:

```bash
git pull --ff-only && \
pytest -q && \
python -m app.robinhood.cli shadow-outcomes --limit 100
```

To collect regular-session history and future quote outcomes continuously, use the
Linux service in [SHADOW_SERVER.md](SHADOW_SERVER.md). The foreground runner is also
available for local checks. Outside a regular session either runner waits without
broker/model calls; during a session it attempts the current slot and persists its
result. Run only one worker against the account across machines:

```bash
python -m app.robinhood.cli shadow-run --agent openai
```

Forward-outcome checkpoint suite: **167 passed**. Compilation, fatal-error lint and whitespace
checks passed. The real CLI's Saturday tick returned MARKET_CLOSED with exit 0;
schedule status reported no active claim or slots and no network calls.

Local verification covers calendar boundaries, concurrent SQLite claims, restarts,
crash blocking, rollback, sanitized failures, persistent New York daily limits,
cooldown expiry, session-ending reads/model calls and review-only execution.
Outcome tests cover quote/cost arithmetic, cash HOLD, exclusion reasons, immutable
paired observations, concurrent SQLite connections, expiry/early close, atomic
rollback, restart persistence, existing database upgrades and local reporting.
No authenticated OpenAI or Robinhood calls were made in this execution workspace;
it has neither API credentials nor Robinhood OAuth state.

The separate sequential synthetic portfolio/fill ledger described above is now
implemented and selected on the server. Next experiment work is to collect enough
regular-session decisions and virtual transitions to evaluate signal. Real-account
SHADOW forward marks remain separate from the synthetic portfolio economics.
No profitability claim or LIVE enablement follows from this checkpoint.
