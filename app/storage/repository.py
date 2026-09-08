from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.models import AccountState, ExecutionResult, MarketPacket, Position, RiskDecision, TradeDecision
from app.storage.models import (
    AccountSnapshotRow, BenchmarkSnapshotRow, CapitalEventRow, DecisionCycleRow,
    FillRow, ModelUsageRow, OrderRow, PositionEpisodeRow,
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

    def save_cycle(self, packet: MarketPacket, decision: TradeDecision, risk: RiskDecision, execution: ExecutionResult, model: str, latency_ms: int = 0) -> None:
        with self.session_factory.begin() as s:
            s.add(DecisionCycleRow(
                packet_json=packet.model_dump_json(), model_identifier=model,
                decision_json=decision.model_dump_json(), risk_json=risk.model_dump_json(),
                execution_json=execution.model_dump_json(), latency_ms=latency_ms,
            ))

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
