# Common Scope market observations

`TapeHeader.scope` explicitly enrolls `ScopeTapePolicy(version="scope-market-inputs-v1",
watch=..., session=...)`. The full watch/source policy and reviewed index session,
including entry cutoff and protection deadlines, are part of the header hash.
The index session must match the common XNYS session. Provider, option source and
SPX universe must match the owner's declared market limits. This is source evidence,
not owner enrollment, a called watch, an admission or permission to trade.

Omitting Scope preserves historical header/frame serialization and the original
tape digests. Existing Degen/Swing tapes and independent replay behavior remain
unchanged. Scope input without enrollment is rejected, including input carried in
an otherwise ordinary `DegenFrame`. There is no implicit family adoption.

## Record and inspect

`CYCLE` can include `DegenFrame.scope` beside ordinary Degen/Swing evidence.
`SCOPE` records only that nested `ScopeCycleInput`, allowing separate observations
between five-minute cycles without fabricating a new decision slot. It accepts no
ordinary histories, inventories, quotes, underlyings or Swing payload. `MARKET`
remains quote-only and rejects nested Scope data. Enrolled MARKET events may retain
exact same-day SPXW quotes and SPX underlying quotes, including protective prices
after the entry window. Events retain the existing session and capacity bounds.

Recording and loading validate all supplied Scope source/receipt clocks, completed
SPX/SPY/QQQ bars, coverage identities, metadata, quote/Greek evidence, context and
completed prior-session evidence. The expected-move expiry must match the session.
SPXW identity is exact; AM SPX, another provider or another expiry is rejected.
A supplied session cannot replace the frozen calendar evidence or deadlines.
Common and nested representations of the same quote/underlying must agree.
The global eight-contract bound includes nested Scope quotes.

Missing, stale, incomplete, unavailable or semantically blocked evidence can still
be recorded when its identity and observation clocks are valid. Valid-through,
contract expiry and session deadlines are future validity bounds, not future
received observations. A sealed tape is not proof that a source was authentic.
The original private create-only files, hash chain, fsync, size bounds and
interrupted-prefix rejection remain in force.

Use `app.options.scope_market_tape.replay_scope_context(tape, sequence, as_of=...)`
to recompute one exact visible Scope observation through the existing context
scanner. It uses the event's original recorded time and returns the complete scan,
play key and input/policy/event/tape hashes. Later observations cannot repair an
earlier event, and an event recorded after `as_of` cannot be selected. Diagnostics
never create a watch, change account revision, refresh an admission or claim a fill.
Both execution authority and LIVE remain false. A series retains the same watch
policy and Scope enrollment, with a separately frozen session for each day.

## Tape-linked native watches

`ScopeExecutionReplay.scope_tape` optionally enrolls a sealed common tape in a
new create-only native watch replay. Supply `ScopeTapeWatchAction` entries in
`steps`, each with its version (`scope-tape-watch-action-v1`), unique key, kind,
action time, play key and exact event sequence. Only CALL supplies a locked choice.
The existing native replay API and installed module execute the request:

```python
from app.options.scope_execution_replay import run_scope_execution_replay

report = run_scope_execution_replay(request, new_absolute_directory)
```

The request must start at the frozen session open and match the complete tape watch
policy and market limits. Population/account identities may differ for independent
owners. Execution policy, initial capital and operating allocations remain explicit
owner inputs; this mode is not a matched-arm comparison manifest. Shared coordinator
arbitration and mixed raw/native steps are rejected before output creation. Omitting
`scope_tape` preserves the existing native replay serialization and behavior.

CALL, OBSERVE_ARMING, REVIEW_ADMISSION, ADVANCE, NEUTRALIZE and OBSERVE_QUOTE use
the existing native watch methods. A reference must identify visible nested Scope
evidence for the exact play. Source timestamps, the original session, contract and
context are copied unchanged from that observation. An action may occur later, but
cannot refresh the evidence by changing its clocks; native freshness/deadline checks
still apply. Future, missing and non-Scope event references are rejected. A null
sequence deliberately supplies no evidence for arming/admission/quote observation or
a timer-only advance. CALL and NEUTRALIZE require recorded evidence. Completed-bar
advance/reset takes only the recorded frame; quote observation takes only its exact
SPX quote. No account, revision, admission, quantity, fill or replacement terms can
be supplied through an action.

Each invocation creates its own venue and execution journal, reconciles/supervises
at the action clock and reads that owner's current revision before applying the
watch operation. Funding, family/global risk and loss state remain native account
inputs. Four independent owner fixtures prove distinct admissions and exports from
the same tape, while a funding-constrained owner rejects an otherwise admitted
opportunity. This does not implement A/B/C/D model roles. Native journals can reopen
with the same policies without resetting original watch terms. The replay runner
itself remains create-only and never resumes an existing directory.

Saved actions retain the instruction hash, tape/policy/event/input hashes, original
recorded time, resolved native-step hash, actual expected revision and complete native
receipt or rejection. An expected rejection must leave the action revision unchanged;
unexpected mutation stops the run with an interruption marker. `inputs.json` freezes
the normalized tape and instructions. The existing 16 MiB request and 200-step bounds
still apply. `native.json` retains the separate portable native accounting export,
including explicit operating allocations and unknown costs. Its verifier validates
native accounting; it does not independently attest the tape or its acquisition.

The report says `COMPLETE_TAPE_WATCH_REPLAY`, `comparison_complete=false` and
`economic_conclusion=NOT_EVALUATED`. Complete watch processing or flat-account cost
arithmetic is not a trading return. No model attempt, order, fill, funds transfer or
loss reset is generated by this mode, and the runner checks that its native trading
tables remain empty. Existing native execution fixtures still exercise actual fills,
fees and loss controls separately. Authentic market/model evidence remains open.

## Explicit remaining replay boundary

Common Scope observations, diagnostic reproduction and independent native watch
lifecycles are fixture verified. The separate [deterministic A baseline](OPTIONS_SCOPE_TRADING_REPLAY.md)
now connects native shared selection, later fills, independent exits and full-cost
accounting. Full Scope A/B/C/D trading comparison is
**not yet implemented**. The
legacy shortlist, native replay scheduler and native comparison exporter reject
enrolled Scope tapes explicitly. Replay rejection happens before creating its
output directory or accounts. Recorded evaluation reports
`SCOPE_TAPE_COMPARISON_NOT_SUPPORTED`, withholding comparison totals instead of
silently treating the tape as a Degen/Swing experiment. This restriction also
applies to an enrolled Scope tape with no Scope observations.

The shared Scope AI restriction on the old replay-model adapter remains intact.
The next slice must connect these watch lifecycles to A/B/C/D role-specific model
contracts, fresh post-cost Scope admissions, original
account revisions and approval deadlines, later actual fills, management and
portable full-cost attribution. Watch actions and account-specific admission
receipts cannot be copied from one arm into another. Every entry/management charge,
fee and explicit operating allocation remains required; unknown stays unknown.
Continuous watch/runtime input follows that replay integration. Combined carry,
remaining families, mixed stock/options and final UI/authentic-data acceptance
remain open. No strategy decision is reopened by the market format.

Run `test_option_scope_market_tape.py`, `test_option_scope_tape_boundaries.py` and
`test_option_scope_tape_watch.py`
with the noneditable installed-wheel procedure
in [testing](OPTIONS_TESTING.md), alongside market-tape, independent/shared/managed
replay, multi-session and native-export regressions. [Status](SLICE2_STATUS.md)
records the reproduced old boundary and exact proof. No provider/model/broker
request, dependency change, deployment or LIVE activation is involved.

The boundary suite additionally checks every nested source clock, quote-receipt
Greek availability, common/nested quote capacity, full historical tape hashes,
all unsupported account consumers (including empty enrolled tapes) and the unchanged
old replay-model restriction. These are acceptance checks for this market-input
contract; they do not enable independent Scope account replay.
