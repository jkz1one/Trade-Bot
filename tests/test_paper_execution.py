from datetime import datetime, timezone
from decimal import Decimal
from app.domain.models import Action, Horizon, Quote, RiskDecision, TradeDecision


def test_paper_fill_uses_governor_notional(broker):
    d=TradeDecision(action=Action.OPEN_LONG,symbol="ABC",confidence=.9,setup_quality=.9,horizon=Horizon.INTRADAY,desired_exposure_fraction=1,invalidation_price=Decimal("9"),thesis="x",invalidation_reason="x",why_now="x")
    r=RiskDecision(approved=True,requested_notional=Decimal("10"),approved_notional=Decimal("2"),planned_risk_dollars=Decimal("0.2"),planned_risk_fraction=Decimal("0.02"),effective_loss_distance=Decimal("0.1"),risk_mode="MICRO",drawdown_modifier=Decimal("1"),confidence_modifier=Decimal("1"))
    q=Quote(symbol="ABC",timestamp=datetime.now(timezone.utc),bid=Decimal("9.99"),ask=Decimal("10"),last=Decimal("10"))
    x=broker.execute(d,r,q)
    assert x.status == "FILLED"
    assert x.notional == Decimal("2")
    state = broker.account_state({"ABC": q})
    assert state.position.quantity * state.position.entry_price == Decimal("2")
    assert state.position.market_value == Decimal("1.998")  # marked at executable bid
    assert state.cash == Decimal("8")


def test_idempotent_retry_does_not_duplicate_fill(broker):
    d=TradeDecision(action=Action.OPEN_LONG,symbol="ABC",confidence=.9,setup_quality=.9,horizon=Horizon.INTRADAY,desired_exposure_fraction=1,invalidation_price=Decimal("9"),thesis="x",invalidation_reason="x",why_now="x")
    r=RiskDecision(approved=True,requested_notional=Decimal("10"),approved_notional=Decimal("2"),planned_risk_dollars=Decimal("0.2"),planned_risk_fraction=Decimal("0.02"),effective_loss_distance=Decimal("0.1"),risk_mode="MICRO",drawdown_modifier=Decimal("1"),confidence_modifier=Decimal("1"))
    q=Quote(symbol="ABC",timestamp=datetime.now(timezone.utc),bid=Decimal("9.99"),ask=Decimal("10"),last=Decimal("10"))
    first = broker.execute(d, r, q, idempotency_key="same-proposal")
    second = broker.execute(d, r, q, idempotency_key="same-proposal")
    assert first == second
    assert broker.account_state().cash == Decimal("8")


def test_close_realizes_pnl_and_restart_reconstructs(repo, settings):
    from app.broker.paper import PaperBroker
    broker = PaperBroker(repo, settings.starting_capital)
    q_open=Quote(symbol="ABC",timestamp=datetime.now(timezone.utc),bid=Decimal("9.99"),ask=Decimal("10"),last=Decimal("10"))
    d_open=TradeDecision(action=Action.OPEN_LONG,symbol="ABC",confidence=.9,setup_quality=.9,horizon=Horizon.INTRADAY,desired_exposure_fraction=1,invalidation_price=Decimal("9"),thesis="x",invalidation_reason="x",why_now="x")
    r_open=RiskDecision(approved=True,requested_notional=Decimal("2"),approved_notional=Decimal("2"),planned_risk_dollars=Decimal("0.2"),planned_risk_fraction=Decimal("0.02"),effective_loss_distance=Decimal("0.1"),risk_mode="MICRO",drawdown_modifier=Decimal("1"),confidence_modifier=Decimal("1"))
    broker.execute(d_open, r_open, q_open, idempotency_key="open")

    restarted = PaperBroker(repo, settings.starting_capital)
    assert restarted.position is not None
    assert restarted.cash == Decimal("8")

    q_close=Quote(symbol="ABC",timestamp=datetime.now(timezone.utc),bid=Decimal("11"),ask=Decimal("11.01"),last=Decimal("11"))
    d_close=TradeDecision(action=Action.CLOSE,symbol="ABC",confidence=.8,setup_quality=.8,horizon=Horizon.INTRADAY,thesis="Exit",invalidation_reason="Thesis complete",why_now="Take exit")
    r_close=RiskDecision(approved=True,requested_notional=Decimal("2.2"),approved_notional=Decimal("2.2"),planned_risk_dollars=Decimal("0"),planned_risk_fraction=Decimal("0"),effective_loss_distance=Decimal("0"),risk_mode="MICRO",drawdown_modifier=Decimal("1"),confidence_modifier=Decimal("0.9"))
    result = restarted.execute(d_close, r_close, q_close, idempotency_key="close")
    assert result.status == "FILLED"
    assert restarted.position is None
    assert restarted.cash == Decimal("10.2")
    assert restarted.realized_pnl == Decimal("0.2")

    restarted_again = PaperBroker(repo, settings.starting_capital)
    assert restarted_again.position is None
    assert restarted_again.cash == Decimal("10.2")
    assert restarted_again.realized_pnl == Decimal("0.2")
