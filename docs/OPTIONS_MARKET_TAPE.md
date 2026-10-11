# Shared options market tape

Delivered P3 recording and market-stage replay, 2026-10-11. This is a separate
**LOCAL_FIXTURE** evidence artifact. No provider, model, broker or execution owner
is opened. Existing populations, coordinators and the deployed experiment are
unchanged. The API takes already-normalized supplied frames; it is not yet wired
to authenticated collection or continuous options PAPER operation.

## Recording contract

`app.options.market_tape.TapeHeader` freezes one complete XNYS session, experiment
ID, declared enrollment time, limits, Degen setup and contract selection policy.
`TapeRecorder(path, header)` creates a new mode-0600 file in an existing owned
mode-0700 directory. It never replaces a file, changes an existing directory's
permissions, reopens a prior capture or resumes an interrupted recording.

The append API is `append(frame, recorded_at=at, kind="CYCLE")`. `frame` is the
existing `DegenFrame`. `CYCLE` records the common five-minute strategy input,
including an empty frame for missing data. `MARKET` records quote-only observations
between decisions, for subsequent fill evidence and SPY endpoints. Inventory and
history are retained only in cycle frames. The recording does not initiate reads
or choose contracts independently for any arm.

Each event has a contiguous sequence, previous-record hash and nonregressing
recorded time. Duplicate cycle slots and duplicate identities within a frame are
rejected. Source and universe must match the header; SPY underlying quotes are
allowed for the benchmark even in a QQQ-only setup. Quotes, history and nested
inventory metadata must have source time no later than receipt time and receipt
time no later than recording. History bars must already be completed at the
history's source/receipt time. Delayed, incomplete or stale supplied evidence can
be retained as such; the existing strategy/governor still rejects unusable data.

Cycle events fall inside the regular session. Quote-only events may arrive through
five seconds after close to retain a closing benchmark observation. A later-arriving
quote cannot retrospectively justify a fill that occurred before it was recorded.

Each successful append is fsynced before returning. A partial write or sync error
poisons the writer and prevents further appends/sealing. The context manager closes
the file without adding a seal. Only explicit `seal()` writes the event count and
final header/chain hashes, syncs and closes the recorder. Closing, sealing again,
appending after sealing and reopening the same path cannot silently change evidence.
An interruption without a complete seal leaves a retained, unusable prefix; there
is no repair, truncation, deletion or automatic retry operation.

The format is bounded JSON lines: at most 4,096 events, 256 KiB per line and 32 MiB
per artifact. The writer reserves seal capacity. Its final seal digest is the
`EvaluationSession.tape_hash`. `load_tape(path)` reads existing private regular
files only, rejects final symlinks/FIFOs/oversize/truncated/changing files, checks
every sequence/hash/time and returns a validated `RecordedTape`. No journal,
execution authority file or credential is needed to read it.

This is an append-only application contract and content-integrity chain, not
hardware immutability or independent retention. The host owner can replace both
evidence and claimed hashes. Header `declared_at`, recording timestamps and source
labels remain supplied assertions. The final tape hash is known only after capture;
binding it later does **not** prove pre-outcome experiment enrollment. A prospective
enrollment witness and independent off-host retention remain separate work.

## Replay and evaluation

`RecordedTape.available(at)` exposes only events recorded by the requested instant.
`replay_shortlist(tape, cycle_key, as_of=at)` reruns the existing `scan_degen` and
`plan_contract_reads` against that exact recorded cycle, at its original recorded
time. It does not borrow a later history or current option chain. Missing history
or inventory remains explicit. The output includes scans, contract plans, missing
inputs and frame hash, with execution authority and LIVE both false.

This is the common market stage only. It does not size a position, perform account
admission, call either model, choose the A/B/C final action, simulate orders, manage
positions or generate independent portfolio ledgers. Those arms still need their
own resulting balances, reservations, model receipts and management state. Source
evidence cannot make one shared portfolio a valid strategy-return comparison.

`evaluate(bundle, tapes=(...))` adds mandatory recorded-content checks for every
declared session. It verifies exact experiment/session/limits/tape bindings, all
regular five-minute cycle slots and each arm's cycle frame hashes. Model attempts
and entry decisions cannot predate the recorded cycle input. Every supplied fill
quote must appear in the tape by its fill time; the existing evaluator separately
requires its source time strictly after decision completion and validates price,
size, fees and order lifetime. Both SPY boundary quotes must be present verbatim
in the normalized evidence, using canonical money/timestamp hashes.

Missing tapes, slots, matching quotes or valid timing add explicit session reasons,
retain the planned denominator and suppress paired/aggregate comparison totals.
Invalid seals or forged typed copies fail validation. Duplicate and unenrolled
tapes are rejected. Limits are 60 tapes and 64 MiB combined normalized evidence.

The installed evaluator CLI accepts repeated optional `--tape PATH` arguments
alongside `--bundle PATH`. It reads only existing artifacts. No recorder command
collects data or creates a production bundle yet. Exit codes retain the original
meaning: 0 complete arithmetic, 1 inconclusive, 2 unavailable/invalid source.

Reports distinguish `SUPPLIED_HASHES_ONLY` from `SEALED_LOCAL_FIXTURE_TAPES` and
include `recorded_market_verified`. That flag means the supplied market content
passed these binding/availability checks. It does not verify the provider, actual
strategy execution, omitted model calls, statistical significance or profitability.
The original no-tape accounting API remains compatible; both modes always report
the economic conclusion as INCONCLUSIVE.

## Next integration

[Native first-session A/B/C journal export](OPTIONS_EVALUATION_EXPORT.md) now
connects stored orders, fills, calls and cycles to this tape and the evaluator.
The next P3 slice is the independently clocked strategy/portfolio replay runner
and explicit multi-session state, with exact arm versions bound to their decisions. Then add position-management reasoning and stored
observer attribution. Authenticated normalized collection, prospective enrollment,
runtime/UI, independent retention and host acceptance remain open. Tests and wheel
proof are recorded in [status](SLICE2_STATUS.md); the [source of truth](SOURCE_OF_TRUTH.md)
owns the remaining delivery order. LIVE remains disabled.
