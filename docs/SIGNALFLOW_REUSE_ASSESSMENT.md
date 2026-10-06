# SignalFlow reuse assessment

Reviewed 2026-10-05 UTC. This is an implementation assessment, not a new master
roadmap, an integration, or approval to deploy/change SignalFlow.

2026-10-06 follow-up: fresh GitHub inspection confirms the same SignalFlow HEAD.
Its broker snapshot/capability, reservation, persistent ledger and partial-fill
contracts now inform the separate [execution lifecycle rehearsal](EXECUTION_REHEARSAL.md).
This is an implemented fixture-only foundation using the current governor, Decimal
and one position. It adds no broker writes or SignalFlow runtime dependency; the
historical review and its narrower evidence below remain intact.

## Canonical snapshots and evidence boundary

- SignalFlow `main`: `f9eaf2c1b5d13dca287ee7138126883065b00395`.
- Trade-Bot `slice2/robinhood-read-shadow`: `87319600d44524840010ccb3d4b3c084c0b00e74`.
- SignalFlow's control ledger is [CURRENT_MASTER_ROADMAP.md](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/CURRENT_MASTER_ROADMAP.md).
  Its historical accepted-runtime evidence is separate from repository HEAD; the
  opening baseline summary also lags later entries describing PRs #106/#108.
  Do not infer the droplet's current image, availability or health from this file.

Follow-up implementation: OpenAI SHADOW now uses a killable model subprocess with a
120-second overall deadline, 60-second request timeout, zero SDK retries and explicit
terminate/kill/reap cleanup. Seventeen process/worker/integration tests exercise genuinely
blocking synchronous children, cancellation races, output validation, service halt,
claim retention and shutdown drain. The historical thread gap below describes the
reviewed snapshot; see [SLICE2_STATUS.md](SLICE2_STATUS.md) for current verification.
An authenticated subprocess model run and target-host startup still remain to be observed.

A thirty-file pinned SignalFlow reference snapshot was recovered. Targeted reads covered architecture,
paper measurement, outcome/rejection reporting, replay, calibration, reconciliation,
stop/loss controls, worker health, runtime incidents and dashboard surfaces. This is
a targeted architectural review, not a full repository or production audit.

Twelve unchanged pure SignalFlow rejection/replay/outcome tests passed in an isolated
reference checkout using Trade-Bot's Python environment. Trade-Bot's unchanged suite
also passed: **181 tests**. SignalFlow's full suite and deployed runtime were not run.
There were no model, broker or market-data calls, and no SignalFlow modifications.

## What carries over

| Area | SignalFlow evidence | Trade-Bot fit and adaptation |
| --- | --- | --- |
| Persistent execution | Separate scheduler/worker heartbeat and restart guard | Service/slot/heartbeat foundation already exists. Keep one worker and SQLite; borrow health semantics, not Redis queues or the full runtime composition root. |
| Decision accounting | Outcome dispositions and exact block reasons | Existing audit/history distinguish model HOLD, deterministic HOLD and failures. Add cohorts and completeness/availability counts over existing linked cycles; retain rejected, blocked and expired observations. |
| Read-only dashboard | Outcome workspace reads stored reports and recent records without provider/model evaluation | Best UI pattern to adapt. Build a separate SHADOW observer that reads persisted service/slot/cycle/outcome state. Opening or refreshing it must never trigger a trading cycle. |
| Point-in-time integrity | Replay checks provider/source/receipt/processing/decision/persistence times and evidence hashes | Preserve saved MarketPackets and usage links; add explicit availability times and hashes before historical replay. Never substitute today's market data for missing historical evidence. |
| Rejection value | Complete, leakage-safe counterfactual outcomes, grouped by exact rule | Later measure losses avoided and opportunities missed. Current rejected entries lack evaluated counterfactual outcomes; reason counts alone cannot establish rule value. |
| Paper lifecycle | Frozen entry context, stable fill identity, quote provenance and immutable review/version fields | Adapt for a separate synthetic PAPER experiment using recorded real market packets. Existing SHADOW forward marks stay quote observations. Synthetic positions must never become locally owned Robinhood positions. |
| Controlled tuning | Versioned artifacts, held-out evidence, approval and rollback | Retain an explicit research/evaluation boundary. Do not import numeric sample thresholds or automatic tuning. Risk authority and credentials remain outside calibration. |
| Risk management | Stop tightening cannot widen original risk; loss controls persist and resets are audited | Preserve original invalidation. Consider these contracts when implementing synthetic position management; do not import option-premium management or change current governor thresholds. |

Primary sources, pinned to the reviewed SignalFlow commit:

- [Architecture](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/architecture.md)
  and [paper execution](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/paper-execution.md).
- [Outcome contract](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/outcome_warehouse_models.py),
  [analysis](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/outcome_analysis.py),
  [rejection value](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/rejection_value.py).
- [Stored outcome workspace](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/outcome_workspace.py)
  and [its UI](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/app/outcome-intelligence/OutcomeIntelligenceWorkspace.tsx).
- [Replay integrity](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/point_in_time_replay.py),
  [calibration controls](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/calibration_control.py),
  [stop authority](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/play_stop_authority.py).

## Boundaries that require adaptation

SignalFlow's original [AI boundary](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/ai_boundary.py)
allows evidence narration and prohibits AI-generated entries, stops, sizing and
confidence. Trade-Bot deliberately gives the model proposal judgment, including an
invalidation proposal; deterministic software alone grants authority and sizes.
Copying that AI schema would remove the experiment being tested.

SignalFlow's confidence report compares confidence with win frequency. Trade-Bot
defines confidence as subjective setup confidence, not a probability. Confidence
bands may be descriptive cohorts; do not label them probability calibration without
a separately specified probabilistic forecast and outcome definition.

SignalFlow's reporting models use floats and contain options, multiple bots, order
reservations and broker-fill fields. Trade-Bot should keep Decimal money/quantity
arithmetic, its single-trader schema and SHADOW's absence of submitted orders.
SignalFlow brokerage/reconciliation contracts are not a Robinhood adapter.

Do not transplant Degen/Swing/Scope thresholds, OPRA streaming, options/dealer analytics,
short-side management, shared multi-bot portfolio coordination, alternative providers,
the Next application or its administration mutation endpoints. None is required for
this single-bankroll equities/ETF experiment. Avoid a second independent trading
authority by hosting Trade-Bot inside SignalFlow's orchestration root.

The existing Trade-Bot [web app](../app/main.py) deliberately accepts PAPER only and
creates fixture market data, a stub agent and PaperBroker. Its run-cycle/halt controls
operate that process; they do not control the SHADOW service. It must not be presented
as a live SHADOW monitor or have its demo metrics relabeled as brokerage results.

## Concrete runtime lesson and reviewed snapshot gap

SignalFlow's [reliability audit](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/docs/play-orchestrator-reliability-audit.md)
and [restart guard](https://github.com/jkz1one/SignalFlow/blob/f9eaf2c1b5d13dca287ee7138126883065b00395/backend/platform/worker_restart_guard.py)
explicitly address provider threads that survive task cancellation. Its canonical
roadmap also records regular-session receive lag, reconnects and OOM failures after
offline checks passed, plus an immediate memory problem associated with diagnostic
provider comparisons inside a latency-sensitive stream worker. These are documented
historical observations, not fresh measurements of the current droplet.

The same cancellation distinction applied in the reviewed Trade-Bot snapshot. `ShadowOrchestrator._decide`
uses `asyncio.to_thread(agent.decide, packet)`, while `ShadowService` applies a
600-second `asyncio.wait_for` to the cycle. A timeout cancels the awaiting coroutine;
it does not forcibly terminate the synchronous OpenAI call/thread. A small local
thread experiment reproduced this behavior without an API call.

That snapshot's fail-closed behavior still prevents another scheduled cycle and any broker
write, and an interrupted claim blocks replay. However, a model request may continue
after HALTED, with additional latency/cost. `asyncio.run` may wait on executor shutdown;
the Docker 660-second stop grace can ultimately force termination. A normal SIGTERM
smoke and async timeout fixtures do not prove bounded shutdown for a stuck real
synchronous call. Do not describe the deadline as guaranteed thread termination.

Before unattended deployment, harden or explicitly verify model request deadlines,
retry budgets and shutdown behavior. If synchronous calls remain, use an isolated
process boundary that can be terminated while preserving the claimed slot and durable
halt. Preserve the model's empty tool list, exact usage attribution when available,
and no replay. Failure-injection tests must use a genuinely blocking synchronous call,
not only an async sleep, and prove no subsequent review/cycle after cancellation.

Keep dashboard reporting and optional diagnostics outside the worker's critical path.
Opening a page should not initialize a broker connection, consume model credits,
recompute the whole experiment or import SignalFlow's full service graph. Collect
stage timing and memory/restart evidence on the actual host before enlarging scope.

## Recommended bounded sequence

This is a reuse recommendation within the settled project scope. No runtime feature
below is implemented by this review.

1. **Harden the model timeout/shutdown boundary.** Implemented and verified offline in
   the subprocess follow-up. Prove behavior for blocked synchronous
   work, executor/process cleanup, durable claims and halt/resume before continuous
   deployment. Retain the existing server migration and target-host verification gates.
2. **Add a separate private read-only SHADOW dashboard.** Show worker state/release,
   heartbeat age, market session, latest slot/cycle, model decision, deterministic
   reasons, reconciliation, review status, linked token cost and quote outcomes. Show
   empty/stale/failure states and distinguish worker health from useful trading signal.
   Use persisted data only, with bounded pagination and no credentials or brokerage
   controls. Validate network-call-free reads and concurrent worker/report access.
3. **Build sequential experiment accounting.** A separate synthetic PAPER ledger with
   one virtual position, conserved cash, immutable fills, explicit spread/slippage/fee
   assumptions, idempotency, restarts and net economics versus a matching SPY baseline.
   If a model sees virtual account state, give that run a separate experiment identity;
   do not mix its decisions/costs with the real-account SHADOW population. Never compare
   virtual holdings with Robinhood reconciliation ownership. Keep model costs across
   HOLDs, failures and all required experiment calls, not just successful entries.
4. **Assess cohorts/rejection value after enough session evidence exists.** Separate
   model/prompt/risk/measurement versions and regime/time cohorts. Report coverage,
   failures and exclusions. Overlapping horizon marks are not independent trades,
   multi-rule attributions are not additive profits, and a small sample threshold is
   not proof of an edge. Historical lessons/tuning remain leakage-safe and offline.

The existing SHADOW pipeline observes actual account truth and never changes it.
Consequently its current reviewed-entry marks cannot alone test sequential position
management or compounding: the real account stays cash after a hypothetical review.
That is a measurement boundary, not a reason to enable LIVE or fabricate holdings.

## Review verification

Executed against the pinned reference modules:

```text
tests/test_roadmap_phase17b_rejection_value.py
tests/test_roadmap_phase22_replay.py
tests/test_roadmap_phase25_outcome_completion.py
12 passed in 0.13s
```

Trade-Bot baseline: `181 passed in 3.93s`. The local cancellation demonstration
confirmed a timed-out awaiting task while its controlled synchronous thread remained
active, then released/joined that thread. This review makes no new profitability,
server-build, deployment, live-authentication or SignalFlow runtime acceptance claim.
