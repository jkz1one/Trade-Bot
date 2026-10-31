# Data Stream and automatic dashboard updates

Data Stream joins Decisions, Opportunities, Trades, Performance and System in the
existing detail tabs. Its dark terminal presentation follows the user's X example;
it shows actual recorded quotes and account events, never animated filler or fake
processing. The bounded list retains source and receipt timestamps, bid/ask sizes,
entitlement and exact option identity. Quote/event filters and internal scrolling
keep it inside the existing 420px detail-card area. The original columns, card
alignment and activity expansion rules remain unchanged. The page uses darker
charcoal surfaces and a greener accent, based on the user's supplied screenshot.

The active-trade card borrows useful handling from SignalFlow's
ContractQuoteSummary at `f9eaf2c1b5d13dca287ee7138126883065b00395`, without copying
its layout or importing its trading logic. Per-unit saved/latest bid and unrealized
P&L lead, followed by average entry, bid/ask and position value. Option premiums
use the actual contract multiplier and stay separate from underlying prices and
protection levels. Source/receipt times, sizes, entitlement, retained Greeks and
basis remain in details. Conflicting/mismatched quotes are withheld. Stale quotes
may be displayed as last-known prices but never revive withheld valuation/P&L.
Native approvals, exits, fills and full-cost accounting are unchanged.

## Update behavior

Previously, `?refresh=true` opted into a 30-second full-page reload. The mixed desk
now polls the authenticated same-origin `/desk/snapshot` every five seconds by
default, replacing rendered account content in place. Selected tabs, family/event
filters, expanded activity, disclosures, keyboard focus and scroll positions are
retained. No refresh is required to see newly persisted evidence.

Only one request is in flight; each has a ten-second timeout. Failed requests back
off to at most 30 seconds, keep dated records and show an interruption warning.
Authentication rejection stops automatic retries. A valid unavailable snapshot
replaces old balances with withheld values. Hidden tabs pause requests and resume
when visible. Copying text or focusing a select temporarily holds replacement.
Frozen historical review, paged history and `?refresh=false` disable automatic
updates; Sync now remains an explicit stored read. The original options-only desk
keeps its prior opt-in refresh behavior.

The CSP permits same-origin connections only. Both new routes retain the existing
private authentication, no-store responses and GET-only access. Every read uses the
existing bounded read-only observer. No page request starts a collector, provider,
model, order, native fill or trade. Stream event labels identify retained journal
events, not an independent reconciliation guarantee.

Five seconds describes the dashboard's check interval, not quote latency. Actual
freshness depends on the independent collector, delivery cadence and original
source timestamp. The Robinhood continuous delivery connection remains unfinished.
The current frozen UI fixture has no running trader or live market feed.

## Validation and deployment

[Installed proof](MIXED_DATA_STREAM_PROOF.json): 63 Python cases, 23 JavaScript
cases, and all 259 application/template files matching source, wheel and installed
bytes. Tests used an isolated noneditable wheel, copied tests outside checkout,
Python `-I -W error`, disabled pytest plugin autoload and explicit anyio. Native
cases ran serially; no installation occurred while they ran. The two initial test
expectation failures (equivalent UTC encodings and existing EMPTY status) were
corrected before the passing final suite. No engine safeguard was changed.

Browser visual acceptance is still pending. The cloud browser could inspect the X
reference, but could not reach the local HTTP preview; policy then rejected opening
local HTML. No blocked-file workaround was attempted. Rendering and DOM unit tests
are not visual acceptance. Check the deployed desktop/mobile views, price clarity,
box heights, Data Stream filtering and scroll behavior, then provide screenshots.

`bash scripts/dashboard-review-host.sh refresh ui-review-v2` requires the currently
reported `trade-bot-dashboard:a3216b6d3953d1291643830b20ac4ef69fd8b37b` reader and
preserves it as `trade-bot-dashboard-before-stream`. It verifies the installed bytes
and unchanged frozen native evidence before switching the separate dashboard.
Do not prepare another fixture. V1, V2, earlier rollback readers, private credentials
and original de5dd1c SHADOW services remain untouched. The operator runs host
commands. No PAPER/model/LIVE activation is part of this release.
