# Slice 2 — Robinhood READ / SHADOW Status

## Current checkpoint — 2026-10-03

Branch: `slice2/robinhood-read-shadow`. PR #1 remains draft. `main` remains untouched.
Slice 2 is not yet fully verified: authenticated structured output and a successful real
Trader Agent SHADOW cycle still require evidence from the user's authenticated Mac.

## Proven against the live account

- Robinhood OAuth and MCP connection work.
- Discovery returned 76 tools and 76 input schemas without required-tool/schema gaps.
- Account, portfolio, positions, working orders, quotes, tradability and historical OHLCV parse.
- Broker/local reconciliation was clean, with no position or working orders at that checkpoint.
- All 20 configured candidates build and regime calculation works.
- Stub SHADOW returned HOLD with no broker review or order submission.
- Historical OHLCV fetches one symbol per call because batched 7-day / 5-minute results
  exceeded the MCP SDK's 1 MiB SSE-event ceiling.
- `openai-check` accepted authentication and model access for `gpt-6-luna`.

## Latest authenticated batch

The user's Mac pulled `b18f79b740a5d10bd93cd726d5e198105135acd6` and passed
**95 tests**. `openai-structured-check` then returned HTTP 429,
`credit_balance_exhausted` / `insufficient_quota`. Robinhood was not touched.
The chained real SHADOW cycle and audit did **not** execute.

The current external blocker is API credit. Add credits in the OpenAI API billing settings
before retrying the authenticated batch. This quota response does not prove that structured
output now succeeds; schema-only and real SHADOW success remain unverified.

## Earlier schema failure

The user's chained batch pulled `6ef7a2ce6e6e34fa75ada66c9bc73622af31ce9c`, then
passed **58 tests**. `openai-structured-check` returned HTTP 400 `invalid_json_schema`:
regex lookaround at `$.properties.invalidation_price.anyOf[1].pattern` was unsupported.
The subsequent real SHADOW cycle and audit did **not** execute because the commands used `&&`.

## Fix and local verification

- Both proposed price fields use an explicit number/string wire schema, with no generated
  Decimal regex. Nullable prices remain supported.
- Prices remain Decimal values after parsing. Positivity, finiteness, precise string parsing,
  action requirements, confidence/exposure bounds and rationale/list limits still validate locally.
- Tests inspect the actual strict `AgentOutputSchema(TradeDecision)` and exercise its JSON parser,
  including invalid prices, high-precision values and application limits.
- The smoke check must return HOLD to report success.
- SHADOW persists an explicit `execution.agent_error` on model failure and exits **8** after
  saving the fail-closed HOLD. Genuine HOLD remains a successful decision.
- Complete simulated SHADOW cycles verify HOLD, approved entry review, agent failure and
  reconciliation failure, including persisted packet/decision/execution, benchmark and usage cost.
- Fresh recovered checkout baseline: **58 passed**.
- Updated complete suite: **95 passed**. Compilation, diff whitespace checks and fatal-error
  lint checks passed. No authenticated API call was made in this execution workspace, which
  has neither the OpenAI key nor Robinhood OAuth state.

## Persistent evidence/history follow-up

While authenticated verification is blocked by API credit, the following bounded infrastructure
work is implemented and locally verified with **105 passing tests**:

- New SHADOW cycles commit decision, usage, account snapshot, benchmark snapshot and explicit
  reconciliation evidence together in one transaction. A late persistence failure rolls back all rows.
- A new `shadow_cycle_evidence` table links usage to the exact decision cycle without altering
  existing tables. Startup creates the table for existing databases; legacy rows remain unlinked.
- `shadow-audit` never borrows an earlier cycle's usage. Missing usage is null; older cycles
  report `LEGACY_UNLINKED` instead of inferred attribution. Cumulative cost remains available.
- Stub cycles are identified as `stub`, not as the configured OpenAI model. Legacy labels are preserved.
- Broker-review failures persist the model decision, risk result and reported token usage/cost,
  with a sanitized `execution.review_error`. They submit nothing and exit **9**.
- `shadow-history --limit 100` reports decisions by action/model, genuine HOLDs, agent/review
  failures, risk rejections, completed hypothetical reviews, linked costs and SPY price observations.
- SPY output is a raw quote-price return with sample endpoints. Strategy/economic P&L remains
  null because SHADOW has neither submitted trades nor a counterfactual fill ledger.
- Tests cover rollback, restart persistence, legacy database upgrade, missing benchmark/usage,
  exact audit attribution, review failure and history limits. PAPER tests remain passing.

History/audit commands read local persisted evidence and make no OpenAI or Robinhood calls:

```bash
python -m app.robinhood.cli shadow-history --limit 100
python -m app.robinhood.cli shadow-audit
```

## Authority and configuration

- Default mode remains PAPER. LIVE remains disabled.
- Trader Agent uses `tools=[]`, strict `TradeDecision` output and `max_turns=1`.
- Deterministic software owns approval and sizing, capped by unleveraged buying power.
- SHADOW reads real broker truth and may use only `review_equity_order` for hypothetical
  trading, after governor approval. It never submits or cancels an order.
- Broker/local mismatches fail closed, including unsupported assets, multiple positions,
  unowned/missing positions, symbol/quantity disagreement, non-long positions and working orders.
- Robinhood state defaults to `robinhood.db`; PAPER state remains separate.
- Model: `gpt-6-luna`. Configured prices: $0.10 / 1M input tokens and $0.50 / 1M output tokens.
- Prompt version: `v2-live-shadow`. Successful SDK token usage and estimated costs persist.

## Next authenticated batch

From the existing activated virtual environment on the Mac:

```bash
git pull --ff-only && \
pytest -q && \
python -m app.robinhood.cli openai-structured-check && \
python -m app.robinhood.cli shadow-cycle --agent openai && \
python -m app.robinhood.cli shadow-audit
```

Run this batch after adding API credit. The schema check touches OpenAI only. After it passes,
the same batch goes directly through
the real SHADOW model path and persisted audit. If the model run exits 8, its HOLD is already
persisted; `python -m app.robinhood.cli shadow-audit` can inspect it separately.

To close Slice 2, inspect the decision, deterministic risk result, skipped execution or
hypothetical broker review, model/prompt identity, latency, tokens/cost and SPY snapshots.
A valid HOLD is acceptable. Do not claim useful signal or profitability from one cycle.

After authenticated verification, proceed to market-session scheduling, a counterfactual performance
ledger, economic/SPY comparison and anti-churn/cooldown/idempotency hardening. Persistent evidence
and decision-history reporting are implemented above; the remaining experiment features are pending.
