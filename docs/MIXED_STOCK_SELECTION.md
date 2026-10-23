# Original stock sources and one shared native choice

The explicit `native-stock-selection-v1` coordinator enrollment now connects long
shares to the same Degen/Swing/Scope owner, journal, cash, order lock and loss
history. `DegenFrame.stocks` supplies one exact stock quote per frozen symbol and,
when enrolled, one original Swing source bundle plus catalyst evidence. The stock
universe, family order and stock-versus-option order are frozen at creation. No
provider calls, paid model contract, second funded account or LIVE path is added.

## Original source rules

Degen candidates are recomputed from the existing completed five-minute and
fifteen-minute scanner. Only confirmed bullish signals can propose long shares.
The stock adaptation anchors a fixed 1R/2R/3R ladder to the original completed
signal close and scanner invalidation; a later quote cannot move that anchor.
The setup's original structural reference remains in its hashed source evidence.
Native stock execution uses T1 as its existing full-position target. All three
objectives are retained in the candidate and stored outcome. This is explicit
new stock-cohort behavior; frozen option baselines and model-plan behavior remain
unchanged. The risk-ladder arithmetic follows the pinned SignalFlow
[`_targets` source](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/setup_engine.py).

Swing sources freeze the actual instrument, completed daily/hourly evidence,
creation time, target exchange session and optional original carry exit session.
The new stock source boundary requires 56–260 declared daily bars. Every bar must
match consecutive actual exchange sessions, source clocks and positive observed
volume; hourly families require exact open-anchored hours, including short final
intervals. The whole bundle must be known before the target session opens.

Each enrolled family is enumerated from that same original bundle: daily breakout,
daily base, 8 EMA, 21 EMA, 50 SMA, previous-week/month high or low, and weekly open.
The existing base/MA/level arithmetic now also accepts an explicit source direction,
so shares reuse the completed rules without fabricating an option contract. Original
option callers keep their direction and behavior. Bearish-only low-level families
remain diagnostic rejections for long shares; they cannot create stock shorts.
Swing geometry retains the original reference, invalidation and fixed risk ladder.
Current completed break/hold, quote-side break/chase and catalyst checks still apply.

Original Swing bundles lock atomically by target session and symbol. A replacement
bundle cannot rewrite that root. Completed-bar invalidation or T1 consumption, and
fresh executable bid observations of those levels, retire each affected family
permanently for that root. A quote rebound or restart cannot erase the terminal.
An ask touching T1 alone does not establish executable target consumption. Valid
completed bars can retire a source even when its current quote or catalyst blocks
entry. Unknown/foreign/stale quote evidence cannot invent a terminal.

Optional [stock carry](MIXED_STOCK_CARRY.md) derives its exact calendar path and
original catalyst coverage from the locked source's declared exit session. Its
source hash is retained through native approval, DAY entry, actual fills and held
protection. No current quote or model silently changes the horizon.

## One admitted selection and native enforcement

Stock candidates first pass native admission against the common complete cash and
cost history, account snapshot/revision, session and global/family loss state.
Stored evidence retains that full original admission. Stocks, admitted native
options and an eligible native Scope packet then enter one deterministic receipt,
ordered by the frozen family and asset priorities. Existing order within each
family/asset is retained. Scope and option Swing family priorities must agree with
the mixed policy. The bounded shortlist permits at most 64 distinct choices.

The existing coordinator selects exactly one candidate and dispatches through its
native path. Proposal, selection, approval, attempt and actual fill remain distinct.
Both stock and option entry guards require the selected asset and exact supplied
proposal. Stock preparation and stored verification rebuild the original candidate
and admission from the retained source/frame, policy, cash history and account.
The selected quantity and price are ceilings, and later preparation cannot extend
the original selected approval deadline. Dispatch still requires fresh native
admission and retains the original prepared intent. Fresh Swing break/chase and
sticky retirement are checked again before attempt.

Held stock cycles bypass candidate discovery and invoke independent native stock
protection with the exact supplied held quote. Missing evidence blocks executable
supervision; it does not manufacture a new entry. Pending stock orders block other
entries. Restart retains original choices, sources, terminals and attempts under
the same lifetime owner and restore fence. Completed stock outcomes and consumed
loss records now retain setup-family attribution, selected candidate, selection
hash and all original objectives, alongside the existing full execution/operating
costs and unknowns. The stored coordinator report identifies mixed fixture mode.

## Boundaries and remaining work

Enrollment is create-only on an untraded native mixed owner. Existing stock orders
or decisions prevent later strategy adoption. Old coordinator populations reject
stock frames, and existing option/Scope market tapes and runtime packets explicitly
reject stock inputs. Paid mixed entry/management, continuous mixed runtime and
mixed A/B/C/D replay/export remain guarded until their full contracts exist.
Absent stock fields are omitted, preserving old frame serialization.

`test_mixed_selection.py` covers native stock/option/Scope competition, actual fills,
held protection, all Swing source families, immutable roots, retirement/restart,
source-bound carry, original deadlines, tampering, outcome attribution and old
consumer rejection. See [status](SLICE2_STATUS.md) for the final installed-wheel
proof and [testing](OPTIONS_TESTING.md) for isolation requirements.

Continue with complete mixed paid entry/management requests/results, usage charges,
fresh post-cost native admission and attribution. Then bind explicit continuous
mixed inputs/session recovery and common tapes with four independent native
A/B/C/D replay/export owners. Final UI/visual and authentic provider/model/host/PAPER
acceptance follow that plumbing. LIVE stays disabled; deployment remains frozen.
