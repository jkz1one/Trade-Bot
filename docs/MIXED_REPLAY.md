# Common mixed tapes and independent native replay

The separate mixed fixture contract joins the [native owner](MIXED_NATIVE_OWNER.md),
[paid entry/management](MIXED_AI.md) and [continuous runtime](MIXED_RUNTIME.md).
It consumes predeclared stock/options/Scope observations through four independent
PAPER owners and exports their native evidence without credentials or deployment.
Existing option-only and Scope-only tapes, replay adapters and exports stay frozen.
They still reject mixed inputs that they cannot consume.

## One common recorded source

`app.mixed.market_tape` defines `mixed-market-tape-v1`. The header freezes the
original experiment, declaration, exact exchange session, option sources, stock
identities/limits and family/asset priority. Optional original Swing and Scope
policies remain explicit. The source tape cannot enroll paid/native authority.

CYCLE records require the complete stock quote universe. Original daily/hourly
stock bundles and catalysts retain their own available source/receipt/creation
clocks. MARKET records contain quotes only; Scope-only records cannot conceal
stock or ordinary option inputs. The entire option/Scope portion also passes its
existing original validator. Delayed or incomplete observations remain recorded
evidence; native eligibility never treats recording as proof of tradability.

The recorder is create-only, private and bounded. Every record links the previous
hash and the seal binds the complete prefix. Up to 60 ordered sessions retain one
original declaration and common policy. Session evidence cannot overlap or move
future data into an earlier decision. Original source and approval deadlines are
never refreshed by serialization or replay.

## Exact independent roles

`app.mixed.replay.MixedComparison` declares the complete session sequence, native
account settings, watch instructions, response scripts and optional between-session
funds settlements before any account is created.

| Arm | Decision contract | Native ownership |
| --- | --- | --- |
| A | Deterministic original family/asset priority | Its own capital, journal, venue, reservations and loss history |
| B | SELECT/HOLD among complete supplied opportunities; original terms stay fixed | Its own paid attempts, fresh native approval, later fills and costs |
| C | Full entry proposals within the original family envelope | Its own paid attempts, native approval, later fills and costs |
| D | The same declared C entry responses plus MAINTAIN/TIGHTEN/EXIT_ALL | Its own management calls, actual holding and independent mandatory exits |

All account/population IDs are distinct. Capital, limits, execution fees, source
policies, risk controls and daily operating allocations must match. Paid call
budgets and entry leases match across B/C/D; C/D entry choices, geometry, usage and
delays match exactly. B cannot add geometry or a longer holding horizon. Scope and
stock choices retain their fixed original plans. Ordinary C/D option proposals
still need full native review and cannot change the original admission ceiling.

`mixed-native-series-model-v1` binds the exact adapter type, full request hash,
ordered tape hashes and response script. The adapter receives complete typed
entry/position requests, with no tape, account, venue or credential access. It
returns bounded local fixture receipts. Missing/unknown usage remains unknown;
an invalid or late proposal still retains known usage. The original process
duration and packet/approval deadlines govern virtual completion. Old replay
adapters remain rejected by the mixed owner.

## Delivered observations and actual execution

Each owner runs the existing native coordinator, governor, durable fixed child,
reconciliation, loss controls and independent protection. Tape-linked Scope watch
actions use that owner's actual current revision. The response receipt does not
approve or fill an order. Stock and Scope refresh reads return only already
delivered original observations; Scope still requires a fresh post-cost owned
admission and its original approval ceiling.

Receipts at the same clock arrive before model completion. A new order needs a
later source quote to fill; cached quotes are not replayed as liquidity. Shares
retain exact increments, source-size accounting, adverse tick/slippage and all
first-fill/per-share fees. Changing a receive clock cannot replenish source size.
Options retain whole quantities, native fill/underlying evidence and original
target, premium, time and carry protection. Partial fills remain partial native
ownership. Missing executable exits retain open exposure and incomplete accounting.

One owner persists across its declared sessions. Original capital is never funded
again, sale proceeds do not settle automatically and only declared native
FUNDS_SETTLED receipts change settled funds. Carried positions must visit their
next original enumerated session. A real same-clock opening receipt arrives
before assessing the holding; missing/later opening evidence still triggers the
ordinary native stale-input behavior. Scope does not inherit Swing carry authority.
Overnight intervals explicitly report unobserved return/drawdown as unknown.

## Portable costs and evidence

`app.mixed.replay_export` exports a fixed allowlist of native rows, not executable
SQL, filenames, keys or restore authority. Its verifier reconstructs a private
in-memory database with fixed schema definitions and validates original approvals,
actual fills, complete model receipts, native cash/reservations, stored Scope
ownership and consumed full-cost loss outcomes. Held option protection remains
native retained state; its immutable terms and lots must match actual fills.
Every attempted order and retained fill must match the complete closing snapshot,
including empty accounts. Recomputed hashes cannot hide unowned fill rows, missing
attempts, changed observations or duplicate fill identities across assets.

`app.mixed.comparison` also binds each native configuration, original cycle/input
clock, exact scripted receipt, delivered refresh, watch revision, fill quote,
settlement and immutable session prefix to the declared common tapes. Every cycle
needs a completed native receipt or a retained paid response that overlapped it. Changing an
exported summary and recomputing its hash does not bypass those checks. Keep the
independently retained bundle hash: this is evidence consistency checking, not a
broker signature or independent replay of every historical risk decision.

Every admitted entry/management charge, execution fee and explicit DATA/HOST/
OPERATING daily allocation survives export. Calendar allocations include weekends
and overnight dates exactly once. Unknown original costs stay unknown. Cash and
economic net are distinct; only a flat, resolved account with complete known costs
gets a final net result. Cross-arm net differences require complete accounts.
Unknown initial daily allocations can prevent healthy native strategy enrollment.
Such runs retain their original unknown inputs and partial native evidence, report
unavailability, and never produce a comparison or assume a zero allocation.
Optional SPY comparisons use known recorded session midpoint endpoints and label
their overnight/dividend/cost limitations. Synthetic economic conclusions remain
`INCONCLUSIVE` even when arithmetic is complete.

## Installed commands and verification

The private JSON request is a complete serialized `MixedComparison`. Every
embedded tape still needs its valid original header, event chain and seal. Use an
absolute new output directory; reruns never resume or overwrite an existing run.

```bash
python -I -W error -m app.mixed.replay_cli run \
  --request /absolute/private/mixed-request.json \
  --output /absolute/private/new-mixed-run
python -I -W error -m app.mixed.replay_cli verify \
  --bundle /absolute/private/new-mixed-run/comparison.json \
  --expected-hash INDEPENDENTLY_RETAINED_BUNDLE_HASH
```

Request/bundle files must be owner-only regular files with mode `0600`. The CLI
rejects symlinks, oversized/changing inputs and incomplete contracts. Exit status
0 means complete fixture accounting, 1 means retained incomplete accounting, and
2 means unavailable/invalid evidence. Interrupted runs retain their inputs and
native partial evidence with an explicit incomplete marker; they are not resumed.

The mixed tape/model/fill, replay, asset, combined-carry, series and CLI suites use
the [isolated installed-wheel procedure](OPTIONS_TESTING.md). The newest
[status receipt](SLICE2_STATUS.md) records broad and final-wheel checks, identity,
legacy serialization and diagnostics excluded from the proof count.

The settled strategy/engine plumbing is connected. Remaining work is final
UI/visual and authentic provider/normalization/model/host/economic/PAPER acceptance.
This slice enables no LIVE path, authenticated call, dependency change or deployment.
