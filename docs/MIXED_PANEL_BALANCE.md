# Balanced detail panels and simpler navigation

## Default-height correction: 2026-10-25

The previous grid-stretch correction still let long content enlarge the lower row.
All six detail tabs now use the same explicit 420px default viewport. Trades and
Data Stream scroll their content inside that viewport; other detail tabs scroll
inside their tab container. Recent activity uses the same default height. Manual
Trades/activity expansion remains independent and persists during polling. The
activity container now has a stable ID so its scroll position also survives polling.
Print and no-JavaScript views retain readable full content. Upper account/trade-card
sizes and colors are unchanged.

The Active trade card still accepts one native `data.position`. Trades can list
multiple orders, but neither that list nor this sizing correction provides a selector
for simultaneous active plays. Native two-play UI integration remains unfinished.

[Installed validation](MIXED_PANEL_HEIGHT_PROOF.json): 27 Python cases, 19 JavaScript
cases and 262 matching source/wheel/installed application files. Browser visual
acceptance is pending: the local Playwright package has no Chromium executable.
No browser/dependency installation or host change occurred. This is not deployed.

The refreshed host helper now requires the confirmed d2092f1 image and preserves
it as `trade-bot-dashboard-before-panel-height`. It refuses an existing container
with that name. The already-consumed before-panel-balance rollback is preserved.
The operator executes deployment; the current frozen V2 review and historical V1
are reused/preserved through the existing checks, never regenerated. Shell syntax
was checked locally; the host procedure has not been executed in this session.

## Earlier panel-balance release

The operator deployed a51a313 after its source-byte check initially failed because
`app/options/read_cli.py` was root-owned mode 600. The supplied path inspection
confirmed traversable directories, a readable sibling template and the original
a3216b6 reader still running. Making only tracked app/fixture-seed source readable
resolved that failure. The subsequent host run matched all 259 installed files,
verified the frozen native account, passed authentication and retained three fills.
Startup connection resets cleared within the existing retry sequence. The previous
reader is preserved as `trade-bot-dashboard-before-stream`. No collector/model/
PAPER worker was started. This is host acceptance, not complete visual acceptance.

The user then reported that Trades stretched the entire lower row while Data
Stream was shorter than neighboring boxes. The latter had an independent 420px
maximum height. This release removes that cap: Data Stream and collapsed Trades
use the existing 420px minimum and stretch with their grid row, while their content
scrolls internally. Column proportions and the equity/active-trade grid are not
changed. Expand trades exposes the full retained list; Collapse trades restores
its compact view. Expansion persists through in-page updates and does not stretch
Recent activity. Explicit record URLs still reveal the relevant expanded trade.

The active-trade tabs remain Summary, Thesis, Protection and Fills & costs. Summary
now has one disclosure, Exact levels and original targets, containing the quote/
cost details as well. Extra cross-section links are removed. Strategy controls
filter without scrolling; decision stages and activity rows are informational.
The accessibility skip link, primary tabs, normal history paging and account JSON
download remain. No changes to native approvals, clocks, fills, exits or accounting.
The engine still owns at most one position across all setup families; this UI change
does not introduce simultaneous independent plays.

Visible explanations now use plain language while preserving simulation, quote age,
unknown-cost and fill-status distinctions. Negative money values and trade returns
use the same amber accent throughout the mixed dashboard. Strategy names remain
visible on mobile after removing their navigation arrows.

[Installed proof](MIXED_PANEL_BALANCE_PROOF.json) records 33 passing Python cases,
19 JavaScript cases and 259 matching source/wheel/installed application files.
The initial development run caught a CSS/Jinja comment-delimiter collision; it
was fixed before the passing final run. Native cases ran serially from copied tests
with a noneditable wheel, Python -I, warnings as errors, plugin autoload disabled
and explicit anyio. No reinstall happened while native tests ran.

Browser acceptance remains pending; the previously established local-preview
access limitation remains. The image edit requested during this work is only an
illustrative mockup, not a browser screenshot or release evidence. Inspect the
actual desktop/mobile collapsed/expanded panels and the single active-trade
disclosure after deploying; no visual pass is inferred from unit tests.

The operator subsequently confirmed deployment of
`d2092f16cc99a3749be04fb2bd5a5d26fa0e30bc`. The running image matches that revision;
259 installed files matched source, native_fixture_verified was true, health was
OK (options-observer), authentication passed, and three native simulated fills
remained in FROZEN_OFFLINE_UI_FIXTURE mode. trader_health was NOT_CHECKED.
Startup resets cleared within retries. No PAPER runtime, collector or model worker
started. This evidence was supplied in the continuation handoff, not independently
rechecked on the host in this session.

Container: `fc18be25a6da731c05841484a87a9d182f02eee2ab8caccb133bd37682957a1a`.
Manifest: `sha256:cf537ab0521b3ca5e948d9b6456067820037cb6f75c226b94adfb9ab8d05674a`.
Config: `sha256:edca13d3c4a190ae2481d5339f9f3dd7c1620e95b0ea26a31c718d01ab31f8b2`.
Manifest list: `sha256:fea17d2705e013da56e050a3c17018554014cae116d462e2071806974ef2536b`.

The a51a313 reader already exists as `trade-bot-dashboard-before-panel-balance`.
Do not rerun the old refresh blindly: both its expected prior image and rollback
name have been consumed. Frozen ui-review-v2, historical failed v1, previous
rollback readers and original SHADOW services remain preserved. Actual desktop/
mobile browser acceptance remains pending. No additional deployment is authorized
or required by this accounting checkpoint.
