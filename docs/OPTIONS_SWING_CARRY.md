# Swing overnight evidence preflight

The next-session Swing owner currently closes positions in the entry session.
This slice supplies the missing **overnight evidence contract**, not permission to
hold overnight. `app.options.swing_carry` independently reconstructs a proposed
carry window, existing setup/contract gates and current fee-inclusive admission.
It performs no journal writes, model/provider calls, reservations or orders.

Every result has `authority=false` and the execution blocker
`SWING_OVERNIGHT_EXECUTION_NOT_ENROLLED`, even when `evidence_status=READY`.
`SwingPolicy.holding_policy` still accepts only `SESSION_CLOSE`; a preflight report
cannot extend a native position, order or model horizon. Scope's supported native
execution/loss integration remains closed as documented separately.

## Inputs and reviewed boundaries

`SwingCarryRequest` contains a frozen research `SwingCarryPolicy`, existing Swing,
completed-structure, contract-selection, execution and account-limit policies,
explicit observation time and proposed exit session. It includes the original
pre-open seed/contract/first target, daily and intraday evidence, observed contract
metadata, catalyst evidence, current quotes and supplied account truth. A retained
terminal can also be supplied. These are offline inputs, not proof of authoritative
provider capture, native journal ownership or the absence of earlier breaches.

The carry policy requires explicit maximum exchange-session and calendar-day spans,
minutes before exit-session close, and a whole exchange-session expiry buffer.
The numeric schema bounds limit resource use; they are not recommended strategies,
approved LIVE limits or automatically enrolled settings. There are no inferred
carry-policy defaults. The example uses synthetic research values only.

- The exit date must be an exact later XNYS session, inside both declared spans.
  Holidays and weekends are omitted from the session count but remain in elapsed
  calendar days. DST and early closes come from the installed exchange calendar.
  Invalid dates never roll forward automatically; unavailable calendar coverage
  remains blocked.
- The proposed deadline is the actual final close minus the declared exit buffer.
  A minimum whole exchange-session buffer before expiry and the earlier exact
  contract trading instant/owner expiry guard both apply. A failed buffer rejects
  the requested horizon; it does not silently shorten or substitute a contract.
- Fresh, complete, REALTIME catalyst evidence must say CLEAR for the exact symbol
  and configured source, and extend through the entire proposed deadline. Evidence
  clearing only today's close cannot justify carry. Missing future coverage is
  never inferred from a calendar or an ETF label.
- The existing completed daily/intraday scanner, v3 original-target lifecycle,
  current directional break/chase check, exact contract read plan, observed delta,
  liquidity and current quote/account governor are recomputed. Retained or newly
  observed terminal evidence blocks the review. This reconstructs supplied
  observations, not an unobserved continuous price path.
- The common governor retains independent account/population identity, settled
  funds, existing reservations/positions, unknown budgets, full-premium limits,
  adverse slippage and all execution fees. Like native entry sizing, preflight
  reserves an exit-order fee **per contract**. Supplied available loss budgets must
  already include every actual entry and management charge. Preflight does not
  calculate model bills, predict future expenses or turn unknown costs into zero.
  It reports no net profit or overnight performance.

The nested `admission` is a current-session diagnostic and can be approved even
when another preflight gate blocks. Its existing short expiry never extends to
the future carry deadline. Use the top-level reasons/status for evidence review;
neither level grants execution authority. Unknown future liquidity or overnight
gap losses are not estimated away, and a stop is not a guaranteed loss bound.

## Reproduction and portable review

The Python API is `review_swing_carry(request)`. `export_swing_carry(request)` retains
the typed request and complete recomputed report, including policy/seed/request
hashes, actual sessions, proposed deadline, scan, read plan and admission.
`verify_swing_carry_export(value, expected_request_hash=...)` requires an independently
retained request hash and reproduces every field. A changed account, fee, date,
status, authority flag or input fails verification. It authenticates neither a
provider nor the person supplying the inputs. It restores no native state.

The CLI accepts bounded JSON (2 MiB), rejects duplicate fields and creates an
exclusive private output file. It never overwrites an existing export. A valid
BLOCKED evidence report is still a successfully generated report; inspect the
printed status/reasons. Malformed input, mismatched verification or output errors
return exit code 2.

Synthetic complete input:
[options-swing-carry-preflight.json](../examples/options-swing-carry-preflight.json).
Run with an installed wheel, replacing paths with absolute paths on your machine:

```bash
python -I -m app.options.swing_carry review \
  /absolute/options-swing-carry-preflight.json /absolute/new-carry-review.json
python -I -m app.options.swing_carry verify \
  /absolute/new-carry-review.json --request-hash RETAINED_REQUEST_HASH
```

Retain the hash printed by the original review separately before transporting the
export. The fixture evaluates its explicit historical `at`, never the current wall
clock. All quoted data is synthetic. No credentials or broker setup are required.

## What remains before overnight execution

This closes calendar/coverage preflight, not the overnight holding lifecycle.
The next integration must freeze eligible carry terms in the same shared owner,
bind them to exact entry decisions and fills, preserve tighter protections through
session rollover/restart, and handle missing overnight/reopening observations
without inventing fills. DAY-order expiration, uncertain attempts, expiry/exercise
and unexpected exposure retain separate native reconciliation boundaries. Held
model context and horizons must explicitly support carry before an AI can request
it. Independent multi-session replay/export must retain open exposure, settlement,
loss controls and every entry/management/data/host cost. Existing session-close
cohorts cannot migrate or acquire carry through this preflight.

The pinned SignalFlow next-session promotion and contract-selection documents were
reread at `f9eaf2c1b5d13dca287ee7138126883065b00395`. They preserve exact contract,
completed history, current catalyst/chase and terminal candidate rules; they do
not grant this repository an overnight execution policy. This is an explicit local
research preflight, not a claim of a replicated SignalFlow holding strategy.
[Existing shared owner](OPTIONS_SHARED_STRATEGIES.md) and
[latest installed evidence](SLICE2_STATUS.md) retain the broader boundaries.
