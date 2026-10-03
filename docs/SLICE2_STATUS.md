# Slice 2 — Robinhood Read / SHADOW Status

## Proven live on 2026-10-03

- Robinhood OAuth is working against the Agentic Trading account.
- Live schema discovery returned 76 tools and 76 input schemas with no required-schema gaps.
- The authenticated read probe completed successfully after transport hardening.
- Account, portfolio, positions, working orders, quotes, tradability, and historical OHLCV parsed successfully.
- Broker/local reconciliation returned clean.
- All 20 configured equity/ETF candidates built successfully.
- The first stub SHADOW cycle returned HOLD, the risk governor rejected entry with `NO_ENTRY_REQUEST`, and no broker review or order path was touched.
- A live probe exposed the MCP SDK's 1 MiB SSE-event ceiling for batched 5-minute historicals. Historical OHLCV now fetches one symbol per call; the subsequent live probe passed.

## Safety architecture

- The Trader Agent has no brokerage tools.
- Robinhood writes remain blocked by the capability firewall.
- SHADOW may call only `review_equity_order` after deterministic risk approval; it never calls `place_equity_order` or cancellation/mutation tools.
- Broker/local reconciliation fails closed for unsupported asset value, multiple positions, unowned/missing positions, position disagreement, non-long positions, or working orders.
- V1 uses unleveraged buying power as the sizing ceiling, so margin leverage cannot increase deterministic exposure.
- PAPER and Robinhood state use separate SQLite databases.
- Model/API failures are converted to an auditable fail-closed HOLD.
- The OpenAI Agents SDK run is bounded to one model turn and uses strict structured `TradeDecision` output.
- Prompt version `v2-live-shadow` is persisted with each new cycle for later attribution.

## Current model configuration

- Model: `gpt-6-luna`
- Configured standard short-context pricing: $0.05 / 1M input tokens and $0.25 / 1M output tokens.
- The current Agents SDK path uses `Agent(output_type=TradeDecision, tools=[])` and `Runner.run_sync(..., max_turns=1)`.
- Token usage is saved when the SDK returns it.

## Commands

Safe live-read probe:

```bash
git pull
source .venv/bin/activate
python -m app.robinhood.cli probe
```

Stub SHADOW validation:

```bash
python -m app.robinhood.cli shadow-cycle --agent stub
```

Real reasoning-agent SHADOW cycle:

```bash
read -s -p 'OpenAI API key: ' OPENAI_API_KEY; export OPENAI_API_KEY; echo
python -m app.robinhood.cli shadow-cycle --agent openai
```

If `OPENAI_API_KEY` is absent, obviously placeholder text, or implausibly short, the CLI exits before any Robinhood or model call.

## Validation state

- Full updated suite on the user's Mac: 51/51 passing.
- User-run historical transport regression after the hotfix: 2/2 passing.
- Credential preflight now explicitly rejects example placeholder keys before any network call.

## Remaining Slice 2 evidence

1. Run the full updated test suite.
2. Execute one real OpenAI SHADOW cycle against live market packet data.
3. Inspect the persisted decision, risk decision, model token usage/cost, and any broker review.
4. Keep PR #1 draft until those checks are clean.

## Live authority

No live brokerage placement or cancellation path exists in Slice 2.
