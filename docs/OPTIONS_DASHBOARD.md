# Options dashboard: decision and protection view

This is the first dedicated M8 presentation pass over the existing authenticated,
stored-only options observer. It changes no execution rule, collector, account,
cost arithmetic, authentication, API response or deployment. Main stays untouched,
PR #1 draft, LIVE disabled and the deployed experiment frozen.

## What is visible

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

All controls are ordinary links or native HTML disclosures. There is no JavaScript,
trading form, new endpoint, action button, model/provider call or background work.
The existing private authentication, no-store policy and restrictive CSP remain.
The API and all source journal/venue contents are unchanged by viewing the page.

The layout uses bounded grids, wrapping long identifiers and a two-column decision
stage layout on narrow screens. Tables retain labeled, keyboard-focusable scroll
containers; the historical chart adds a focusable horizontal scroll surface on
mobile to preserve readable labels. The skip link, anchored section navigation,
native disclosure keyboard behavior and visible focus outlines remain available.
These are implemented semantics, not a claim of completed browser acceptance.

## Reproducible offline rendering drill

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
regressions are recorded in [continuation status](SLICE2_STATUS.md). The cloud browser
rejected the local preview URL because its URL policy permits only HTTP/HTTPS;
no workaround or alternate browser surface was attempted. No screenshots were
captured and no desktop/mobile visual or keyboard acceptance is claimed.

Actual rendering/clipping, expanded states, keyboard traversal, chart-label and
contrast review, plus user visual acceptance, remain M8 gates. This pass does not
close Scope execution, authentic provider/host acceptance or prospective economics.
See [observer contract](OPTIONS_OBSERVER.md) and [source of truth](SOURCE_OF_TRUTH.md).
