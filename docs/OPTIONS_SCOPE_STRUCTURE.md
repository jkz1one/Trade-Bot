# Scope completed structure and confirmation

`app.options.scope_structure.scan_scope_structure(frame, policy, now=...)`
extends the [Scope preflight](OPTIONS_SCOPE_PREFLIGHT.md) with deterministic
SPX price structure, SPY/QQQ directional confirmation and exact-contract
reachability diagnostics. It is a pure supplied-evidence calculation with false
trade/LIVE authority. It creates no candidate, proposal, admission, account,
model charge, order or execution owner.

This is **fixture-verified structure**, not complete Scope acceptance or a new
runtime family enrollment. Existing Degen/Swing cohorts, independent accounts,
cost accounting and the deployed experiment remain unchanged.

## Evidence and calculation

The scanner revalidates the complete input and policy and reruns preflight at the
evaluation clock. All nine required coverage groups, explicit index session,
current complete SPX/SPY/QQQ histories and exact same-day SPXW quote/metadata are
still required. A coverage failure returns no pattern observations and retains
the full preflight result with its subject-specific blockers.

Two versioned payload bindings connect coverage attestations to actual inputs:

- `technical_structure`: `scope-technical-payload-v1` and the exact SPX history.
- `cross_market_agreement`: `scope-confirmation-payload-v1` and the three exact
  histories in SPX, SPY, QQQ order.

`structure_payload_hashes(frame)` exposes these deterministic hashes for a
normalized publisher. The scanner recomputes them; unrelated payload references
or modified histories block. Attestations must have received the histories and
must cover their latest completed bars. Hashes establish content binding, not
provider authenticity, and cannot replace an immutable collector/journal history.
The other seven coverage payloads still await their semantic evaluators.

At least five completed SPX five-minute bars are required. The first three form
the opening range. The scanner uses actual supplied session boundaries, not a
weekday or hard-coded UTC session. SPX VWAP uses every completed bar's typical
price `(high + low + close) / 3`, weighted by its supplied volume. **Every SPX bar
needs positive volume.** Zero or absent usable volume blocks; rows are not skipped
and price-only averages are not substituted. This is a material provider gate for
an index feed, whose available fields have not been accepted here.

Policy requires explicit target-R multiples, pullback touch bounds, compression
fraction, directional-confirmation fraction and material-conflict fraction. Tests
exercise the pinned research baselines, including 1.5R/2.5R targets and fractional
confirmation/conflict bounds of `0.0002`/`0.0005` (0.02%/0.05%). No default adopts
those values for a live account. The entire nested preflight and structure policy
is bound into the scan hash.

## Delivered patterns

Every scan with usable evidence reports each pattern in both CALL and PUT
directions as `WATCHING`, `BLOCKED` or `DETECTED`, retaining reasons and geometry
where present. `DETECTED` means the implemented structural checks pass; it is not
an entry recommendation or an approval.

| Pattern | Completed-bar condition |
| --- | --- |
| Opening-range break/hold | Two closes accept beyond the opening boundary; invalidation uses VWAP and recent extremes. |
| VWAP reclaim continuation | Completed cross, continued acceptance and aligned four-bar slope. |
| Trend pullback continuation | Established side of VWAP, bounded touch and renewed directional close. |
| Compression expansion | Recent range is bounded relative to the actual opening range, then breaks with a completed close. |
| Failed reversal continuation | A countertrend VWAP cross fails, acceptance returns and the trend resumes. |
| Failed-break reversal | Breach, a separate neutral close, then a fresh completed follow-through close. The initial failure alone remains blocked. |
| Opening-drive failure | Opening-side structure loses VWAP and range midpoint with opposing slope. |
| VWAP rejection reversal | Completed test and rejection of VWAP, directional candle and aligned slope. |
| Trap reversal | Explicit breach, neutral reset and separate fresh follow-through. |

These adapt the nine price-derived modules in pinned SignalFlow
[`scope_wizard.py`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard.py)
at `f9eaf2c1b5d13dca287ee7138126883065b00395`, within the approved
[V2 playbook](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/SCOPE_WIZARD_SPXW_PLAYBOOK_V2.md).
No reference base score, confidence probability, premium tier or quantity is
copied. The adaptation requires complete volume-backed history, uses the actual
opening width without an artificial minimum, requires fresh follow-through for
failed-break reversal, and blocks already-consumed second objectives.

The local failed-break/trap sequence proves only what these supplied bars show.
It does not prove an account's previous play was invalidated, a durable neutral
state was recorded, or all reversal/flip/cooldown controls passed. Every family
still needs the common durable play-state gate before candidate admission.

## Confirmation and contract path

Each market's change is the final completed close divided by that session's first
open, minus one. At least one of SPY/QQQ must strictly exceed the frozen directional
confirmation bound; neither may exceed the opposing material-conflict bound.
Equality is handled explicitly and tested. SPX retains setup authority: confirmation
cannot create a missing SPX pattern.

The supplied contract must have the detected direction's right. Its strike must
be reachable by the second structural objective, matching the pinned contract-path
rule. A strike exactly on the objective is allowed; one beyond it blocks. If SPX
has already reached that objective, the old target path cannot be reused. No
alternate instrument, expiry or underlying is selected.

All calculations use Decimal in an isolated arithmetic context. Displayed derived
values use at most twelve decimal places; targets round toward the entry so
rounding cannot extend reachability. Invalid or unrepresentable geometry blocks
rather than emitting a partial result. These are historical structural references,
not current executable entry prices, quantity limits or approval ceilings.

## Remaining integration

Six context-derived modules remain: prior-level break/retest, prior-level rejection,
dealer-level acceptance/rejection, implied-move boundary rejection and exhaustion
confluence reversal. Their semantic context must be implemented alongside options
analytics, flow, dealer, news/event risk and obstruction/quality checks.

Durable called-play limits, loss/cooldown/neutral state, shared-owner arbitration,
current-price admission, management, runtime enrollment, stored observer views,
replay/export and prospective full-cost measurement remain open. Future integration
must preserve the one-owner ledger and all entry/management expenses; the scanner
does not supply a fee-free alternate execution path. Authentic provider/model and
host acceptance, overnight Swing and combined stock/options ownership are unchanged.

Exact installed verification is recorded in [status](SLICE2_STATUS.md). Main stays
untouched, PR #1 draft, LIVE disabled and the deployed experiment frozen.
