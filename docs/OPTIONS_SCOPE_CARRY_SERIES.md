# Independent combined Scope/Swing carry series

`app.options.scope_carry_series` adds a separate create-only offline fixture path
for four independent combined Degen/Swing/Scope owners. Use `ScopeCarrySeries` and
`run_scope_carry_series(request, new_absolute_directory)` from an installed wheel.
It makes no authenticated provider, model or broker call and starts no service.
Existing Scope tape, model, comparison and session-series requests retain their
original versions and continue to reject combined carry.

## Frozen roles and evidence

Each session contains a `ScopeCarryComparison`: one `ScopeCarryTradingReplay` A
and three `ScopeCarryModelReplay` requests. A preserves deterministic native
family priority. B selects one supplied candidate or HOLD without replacement
geometry. C reasons over the full entry request; D has exactly C's declared entry
choices, delays, geometry and usage plus separately paid management. Accounts,
population IDs, cash, reservations, fills, budgets and loss controls remain separate.
Shared observations and matched scripts never copy another account's decisions.

The new `scope-carry-series-model-v1` enrollment freezes all ordered tape hashes,
the complete series request hash and the full script hash. Only the exact new
`ScopeCarryReplayModel`/`ScopeCarryShortlistModel` adapters can bind it. Old model
adapters and old enrollment cannot be substituted. Each owner retains its native
`shared-scope-carry-v1` and bounded Swing carry policies, original source clocks,
full typed request and result, settled charges and original admission deadlines.
Scope selection still requires delivered fresh post-cost owned admission; no
source clock, model lease, approval deadline or protection cutoff is extended.

B additionally requires `scope_carry_shortlist="scope-carry-shortlist-v1"` on its
entry policy. Its separately hashed prompt and `shared-scope-carry-shortlist-plan-v1`
schema prohibit every geometry/horizon field. The original native Swing candidate
owns its carry terms. This marker remains unavailable to ordinary native runtime
owners and legacy replay. C/D's separately versioned carry script permits a longer
proposed horizon only where native review proves original Swing carry terms.
Scope still selects the exact fixed plan with no replacement terms; Degen remains
intraday. D's management binds only the actual held family's original context.

## Session continuity and costs

The runner creates each native owner once, retains its journal/venue across
sessions, resets only delivered quote caches at the next session and never resets
capital, losses or model budgets. Later paid flat-account entry calls must retain
proven prior closed outcomes; their charges remain in full account costs.
Every session retains a native closing export.
Immutable earlier economic evidence and original order authority must remain exact.
Funds settlement requires explicit per-account receipts between sessions; no
credit or settlement date is inferred. Unfilled watch instructions remain bound
to their declared receipt sequence and original session clocks.

`gaps` must declare every exact interval from one session close to the next open.
Each gap includes explicit data and host allocations, which may be unknown. These
allocations apply separately to all four matched research accounts. Each closing
export includes cumulative session and gap costs; no overnight operation becomes
free because the tape contains only regular-session observations. Missing earlier
or gap costs remain unknown in subsequent exports. Entry and management charges,
execution fees and all explicit operating allocations remain visible.

An authorized Swing carry boundary must retain original native terms, and the
next tape must cover the next enumerated original carry session. An unfilled
intraday close stays visible as `UNRESOLVED_INTRADAY_EXPOSURE`, with its original
cutoff and unknown net result while still held. Scope never acquires an overnight
horizon. A bounded Swing holding still open after its original exit deadline is
`UNRESOLVED_CARRY_EXIT`; an expired protective order retains the native
`OPTION_EXIT_REVIEW_REQUIRED` halt. A later quote does not clear that halt, retry
the order or extend its original deadline. Accounting stays incomplete while held. Reopening observations never attest the unseen price
path or a guaranteed protective fill. The report labels held gaps
`NOT_CONTINUOUSLY_OBSERVED`; overnight return/drawdown stay absent.

## Portable comparison

`series.json` retains the complete request, every account's native closing export,
the reconstructed report and a `series_hash`. Retain that hash independently and
call `verify_scope_carry_series(bundle, expected_series_hash)`. Verification binds
exact native owner/model enrollment, immutable history, actual fills, original
protection and all allocations; modifying only a public total cannot verify.

Daily rows keep their original incomplete status when an opening or closing
holding has no supported value. Separately, `carry_period_accounting` can report
complete cash arithmetic after the final account is flat and all cumulative costs
are known. A paired final net difference is available only when all four accounts
are complete. An unknown model bill, missing operating allocation, unresolved
holding or unfilled close withholds comparison. Other known account results remain
visible. Session-only SPY endpoints are retained as diagnostics; they are not a
matched whole-period benchmark for overnight exposure. No benchmark-adjusted carry
return is invented. Economic acceptance remains `INCONCLUSIVE`.

This is fixture plumbing, not authentic provider/model/host/economic acceptance.
Remaining supported family completion and one mixed stock/options owner precede
final UI and authentic PAPER testing. LIVE stays disabled; main and the deployed
experiment remain frozen. See [testing](OPTIONS_TESTING.md) and the latest
[measured status](SLICE2_STATUS.md).
