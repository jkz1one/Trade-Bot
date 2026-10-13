"""Scope completed structure is deterministic evidence, never account authority."""

from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope import frame as preflight_frame
from test_option_scope import policy as preflight_policy

from app.options.degen import DegenBar
from app.options.scope_structure import (
    PATTERNS,
    ScopeStructurePolicy,
    scan_scope_structure,
    structure_payload_hashes,
)

D = Decimal
CLOSES = {
    "opening_range_break_hold": ("100", "100.1", "100", "100.2", "100.4", "100.6"),
    "vwap_reclaim_continuation": ("100", "100", "100", "99", "101", "102"),
    "trend_pullback_continuation": ("100", "100.1", "100", "100.2", "100.4", "100.6"),
    "compression_expansion": ("100", "100", "100", "100", "100", "101"),
    "failed_reversal_continuation": ("100", "100", "102", "99", "101", "103"),
    "failed_break_reversal": ("100", "100", "100", "98", "101", "102"),
    "opening_drive_failure": ("100", "100", "100", "100", "101", "102"),
    "vwap_rejection_reversal": ("100", "100", "100", "100", "100", "101"),
    "trap_reversal": ("100", "100", "100", "98", "101", "102"),
}


def policy(**changes):
    return ScopeStructurePolicy.model_validate(
        {
            "preflight": preflight_policy(),
            "first_target_r": "1.5",
            "second_target_r": "2.5",
            "pullback_touch_points": "1",
            "pullback_touch_fraction": ".0012",
            "compression_fraction": ".35",
            "confirmation_fraction": ".0002",
            "conflict_fraction": ".0005",
        }
        | changes
    )


def bind(f):
    hashes = structure_payload_hashes(f)
    return f.model_copy(
        update={
            "evidence": tuple(
                e.model_copy(update={"payload_hash": hashes[e.kind]}) if e.kind in hashes else e
                for e in f.evidence
            )
        }
    )


def frame(pattern="opening_range_break_hold", right="CALL", *, count=6):
    now = AT - timedelta(minutes=5 * (6 - count))
    f = preflight_frame(now=now, right=right)
    histories = []
    for h in f.histories:
        bars = []
        for n in range(count):
            close = (
                D(CLOSES[pattern][n]) if h.symbol == "SPX" else D(101 if n == count - 1 else 100)
            )
            o, high, low = close - D(".1"), close + D(".2"), close - D(".2")
            if h.symbol != "SPX":
                o = D(100) if n == 0 else close
            if h.symbol == "SPX" and pattern == "compression_expansion" and n == 0:
                high, low = D(105), D(95)
            if h.symbol == "SPX" and pattern == "vwap_rejection_reversal" and n == 5:
                o, low = D("100.5"), D(99)
            if right == "PUT":
                o, high, low, close = 200 - o, 200 - low, 200 - high, 200 - close
            bars.append(
                DegenBar(
                    begins_at=f.session.opens_at + timedelta(minutes=5 * n),
                    open=o,
                    high=high,
                    low=low,
                    close=close,
                    volume=100,
                    interpolated=False,
                )
            )
        histories.append(h.model_copy(update={"bars": tuple(bars)}))
    instrument = f.metadata.instrument.model_copy(
        update={"contract": f.metadata.instrument.contract.model_copy(update={"strike": D(100)})}
    )
    return bind(
        f.model_copy(
            update={
                "histories": tuple(histories),
                "metadata": f.metadata.model_copy(update={"instrument": instrument}),
                "quote": f.quote.model_copy(update={"instrument": instrument}),
            }
        )
    )


def observe(f, pattern="opening_range_break_hold", right="CALL", *, p=None, now=AT):
    scan = scan_scope_structure(f, p or policy(), now=now)
    assert not scan.issues, scan.issues
    return next(o for o in scan.observations if o.pattern == pattern and o.right == right)


@pytest.mark.parametrize("pattern", PATTERNS)
@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_nine_patterns_in_both_directions(pattern, right):
    f = frame(pattern, right)
    scan = scan_scope_structure(f, policy(), now=AT)
    assert scan.issues == () and len(scan.observations) == 18
    item = observe(f, pattern, right)
    assert item.status == "DETECTED" and item.reasons == ()
    g = item.geometry
    sign = 1 if right == "CALL" else -1
    assert g.invalidation * sign < g.reference * sign < g.target_one * sign < g.target_two * sign
    assert scan.authority is False and scan.live_enabled is False
    assert (
        not {"proposal", "admission", "quantity", "score", "probability"}
        & type(scan).model_fields.keys()
    )


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_opening_range_geometry_and_cross_market_fraction(right):
    scan = scan_scope_structure(frame(right=right), policy(), now=AT)
    g = observe(frame(right=right), right=right).geometry
    assert g.reference == (D("100.3") if right == "CALL" else D("99.7"))
    assert g.invalidation == D(100)
    assert g.target_one == (D("100.75") if right == "CALL" else D("99.25"))
    assert g.target_two == (D("101.05") if right == "CALL" else D("98.95"))
    assert (
        scan.changes["SPY"] == scan.changes["QQQ"] == (D(".01") if right == "CALL" else D("-.01"))
    )
    assert scan.completed_through == AT.replace(second=0)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_failed_break_needs_separate_neutral_and_followthrough_bars(right):
    early = frame("failed_break_reversal", right, count=5)
    now = AT - timedelta(minutes=5)
    initial = observe(early, "failed_break_reversal", right, now=now)
    assert initial.status == "BLOCKED"
    assert "NEUTRAL_RESET_REQUIRES_FRESH_COMPLETED_CONFIRMATION" in initial.reasons
    assert observe(early, "trap_reversal", right, now=now).status == "WATCHING"
    later = frame("failed_break_reversal", right)
    for pattern in ("failed_break_reversal", "trap_reversal"):
        assert observe(later, pattern, right).status == "DETECTED"
    assert scan_scope_structure(later, policy(), now=now).issues == ("SCOPE_PREFLIGHT_BLOCKED",)


def confirmation_frame(spy, qqq, *, right="CALL"):
    f = frame(right=right)
    histories = [f.histories[0]]
    for h, change in zip(f.histories[1:], (spy, qqq)):
        last = D(100) * (1 + D(change))
        b = h.bars[-1].model_copy(update={"open": last, "high": last, "low": last, "close": last})
        histories.append(h.model_copy(update={"bars": (*h.bars[:-1], b)}))
    return bind(f.model_copy(update={"histories": tuple(histories)}))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "spy,qqq,status,reason",
    [
        (".0003", "0", "DETECTED", None),
        ("0", ".0003", "DETECTED", None),
        (".0002", "0", "BLOCKED", "SPY_OR_QQQ_DIRECTIONAL_CONFIRMATION_REQUIRED"),
        ("0", "0", "BLOCKED", "SPY_OR_QQQ_DIRECTIONAL_CONFIRMATION_REQUIRED"),
        (".0003", "-.0005", "DETECTED", None),
        (".0003", "-.00050001", "BLOCKED", "CONFIRMATION_MARKET_MATERIALLY_CONFLICTS"),
    ],
)
def test_confirmation_thresholds_are_directional_and_exact(right, spy, qqq, status, reason):
    sign = D(1) if right == "CALL" else D(-1)
    f = confirmation_frame(D(spy) * sign, D(qqq) * sign, right=right)
    result = observe(f, right=right)
    assert result.status == status
    if reason:
        assert reason in result.reasons


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("distance", ["0", ".000000000001"])
def test_exact_strike_at_second_objective_or_beyond(right, distance):
    f = frame(right=right)
    objective = observe(f, right=right).geometry.target_two
    strike = objective + (1 if right == "CALL" else -1) * D(distance)
    c = f.metadata.instrument.contract.model_copy(update={"strike": strike})
    i = f.metadata.instrument.model_copy(update={"contract": c})
    f = f.model_copy(
        update={
            "metadata": f.metadata.model_copy(update={"instrument": i}),
            "quote": f.quote.model_copy(update={"instrument": i}),
        }
    )
    observation = observe(f, right=right)
    assert observation.status == ("DETECTED" if D(distance) == 0 else "BLOCKED")
    if D(distance):
        assert "EXACT_STRIKE_BEYOND_SECOND_OBJECTIVE" in observation.reasons


@pytest.mark.parametrize("kind", ["technical_structure", "cross_market_agreement"])
def test_attestation_hash_cannot_substitute_unrelated_semantic_payload(kind):
    f = frame()
    f = f.model_copy(
        update={
            "evidence": tuple(
                e.model_copy(update={"payload_hash": "f" * 64}) if e.kind == kind else e
                for e in f.evidence
            )
        }
    )
    scan = scan_scope_structure(f, policy(), now=AT)
    assert scan.observations == ()
    assert kind.upper() + "_PAYLOAD_MISMATCH" in scan.issues


@pytest.mark.parametrize("kind", ["technical_structure", "cross_market_agreement"])
def test_bound_payload_must_be_known_at_attestation_receipt(kind):
    f = frame()
    earlier = AT - timedelta(seconds=1)
    f = f.model_copy(
        update={
            "evidence": tuple(
                e.model_copy(update={"source_at": earlier, "received_at": earlier})
                if e.kind == kind
                else e
                for e in f.evidence
            )
        }
    )
    assert (
        kind.upper() + "_PAYLOAD_NOT_YET_KNOWN" in scan_scope_structure(f, policy(), now=AT).issues
    )


@pytest.mark.parametrize(
    "defect", ["zero_volume", "partial_volume", "four_bars", "missing_context"]
)
def test_unavailable_input_never_becomes_a_pattern(defect):
    count = 4 if defect == "four_bars" else 6
    f = frame(count=count)
    now = AT - timedelta(minutes=5 * (6 - count))
    if "volume" in defect:
        h = f.histories[0]
        bars = tuple(
            b.model_copy(update={"volume": 0}) if defect == "zero_volume" or n == 2 else b
            for n, b in enumerate(h.bars)
        )
        f = bind(
            f.model_copy(
                update={"histories": (h.model_copy(update={"bars": bars}), *f.histories[1:])}
            )
        )
    elif defect == "missing_context":
        f = f.model_copy(
            update={"evidence": tuple(e for e in f.evidence if e.kind != "options_flow")}
        )
    scan = scan_scope_structure(f, policy(), now=now)
    assert scan.issues and not scan.observations
    expected = (
        "COMPLETE_VOLUME_BACKED_SPX_VWAP_REQUIRED"
        if "volume" in defect
        else "FIVE_COMPLETED_SPX_BARS_REQUIRED"
        if count == 4
        else "SCOPE_PREFLIGHT_BLOCKED"
    )
    assert expected in scan.issues


def test_changed_completed_history_needs_new_payload_binding():
    f = frame()
    h = f.histories[0]
    b = h.bars[0].model_copy(update={"volume": 101})
    f = f.model_copy(
        update={"histories": (h.model_copy(update={"bars": (b, *h.bars[1:])}), *f.histories[1:])}
    )
    assert set(scan_scope_structure(f, policy(), now=AT).issues) == {
        "TECHNICAL_STRUCTURE_PAYLOAD_MISMATCH",
        "CROSS_MARKET_AGREEMENT_PAYLOAD_MISMATCH",
    }


def test_future_interpolated_or_gapped_history_stops_before_semantic_work():
    f = frame()
    for bars in (
        f.histories[0].bars[:-1],
        (
            *f.histories[0].bars[:-1],
            f.histories[0].bars[-1].model_copy(update={"interpolated": True}),
        ),
    ):
        h = f.histories[0].model_copy(update={"bars": bars})
        invalid = bind(f.model_copy(update={"histories": (h, *f.histories[1:])}))
        scan = scan_scope_structure(invalid, policy(), now=AT)
        assert scan.issues == ("SCOPE_PREFLIGHT_BLOCKED",) and not scan.observations


def test_frozen_hashes_and_decimal_context_and_no_io(monkeypatch):
    import builtins
    import socket
    import sqlite3

    f, p = frame(), policy()
    original = f.model_dump_json(), p.model_dump_json()
    expected = scan_scope_structure(f, p, now=AT)

    def forbidden(*args, **kwargs):
        raise AssertionError("No I/O in structure scan")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    with localcontext() as ctx:
        ctx.prec = 2
        assert scan_scope_structure(f, p, now=AT) == expected
    assert (f.model_dump_json(), p.model_dump_json()) == original
    assert (
        scan_scope_structure(f, policy(first_target_r="1.6"), now=AT).policy_hash
        != expected.policy_hash
    )


def test_malformed_copied_inputs_and_unordered_policy_raise():
    f = frame()
    with pytest.raises(ValueError, match="Aware"):
        scan_scope_structure(f, policy(), now=AT.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        scan_scope_structure(f, policy().model_copy(update={"first_target_r": 1.5}), now=AT)
    with pytest.raises(ValidationError):
        policy(second_target_r="1.5")
    with pytest.raises(ValidationError):
        policy(confirmation_fraction=".0005")
    with pytest.raises(ValueError, match="Exactly one"):
        structure_payload_hashes(f.model_copy(update={"histories": f.histories[:2]}))


def test_flat_completed_structure_keeps_every_pattern_watching():
    f = frame()
    h = f.histories[0]
    bars = tuple(
        b.model_copy(update={"open": D(100), "high": D(100), "low": D(100), "close": D(100)})
        for b in h.bars
    )
    f = bind(
        f.model_copy(update={"histories": (h.model_copy(update={"bars": bars}), *f.histories[1:])})
    )
    scan = scan_scope_structure(f, policy(), now=AT)
    assert not scan.issues and len(scan.observations) == 18
    assert all(o.status == "WATCHING" and o.geometry is None for o in scan.observations)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_consumed_objective_cannot_be_reused_as_a_fresh_path(right):
    f = frame(right=right)
    h = f.histories[0]
    last = D(103 if right == "CALL" else 97)
    b = h.bars[-1].model_copy(
        update={"open": last, "close": last, "high": last + 1, "low": last - 1}
    )
    f = bind(
        f.model_copy(
            update={
                "histories": (h.model_copy(update={"bars": (*h.bars[:-1], b)}), *f.histories[1:])
            }
        )
    )
    item = observe(f, right=right)
    assert item.status == "BLOCKED" and "STRUCTURAL_OBJECTIVES_ALREADY_CONSUMED" in item.reasons


def test_contract_right_is_not_silently_replaced_for_detected_structure():
    f = frame()
    c = f.metadata.instrument.contract.model_copy(update={"right": "PUT"})
    i = f.metadata.instrument.model_copy(update={"contract": c})
    f = f.model_copy(
        update={
            "metadata": f.metadata.model_copy(update={"instrument": i, "delta": D("-.99")}),
            "quote": f.quote.model_copy(update={"instrument": i}),
        }
    )
    item = observe(f)
    assert item.status == "BLOCKED" and "EXACT_CONTRACT_RIGHT_MISMATCH" in item.reasons


def test_invalid_structural_risk_cannot_create_geometry():
    f = frame()
    h = f.histories[0]
    bars = []
    for n, b in enumerate(h.bars):
        close = D((100, 100, 100, 105, 106, 107)[n])
        bars.append(
            b.model_copy(
                update={
                    "open": close,
                    "high": close + D(".2"),
                    "low": close - D(".2"),
                    "close": close,
                }
            )
        )
    f = bind(
        f.model_copy(
            update={"histories": (h.model_copy(update={"bars": tuple(bars)}), *f.histories[1:])}
        )
    )
    item = observe(f)
    assert item.status == "BLOCKED" and item.geometry is None
    assert "INVALID_STRUCTURAL_RISK" in item.reasons


def test_unrepresentable_derived_geometry_is_an_explicit_blocker():
    f = frame()
    h = f.histories[0]
    scale = D("100000000000000000000")
    bars = tuple(
        b.model_copy(
            update={key: getattr(b, key) * scale for key in ("open", "high", "low", "close")}
        )
        for b in h.bars
    )
    f = bind(
        f.model_copy(update={"histories": (h.model_copy(update={"bars": bars}), *f.histories[1:])})
    )
    scan = scan_scope_structure(f, policy(), now=AT)
    assert scan.issues == ("STRUCTURE_NUMERIC_RANGE",) and not scan.observations
