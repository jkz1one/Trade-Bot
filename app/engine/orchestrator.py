from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.agent.trader import TraderAgent
from app.broker.base import Broker
from app.config import Settings
from app.domain.models import ExecutionResult, MarketPacket
from app.market.base import UniverseProvider
from app.risk.governor import govern
from app.storage.repository import Repository


class Orchestrator:
    def __init__(self, settings: Settings, repo: Repository, broker: Broker, market: UniverseProvider, agent: TraderAgent):
        self.settings, self.repo, self.broker, self.market, self.agent = settings, repo, broker, market, agent
        self.system_enabled = True
        self.daily_entries = 0

    def cycle(self):
        started = perf_counter()
        candidates = self.market.candidates()
        quotes = {c.quote.symbol: c.quote for c in candidates}
        account = self.broker.account_state(quotes)
        packet = MarketPacket(as_of=datetime.now(timezone.utc), account=account, candidates=candidates, regime="fixture/demo")
        run = self.agent.decide(packet)
        risk = govern(run.decision, packet, self.settings, system_enabled=self.system_enabled, broker_reconciled=True, daily_entries=self.daily_entries)
        execution = ExecutionResult(status="SKIPPED", symbol=run.decision.symbol, message="No executable action")
        if risk.approved and run.decision.symbol:
            quote = quotes[run.decision.symbol]
            execution = self.broker.execute(
                run.decision, risk, quote, idempotency_key=f"proposal-{uuid4().hex}"
            )
            if execution.status == "FILLED":
                self.daily_entries += 1
        latency_ms = int((perf_counter() - started) * 1000)
        self.repo.save_cycle(packet, run.decision, risk, execution, self.settings.model_name, latency_ms)
        if run.input_tokens or run.output_tokens:
            self.repo.save_model_usage(self.settings.model_name, run.input_tokens, run.output_tokens, self.settings.model_input_usd_per_million, self.settings.model_output_usd_per_million)
        self.repo.save_account_snapshot(self.broker.account_state(quotes))
        spy = quotes.get(self.settings.benchmark_symbol)
        if spy:
            self.repo.save_benchmark(spy.symbol, spy.last)
        return packet, run.decision, risk, execution
