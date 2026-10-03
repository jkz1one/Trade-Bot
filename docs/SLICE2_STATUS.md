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

## Latest empirical failure

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

The schema check touches OpenAI only. After it passes, the same batch goes directly through
the real SHADOW model path and persisted audit. If the model run exits 8, its HOLD is already
persisted; `python -m app.robinhood.cli shadow-audit` can inspect it separately.

To close Slice 2, inspect the decision, deterministic risk result, skipped execution or
hypothetical broker review, model/prompt identity, latency, tokens/cost and SPY snapshots.
A valid HOLD is acceptable. Do not claim useful signal or profitability from one cycle.

After authenticated verification, proceed to market-session scheduling, persistent experiment
results, economic/SPY performance, anti-churn/cooldown/idempotency hardening and decision history.
Those experiment features are not implemented or verified by this schema-fix checkpoint.
