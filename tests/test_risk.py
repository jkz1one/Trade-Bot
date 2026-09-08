from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from app.domain.models import AccountState, Action, Candidate, Horizon, MarketPacket, Quote, TradeDecision
from app.risk.governor import govern
from app.risk.policy import policy_for_equity


def packet(equity="10", high=None, price="10", ask="10.01", atr="0.02", tradable=True, timestamp=None, position=None):
    e=Decimal(equity); h=Decimal(high or equity)
    q=Quote(symbol="ABC", timestamp=timestamp or datetime.now(timezone.utc), bid=Decimal(price), ask=Decimal(ask), last=Decimal(price), fractional_tradable=tradable)
    c=Candidate(quote=q, atr_fraction=Decimal(atr), realized_vol_fraction=Decimal("0.02"))
    a=AccountState(equity=e,cash=e,buying_power=e,high_watermark=h,position=position)
    return MarketPacket(as_of=datetime.now(timezone.utc),account=a,candidates=[c])


def open_decision(exposure=0.9, invalidation="9.70", confidence=.9):
    return TradeDecision(action=Action.OPEN_LONG,symbol="ABC",confidence=confidence,setup_quality=.9,horizon=Horizon.INTRADAY,desired_exposure_fraction=exposure,invalidation_price=Decimal(invalidation),thesis="Valid test thesis",invalidation_reason="Price breaks structure",evidence=["test"],risks=["test"],why_now="test timing")

@pytest.mark.parametrize("equity,mode",[("10","MICRO"),("25","SMALL"),("100","GROWTH"),("1000","SCALE"),("10000","PRESERVATION")])
def test_bankroll_tiers(equity,mode):
    assert policy_for_equity(Decimal(equity)).name == mode

def test_agent_cannot_control_final_notional(settings):
    p=packet("10",price="10",ask="10.01",atr="0.02")
    d=open_decision(exposure=1.0,invalidation="9.99")
    r=govern(d,p,settings)
    assert r.approved
    assert r.approved_notional <= Decimal("9")
    assert r.approved_notional < r.requested_notional
    assert "AGENT_NOTIONAL_CLIPPED" in r.constraint_hits

def test_minimum_order_never_rounded_up_past_risk(settings):
    p=packet("10",price="100",ask="100.10",atr="0.50")
    d=open_decision(exposure=.9,invalidation="10")
    r=govern(d,p,settings)
    assert not r.approved
    assert "MIN_NOTIONAL_EXCEEDS_RISK_BUDGET" in r.rejection_reasons

def test_drawdown_shutdown(settings):
    p=packet("5",high="10",price="10",ask="10.01")
    r=govern(open_decision(),p,settings)
    assert not r.approved
    assert "DRAWDOWN_SHUTDOWN" in r.rejection_reasons

def test_stale_quote_fails_closed(settings):
    old=datetime.now(timezone.utc)-timedelta(minutes=10)
    r=govern(open_decision(),packet(timestamp=old),settings)
    assert not r.approved and "STALE_QUOTE" in r.rejection_reasons

def test_nonfractional_fails_closed(settings):
    r=govern(open_decision(),packet(tradable=False),settings)
    assert not r.approved and "NOT_FRACTIONAL_TRADABLE" in r.rejection_reasons

def test_insufficient_buying_power(settings):
    p=packet(); p.account.buying_power=Decimal("0.50")
    r=govern(open_decision(),p,settings)
    assert not r.approved and "MIN_NOTIONAL_EXCEEDS_RISK_BUDGET" in r.rejection_reasons

def test_hold_never_executes(settings):
    d=TradeDecision(action=Action.HOLD,confidence=.5,setup_quality=.5,thesis="No edge",invalidation_reason="No position",why_now="Wait")
    r=govern(d,packet(),settings)
    assert not r.approved and r.approved_notional == 0


def test_too_tight_invalidation_uses_volatility_floor(settings):
    p = packet("10", price="10", ask="10.01", atr="0.10")
    d = open_decision(exposure=1.0, invalidation="10.00")
    r = govern(d, p, settings)
    assert r.effective_loss_distance >= Decimal("0.035")
    assert r.approved_notional <= Decimal("9")

def test_drawdown_progressively_reduces_risk(settings):
    healthy = govern(open_decision(exposure=1.0, invalidation="9.00"), packet("10", high="10"), settings)
    drawn = govern(open_decision(exposure=1.0, invalidation="9.00"), packet("7", high="10"), settings)
    assert Decimal("0") < drawn.drawdown_modifier < Decimal("1")
    assert drawn.planned_risk_fraction < healthy.planned_risk_fraction

def test_same_symbol_second_entry_is_averaging_down(settings):
    from app.domain.models import Position
    pos = Position(
        symbol="ABC", quantity=Decimal("0.2"), entry_price=Decimal("10"),
        current_price=Decimal("9.5"), original_invalidation=Decimal("9"),
        thesis="existing", opened_at=datetime.now(timezone.utc),
    )
    r = govern(open_decision(), packet(position=pos), settings)
    assert not r.approved
    assert "AVERAGING_DOWN_PROHIBITED" in r.rejection_reasons


def test_close_is_allowed_even_when_new_entries_halted(settings):
    from app.domain.models import Position
    pos = Position(symbol="ABC", quantity=Decimal("0.2"), entry_price=Decimal("10"), current_price=Decimal("10"), original_invalidation=Decimal("9"), thesis="existing", opened_at=datetime.now(timezone.utc))
    p = packet(position=pos)
    d = TradeDecision(action=Action.CLOSE, symbol="ABC", confidence=.7, setup_quality=.7, thesis="Exit", invalidation_reason="Exit", why_now="Risk reduction")
    r = govern(d, p, settings, system_enabled=False)
    assert r.approved
    assert r.approved_notional > 0

def test_reduce_fails_closed_in_slice1(settings):
    d = TradeDecision(action=Action.REDUCE, symbol="ABC", confidence=.7, setup_quality=.7, thesis="Reduce", invalidation_reason="Reduce", why_now="Risk reduction")
    r = govern(d, packet(), settings)
    assert not r.approved
    assert "REDUCE_NOT_IMPLEMENTED_SLICE1" in r.rejection_reasons
