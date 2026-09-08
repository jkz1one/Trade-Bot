# Slice 1 status — 2026-09-08

## Implemented

- Python/FastAPI/Jinja one-page application with SQLite persistence.
- Default paper bankroll: $10.
- Strict Pydantic `TradeDecision` schema.
- OpenAI Agents SDK adapter with no execution tools exposed to the Trader Agent.
- Deterministic fake trader for repeatable tests/demo cycles.
- Fixture market provider and fixed-universe interface.
- Dynamic bankroll risk tiers: MICRO, SMALL, GROWTH, SCALE, PRESERVATION.
- Risk-at-invalidation sizing using proposed invalidation plus volatility/spread floors.
- Deterministic governor that can approve, clip, or reject entries.
- $1 broker-minimum handling without unsafe round-up.
- Drawdown de-risking and hard shutdown.
- Stale quote, tradability, buying-power, one-position, averaging-down, and daily-entry checks.
- Paper buy fills at ask and close fills at bid.
- Idempotency support for paper execution retries.
- Paper state reconstruction after process restart from persisted position episodes.
- Capital events for initial contribution, deposits, and withdrawals; external flows are excluded from strategy P&L.
- Model-usage/cost schema with pricing captured at run time.
- Benchmark snapshots and raw SPY price return when no external capital flows are present.
- Full cycle persistence: market packet, model decision, risk decision, execution result, latency.
- Dashboard: equity, P&L, return, capital multiple, high watermark, risk mode, drawdown, agent decision, risk outcome, position, AI cost, economic P&L, benchmark, activity, HALT.
- Slice 1 refuses to start as SHADOW or LIVE.
- No Robinhood/MCP order-placement code exists in Slice 1.

## Validation performed here

- `pytest -q`: 27 tests passed.
- `python -m compileall -q app`: passed.
- FastAPI dashboard GET and demo-cycle POST smoke-tested with TestClient.
- Source scan found no `place_equity_order`, `review_equity_order`, Robinhood, or MCP references in application code.

## Not yet proven / intentionally deferred

- OpenAI Agents SDK is declared as a dependency, but the package is not installed in this execution sandbox; no authenticated model call was made. The adapter shape was reconciled against current official SDK documentation.
- Dockerfile and Compose file were written, but this sandbox has no Docker CLI, so an image build was not executed here.
- Robinhood read/shadow/live integration is intentionally absent until later slices.
- Real exchange calendar and 15-minute market scheduler are not implemented in Slice 1.
- Real market data is not connected; fixtures are explicitly demo data.
- `REDUCE` is represented in the decision schema but deliberately fails closed in Slice 1; `CLOSE` is implemented.
- Contribution-adjusted/time-weighted SPY benchmarking is not implemented yet. When external capital flows exist, the dashboard suppresses raw benchmark return rather than presenting a misleading comparison.
- No claim of profitability or alpha has been made.
