# Native options comparison export

Delivered P3 first-session export, 2026-10-11. `app.options.evaluation_export`
connects native Degen PAPER journals to the [paired evaluator](OPTIONS_EVALUATION.md)
and [sealed common tape](OPTIONS_MARKET_TAPE.md). It does not run strategies, call
a model/provider, simulate a fill or open execution authority. The independently
clocked [A/B/C replay runner](OPTIONS_REPLAY.md) uses this exporter; its
[multi-session extension](OPTIONS_REPLAY_SERIES.md) adds ordered closing snapshots.

The [arm D extension](OPTIONS_MANAGED_REPLAY.md) adds optional four-arm export,
full managed-decision lineage and role-separated model cost evidence. Existing
three-arm requests remain supported.

## Scope and API

`export_arm(journal, definition, session, tape, data_cost=None, host_cost=None)`
returns an `ArmSession` and a source receipt. `export_comparison(manifest, tape,
sources)` reads all three A/B/C journals and returns an evaluator-ready `bundle`,
`source_proof` receipts and the recorded-content `report`.

`sources` maps each arm to an existing absolute `journal` path and optional explicit
`data_cost` / `host_cost`. Missing allocations remain unknown, never zero. All three
definitions must have distinct frozen population identities and match their actual
native configuration. A is deterministic, B has the narrow selector, and C has the
full entry-model configuration. The stored setup and selection must match the tape.

`strategy_hash(stored_strategy)` canonicalizes the native frozen strategy while
excluding the private model-key path. That digest must match the arm's predeclared
definition. Excluding a credential location does not remove model configuration,
prompt/schema identity, setup, selection or full entry policy from the binding.
No key is read or exported. The helper does not prove when enrollment occurred.

The compatible `export_comparison` API supports one first session. The new
`export_series` API reads a saved cumulative journal at each session close and
links prior audit/history and opening balances without resetting capital. See
[the multi-session contract](OPTIONS_REPLAY_SERIES.md) for provenance, settlement,
unknown history and historical-correction limits.

## Read and consistency checks

Each source uses the existing observer's private mode-0600, current-owner bounded
database check, read-only SQLite URI, query-only transaction and two-second query
deadline. The reader never constructs an engine, opens the venue or attaches the
paired authority database. A copied journal without execution authority can still
supply evidence. Missing files are not created, and source bytes are unchanged.

The export checks:

- Exact native schema, limits, policy, population and A/B/C strategy binding.
- Contiguous retained audit sequence and one matching event for each model
  admission, known usage receipt, order attempt and scheduler start/completion.
- Model identity, receipt ID, stored token usage and exact cost recomputed from
  the frozen rates. Known HOLD charges remain included.
- Complete order observations and matching fill-table entries. Orders inherit
  their stored preparation/attempt times; model-funded entries use the retained
  usage-completion time as their decision-completion boundary.
- Actual stored input frames and their hashes, real cycle outcomes, missing slots,
  incomplete cycles and known completion across a five-minute deadline.
- Closing cash, settled cash and owned position against the stored snapshot.
  Complete closing evidence requires a complete snapshot at close through five
  seconds afterward, without unresolved reconciliation issues or foreign exposure.
  Snapshot/order/receipt coverage discrepancies keep closing evidence incomplete.

The source receipt contains its arm, audit revision, strategy hash and export
content hash. It does not contain filesystem paths, credentials or execution
authority. Retained source content and revisions are not an independent witness
against an owner rewriting a database.

Structural contradictions fail export. Legitimate missing/unknown evidence remains
in the exported row: an interrupted cycle is UNKNOWN; an admitted call without a
usage receipt has unknown cost; missing allocation stays null. No absent slot,
model charge, fill, close or settlement is invented. The evaluator then replays
cash/ownership and checks every session's common recorded inputs and quote timing.
Its economic conclusion remains INCONCLUSIVE in all cases.

Bounds per source: 64 MiB database, 256 KiB decoded JSON record, 10,000 audit events,
200 orders/receipts, 1,000 fill rows and 100 calls/cycles. Exported bundles retain
the evaluator's 16 MiB cap. Hitting a bound is unavailable evidence, not permission
to paginate away or silently omit relevant records.

## Installed command

`python -I -m app.options.evaluation_export_cli --request PATH` reads a private
mode-0600 bounded JSON `ExportRequest`. It contains the exact `EvaluationManifest`,
existing tape path, and three `ExportSource` records with arm, journal and cost
allocations. There is no production request artifact or deployment command yet.
The [replay runner](OPTIONS_REPLAY.md) constructs these from its frozen experiment configuration.

The command prints a JSON envelope containing `bundle`, `source_proof` and `report`.
The nested `bundle` is the evaluator's input format; the whole envelope is not an
`EvaluationBundle`. No output file is written automatically. Exit 0 means complete
arithmetic, 1 inconclusive and 2 unavailable/invalid source; errors omit private
paths and raw database/provider content.

## Remaining work

The exporter tests run native A/B/C coordinators with mocked responses and the
real local fixture venue. The separate [first-session scheduler](OPTIONS_REPLAY.md)
now connects independent clocks, scripted completion timing, positions and
subsequent tape-driven fills to this exporter. Neither establishes an authenticated
AI experiment. The [multi-session extension](OPTIONS_REPLAY_SERIES.md) now handles
opening state and explicit funds settlement; authentic prospective collection
and historical-correction/revaluation remain separate work.

Position reasoning and stored observer attribution are implemented. Authentic data/model acceptance,
continuous options runtime/UI and host/recovery gates remain in the
[source of truth](SOURCE_OF_TRUTH.md). The deployed experiment remains frozen;
LIVE is disabled. Latest measured test proof is in [status](SLICE2_STATUS.md).
