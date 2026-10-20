# Deterministic Scope trading replay from common tapes

`app.options.scope_trading_replay` connects a sealed common market tape to one new,
independent **A baseline**: tape-linked watches, deterministic shared family selection,
owned approval, native order attempts, later executable fills and independent exits.
It uses the existing coordinator, watch book, virtual scheduler, venue, loss controls
and portable accounting exporter. It does not introduce another strategy or fill rule.

`ScopeTradingReplay` freezes the tape, owner limits/execution policy,
`SharedScopePolicy`, ordered `watch_actions` and optional data/host allocations.
Use `asyncio.run(run_scope_trading_replay(request, new_absolute_directory))` from an
installed wheel. This API creates local PAPER fixtures only; it starts no service
and makes no authenticated provider, model or broker calls.

## Enrollment and event order

The tape's full Scope watch policy and market limits must match the new owner;
only population/account identities can differ. Both sides require native Scope and
`shared-scope-selection-v1`. Priority must cover Degen, Scope and exactly the optional
tape-enrolled session-close Swing family, with matching native family loss policies.
Model cost-policy enrollment, AI selection and Swing carry are rejected. Old tapes,
watch-only requests and comparison runners retain their existing contracts.

Watch actions use the [sealed observation-reference contract](OPTIONS_SCOPE_MARKET_TAPE.md#tape-linked-native-watches).
Keys are unique, clocks ordered and same-time references follow sequence order
(timer-only instructions sort before referenced instructions at that instant).
The owner starts at the frozen session open; instructions must finish by close.
References are resolved without replacing source clocks, trading terms or deadlines.
A reference cannot be applied until its actual event sequence has been delivered,
even if a later event has the same timestamp as an earlier decision cycle.

At each event the existing native scheduler processes delivered executable prices,
reconciles and supervises protection before applying due watch actions and starting
a CYCLE. Each watch action reads this owner's actual current revision. SCOPE-only
observations also supply their exact nested option/SPX prices to the scheduler;
identical common/nested representations are counted once. Missing quotes stay
missing. Timer-only instructions and native order/position deadlines progress without
inventing market receipts. Native rejected watch actions retain explicit reasons
and cannot mutate their action revision.

CYCLE remains the only entry-decision event. It must supply the existing complete
shared-family input contract, including enrolled Degen histories and requested
quote coverage. Missing family data is not permission to select Scope. A native
cycle exception stops replay with an incomplete marker, rather than presenting a
halted cycle as a successful empty trading session.

## Native fills, exits and accounting

An approved attempt is not a fill. The unchanged scheduler requires a newly delivered,
fresh, executable quote with source time strictly later than order preparation,
correct limit/size and remaining liquidity. Cached, equal-source-time and unavailable
quotes cannot invent executions. Partial fills use actual whole quantities and keep
remaining exposure/reservations. Scope's fixed targets, premium protection and original
session deadline remain native, independently authoritative exits. An unfilled exit
retains exposure and withholds complete net accounting.

Each invocation creates separate venue/journal files and original capital. No cash,
settled funds, order reservation, fill or loss state is shared with another replay.
Every actual execution fee and explicit operating allocation remains in native
accounting. Missing data/host allocations remain unknown. A has no model calls;
B/C/D entry and management charges have not been substituted with free A decisions.
The runner refreshes native loss controls after final reconciliation and exports the
same stored family/global outcomes and protection used by the execution owner.

The private create-only directory retains the normalized request/hash, isolated
journals, `native.json` and `report.json`. The report includes tape/receipt bindings,
watch action results, native accounting and the export hash. Returned report data
matches its saved JSON. Native portable verification reconstructs accounting from
its typed evidence; it does not independently attest tape acquisition. Request size
is bounded to 16 MiB and 200 watch actions, with the existing tape/journal/export
bounds and a 900-second scheduler deadline. Failures leave `interrupted.json` and
no successful final report; existing directories are never reused or resumed.

`COMPLETE_DETERMINISTIC_TAPE_REPLAY` means the supplied A sequence finished. The
report retains `comparison_complete=false` and `economic_conclusion=NOT_EVALUATED`.
There is no complete A/B/C/D comparison, benchmark evaluation, authentic source
acceptance or profitability claim. B and full matched comparison export remain next, followed by continuous
watch/runtime inputs. Legacy comparison consumers and the old Scope AI adapter remain
blocked. Main stays untouched, PR #1 draft, LIVE disabled and deployment frozen.

The separate [C/D scripted response contract](OPTIONS_SCOPE_REPLAY_MODEL.md) now
provides full typed fixed-plan entry and management receipts. The separate
[native C/D tape enrollment](OPTIONS_SCOPE_MODEL_REPLAY.md) connects its scheduler,
delivered fresh admission, original deadlines, later fills and complete costs.
It does not change the model-off A contract or complete the comparison wrapper.
