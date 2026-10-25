# Balanced detail panels and simpler navigation

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

The guarded refresh now expects the deployed a51a313 image and preserves it as
`trade-bot-dashboard-before-panel-balance`. It reuses frozen ui-review-v2. Do not
rerun prepare. Original SHADOW, V1/V2 data, older rollback readers and credentials
remain untouched. No dependencies, engine changes or prospective activation.
