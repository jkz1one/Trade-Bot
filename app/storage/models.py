from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CapitalEventRow(Base):
    __tablename__ = "capital_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    kind: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class AccountSnapshotRow(Base):
    __tablename__ = "account_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    high_watermark: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class DecisionCycleRow(Base):
    __tablename__ = "decision_cycles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    packet_json: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(64), default="v1")
    model_identifier: Mapped[str] = mapped_column(String(128))
    decision_json: Mapped[str] = mapped_column(Text)
    risk_json: Mapped[str] = mapped_column(Text)
    execution_json: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class OrderRow(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    requested_notional: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    status: Mapped[str] = mapped_column(String(32))


class FillRow(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_external_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    symbol: Mapped[str] = mapped_column(String(16))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class PositionEpisodeRow(Base):
    __tablename__ = "position_episodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    invalidation_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    thesis: Mapped[str] = mapped_column(Text)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)


class ModelUsageRow(Base):
    __tablename__ = "model_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    input_price_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    output_price_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class BenchmarkSnapshotRow(Base):
    __tablename__ = "benchmark_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    symbol: Mapped[str] = mapped_column(String(16))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class SystemEventRow(Base):
    __tablename__ = "system_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    level: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
