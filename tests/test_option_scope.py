"""Scope coverage proof deliberately stops before setup, account or order authority."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from app.options.degen import DegenBar
from app.options.models import OptionContract, OptionInstrument, OptionQuote
from app.options.scope import (
    SCOPE_GROUPS,
    ScopeEvidence,
    ScopeHistory,
    ScopePreflightInput,
    ScopePreflightPolicy,
    ScopeSession,
    preflight_scope,
)
from app.options.selection import ContractMetadata

AT = datetime(2026, 10, 9, 14, 0, 1, tzinfo=UTC)
D = Decimal


def policy(**changes):
    return ScopePreflightPolicy.model_validate(
        {
            "sources": [
                {"kind": kind, "source": "fixture-" + kind, "max_age_seconds": 30}
                for kind in SCOPE_GROUPS
            ],
            "history_sources": [
                {"symbol": s, "source": "fixture-" + s} for s in ("SPX", "SPY", "QQQ")
            ],
            "session_source": "fixture-index-calendar",
            "provider": "fixture-provider",
            "metadata_source": "fixture-metadata",
            "quote_source": "fixture-quote",
            "max_receive_lag_seconds": 2,
            "max_evidence_skew_seconds": 2,
            "max_history_age_seconds": 10,
            "max_contract_age_seconds": 10,
            "max_spread_fraction": ".15",
        }
        | changes
    )


def frame(*, now=AT, right="CALL", early_close=False):
    def clock(hour, minute=0):
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    opened = clock(13, 30)
    close = clock(17 if early_close else 20)
    session = ScopeSession(
        source="fixture-index-calendar",
        evidence_hash="a" * 64,
        session_date=now.date(),
        opens_at=opened,
        entry_starts_at=clock(13, 45),
        entry_cutoff_at=clock(16, 30) if early_close else clock(18, 30),
        protect_at=close - timedelta(minutes=15),
        closes_at=close,
    )
    common = {"source_at": now, "received_at": now, "complete": True, "entitlement": "REALTIME"}
    instrument = OptionInstrument(
        provider="fixture-provider",
        instrument_id="exact-SPXW-call" if right == "CALL" else "exact-SPXW-put",
        metadata_complete=True,
        option_tradable=True,
        contract=OptionContract(
            underlying="SPX",
            underlying_kind="INDEX",
            underlying_market="US_INDEX",
            root="SPXW",
            right=right,
            strike="6000",
            expiration=now.date(),
            multiplier=100,
            deliverable_kind="CASH",
            deliverable_units=0,
            exercise_style="EUROPEAN",
            settlement="CASH",
            settlement_session="PM",
            last_trading_at=close,
            expires_at=close,
            settles_at=close + timedelta(days=1),
            adjusted=False,
            tick_below_three=".05",
            tick_at_or_above_three=".10",
        ),
    )
    return ScopePreflightInput(
        session=session,
        evidence=tuple(
            ScopeEvidence(
                **common,
                source="fixture-" + kind,
                kind=kind,
                payload_hash=f"{n:064x}",
                status="AVAILABLE",
            )
            for n, kind in enumerate(SCOPE_GROUPS, 1)
        ),
        histories=tuple(
            ScopeHistory(
                **common,
                source="fixture-" + symbol,
                symbol=symbol,
                bars=tuple(
                    DegenBar(
                        begins_at=opened + timedelta(minutes=5 * n),
                        open="6000",
                        high="6002",
                        low="5999",
                        close="6001",
                        volume=0,  # Index volume is not synthesized or used for this coverage gate.
                        interpolated=False,
                    )
                    for n in range(int((now - opened).total_seconds() // 300))
                ),
            )
            for symbol in ("SPX", "SPY", "QQQ")
        ),
        metadata=ContractMetadata(
            **common,
            source="fixture-metadata",
            instrument=instrument,
            delta=".99" if right == "CALL" else "-.99",
            greek_provenance="OBSERVED",
            volume=None,
            open_interest=None,
        ),
        quote=OptionQuote(
            **common,
            source="fixture-quote",
            instrument=instrument,
            bid="1.95",
            ask="2.00",
            bid_size=2,
            ask_size=3,
        ),
    )


def codes(f, *, p=None, now=AT):
    result = preflight_scope(f, p or policy(), now=now)
    assert result.status == "BLOCKED"
    assert result.authority is False and result.live_enabled is False
    return {(b.subject, b.code) for b in result.blockers}


def replace(f, key, value):
    return f.model_copy(update={key: value})


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("early_close", [False, True])
def test_complete_coverage_is_not_a_candidate_or_authority(right, early_close, monkeypatch):
    import builtins
    import socket
    import sqlite3

    f, p = frame(right=right, early_close=early_close), policy()
    original = f.model_dump_json(), p.model_dump_json()

    def forbidden(*args, **kwargs):
        raise AssertionError("Preflight must not perform I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    result = preflight_scope(f, p, now=AT)
    assert result.status == "COVERAGE_COMPLETE" and result.blockers == ()
    assert result.authority is False and result.live_enabled is False
    assert (
        not {"quantity", "proposal", "admission", "candidate", "score"}
        & type(result).model_fields.keys()
    )
    assert (f.model_dump_json(), p.model_dump_json()) == original
    assert (
        preflight_scope(ScopePreflightInput.model_validate_json(original[0]), p, now=AT) == result
    )


@pytest.mark.parametrize("kind", SCOPE_GROUPS)
def test_each_missing_core_group_blocks(kind):
    f = frame()
    f = replace(f, "evidence", tuple(e for e in f.evidence if e.kind != kind))
    assert (kind, "MISSING_EVIDENCE") in codes(f)


@pytest.mark.parametrize("kind", SCOPE_GROUPS)
def test_each_duplicate_core_group_blocks_even_if_identical(kind):
    f = frame()
    f = replace(f, "evidence", f.evidence + (next(e for e in f.evidence if e.kind == kind),))
    assert (kind, "DUPLICATE_EVIDENCE") in codes(f)


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "foreign"},
        {"status": "UNAVAILABLE"},
        {"status": "UNKNOWN"},
        {"complete": False},
        {"entitlement": "UNKNOWN"},
        {"entitlement": "DELAYED"},
        {"entitlement": "INDICATIVE"},
        {"source_at": AT + timedelta(seconds=1)},
        {"received_at": AT + timedelta(seconds=1)},
        {"source_at": AT - timedelta(seconds=3)},
        {"source_at": AT - timedelta(seconds=30), "received_at": AT - timedelta(seconds=30)},
    ],
)
def test_unusable_core_evidence_does_not_get_defaults(changes):
    f = frame()
    f = replace(f, "evidence", (f.evidence[0].model_copy(update=changes), *f.evidence[1:]))
    assert (SCOPE_GROUPS[0], "EVIDENCE_BINDING_COVERAGE_OR_FRESHNESS") in codes(f)


@pytest.mark.parametrize("symbol", ["SPX", "SPY", "QQQ"])
@pytest.mark.parametrize("defect", ["missing", "duplicate", "gap", "future", "interpolated", "old"])
def test_all_three_markets_need_current_complete_history(symbol, defect):
    f = frame()
    h = next(h for h in f.histories if h.symbol == symbol)
    remaining = tuple(h for h in f.histories if h.symbol != symbol)
    expected = "COMPLETED_SESSION_HISTORY_REQUIRED"
    if defect == "missing":
        histories, expected = remaining, "MISSING_HISTORY"
    elif defect == "duplicate":
        histories, expected = (*f.histories, h), "DUPLICATE_HISTORY"
    else:
        if defect == "gap":
            h = replace(h, "bars", h.bars[:2] + h.bars[3:])
        elif defect == "future":
            h = replace(h, "bars", h.bars + (replace(h.bars[-1], "begins_at", AT),))
        elif defect == "interpolated":
            h = replace(h, "bars", (*h.bars[:-1], replace(h.bars[-1], "interpolated", True)))
        else:
            h = h.model_copy(
                update={
                    "source_at": AT - timedelta(seconds=11),
                    "received_at": AT - timedelta(seconds=11),
                }
            )
            expected = "HISTORY_BINDING_COVERAGE_OR_FRESHNESS"
        histories = (*remaining, h)
    assert (symbol, expected) in codes(replace(f, "histories", histories))


@pytest.mark.parametrize(
    "changes",
    [
        {"root": "SPX"},
        {"root": "SPY", "underlying": "SPY"},
        {"root": "SPXW", "underlying": "QQQ"},
        {"underlying_kind": "ETF"},
        {"underlying_market": "US_LISTED"},
        {"settlement_session": "AM"},
        {"exercise_style": "AMERICAN"},
        {"settlement": "PHYSICAL"},
        {"deliverable_kind": "SHARES", "deliverable_units": 100},
        {"multiplier": 10},
        {"adjusted": True},
        {"last_trading_at": AT},
        {"last_trading_at": AT + timedelta(minutes=1)},
        {"tick_below_three": D(".02")},
    ],
)
def test_exact_spxw_identity_and_protection_cutoff(changes):
    f = frame()
    c = f.metadata.instrument.contract.model_copy(update=changes)
    i = replace(f.metadata.instrument, "contract", c)
    f = f.model_copy(
        update={
            "metadata": replace(f.metadata, "instrument", i),
            "quote": replace(f.quote, "instrument", i),
        }
    )
    assert ("contract", "EXACT_SPXW_ZERO_DTE_IDENTITY_OR_CUTOFF") in codes(f)


def test_no_next_expiry_substitution():
    f = frame()
    c = f.metadata.instrument.contract
    next_day = c.model_copy(
        update={
            "expiration": c.expiration + timedelta(days=1),
            "last_trading_at": c.last_trading_at + timedelta(days=1),
            "expires_at": c.expires_at + timedelta(days=1),
            "settles_at": c.settles_at + timedelta(days=1),
        }
    )
    i = replace(f.metadata.instrument, "contract", next_day)
    f = f.model_copy(
        update={
            "metadata": replace(f.metadata, "instrument", i),
            "quote": replace(f.quote, "instrument", i),
        }
    )
    assert ("contract", "EXACT_SPXW_ZERO_DTE_IDENTITY_OR_CUTOFF") in codes(f)


@pytest.mark.parametrize(
    "changes", [{"provider": "foreign"}, {"metadata_complete": False}, {"option_tradable": False}]
)
def test_instrument_capability_must_be_explicit(changes):
    f = frame()
    i = f.metadata.instrument.model_copy(update=changes)
    assert ("contract", "EXACT_SPXW_ZERO_DTE_IDENTITY_OR_CUTOFF") in codes(
        replace(f, "metadata", replace(f.metadata, "instrument", i))
    )


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"bid": None}, "EXECUTABLE_TWO_SIDED_MARKET_REQUIRED"),
        ({"ask": None}, "EXECUTABLE_TWO_SIDED_MARKET_REQUIRED"),
        ({"bid": D(0)}, "EXECUTABLE_TWO_SIDED_MARKET_REQUIRED"),
        ({"bid": D(3)}, "EXECUTABLE_TWO_SIDED_MARKET_REQUIRED"),
        ({"bid_size": 0}, "EXECUTABLE_TWO_SIDED_MARKET_REQUIRED"),
        ({"ask_size": 0}, "EXECUTABLE_TWO_SIDED_MARKET_REQUIRED"),
        ({"ask": D("2.50")}, "SPREAD_EXCEEDS_FROZEN_BOUND"),
        ({"bid": D("1.96")}, "QUOTE_PRICE_OFF_CONTRACT_TICK"),
        ({"bid": D("3.05"), "ask": D("3.10")}, "QUOTE_PRICE_OFF_CONTRACT_TICK"),
        ({"source": "foreign"}, "QUOTE_BINDING_COVERAGE_OR_FRESHNESS"),
        ({"entitlement": "DELAYED"}, "QUOTE_BINDING_COVERAGE_OR_FRESHNESS"),
        ({"complete": False}, "QUOTE_BINDING_COVERAGE_OR_FRESHNESS"),
        ({"source_at": AT + timedelta(seconds=1)}, "QUOTE_BINDING_COVERAGE_OR_FRESHNESS"),
        (
            {"source_at": AT - timedelta(seconds=10), "received_at": AT - timedelta(seconds=10)},
            "QUOTE_BINDING_COVERAGE_OR_FRESHNESS",
        ),
    ],
)
def test_exact_quote_must_be_executable_and_current(changes, code):
    f = frame()
    assert ("quote", code) in codes(replace(f, "quote", f.quote.model_copy(update=changes)))


def test_quote_cannot_silently_change_mapping_or_contract():
    f = frame()
    i = replace(f.quote.instrument, "instrument_id", "replacement")
    assert ("quote", "EXACT_INSTRUMENT_MISMATCH") in codes(
        replace(f, "quote", replace(f.quote, "instrument", i))
    )


@pytest.mark.parametrize("right,delta", [("CALL", "-.2"), ("PUT", ".2"), ("CALL", "0")])
def test_delta_direction_is_consistent_without_degen_band(right, delta):
    f = frame(right=right)
    assert ("contract", "DELTA_DIRECTION_INCONSISTENT") in codes(
        replace(f, "metadata", replace(f.metadata, "delta", D(delta)))
    )


def test_missing_delta_and_liquidity_are_not_claimed_observed_or_used_as_zero():
    f = frame()
    f = replace(
        f,
        "metadata",
        f.metadata.model_copy(update={"delta": None, "greek_provenance": "UNAVAILABLE"}),
    )
    assert preflight_scope(f, policy(), now=AT).status == "COVERAGE_COMPLETE"
    assert (
        f.metadata.delta is None and f.metadata.volume is None and f.metadata.open_interest is None
    )


@pytest.mark.parametrize(
    "field,code",
    [
        ("session", "MISSING_INDEX_SESSION"),
        ("metadata", "MISSING_EXACT_SPXW_METADATA"),
        ("quote", "MISSING_EXACT_SPXW_QUOTE"),
    ],
)
def test_missing_exact_inputs_remain_blocked(field, code):
    assert any(c == code for _, c in codes(replace(frame(), field, None)))


@pytest.mark.parametrize("boundary", ["entry_cutoff_at", "protect_at", "closes_at"])
def test_session_cutoffs_are_exclusive(boundary):
    f = frame()
    assert ("session", "INDEX_SESSION_BINDING_OR_ENTRY_WINDOW") in codes(
        f, now=getattr(f.session, boundary)
    )


def test_clock_skew_is_separate_from_individual_freshness():
    f = frame(now=AT + timedelta(seconds=5))
    h = f.histories[1].model_copy(update={"source_at": AT, "received_at": AT})
    f = replace(f, "histories", (f.histories[0], h, f.histories[2]))
    assert codes(f, now=AT + timedelta(seconds=5)) == {
        ("markets", "SPX_CONFIRMATION_QUOTE_CLOCK_SKEW")
    }


def test_hashes_bind_full_inputs_and_policy_without_decimal_context_drift():
    f, p = frame(), policy()
    expected = preflight_scope(f, p, now=AT)
    changed = replace(
        f, "evidence", (replace(f.evidence[0], "payload_hash", "f" * 64), *f.evidence[1:])
    )
    assert preflight_scope(changed, p, now=AT).input_hash != expected.input_hash
    assert (
        preflight_scope(f, policy(max_spread_fraction=".16"), now=AT).policy_hash
        != expected.policy_hash
    )
    with localcontext() as ctx:
        ctx.prec = 2
        assert preflight_scope(f, p, now=AT) == expected


def test_revalidates_model_copy_and_requires_aware_clocks():
    f = frame()
    with pytest.raises(ValidationError):
        preflight_scope(replace(f, "quote", replace(f.quote, "ask", 2.0)), policy(), now=AT)
    with pytest.raises(ValueError, match="Aware"):
        preflight_scope(f, policy(), now=AT.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        policy(sources=(*policy().sources[:-1], policy().sources[0]))
    with pytest.raises(ValidationError):
        policy(history_sources=(policy().history_sources[0],) * 3)
    with pytest.raises(ValidationError):
        ScopeSession.model_validate(
            f.session.model_dump() | {"protect_at": f.session.entry_cutoff_at}
        )


@pytest.mark.parametrize("part", ["metadata", "history"])
@pytest.mark.parametrize(
    "change",
    [
        {"complete": False},
        {"entitlement": "DELAYED"},
        {"source": "unbound-source"},
        {"received_at": AT + timedelta(seconds=1)},
    ],
)
def test_current_metadata_and_history_are_independently_required(part, change):
    f = frame()
    if part == "metadata":
        f = replace(f, "metadata", f.metadata.model_copy(update=change))
        expected = ("contract", "METADATA_BINDING_COVERAGE_OR_FRESHNESS")
    else:
        h = f.histories[0].model_copy(update=change)
        f = replace(f, "histories", (h, *f.histories[1:]))
        expected = ("SPX", "HISTORY_BINDING_COVERAGE_OR_FRESHNESS")
    assert expected in codes(f)


def test_session_source_and_open_are_not_inferred_from_a_weekday():
    f = frame()
    assert ("session", "INDEX_SESSION_BINDING_OR_ENTRY_WINDOW") in codes(
        replace(f, "session", replace(f.session, "source", "unbound"))
    )
    assert ("session", "INDEX_SESSION_BINDING_OR_ENTRY_WINDOW") in codes(
        f, now=f.session.entry_starts_at - timedelta(microseconds=1)
    )
    assert ("session", "INDEX_SESSION_BINDING_OR_ENTRY_WINDOW") in codes(
        f, now=AT + timedelta(days=1)
    )


def test_new_york_session_identity_survives_utc_offset_serialization():
    from zoneinfo import ZoneInfo

    f = frame()
    ny_now = AT.astimezone(ZoneInfo("America/New_York"))
    assert preflight_scope(f, policy(), now=ny_now) == preflight_scope(f, policy(), now=AT)
