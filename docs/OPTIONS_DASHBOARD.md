# Options dashboard: decision and protection view

This is the M8 research-desk presentation over the existing authenticated,
stored-only options observer. It changes no execution rule, collector, account,
cost arithmetic, authentication, API response or deployment. Main stays untouched,
PR #1 draft, LIVE disabled and the deployed experiment frozen.

## Mixed desk follow-up — 2026-10-23

The [explicit mixed observer](MIXED_DASHBOARD.md) now implements the separate
stock/options/Scope presentation and original target rail. Its dedicated contract
supersedes the historical mixed-work statements below. The legacy options observer
and comparison remain separate. See [installed proof](MIXED_DASHBOARD_PROOF.json).
Actual browser acceptance is still pending. Deployment is now user-authorized,
but target-host access and compatible journal/route selection remain outstanding;
no server, worker, provider or LIVE state has been changed.

## Persistent desk follow-up — 2026-10-23

The requested direction is one persistent page with a restrained game-HUD palette,
no candle chart, balance history and an active trade card above the detail tabs.
The implemented options desk keeps those two panels outside the tab content.
Summary, Trade details, Decisions, Scope and Fills & costs switch locally. The
original thesis, native invalidations, exit deadline, bid-mark availability and
pending/unknown ownership remain explicit. This is not yet unified mixed-account
presentation; the boundary below remains in force.

The balance graph uses the existing independently bound historical comparison.
5-session, 20-session and All controls crop its recorded path without rebasing
returns, changing the dollar scale, extending incomplete paths or fetching prices.
Model-off A, SPY and cash can be hidden independently. These settings and the
selected tab persist in sessionStorage under the population identity. Denied or
malformed storage does not break the page. Refresh still means an explicitly
requested stored read; historical pagination disables automatic refresh.

Tabs expose tablist/tab/tabpanel semantics, Arrow/Home/End navigation and focus.
Anchor links reveal their containing panel, including the card's protection link.
Without JavaScript all evidence remains visible; print exposes all panels.
The authenticated `/desk.js` endpoint serves only the packaged presentation asset
and does not read a journal. CSP allows same-origin scripts, disallows inline
scripts, keeps default-src none and nosniff; script code has no fetch, timers,
provider SDK, model call or trading action. No dependencies were added.

SignalFlow references remain pinned to
`f9eaf2c1b5d13dca287ee7138126883065b00395` in the
[source manifest](research/signalflow_options_sources.json). The inspected
`PlayProgressRail.tsx` and `DynamicManagementPanel.tsx` informed compact retained
protection checkpoints and expandable diagnostics. **No React component or
numeric progress-rail algorithm was ported in this slice.** The observer does not
expose enough bound original target/current-underlying evidence to honestly port
that rail wholesale; a decorative progression must not imply target attainment.
SignalFlow midpoint/last fallbacks and proposed-stop/native-stop merging were not
adopted. Native premium floors and original thesis stay in retained detail panels.
External comparison research: [FreqUI](https://www.freqtrade.io/en/stable/freq-ui/)
uses trade/performance/wallet views; [QuantConnect live results](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/results)
separate equity, holdings, orders and logs. This desk adopts the information
hierarchy, not their trading controls or best-effort historical balance backfills.

Validation: **129 distinct Python cases and 7 JavaScript unit cases** on wheel
`bbbcba357fffd726fdc5fe70eea3562d6902ebeaeed7df5a3d819f48a3fe6a3b`.
The initial run passed 124 cases and failed five assertions tied to replaced
navigation/heading text; the five-case focused rerun passed after updating those
assertions. No application change or reinstall intervened. Five Python cases and
seven JavaScript cases are new. All 244 app/template files match source, wheel and
installed bytes; 239 match the parent. See [exact proof](DASHBOARD_HUD_PROOF.json).

Eight fixture states at desktop/mobile sizes were generated and checked for
balanced markup. **Actual browser review and screenshots remain blocked**: the
cloud browser returned `ERR_CONNECTION_REFUSED` for the running local fixture
preview. JavaScript unit checks are not browser acceptance. Mobile layout,
keyboard/screen-reader behavior and visual polish remain subject to that review.
Mixed stock/options observer and original target rail remain open UI work. No
authentic provider/model/broker acceptance was attempted or authorized.

## What is visible

The October 23 pass adds an **At a glance** briefing with retained entry blockers,
account/supervision ages, exact owned contract and original exit deadline, plus the
newest decision **on the selected family/page**. It explicitly allows that decision
to be historical; it is not a new signal. Missing ages remain Unknown and a recorded
zero-second age remains zero. Scope selections never link an option decision hidden
by that selection. The header carries the observation timestamp and fixture mode.

Current ownership and deterministic protection now precede the potentially long
decision timeline. Four stages still separate proposal, native review, order and
fills; applying a TIGHTEN still cannot invent an order. The historical chart keeps
its own dated net-equity/benchmark cards, with exact session values and all cost
roles in a native disclosure. Order/fill tables have separate disclosures, open by
default. Current unavailable equity uses warning emphasis, never a substituted
historical result. No accounting or stored/API contract changes accompany this pass.

The responsive briefing uses three/two/one columns. Long desktop briefing text has
an explicitly labeled, keyboard-focusable scroll region and remains fully visible
on mobile; full decisions retain the complete escaped thesis and uncertainty.
Native disclosures and links remain readable without scripts. The desk enhancement
uses one authenticated same-origin script, with no external resources. These are
implemented layout/interaction contracts, pending actual browser acceptance.

### Mixed-owner boundary

The existing `OptionObserver` explicitly rejects `mixed_owner` enrollment. This
pass preserves that guard and tests that reading such a journal leaves both native
journal and venue bytes unchanged and shows Unavailable without account metrics.
It does **not** present this options surface as an accepted unified stock/options
dashboard. A separately bound mixed observer/comparison presentation remains UI
work; the settled native mixed engine/runtime/replay is not reopened.

The dark research desk uses a compact overview, restrained mint/blue accents and
separate panels for historical comparisons, decisions, position and evidence.
Current cash and equity estimates lead the page. The estimate remains unavailable
when the observer withholds it, and its label explicitly excludes exit/data/host
costs. Known model cost retains its exact precision and unknown-call count.
Historical net results and SPY remain separately dated, independently computed
evidence; they never replace current missing values.

Account and supervision status/timestamps, worker records, unacknowledged alerts
and entry blockers remain visible. Frozen population/release/runtime details move
into a native expandable section. No fresh saved record is labeled as a running
worker or permission to trade. Empty and unavailable populations show no metrics.

The selected history page now displays one decision card per stored cycle:

- **Proposal:** attributed role/action, thesis and uncertainty where recorded.
- **Review:** saved review outcome and application status, including rejection/HOLD.
- **Order:** the linked order state and whether an attempt was actually recorded.
- **Fills:** attributed recorded quantity versus approved quantity, independently
  of order acceptance.

Every card retains the exact model cost or its unavailable/not-called status.
Management changes, review blockers and errors remain visible. Expandable details
retain candidates, exact contracts, quantity/full-premium ceilings, approval times,
setup reasons, requested/applied stops and order/fill identifiers. A TIGHTEN action
can be applied without an order; the card never invents one. Historical navigation
and family filters describe the selected history page, not current advice. Scope
watches remain a distinct research-only section with their existing evidence.

Owned management now also shows the saved native health assessment, its time and
observation freshness, retained action/reasons, and enrolled premium/trade floors.
An old CAUTION/DEFENSIVE/HEALTHY label remains explicitly a **stored assessment**;
stale observations remain visible. Floor units differ: the trade floor is a minimum
fill price, while the premium trail is an original-quantity premium equivalent.
Neither promises an executable sale or complete net return. Missing floors remain
“Not established,” and missing diagnostic components remain “Unknown.” Expandable
progress/contract diagnostics retain coverage blockers and the theta heuristic label.

## Interaction and bounds

The original review used links and native disclosures. The persistent desk now
adds the authenticated packaged script and local tab/chart buttons described above.
It has no trading form, model/provider call or background execution work.
The existing private authentication, no-store policy and restrictive CSP remain.
The API and all source journal/venue contents are unchanged by viewing the page.

The layout uses bounded grids, wrapping long identifiers and a two-column decision
stage layout on narrow screens. Tables retain labeled, keyboard-focusable scroll
containers; the historical chart adds a focusable horizontal scroll surface on
mobile to preserve readable labels. The skip link, anchored section navigation,
native disclosure keyboard behavior and visible focus outlines remain available.
These are implemented semantics, not a claim of completed browser acceptance.

## Reproducible offline rendering drill

For one installed test run plus all review files and retained results, use the
[options testing procedure](OPTIONS_TESTING.md). It wraps the existing drill below
and verifies the installed application matches the checkout before running.
Successful runs also produce `Trade-Bot-UI-Review.zip` for review on another
computer without installing Python or repeating the tests. Extract it and open
`index.html`; the original rendered pages are unchanged and visual acceptance
remains pending.

With the matching package and existing test dependencies installed, run the helper
from the checkout. Choose a new absolute destination:

```bash
PYTHONPATH=.:tests python tests/options_dashboard_examples.py \
  --output /absolute/path/new-dashboard-drill
```

The command creates independent local fixture journals and static HTML for eight
states: populated, empty, unavailable, stale, halted, unknown cost/order, long text
and HOLD. Entry/management/fill, stale and HOLD baselines use native fixture owners
and scripted model results. Comparison and modified edge states are explicitly
synthetic presentation examples, not accepted economics or authentic market data.
No real provider/model/broker is called. This is a local rendering drill, not a
service or deployment instruction.

Open each `*-desktop.html` and `*-mobile.html` locally. They embed the exact rendered
page at 1360px and 390px, with a visible DISPLAY FIXTURE label. Their frame is only
the test wrapper; the actual authenticated app remains frame-denied. Expand long
decision and protection details, navigate by keyboard, inspect all sections and
chart labels, and retain screenshots before visual acceptance. The helper never
overwrites an existing destination or attaches to the deployed population. Static
files support layout, disclosure and section-anchor review; family/pagination/API
routes still require the authenticated observer and are not emulated by the drill.

## Acceptance still open

Native rendered-state, cost/uncertainty, escaping, read-only and installed-package
regressions are recorded in [continuation status](SLICE2_STATUS.md). On October 23,
the actual browser could not connect to the isolated localhost fixture server
(`ERR_CONNECTION_REFUSED`); its workspace-host URL was then rejected with
`ERR_BLOCKED_BY_CLIENT`. No attempt was made to bypass that policy. No screenshots
were captured and no desktop/mobile visual or keyboard acceptance is claimed.
The earlier file-URL rejection remains historical evidence, not a successful review.

Actual rendering/clipping, expanded states, keyboard traversal, chart-label and
contrast review, plus user visual acceptance, remain M8 gates. This pass does not
close unified mixed presentation, authentic provider/host acceptance or prospective economics.
See [observer contract](OPTIONS_OBSERVER.md) and [source of truth](SOURCE_OF_TRUTH.md).
