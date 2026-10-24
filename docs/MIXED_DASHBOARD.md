# Stored mixed-account research desk

The explicit `--mixed` observer serves one native stock/options/Scope PAPER
journal. It keeps balance history and the active trade card on one page, with
local Protection, Decisions, Orders & fills, Costs and Diagnostics tabs. The
restrained HUD shares the existing options styling and packaged script. There is
no candle chart, dependency change, execution route or provider/model work on reads.

## Evidence and presentation

`MixedObserver` uses the existing bounded, owner-private, read-only SQLite
transaction. It supplies data to pure native verification functions without
opening an execution owner. Frozen enrollment, original order terms, native fills,
current snapshot coverage, reconstructed cash and held protection must agree.
Incomplete reconciliation withholds balances, position and authoritative fill
totals; stored attempts and independently verified costs can remain visible.
The legacy `OptionObserver` still rejects mixed enrollment.

Cash, settled funds, reservations and full-cost equity remain separate. Execution
fees are already included in cash; entry/management charges and DATA/HOST/OPERATING
allocations are deducted once. Unknown charges, unresolved orders or stale account
evidence suppress current equity. Open-position estimates require a complete,
sized, fresh stored bid and exclude future exit costs. They are fixture estimates,
not broker value or evidence of executable liquidity now.

The chart reconstructs the last 100 saved snapshot boundaries. Only complete flat
boundaries with full known costs receive values. Open positions, missing native
attempt/fill coverage and incomplete costs create gaps. Points are spaced by record
order, not elapsed time. Isolated points stay visible; lines do not bridge gaps.
This is not a continuous marked equity curve. SPY and A/B/C/D mixed comparisons
still need a separately bound presentation; the option-only comparison file is
explicitly rejected in mixed mode.

Trade cards retain actual share/contract quantity, exact option identity, original
thesis, native active invalidation, original targets, premium protection and exit
deadline. Underlying levels never use option premium as a price reference. The
rail adapts SignalFlow's 5.5-point collision grouping and alternating 14-point
label rows from `PlayProgressRail.tsx`, pinned to
`f9eaf2c1b5d13dca287ee7138126883065b00395` in the
[source manifest](research/signalflow_options_sources.json). React components,
midpoint/last execution fallbacks and proposed/native-stop merging are not adopted.
Stale stock quotes say Last bid; targets and native stages never establish a fill.

Model proposals, saved native approvals, actual attempt timestamps and native fill
receipts are separate. Original account revision is displayed where retained by
the stock intent; options explicitly label its absence rather than inventing a
revision. Exact retained terms remain available in escaped disclosures. Supervision
records carry their own age and do not prove a currently running worker.

The report is bounded to 2,000 rows per execution table, the existing 64 MiB
database / 1 MiB response / two-second read limits, 100 recent saved frames and
100 chart boundaries. Capacity or malformed evidence fails closed. This bounded
fixture reader has not established long-running production capacity acceptance.

## Installed verification and visual review

See [durable proof](MIXED_DASHBOARD_PROOF.json) and the newest
[status entry](SLICE2_STATUS.md) for exact wheel, case IDs and file identities.
The five observer/dashboard suites run serially from copied tests against a
noneditable installed wheel, Python `-I`, warnings as errors, disabled pytest
plugin autoload and explicit anyio. JavaScript checks cover local tabs and chart
interaction; they are not browser acceptance.

`tests/mixed_dashboard_examples.py` generates nine offline display states: flat,
stock, stale, closed, option, Scope, unknown cost, unavailable and long text.
The first seven use native fixture owners and scripted model results; unavailable
and long text are explicit display alterations. Run from copied tests only after
native verification has finished. No real account or credentials are involved.
The helper creates desktop/mobile wrappers and the packaged local script in a new
absolute output directory. It starts no HTTP server and performs no deployment.

Actual desktop/mobile review, expanded states, keyboard use, clipping/contrast and
screenshots remain **pending**. Earlier loopback previews were unreachable and
workspace/file URLs were blocked by browser policy. Do not bypass those restrictions
or represent generated HTML as screenshots. A reachable authorized review endpoint
or operator browser evidence is still required before visual acceptance.

## Authorized deployment handoff

The October 23 continuation explicitly requested deployment. That supersedes the
earlier no-deployment instruction for this dashboard, not the LIVE/provider/model/
broker restrictions. Main remains unchanged and PR #1 remains open/draft.
No server change has been performed: this workspace has no configured SSH access,
SSH agent or connected host execution tool. The documented existing endpoint
`signalflow.duckdns.org` serves the frozen SHADOW/virtual-v1 observer, whose journal
schema is different. A mixed observer cannot adopt that journal or replace its
worker by changing a command-line flag.

Deploy this reader separately, against an explicitly selected existing native
mixed journal, using its owner UID and a verified noneditable installed release.
Keep all execution/provider credentials unavailable to the reader. Its password
must be an absolute owned regular mode-0600 file containing 24–512 visible ASCII
characters. The journal must also satisfy the reader's private ownership checks.
Neither source file is created, migrated or repaired by the observer.

After provisioning those explicit paths on the target host, the installed entry
point is:

```bash
/absolute/verified/venv/bin/python -I -m app.options.observer_cli \
  --mixed \
  --journal /absolute/private/native-mixed/journal.db \
  --population-id EXACT_EXISTING_POPULATION \
  --password-file /absolute/private/observer.password \
  --port 8790
```

This binds loopback only with access logs disabled. Retain authentication through
an existing approved SSH tunnel or separately configured HTTPS endpoint. Do not
publish plain HTTP, change the existing SHADOW proxy/worker, initialize a trader,
or run `shadow-server.sh start` as a dashboard upgrade. Reusing the old synthetic
data requires a separately scoped SHADOW presentation adapter, not invented mixed
state. A demonstration journal must be labeled fixture data, never live account data.

Before activation, retain the prior observer command/release for rollback and
confirm the selected journal/population and isolated dependency inventory. Verify
unauthenticated requests receive 401, authenticated stored reads work, mutation
requests are rejected, no source bytes change, and actual desktop/mobile screenshots
are reviewed. `/healthz` only proves process response, not worker or market health.
Rollback stops only the new reader and restores its prior route/release; it does
not alter the journal or worker. Host execution and rollback remain unexercised.

Outstanding deployment inputs: authorized host access, selected existing mixed
journal/population and its owner, and the separate private route. Authentic
provider/normalization/model/host/economic/PAPER acceptance remains open. LIVE is disabled.
