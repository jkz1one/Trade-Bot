from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from app.domain.models import AccountState, ExecutionResult, MarketPacket, Position, RiskDecision, TradeDecision
from app.config import Settings
from app.storage.models import (
    AccountSnapshotRow, BenchmarkSnapshotRow, CapitalEventRow, DecisionCycleRow,
    FillRow, ModelUsageRow, OrderRow, PositionEpisodeRow, ShadowCycleEvidenceRow,
    ShadowScheduleSlotRow, ShadowForwardOutcomeRow,
)


class Repository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def ensure_initial_capital(self, amount: Decimal) -> None:
        with self.session_factory.begin() as s:
            count = s.scalar(select(func.count()).select_from(CapitalEventRow)) or 0
            if count == 0:
                s.add(CapitalEventRow(kind="INITIAL_CONTRIBUTION", amount=amount))

    def capital_flow_total(self) -> Decimal:
        with self.session_factory() as s:
            value = s.scalar(select(func.coalesce(func.sum(CapitalEventRow.amount), 0)))
            return Decimal(str(value))

    def add_capital_event(self, kind: str, amount: Decimal) -> None:
        with self.session_factory.begin() as s:
            s.add(CapitalEventRow(kind=kind, amount=amount))

    def realized_pnl_total(self) -> Decimal:
        with self.session_factory() as s:
            value = s.scalar(
                select(func.coalesce(func.sum(PositionEpisodeRow.realized_pnl), 0))
                .where(PositionEpisodeRow.closed_at.is_not(None))
            )
            return Decimal(str(value))

    def load_open_position(self) -> Position | None:
        with self.session_factory() as s:
            row = s.scalar(
                select(PositionEpisodeRow)
                .where(PositionEpisodeRow.closed_at.is_(None))
                .order_by(PositionEpisodeRow.id.desc())
                .limit(1)
            )
            if row is None:
                return None
            return Position(
                symbol=row.symbol,
                quantity=Decimal(str(row.quantity)),
                entry_price=Decimal(str(row.entry_price)),
                current_price=Decimal(str(row.entry_price)),
                original_invalidation=Decimal(str(row.invalidation_price)),
                thesis=row.thesis,
                opened_at=row.opened_at,
            )

    def latest_high_watermark(self) -> Decimal | None:
        with self.session_factory() as s:
            value = s.scalar(
                select(AccountSnapshotRow.high_watermark)
                .order_by(AccountSnapshotRow.id.desc())
                .limit(1)
            )
            return Decimal(str(value)) if value is not None else None

    def save_account_snapshot(self, a: AccountState) -> None:
        with self.session_factory.begin() as s:
            s.add(AccountSnapshotRow(equity=a.equity, cash=a.cash, high_watermark=a.high_watermark, realized_pnl=a.realized_pnl))

    def save_cycle(
        self,
        packet: MarketPacket,
        decision: TradeDecision,
        risk: RiskDecision,
        execution: ExecutionResult,
        model: str,
        latency_ms: int = 0,
        prompt_version: str = "v1",
    ) -> None:
        with self.session_factory.begin() as s:
            s.add(DecisionCycleRow(
                packet_json=packet.model_dump_json(),
                prompt_version=prompt_version,
                model_identifier=model,
                decision_json=decision.model_dump_json(),
                risk_json=risk.model_dump_json(),
                execution_json=execution.model_dump_json(),
                latency_ms=latency_ms,
            ))

    def save_shadow_cycle(
        self, packet: MarketPacket, decision: TradeDecision, risk: RiskDecision,
        execution: ExecutionResult, model: str, *, prompt_version: str,
        latency_ms: int, input_tokens: int, output_tokens: int,
        input_price: Decimal, output_price: Decimal, benchmark_symbol: str,
        reconciliation: dict,
        slot_key: str | None = None, claim_token: str | None = None,
        outcome_settings: Settings | None = None, completed_at: datetime | None = None,
    ) -> int:
        """Commit all evidence together, including explicit cycle-to-usage attribution."""
        if input_tokens < 0 or output_tokens < 0 or input_price < 0 or output_price < 0:
            raise ValueError("Model usage and pricing must be nonnegative")
        with self.session_factory.begin() as s:
            slot = s.get(ShadowScheduleSlotRow, slot_key) if slot_key is not None else None
            if slot_key is not None and (
                slot is None or slot.status != "CLAIMED" or slot.claim_token != claim_token
            ):
                raise RuntimeError("SHADOW scheduled cycle does not own its active claim")
            row = DecisionCycleRow(
                timestamp=packet.as_of, packet_json=packet.model_dump_json(),
                prompt_version=prompt_version, model_identifier=model,
                decision_json=decision.model_dump_json(), risk_json=risk.model_dump_json(),
                execution_json=execution.model_dump_json(), latency_ms=latency_ms,
            )
            account = packet.account
            snapshot = AccountSnapshotRow(
                timestamp=packet.as_of, equity=account.equity, cash=account.cash,
                high_watermark=account.high_watermark, realized_pnl=account.realized_pnl,
            )
            usage = None
            if input_tokens or output_tokens:
                cost = (
                    Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price
                ) / Decimal("1000000")
                usage = ModelUsageRow(
                    timestamp=packet.as_of, model=model, input_tokens=input_tokens,
                    output_tokens=output_tokens, input_price_per_million=input_price,
                    output_price_per_million=output_price, estimated_cost=cost,
                )
                s.add(usage)
            spy = next((c for c in packet.candidates
                        if c.quote.symbol == benchmark_symbol), None)
            benchmark = None
            if spy is not None:
                benchmark = BenchmarkSnapshotRow(
                    timestamp=packet.as_of, symbol=benchmark_symbol, price=spy.quote.last,
                )
                s.add(benchmark)
            s.add_all([row, snapshot])
            s.flush()
            s.add(ShadowCycleEvidenceRow(
                cycle_id=row.id, model_usage_id=usage.id if usage else None,
                account_snapshot_id=snapshot.id,
                benchmark_snapshot_id=benchmark.id if benchmark else None,
                reconciliation_json=json.dumps(reconciliation),
            ))
            if outcome_settings is not None:
                from app.metrics.shadow_outcomes import record_forward_outcomes

                record_forward_outcomes(
                    s, row.id, packet, decision, risk, execution,
                    reconciliation=reconciliation, model=model, usage=usage,
                    benchmark_symbol=benchmark_symbol,
                    quote_max_age_seconds=outcome_settings.quote_max_age_seconds,
                    completed_at=completed_at or datetime.now(timezone.utc),
                )
            if slot is not None:
                code = (3 if not reconciliation["reconciled"] else
                        8 if execution.agent_error else 9 if execution.review_error else 0)
                slot.cycle_id = row.id
                slot.status = "COMPLETED" if code == 0 else "FAILED"
                slot.exit_code = code
                slot.error_class = execution.agent_error or execution.review_error
                slot.finished_at = datetime.now(timezone.utc)
                slot.active_lock = None
            s.flush()
            return row.id

    def shadow_forward_outcomes(self, limit: int = 100) -> list[ShadowForwardOutcomeRow]:
        # The limit counts source cycles, so both horizons remain visible together.
        with self.session_factory() as s:
            ids = select(ShadowForwardOutcomeRow.source_cycle_id).distinct().order_by(
                ShadowForwardOutcomeRow.source_cycle_id.desc()
            ).limit(limit)
            return list(s.scalars(select(ShadowForwardOutcomeRow).where(
                ShadowForwardOutcomeRow.source_cycle_id.in_(ids)
            ).order_by(ShadowForwardOutcomeRow.source_cycle_id.desc(),
                       ShadowForwardOutcomeRow.horizon_minutes)))

    def claim_shadow_slot(self, window, claim_token: str, claimed_at: datetime) -> bool:
        try:
            with self.session_factory.begin() as s:
                s.add(ShadowScheduleSlotRow(
                    slot_key=window.key, claim_token=claim_token, active_lock=1,
                    scheduled_for=window.scheduled_for, session_date=window.session_date,
                    session_open=window.opens_at, session_close=window.closes_at,
                    claimed_at=claimed_at, status="CLAIMED",
                ))
            return True
        except IntegrityError:
            # Primary-key and unique-lock constraints arbitrate concurrent workers.
            return False

    def shadow_slot(self, slot_key: str) -> ShadowScheduleSlotRow | None:
        with self.session_factory() as s:
            return s.get(ShadowScheduleSlotRow, slot_key)

    def fail_shadow_slot(self, slot_key: str, claim_token: str, code: int, error: str) -> None:
        with self.session_factory.begin() as s:
            row = s.get(ShadowScheduleSlotRow, slot_key)
            if row is not None and row.status == "CLAIMED" and row.claim_token == claim_token:
                row.status = "FAILED"
                row.exit_code = code
                row.error_class = error
                row.finished_at = datetime.now(timezone.utc)
                row.active_lock = None

    def shadow_schedule_slots(self, limit: int = 100) -> list[ShadowScheduleSlotRow]:
        with self.session_factory() as s:
            return list(s.scalars(select(ShadowScheduleSlotRow)
                                 .order_by(ShadowScheduleSlotRow.scheduled_for.desc())
                                 .limit(limit)))

    def active_shadow_slot(self) -> ShadowScheduleSlotRow | None:
        with self.session_factory() as s:
            return s.scalar(select(ShadowScheduleSlotRow)
                            .where(ShadowScheduleSlotRow.active_lock == 1))

    def shadow_review_activity(self, now: datetime) -> tuple[int, datetime | None]:
        """Daily reviewed entries and most recent reviewed close survive restarts."""
        local = now.astimezone(ZoneInfo("America/New_York"))
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = day_start.astimezone(timezone.utc)
        with self.session_factory() as s:
            rows = list(s.scalars(select(DecisionCycleRow)
                                  .where(DecisionCycleRow.timestamp >= start - timedelta(days=1),
                                         DecisionCycleRow.timestamp <= now)))
        entries = 0
        last_close = None
        for row in rows:
            decision = json.loads(row.decision_json)
            risk = json.loads(row.risk_json)
            execution = json.loads(row.execution_json)
            if not risk["approved"] or execution.get("broker_review") is None:
                continue
            stamp = row.timestamp.replace(tzinfo=timezone.utc) if row.timestamp.tzinfo is None else row.timestamp
            if decision["action"] == "OPEN_LONG" and stamp >= start:
                entries += 1
            if decision["action"] == "CLOSE":
                last_close = max(last_close, stamp) if last_close else stamp
        return entries, last_close

    def shadow_cycle_evidence(self, cycle_id: int) -> dict:
        with self.session_factory() as s:
            evidence = s.get(ShadowCycleEvidenceRow, cycle_id)
            if evidence is None:
                return {"status": "LEGACY_UNLINKED", "model_usage": None,
                        "reconciliation": None}
            usage = s.get(ModelUsageRow, evidence.model_usage_id) if evidence.model_usage_id else None
            return {
                "status": "LINKED",
                "model_usage": {
                    "model": usage.model, "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "input_price_per_million": str(usage.input_price_per_million),
                    "output_price_per_million": str(usage.output_price_per_million),
                    "estimated_cost": str(usage.estimated_cost),
                } if usage else None,
                "reconciliation": json.loads(evidence.reconciliation_json),
            }

    def save_fill(self, order_id: str, symbol: str, notional: Decimal, price: Decimal, quantity: Decimal, invalidation: Decimal, thesis: str) -> None:
        with self.session_factory.begin() as s:
            s.add(OrderRow(external_id=order_id, symbol=symbol, side="BUY", requested_notional=notional, status="FILLED"))
            s.add(FillRow(order_external_id=order_id, symbol=symbol, price=price, quantity=quantity))
            s.add(PositionEpisodeRow(symbol=symbol, opened_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc), entry_price=price, quantity=quantity, invalidation_price=invalidation, thesis=thesis))

    def save_close(self, order_id: str, symbol: str, notional: Decimal, price: Decimal, quantity: Decimal) -> Decimal:
        from datetime import datetime, timezone

        with self.session_factory.begin() as s:
            episode = s.scalar(
                select(PositionEpisodeRow)
                .where(PositionEpisodeRow.symbol == symbol, PositionEpisodeRow.closed_at.is_(None))
                .order_by(PositionEpisodeRow.id.desc())
                .limit(1)
            )
            if episode is None:
                raise RuntimeError("no open position episode to close")
            realized = (price - Decimal(str(episode.entry_price))) * quantity
            s.add(OrderRow(external_id=order_id, symbol=symbol, side="SELL", requested_notional=notional, status="FILLED"))
            s.add(FillRow(order_external_id=order_id, symbol=symbol, price=price, quantity=quantity))
            episode.closed_at = datetime.now(timezone.utc)
            episode.exit_price = price
            episode.realized_pnl = realized
            return realized

    def save_model_usage(self, model: str, input_tokens: int, output_tokens: int, input_price: Decimal, output_price: Decimal) -> Decimal:
        cost = (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price) / Decimal("1000000")
        with self.session_factory.begin() as s:
            s.add(ModelUsageRow(model=model, input_tokens=input_tokens, output_tokens=output_tokens, input_price_per_million=input_price, output_price_per_million=output_price, estimated_cost=cost))
        return cost

    def model_cost_total(self) -> Decimal:
        with self.session_factory() as s:
            value = s.scalar(select(func.coalesce(func.sum(ModelUsageRow.estimated_cost), 0)))
            return Decimal(str(value))

    def latest_model_usage(self) -> ModelUsageRow | None:
        with self.session_factory() as s:
            return s.scalar(
                select(ModelUsageRow)
                .order_by(ModelUsageRow.id.desc())
                .limit(1)
            )

    def save_benchmark(self, symbol: str, price: Decimal) -> None:
        with self.session_factory.begin() as s:
            s.add(BenchmarkSnapshotRow(symbol=symbol, price=price))

    def benchmark_range(self, symbol: str) -> tuple[Decimal, Decimal] | None:
        with self.session_factory() as s:
            first = s.scalar(
                select(BenchmarkSnapshotRow.price)
                .where(BenchmarkSnapshotRow.symbol == symbol)
                .order_by(BenchmarkSnapshotRow.id.asc())
                .limit(1)
            )
            last = s.scalar(
                select(BenchmarkSnapshotRow.price)
                .where(BenchmarkSnapshotRow.symbol == symbol)
                .order_by(BenchmarkSnapshotRow.id.desc())
                .limit(1)
            )
            if first is None or last is None:
                return None
            return Decimal(str(first)), Decimal(str(last))

    def recent_cycles(self, limit: int = 10) -> list[DecisionCycleRow]:
        with self.session_factory() as s:
            return list(s.scalars(select(DecisionCycleRow).order_by(DecisionCycleRow.id.desc()).limit(limit)))
