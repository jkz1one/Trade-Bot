# Native A/B/C PAPER replay

Delivered P3 scheduler, 2026-10-11. `app.options.replay` runs a sealed common tape
through three independent native PAPER owners and automatically exports their
journals. It is a **scripted local fixture experiment**, not an authenticated AI
backtest, prospective enrollment or evidence of profitability.

The [multi-session extension](OPTIONS_REPLAY_SERIES.md), delivered 2026-10-12,
retains the same accounts and explicit settlement across ordered sessions. The
one-session API below remains compatible.

The [arm D extension](OPTIONS_MANAGED_REPLAY.md) adds optional management, four
independent accounts and stored attribution. This original A/B/C interface remains supported.

## What runs

- A uses the existing deterministic Degen candidate selection.
- B uses explicit scripted SELECT/HOLD responses through the narrow model protocol.
- C uses explicit scripted full entry geometry or HOLD through the broader protocol.

Each arm has its own clock, journal, durable local venue, capital, orders, costs and
position. They run sequentially against the same immutable recording. Their
virtual completion/fill times are independent of the order in which arms run.
The engine still approves, sizes, dispatches and supervises each position. There
are no model/provider network calls, API keys, broker writes or live activation.
Native local venue operations still use the existing bounded worker processes.

`ReplaySettings` contains a one-session manifest template, B/C `ReplayScript`s,
frozen judgment limits, full entry policy and explicit data/host cost allocations.
Each script names exact five-minute cycle keys, integer response delays, synthetic
token usage and a HOLD, SELECT, ENTER or UNKNOWN outcome. Selection refers to an
index in that request's admitted candidates, never a future tape entry. ENTER
supplies explicit condition, invalidation, target and horizon. Software binds the
proposal to the actual request and evidence, then applies the normal governor.
Script responses and usage are visibly synthetic. They are not rebound authentic
provider responses and cannot establish whether any AI adds economic value.

The runner enrolls fresh A/B/C journals and derives their exact strategy hashes
from the supplied configuration and scripts. Those hashes replace the template's
strategy hashes in `manifest.json` **before the first cycle**. They do not amend an
existing population. The original settings and full sealed tape are retained in
`admission.json`. Script/configuration changes cannot reenroll an existing owner.

## Event order and uncertainty

Only recorded CYCLE events start a five-minute opportunity. MARKET events update
the currently available prefix. While a model awaits its scripted completion,
market receipts continue; final admission uses the latest delivered option and
underlying quotes. Original packet leases and process-time limits still apply.
Known usage is charged even when a response is late, HOLD or rejected. Missing
scripts and UNKNOWN outcomes retain unknown cost and halt entry, never a free
invented judgment. Extra declared responses for opportunities that never reach a
model remain unused; the result lists actually consumed script keys.

Equal-time market receipts precede model completion. An order can fill only from a
newly delivered quote whose source time is strictly after decision/intent creation.
A quote consumed before completion is never replayed afterward. Exact identity,
entitlement, freshness, adverse slippage, fixed limit and unused whole-contract
size are checked, then independently enforced by the native venue. Partial fills
consume observed size. Each simulated arm has its own liquidity accounting; this
is not a shared funded market-impact simulation.

Working DAY orders expire at their frozen deadlines in the local fixture.
Position exit timers and delivered market changes run protection independently of
entry/model selection. Cached stale quotes cannot invent an exit. Missing exit
evidence retains exposure and produces inconclusive accounting. Settlement is
never assumed. An occupied model cycle causes an intervening slot to be recorded
as skipped in the scheduler receipt; no backdated cycle is fabricated. The paired
evaluator detects that missing native slot and withholds complete totals.

## API and installed command

`await run_replay(settings, tape, new_directory)` validates the sealed tape and
matching first-session manifest, creates a private new directory and runs all
three arms. The directory must not exist. Files are create-only, private and
fsynced. Interruptions retain admission and native evidence; there is no automatic
resume, overwrite, source restoration or promotion. Native ownership is closed
when the runner exits. Incomplete runs have no `result.json`.

The installed command is:

```bash
python -I -m app.options.replay_cli --request /absolute/private-request.json \
  --output /absolute/new-replay-directory
```

The owned mode-600 request is limited to 256 KiB and contains `settings` serialized
from `ReplaySettings`, plus `tape`, an absolute path to a sealed `TapeRecorder`
file. The [series form](OPTIONS_REPLAY_SERIES.md) uses an ordered `tapes` array
instead, with a 64 MiB combined tape bound. The directory stores admission, the derived manifest, A/B/C native fixture
journals/venues, evidence-only closing journal snapshots and `result.json`. Do not pass a deployed source directory. The
command never installs or starts a service. Each arm has a 900-second wall limit;
script delays are virtual, bounded to 600 seconds and never sleep wall time.

The result contains the automatic export bundle, source receipts, accounting
report and per-arm skipped/consumed-script keys. The CLI prints the accounting
report. Exit 0 is complete arithmetic, 1 inconclusive and 2 sanitized unavailable
input/run evidence. Neither exit 0 nor `COMPLETE_ARITHMETIC` means profitability;
the economic conclusion remains INCONCLUSIVE. The source retains explicit
`LOCAL_FIXTURE` and `SCRIPTED` attribution.

## Next bounded work

The [multi-session extension](OPTIONS_REPLAY_SERIES.md) now carries balances,
settlement and unknown history through saved native boundaries. The
[arm D extension](OPTIONS_MANAGED_REPLAY.md) now adds position reasoning and
stored decision/approval/fill attribution in P3. Authentic
provider/model acceptance, continuous options runtime, the required finished UI,
prospective collection and host/recovery acceptance remain separate gates.
The deployed experiment stays frozen and LIVE disabled. Current measured proof is
in [status](SLICE2_STATUS.md); [source of truth](SOURCE_OF_TRUTH.md) owns delivery order.
