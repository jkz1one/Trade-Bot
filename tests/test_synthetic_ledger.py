from datetime import timedelta
from decimal import Decimal

import pytest

from app.config import Settings
from app.domain.models import Action, Candidate, MarketPacket, Quote, TradeDecision
from app.experiment.ledger import ExperimentConfig, LedgerState, PaperLedger
from app.risk.governor import govern
from app.robinhood.schedule import XNYSCalendar
from tests.test_shadow_outcomes import START

D = Decimal


def decision(action=Action.OPEN_LONG, **changes):
    return TradeDecision(
        action=action,
        symbol=None if action == Action.HOLD else "AAPL",
        confidence=0.8,
        setup_quality=0.8,
        desired_exposure_fraction=0.5,
        invalidation_price=98,
        thesis="Quoted evidence",
        invalidation_reason="Original stop",
        why_now="Observed opportunity",
        **changes,
    )


def packet(at=START, bid=100, ask="100.10", quote_time=None, missing=()):
    config = ExperimentConfig.capture(Settings(), "test-model")
    account = PaperLedger(
        config, LedgerState(cash=10, high_watermark=10, benchmark_cash=10)
    ).account()
    return MarketPacket(
        as_of=at,
        account=account,
        candidates=[
            Candidate(
                quote=Quote(symbol=s, timestamp=quote_time or at, bid=bid, ask=ask, last=bid),
                atr_fraction=".01",
                realized_vol_fraction=".01",
            )
            for s in ("AAPL", "SPY")
            if s not in missing
        ],
    )


def prepared(at=START, *, settings=None, fee=0, slip=5):
    config = ExperimentConfig.capture(
        settings or Settings(), "test-model", fee_per_fill=D(fee), slippage_bps=D(slip)
    )
    ledger = PaperLedger(config, LedgerState(cash=10, high_watermark=10, benchmark_cash=10))
    p = packet(at)
    window = XNYSCalendar().current_window(at)
    ledger.prepare(p, window)
    return ledger, p, window


def entry(ledger, p, window, **kwargs):
    risk = ledger.propose(decision(**kwargs), p, p.as_of + timedelta(seconds=1), window)
    assert risk.approved, risk.rejection_reasons
    ledger.state.pending.source_cycle_id = 17
    return risk


def advance(ledger, at, **kwargs):
    # Restart before every transition; only persisted state carries across cycles.
    ledger = PaperLedger(
        ledger.config, LedgerState.model_validate_json(ledger.state.model_dump_json())
    )
    p = packet(at, **kwargs)
    ledger.prepare(p, XNYSCalendar().current_window(at))
    return ledger, p


def test_sequential_fills_cash_fees_benchmark_and_all_model_costs():
    ledger, p, window = prepared(fee=".001")
    ledger.charge_model(100, 40, attempted=True)
    entry(ledger, p, window)
    assert ledger.state.position is None and not ledger.fills
    ledger, p = advance(ledger, START + timedelta(minutes=15))
    pos = ledger.state.position
    assert pos and ledger.fills[0]["source_cycle_id"] == 17
    assert ledger.fills[0]["price"] == str(D("100.10") * D("1.0005"))
    assert pos.quantity.as_tuple().exponent == -8
    assert ledger.account().position == pos
    assert ledger.state.cash + pos.quantity * pos.entry_price + ledger.state.fees_paid == 10
    ledger.charge_model(100, 40, attempted=True)
    result = ledger.propose(
        decision(Action.CLOSE),
        p,
        p.as_of + timedelta(seconds=1),
        XNYSCalendar().current_window(p.as_of),
    )
    assert result.approved
    ledger.state.pending.source_cycle_id = 18
    ledger, p = advance(ledger, START + timedelta(minutes=30), bid=102, ask="102.10")
    ledger.charge_model(100, 40, attempted=True)  # HOLD costs count too.
    ledger.propose(
        decision(Action.HOLD),
        p,
        p.as_of + timedelta(seconds=1),
        XNYSCalendar().current_window(p.as_of),
    )
    assert ledger.fills[0]["reason"] == "MODEL_CLOSE"
    assert ledger.fills[0]["source_cycle_id"] == 18
    assert ledger.state.position is None
    assert ledger.state.cash == 10 + pos.quantity * (D(102) * D(".9995") - pos.entry_price) - D(
        ".002"
    )
    s = ledger.snapshot()
    assert D(s["net_after_model_cost_equity"]) == ledger.state.cash - D(".00009")
    assert D(
        s["benchmark_liquidation_equity"]
    ) == ledger.state.benchmark_cash + ledger.state.benchmark_quantity * D(102) * D(".9995") - D(
        ".001"
    )
    assert (
        D(s["net_excess_fraction"])
        == (D(s["net_after_model_cost_equity"]) - D(s["benchmark_liquidation_equity"])) / 10
    )
    ledger.check()


@pytest.mark.parametrize("kind", ["same", "stale", "future", "naive", "crossed", "missing"])
def test_unusable_quotes_never_fill_or_create_fresh_marks(kind):
    ledger, p, w = prepared()
    entry(ledger, p, w)
    at = START + timedelta(minutes=15)
    options = {
        "same": {"quote_time": START + timedelta(seconds=1)},
        "stale": {"quote_time": at - timedelta(seconds=121)},
        "future": {"quote_time": at + timedelta(seconds=1)},
        "naive": {"quote_time": at.replace(tzinfo=None)},
        "crossed": {"ask": 99},
        "missing": {"missing": ("AAPL",)},
    }[kind]
    ledger, _ = advance(ledger, at, **options)
    assert ledger.state.position is None and ledger.state.pending is not None
    assert not ledger.fills and not ledger.ready
    assert "WAITING_FOR_FRESH_FORWARD_QUOTE" in ledger.events


def test_expiry_and_price_gap_revalidate_without_backdating():
    ledger, p, w = prepared()
    entry(ledger, p, w)
    late, _ = advance(ledger, START + timedelta(minutes=30))
    assert late.state.pending is None and late.state.position is None
    assert "PROPOSAL_EXPIRED" in late.events
    fallen, _ = advance(ledger, START + timedelta(minutes=15), bid=97, ask="97.10")
    assert fallen.state.position is None and not fallen.fills
    assert fallen.events
    tomorrow, _ = advance(ledger, START + timedelta(days=1))
    assert tomorrow.state.position is None and tomorrow.state.pending is None


def test_gap_stop_uses_actual_bid_and_stop_cannot_be_widened():
    ledger, p, w = prepared()
    entry(ledger, p, w)
    ledger, p = advance(ledger, START + timedelta(minutes=15))
    original = ledger.state.position
    result = ledger.propose(
        decision(), p, p.as_of + timedelta(seconds=1), XNYSCalendar().current_window(p.as_of)
    )
    assert "AVERAGING_DOWN_PROHIBITED" in result.rejection_reasons
    assert ledger.state.position.original_invalidation == 98
    ledger, _ = advance(ledger, START + timedelta(minutes=30), bid=95, ask="95.10")
    assert ledger.state.position is None
    assert ledger.fills[0]["reason"] == "INVALIDATION"
    assert D(ledger.fills[0]["price"]) == D(95) * D(".9995")
    assert ledger.state.cash == 10 + original.quantity * (D(95) * D(".9995") - original.entry_price)


@pytest.mark.parametrize("overnight", [False, True])
def test_session_exit_and_next_day_catchup(overnight):
    ledger, p, w = prepared()
    entry(ledger, p, w, hold_overnight=overnight)
    ledger, _ = advance(ledger, START + timedelta(minutes=15))
    close_slot = w.closes_at - timedelta(minutes=15)
    closed, _ = advance(ledger, close_slot)
    assert bool(closed.state.position) == overnight
    if not overnight:
        assert closed.fills[0]["reason"] == "SESSION_EXIT"
    caught_up, _ = advance(ledger, START + timedelta(days=1))
    assert bool(caught_up.state.position) == overnight
    if not overnight:
        assert caught_up.fills[0]["reason"] == "MISSED_SESSION_EXIT"


def test_no_new_intents_when_last_slot_or_model_finishes_after_close():
    at = XNYSCalendar().current_window(START).closes_at - timedelta(minutes=15)
    ledger, p, w = prepared(at)
    result = ledger.propose(decision(), p, at + timedelta(seconds=1), w)
    assert not result.approved and "NO_FORWARD_SESSION_SLOT" in result.rejection_reasons
    ledger, p, w = prepared()
    assert not ledger.propose(decision(), p, w.closes_at, w).approved


def test_cooldown_and_daily_entries_survive_restart():
    settings = Settings(max_daily_entries=1, exit_cooldown_minutes=30)
    ledger, p, w = prepared(settings=settings)
    entry(ledger, p, w)
    ledger, p = advance(ledger, START + timedelta(minutes=15))
    ledger, p = advance(ledger, START + timedelta(minutes=30), bid=97, ask="97.10")
    p = packet(p.as_of)
    result = ledger.risk(decision(), p, p.as_of)
    assert not result.approved
    assert {"EXIT_COOLDOWN", "DAILY_ENTRY_LIMIT"} <= set(result.rejection_reasons)
    ledger, p = advance(ledger, START + timedelta(days=1))
    assert ledger.state.daily_entries == 0
    assert ledger.risk(decision(), p, p.as_of).approved


def test_fee_and_slippage_reserved_inside_deterministic_risk():
    ledger, p, w = prepared(fee=".01")
    result = entry(ledger, p, w)
    from app.risk.policy import policy_for_equity

    budget = (
        ledger.account().equity
        * policy_for_equity(ledger.account().equity).max_risk_fraction
        * result.drawdown_modifier
        * result.confidence_modifier
    )
    assert result.planned_risk_dollars <= budget
    ledger, _ = advance(ledger, START + timedelta(minutes=15))
    assert ledger.state.cash >= 0
    ledger.check()


def test_unknown_usage_nulls_economics_blocks_entries_without_inventing_zero():
    ledger, p, w = prepared()
    assert ledger.charge_model(0, 0, attempted=False) is None
    assert ledger.state.unknown_model_calls == 0
    ledger.charge_model(0, 0, attempted=True)
    ledger.propose(decision(), p, p.as_of + timedelta(seconds=1), w)
    assert ledger.state.pending is None and ledger.state.unknown_model_calls == 1
    report = ledger.snapshot()
    assert report["net_after_model_cost_equity"] is None and report["net_excess_fraction"] is None
    assert report["gross_liquidation_equity"] == "10"


def test_stale_held_position_nulls_equity_but_cash_is_preserved():
    ledger, p, w = prepared()
    entry(ledger, p, w)
    ledger, p = advance(ledger, START + timedelta(minutes=15))
    cash = ledger.state.cash
    ledger, _ = advance(ledger, START + timedelta(minutes=30), missing=("AAPL",))
    assert ledger.state.cash == cash and ledger.state.position is not None
    assert ledger.snapshot()["gross_liquidation_equity"] is None and not ledger.ready


@pytest.mark.parametrize("action", [Action.OPEN_LONG, Action.CLOSE])
@pytest.mark.parametrize("invalid", ["future", "naive"])
def test_governor_rejects_invalid_quote_time_with_injected_clock(action, invalid):
    _ledger, p, _ = prepared()
    if action == Action.CLOSE:
        from app.domain.models import Position

        p.account.position = Position(
            symbol="AAPL",
            quantity=".01",
            entry_price=100,
            current_price=100,
            original_invalidation=98,
            thesis="Test",
            opened_at=START,
        )
    p.candidates[0].quote.timestamp = (
        START + timedelta(seconds=1) if invalid == "future" else START.replace(tzinfo=None)
    )
    result = govern(decision(action), p, Settings(), now=START)
    assert not result.approved
    assert (
        "FUTURE_QUOTE" if invalid == "future" else "INVALID_QUOTE_TIME"
    ) in result.rejection_reasons


def test_replay_and_negative_usage_are_rejected():
    ledger, p, w = prepared()
    with pytest.raises(ValueError, match="advance time"):
        ledger.prepare(p, w)
    with pytest.raises(ValueError, match="Negative"):
        ledger.charge_model(-1, 0, attempted=True)
