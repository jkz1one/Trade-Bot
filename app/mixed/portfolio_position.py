"""Explicit portfolio management protocol; advice always names one original play."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from app.options.models import paper_market_evidence
from app.mixed.accounting import reconstruct
from app.mixed.native_models import StockProtection
from app.mixed.portfolio_accounting import PortfolioHistory
from app.mixed.stock_models import StockIntent, StockPosition, StockQuote
from app.options.degen import DegenScan
from app.options.engine import fingerprint
from app.options.lifecycle import OptionExecutionPolicy, OptionIntent, OptionPosition
from app.options.models import (
    Name,
    OptionAccount,
    OptionLimits,
    OptionQuote,
    OptionRecord,
    SessionWindow,
    UnderlyingObservation,
)
from app.options.position_reasoning import (
    Digest,
    PositionPlan,
    PositionReasoningPolicy,
    PositionReview,
)
from app.options.scope_context import ScopeContextScan


class PortfolioPositionPacket(OptionRecord):
    version: Literal["portfolio-position-packet-v2"] = "portfolio-position-packet-v2"
    mode: Literal["PAPER"] = "PAPER"
    play_id: Name
    decision_id: Digest
    cycle_key: Name
    model_configuration_hash: Digest
    as_of: datetime
    valid_until: datetime
    position_revision: int = Field(gt=0, strict=True)
    position: StockPosition | OptionPosition
    entry: StockIntent | OptionIntent
    original_decision: dict[str, JsonValue] | None = None
    original_context: dict[str, JsonValue] | None = None
    protection: StockProtection | OptionPosition
    history: PortfolioHistory
    account: OptionAccount
    quote: StockQuote | OptionQuote
    underlying: UnderlyingObservation | None
    scan: DegenScan | ScopeContextScan
    session: SessionWindow
    limits: OptionLimits
    execution_policy: OptionExecutionPolicy
    policy: PositionReasoningPolicy
    evidence_ids: tuple[Digest, Digest, Digest, Digest, Digest, Digest]

    @model_validator(mode="after")
    def bound(self):
        held = reconstruct(self.history).ledger.positions.get(self.play_id)
        e, p = self.entry, self.position
        stock = isinstance(e, StockIntent)
        if (
            held is None
            or held != p
            or self.play_id != e.client_id
            or e.side != "BUY"
            or self.play_id != p.entry_client_id
            or e.instrument != self.quote.instrument
            or stock != isinstance(p, StockPosition)
            or stock != isinstance(self.protection, StockProtection)
            or self.cycle_key
            != "position:" + str(int(self.as_of.timestamp()) // 300) + ":" + self.play_id
            or not self.as_of
            < self.valid_until
            <= min(e.exit_at, self.as_of + timedelta(seconds=self.policy.max_lease_seconds))
            or self.valid_until.timestamp() > (int(self.as_of.timestamp()) // 300 + 1) * 300
            or self.history.captured_at != self.as_of
            or self.execution_policy.mixed_owner is None
            or self.execution_policy.mixed_owner.portfolio is None
            or self.execution_policy.mixed_owner.reasoning is None
            or self.scan.evaluated_at != self.as_of
            or self.scan.issues
            or self.limits != self.history.policy.options
            or self.evidence_ids
            != tuple(
                fingerprint(x) for x in (p, e, self.account, self.quote, self.protection, self.scan)
            )
        ):
            raise ValueError("Exact original portfolio play and completed context required")
        if stock:
            if (
                p.entry != e
                or self.protection.entry_client_id != self.play_id
                or self.underlying is not None
            ):
                raise ValueError("Original stock identity required")
        elif (
            p.contract != e.instrument.contract
            or self.protection.entry_client_id != self.play_id
            or self.protection.quantity != p.quantity
            or self.protection.basis != p.basis
            or self.underlying is None
            or self.underlying.symbol != p.contract.underlying
        ):
            raise ValueError("Original option identity and protection required")
        if isinstance(self.scan, DegenScan) and (
            self.scan.completed_through is None
            or self.scan.higher_timeframe_through is None
            or not self.scan.higher_timeframe_through <= self.scan.completed_through <= self.as_of
            or self.as_of - self.scan.completed_through >= timedelta(seconds=300)
            or self.as_of - self.scan.higher_timeframe_through >= timedelta(seconds=900)
        ):
            raise ValueError("Original completed current management context required")
        return self


def review(packet, plan, *, position, account, quote, underlying, now, protection=None):
    packet = PortfolioPositionPacket.model_validate(packet.model_dump())
    plan = PositionPlan.model_validate(plan.model_dump())
    guard = protection or packet.protection

    def out(status, reason, **kwargs):
        return PositionReview(
            outcome=status, reasons=(reason,), packet_hash=fingerprint(packet), plan=plan, **kwargs
        )

    if (
        plan.packet_hash != fingerprint(packet)
        or plan.decision_id != packet.decision_id
        or plan.entry_client_id != packet.play_id
        or plan.position_revision != packet.position_revision
        or not {packet.evidence_ids[0], packet.evidence_ids[5]}
        <= set(plan.evidence_ids)
        <= set(packet.evidence_ids)
    ):
        return out("REJECTED", "PORTFOLIO_PLAN_IDENTITY_CHANGED")
    stock = isinstance(packet.entry, StockIntent)
    if guard.exit_reason or now >= packet.entry.exit_at:
        return out("MANDATORY_EXIT", "PORTFOLIO_PROTECTION_PRECEDES_ADVICE")
    if (
        position != packet.position
        or guard != packet.protection
        or quote is None
        or quote.instrument != packet.entry.instrument
        or quote.source_at < packet.quote.source_at
        or not packet.as_of <= now < packet.valid_until
        or not account.reconciled
        or not account.complete
        or account.entry_halted
        or account.entry_blockers
        or account.working_orders
        or not account.budgets_known
        or not timedelta(0)
        <= now - account.captured_at
        < timedelta(seconds=packet.limits.account_max_age_seconds)
    ):
        return out("REJECTED", "PORTFOLIO_CURRENT_MANAGEMENT_EVIDENCE_CHANGED")
    from app.options.governor import _fresh

    limits = packet.execution_policy.mixed_owner.stocks if stock else packet.limits
    if (
        not quote.complete
        or not paper_market_evidence(quote)
        or quote.bid is None
        or quote.bid <= 0
        or quote.bid_size is None
        or quote.bid_size < position.quantity
        or quote.source != (limits.quote_source if stock else limits.option_source)
        or not _fresh(
            quote.source_at,
            quote.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        return out("REJECTED", "PORTFOLIO_FRESH_EXECUTABLE_QUOTE_REQUIRED")
    if stock:
        stop = guard.invalidation
        if guard.issue or not stop < quote.bid < packet.entry.original_target:
            return out("MANDATORY_EXIT", "PORTFOLIO_STOCK_PROTECTION_REQUIRED")
    else:
        from app.options.protection import assess_position

        checked = assess_position(
            guard, quote, underlying, packet.limits, packet.execution_policy, now=now
        )
        if checked.exit_reason:
            return out("MANDATORY_EXIT", checked.exit_reason)
        if checked.supervision_issue:
            return out("REJECTED", checked.supervision_issue)
        stop = guard.tightened_underlying_invalidation
    if plan.action == "MAINTAIN":
        return out("MAINTAIN", "MODEL_MAINTAIN")
    if plan.action == "TIGHTEN":
        price = plan.underlying_invalidation
        valid = (
            (stop < price < quote.bid)
            if stock
            else (
                stop < price < underlying.bid
                if position.contract.right == "CALL"
                else underlying.ask < price < stop
            )
        )
        if not valid:
            return out("REJECTED", "PORTFOLIO_STOP_CANNOT_WIDEN_OR_CROSS")
        return out("ELIGIBLE", "PORTFOLIO_EXACT_PLAY_TIGHTEN", tightened_invalidation=price)
    return out("ELIGIBLE", "PORTFOLIO_EXACT_PLAY_FULL_EXIT")
