# Scope context variants and risk review

`app.options.scope_context.scan_scope_context(frame, context, policy, now=...)`
adds the six context-derived variants to the nine
[completed-structure patterns](OPTIONS_SCOPE_STRUCTURE.md). It binds typed dealer,
expected-move, flow, news and economic-event payloads to the existing required
coverage attestations, checks prior-session evidence, and retains deterministic
context-risk blockers. Results remain **fixture-verified diagnostics**, always
with false trade/LIVE authority.

No candidate, score, quantity, account, model, order, runtime family enrollment or
broker path is added. Existing independent research accounts, their full costs and
the shared Degen/Swing owner remain unchanged.

## Typed evidence

`ScopeContextInput` requires explicit fields; an unavailable payload is `None`,
which produces a named blocker rather than a neutral or clear default:

- Dealer context: SPX identity and one to twelve positive unique observed nodes.
- Expected moves: SPX identity, current-session expiration, reference spot, positive
  ATM-straddle move and positive separately supplied IV-derived move. The lower
  ATM boundary must remain positive. This input does not infer IV or verify a
  provider's calculation method; authentic normalization must establish those facts.
- Options flow: explicit `SPX_SPXW` scope and bullish, bearish, neutral or unknown
  state, with an exclusive validity boundary.
- News: explicit `BROAD_MARKET` scope and the same directional/unknown states,
  with an exclusive validity boundary.
- Economic events: explicit `US_MACRO` scope, clear/elevated/high-impact/unknown
  state, and an exclusive validity boundary.
- Prior-session SPX range: explicit source, session date, close, ordered positive
  high/low, coverage, entitlement and source/receipt times.

The supplied previous-session date is part of the reviewed calendar input. Prior
range identity must match it, its close must belong to that New York date, and
close/source/receipt chronology must show the range was known before the current
open. Frozen source, maximum age, receipt lag, completeness and REALTIME checks
apply. The date is not inferred from weekdays or authenticated by this function;
actual prior-session/index-calendar mapping remains a provider acceptance gate.

`context_payload_hashes(context)` defines `scope-context-payload-v1` bindings for
the five current coverage groups. The scanner recomputes each hash and requires
exact source, source/receipt clocks, completeness and entitlement agreement with
its preflight attestation. Preflight independently enforces the frozen source
and freshness requirements. A matching hash alone cannot override those checks.
Unknown or expired state, wrong flow/news kind, mismatched expected-move expiry,
or missing/mismatched payloads block the entire context review.

These hashes bind normalized content, not external authenticity. A collector must
retain and validate the actual provider payloads; no model may fabricate context
state or use this schema as evidence that data was observed.

## Six derived variants

The implementation follows the anchored variants in pinned SignalFlow
[`_contextualize_setup_candidates`](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard.py)
at `f9eaf2c1b5d13dca287ee7138126883065b00395`:

| Variant | Required relationship to an already detected parent |
| --- | --- |
| Prior-level break/retest | Continuation reference near the direction's source-defined prior level. |
| Prior-level rejection | Reversal reference near that prior level. |
| Dealer-level acceptance | Continuation reference near the nearest observed dealer node. |
| Dealer-level rejection | Reversal reference near the nearest observed dealer node. |
| Implied-move boundary rejection | Reversal reference near the direction's ATM-straddle boundary. |
| Exhaustion confluence reversal | Both the dealer-node and expected-boundary relationships hold. |

As in the pinned context function, CALL variants reference the prior low/lower
expected boundary and PUT variants reference the prior high/upper boundary. These
are **level-anchored variants of an existing price pattern**, not independent
proof of a new retest/rejection event. Context cannot originate a setup.

Proximity is bounded by the larger of explicitly frozen point and spot-fraction
limits. A node exactly at the limit qualifies; one beyond does not. Equal-distance
dealer-node ties choose the lower level deterministically. A blocked or watching
parent never produces a derived variant, so a pending neutral reset, missing
confirmation or rejected exact contract cannot be rescued by context.

Every variant retains `parent_pattern`, the exact parent geometry and matched
level. All parent alternatives remain visible instead of being collapsed by an
unimplemented quality score. They are correlated views of the same evidence, not
independent opportunities or additional bankrolls. Future candidate arbitration
must preserve that derivation and the one-owner position limit.

## Context risk and remaining authority

The same risk checks apply to the original detected pattern and every derived
variant. Opposing SPX/SPXW flow, opposing broad-market news and a known high-impact
event window each block. Elevated event risk stays explicit as a quality-review
note; it is not silently clear and no score or probability is invented.

Expected-move consumption is the absolute distance between completed SPX spot and
the opening-range midpoint, divided by the supplied ATM-straddle move. Exceeding
the explicitly frozen fractional ceiling blocks; equality is allowed. The IV
move remains required contextual evidence, but is not substituted as this
denominator. All arithmetic uses a fixed Decimal context and numeric failure
produces a named blocker.

A result contains the complete underlying structure scan, context observations,
unmatched context families and any global issues. Consumers must honor global
issues and per-observation blockers. A nested earlier `DETECTED` observation does
not override a failed context review. Whole frame/context and policy hashes bind
the result; reads perform no I/O.

[Durable unfilled watches](OPTIONS_SCOPE_WATCHES.md) now preserve called-play
counting, locked evidence and invalidation/expiry in the existing journal.
New frozen watch cohorts also support distinct neutral resets and fresh reversal/
cooldown checks. [Quality review](OPTIONS_SCOPE_QUALITY.md) now adds auditable scoring
and known-level path checks. Full-cost native loss/cooldown state, complete
obstruction/arming policy, shared-owner admission and management, explicit Scope
runtime enrollment, stored observer projection and full-cost replay remain open. Authentic data normalization and provider/calendar
acceptance are still required. Scope cannot trade through these diagnostics.

See [status](SLICE2_STATUS.md) for exact installed verification and
[source of truth](SOURCE_OF_TRUTH.md) for the continuing delivery contract. Main
is untouched, PR #1 draft, LIVE disabled and the deployed experiment frozen.
