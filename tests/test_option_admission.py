from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.options.governor import admit_option
from app.options.models import (
    EquityHolding,
    OptionAccount,
    OptionContract,
    OptionHolding,
    OptionInstrument,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    SessionWindow,
    UnderlyingQuote,
)

D = Decimal
NOW = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)
END = NOW.replace(hour=20)


def inputs(right="CALL"):
    contract = OptionContract(
        underlying="SPY",
        underlying_kind="ETF",
        underlying_market="US_LISTED",
        root="SPY",
        right=right,
        strike="600",
        expiration=date(2026, 10, 9),
        multiplier=100,
        deliverable_kind="SHARES",
        deliverable_units=100,
        exercise_style="AMERICAN",
        settlement="PHYSICAL",
        settlement_session="PM",
        adjusted=False,
        last_trading_at=END,
        expires_at=END + timedelta(hours=1),
        settles_at=END + timedelta(days=1),
        tick_below_three=".01",
        tick_at_or_above_three=".01",
    )
    instrument = OptionInstrument(
        provider="fixture",
        instrument_id="provider-contract",
        contract=contract,
        metadata_complete=True,
        option_tradable=True,
    )
    quote = OptionQuote(
        instrument=instrument,
        source="fixture-opra",
        source_at=NOW,
        received_at=NOW,
        entitlement="REALTIME",
        complete=True,
        bid=".98",
        ask="1",
        bid_size=20,
        ask_size=20,
    )
    underlying = UnderlyingQuote(
        symbol="SPY",
        source="fixture-equity",
        source_at=NOW,
        received_at=NOW,
        entitlement="REALTIME",
        complete=True,
        bid="600",
        ask="600.01",
    )
    account = OptionAccount(
        account_id="option-paper",
        population_id="new-options-v1",
        snapshot_id="snapshot-1",
        captured_at=NOW,
        complete=True,
        reconciled=True,
        cash="1000",
        settled_cash="1000",
        reserved_cash="0",
        daily_loss_available="600",
        total_loss_available="800",
        budgets_known=True,
        working_orders=0,
        unsupported_exposure=False,
        entry_halted=False,
    )
    limits = OptionLimits(
        account_id=account.account_id,
        population_id=account.population_id,
        allowed_underlyings=("SPY",),
        provider="fixture",
        option_source="fixture-opra",
        underlying_source="fixture-equity",
        session_source="fixture-calendar",
        max_contracts=10,
        max_entry_debit="500",
        max_account_exposure="500",
        max_full_premium_loss="500",
        entry_fee_per_contract=".65",
        exit_fee_per_contract=".65",
        entry_fee_per_order="1",
        exit_fee_per_order="1",
        slippage_bps="5",
        max_spread_fraction=".10",
        minimum_underlying_price="5",
        quote_max_age_seconds=10,
        account_max_age_seconds=10,
        max_receive_lag_seconds=2,
        max_sync_seconds=2,
        approval_lifetime_seconds=5,
    )
    session = SessionWindow(
        source="fixture-calendar",
        underlying="SPY",
        opens_at=NOW.replace(hour=13, minute=30),
        entry_cutoff_at=END - timedelta(minutes=15),
        closes_at=END,
    )
    proposal = OptionProposal(
        action="OPEN_LONG",
        contract=contract,
        underlying_invalidation="599" if right == "CALL" else "601",
        thesis="Frozen test setup",
    )
    return {
        "proposal": proposal,
        "quote": quote,
        "underlying": underlying,
        "account": account,
        "limits": limits,
        "session": session,
        "now": NOW,
    }


def change(data, key, **values):
    data[key] = data[key].model_copy(update=values)
    return data


def owned(data, quantity=4):
    change(data, "proposal", action="CLOSE")
    change(
        data,
        "account",
        position=OptionHolding(
            contract=data["proposal"].contract,
            quantity=quantity,
            original_underlying_invalidation=data["proposal"].underlying_invalidation,
        ),
    )
    return data


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_call_and_put_are_fully_paid_long_contracts(right):
    data = inputs(right)
    result = admit_option(**data)
    assert result.outcome == "APPROVED" and result.action == "OPEN_LONG"
    assert result.quantity == 4 and type(result.quantity) is int
    assert result.limit_price == D("1.01")
    assert result.entry_debit == D("407.60")
    assert result.reserved_exit_fees == D("3.60")
    assert result.full_premium_loss == D("411.20")
    assert result.contract_id == data["proposal"].contract.contract_id
    assert result.valid_until == NOW + timedelta(seconds=5)
    assert result.mode == "PAPER"


def test_hold_is_a_complete_result_without_any_external_inputs():
    result = admit_option(
        OptionProposal(action="HOLD", thesis="No eligible setup"),
        None,
        None,
        None,
        None,
        None,
        now=NOW,
    )
    assert result.outcome == "HOLD" and result.quantity == 0
    assert result.reasons == () and result.contract_id is None and result.valid_until is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("strike", D("601")),
        ("right", "PUT"),
        ("root", "SPY1"),
        ("expiration", date(2026, 10, 10)),
        ("multiplier", 10),
        ("deliverable_units", 99),
        ("exercise_style", "EUROPEAN"),
        ("settlement_session", "AM"),
        ("last_trading_at", END - timedelta(minutes=1)),
        ("tick_below_three", D(".05")),
    ],
)
def test_same_provider_id_cannot_hide_foreign_or_conflicting_metadata(field, value):
    data = inputs()
    contract = data["quote"].instrument.contract.model_copy(update={field: value})
    if field == "expiration":
        contract = contract.model_copy(
            update={
                "expires_at": END + timedelta(days=1),
                "settles_at": END + timedelta(days=2),
            }
        )
    instrument = data["quote"].instrument.model_copy(update={"contract": contract})
    change(data, "quote", instrument=instrument)
    result = admit_option(**data)
    assert result.outcome == "REJECTED" and "EXACT_CONTRACT_MISMATCH" in result.reasons
    assert result.quantity == 0 and result.entry_debit == 0


def test_identity_is_scale_timezone_and_decimal_context_independent():
    contract = inputs()["proposal"].contract
    same = contract.model_copy(
        update={
            "strike": D("600.00"),
            "last_trading_at": contract.last_trading_at.astimezone(ZoneInfo("America/New_York")),
        }
    )
    with localcontext() as context:
        context.prec = 3
        assert contract.contract_id == same.contract_id
        other = contract.model_copy(update={"strike": D("600.001")})
        assert contract.contract_id != other.contract_id
    instrument = OptionInstrument(
        provider="other",
        instrument_id="different",
        contract=same,
        metadata_complete=True,
        option_tradable=True,
    )
    assert instrument.contract.contract_id == contract.contract_id


@pytest.mark.parametrize(
    "changes",
    [
        {"adjusted": True},
        {"multiplier": 10},
        {"deliverable_units": 101},
        {"settlement": "CASH"},
        {"exercise_style": "EUROPEAN"},
        {"tick_below_three": D(".03")},
        {"settlement_session": "AM"},
    ],
)
def test_unsupported_metadata_cannot_pass_when_all_sources_agree(changes):
    data = inputs()
    contract = data["proposal"].contract.model_copy(update=changes)
    change(data, "proposal", contract=contract)
    change(
        data, "quote", instrument=data["quote"].instrument.model_copy(update={"contract": contract})
    )
    assert "UNSUPPORTED_CONTRACT_METADATA" in admit_option(**data).reasons


@pytest.mark.parametrize(
    "right,stop", [("CALL", "600"), ("CALL", "601"), ("PUT", "600.01"), ("PUT", "599")]
)
def test_call_and_put_underlying_invalidation_have_opposite_geometry(right, stop):
    data = change(inputs(right), "proposal", underlying_invalidation=D(stop))
    assert "INVALID_UNDERLYING_INVALIDATION" in admit_option(**data).reasons


@pytest.mark.parametrize(
    "key,changes,reason",
    [
        ("account", {"account_id": "foreign"}, "ACCOUNT_POPULATION_MISMATCH"),
        ("account", {"population_id": "virtual-v1"}, "ACCOUNT_POPULATION_MISMATCH"),
        ("account", {"complete": False}, "ACCOUNT_NOT_RECONCILED"),
        ("account", {"reconciled": False}, "ACCOUNT_NOT_RECONCILED"),
        ("account", {"captured_at": NOW + timedelta(seconds=1)}, "STALE_OR_FUTURE_ACCOUNT"),
        ("account", {"captured_at": NOW - timedelta(seconds=10)}, "STALE_OR_FUTURE_ACCOUNT"),
        ("account", {"working_orders": 1}, "UNRESOLVED_ORDER"),
        ("account", {"unsupported_exposure": True}, "UNSUPPORTED_ACCOUNT_EXPOSURE"),
        ("account", {"entry_halted": True}, "ENTRY_HALTED"),
        ("account", {"entry_blockers": ("ALERT_BACKLOG",)}, "ALERT_BACKLOG"),
        ("account", {"budgets_known": False}, "UNKNOWN_COST_OR_LOSS_BUDGET"),
        ("limits", {"allowed_underlyings": ("QQQ",)}, "UNDERLYING_NOT_ALLOWED"),
        ("quote", {"source": "wrong-feed"}, "OPTION_SOURCE_MISMATCH"),
        ("quote", {"entitlement": "DELAYED"}, "OPTION_COVERAGE_OR_ENTITLEMENT"),
        ("quote", {"entitlement": "INDICATIVE"}, "OPTION_COVERAGE_OR_ENTITLEMENT"),
        ("quote", {"complete": False}, "OPTION_COVERAGE_OR_ENTITLEMENT"),
        ("quote", {"source_at": NOW + timedelta(seconds=1)}, "INVALID_OPTION_QUOTE_TIME"),
        ("quote", {"received_at": NOW + timedelta(seconds=1)}, "INVALID_OPTION_QUOTE_TIME"),
        ("quote", {"source_at": NOW - timedelta(seconds=10)}, "INVALID_OPTION_QUOTE_TIME"),
        ("quote", {"received_at": NOW - timedelta(seconds=1)}, "INVALID_OPTION_QUOTE_TIME"),
        ("quote", {"source_at": NOW - timedelta(seconds=3)}, "INVALID_OPTION_QUOTE_TIME"),
        ("quote", {"bid": D("1.01")}, "INVALID_OR_MISSING_EXECUTABLE_QUOTE"),
        ("quote", {"bid": None}, "INVALID_OR_MISSING_EXECUTABLE_QUOTE"),
        ("quote", {"bid": D(0)}, "INVALID_OR_MISSING_EXECUTABLE_QUOTE"),
        ("quote", {"ask": None}, "INVALID_OR_MISSING_EXECUTABLE_QUOTE"),
        ("quote", {"ask_size": 0}, "NO_EXECUTABLE_ASK_SIZE"),
        ("quote", {"bid": D(".5")}, "OPTION_SPREAD_TOO_WIDE"),
        ("underlying", {"symbol": "QQQ"}, "UNDERLYING_SOURCE_OR_SYMBOL_MISMATCH"),
        ("underlying", {"source": "untrusted"}, "UNDERLYING_SOURCE_OR_SYMBOL_MISMATCH"),
        ("underlying", {"entitlement": "UNKNOWN"}, "UNDERLYING_COVERAGE_OR_ENTITLEMENT"),
        ("underlying", {"complete": False}, "UNDERLYING_COVERAGE_OR_ENTITLEMENT"),
        ("underlying", {"bid": D("601")}, "INVALID_UNDERLYING_QUOTE"),
        ("underlying", {"source_at": NOW + timedelta(seconds=1)}, "INVALID_UNDERLYING_QUOTE"),
        ("session", {"source": "untrusted"}, "INVALID_OR_CLOSED_SESSION"),
        ("session", {"underlying": "QQQ"}, "INVALID_OR_CLOSED_SESSION"),
        ("session", {"opens_at": NOW + timedelta(seconds=1)}, "INVALID_OR_CLOSED_SESSION"),
        ("session", {"entry_cutoff_at": NOW}, "ENTRY_CUTOFF"),
    ],
)
def test_invalid_evidence_blocks_with_exact_reason(key, changes, reason):
    result = admit_option(**change(inputs(), key, **changes))
    assert result.outcome == "REJECTED" and reason in result.reasons
    assert result.quantity == result.entry_debit == result.full_premium_loss == 0


@pytest.mark.parametrize(
    "key,reason",
    [
        ("quote", "OPTION_QUOTE_MISSING"),
        ("underlying", "UNDERLYING_EVIDENCE_MISSING"),
        ("session", "SESSION_EVIDENCE_MISSING"),
    ],
)
def test_missing_inputs_are_never_created_from_clock(key, reason):
    data = inputs()
    data[key] = None
    assert reason in admit_option(**data).reasons


def test_unsynchronized_but_individually_fresh_evidence_blocks():
    data = inputs()
    change(
        data, "quote", source_at=NOW - timedelta(seconds=3), received_at=NOW - timedelta(seconds=2)
    )
    assert "UNSYNCHRONIZED_EVIDENCE" in admit_option(**data).reasons


@pytest.mark.parametrize(
    "position",
    [
        EquityHolding(symbol="QQQ", quantity=".5"),
        OptionHolding(
            contract=inputs()["proposal"].contract,
            quantity=1,
            original_underlying_invalidation="599",
        ),
        OptionHolding(
            contract=inputs("PUT")["proposal"].contract,
            quantity=1,
            original_underlying_invalidation="601",
        ),
    ],
)
def test_one_position_across_equities_calls_and_puts_and_no_averaging(position):
    assert (
        "POSITION_ALREADY_OPEN_NO_ADDS"
        in admit_option(**change(inputs(), "account", position=position)).reasons
    )


@pytest.mark.parametrize(
    "key,field,value,expected",
    [
        ("limits", "max_contracts", 1, 1),
        ("quote", "ask_size", 2, 2),
        ("limits", "max_entry_debit", D("203"), 1),
        ("limits", "max_account_exposure", D("500"), 4),
        ("limits", "max_full_premium_loss", D("206.6"), 2),
        ("account", "daily_loss_available", D("308"), 2),
        ("account", "total_loss_available", D("104.3"), 1),
        ("account", "settled_cash", D("104.3"), 1),
        ("account", "reserved_cash", D("895.7"), 1),
        ("proposal", "max_entry_debit", D("102.65"), 1),
        ("account", "daily_loss_available", D(0), 0),
        ("limits", "max_full_premium_loss", D("103.299999999999"), 0),
    ],
)
def test_every_quantity_cap_is_independent_and_never_rounds_up(key, field, value, expected):
    result = admit_option(**change(inputs(), key, **{field: value}))
    assert result.quantity == expected
    assert result.outcome == ("APPROVED" if expected else "REJECTED")


def test_frozen_ten_dollar_population_cannot_fund_one_contract():
    data = change(inputs(), "account", cash=D(10), settled_cash=D(10))
    result = admit_option(**data)
    assert result.quantity == 0 and "ONE_CONTRACT_EXCEEDS_FUNDS_OR_LIMITS" in result.reasons


def test_account_exposure_cap_and_model_request_cannot_raise_other_caps():
    data = inputs()
    change(data, "limits", max_entry_debit=D(205), max_account_exposure=D(205))
    change(data, "proposal", max_entry_debit=D(999999))
    assert admit_option(**data).quantity == 2
    change(data, "limits", max_entry_debit=D(100), max_account_exposure=D(100))
    assert admit_option(**data).quantity == 0


@pytest.mark.parametrize("budget", [D(n) / 10 for n in range(0, 5100, 137)])
def test_quantity_is_maximal_feasible_and_cash_conserving(budget):
    data = change(inputs(), "account", daily_loss_available=budget)
    result = admit_option(**data)
    caps = min(budget, D(500))
    if result.outcome == "APPROVED":
        assert result.full_premium_loss <= caps
        assert result.entry_debit <= D(500)
        assert result.entry_debit + result.reserved_exit_fees == result.full_premium_loss
        assert (result.quantity + 1) * D("102.30") + 2 > caps
    else:
        assert budget < D("104.30") and result.quantity == 0


def test_arithmetic_is_independent_of_callers_low_decimal_precision():
    data = inputs()
    normal = admit_option(**data)
    with localcontext() as context:
        context.prec = 2
        assert admit_option(**data) == normal


@pytest.mark.parametrize(
    "ask,bid,tick_low,tick_high,expected",
    [
        ("2.999", "2.998", ".01", ".10", "3.10"),
        ("2.98", "2.97", ".05", ".10", "3.00"),
        ("3.01", "3.00", ".01", ".05", "3.05"),
    ],
)
def test_adverse_buy_price_respects_tick_tiers(ask, bid, tick_low, tick_high, expected):
    data = inputs()
    contract = data["proposal"].contract.model_copy(
        update={
            "tick_below_three": D(tick_low),
            "tick_at_or_above_three": D(tick_high),
        }
    )
    change(data, "proposal", contract=contract)
    change(
        data,
        "quote",
        ask=D(ask),
        bid=D(bid),
        instrument=data["quote"].instrument.model_copy(update={"contract": contract}),
    )
    result = admit_option(**data)
    assert result.limit_price == D(expected) and result.quantity == 1


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_close_sells_only_owned_whole_contracts_at_bid_with_adverse_costs(right):
    data = owned(inputs(right))
    result = admit_option(**data)
    assert result.outcome == "APPROVED" and result.quantity == 4
    assert result.limit_price == D(".97") and result.minimum_exit_cash_change == D("384.40")
    assert result.entry_debit == result.full_premium_loss == 0
    change(data, "quote", bid_size=1)
    assert admit_option(**data).quantity == 1


def test_close_remains_available_during_entry_halt_unknown_budgets_and_missing_thesis_data():
    data = owned(inputs(), 1)
    change(
        data,
        "account",
        entry_halted=True,
        budgets_known=False,
        daily_loss_available=D(0),
        total_loss_available=D(0),
        entry_blockers=("MODEL_OFFLINE", "ALERT_BACKLOG"),
    )
    change(data, "quote", ask=None)
    data["underlying"] = None
    change(data, "session", entry_cutoff_at=NOW)
    assert admit_option(**data).outcome == "APPROVED"


@pytest.mark.parametrize(
    "change_kind,reason",
    [
        ("flat", "NO_EXACT_OWNED_OPTION"),
        ("equity", "NO_EXACT_OWNED_OPTION"),
        ("other-option", "NO_EXACT_OWNED_OPTION"),
        ("bid-size", "NO_EXECUTABLE_BID_SIZE"),
        ("missing-bid", "INVALID_OR_MISSING_EXECUTABLE_QUOTE"),
        ("pending", "UNRESOLVED_ORDER"),
        ("stale", "INVALID_OPTION_QUOTE_TIME"),
        ("fees", "CLOSE_NOT_CASH_CONSERVING"),
    ],
)
def test_close_cannot_become_opening_short_or_invented_flat(change_kind, reason):
    data = owned(inputs())
    if change_kind == "flat":
        change(data, "account", position=None)
    elif change_kind == "equity":
        change(data, "account", position=EquityHolding(symbol="SPY", quantity="4"))
    elif change_kind == "other-option":
        change(
            data,
            "account",
            position=data["account"].position.model_copy(
                update={"contract": inputs("PUT")["proposal"].contract}
            ),
        )
    elif change_kind == "bid-size":
        change(data, "quote", bid_size=0)
    elif change_kind == "missing-bid":
        change(data, "quote", bid=None)
    elif change_kind == "pending":
        change(data, "account", working_orders=1)
    elif change_kind == "stale":
        change(data, "quote", source_at=NOW - timedelta(seconds=20))
    else:
        change(data, "limits", exit_fee_per_order=D(2000))
    assert reason in admit_option(**data).reasons


def test_half_day_window_and_last_trade_bound_entry_without_weekday_guesses():
    data = inputs()
    change(
        data,
        "session",
        closes_at=NOW + timedelta(minutes=20),
        entry_cutoff_at=NOW + timedelta(minutes=5),
    )
    assert admit_option(**data).outcome == "APPROVED"
    data["now"] = NOW + timedelta(minutes=5)
    assert "ENTRY_CUTOFF" in admit_option(**data).reasons
    data["now"] = END
    assert "CONTRACT_TRADING_ENDED" in admit_option(**data).reasons


def test_spxw_cash_metadata_and_am_contract_remain_distinct_from_spy_and_pm():
    data = inputs()
    contract = data["proposal"].contract.model_copy(
        update={
            "underlying": "SPX",
            "underlying_kind": "INDEX",
            "underlying_market": "US_INDEX",
            "root": "SPXW",
            "deliverable_kind": "CASH",
            "deliverable_units": 0,
            "exercise_style": "EUROPEAN",
            "settlement": "CASH",
        }
    )
    change(data, "proposal", contract=contract)
    change(
        data, "quote", instrument=data["quote"].instrument.model_copy(update={"contract": contract})
    )
    change(data, "underlying", symbol="SPX")
    change(data, "limits", allowed_underlyings=("SPX",))
    change(data, "session", underlying="SPX")
    assert admit_option(**data).outcome == "APPROVED"
    am = contract.model_copy(
        update={
            "root": "SPX",
            "settlement_session": "AM",
            "last_trading_at": NOW - timedelta(days=1),
        }
    )
    change(data, "proposal", contract=am)
    change(data, "quote", instrument=data["quote"].instrument.model_copy(update={"contract": am}))
    assert "CONTRACT_TRADING_ENDED" in admit_option(**data).reasons
    assert am.contract_id != contract.contract_id


@pytest.mark.parametrize(
    "source_age,account_age,cutoff_delta,last_delta,expected",
    [
        (0, 0, 100, 100, 5),
        (9, 0, 100, 100, 1),
        (0, 9, 100, 100, 1),
        (0, 0, 2, 100, 2),
        (0, 0, 100, 3, 3),
    ],
)
def test_approval_lifetime_cannot_renew_expiring_evidence(
    source_age, account_age, cutoff_delta, last_delta, expected
):
    data = inputs()
    change(
        data,
        "quote",
        source_at=NOW - timedelta(seconds=source_age),
        received_at=NOW - timedelta(seconds=source_age),
    )
    change(
        data,
        "underlying",
        source_at=NOW - timedelta(seconds=source_age),
        received_at=NOW - timedelta(seconds=source_age),
    )
    change(data, "account", captured_at=NOW - timedelta(seconds=account_age))
    change(data, "session", entry_cutoff_at=NOW + timedelta(seconds=cutoff_delta))
    contract = data["proposal"].contract.model_copy(
        update={"last_trading_at": NOW + timedelta(seconds=last_delta)}
    )
    change(data, "proposal", contract=contract)
    change(
        data, "quote", instrument=data["quote"].instrument.model_copy(update={"contract": contract})
    )
    result = admit_option(**data)
    assert result.outcome == "APPROVED" and result.valid_until == NOW + timedelta(seconds=expected)


@pytest.mark.parametrize(
    "key,changes",
    [
        ("quote", {"ask_size": D("1.5")}),
        ("quote", {"bid_size": True}),
        ("quote", {"ask": float("inf")}),
        ("quote", {"ask": 1.0}),
        ("account", {"cash": D("NaN")}),
        ("account", {"reserved_cash": D(1001)}),
        ("account", {"settled_cash": D(1001)}),
        ("account", {"working_orders": "0"}),
        ("quote", {"source_at": NOW.replace(tzinfo=None)}),
        ("limits", {"mode": "LIVE"}),
        ("limits", {"allowed_underlyings": ("SPY", "SPY")}),
        ("limits", {"max_entry_debit": D(501)}),
        ("limits", {"provider": " "}),
        ("limits", {"slippage_bps": D(10000)}),
        ("limits", {"max_contracts": D("1.5")}),
        ("proposal", {"underlying_invalidation": D("Infinity")}),
        ("proposal", {"max_entry_debit": D("1e99999")}),
    ],
)
def test_forged_model_copy_inputs_are_revalidated_before_approval(key, changes):
    with pytest.raises(ValidationError):
        admit_option(**change(inputs(), key, **changes))


@pytest.mark.parametrize("quantity", [1.5, "1", D(1), True, 0, -1])
def test_owned_contract_quantity_requires_positive_native_integer(quantity):
    with pytest.raises(ValidationError):
        OptionHolding(
            contract=inputs()["proposal"].contract,
            quantity=quantity,
            original_underlying_invalidation="599",
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"quantity": 1.5},
        {"quantity": 5},
        {"account": {"cash": "999999"}},
        {"mode": "LIVE"},
        {"tools": ["place_option_order"]},
    ],
)
def test_model_cannot_supply_size_account_mode_or_tools(extra):
    with pytest.raises(ValidationError):
        OptionProposal.model_validate({**inputs()["proposal"].model_dump(), **extra})


def test_contract_chronology_and_required_metadata_cannot_be_inferred():
    values = inputs()["proposal"].contract.model_dump()
    for field in ("multiplier", "settlement_session", "deliverable_units", "last_trading_at"):
        missing = {name: value for name, value in values.items() if name != field}
        with pytest.raises(ValidationError):
            OptionContract.model_validate(missing)
    with pytest.raises(ValidationError):
        OptionContract.model_validate({**values, "expires_at": END - timedelta(seconds=1)})
    with pytest.raises(ValidationError):
        OptionContract.model_validate({**values, "expiration": date(2026, 10, 10)})


def test_inputs_are_frozen_and_json_roundtrip_preserves_all_terms():
    data = inputs()
    for value in (data["limits"], data["account"], data["proposal"], data["quote"]):
        with pytest.raises(ValidationError):
            value.mode = "LIVE"
        assert type(value).model_validate_json(value.model_dump_json()) == value
    proposal = data["proposal"]
    with pytest.raises(ValidationError):
        proposal.contract.strike = D(1)
    result = admit_option(**data)
    assert type(result).model_validate_json(result.model_dump_json()) == result


def test_naive_clock_is_rejected_before_any_admission():
    data = inputs()
    data["now"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="clock"):
        admit_option(**data)


@pytest.mark.parametrize("market", ["OTC", "NON_US", "US_INDEX"])
def test_a_whitelisted_ticker_cannot_override_unsupported_market(market):
    data = inputs()
    contract = data["proposal"].contract.model_copy(update={"underlying_market": market})
    change(data, "proposal", contract=contract)
    change(
        data, "quote", instrument=data["quote"].instrument.model_copy(update={"contract": contract})
    )
    assert "UNSUPPORTED_CONTRACT_METADATA" in admit_option(**data).reasons


@pytest.mark.parametrize("field", ["metadata_complete", "option_tradable"])
def test_incomplete_or_nontradable_instrument_does_not_grant_admission(field):
    data = inputs()
    change(data, "quote", instrument=data["quote"].instrument.model_copy(update={field: False}))
    assert "OPTION_METADATA_OR_TRADABILITY" in admit_option(**data).reasons


def test_penny_underlying_remains_ineligible_even_when_cheap_contract_fits():
    data = change(inputs("PUT"), "underlying", bid=D("4.99"), ask=D("5"))
    assert "UNDERLYING_BELOW_PRICE_FLOOR" in admit_option(**data).reasons
    with pytest.raises(ValidationError):
        OptionLimits.model_validate(
            {**data["limits"].model_dump(), "minimum_underlying_price": "1"}
        )


def test_entry_stop_cannot_reduce_full_premium_loss_or_increase_size():
    data = inputs()
    baseline = admit_option(**data)
    for stop in (D("599.99999999"), D("500")):
        result = admit_option(**change(data, "proposal", underlying_invalidation=stop))
        assert result.quantity == baseline.quantity
        assert result.full_premium_loss == baseline.full_premium_loss


def test_owned_low_value_close_can_pay_fees_from_settled_cash_without_borrowing():
    data = owned(inputs(), 1)
    change(data, "quote", bid=D(".02"), ask=None)
    change(data, "limits", exit_fee_per_order=D(5))
    result = admit_option(**data)
    assert result.outcome == "APPROVED" and result.minimum_exit_cash_change == D("-4.65")
    change(data, "account", settled_cash=D("4.64"))
    assert "CLOSE_NOT_CASH_CONSERVING" in admit_option(**data).reasons


def test_actual_instants_are_normalized_across_dst_folds():
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    quote = inputs()["underlying"]
    values = {**quote.model_dump(), "source_at": second, "received_at": first}
    normalized = UnderlyingQuote.model_validate(values)
    assert normalized.source_at > normalized.received_at
    assert normalized.source_at - normalized.received_at == timedelta(hours=1)
    data = inputs()
    data["now"] = NOW.astimezone(zone)
    assert admit_option(**data) == admit_option(**inputs())


def test_money_context_cannot_overflow_or_round_admission():
    data = inputs()
    baseline = admit_option(**data)
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.rounding = "ROUND_DOWN"
        assert admit_option(**data) == baseline
