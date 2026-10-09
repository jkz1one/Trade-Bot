# M1: offline options identity and admission

`app.options.models` and `app.options.governor.admit_option` implement the first
options milestone. This is a pure PAPER calculation over supplied immutable inputs.
It has no database, model, provider, credential, broker tool or dispatch capability.
The stock engine and frozen `virtual-v1` deployment do not call it. It cannot trade
options yet. [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md) owns the delivery sequence;
next is M2, durable option PAPER execution.

## Inputs and identity

Software supplies `OptionLimits`, a reconciled `OptionAccount`, an exact
`OptionQuote`, separate `UnderlyingQuote` and explicit `SessionWindow`. The proposal
supplies HOLD, OPEN_LONG or CLOSE, the exact contract, thesis and original underlying
invalidation for entry. Its optional debit request can only reduce size. It cannot
supply quantity, account truth, mode, tools or risk policy. HOLD needs none of the
other evidence and returns an ordinary zero-quantity HOLD result.

Contract metadata includes underlying/root/right/strike/expiry, US market category,
multiplier/deliverable, exercise style, settlement kind/session, actual last trading,
expiry and settlement instants, adjusted status and two premium tick tiers. A
broker-independent `option-v1:` SHA-256 identity binds all metadata; Decimal scale
and equivalent timestamp timezones do not change it. Provider/instrument identifiers
remain a separate mapping. The same provider ID cannot override conflicting expiry,
strike, right, deliverable or trading/settlement metadata.

Initial support is standard 100-multiplier US-listed stock/ETF share deliverables,
or European cash-settled US index contracts. Adjusted, OTC, non-US and incompatible
metadata are rejected even when whitelisted. Contract metadata completeness and
tradability are explicit. Entry also requires a frozen underlying price floor of
at least $5. These are conservative engineering limits for PAPER, not authenticated
broker/data verification or approved LIVE settings.

All timestamps normalize to UTC, preserving actual instants through DST folds.
All money accepts Decimal, decimal text or integers, rejecting floats/bools,
nonfinite values and unbounded precision/exponents. Whole contract sizes require
native integers. Inputs forbid extra fields, freeze nested contracts and are
revalidated at admission, including values forged through Pydantic `model_copy`.

## Evidence and sizing

Quotes retain source and receipt times, exact contract mapping, bid/ask/whole sizes,
source identity, completeness and REALTIME entitlement. Entry rejects stale/future/
crossed/missing/zero-bid quotes, receipt-time regression/excessive lag, incomplete or
indicative/delayed evidence and unsynchronized underlying/option timestamps. These
flags are caller-supplied evidence claims, not self-authenticating provider proof.

Account and population IDs bind the explicit policy. Incomplete, unreconciled,
stale/future, unsupported or unresolved-order account truth blocks approval.
Existing equity or option positions block entry and all adds. Entry halts, caller
health blockers and unknown cost/loss budgets block new exposure. Calls require
invalidation below underlying bid; puts require invalidation above underlying ask.

Buy limits round ask plus adverse slippage upward to the contract tick, including
a move across the $3 tick tier. Software selects the largest whole quantity that
fits observed ask size, maximum contracts, entry debit, account exposure, available
settled funds after other reservations, full-premium loss, and remaining daily/
total loss budgets. Entry and closing fees are conservative explicit per-order/
per-contract inputs. Full-premium loss includes the entire approved entry debit
plus reserved exit fees. A close stop or model request cannot raise this ceiling;
an unaffordable single contract returns rejection with zero quantity. Integer-ratio
division prevents rounding a nearly affordable contract upward. Arithmetic and
identity do not inherit the caller's Decimal arithmetic context.

CLOSE sells only exact owned whole contracts, bounded by observed bid size. It uses
bid minus adverse slippage rounded down, with explicit fees and signed minimum
exit cash change. Low-value closes can pay fees from remaining settled funds;
unfunded fees cannot create borrowing. An entry halt, unknown entry budget, missing
underlying thesis evidence or elapsed entry cutoff cannot veto an otherwise valid
owned close. Exact account/contract identity, session, fresh bid/size and unresolved
order checks still apply. Missing bids do not invent liquidation proceeds or flatness.

Approvals expire at the earliest policy lifetime, quote/account freshness deadline,
session close or exact last trading instant; entry also binds underlying freshness
and the entry cutoff. A session window is supplied reviewed evidence, not a guessed
weekday or an actual calendar integration. No option is admitted after last trading,
including an AM contract whose last trading session is already past.

## Execution boundary and next slice

An `OptionAdmission` is an offline result, never a receipt or reusable dispatch
authority. M2 must atomically persist frozen policy, proposal, complete evidence,
approval and reservations; independently reconstruct authoritative account truth;
and re-admit fresh evidence before any fixture attempt. It must preserve original
invalidation, whole partial fills, unknown attempts and costs, model-independent
exit requirements, exact calendar/cutoff/settlement behavior and authoritative
reconciliation. Cash settlement and exercise-created exposure are not implemented
by accepting their identity metadata here.

There is no options runtime enrollment, strategy/model schema wiring, actual option
read adapter, SHADOW option preview, broker write, deployment change or LIVE path.
Provider, target-host, off-host recovery and LIVE acceptance remain separate gates.
