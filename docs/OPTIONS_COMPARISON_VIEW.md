# Historical comparison in the stored options dashboard

The options observer can now link an explicitly generated historical comparison
to its existing population. Current cash/position/mark evidence and historical
research results remain separate. Page reads do not run evaluation, collect data,
call models, open execution ownership or write any source.

## Materialize and link

First finish the existing native replay/export. Its `result.json` must be an
absolute, private owned regular `0600` file no larger than 16 MiB. The new installed
command validates the bundle, manifest/evidence hashes, supplied arm accounting,
SPY endpoint arithmetic and the final native source proof. It rejects an altered
net result, fee, model charge, benchmark or authority claim. Materialization is
an explicit offline operation; it does not load credentials or start a trader.

```sh
python -I -m app.options.comparison_cli \
  --result /absolute/private/replay/result.json \
  --arm D \
  --output /absolute/private/comparison.json

python -I -m app.options.observer_cli \
  --journal /absolute/private/replay/D/journal.db \
  --population-id the-exact-enrolled-D-population \
  --password-file /absolute/private/observer.password \
  --comparison-file /absolute/private/comparison.json \
  --port 8790
```

The output directory must already be owned and mode `0700`. Output creation is
exclusive, mode `0600`, and fsyncs both file and directory. A repeated invocation
does not replace the view. Use a new path for a new report and explicitly link it;
there is no automatic latest-run discovery or refresh-triggered research.
The CLI exits 0 for a created projection and 2 for sanitized unavailable input.
Creation does not imply complete arithmetic or economic acceptance.

`create_options_app` and `OptionObserver` accept the optional keyword
`comparison_file`. Omitting it retains the default unlinked state. An invalid view
shows comparison UNAVAILABLE while the independently readable account evidence
remains available. Missing evidence never becomes a zero benchmark or return.

## Read contract

The compact view is at most 256 KiB, sixty ordered session rows, and contains a
content digest. Reads reject symlinks, special files, public permissions, changed
files, malformed content and future closing boundaries. The view must match the
observer's population, account, native configuration and frozen strategy hash.
Its final native event count/hash must match the same historical prefix in the
observer's read-only SQLite snapshot. A later append is compatible; a changed,
missing or foreign historical prefix is not. The existing observer's two-second
cooperative SQL deadline, 10,000-event and response bounds still apply.

The digest and source hashes establish local content binding, not authentication
against an owner who can rewrite all inputs. Sealed-market verification is labeled
as the **stored export's claim**; the observer neither reopens market tapes nor
repeats those checks. Runtime liveness, provider authenticity, prospective
enrollment and release approval are not inferred.

## Display and uncertainty

The panel identifies the experiment, selected account and exact historical closing
boundary. It shows net equity, the independent model-off A account, SPY's compounded
session-price comparison, and the zero-return cash baseline from common initial
capital. SPY is not buy-and-hold total return. The source economic conclusion
remains INCONCLUSIVE.

Net results include observed venue fees, spread/slippage through native fill
prices, every entry and management model charge, and supplied data/host allocations.
The session table retains the individual cost roles and unknown-call counts. Model
costs use frozen configured rates; they are not invoices. Unknown data, host or
model charges stay unknown. Cumulative lines end at the first incomplete paired
session and never resume from a newly invented base. Later standalone session
values may remain visible without claiming a complete cumulative result.

The SVG chart is server-rendered, labeled for assistive technology, and uses both
color and line patterns. Exact session values and costs remain in a keyboard-
focusable scrollable table. A skip link, visible focus styles and escaped long text
support the existing responsive layout. No script or remote chart dependency is
introduced. Currency cards round for display; exact values remain in the table.
SPY chart projection is rounded to twelve decimal places after the exact offline
calculation, solely for bounded display and without execution authority.

## Acceptance boundary

This adds stored historical cost/benchmark integration and server-rendered chart
states to M4. It does not close M8: real desktop/mobile rendering, visual hierarchy,
keyboard interaction, contrast and screenshots still require a working browser.
This environment's Chromium download again returned an unusable archive. No
rendered QA is claimed. Current marks still exclude exit/data/host costs and do
not inherit a historical comparison's completeness. Authentic inputs, target-host
acceptance, overnight Swing, Scope and mixed ownership remain separate work.
Main, PR draft, LIVE-disabled state and the frozen deployment are preserved.
