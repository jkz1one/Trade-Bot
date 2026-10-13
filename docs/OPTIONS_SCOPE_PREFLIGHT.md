# Scope SPX/SPXW evidence preflight

`app.options.scope.preflight_scope(frame, policy, now=...)` implements the first
Scope boundary: explicit evidence coverage, completed confirmation histories and
exact contract identity. It returns `BLOCKED` with subject-specific reasons or
`COVERAGE_COMPLETE`, always with `authority=false` and `live_enabled=false`.
It performs no I/O and has no account, model, sizing, order or execution owner.

This is **fixture-verified preflight**, not Scope setup detection, trade admission
or authentic provider acceptance. The existing Degen/Swing candidate universe,
runtime enrollment and independent research accounts are unchanged. Scope cannot
enter their AI packet or acquire a second execution path through this function.

## Pinned contract

The already approved SignalFlow reference remains
`f9eaf2c1b5d13dca287ee7138126883065b00395`:

- [Scope V2 playbook](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/SCOPE_WIZARD_SPXW_PLAYBOOK_V2.md)
- [Evidence and decision implementation](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard.py)
- [Research policy](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/scope_wizard_policy.py)

Those files were re-read for this implementation. SPX supplies setup authority;
SPY/QQQ supply confirmation, and only exact same-day SPXW contracts qualify.
Missing capability never redirects to SPY, AM-settled SPX or another expiry.
The reference's permissive missing-root/entitlement/coverage defaults are not
copied. Its score, ask/debit tiers, time settings, loss controls and quote ages
remain research baselines, not accepted account limits or measured provider SLA.

## Inputs and blockers

`ScopePreflightPolicy` requires nine unique source/age bindings: provider readiness,
technical structure, options analytics, dealer structure, options flow,
cross-market agreement, economic events, broad-market news and SPXW contracts.
Each `ScopeEvidence` requires an explicit availability status, completeness,
REALTIME entitlement, source and receipt times, and the digest of a retained
normalized payload. Missing, duplicate, delayed, unknown, stale, future or
unbound evidence blocks. No empty input becomes available by default.

These records are **coverage attestations**. A payload digest binds the supplied
reference; it neither loads the payload nor verifies its semantic conclusions or
authenticity. In particular, complete cross-market coverage is not an assertion
that SPY/QQQ agree with an SPX setup. Dealer levels, expected moves, news/event
risk and confirmation direction still need their specific setup evaluators.

Three explicit history-source bindings require SPX, SPY and QQQ. Each supplied
history must contain every completed regular five-minute bar from the supplied
session open through the evaluation clock, with at least three completed bars.
Missing, duplicate, gapped, interpolated, future, stale or delayed history blocks.
Every bar must have been completed by its source and receipt times. Index volume
is not inferred, and this coverage check does not require positive index volume.
The three history source times and exact option quote must meet an explicit
synchronization bound, separately from individual age and receipt-lag bounds.

`ScopeSession` carries an explicit source, evidence digest, New York session date,
open, entry start, exclusive entry cutoff, protection cutoff and close. Ordered
same-session boundaries are required. There is no weekday shortcut or assumption
that an equity calendar establishes the SPXW session. The supplied session is
reviewed input, not proof that an actual exchange was open; authentic calendar
mapping and shortened-session validation remain provider acceptance work.

One supplied `ContractMetadata` and `OptionQuote` must identify the exact same
provider instrument and full canonical contract. The contract must be standard,
unadjusted, USD, multiplier 100, European cash settlement with no share deliverable,
US INDEX underlying SPX, root SPXW and PM settlement. Expiration and last trading
must match the evaluated New York day. The reviewed protection cutoff must occur
no later than last trading; expired or untradable instruments block.

Metadata and quote have independently frozen sources and freshness bounds. Quotes
need positive bid/ask, positive displayed sizes, an uncrossed market, supplied
contract tick alignment and a bounded midpoint-relative spread. A provider mapping
change cannot substitute another quote. An observed/supplied delta with the wrong
CALL/PUT sign blocks, but there is no Degen delta band. Missing Greeks and
volume/open interest remain missing; passing preflight does not claim those values
exist or satisfy a later liquidity/admission rule.

Every result binds the entire input and policy hashes and evaluation time. Models
and unsafe `model_copy` inputs are revalidated. Money uses Decimal with a local
arithmetic context. All freshness settings are explicit research/fixture inputs;
no default thresholds have been selected from unobserved provider behavior.

## Integration still required

The approved continuation/reversal modules, SPX structural geometry, confirmation
agreement, contract reachability, neutral transition after failed continuation,
called-play limits, loss/cooldown state, management and shared-owner admission
remain open. This gate does not import source scores as probabilities or authorize
source premium tiers, position sizes or manual loss resets.

Authentic SPX/SPXW data and entitlement, exact normalization, event/news/dealer/flow
coverage, actual session/cutoff proof, common AI arbitration, runtime enrollment,
stored observations, replay/export and all-cost cohort measurement are still needed
before Scope can run. No account or charge exists at preflight; future Scope work
must use the existing common ledger and preserve independent research accounts,
all entry/management costs and proposal/review/fill attribution.

See [the source of truth](SOURCE_OF_TRUTH.md), [shared strategies](OPTIONS_SHARED_STRATEGIES.md)
and [status](SLICE2_STATUS.md) for current capabilities and exact installed proof.
Main, PR draft, LIVE-disabled state and the deployed experiment remain preserved.
